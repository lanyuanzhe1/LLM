import json
from pathlib import Path
from unittest.mock import patch

import pytest

import ingest_knowledge as ik


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class FakeEmbeddingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def embed(self, text: str, domain: str) -> "np.ndarray":
        import numpy as np
        rng = np.random.RandomState(hash(text) % 2**31)
        return rng.randn(2560).astype(np.float32)

    async def close(self):
        pass


def test_resolve_scope_base_excludes_projects(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "base_doc.txt", "base content")
    _write_file(tmp_path / "projects" / "demo" / "proj.txt", "project")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="base")

    assert report["files_indexed"] == 1
    assert (tmp_path / "out" / "base" / "vectors.npy").is_file()
    assert (tmp_path / "out" / "base" / "manifest.json").is_file()


def test_resolve_scope_project_only_sees_project(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "projects" / "demo" / "a.txt", "demo content")
    _write_file(tmp_path / "projects" / "other" / "b.txt", "other")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="project", project_id="demo")

    assert report["project_id"] == "demo"
    assert report["files_indexed"] == 1
    assert (tmp_path / "out" / "projects" / "demo" / "vectors.npy").is_file()


def test_resolve_scope_all_projects(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "projects" / "demo" / "a.txt", "A")
    _write_file(tmp_path / "projects" / "other" / "b.txt", "B")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        report = ik.run_ingestion(scope="all-projects")

    assert report["projects_processed"] == 2


def test_empty_knowledge_dir_exits_nonzero(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ik, "DOC_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    report = ik.run_ingestion(scope="base")
    assert report["files_scanned"] == 0
    assert report["files_indexed"] == 0


def test_all_files_skipped_exits_nonzero(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "slides.pptx", "no parser for pptx")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    report = ik.run_ingestion(scope="base")
    assert report["files_scanned"] == 0


def test_ingest_report_is_valid_json(tmp_path: Path, monkeypatch):
    _write_file(tmp_path / "doc.txt", "test content for report validation")

    monkeypatch.setattr(ik, "DOC_DIR", tmp_path)
    monkeypatch.setattr(ik, "OUTPUT_BASE_DIR", tmp_path / "out")
    monkeypatch.setattr(ik, "CHUNK_SIZE", 600)
    monkeypatch.setattr(ik, "CHUNK_OVERLAP", 100)
    monkeypatch.setattr(ik, "PARSER_VERSION", "2026-07-20")
    monkeypatch.setenv("XF_APP_ID", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_KEY", "fake")
    monkeypatch.setenv("XF_EMBEDDING_API_SECRET", "fake")

    with patch.object(ik, "IflytekEmbeddingClient", FakeEmbeddingClient):
        ik.run_ingestion(scope="base")

    report_path = tmp_path / "out" / "base" / "ingest_report.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    assert "files_scanned" in report
    assert "chunks_embedded" in report
