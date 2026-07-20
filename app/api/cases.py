from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import CaseAnalyzeRequest
from app.services.workflow_gateway import WorkflowGateway


router = APIRouter(prefix="/v1/cases", tags=["cases"])


@router.post("/analyze")
async def analyze(
    payload: CaseAnalyzeRequest,
    request: Request,
) -> StreamingResponse:
    container = request.app.state.container
    gateway = WorkflowGateway(
        workflow=container.workflow,
        contexts=container.contexts,
        max_buffer_chars=request.app.state.settings.gateway_max_buffer_chars,
    )
    return StreamingResponse(
        gateway.stream(
            message=payload.case.goal or "分析储粮安全案例",
            request_id=request.state.request_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            role=payload.role,
            task_type="case_analysis",
            case=payload.case,
            project_id=payload.project_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
