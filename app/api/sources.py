from fastapi import APIRouter, HTTPException, Request

from app.rag.evidence import Evidence


router = APIRouter(prefix="/v1/sources", tags=["sources"])


@router.get("/{evidence_id:path}", response_model=Evidence)
async def source(evidence_id: str, request: Request) -> Evidence:
    retriever = request.app.state.container.retriever
    resolver = getattr(retriever, "get_evidence", None)
    evidence = resolver(evidence_id) if callable(resolver) else None
    if evidence is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    return evidence
