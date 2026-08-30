import logging
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Protocol

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import cases, chat, health, knowledge, openai_compat, sources
from app.clients.iflytek_chatdoc import IflytekChatDocClient
from app.clients.iflytek_maas import IflytekMaaSClient
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.config import (
    Settings,
    cloud_configuration_issues,
    get_settings,
)
from app.core.errors import AppError, ConfigurationError
from app.core.observability import RequestIdMiddleware
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.domain.cases.rules import CaseEvaluator
from app.rag.chatdoc_retriever import ChatDocRetriever, load_chatdoc_manifest
from app.services.citation_validation import CitationValidator
from app.services.generation import GenerationService
from app.services.knowledge_catalog import KnowledgeCatalog
from app.services.local_workflow import LocalWorkflow
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


def build_container(
    settings: Settings,
) -> tuple[ServiceContainer, tuple[Closeable, ...]]:
    chatdoc_secret = settings.xf_embedding_api_secret.get_secret_value()
    maas_key = settings.xf_maas_api_key.get_secret_value()
    maas_secret = settings.xf_maas_api_secret.get_secret_value()
    workflow_key = settings.xf_workflow_api_key.get_secret_value()
    workflow_secret = settings.xf_workflow_api_secret.get_secret_value()

    owned_closeables: list[Closeable] = []
    if not settings.xf_chatdoc_repo_id:
        raise ConfigurationError("必须配置讯飞 ChatDoc 知识库")
    try:
        manifest = load_chatdoc_manifest(settings.chatdoc_manifest_path)
    except (OSError, ValueError, TypeError) as exc:
        raise ConfigurationError("讯飞知识库清单无效") from exc
    if manifest.repo_id != settings.xf_chatdoc_repo_id:
        raise ConfigurationError("讯飞知识库配置与清单不一致")
    chatdoc = IflytekChatDocClient(
        app_id=settings.xf_app_id,
        api_secret=chatdoc_secret,
        base_url=settings.chatdoc_url,
        timeout_seconds=settings.chatdoc_timeout_seconds,
    )
    _register_startup_closeable(chatdoc)
    owned_closeables.append(chatdoc)
    retriever: Any = ChatDocRetriever(
        client=chatdoc,
        manifest=manifest,
        min_score=settings.retrieval_min_score,
    )
    knowledge = KnowledgeCatalog(client=chatdoc, manifest=manifest)

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
    owned_closeables.append(maas)
    generation = GenerationService(maas)
    cases = CaseEvaluator()
    citations = CitationValidator()
    contexts = RequestContextStore(settings.request_context_ttl_seconds)
    workflow_provider = getattr(settings, "workflow_provider", "local")
    if workflow_provider == "local":
        # 进程内编排器：与 XingchenWorkflowClient 同一 stream 帧流接口，
        # 无网络资源，不注册 close()
        workflow: Any = LocalWorkflow(
            retriever=retriever,
            generation=generation,
            cases=cases,
            citations=citations,
            contexts=contexts,
        )
    else:
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
        owned_closeables.append(workflow)
    container = ServiceContainer(
        retriever=retriever,
        generation=generation,
        cases=cases,
        citations=citations,
        contexts=contexts,
        workflow=workflow,
        knowledge=knowledge,
    )
    return container, tuple(owned_closeables)


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
    application.middleware("http")(openai_compat.auth_middleware)

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if request.url.path == "/v1/chat/completions":
            return openai_compat.openai_error_response(
                status_code=422,
                message="聊天请求无效",
                error_type="invalid_request_error",
                code="invalid_request_error",
            )
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
    application.include_router(openai_compat.router)
    application.include_router(chat.router)
    application.include_router(cases.router)
    application.include_router(sources.router)
    application.include_router(knowledge.router)
    application.include_router(tools_router)
    return application


app = create_app()
