"""Read-only knowledge catalog endpoints (/v1/knowledge/*).

Protected by the OpenAI-compat service key via ``auth_middleware``.
Upstream ChatDoc failures are surfaced as 503 KNOWLEDGE_UNAVAILABLE (the
business code is not propagated); unknown files are 404 DOCUMENT_NOT_FOUND.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.core.errors import ProviderUnavailable
from app.schemas.knowledge import KnowledgeFileChunks, KnowledgeFileList

router = APIRouter(prefix="/v1/knowledge", tags=["knowledge"])


def _catalog(request: Request):
    catalog = getattr(
        getattr(request.app.state, "container", None),
        "knowledge",
        None,
    )
    if catalog is None:
        raise HTTPException(
            status_code=503,
            detail="KNOWLEDGE_UNAVAILABLE",
        )
    return catalog


@router.get("/files", response_model=KnowledgeFileList)
async def list_files(request: Request) -> KnowledgeFileList:
    catalog = _catalog(request)
    try:
        files = await catalog.list_files()
    except ProviderUnavailable:
        raise HTTPException(
            status_code=503,
            detail="KNOWLEDGE_UNAVAILABLE",
        ) from None
    return KnowledgeFileList(files=files)


@router.get("/files/{file_id}/chunks", response_model=KnowledgeFileChunks)
async def file_chunks(file_id: str, request: Request) -> KnowledgeFileChunks:
    catalog = _catalog(request)
    try:
        result = await catalog.file_chunks(file_id)
    except ProviderUnavailable:
        raise HTTPException(
            status_code=503,
            detail="KNOWLEDGE_UNAVAILABLE",
        ) from None
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="DOCUMENT_NOT_FOUND",
        )
    return result
