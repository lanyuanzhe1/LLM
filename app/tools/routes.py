import inspect
import logging
import secrets
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.routing import APIRoute

from app.core.errors import AppError
from app.schemas.tools import (
    CaseEvaluateRequest,
    CaseEvaluateResponse,
    CitationValidateRequest,
    CitationValidateResponse,
    GenerateRequest,
    GenerateResponse,
    RetrieveRequest,
    RetrieveResponse,
)


logger = logging.getLogger("grain_core.tools")


def _authorize(request: Request) -> None:
    authorization = request.headers.get("Authorization")
    if not authorization:
        raise HTTPException(status_code=401, detail="invalid tool token")

    try:
        token = request.app.state.settings.tools_service_token.get_secret_value()
    except Exception:
        raise HTTPException(status_code=401, detail="invalid tool token") from None

    if not isinstance(token, str) or not token.strip():
        raise HTTPException(status_code=401, detail="invalid tool token")

    try:
        supplied = authorization.encode("ascii")
        expected = ("Bearer " + token).encode("ascii")
    except UnicodeEncodeError:
        raise HTTPException(
            status_code=401,
            detail="invalid tool token",
        ) from None
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid tool token")


class AuthenticatedToolRoute(APIRoute):
    def get_route_handler(self) -> Callable:
        route_handler = super().get_route_handler()

        async def authenticated(request: Request):
            _authorize(request)
            return await route_handler(request)

        return authenticated


router = APIRouter(
    prefix="/tools/v1",
    tags=["xingchen-tools"],
    route_class=AuthenticatedToolRoute,
)


def _citation_ids(response: Any) -> list[str]:
    for field_name in ("citation_ids", "cited_evidence_ids"):
        value = getattr(response, field_name, None)
        if value is not None:
            return list(value)
    evidences = getattr(response, "evidences", None)
    if evidences is not None:
        return [evidence.evidence_id for evidence in evidences]
    return []


async def _execute_tool(
    *,
    request_id: str,
    tool_name: str,
    operation: Callable[[], Any],
) -> Any:
    started = time.monotonic()
    result_code = "INTERNAL_ERROR"
    citation_ids: list[str] = []
    try:
        response = operation()
        if inspect.isawaitable(response):
            response = await response
        result_code = "OK"
        citation_ids = _citation_ids(response)
        return response
    except AppError as exc:
        result_code = exc.code
        raise
    finally:
        logger.info(
            "tool_completed",
            extra={
                "event": "tool_completed",
                "request_id": request_id,
                "node_name": tool_name,
                "tool_name": tool_name,
                "elapsed_ms": round(
                    (time.monotonic() - started) * 1000,
                    2,
                ),
                "result_code": result_code,
                "citation_ids": citation_ids,
            },
        )


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    payload: RetrieveRequest,
    request: Request,
) -> RetrieveResponse:
    async def operation() -> RetrieveResponse:
        response = await request.app.state.container.retriever.retrieve(
            payload
        )
        await request.app.state.container.contexts.set_retrieval_result(
            payload.request_id,
            response.evidences,
            sufficient=response.quality.sufficient,
        )
        return response

    return await _execute_tool(
        request_id=payload.request_id,
        tool_name="retrieve",
        operation=operation,
    )


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    request: Request,
) -> GenerateResponse:
    return await _execute_tool(
        request_id=payload.request_id,
        tool_name="generate",
        operation=lambda: request.app.state.container.generation.generate(
            payload
        ),
    )


@router.post("/cases/evaluate", response_model=CaseEvaluateResponse)
async def evaluate_case(
    payload: CaseEvaluateRequest,
    request: Request,
) -> CaseEvaluateResponse:
    async def operation() -> CaseEvaluateResponse:
        response = request.app.state.container.cases.evaluate(payload)
        await request.app.state.container.contexts.set_case_result(
            payload.request_id,
            needs_input=response.needs_input,
            missing_fields=response.missing_fields,
            question=response.question,
        )
        return response

    return await _execute_tool(
        request_id=payload.request_id,
        tool_name="cases.evaluate",
        operation=operation,
    )


@router.post("/citations/validate", response_model=CitationValidateResponse)
async def validate_citations(
    payload: CitationValidateRequest,
    request: Request,
) -> CitationValidateResponse:
    async def operation() -> CitationValidateResponse:
        state = (
            await request.app.state.container.contexts.get_retrieval_state(
                payload.request_id
            )
        )
        trusted_by_id = {
            evidence.evidence_id: evidence
            for evidence in (
                state.evidences if state is not None else ()
            )
        }
        reconciled = (
            state is not None
            and len(trusted_by_id) == len(state.evidences)
            and all(
                candidate.evidence_id in trusted_by_id
                and candidate.model_dump(mode="python")
                == trusted_by_id[candidate.evidence_id].model_dump(
                    mode="python"
                )
                for candidate in payload.evidences
            )
        )
        if not reconciled:
            if state is not None:
                await request.app.state.container.contexts.reconcile_and_set_validation(
                    payload.request_id,
                    revision=state.revision,
                    submitted_evidences=payload.evidences,
                    valid=False,
                    answer=payload.answer,
                    citation_ids=[],
                )
            return CitationValidateResponse(
                request_id=payload.request_id,
                valid=False,
                errors=["证据上下文校验失败"],
                unsupported_sentences=[],
                citation_ids=[],
            )
        trusted_payload = payload.model_copy(
            update={
                "evidences": [
                    trusted_by_id[candidate.evidence_id]
                    for candidate in payload.evidences
                ]
            }
        )
        response = request.app.state.container.citations.validate(
            trusted_payload
        )
        committed = await request.app.state.container.contexts.reconcile_and_set_validation(
            payload.request_id,
            revision=state.revision,
            submitted_evidences=payload.evidences,
            valid=response.valid,
            answer=payload.answer,
            citation_ids=response.citation_ids,
        )
        if not committed:
            return CitationValidateResponse(
                request_id=payload.request_id,
                valid=False,
                errors=["证据上下文校验失败"],
                unsupported_sentences=[],
                citation_ids=[],
            )
        return response

    return await _execute_tool(
        request_id=payload.request_id,
        tool_name="citations.validate",
        operation=operation,
    )
