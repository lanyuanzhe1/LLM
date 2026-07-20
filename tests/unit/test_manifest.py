"""Unit tests for app.ingest.manifest."""

import json
from pathlib import Path

import pytest

from app.ingest.manifest import (
    DocumentEntry,
    Manifest,
    ManifestConfig,
    find_reusable,
    load_manifest,
    save_manifest,
)
from app.ingest.scanner import ScannedDocument


def _doc(path: str, sha256: str = "a" * 64) -> ScannedDocument:
    return ScannedDocument(
        path=path, sha256=sha256, source_type=None, size_bytes=100, mtime_ns=0,
    )


MANIFEST_CONFIG = ManifestConfig(
    parser_version="2026-07-20",
    chunk_size=600,
    chunk_overlap=100,
    embedding_provider="iflytek",
    embedding_url="https://emb-cn-huabei-1.xf-yun.com/",
    embedding_dimension=2560,
)


# ---------------------------------------------------------------------------
# RED-1: load_manifest returns None for a missing file
# ---------------------------------------------------------------------------
def test_load_manifest_returns_none_for_missing_file(tmp_path: Path) -> None:
    result = load_manifest(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# RED-2: save → load round-trip
# ---------------------------------------------------------------------------
def test_save_and_load_round_trip(tmp_path: Path) -> None:
    manifest = Manifest(
        schema_version=1,
        scope="project",
        project_id="demo",
        source_root="/data/docs",
        embedding_dimension=2560,
        embedding_provider="iflytek",
        embedding_url="https://emb-cn-huabei-1.xf-yun.com/",
        chunk_size=600,
        chunk_overlap=100,
        parser_version="2026-07-20",
        documents={
            "report.pdf": DocumentEntry(
                sha256="b" * 64, mtime_ns=1_700_000_000_000, size_bytes=2048,
                status="indexed", chunk_count=5,
            ),
        },
    )
    save_manifest(manifest, tmp_path)

    loaded = load_manifest(tmp_path)
    assert loaded is not None
    assert loaded.schema_version == 1
    assert loaded.scope == "project"
    assert loaded.project_id == "demo"
    assert loaded.source_root == "/data/docs"
    assert loaded.embedding_dimension == 2560
    assert loaded.embedding_provider == "iflytek"
    assert loaded.embedding_url == "https://emb-cn-huabei-1.xf-yun.com/"
    assert loaded.chunk_size == 600
    assert loaded.chunk_overlap == 100
    assert loaded.parser_version == "2026-07-20"

    assert "report.pdf" in loaded.documents
    entry = loaded.documents["report.pdf"]
    assert entry.sha256 == "b" * 64
    assert entry.mtime_ns == 1_700_000_000_000
    assert entry.size_bytes == 2048
    assert entry.status == "indexed"
    assert entry.chunk_count == 5


# ---------------------------------------------------------------------------
# RED-3: find_reusable splits docs correctly
# ---------------------------------------------------------------------------
def test_find_reusable_returns_unchanged_documents() -> None:
    manifest = Manifest(
        documents={
            "unchanged.pdf": DocumentEntry(
                sha256="a" * 64, mtime_ns=0, size_bytes=100,
                status="indexed", chunk_count=3,
            ),
            "changed.pdf": DocumentEntry(
                sha256="b" * 64, mtime_ns=0, size_bytes=100,
                status="indexed", chunk_count=3,
            ),
        },
        parser_version="2026-07-20",
    )
    current: dict[str, ScannedDocument] = {
        "unchanged.pdf": _doc("unchanged.pdf", sha256="a" * 64),
        "changed.pdf": _doc("changed.pdf", sha256="c" * 64),  # different hash
        "new.pdf": _doc("new.pdf", sha256="d" * 64),
    }

    reusable, new_or_changed = find_reusable(manifest, current, MANIFEST_CONFIG)

    assert reusable == ["unchanged.pdf"]
    assert set(new_or_changed) == {"changed.pdf", "new.pdf"}


# ---------------------------------------------------------------------------
# RED-4: config mismatch → nothing is reusable
# ---------------------------------------------------------------------------
def test_find_reusable_requires_parser_version_match() -> None:
    manifest = Manifest(
        documents={
            "file.pdf": DocumentEntry(
                sha256="a" * 64, mtime_ns=0, size_bytes=100,
                status="indexed", chunk_count=1,
            ),
        },
        parser_version="2025-01-01",  # old
    )
    current: dict[str, ScannedDocument] = {
        "file.pdf": _doc("file.pdf", sha256="a" * 64),
    }

    reusable, new_or_changed = find_reusable(manifest, current, MANIFEST_CONFIG)

    assert reusable == []
    assert new_or_changed == ["file.pdf"]


# ---------------------------------------------------------------------------
# RED-5: deleted files silently dropped
# ---------------------------------------------------------------------------
def test_find_reusable_deleted_file_not_reused() -> None:
    manifest = Manifest(
        documents={
            "deleted.pdf": DocumentEntry(
                sha256="a" * 64, mtime_ns=0, size_bytes=100,
                status="indexed", chunk_count=1,
            ),
        },
        parser_version="2026-07-20",
    )
    current: dict[str, ScannedDocument] = {}

    reusable, new_or_changed = find_reusable(manifest, current, MANIFEST_CONFIG)

    assert reusable == []
    assert new_or_changed == []
