from pathlib import Path

import numpy as np
import pytest

from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.schemas.tools import RetrieveRequest
from tests.unit.test_vector_store import write_store


class FakeEmbedding:
    async def embed(self, text: str, domain: str) -> np.ndarray:
        assert domain == "query"
        return np.array([1.0, 0.0], dtype=np.float32)


@pytest.mark.asyncio
async def test_retriever_returns_evidence_and_quality(tmp_path: Path):
    store_path = tmp_path / "vector_store"
    write_store(store_path)
    retriever = Retriever(
        store=VectorStore.load(store_path),
        embedding=FakeEmbedding(),
        min_score=0.35,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="req", query="低温", top_k=1)
    )

    assert response.evidences[0].source == "a.pdf"
    assert response.quality.sufficient is True


@pytest.mark.asyncio
async def test_filters_apply_to_full_candidates_before_top_k(tmp_path: Path):
    store_path = tmp_path / "vector_store"
    write_store(
        store_path,
        vectors=np.array(
            [
                [1.0, 0.0],
                [0.95, 0.05],
                [0.9, 0.1],
                [0.8, 0.2],
            ],
            dtype=np.float32,
        ),
        metadata=[
            {
                "text": "highest",
                "source": "general.pdf",
                "source_type": "paper",
                "authority_level": "unknown",
            },
            {
                "text": "type-only",
                "source": "policy-guide.pdf",
                "source_type": "policy",
                "authority_level": "guide",
            },
            {
                "text": "authority-only",
                "source": "law-paper.pdf",
                "source_type": "paper",
                "authority_level": "law",
            },
            {
                "text": "combined",
                "source": "law.pdf",
                "source_type": "policy",
                "authority_level": "law",
            },
        ],
    )
    retriever = Retriever(
        store=VectorStore.load(store_path),
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="法规",
            top_k=1,
            filters={"source_type": "policy", "authority_level": "law"},
        )
    )

    assert [item.text for item in response.evidences] == ["combined"]


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_name", ["source_type", "authority_level"])
async def test_requested_filter_fails_closed_for_missing_metadata(
    tmp_path: Path, filter_name
):
    store_path = tmp_path / "vector_store"
    write_store(store_path)
    retriever = Retriever(
        store=VectorStore.load(store_path),
        embedding=FakeEmbedding(),
        min_score=-1.0,
    )

    response = await retriever.retrieve(
        RetrieveRequest(
            request_id="req",
            query="低温",
            top_k=2,
            filters={filter_name: "unknown"},
        )
    )

    assert response.evidences == []
    assert response.quality.top_score == 0.0
    assert response.quality.sufficient is False
