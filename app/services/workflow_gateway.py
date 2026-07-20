import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

from app.core.errors import AppError
from app.core.request_context import RequestContextStore
from app.schemas.api import CaseData, Role
from app.schemas.events import DoneEvent, ErrorEvent, sse


_UNEXPECTED_ERROR = ErrorEvent(
    code="WORKFLOW_UNAVAILABLE",
    message="智能体工作流暂时不可用",
    retryable=True,
)
_PROTOCOL_ERROR = ErrorEvent(
    code="WORKFLOW_PROTOCOL_ERROR",
    message="智能体工作流响应未通过安全校验",
    retryable=False,
)
_INSUFFICIENT_REFUSAL = "知识库证据不足，无法提供可靠回答。"
_VALIDATION_FAILED_REFUSAL = "回答未通过引用验证，无法安全展示生成内容。"
logger = logging.getLogger("grain_core.workflow")


class _WorkflowBufferExceeded(Exception):
    pass


class WorkflowGateway:
    def __init__(
        self,
        *,
        workflow: Any,
        contexts: RequestContextStore,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        max_buffer_chars: int = 32_000,
    ) -> None:
        self.workflow = workflow
        self.contexts = contexts
        self.id_factory = id_factory
        self.max_buffer_chars = max_buffer_chars

    async def stream(
        self,
        *,
        message: str,
        request_id: str | None = None,
        session_id: str | None,
        user_id: str | None,
        role: Role,
        task_type: str,
        case: CaseData | None = None,
        project_id: str | None = None,
    ) -> AsyncIterator[str]:
        resolved_request_id = request_id or self.id_factory()
        resolved_session_id = session_id or str(uuid.uuid4())
        uid = (user_id or resolved_session_id)[:128]
        parameters = {
            "AGENT_USER_INPUT": message,
            "REQUEST_ID": resolved_request_id,
            "SESSION_ID": resolved_session_id,
            "USER_ROLE": role.value,
            "TASK_TYPE": task_type,
            "CASE_JSON": (
                json.dumps(case.model_dump(mode="json"), ensure_ascii=False)
                if case is not None
                else ""
            ),
            "PROJECT_ID": project_id or "",
        }
        context_consumed = False
        terminal_logged = False
        started = time.monotonic()

        async def consume_context():
            nonlocal context_consumed
            if context_consumed:
                return None
            context = await self.contexts.pop(resolved_request_id)
            context_consumed = True
            return context

        def log_terminal(
            *,
            finish_reason: str,
            result_code: str,
            citation_ids: list[str],
        ) -> None:
            nonlocal terminal_logged
            if terminal_logged:
                return
            terminal_logged = True
            logger.info(
                "workflow_terminal",
                extra={
                    "event": "workflow_terminal",
                    "request_id": resolved_request_id,
                    "node_name": "gateway",
                    "elapsed_ms": round(
                        (time.monotonic() - started) * 1000,
                        2,
                    ),
                    "result_code": result_code,
                    "finish_reason": finish_reason,
                    "citation_ids": list(citation_ids),
                },
            )

        try:
            yield sse(
                "meta",
                {
                    "request_id": resolved_request_id,
                    "session_id": resolved_session_id,
                },
            )
            buffered_deltas: list[str] = []
            buffered_chars = 0
            provider_stream = self.workflow.stream(parameters, uid=uid)
            try:
                async for frame in provider_stream:
                    for choice in frame.choices:
                        content = choice.delta.content
                        if not content:
                            continue
                        buffered_chars += len(content)
                        if buffered_chars > self.max_buffer_chars:
                            raise _WorkflowBufferExceeded
                        buffered_deltas.append(content)
            finally:
                close = getattr(provider_stream, "aclose", None)
                if close is not None:
                    await close()

            context = await consume_context()
            buffered_answer = "".join(buffered_deltas)
            if context is not None and context.needs_input:
                if context.question is None:
                    log_terminal(
                        finish_reason="error",
                        result_code=_PROTOCOL_ERROR.code,
                        citation_ids=[],
                    )
                    yield sse("error", _PROTOCOL_ERROR)
                    return
                yield sse("delta", {"content": context.question})
                yield sse("citations", {"items": []})
                log_terminal(
                    finish_reason="needs_input",
                    result_code="NEEDS_INPUT",
                    citation_ids=[],
                )
                yield sse(
                    "done",
                    DoneEvent(
                        finish_reason="needs_input",
                        missing_fields=context.missing_fields,
                    ),
                )
                return

            if (
                context is not None
                and context.retrieval_sufficient is False
            ):
                yield sse(
                    "delta",
                    {"content": _INSUFFICIENT_REFUSAL},
                )
                yield sse("citations", {"items": []})
                log_terminal(
                    finish_reason="stop",
                    result_code="EVIDENCE_INSUFFICIENT",
                    citation_ids=[],
                )
                yield sse("done", DoneEvent())
                return

            retrieved_ids = (
                [
                    evidence.evidence_id
                    for evidence in context.evidences
                ]
                if context is not None
                else []
            )
            retrieved_id_set = set(retrieved_ids)
            citation_id_set = (
                set(context.citation_ids)
                if context is not None
                else set()
            )
            citations_resolve_exactly = (
                context is not None
                and len(retrieved_id_set) == len(retrieved_ids)
                and len(citation_id_set) == len(context.citation_ids)
                and citation_id_set <= retrieved_id_set
            )
            if (
                context is not None
                and context.retrieval_sufficient is True
                and context.validation_valid is True
                and buffered_answer == context.validated_answer
                and citations_resolve_exactly
            ):
                citations = [
                    evidence
                    for evidence in context.evidences
                    if evidence.evidence_id in citation_id_set
                ]
                for content in buffered_deltas:
                    yield sse("delta", {"content": content})
                yield sse(
                    "citations",
                    {
                        "items": [
                            evidence.model_dump(mode="json")
                            for evidence in citations
                        ]
                    },
                )
                log_terminal(
                    finish_reason="stop",
                    result_code="OK",
                    citation_ids=[
                        evidence.evidence_id for evidence in citations
                    ],
                )
                yield sse("done", DoneEvent())
                return

            if (
                context is not None
                and context.validation_valid is False
            ):
                citations = list(context.evidences)
                yield sse(
                    "delta",
                    {"content": _VALIDATION_FAILED_REFUSAL},
                )
                yield sse(
                    "citations",
                    {
                        "items": [
                            {"evidence_id": evidence.evidence_id}
                            for evidence in citations
                        ]
                    },
                )
                log_terminal(
                    finish_reason="stop",
                    result_code="VALIDATION_FAILED_FALLBACK",
                    citation_ids=[
                        evidence.evidence_id for evidence in citations
                    ],
                )
                yield sse("done", DoneEvent())
                return

            log_terminal(
                finish_reason="error",
                result_code=_PROTOCOL_ERROR.code,
                citation_ids=[],
            )
            yield sse("error", _PROTOCOL_ERROR)
        except _WorkflowBufferExceeded:
            await consume_context()
            log_terminal(
                finish_reason="error",
                result_code=_PROTOCOL_ERROR.code,
                citation_ids=[],
            )
            yield sse("error", _PROTOCOL_ERROR)
        except AppError as exc:
            await consume_context()
            log_terminal(
                finish_reason="error",
                result_code=exc.code,
                citation_ids=[],
            )
            yield sse(
                "error",
                ErrorEvent(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
        except Exception:
            await consume_context()
            log_terminal(
                finish_reason="error",
                result_code=_UNEXPECTED_ERROR.code,
                citation_ids=[],
            )
            yield sse("error", _UNEXPECTED_ERROR)
        finally:
            await consume_context()
            if not terminal_logged:
                log_terminal(
                    finish_reason="error",
                    result_code="STREAM_CLOSED",
                    citation_ids=[],
                )
