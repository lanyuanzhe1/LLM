"""Prepare and publish the base knowledge corpus to iFlytek ChatDoc."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

CHATDOC_MAX_FILE_BYTES = 20 * 1024 * 1024
CHATDOC_SUPPORTED_EXTENSIONS = frozenset(
    {".pdf", ".docx", ".txt", ".md", ".ppt", ".pptx"}
)


class ChatDocIngestClient(Protocol):
    async def create_repo(self, name: str, description: str = "") -> str: ...
    async def upload_file(self, path: Path, *, upload_name: str | None = None) -> str: ...
    async def wait_until_vectored(self, file_ids: list[str], **kwargs) -> dict[str, str]: ...
    async def add_files(self, repo_id: str, file_ids: list[str]) -> None: ...


@dataclass(frozen=True)
class PreparedUpload:
    source: str
    path: Path
    upload_name: str
    source_type: str | None
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class IngestResult:
    repo_id: str
    repo_name: str
    uploaded_files: int
    skipped_files: int
    artifact_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _upload_name(source: str) -> str:
    return source.replace("/", "__")


def prepare_uploads(
    source_root: Path,
    *,
    max_file_bytes: int = CHATDOC_MAX_FILE_BYTES,
) -> tuple[list[PreparedUpload], list[dict[str, Any]]]:
    root = Path(source_root).resolve(strict=True)
    prepared: list[PreparedUpload] = []
    skipped: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.name.startswith((".", "~")):
            continue
        if path.suffix.lower() not in CHATDOC_SUPPORTED_EXTENSIONS:
            continue
        resolved = path.resolve(strict=True)
        try:
            source = resolved.relative_to(root).as_posix()
        except ValueError:
            continue
        size_bytes = resolved.stat().st_size
        if size_bytes > max_file_bytes:
            skipped.append(
                {
                    "source": source,
                    "reason": "oversized",
                    "size_bytes": size_bytes,
                }
            )
            continue
        parts = source.split("/")
        prepared.append(
            PreparedUpload(
                source=source,
                path=resolved,
                upload_name=_upload_name(source),
                source_type=parts[0] if len(parts) > 1 else None,
                sha256=_sha256(resolved),
                size_bytes=size_bytes,
            )
        )
    return prepared, skipped


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging")
    staging.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(staging, path)


def _set_env_value(path: Path, key: str, value: str) -> None:
    original = path.read_text(encoding="utf-8") if path.is_file() else ""
    lines = original.splitlines()
    replacement = f"{key}={value}"
    output: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith(f"{key}="):
            if not replaced:
                output.append(replacement)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(replacement)
    rendered = "\n".join(output).rstrip("\n") + "\n"
    staging = path.with_name(f".{path.name}.staging")
    staging.write_text(rendered, encoding="utf-8")
    os.replace(staging, path)


async def run_ingest(
    *,
    client: ChatDocIngestClient,
    source_root: Path,
    artifact_path: Path,
    env_file: Path,
    repo_name: str,
    progress: Callable[[str], None] | None = None,
) -> IngestResult:
    report = progress or (lambda message: None)
    prepared, skipped = prepare_uploads(source_root)
    if not prepared:
        raise RuntimeError("no ChatDoc-compatible files are within the upload limit")

    repo_id = await client.create_repo(
        repo_name,
        "粮食储藏、害虫防治、低温储粮、粮仓建设、粮食安全法规",
    )
    report(f"Created ChatDoc repo {repo_id[:12]}")

    uploaded: list[tuple[PreparedUpload, str]] = []
    for index, item in enumerate(prepared, start=1):
        file_id = await client.upload_file(item.path, upload_name=item.upload_name)
        uploaded.append((item, file_id))
        report(f"Uploaded {index}/{len(prepared)}: {item.source}")

    file_ids = [file_id for _, file_id in uploaded]
    statuses = await client.wait_until_vectored(file_ids)
    if any(statuses.get(file_id) != "vectored" for file_id in file_ids):
        raise RuntimeError("ChatDoc did not vectorize every uploaded file")
    report(f"Vectored {len(file_ids)} files")

    for start in range(0, len(file_ids), 20):
        await client.add_files(repo_id, file_ids[start : start + 20])

    sources: dict[str, Any] = {}
    for item, file_id in uploaded:
        sources[item.source] = {
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
            "source_type": item.source_type,
            "uploads": [
                {
                    "file_id": file_id,
                    "upload_name": item.upload_name,
                    "status": statuses[file_id],
                }
            ],
        }
    manifest = {
        "schema_version": 1,
        "backend": "iflytek_chatdoc",
        "repo_id": repo_id,
        "repo_name": repo_name,
        "source_root": str(Path(source_root)),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sources": sources,
        "skipped_sources": skipped,
    }
    _atomic_json(Path(artifact_path), manifest)
    _set_env_value(Path(env_file), "XF_CHATDOC_REPO_ID", repo_id)
    report(f"Published ChatDoc manifest: {artifact_path}")
    return IngestResult(
        repo_id=repo_id,
        repo_name=repo_name,
        uploaded_files=len(uploaded),
        skipped_files=len(skipped),
        artifact_path=Path(artifact_path),
    )
