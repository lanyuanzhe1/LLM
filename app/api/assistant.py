import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.schemas.api import AssistantChatRequest
from app.services.assistant_chat import stream_assistant


router = APIRouter(prefix="/v1", tags=["assistant"])

# 白名单：仅放行 plaza 里已接线配置的讯飞智能体，防止 app_id 凭据被任意 assistant_id 复用。
# 与 frontend/plaza/src/configs/agents.ts 的 assistantId 字段保持一致。
_ALLOWED_ASSISTANT_IDS: frozenset[str] = frozenset(
    {
        "kpevnp8z2ff2_v1",  # 粮食行业知识库智能体
        "xyzrra1uxi9w_v1",  # 助教智能体·星廪智枢
        "khhye2gs67wy_v1",  # 粮食仓储科研智能体·星廪智枢
        "xou2bntqeaa5_v1",  # 助学智能体·星廪智枢
    }
)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/assistant/chat", response_model=None)
async def assistant_chat(
    payload: AssistantChatRequest,
    request: Request,
) -> StreamingResponse | JSONResponse:
    settings = request.app.state.settings
    api_key = settings.xf_assistant_api_key
    api_secret = settings.xf_assistant_api_secret
    app_id = settings.xf_assistant_app_id
    if not (api_key and api_secret and app_id):
        return JSONResponse(
            status_code=503,
            content={
                "code": "ASSISTANT_NOT_CONFIGURED",
                "message": "智能体 API 凭据未配置，请联系管理员补充 XF_ASSISTANT_* 配置。",
            },
        )

    if payload.assistant_id not in _ALLOWED_ASSISTANT_IDS:
        return JSONResponse(
            status_code=400,
            content={
                "code": "ASSISTANT_NOT_ALLOWED",
                "message": f"assistant_id {payload.assistant_id!r} 不在本服务白名单内。",
            },
        )

    secret_key = api_key.get_secret_value()
    secret = api_secret.get_secret_value()
    turns = [turn.model_dump() for turn in payload.messages]

    async def events() -> AsyncIterator[str]:
        async for event, data in stream_assistant(
            assistant_id=payload.assistant_id,
            url_base=settings.assistant_api_url,
            api_key=secret_key,
            api_secret=secret,
            app_id=app_id,
            # uid 仅为转发给讯飞的多轮会话连续性标签，不是安全边界：本服务无用户体系，
            # 后端不按 uid 存储任何数据，伪造它最多影响调用方自己的会话延续（无跨用户数据可越权）。
            # 匿名缺省用服务端随机 uuid，避免共用缺省值导致会话串扰。待将来接入登录后再绑定账号。
            uid=payload.uid or uuid.uuid4().hex,
            messages=turns,
            timeout_seconds=settings.workflow_timeout_seconds,
        ):
            yield _sse(event, data)
        yield _sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
