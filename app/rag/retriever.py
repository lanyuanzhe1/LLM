from typing import Protocol

import numpy as np

from app.rag.evidence import build_evidence
from app.rag.vector_store import VectorStore
from app.schemas.tools import (
    RetrieveRequest,
    RetrieveResponse,
    RetrievalQuality,
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str, domain: str) -> np.ndarray: ...


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedding: EmbeddingProvider,
        min_score: float,
    ) -> None:
        self.store = store
        self.embedding = embedding
        self.min_score = min_score

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        query_vector = await self.embedding.embed(request.query, domain="query")
        hits = self.store.search(
            query_vector,
            top_k=len(self.store.metadata),
        )
        if request.filters.source_type:
            hits = [
                hit
                for hit in hits
                if hit.metadata.get("source_type")
                == request.filters.source_type
            ]
        if request.filters.authority_level:
            hits = [
                hit
                for hit in hits
                if hit.metadata.get("authority_level")
                == request.filters.authority_level
            ]
        evidences = [
            build_evidence(hit.metadata, hit.score)
            for hit in hits[: request.top_k]
        ]
        top_score = evidences[0].score if evidences else 0.0
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=evidences,
            quality=RetrievalQuality(
                top_score=top_score,
                sufficient=bool(evidences and top_score >= self.min_score),
            ),
        )
