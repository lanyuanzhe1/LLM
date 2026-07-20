# ingest_knowledge.py
"""Project-scoped knowledge ingestion CLI.

Usage:
  python ingest_knowledge.py --scope base
  python ingest_knowledge.py --project-id demo
  python ingest_knowledge.py --project-id demo --source /path/to/file.pdf
  python ingest_knowledge.py --scope all-projects
"""

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass as _dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.ingest.reader import SUPPORTED_EXTENSIONS, read_file
from app.ingest.scanner import (
    ScannedDocument,
    scan_base,
    scan_project,
    validate_project_id,
)
from app.ingest.manifest import (
    Manifest,
    ManifestConfig,
    DocumentEntry,
    find_reusable,
    load_manifest,
    save_manifest,
)
from app.ingest.builder import (
    build_index_from_chunks,
    save_artifacts,
    publish_store,
)

# ---- Configuration (overridable via env) ----
DOC_DIR = Path(os.environ.get("KNOWLEDGE_DIR", "./knowledge"))
OUTPUT_BASE_DIR = Path(os.environ.get("VECTOR_STORE_DIR", "./vector_store"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "100"))
PARSER_VERSION = os.environ.get("PARSER_VERSION", "2026-07-20")
SLEEP_INTERVAL = float(os.environ.get("INGEST_SLEEP_INTERVAL", "0.3"))


# ---- Text cleaning (from build_vector_store.py) ----

def clean_text(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"([，。！？；：、])\s+", r"\1", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text.strip()


# ---- Chunking (from build_vector_store.py) ----


@_dataclass(frozen=True)
class _TextSegment:
    start: int
    end: int


_SEGMENT_BOUNDARY_PATTERN = re.compile(
    r"\n{2,}|[。！？!?]+|(?<!\d)\.(?!\d)"
)


def _offset_segments(text: str) -> list[_TextSegment]:
    segments: list[_TextSegment] = []
    cursor = 0
    for match in _SEGMENT_BOUNDARY_PATTERN.finditer(text):
        boundary = match.end()
        if boundary > cursor:
            segments.append(_TextSegment(start=cursor, end=boundary))
            cursor = boundary
    if cursor < len(text):
        segments.append(_TextSegment(start=cursor, end=len(text)))
    return segments


def chunk_text(
    text: str,
    source_file: str,
    chunk_size: int = 600,
    overlap: int = 100,
    *,
    document_checksum: str | None = None,
    source_type: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be 0 <= overlap < chunk_size")
    if not text:
        return []

    segments = _offset_segments(text)
    preferred_ends = tuple(seg.end for seg in segments)
    chunks: list[dict] = []
    start = 0
    previous_end = 0
    while start < len(text):
        hard_end = min(start + chunk_size, len(text))
        semantic_ends = [
            end for end in preferred_ends
            if previous_end < end <= hard_end
        ]
        end = max(semantic_ends) if semantic_ends else hard_end
        if end <= previous_end or end <= start:
            end = hard_end
        chunk_value = text[start:end]
        meta = {
            "text": chunk_value,
            "source": source_file,
            "start_pos": start,
            "char_count": len(chunk_value),
        }
        if document_checksum is not None:
            meta["document_checksum"] = document_checksum
        if source_type is not None:
            meta["source_type"] = source_type
        if scope is not None:
            meta["scope"] = scope
        if project_id is not None:
            meta["project_id"] = project_id
        chunks.append(meta)
        if end == len(text):
            break
        previous_end = end
        start = end - overlap
    return chunks


# ---- Pipeline orchestration ----

def _output_dir(scope: str, project_id: str | None = None) -> Path:
    if scope == "base":
        return OUTPUT_BASE_DIR / "base"
    if scope == "project" and project_id:
        return OUTPUT_BASE_DIR / "projects" / project_id
    raise ValueError(f"unknown scope: {scope}")


def _manifest_config() -> ManifestConfig:
    return ManifestConfig(
        parser_version=PARSER_VERSION,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        embedding_provider="iflytek",
        embedding_url="https://emb-cn-huabei-1.xf-yun.com/",
        embedding_dimension=2560,
    )


def _embed_batch(
    chunks: list[dict],
    client: IflytekEmbeddingClient,
) -> list[dict]:
    """Embed all chunks synchronously via the async client."""
    import time as _time

    async def _embed_all():
        for i, c in enumerate(chunks):
            vec = await client.embed(c["text"], domain="para")
            c["embedding"] = vec
            if (i + 1) % 50 == 0:
                _time.sleep(0.5)

    asyncio.run(_embed_all())
    return chunks


def _collect_preexisting_chunks(
    manifest: Manifest,
    reusable_paths: list[str],
    store_dir: Path,
) -> list[dict]:
    """Load previously embedded chunks for reusable documents."""
    import numpy as np

    vectors_path = store_dir / "vectors.npy"
    metadata_path = store_dir / "chunks_metadata.json"

    if not vectors_path.is_file() or not metadata_path.is_file():
        return []

    all_vectors = np.load(vectors_path, allow_pickle=False)
    all_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    reusable_set = set(reusable_paths)
    reused: list[dict] = []
    for i, meta in enumerate(all_metadata):
        if meta.get("source") in reusable_set:
            chunk = dict(meta)
            chunk["embedding"] = all_vectors[i].copy()
            reused.append(chunk)

    return reused


def run_ingestion(
    *,
    scope: str,
    project_id: str | None = None,
    source_file: str | None = None,
) -> dict:
    """Run the full ingestion pipeline. Returns an ingest_report dict."""

    # Validate
    if scope not in ("base", "project", "all-projects"):
        raise ValueError(f"unknown scope: {scope}")

    app_id = os.environ.get("XF_APP_ID", "")
    api_key = os.environ.get("XF_EMBEDDING_API_KEY", "")
    api_secret = os.environ.get("XF_EMBEDDING_API_SECRET", "")
    if not app_id or not api_key or not api_secret:
        print("[ERROR] Missing iFlytek credentials in environment")
        sys.exit(1)

    started = datetime.now(timezone.utc)
    report = {
        "scope": scope,
        "project_id": project_id,
        "started": started.isoformat(),
        "files_scanned": 0,
        "files_indexed": 0,
        "files_reused": 0,
        "files_replaced": 0,
        "files_deleted": 0,
        "files_skipped": 0,
        "files_failed": 0,
        "chunks_embedded": 0,
        "chunks_reused": 0,
        "published_path": "",
        "warnings": [],
    }

    # Handle --source copy
    if source_file:
        if scope != "project" or not project_id:
            print("[ERROR] --source requires --project-id")
            sys.exit(1)
        src = Path(source_file).resolve()
        if not src.is_file():
            print(f"[ERROR] source file not found: {source_file}")
            sys.exit(1)
        ext = src.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            print(f"[ERROR] unsupported file type: {ext}")
            sys.exit(1)
        dest_dir = DOC_DIR / "projects" / project_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        print(f"  Copied {src.name} -> {dest}")

    # Resolve scope to a list of (scope, project_id) jobs
    if scope == "all-projects":
        projects_root = DOC_DIR / "projects"
        if not projects_root.is_dir():
            print("[WARNING] No projects directory found")
            report["projects_processed"] = 0
            return report
        jobs = [
            ("project", d.name)
            for d in sorted(projects_root.iterdir())
            if d.is_dir() and not d.name.startswith(".")
        ]
        report["projects_processed"] = len(jobs)
    else:
        jobs = [(scope, project_id)]

    for job_scope, job_project_id in jobs:
        _ingest_one_scope(job_scope, job_project_id, report)

    # Finalize
    completed = datetime.now(timezone.utc)
    report["completed"] = completed.isoformat()

    # Write report
    if scope != "all-projects":
        out_dir = _output_dir(scope, project_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "ingest_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return report


def _ingest_one_scope(
    scope: str,
    project_id: str | None,
    report: dict,
) -> None:
    """Ingest a single scope (base or one project)."""

    # Scan
    if scope == "base":
        scanned = list(scan_base(DOC_DIR))
        source_root = str(DOC_DIR)
        doc_root = DOC_DIR
    else:
        scanned = list(scan_project(DOC_DIR, project_id))
        source_root = str(DOC_DIR / "projects" / project_id)
        doc_root = DOC_DIR / "projects" / project_id

    report["files_scanned"] += len(scanned)
    if not scanned:
        print(f"[WARNING] No supported files found for scope={scope}")
        return

    # Separate supported vs unsupported
    current_docs: dict[str, ScannedDocument] = {}
    for doc in scanned:
        current_docs[doc.path] = doc

    # Read text
    docs_with_text: list[tuple[ScannedDocument, str]] = []
    for doc in scanned:
        full_path = doc_root / doc.path
        text = read_file(full_path)
        if text.strip():
            docs_with_text.append((doc, text))
        else:
            report["files_skipped"] += 1

    if not docs_with_text:
        print(f"[ERROR] All {len(scanned)} files produced empty text")
        sys.exit(1)

    # Check manifest for incremental reuse
    out_dir = _output_dir(scope, project_id)
    manifest = load_manifest(out_dir)
    config = _manifest_config()

    reusable_paths: list[str] = []
    new_changed_paths: list[str] = []
    if manifest is not None:
        reusable_paths, new_changed_paths = find_reusable(
            manifest, current_docs, config
        )

    # Separate docs into reusable vs new
    reusable_set = set(reusable_paths)
    new_docs = [
        (doc, text)
        for doc, text in docs_with_text
        if doc.path not in reusable_set
    ]

    # Load preexisting chunks
    preexisting = _collect_preexisting_chunks(
        manifest, reusable_paths, out_dir
    ) if manifest else []

    for chunk in preexisting:
        chunk["scope"] = scope
        if project_id is not None:
            chunk["project_id"] = project_id
    report["files_reused"] += len(reusable_paths)
    report["chunks_reused"] += len(preexisting)

    # Chunk new documents
    new_chunks: list[dict] = []
    for doc, text in new_docs:
        cleaned = clean_text(text)
        chunks = chunk_text(
            cleaned,
            doc.path,
            CHUNK_SIZE,
            CHUNK_OVERLAP,
            document_checksum=doc.sha256,
            source_type=doc.source_type,
            scope=scope,
            project_id=project_id,
        )
        new_chunks.extend(chunks)

    # Embed new chunks
    if new_chunks:
        client = IflytekEmbeddingClient(
            app_id=os.environ["XF_APP_ID"],
            api_key=os.environ["XF_EMBEDDING_API_KEY"],
            api_secret=os.environ["XF_EMBEDDING_API_SECRET"],
            url="https://emb-cn-huabei-1.xf-yun.com/",
            timeout_seconds=30.0,
        )
        try:
            new_chunks = _embed_batch(new_chunks, client)
        except Exception as e:
            print(f"[ERROR] Embedding failed: {e}")
            sys.exit(1)
        finally:
            asyncio.run(client.close())

    report["files_indexed"] += len(new_docs)
    report["chunks_embedded"] += len(new_chunks)

    # Merge reused + new
    all_chunks = preexisting + new_chunks
    if not all_chunks:
        print("[ERROR] No chunks to publish")
        sys.exit(1)

    # Build index + save + publish
    nbrs = build_index_from_chunks(all_chunks)
    staging = out_dir.parent / f".{out_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        save_artifacts(nbrs, all_chunks, staging)
        # Write manifest
        new_manifest = Manifest(
            schema_version=1,
            scope=scope,
            project_id=project_id,
            source_root=source_root,
            parser_version=PARSER_VERSION,
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            documents={
                doc.path: DocumentEntry(
                    sha256=doc.sha256,
                    mtime_ns=doc.mtime_ns,
                    size_bytes=doc.size_bytes,
                    status="indexed",
                    chunk_count=sum(
                        1 for c in all_chunks if c["source"] == doc.path
                    ),
                )
                for doc, _ in docs_with_text
            },
        )
        save_manifest(new_manifest, staging)
        publish_store(staging, out_dir)
        report["published_path"] = str(out_dir)
        print(f"  Published: {out_dir} ({len(all_chunks)} chunks)")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


# ---- CLI ----

def main():
    parser = argparse.ArgumentParser(
        description="Grain Storage Knowledge Ingestion"
    )
    parser.add_argument(
        "--project-id",
        help="Target project ID",
        default=None,
    )
    parser.add_argument(
        "--scope",
        choices=["base", "all-projects"],
        default=None,
        help="Ingestion scope (default: inferred from --project-id)",
    )
    parser.add_argument(
        "--source",
        help="Copy this file into the project before ingestion",
        default=None,
    )

    args = parser.parse_args()

    # Resolve scope
    if args.scope:
        scope = args.scope
    elif args.project_id:
        scope = "project"
    else:
        scope = "base"

    if scope == "project" and not args.project_id:
        parser.error("--project-id is required for project scope")

    if args.project_id:
        validate_project_id(args.project_id)

    report = run_ingestion(
        scope=scope,
        project_id=args.project_id,
        source_file=args.source,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
