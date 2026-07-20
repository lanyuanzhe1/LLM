"""Tests for app.ingest.scanner — file discovery with scope boundaries."""

import hashlib
import pytest
from pathlib import Path

from app.ingest.scanner import (
    ScannedDocument,
    validate_project_id,
    scan_base,
    scan_project,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# validate_project_id
# ---------------------------------------------------------------------------

class TestValidateProjectId:
    def test_validate_project_id_rejects_empty(self):
        for bad in ("", "  ", "\t"):
            with pytest.raises(ValueError):
                validate_project_id(bad)

    def test_validate_project_id_rejects_path_traversal(self):
        for bad in ("../etc", "a/b", "/root", "C:\\windows", "./hidden"):
            with pytest.raises(ValueError):
                validate_project_id(bad)

    def test_validate_project_id_rejects_unprintable(self):
        for bad in ("proj\nect", "proj\0id", "proj\tid"):
            with pytest.raises(ValueError):
                validate_project_id(bad)

    def test_validate_project_id_accepts_valid(self):
        for good in ("demo", "my-project_2024", "project-123"):
            assert validate_project_id(good) == good


# ---------------------------------------------------------------------------
# scan_base
# ---------------------------------------------------------------------------

class TestScanBase:
    def test_scan_base_excludes_projects_dir(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "root.txt", "root")
        _write_file(doc_dir / "sub" / "nested.txt", "nested")
        _write_file(doc_dir / "projects" / "demo" / "excluded.txt", "x")

        docs = list(scan_base(doc_dir))
        paths = {d.path for d in docs}
        assert "root.txt" in paths
        assert "sub/nested.txt" in paths
        assert "projects/demo/excluded.txt" not in paths

    def test_scan_base_skips_unsupported_extensions(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "a.txt", "ok")
        _write_file(doc_dir / "b.pptx", "no")
        _write_file(doc_dir / "c.png", "no")

        docs = list(scan_base(doc_dir))
        paths = {d.path for d in docs}
        assert "a.txt" in paths
        assert "b.pptx" not in paths
        assert "c.png" not in paths

    def test_scan_base_skips_symlinks(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "real.txt", "real")
        target = doc_dir / "real.txt"
        link = doc_dir / "link.txt"
        link.symlink_to(target)

        docs = list(scan_base(doc_dir))
        paths = {d.path for d in docs}

        # Symlink may or may not be supported on the platform;
        # if it exists as a symlink, it MUST NOT appear.
        if link.is_symlink():
            assert "link.txt" not in paths
        else:
            # Platform does not support symlinks — test is vacuous
            pass


# ---------------------------------------------------------------------------
# scan_project
# ---------------------------------------------------------------------------

class TestScanProject:
    def test_scan_project_only_sees_one_project(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "projects" / "demo" / "a.txt", "demo-a")
        _write_file(doc_dir / "projects" / "demo" / "sub" / "b.txt", "demo-b")
        _write_file(doc_dir / "projects" / "other" / "c.txt", "other-c")

        docs = list(scan_project(doc_dir, "demo"))
        paths = {d.path for d in docs}
        assert "a.txt" in paths
        assert "sub/b.txt" in paths
        assert "c.txt" not in paths
        assert len(paths) == 2

    def test_scan_project_nonexistent_dir_yields_empty(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        # No projects/nope/ directory exists
        docs = list(scan_project(doc_dir, "nope"))
        assert docs == []


# ---------------------------------------------------------------------------
# ScannedDocument fields
# ---------------------------------------------------------------------------

class TestScannedDocument:
    def test_scanned_document_has_checksum(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "hello.txt", "hello world")

        docs = list(scan_base(doc_dir))
        assert len(docs) == 1
        d = docs[0]

        assert d.path == "hello.txt"
        assert len(d.sha256) == 64
        assert all(c in "0123456789abcdef" for c in d.sha256)
        assert d.source_type is None  # root file has no parent dir
        assert d.size_bytes == 11
        assert d.mtime_ns > 0

    def test_scanned_document_source_type_from_subdir(self, tmp_path: Path):
        doc_dir = tmp_path / "docs"
        _write_file(doc_dir / "category" / "item.txt", "xyz")

        docs = list(scan_base(doc_dir))
        assert len(docs) == 1
        d = docs[0]
        assert d.source_type == "category"
        assert d.path == "category/item.txt"
