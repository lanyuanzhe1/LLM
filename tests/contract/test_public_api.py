import json
import logging
import re
import uuid
import warnings
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import SecretStr
from starlette.exceptions import StarletteDeprecationWarning

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=(
            "Using `httpx` with `starlette.testclient` is deprecated; "
            "install `httpx2` instead\\."
        ),
        category=StarletteDeprecationWarning,
    )
    from fastapi.testclient import TestClient

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.core.config import Settings
from app.core.errors import VectorStoreNotReady
from app.core.observability import RequestIdMiddleware
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.rag.evidence import Evidence
from app.rag.vector_store import VectorStore
from app.schemas.events import WorkflowFrame
from app.schemas.tools import (
    CitationValidateResponse,
    RetrievalQuality,
    RetrieveResponse,
)


class FakeWorkflow:
    def __init__(self, contexts: RequestContextStore) -> None:
        self.contexts = contexts
        self.calls: list[tuple[dict, str]] = []

    async def stream(self, parameters: dict, uid: str):
        self.calls.append((parameters, uid))
        await self.contexts.set_retrieval_result(
            parameters["REQUEST_ID"],
            [EVIDENCE],
            sufficient=True,
        )
        await self.contexts.set_validation_result(
            parameters["REQUEST_ID"],
            valid=True,
            answer="回答",
            citation_ids=[EVIDENCE.evidence_id],
        )
        yield WorkflowFrame.model_validate(
            {
                "code": 0,
                "message": "Success",
                "id": "sid",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "回答"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )


class FailingRetriever:
    async def retrieve(self, request):
        raise VectorStoreNotReady()


class EmbeddingFailureRetriever:
    def __init__(self, embedding: IflytekEmbeddingClient) -> None:
        self.embedding = embedding

    async def retrieve(self, request):
        await self.embedding.embed(request.query, domain="query")
        raise AssertionError("unreachable")


class CorrelatedRetriever:
    async def retrieve(self, request):
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=[EVIDENCE],
            quality=RetrievalQuality(
                top_score=EVIDENCE.score,
                sufficient=True,
            ),
        )


class CorrelatedValidator:
    def validate(self, request):
        return CitationValidateResponse(
            request_id=request.request_id,
            valid=True,
            errors=[],
            unsupported_sentences=[],
            citation_ids=[EVIDENCE.evidence_id],
            coverage={
                "total_sentences": 1,
                "cited_sentences": 1,
                "ratio": 1.0,
            },
        )


class InProcessToolWorkflow:
    answer = "已验证回答"

    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.calls: list[tuple[dict, str]] = []
        self.tool_response_ids: list[tuple[str, str]] = []

    async def stream(self, parameters: dict, uid: str):
        assert self.app is not None
        self.calls.append((parameters, uid))
        request_id = parameters["REQUEST_ID"]
        headers = {"Authorization": "Bearer tool-token"}
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://in-process",
        ) as client:
            retrieved = await client.post(
                "/tools/v1/retrieve",
                headers=headers,
                json={
                    "request_id": request_id,
                    "query": parameters["AGENT_USER_INPUT"],
                },
            )
            retrieved.raise_for_status()
            retrieved_payload = retrieved.json()
            validated = await client.post(
                "/tools/v1/citations/validate",
                headers=headers,
                json={
                    "request_id": request_id,
                    "answer": self.answer,
                    "evidences": retrieved_payload["evidences"],
                },
            )
            validated.raise_for_status()
            self.tool_response_ids.extend(
                [
                    ("retrieve", retrieved_payload["request_id"]),
                    (
                        "citations.validate",
                        validated.json()["request_id"],
                    ),
                ]
            )

        yield WorkflowFrame.model_validate(
            {
                "code": 0,
                "message": "Success",
                "id": "sid",
                "choices": [
                    {
                        "delta": {
                            "role": "assistant",
                            "content": self.answer,
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )


class FakeStore:
    def __init__(self, evidence: Evidence | None = None) -> None:
        self.metadata = [{}, {}, {}]
        self.dimension = 2560
        self.evidence = evidence
        self.requested_ids: list[str] = []

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        self.requested_ids.append(evidence_id)
        if self.evidence and self.evidence.evidence_id == evidence_id:
            return self.evidence.model_copy(update={"score": None})
        return None


EVIDENCE = Evidence(
    evidence_id="folder/item:id",
    document_id="sha256:document",
    title="低温储粮",
    source="knowledge/test.pdf",
    page=3,
    text="低温可以抑制储粮害虫活动。",
    score=0.88,
)


def settings(vector_store_dir: Path | None = None, **overrides):
    values = {
        "xf_app_id": "app-id",
        "xf_embedding_api_key": SecretStr("embedding-key"),
        "xf_embedding_api_secret": SecretStr("embedding-secret"),
        "xf_maas_api_key": SecretStr("maas-key"),
        "xf_maas_api_secret": SecretStr("maas-secret"),
        "xf_maas_resource_id": "resource-id",
        "xf_maas_service_id": "service-id",
        "xf_workflow_api_key": SecretStr("workflow-key"),
        "xf_workflow_api_secret": SecretStr("workflow-secret"),
        "xf_workflow_flow_id": "flow-id",
        "tools_service_token": SecretStr("tool-token"),
        "vector_store_dir": vector_store_dir or Path("missing-vector-store"),
        "retrieval_min_score": 0.35,
        "embedding_url": "https://embedding.invalid/",
        "embedding_timeout_seconds": 1,
        "maas_url": "wss://maas.invalid/v1/chat",
        "maas_timeout_seconds": 1,
        "maas_max_frames": 1024,
        "maas_max_payload_bytes": 2_097_152,
        "maas_max_answer_chars": 32_000,
        "workflow_url": "https://workflow.invalid/v1/chat",
        "workflow_timeout_seconds": 1,
        "workflow_max_frames": 1024,
        "workflow_max_payload_bytes": 2_097_152,
        "workflow_max_answer_chars": 32_000,
        "gateway_max_buffer_chars": 32_000,
        "request_context_ttl_seconds": 300,
        "log_level": "INFO",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def container(
    *,
    vector_store=None,
    retriever=None,
    workflow=None,
    contexts=None,
) -> ServiceContainer:
    resolved_contexts = contexts or RequestContextStore(ttl_seconds=300)
    return ServiceContainer(
        retriever=retriever,
        generation=None,
        cases=None,
        citations=None,
        contexts=resolved_contexts,
        vector_store=vector_store,
        workflow=workflow or FakeWorkflow(resolved_contexts),
    )


def make_client(
    *,
    vector_store=None,
    retriever=None,
    workflow=None,
    contexts=None,
    app_settings=None,
) -> TestClient:
    from app.main import create_app

    return TestClient(
        create_app(
            settings=app_settings or settings(),
            container=container(
                vector_store=vector_store,
                retriever=retriever,
                workflow=workflow,
                contexts=contexts,
            ),
        )
    )


def test_importing_application_does_not_load_settings_or_open_network(
    monkeypatch,
):
    calls: list[tuple] = []

    import importlib
    import app.main

    with monkeypatch.context() as isolated:
        isolated.setattr(
            "app.core.config.get_settings",
            lambda: (_ for _ in ()).throw(
                AssertionError("settings loaded")
            ),
        )
        isolated.setattr(
            httpx.AsyncClient,
            "__init__",
            lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        importlib.reload(app.main)

    assert calls == []
    importlib.reload(app.main)


def test_health_is_live_and_ready_reports_missing_store():
    client = make_client()

    health = client.get("/health")
    ready = client.get("/ready")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert ready.status_code == 503
    assert ready.json() == {
        "code": "VECTOR_STORE_NOT_READY",
        "message": "向量库尚未就绪",
        "retryable": True,
    }


def test_ready_reports_vector_count_and_dimension():
    client = make_client(vector_store=FakeStore())

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "vectors": 3,
        "dimension": 2560,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("xf_app_id", " \t "),
        ("xf_maas_api_key", SecretStr(" \t ")),
    ],
)
def test_ready_rejects_blank_injected_cloud_configuration(field, value):
    client = make_client(
        vector_store=FakeStore(),
        app_settings=settings(**{field: value}),
    )

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "CLOUD_CONFIG_NOT_READY",
        "message": "云端服务配置尚未就绪",
        "retryable": False,
    }


def test_ready_rejects_missing_injected_cloud_configuration():
    incomplete = settings()
    del incomplete.xf_workflow_api_secret
    client = make_client(vector_store=FakeStore(), app_settings=incomplete)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "code": "CLOUD_CONFIG_NOT_READY",
        "message": "云端服务配置尚未就绪",
        "retryable": False,
    }


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/v1/chat",
            {"message": "低温储粮", "role": "student"},
        ),
        (
            "/v1/cases/analyze",
            {
                "role": "technician",
                "case": {
                    "grain_type": "小麦",
                    "storage_type": "平房仓",
                    "storage_days": 60,
                    "goal": "判断霉变风险",
                },
            },
        ),
    ],
)
def test_public_streams_use_exact_sse_contract_and_correlated_request_id(
    path, payload
):
    client = make_client()

    response = client.post(
        path,
        json=payload,
        headers={"X-Request-ID": "req-test_01:api"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "text/event-stream"
    )
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    server_request_id = response.headers["x-request-id"]
    assert server_request_id != "req-test_01:api"
    uuid_match = re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        server_request_id,
    )
    assert uuid_match
    event_lines = [
        line
        for line in response.text.splitlines()
        if line.startswith("event:")
    ]
    assert event_lines == [
        "event: meta",
        "event: delta",
        "event: citations",
        "event: done",
    ]
    assert f'"request_id": "{server_request_id}"' in response.text
    assert "req-test_01:api" not in response.text


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/v1/chat", {"message": "", "role": "student"}),
        ("/v1/chat", {"message": "ok", "role": "administrator"}),
        ("/v1/cases/analyze", {"case": {"storage_days": -1}}),
    ],
)
def test_public_request_validation_returns_422_with_request_id(path, payload):
    response = make_client().post(path, json=payload)

    assert response.status_code == 422
    assert response.headers["x-request-id"]
    assert response.json()["detail"]


@pytest.mark.parametrize("value", ["1e309", "NaN", "Infinity"])
def test_nonfinite_case_json_returns_safe_structured_422(value):
    client = make_client()
    response = client.post(
        "/v1/cases/analyze",
        content=f'{{"case":{{"co2_ppm":{value}}}}}',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]
    assert all("input" not in item and "ctx" not in item for item in payload["detail"])
    assert value not in response.text


@pytest.mark.parametrize("value", ["1e309", "NaN", "Infinity"])
def test_authenticated_tool_nonfinite_case_returns_safe_422(value):
    client = make_client()
    response = client.post(
        "/tools/v1/cases/evaluate",
        content=f'{{"request_id":"req","case":{{"co2_ppm":{value}}}}}',
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tool-token",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]
    assert value not in response.text


def test_source_returns_evidence_for_encoded_path_id():
    store = FakeStore(EVIDENCE)
    client = make_client(vector_store=store)
    encoded_id = quote(EVIDENCE.evidence_id, safe="")

    response = client.get(f"/v1/sources/{encoded_id}")

    assert response.status_code == 200
    assert response.json()["evidence_id"] == EVIDENCE.evidence_id
    assert response.json()["score"] is None
    assert store.requested_ids == [EVIDENCE.evidence_id]


@pytest.mark.parametrize("store", [None, FakeStore()])
def test_source_returns_404_for_missing_evidence_or_store(store):
    response = make_client(vector_store=store).get(
        "/v1/sources/sha256%3Amissing"
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "EVIDENCE_NOT_FOUND"}


@pytest.mark.parametrize(
    "supplied",
    [
        "contains a space",
        "line\r\nX-Injected: yes",
        "x" * 129,
        b"\xff",
    ],
)
def test_invalid_request_ids_are_replaced_and_never_reflected(supplied):
    response = make_client().get(
        "/health", headers={"X-Request-ID": supplied}
    )

    generated = response.headers["x-request-id"]
    assert response.status_code == 200
    assert generated != supplied
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        generated,
    )
    assert "x-injected" not in response.headers


def test_valid_maximum_length_client_request_id_is_not_authoritative():
    request_id = "a" * 128

    response = make_client().get(
        "/health", headers={"X-Request-ID": request_id}
    )

    generated = response.headers["x-request-id"]
    assert generated != request_id
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        generated,
    )


def test_app_errors_use_public_shape_and_request_id():
    client = make_client(retriever=FailingRetriever())

    response = client.post(
        "/tools/v1/retrieve",
        headers={
            "Authorization": "Bearer tool-token",
            "X-Request-ID": "public-error",
        },
        json={"request_id": "tool-request", "query": "低温"},
    )

    assert response.status_code == 503
    assert response.headers["x-request-id"] != "public-error"
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        response.headers["x-request-id"],
    )
    assert response.json() == {
        "code": "VECTOR_STORE_NOT_READY",
        "message": "向量库尚未就绪",
        "retryable": True,
    }


def test_embedding_provider_body_never_enters_api_error_response():
    sentinel = "RAW_EMBEDDING_API_RESPONSE_SECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "header": {
                    "code": 10001,
                    "message": sentinel,
                }
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedding = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=1,
    )
    client = make_client(retriever=EmbeddingFailureRetriever(embedding))

    with client:
        response = client.post(
            "/tools/v1/retrieve",
            headers={"Authorization": "Bearer tool-token"},
            json={"request_id": "tool-request", "query": "低温"},
        )
        client.portal.call(http.aclose)

    assert response.status_code == 502
    assert response.json() == {
        "code": "EMBEDDING_UNAVAILABLE",
        "message": "向量化服务暂时不可用",
        "retryable": True,
    }
    assert sentinel not in response.text


def test_tools_router_remains_mounted_and_authenticated():
    response = make_client().post(
        "/tools/v1/retrieve",
        json={"request_id": "tool-request", "query": "低温"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid tool token"}


def test_public_and_real_tool_routes_share_isolated_server_uuid_chains(caplog):
    from app.main import create_app

    contexts = RequestContextStore(ttl_seconds=300)
    workflow = InProcessToolWorkflow()
    injected = ServiceContainer(
        retriever=CorrelatedRetriever(),
        generation=None,
        cases=None,
        citations=CorrelatedValidator(),
        contexts=contexts,
        vector_store=None,
        workflow=workflow,
    )
    application = create_app(
        settings=settings(),
        container=injected,
    )
    workflow.app = application
    payload = {"message": "低温储粮", "role": "student"}

    with TestClient(application) as client:
        with caplog.at_level(logging.INFO):
            first = client.post(
                "/v1/chat",
                headers={"X-Request-ID": "shared-client-id"},
                json=payload,
            )
            second = client.post(
                "/v1/chat",
                headers={"X-Request-ID": "shared-client-id"},
                json=payload,
            )

    server_ids = [
        first.headers["x-request-id"],
        second.headers["x-request-id"],
    ]
    assert server_ids[0] != server_ids[1]
    for server_id, response, call in zip(
        server_ids,
        [first, second],
        workflow.calls,
        strict=True,
    ):
        assert response.status_code == 200
        uuid_value = uuid.UUID(server_id)
        assert uuid_value.version == 4
        assert json.loads(
            response.text.split("event: meta\ndata: ", 1)[1].split(
                "\n\n",
                1,
            )[0]
        )["request_id"] == server_id
        assert call[0]["REQUEST_ID"] == server_id
        assert f'"content": "{workflow.answer}"' in response.text

    assert workflow.tool_response_ids == [
        ("retrieve", server_ids[0]),
        ("citations.validate", server_ids[0]),
        ("retrieve", server_ids[1]),
        ("citations.validate", server_ids[1]),
    ]
    tool_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "tool_completed"
    ]
    assert [
        (record.tool_name, record.request_id)
        for record in tool_records
    ] == workflow.tool_response_ids
    http_records = [
        record
        for record in caplog.records
        if record.name == "grain_core.http"
        and getattr(record, "event", None) == "http_request"
        and record.path == "/v1/chat"
    ]
    terminal_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "workflow_terminal"
    ]
    assert [record.request_id for record in http_records] == server_ids
    assert [record.client_request_id for record in http_records] == [
        "shared-client-id",
        "shared-client-id",
    ]
    assert [record.request_id for record in terminal_records] == server_ids
    assert all(record.finish_reason == "stop" for record in terminal_records)
    assert all(not hasattr(record, "answer") for record in caplog.records)
    assert all(
        not hasattr(record, "evidence_text") for record in caplog.records
    )
    log_messages = "\n".join(
        record.getMessage() for record in caplog.records
    )
    assert workflow.answer not in log_messages
    assert EVIDENCE.text not in log_messages
    assert "tool-token" not in log_messages
    for server_id in server_ids:
        terminal_index = next(
            index
            for index, record in enumerate(caplog.records)
            if getattr(record, "event", None) == "workflow_terminal"
            and record.request_id == server_id
        )
        http_index = next(
            index
            for index, record in enumerate(caplog.records)
            if getattr(record, "event", None) == "http_request"
            and record.request_id == server_id
        )
        assert terminal_index < http_index


def test_lifespan_applies_configured_log_level():
    configured = settings()
    configured.log_level = "DEBUG"
    app = __import__("app.main", fromlist=["create_app"]).create_app(
        settings=configured,
        container=container(),
    )
    grain_logger = logging.getLogger("grain_core")
    root_logger = logging.getLogger()
    previous_grain_level = grain_logger.level
    previous_root_level = root_logger.level
    try:
        with TestClient(app):
            assert grain_logger.level == logging.DEBUG
            assert root_logger.level == logging.DEBUG
    finally:
        grain_logger.setLevel(previous_grain_level)
        root_logger.setLevel(previous_root_level)


def test_http_completion_log_occurs_after_stream_body_finishes(caplog):
    application = FastAPI()
    application.add_middleware(RequestIdMiddleware)
    stream_logger = logging.getLogger("test.stream")

    @application.get("/stream-error")
    async def stream_error():
        async def body():
            yield b"partial"
            stream_logger.info(
                "stream_finished",
                extra={"event": "stream_finished"},
            )

        return StreamingResponse(body(), status_code=500)

    with caplog.at_level(logging.INFO):
        response = TestClient(application).get("/stream-error")

    assert response.status_code == 500
    relevant_events = [
        record.event
        for record in caplog.records
        if getattr(record, "event", None)
        in {"stream_finished", "http_request"}
    ]
    assert relevant_events == ["stream_finished", "http_request"]


def test_missing_vector_store_builds_unavailable_retriever_without_network(
    monkeypatch, tmp_path
):
    from app.main import UnavailableRetriever, build_container
    from app.schemas.tools import RetrieveRequest

    opened = 0

    class NoNetworkAsyncClient:
        def __init__(self):
            nonlocal opened
            opened += 1

        async def aclose(self):
            pass

    monkeypatch.setattr(httpx, "AsyncClient", NoNetworkAsyncClient)
    built, closeables = build_container(settings(tmp_path / "absent"))

    assert built.vector_store is None
    assert isinstance(built.retriever, UnavailableRetriever)
    assert opened == 2
    assert len(closeables) == 3

    import asyncio

    with pytest.raises(VectorStoreNotReady):
        asyncio.run(
            built.retriever.retrieve(
                RetrieveRequest(request_id="request", query="低温")
            )
        )
    asyncio.run(closeables[0].close())
    asyncio.run(closeables[1].close())
    asyncio.run(closeables[2].close())


def test_vector_store_builds_ready_retriever(monkeypatch, tmp_path):
    from app.main import build_container

    np.save(tmp_path / "vectors.npy", np.array([[1.0, 0.0]], dtype=np.float32))
    (tmp_path / "chunks_metadata.json").write_text(
        '[{"source":"doc.pdf","text":"text"}]',
        encoding="utf-8",
    )
    built, closeables = build_container(settings(tmp_path))

    assert isinstance(built.vector_store, VectorStore)
    assert built.retriever.store is built.vector_store

    import asyncio

    for closeable in closeables:
        asyncio.run(closeable.close())


def test_validated_environment_limits_reach_owned_provider_clients(
    monkeypatch, tmp_path
):
    from app.main import build_container

    environment = {
        "XF_APP_ID": "app-id",
        "XF_EMBEDDING_API_KEY": "embedding-key",
        "XF_EMBEDDING_API_SECRET": "embedding-secret",
        "XF_MAAS_API_KEY": "maas-key",
        "XF_MAAS_API_SECRET": "maas-secret",
        "XF_MAAS_RESOURCE_ID": "resource-id",
        "XF_MAAS_SERVICE_ID": "service-id",
        "XF_WORKFLOW_API_KEY": "workflow-key",
        "XF_WORKFLOW_API_SECRET": "workflow-secret",
        "XF_WORKFLOW_FLOW_ID": "flow-id",
        "TOOLS_SERVICE_TOKEN": "tool-token",
        "VECTOR_STORE_DIR": str(tmp_path / "absent"),
        "MAAS_MAX_FRAMES": "11",
        "MAAS_MAX_PAYLOAD_BYTES": "1200",
        "MAAS_MAX_ANSWER_CHARS": "1300",
        "WORKFLOW_MAX_FRAMES": "21",
        "WORKFLOW_MAX_PAYLOAD_BYTES": "2200",
        "WORKFLOW_MAX_ANSWER_CHARS": "2300",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    configured = Settings(_env_file=None)
    captured = {}

    class Closeable:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def close(self):
            pass

    class Embedding(Closeable):
        pass

    class MaaS(Closeable):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured["maas"] = kwargs

    class Workflow(Closeable):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            captured["workflow"] = kwargs

    monkeypatch.setattr("app.main.IflytekEmbeddingClient", Embedding)
    monkeypatch.setattr("app.main.IflytekMaaSClient", MaaS)
    monkeypatch.setattr("app.main.XingchenWorkflowClient", Workflow)

    build_container(configured)

    assert {
        key: captured["maas"][key]
        for key in (
            "max_frames",
            "max_payload_bytes",
            "max_answer_chars",
        )
    } == {
        "max_frames": 11,
        "max_payload_bytes": 1200,
        "max_answer_chars": 1300,
    }
    assert {
        key: captured["workflow"][key]
        for key in (
            "max_frames",
            "max_payload_bytes",
            "max_answer_chars",
        )
    } == {
        "max_frames": 21,
        "max_payload_bytes": 2200,
        "max_answer_chars": 2300,
    }


@pytest.mark.parametrize(
    ("route_module", "path", "payload"),
    [
        (
            "chat",
            "/v1/chat",
            {"message": "低温储粮", "role": "student"},
        ),
        (
            "cases",
            "/v1/cases/analyze",
            {
                "role": "technician",
                "case": {"grain_type": "小麦", "goal": "判断风险"},
            },
        ),
    ],
)
def test_validated_gateway_limit_reaches_public_route(
    monkeypatch, route_module, path, payload
):
    captured = {}

    class Gateway:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def stream(self, **kwargs):
            yield "event: done\ndata: {}\n\n"

    monkeypatch.setattr(
        f"app.api.{route_module}.WorkflowGateway",
        Gateway,
    )
    configured = settings(gateway_max_buffer_chars=17)

    response = make_client(app_settings=configured).post(path, json=payload)

    assert response.status_code == 200
    assert captured["max_buffer_chars"] == 17


def test_injected_container_is_never_closed():
    from app.main import create_app

    class CloseableContainer:
        close_calls = 0

        async def close(self):
            self.close_calls += 1

    injected = container()
    injected.close = CloseableContainer().close
    app = create_app(settings=settings(), container=injected)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert injected.close.__self__.close_calls == 0


def test_all_owned_closeables_close_once_even_when_one_close_fails(
    monkeypatch,
):
    from app.main import create_app

    class Closeable:
        def __init__(self, fail=False):
            self.calls = 0
            self.fail = fail

        async def close(self):
            self.calls += 1
            if self.fail:
                raise RuntimeError("close failed")

    first = Closeable(fail=True)
    second = Closeable()
    built = container()
    monkeypatch.setattr(
        "app.main.build_container",
        lambda configured: (built, (first, second)),
    )
    app = create_app(settings=settings())

    with pytest.raises(RuntimeError, match="close failed"):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200

    assert first.calls == 1
    assert second.calls == 1


def test_startup_failure_closes_resources_created_before_failure(
    monkeypatch,
):
    from app.main import create_app

    class Embedding:
        instances = []

        def __init__(self, **kwargs):
            self.calls = 0
            self.instances.append(self)

        async def close(self):
            self.calls += 1

    class BrokenWorkflow:
        def __init__(self, **kwargs):
            raise RuntimeError("workflow construction failed")

    class MaaS:
        instances = []

        def __init__(self, **kwargs):
            self.calls = 0
            self.instances.append(self)

        async def close(self):
            self.calls += 1

    monkeypatch.setattr(
        "app.main.VectorStore.load",
        lambda directory: (_ for _ in ()).throw(VectorStoreNotReady()),
    )
    monkeypatch.setattr("app.main.IflytekEmbeddingClient", Embedding)
    monkeypatch.setattr("app.main.IflytekMaaSClient", MaaS)
    monkeypatch.setattr("app.main.XingchenWorkflowClient", BrokenWorkflow)

    with pytest.raises(RuntimeError, match="workflow construction failed"):
        with TestClient(create_app(settings=settings())):
            pass

    assert len(Embedding.instances) == 1
    assert Embedding.instances[0].calls == 1
    assert len(MaaS.instances) == 1
    assert MaaS.instances[0].calls == 1


def test_openapi_exposes_all_public_and_tool_routes():
    paths = make_client().get("/openapi.json").json()["paths"]

    assert {
        "/v1/chat",
        "/v1/cases/analyze",
        "/v1/sources/{evidence_id}",
        "/health",
        "/ready",
        "/tools/v1/retrieve",
        "/tools/v1/generate",
        "/tools/v1/cases/evaluate",
        "/tools/v1/citations/validate",
    } <= paths.keys()
