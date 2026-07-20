import logging
import uuid
import warnings
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
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

from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.rag.evidence import Evidence
from app.schemas.tools import (
    CaseEvaluateResponse,
    CitationValidateResponse,
    GenerateResponse,
    GenerationUsage,
    RetrievalQuality,
    RetrieveResponse,
)
from app.tools.routes import _authorize, router


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="测试",
    source="test.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)
EVIDENCE_2 = Evidence(
    evidence_id="sha256:e2",
    document_id="sha256:d2",
    title="监测",
    source="monitoring.pdf",
    text="粮情监测需要持续记录。",
    page=2,
    score=0.8,
    authority_level="industry",
    quality_flags=["reviewed"],
)

ROUTES = [
    ("/tools/v1/retrieve", {"request_id": "retrieve-id", "query": "低温"}),
    (
        "/tools/v1/generate",
        {
            "request_id": "generate-id",
            "question": "怎样储粮？",
            "evidences": [EVIDENCE.model_dump()],
        },
    ),
    ("/tools/v1/cases/evaluate", {"request_id": "case-id", "case": {}}),
    (
        "/tools/v1/citations/validate",
        {
            "request_id": "citation-id",
            "answer": "结论。[E1]",
            "evidences": [EVIDENCE.model_dump()],
        },
    ),
]


class FakeRetriever:
    def __init__(self):
        self.calls = 0

    async def retrieve(self, request):
        self.calls += 1
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=[EVIDENCE],
            quality=RetrievalQuality(top_score=0.9, sufficient=True),
        )


class FakeGeneration:
    def __init__(self):
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return GenerateResponse(
            request_id=request.request_id,
            answer="结论。[E1]",
            cited_evidence_ids=[EVIDENCE.evidence_id],
            usage=GenerationUsage(total_tokens=10),
        )


class FakeCases:
    def __init__(self):
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        return CaseEvaluateResponse(
            request_id=request.request_id,
            needs_input=True,
            missing_fields=["grain_type"],
            question="请补充粮食品种。",
            rules=[],
        )


class FakeValidator:
    def __init__(self):
        self.calls = 0
        self.requests = []

    def validate(self, request):
        self.calls += 1
        self.requests.append(request)
        return CitationValidateResponse(
            request_id=request.request_id,
            valid=True,
            errors=[],
            unsupported_sentences=[],
            citation_ids=[request.evidences[0].evidence_id],
        )


def make_client(
    token: object = "tool-token", *, configured: bool = True
) -> tuple[TestClient, RequestContextStore, ServiceContainer]:
    contexts = RequestContextStore(ttl_seconds=300)
    container = ServiceContainer(
        retriever=FakeRetriever(),
        generation=FakeGeneration(),
        cases=FakeCases(),
        citations=FakeValidator(),
        contexts=contexts,
        vector_store=None,
        workflow=None,
    )
    app = FastAPI()
    if configured:
        app.state.settings = SimpleNamespace(
            tools_service_token=SimpleNamespace(
                get_secret_value=lambda: token
            )
        )
    app.state.container = container
    app.include_router(router)
    return TestClient(app), contexts, container


def assert_no_service_invocations(container: ServiceContainer) -> None:
    assert container.retriever.calls == 0
    assert container.generation.calls == 0
    assert container.cases.calls == 0
    assert container.citations.calls == 0


async def seed_retrieval(contexts, request_id, evidences):
    await contexts.set_retrieval_result(
        request_id,
        evidences,
        sufficient=True,
    )


def test_all_routes_delegate_return_responses_and_persist_context():
    client, contexts, container = make_client()
    headers = {"Authorization": "Bearer tool-token"}
    with client:
        client.portal.call(
            seed_retrieval,
            contexts,
            "citation-id",
            [EVIDENCE],
        )
        responses = [
            client.post(path, headers=headers, json=payload)
            for path, payload in ROUTES
        ]

        assert [response.status_code for response in responses] == [200] * 4
        assert responses[0].json()["query"] == "低温"
        assert responses[1].json()["answer"] == "结论。[E1]"
        assert responses[2].json()["needs_input"] is True
        assert responses[3].json()["valid"] is True
        assert container.retriever.calls == 1
        assert container.generation.calls == 1
        assert container.cases.calls == 1
        assert container.citations.calls == 1

        retrieved = client.portal.call(contexts.pop, "retrieve-id")
        case = client.portal.call(contexts.pop, "case-id")
        citations = client.portal.call(contexts.pop, "citation-id")
        assert retrieved.evidences == (EVIDENCE,)
        assert retrieved.retrieval_sufficient is True
        assert case.needs_input is True
        assert case.missing_fields == ["grain_type"]
        assert case.question == "请补充粮食品种。"
        assert citations.validation_valid is True
        assert citations.validated_answer == "结论。[E1]"
        assert citations.citation_ids == [EVIDENCE.evidence_id]


@pytest.mark.parametrize("path,payload", ROUTES)
@pytest.mark.parametrize(
    "authorization", [None, "", "Basic tool-token", "Bearer wrong-token"]
)
def test_all_routes_reject_invalid_tokens_without_service_invocation(
    path, payload, authorization
):
    client, _, container = make_client()
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.post(path, headers=headers, json=payload)

    assert response.status_code == 401
    assert_no_service_invocations(container)


@pytest.mark.parametrize("token", ["", "   ", None])
def test_empty_or_unavailable_configured_secret_rejects_bearer_token(token):
    client, _, container = make_client(token=token)

    response = client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer "},
        json=ROUTES[0][1],
    )

    assert response.status_code == 401
    assert_no_service_invocations(container)


def test_missing_settings_state_rejects_token_without_service_invocation():
    client, _, container = make_client(configured=False)

    response = client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer tool-token"},
        json=ROUTES[0][1],
    )

    assert response.status_code == 401
    assert_no_service_invocations(container)


def test_malformed_secret_state_rejects_token_without_service_invocation():
    client, _, container = make_client()
    client.app.state.settings = SimpleNamespace(
        tools_service_token=SimpleNamespace(
            get_secret_value=lambda: (_ for _ in ()).throw(ValueError())
        )
    )

    response = client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer tool-token"},
        json=ROUTES[0][1],
    )

    assert response.status_code == 401
    assert_no_service_invocations(container)


def test_unauthenticated_malformed_tool_body_is_401():
    client, _, container = make_client()

    response = client.post("/tools/v1/retrieve", content=b"{")

    assert response.status_code == 401
    assert_no_service_invocations(container)


def test_non_ascii_raw_authorization_header_fails_closed_as_401():
    client, _, container = make_client()
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/tools/v1/retrieve",
            "headers": [(b"authorization", b"Bearer \xff")],
            "app": client.app,
        }
    )

    with pytest.raises(HTTPException) as caught:
        _authorize(request)

    assert caught.value.status_code == 401
    assert caught.value.detail == "invalid tool token"
    assert_no_service_invocations(container)


def test_authenticated_malformed_tool_body_is_422():
    client, _, container = make_client()

    response = client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer tool-token"},
        content=b"{",
    )

    assert response.status_code == 422
    assert_no_service_invocations(container)


@pytest.mark.parametrize("path,payload", ROUTES)
def test_authenticated_tool_requests_reject_unknown_fields(path, payload):
    client, _, container = make_client()

    response = client.post(
        path,
        headers={"Authorization": "Bearer tool-token"},
        json={**payload, "unknown": True},
    )

    assert response.status_code == 422
    assert_no_service_invocations(container)


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/tools/v1/generate",
            {
                "request_id": "generate-id",
                "question": "怎样储粮？",
                "evidences": [EVIDENCE.model_dump(), EVIDENCE.model_dump()],
            },
        ),
        (
            "/tools/v1/citations/validate",
            {
                "request_id": "citation-id",
                "answer": "结论。[E1]",
                "evidences": [EVIDENCE.model_dump(), EVIDENCE.model_dump()],
            },
        ),
    ],
)
def test_authenticated_tool_requests_reject_duplicate_evidence_ids(path, payload):
    client, _, container = make_client()

    response = client.post(
        path,
        headers={"Authorization": "Bearer tool-token"},
        json=payload,
    )

    assert response.status_code == 422
    assert_no_service_invocations(container)


def test_tool_log_uses_payload_authoritative_uuid_without_content(caplog):
    client, contexts, _ = make_client()
    authoritative_request_id = str(uuid.uuid4())
    payload = {
        **ROUTES[-1][1],
        "request_id": authoritative_request_id,
    }

    with client:
        client.portal.call(
            seed_retrieval,
            contexts,
            authoritative_request_id,
            [EVIDENCE],
        )
        with caplog.at_level(logging.INFO, logger="grain_core.tools"):
            response = client.post(
                "/tools/v1/citations/validate",
                headers={"Authorization": "Bearer tool-token"},
                json=payload,
            )

    assert response.status_code == 200
    assert response.json()["request_id"] == authoritative_request_id
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "tool_completed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.request_id == payload["request_id"]
    assert uuid.UUID(record.request_id).version == 4
    assert record.tool_name == "citations.validate"
    assert record.result_code == "OK"
    assert record.elapsed_ms >= 0
    assert record.citation_ids == [EVIDENCE.evidence_id]
    assert not hasattr(record, "answer")
    assert not hasattr(record, "evidence_text")
    assert "结论" not in record.getMessage()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "<script>METADATA_SENTINEL</script>"),
        ("source", "<img onerror=METADATA_SENTINEL>"),
        ("text", "[外链](javascript:METADATA_SENTINEL)"),
        ("page", 3),
        ("score", 0.89),
        ("authority_level", "law"),
        ("quality_flags", ["changed"]),
    ],
)
def test_citation_route_rejects_same_id_metadata_drift_without_validation_state(
    field,
    value,
):
    client, contexts, container = make_client()
    candidate = EVIDENCE.model_dump(mode="json")
    candidate[field] = value
    payload = {
        "request_id": "drift-request",
        "answer": "结论。[E1]",
        "evidences": [candidate],
    }

    with client:
        client.portal.call(
            seed_retrieval,
            contexts,
            "drift-request",
            [EVIDENCE],
        )
        response = client.post(
            "/tools/v1/citations/validate",
            headers={"Authorization": "Bearer tool-token"},
            json=payload,
        )
        context = client.portal.call(contexts.pop, "drift-request")

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert container.citations.calls == 0
    assert context.validation_valid is None
    assert context.validated_answer is None


def test_citation_route_rejects_unknown_evidence_id_without_validation_state():
    client, contexts, container = make_client()

    with client:
        client.portal.call(
            seed_retrieval,
            contexts,
            "unknown-request",
            [EVIDENCE],
        )
        response = client.post(
            "/tools/v1/citations/validate",
            headers={"Authorization": "Bearer tool-token"},
            json={
                "request_id": "unknown-request",
                "answer": "结论。[E1]",
                "evidences": [EVIDENCE_2.model_dump(mode="json")],
            },
        )
        context = client.portal.call(contexts.pop, "unknown-request")

    assert response.status_code == 200
    assert response.json()["valid"] is False
    assert container.citations.calls == 0
    assert context.validation_valid is None


def test_citation_route_uses_trusted_subset_in_caller_alias_order():
    client, contexts, container = make_client()

    with client:
        client.portal.call(
            seed_retrieval,
            contexts,
            "subset-request",
            [EVIDENCE, EVIDENCE_2],
        )
        response = client.post(
            "/tools/v1/citations/validate",
            headers={"Authorization": "Bearer tool-token"},
            json={
                "request_id": "subset-request",
                "answer": "结论。[E1]",
                "evidences": [EVIDENCE_2.model_dump(mode="json")],
            },
        )

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert container.citations.calls == 1
    trusted_request = container.citations.requests[0]
    assert [item.evidence_id for item in trusted_request.evidences] == [
        EVIDENCE_2.evidence_id
    ]
    assert trusted_request.evidences[0].model_dump() == EVIDENCE_2.model_dump()
