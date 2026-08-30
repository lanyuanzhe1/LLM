import hmac
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import SecretStr

from app.schemas.api import Role
from app.schemas.openai_compat import (
    ChatCompletionRequest,
    validate_forwarded_identifier,
)
from app.services.openai_compat import (
    OpenAICompatUpstreamError,
    build_workflow_message,
    collect_openai_completion,
    openai_stream,
    preflight_openai_stream,
)
from app.services.workflow_gateway import WorkflowGateway


router = APIRouter(prefix="/v1", tags=["openai-compatible"])


def openai_error_response(
    *,
    status_code: int,
    message: str,
    error_type: str,
    code: str,
) -> JSONResponse:
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if status_code == 401
        else None
    )
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": None,
                "code": code,
            }
        },
    )


def _configured_key(request: Request) -> str:
    configured = request.app.state.settings.openai_compat_api_key
    if isinstance(configured, SecretStr):
        return configured.get_secret_value()
    return str(configured)


def _authorized(request: Request) -> bool:
    authorization = request.headers.get("Authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or not supplied
        or " " in supplied
    ):
        return False
    expected = _configured_key(request)
    return hmac.compare_digest(
        supplied.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _require_authorized(request: Request) -> JSONResponse | None:
    if _authorized(request):
        return None
    return openai_error_response(
        status_code=401,
        message="API 密钥无效",
        error_type="invalid_request_error",
        code="invalid_api_key",
    )


async def auth_middleware(request: Request, call_next):
    protected_route = (
        request.method == "GET"
        and request.url.path == "/v1/models"
    ) or (
        request.method == "POST"
        and request.url.path == "/v1/chat/completions"
    )
    if protected_route:
        unauthorized = _require_authorized(request)
        if unauthorized is not None:
            return unauthorized
    return await call_next(request)


@router.get("/models")
async def list_models(request: Request):
    model = request.app.state.settings.openai_compat_model_id
    return {
        "object": "list",
        "data": [
            {
                "id": model,
                "name": (
                    request.app.state.settings.openai_compat_model_name
                ),
                "object": "model",
                "created": 0,
                "owned_by": "grain-learning",
            }
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest,
    request: Request,
):
    configured_model = request.app.state.settings.openai_compat_model_id
    if payload.model != configured_model:
        return openai_error_response(
            status_code=404,
            message=f"模型 {payload.model} 不存在",
            error_type="invalid_request_error",
            code="model_not_found",
        )

    try:
        session_id = validate_forwarded_identifier(
            request.headers.get("X-OpenWebUI-Chat-Id"),
            "X-OpenWebUI-Chat-Id",
        )
        user_id = validate_forwarded_identifier(
            request.headers.get("X-OpenWebUI-User-Id"),
            "X-OpenWebUI-User-Id",
        )
    except ValueError:
        return openai_error_response(
            status_code=400,
            message="Open WebUI 转发标识无效",
            error_type="invalid_request_error",
            code="invalid_request_error",
        )

    container = request.app.state.container
    settings = request.app.state.settings
    user_message = build_workflow_message(
        [(item.role, item.content) for item in payload.messages],
        enabled=settings.openai_compat_history_enabled,
        max_turns=settings.openai_compat_history_max_turns,
        max_chars=settings.openai_compat_history_max_chars,
    )
    task_type = "knowledge_qa"
    gateway = WorkflowGateway(
        workflow=container.workflow,
        contexts=container.contexts,
        max_buffer_chars=request.app.state.settings.gateway_max_buffer_chars,
    )
    events = gateway.stream(
        message=user_message,
        request_id=request.state.request_id,
        session_id=session_id,
        user_id=user_id,
        role=Role.STUDENT,
        task_type=task_type,
        project_id=(
            request.app.state.settings.openai_compat_project_id
        ),
    )
    completion_id = f"chatcmpl-{request.state.request_id}"
    created = int(time.time())
    emit_openwebui_status = (
        session_id is not None or user_id is not None
    )

    if payload.stream:
        try:
            events = await preflight_openai_stream(
                events,
                return_after_meta=emit_openwebui_status,
            )
        except OpenAICompatUpstreamError as exc:
            return openai_error_response(
                status_code=502,
                message=exc.message,
                error_type="server_error",
                code=exc.code,
            )
        return StreamingResponse(
            openai_stream(
                events,
                completion_id=completion_id,
                model=configured_model,
                created=created,
                emit_openwebui_status=emit_openwebui_status,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        return await collect_openai_completion(
            events,
            completion_id=completion_id,
            model=configured_model,
            created=created,
        )
    except OpenAICompatUpstreamError as exc:
        return openai_error_response(
            status_code=502,
            message=exc.message,
            error_type="server_error",
            code=exc.code,
        )
