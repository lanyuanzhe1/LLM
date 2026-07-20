import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from app.rag.registry import VectorStoreRegistry


def _write_store(path: Path, n: int = 2) -> None:
    path.mkdir(parents=True, exist_ok=True)
    np.save(path / "vectors.npy", np.array([[1.0, 0.0], [0.0, 1.0]][:n], dtype=np.float32))
    metadata = [{"text": f"chunk {i}", "source": f"doc{i}.pdf", "start_pos": 0} for i in range(n)]
    (path / "chunks_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")


class TestVectorStoreRegistry:
    def test_registry_loads_base_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_store(root / "base")
            registry = VectorStoreRegistry(root)
            store = registry.get_base()
            assert store is not None
            assert store.dimension == 2

    def test_registry_loads_project_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_store(root / "projects" / "demo")
            registry = VectorStoreRegistry(root)
            store = registry.get_project("demo")
            assert store is not None
            assert store.dimension == 2

    def test_registry_returns_none_for_missing_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = VectorStoreRegistry(root)
            assert registry.get_base() is None

    def test_registry_returns_none_for_missing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = VectorStoreRegistry(root)
            assert registry.get_project("no-such") is None

    def test_registry_caches_loaded_stores(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_store(root / "base")
            registry = VectorStoreRegistry(root)
            s1 = registry.get_base()
            s2 = registry.get_base()
            assert s1 is not None
            assert s1 is s2

    def test_registry_reload_clears_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_store(root / "base")
            registry = VectorStoreRegistry(root)
            s1 = registry.get_base()
            registry.reload()
            s2 = registry.get_base()
            assert s1 is not None
            assert s2 is not None
            assert s1 is not s2

    def test_registry_multiple_projects_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_store(root / "projects" / "alpha")
            _write_store(root / "projects" / "beta")
            registry = VectorStoreRegistry(root)
            alpha = registry.get_project("alpha")
            beta = registry.get_project("beta")
            assert alpha is not None
            assert beta is not None
            assert alpha is not beta
