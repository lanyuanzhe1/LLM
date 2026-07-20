"""Tests for app.ingest.builder — index construction, artifact saving, atomic publish."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

# -- import NOT yet: the module does not exist (RED) -------------------------


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_chunks(n: int = 3) -> list[dict]:
    rng = np.random.RandomState(42)
    return [{
        "text": f"chunk {i}", "source": f"doc{i}.pdf",
        "start_pos": i * 100, "char_count": 50,
        "embedding": rng.randn(2560).astype(np.float32),
        "document_checksum": "a" * 64, "source_type": "papers",
    } for i in range(n)]


# ---------------------------------------------------------------------------
# build_index_from_chunks
# ---------------------------------------------------------------------------

class TestBuildIndex:
    def test_build_index_returns_neighbors(self):
        """5 chunks, returns NearestNeighbors with shape (5, 2560)."""
        from app.ingest.builder import build_index_from_chunks

        chunks = _make_chunks(5)
        nbrs = build_index_from_chunks(chunks)
        assert hasattr(nbrs, "_fit_X"), "expected fitted NearestNeighbors"
        assert nbrs._fit_X.shape == (5, 2560)

    def test_build_index_rejects_empty(self):
        """Empty list raises ValueError."""
        from app.ingest.builder import build_index_from_chunks

        with pytest.raises(ValueError, match="empty"):
            build_index_from_chunks([])


# ---------------------------------------------------------------------------
# save_artifacts
# ---------------------------------------------------------------------------

class TestSaveArtifacts:
    def test_save_artifacts_writes_vectors_and_metadata(self, tmp_path: Path):
        """3 chunks, both files exist, metadata has 3 entries, no 'embedding' key."""
        from app.ingest.builder import build_index_from_chunks, save_artifacts

        chunks = _make_chunks(3)
        nbrs = build_index_from_chunks(chunks)
        out = tmp_path / "vectors_test"
        save_artifacts(nbrs, chunks, out)

        vec_file = out / "vectors.npy"
        meta_file = out / "chunks_metadata.json"
        assert vec_file.is_file(), f"expected {vec_file} to exist"
        assert meta_file.is_file(), f"expected {meta_file} to exist"

        vectors = np.load(str(vec_file))
        assert vectors.ndim == 2
        assert vectors.shape[0] == 3

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        assert len(meta) == 3
        for entry in meta:
            assert "embedding" not in entry.keys()
            assert "text" in entry

    def test_save_artifacts_strips_embedding_from_metadata(self, tmp_path: Path):
        """1 chunk, confirm no 'embedding' key in saved JSON."""
        from app.ingest.builder import build_index_from_chunks, save_artifacts

        chunks = _make_chunks(1)
        nbrs = build_index_from_chunks(chunks)
        out = tmp_path / "single"
        save_artifacts(nbrs, chunks, out)

        meta = json.loads((out / "chunks_metadata.json").read_text(encoding="utf-8"))
        assert len(meta) == 1
        with pytest.raises(KeyError):
            _ = meta[0]["embedding"]


# ---------------------------------------------------------------------------
# publish_store
# ---------------------------------------------------------------------------

class TestPublishStore:
    def test_publish_store_atomic_swap(self, tmp_path: Path):
        """Staging has artifacts, publish to fresh target → staging removed, target has files."""
        from app.ingest.builder import build_index_from_chunks, save_artifacts, publish_store

        staging = tmp_path / "staging"
        target = tmp_path / "target"
        chunks = _make_chunks(2)
        nbrs = build_index_from_chunks(chunks)
        save_artifacts(nbrs, chunks, staging)

        publish_store(staging, target)

        assert not staging.exists(), "staging should be removed after publish"
        assert target.is_dir(), "target directory should exist"
        assert (target / "vectors.npy").is_file()
        assert (target / "chunks_metadata.json").is_file()

    def test_publish_store_replaces_existing(self, tmp_path: Path):
        """Target has old file, staging has new artifacts, publish replaces, old file gone."""
        from app.ingest.builder import build_index_from_chunks, save_artifacts, publish_store

        # Create an existing target with an extra file
        target = tmp_path / "target"
        target.mkdir()
        (target / "old_file.txt").write_text("legacy")

        # Create staging with new artifacts
        staging = tmp_path / "staging"
        chunks = _make_chunks(2)
        nbrs = build_index_from_chunks(chunks)
        save_artifacts(nbrs, chunks, staging)

        publish_store(staging, target)

        assert not staging.exists(), "staging should be removed after publish"
        assert (target / "vectors.npy").is_file(), "vectors.npy should exist"
        assert (target / "chunks_metadata.json").is_file(), "metadata should exist"
        assert not (target / "old_file.txt").exists(), "old file should be gone"
