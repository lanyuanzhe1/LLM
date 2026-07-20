from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import cloud_configuration_issues
from app.core.errors import VectorStoreNotReady


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    store = request.app.state.container.vector_store
    if store is None:
        error = VectorStoreNotReady()
        return JSONResponse(
            status_code=error.status_code,
            content=error.to_dict(),
        )
    if cloud_configuration_issues(request.app.state.settings):
        return JSONResponse(
            status_code=503,
            content={
                "code": "CLOUD_CONFIG_NOT_READY",
                "message": "云端服务配置尚未就绪",
                "retryable": False,
            },
        )
    return {
        "status": "ready",
        "vectors": len(store.metadata),
        "dimension": store.dimension,
    }
