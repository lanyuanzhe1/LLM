from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import ChatRequest
from app.services.workflow_gateway import WorkflowGateway


router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    container = request.app.state.container
    gateway = WorkflowGateway(
        workflow=container.workflow,
        contexts=container.contexts,
        max_buffer_chars=request.app.state.settings.gateway_max_buffer_chars,
    )
    return StreamingResponse(
        gateway.stream(
            message=payload.message,
            request_id=request.state.request_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            role=payload.role,
            task_type="knowledge_qa",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
