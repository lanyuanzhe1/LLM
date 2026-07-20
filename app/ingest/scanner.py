"""Scope-aware file discovery with project_id validation for RAG ingestion."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator

from app.ingest.reader import SUPPORTED_EXTENSIONS

_VALID_PROJECT_ID = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9_]*[a-zA-Z0-9]$")


@dataclass(frozen=True)
class ScannedDocument:
    path: str
    sha256: str
    source_type: str | None
    size_bytes: int
    mtime_ns: int


def validate_project_id(value: str) -> str:
    """Validate and normalise a project_id.

    Raises ValueError for empty, path-traversal patterns, unprintable
    characters, or values that do not match the expected identifier shape.
    Returns the stripped value on success.
    """
    if not isinstance(value, str):
        raise ValueError("project_id must be a string")

    # Unprintable characters — check raw value first
    if "\n" in value or "\0" in value or "\t" in value:
        raise ValueError("project_id contains unprintable characters")

    # Path-traversal and absolute-path heuristics
    for bad in ("../", "/", "\\", "./"):
        if bad in value:
            raise ValueError("project_id must not be a path")

    stripped = value.strip()
    if not stripped:
        raise ValueError("project_id must not be empty")

    if not _VALID_PROJECT_ID.fullmatch(stripped):
        raise ValueError(
            "project_id must match [a-zA-Z0-9][-a-zA-Z0-9_]*[a-zA-Z0-9]"
        )
    if len(stripped) > 64:
        raise ValueError("project_id must be at most 64 characters")
    return stripped


def _scan_directory(
    doc_dir: Path, *, exclude_prefixes: tuple[str, ...] = ()
) -> Iterator[ScannedDocument]:
    """Yield ScannedDocument for every supported file under *doc_dir*.

    Parameters
    ----------
    exclude_prefixes:
        Relative paths starting with any of these prefixes are skipped.
        Used to hide the ``projects/`` tree during base scans.
    """
    doc_dir = doc_dir.resolve(strict=False)
    if not doc_dir.is_dir():
        return
    for file_path in doc_dir.rglob("*"):
        if file_path.is_symlink() or not file_path.is_file():
            continue
        if file_path.name.startswith("~") or file_path.name.startswith("."):
            continue
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        try:
            resolved_file = file_path.resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        try:
            resolved_file.relative_to(doc_dir)
        except ValueError:
            continue
        try:
            relative = file_path.relative_to(doc_dir).as_posix()
        except ValueError:
            continue
        if exclude_prefixes and relative.startswith(exclude_prefixes):
            continue
        try:
            raw = file_path.read_bytes()
        except OSError:
            continue
        parts = relative.split("/")
        source_type = parts[0] if len(parts) > 1 else None
        stat = file_path.stat()
        yield ScannedDocument(
            path=relative,
            sha256=hashlib.sha256(raw).hexdigest(),
            source_type=source_type,
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )


def scan_base(doc_dir: Path) -> Iterator[ScannedDocument]:
    """Walk *doc_dir*, skipping the ``projects/`` sub-tree."""
    yield from _scan_directory(doc_dir, exclude_prefixes=("projects/",))


def scan_project(doc_dir: Path, project_id: str) -> Iterator[ScannedDocument]:
    """Scan only ``doc_dir/projects/<project_id>/``."""
    project_dir = doc_dir / "projects" / validate_project_id(project_id)
    yield from _scan_directory(project_dir)
