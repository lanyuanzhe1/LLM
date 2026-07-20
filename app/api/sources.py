from fastapi import APIRouter, HTTPException, Request

from app.rag.evidence import Evidence


router = APIRouter(prefix="/v1/sources", tags=["sources"])


@router.get("/{evidence_id:path}", response_model=Evidence)
async def source(evidence_id: str, request: Request) -> Evidence:
    store = request.app.state.container.vector_store
    evidence = store.get_evidence(evidence_id) if store is not None else None
    if evidence is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    return evidence
