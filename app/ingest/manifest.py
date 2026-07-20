"""Manifest — incremental state tracking for document ingestion.

Tracks document hashes and embedding configuration so unchanged files
can reuse their cached embeddings across pipeline runs.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.ingest.scanner import ScannedDocument


@dataclass
class DocumentEntry:
    """A single document's cached state in the manifest."""

    sha256: str
    mtime_ns: int
    size_bytes: int
    status: str = "indexed"
    chunk_count: int = 0


@dataclass
class Manifest:
    """Top-level manifest tracking the full ingestion state."""

    schema_version: int = 1
    scope: str = "base"
    project_id: str | None = None
    source_root: str = ""
    embedding_dimension: int = 2560
    embedding_provider: str = "iflytek"
    embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com/"
    chunk_size: int = 600
    chunk_overlap: int = 100
    parser_version: str = ""
    documents: dict[str, DocumentEntry] = field(default_factory=dict)


@dataclass
class ManifestConfig:
    """Immutable configuration snapshot used to decide cache-reuse eligibility."""

    parser_version: str
    chunk_size: int
    chunk_overlap: int
    embedding_provider: str
    embedding_url: str
    embedding_dimension: int


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_manifest(store_dir: Path) -> Manifest | None:
    """Read and parse manifest.json from *store_dir*, or return None."""
    path = store_dir / "manifest.json"
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    docs_raw = data.get("documents", {})
    documents: dict[str, DocumentEntry] = {}
    if isinstance(docs_raw, dict):
        for name, entry in docs_raw.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            documents[name] = DocumentEntry(
                sha256=str(entry.get("sha256", "")),
                mtime_ns=int(entry.get("mtime_ns", 0)),
                size_bytes=int(entry.get("size_bytes", 0)),
                status=str(entry.get("status", "indexed")),
                chunk_count=int(entry.get("chunk_count", 0)),
            )

    return Manifest(
        schema_version=int(data.get("schema_version", 1)),
        scope=str(data.get("scope", "base")),
        project_id=data.get("project_id"),
        source_root=str(data.get("source_root", "")),
        embedding_dimension=int(data.get("embedding_dimension", 2560)),
        embedding_provider=str(data.get("embedding_provider", "iflytek")),
        embedding_url=str(data.get("embedding_url", "")),
        chunk_size=int(data.get("chunk_size", 600)),
        chunk_overlap=int(data.get("chunk_overlap", 100)),
        parser_version=str(data.get("parser_version", "")),
        documents=documents,
    )


def save_manifest(manifest: Manifest, store_dir: Path) -> None:
    """Serialise *manifest* to manifest.json inside *store_dir*."""
    store_dir.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "schema_version": manifest.schema_version,
        "scope": manifest.scope,
        "project_id": manifest.project_id,
        "source_root": manifest.source_root,
        "embedding_dimension": manifest.embedding_dimension,
        "embedding_provider": manifest.embedding_provider,
        "embedding_url": manifest.embedding_url,
        "chunk_size": manifest.chunk_size,
        "chunk_overlap": manifest.chunk_overlap,
        "parser_version": manifest.parser_version,
        "documents": {
            name: {
                "sha256": entry.sha256,
                "mtime_ns": entry.mtime_ns,
                "size_bytes": entry.size_bytes,
                "status": entry.status,
                "chunk_count": entry.chunk_count,
            }
            for name, entry in manifest.documents.items()
        },
    }
    (store_dir / "manifest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Reuse logic
# ---------------------------------------------------------------------------


def find_reusable(
    manifest: Manifest,
    current_docs: dict[str, ScannedDocument],
    config: ManifestConfig,
) -> tuple[list[str], list[str]]:
    """Compare current documents against cached manifest state.

    Returns (reusable_paths, new_or_changed_paths).

    A document is reusable when ALL of the following hold:
      - The embedding/chunking config matches the last run exactly.
      - The content hash (sha256) has not changed.
      - The manifest entry status is ``"indexed"``.

    Documents that appear in *current_docs* but not in the manifest, or
    whose hash or config has changed, are placed in *new_or_changed*.
    Documents in the manifest that have been deleted from the filesystem
    are silently omitted from both lists.
    """
    config_match = (
        manifest.parser_version == config.parser_version
        and manifest.chunk_size == config.chunk_size
        and manifest.chunk_overlap == config.chunk_overlap
        and manifest.embedding_provider == config.embedding_provider
        and manifest.embedding_url == config.embedding_url
        and manifest.embedding_dimension == config.embedding_dimension
    )

    reusable: list[str] = []
    new_or_changed: list[str] = []

    for path, doc in current_docs.items():
        entry = manifest.documents.get(path)
        if (
            config_match
            and entry is not None
            and entry.sha256 == doc.sha256
            and entry.status == "indexed"
        ):
            reusable.append(path)
        else:
            new_or_changed.append(path)

    return reusable, new_or_changed
