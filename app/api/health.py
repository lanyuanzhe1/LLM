from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import cloud_configuration_issues


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    retriever = request.app.state.container.retriever
    ready_details = getattr(retriever, "ready_details", None)
    if callable(ready_details):
        if cloud_configuration_issues(request.app.state.settings):
            return JSONResponse(
                status_code=503,
                content={
                    "code": "CLOUD_CONFIG_NOT_READY",
                    "message": "云端服务配置尚未就绪",
                    "retryable": False,
                },
            )
        return ready_details()
    return JSONResponse(
        status_code=503,
        content={
            "code": "CHATDOC_NOT_READY",
            "message": "讯飞 ChatDoc 检索服务尚未就绪",
            "retryable": False,
        },
    )
