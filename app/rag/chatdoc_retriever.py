"""Retriever adapter for iFlytek ChatDoc vector search."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.clients.iflytek_chatdoc import ChatDocSearchHit
from app.rag.evidence import Evidence, build_evidence, normalize_source
from app.schemas.tools import RetrieveRequest, RetrieveResponse, RetrievalQuality


@dataclass(frozen=True)
class ChatDocFile:
    file_id: str
    source: str
    checksum: str
    source_type: str | None


@dataclass(frozen=True)
class ChatDocManifest:
    repo_id: str
    files: dict[str, ChatDocFile]
    source_count: int


class ChatDocSearchProvider(Protocol):
    async def search(
        self, *, repo_id: str, query: str, top_n: int
    ) -> list[ChatDocSearchHit]: ...


def load_chatdoc_manifest(path: Path) -> ChatDocManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("backend") != "iflytek_chatdoc":
        raise ValueError("invalid ChatDoc manifest backend")
    repo_id = payload.get("repo_id")
    sources = payload.get("sources")
    if not isinstance(repo_id, str) or not repo_id.strip():
        raise ValueError("invalid ChatDoc repo_id")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("invalid ChatDoc sources")
    files: dict[str, ChatDocFile] = {}
    for raw_source, entry in sources.items():
        source = normalize_source(raw_source)
        if not isinstance(entry, dict):
            raise ValueError("invalid ChatDoc source entry")
        checksum = entry.get("sha256")
        uploads = entry.get("uploads")
        source_type = entry.get("source_type")
        if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("invalid ChatDoc source checksum")
        if source_type is not None and not isinstance(source_type, str):
            raise ValueError("invalid ChatDoc source type")
        if not isinstance(uploads, list) or not uploads:
            raise ValueError("invalid ChatDoc uploads")
        for upload in uploads:
            if not isinstance(upload, dict) or upload.get("status") != "vectored":
                raise ValueError("ChatDoc upload is not vectored")
            file_id = upload.get("file_id")
            if not isinstance(file_id, str) or not file_id.strip() or file_id in files:
                raise ValueError("invalid or duplicate ChatDoc file_id")
            files[file_id] = ChatDocFile(
                file_id=file_id,
                source=source,
                checksum=checksum,
                source_type=source_type,
            )
    return ChatDocManifest(
        repo_id=repo_id.strip(),
        files=files,
        source_count=len(sources),
    )


def _normalized_score(value: float) -> float:
    score = float(value)
    if not math.isfinite(score):
        raise ValueError("ChatDoc score must be finite")
    if score > 1.0:
        score /= 100.0
    return max(-1.0, min(1.0, score))


class ChatDocRetriever:
    backend = "chatdoc"

    def __init__(
        self,
        *,
        client: ChatDocSearchProvider,
        manifest: ChatDocManifest,
        min_score: float,
        evidence_cache_size: int = 2000,
    ) -> None:
        self.client = client
        self.manifest = manifest
        self.min_score = min_score
        self.evidence_cache_size = evidence_cache_size
        self._evidence_by_id: dict[str, Evidence] = {}

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        has_filters = bool(
            request.filters.source_type or request.filters.authority_level
        )
        hits = await self.client.search(
            repo_id=self.manifest.repo_id,
            query=request.query,
            top_n=20 if has_filters else request.top_k,
        )
        evidences: list[Evidence] = []
        for hit in hits:
            source = self.manifest.files.get(hit.file_id)
            if source is None:
                continue
            metadata = {
                "source": source.source,
                "text": hit.content,
                "start_pos": hit.index,
                "document_checksum": source.checksum,
                "source_type": source.source_type,
                "authority_level": "unknown",
                "quality_flags": ["chatdoc_managed", hit.retrieval_type],
            }
            if (
                request.filters.source_type
                and metadata["source_type"] != request.filters.source_type
            ):
                continue
            if (
                request.filters.authority_level
                and metadata["authority_level"]
                != request.filters.authority_level
            ):
                continue
            evidence = build_evidence(metadata, _normalized_score(hit.score))
            evidences.append(evidence)
            self._evidence_by_id[evidence.evidence_id] = evidence
            if len(evidences) >= request.top_k:
                break
        while len(self._evidence_by_id) > self.evidence_cache_size:
            self._evidence_by_id.pop(next(iter(self._evidence_by_id)))
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

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self._evidence_by_id.get(evidence_id)

    def ready_details(self) -> dict[str, str | int]:
        return {
            "status": "ready",
            "backend": self.backend,
            "sources": self.manifest.source_count,
            "repo": self.manifest.repo_id[:12],
        }
