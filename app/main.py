import logging
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import cases, chat, health, sources
from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.clients.iflytek_maas import IflytekMaaSClient
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.config import (
    Settings,
    cloud_configuration_issues,
    get_settings,
)
from app.core.errors import AppError, ConfigurationError, VectorStoreNotReady
from app.core.observability import RequestIdMiddleware
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.domain.cases.rules import CaseEvaluator
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.services.citation_validation import CitationValidator
from app.services.generation import GenerationService
from app.tools.routes import router as tools_router


class Closeable(Protocol):
    def close(self) -> Awaitable[None]: ...


_startup_closeables: ContextVar[list[Closeable] | None] = ContextVar(
    "startup_closeables",
    default=None,
)


def _register_startup_closeable(item: Closeable) -> None:
    closeables = _startup_closeables.get()
    if closeables is not None:
        closeables.append(item)


class UnavailableRetriever:
    def __init__(self, error: VectorStoreNotReady) -> None:
        self.error = error

    async def retrieve(self, request):
        raise self.error


def build_container(
    settings: Settings,
) -> tuple[ServiceContainer, tuple[Closeable, ...]]:
    embedding_key = settings.xf_embedding_api_key.get_secret_value()
    embedding_secret = settings.xf_embedding_api_secret.get_secret_value()
    maas_key = settings.xf_maas_api_key.get_secret_value()
    maas_secret = settings.xf_maas_api_secret.get_secret_value()
    workflow_key = settings.xf_workflow_api_key.get_secret_value()
    workflow_secret = settings.xf_workflow_api_secret.get_secret_value()

    try:
        store = VectorStore.load(settings.vector_store_dir)
    except VectorStoreNotReady as exc:
        store = None
        unavailable_error = exc

    embedding = IflytekEmbeddingClient(
        app_id=settings.xf_app_id,
        api_key=embedding_key,
        api_secret=embedding_secret,
        url=settings.embedding_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    _register_startup_closeable(embedding)
    if store is None:
        retriever: Any = UnavailableRetriever(unavailable_error)
    else:
        retriever = Retriever(
            store=store,
            embedding=embedding,
            min_score=settings.retrieval_min_score,
        )

    maas = IflytekMaaSClient(
        app_id=settings.xf_app_id,
        api_key=maas_key,
        api_secret=maas_secret,
        resource_id=settings.xf_maas_resource_id,
        service_id=settings.xf_maas_service_id,
        url=settings.maas_url,
        timeout_seconds=settings.maas_timeout_seconds,
        max_frames=settings.maas_max_frames,
        max_payload_bytes=settings.maas_max_payload_bytes,
        max_answer_chars=settings.maas_max_answer_chars,
    )
    _register_startup_closeable(maas)
    workflow = XingchenWorkflowClient(
        api_key=workflow_key,
        api_secret=workflow_secret,
        flow_id=settings.xf_workflow_flow_id,
        url=settings.workflow_url,
        timeout_seconds=settings.workflow_timeout_seconds,
        max_frames=settings.workflow_max_frames,
        max_payload_bytes=settings.workflow_max_payload_bytes,
        max_answer_chars=settings.workflow_max_answer_chars,
    )
    _register_startup_closeable(workflow)
    container = ServiceContainer(
        retriever=retriever,
        generation=GenerationService(maas),
        cases=CaseEvaluator(),
        citations=CitationValidator(),
        contexts=RequestContextStore(settings.request_context_ttl_seconds),
        vector_store=store,
        workflow=workflow,
    )
    return container, (embedding, maas, workflow)


async def _close_all(closeables: tuple[Closeable, ...]) -> None:
    first_error: BaseException | None = None
    for item in closeables:
        try:
            await item.close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def create_app(
    *,
    settings: Settings | Any | None = None,
    container: ServiceContainer | None = None,
) -> FastAPI:
    resolved_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal resolved_settings
        closeables: tuple[Closeable, ...] = ()
        resolved_settings = resolved_settings or get_settings()
        app.state.settings = resolved_settings
        log_level = str(
            getattr(resolved_settings, "log_level", "INFO")
        ).upper()
        configured_level = getattr(logging, log_level, logging.INFO)
        logging.getLogger().setLevel(configured_level)
        logging.getLogger("grain_core").setLevel(configured_level)
        if container is None:
            if cloud_configuration_issues(resolved_settings):
                raise ConfigurationError("运行时配置无效")
            startup_closeables: list[Closeable] = []
            token = _startup_closeables.set(startup_closeables)
            try:
                try:
                    app.state.container, closeables = build_container(
                        resolved_settings
                    )
                except BaseException:
                    await _close_all(tuple(startup_closeables))
                    raise
            finally:
                _startup_closeables.reset(token)
        else:
            app.state.container = container
        try:
            yield
        finally:
            await _close_all(closeables)

    application = FastAPI(
        title="粮储智研助手技术实体",
        lifespan=lifespan,
    )
    if resolved_settings is not None:
        application.state.settings = resolved_settings
    if container is not None:
        application.state.container = container
    application.add_middleware(RequestIdMiddleware)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        detail = [
            {
                "loc": [
                    item if isinstance(item, (str, int)) else str(item)
                    for item in error.get("loc", ())
                ],
                "msg": str(error.get("msg", "Invalid request")),
                "type": str(error.get("type", "validation_error")),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @application.exception_handler(AppError)
    async def app_error_handler(
        request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_dict(),
        )

    application.include_router(health.router)
    application.include_router(chat.router)
    application.include_router(cases.router)
    application.include_router(sources.router)
    application.include_router(tools_router)
    return application


app = create_app()
