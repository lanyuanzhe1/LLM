from typing import Protocol

import numpy as np

from app.rag.evidence import build_evidence
from app.rag.registry import VectorStoreRegistry
from app.rag.vector_store import SearchHit
from app.schemas.tools import (
    RetrieveRequest,
    RetrieveResponse,
    RetrievalQuality,
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str, domain: str) -> np.ndarray: ...


class ProjectRetriever:
    def __init__(
        self,
        *,
        registry: VectorStoreRegistry,
        embedding: EmbeddingProvider,
        min_score: float,
    ) -> None:
        self._registry = registry
        self._embedding = embedding
        self._min_score = min_score

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        query_vector = await self._embedding.embed(
            request.query, domain="query"
        )
        all_hits: list[SearchHit] = []

        base = self._registry.get_base()
        if base is not None:
            for hit in base.search(query_vector, top_k=len(base.metadata)):
                hit.metadata["scope"] = "base"
                all_hits.append(hit)

        if request.project_id:
            project_store = self._registry.get_project(request.project_id)
            if project_store is not None:
                for hit in project_store.search(
                    query_vector, top_k=len(project_store.metadata)
                ):
                    hit.metadata["scope"] = "project"
                    hit.metadata["project_id"] = request.project_id
                    all_hits.append(hit)

        if request.filters.source_type:
            all_hits = [
                h
                for h in all_hits
                if h.metadata.get("source_type") == request.filters.source_type
            ]
        if request.filters.authority_level:
            all_hits = [
                h
                for h in all_hits
                if h.metadata.get("authority_level")
                == request.filters.authority_level
            ]

        all_hits.sort(key=lambda h: h.score, reverse=True)
        top_hits = all_hits[: request.top_k]
        evidences = [
            build_evidence(h.metadata, h.score) for h in top_hits
        ]
        top_score = evidences[0].score if evidences else 0.0
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=evidences,
            quality=RetrievalQuality(
                top_score=top_score,
                sufficient=bool(
                    evidences and top_score >= self._min_score
                ),
            ),
        )
