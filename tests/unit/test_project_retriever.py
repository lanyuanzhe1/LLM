import json
from pathlib import Path

import numpy as np
import pytest

from app.rag.registry import VectorStoreRegistry
from app.rag.vector_store import VectorStore
from app.schemas.tools import RetrieveRequest


def _write_store(
    path: Path, texts: list[str], source_prefix: str = "doc"
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    rng = np.random.RandomState(42)
    vectors = rng.randn(len(texts), 2560).astype(np.float32)
    np.save(path / "vectors.npy", vectors)
    metadata = [
        {
            "text": t,
            "source": f"{source_prefix}{i}.pdf",
            "start_pos": 0,
        }
        for i, t in enumerate(texts)
    ]
    (path / "chunks_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )


class FakeEmbedding:
    """Returns uniformly positive vectors — all cosine similarities ≈ 1."""

    async def embed(self, text: str, domain: str) -> np.ndarray:
        return np.ones(2560, dtype=np.float32)


# ---------------------------------------------------------------------------
# The import below will fail until project_retriever.py is created (RED phase)
# ---------------------------------------------------------------------------
from app.rag.project_retriever import ProjectRetriever  # noqa: E402


@pytest.mark.asyncio
async def test_project_retriever_merges_base_and_project(tmp_path: Path):
    _write_store(tmp_path / "base", ["暖通设计", "磷化铝熏蒸"], source_prefix="base-")
    _write_store(
        tmp_path / "projects" / "demo", ["绿色储粮"], source_prefix="demo-"
    )

    registry = VectorStoreRegistry(root_dir=tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="r1",
            query="储粮害虫",
            top_k=5,
            project_id="demo",
        )
    )

    assert len(response.evidences) == 3
    sources = {ev.source for ev in response.evidences}
    assert len(sources) == 3


@pytest.mark.asyncio
async def test_project_retriever_base_only_when_no_project_id(tmp_path: Path):
    _write_store(tmp_path / "base", ["平衡水分"])

    registry = VectorStoreRegistry(root_dir=tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="r2", query="水分", top_k=5)
    )

    assert len(response.evidences) == 1


@pytest.mark.asyncio
async def test_project_retriever_respects_top_k(tmp_path: Path):
    texts = [f"chunk-{i}" for i in range(10)]
    _write_store(tmp_path / "base", texts)

    registry = VectorStoreRegistry(root_dir=tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="r3", query="测试", top_k=3)
    )

    assert len(response.evidences) == 3


@pytest.mark.asyncio
async def test_project_retriever_never_leaks_cross_project(tmp_path: Path):
    _write_store(tmp_path / "base", ["暖通设计", "磷化铝熏蒸"])
    _write_store(tmp_path / "projects" / "demo", ["绿色储粮"])
    _write_store(tmp_path / "projects" / "other", ["OTHER-SECRET"])

    registry = VectorStoreRegistry(root_dir=tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="r4",
            query="储粮害虫",
            top_k=10,
            project_id="demo",
        )
    )

    sources = {ev.source for ev in response.evidences}
    assert "other" not in {Path(s).parts[0] for s in sources}
    assert "OTHER" not in " ".join(ev.text for ev in response.evidences)
    # Base + demo only: 2 + 1 = 3
    assert len(response.evidences) == 3


@pytest.mark.asyncio
async def test_project_retriever_with_missing_project_still_uses_base(
    tmp_path: Path,
):
    _write_store(tmp_path / "base", ["替代储存方案"])

    registry = VectorStoreRegistry(root_dir=tmp_path)
    retriever = ProjectRetriever(
        registry=registry,
        embedding=FakeEmbedding(),
        min_score=0.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="r5",
            query="储藏",
            top_k=5,
            project_id="no-such",
        )
    )

    assert len(response.evidences) == 1
    assert response.quality.sufficient is True
