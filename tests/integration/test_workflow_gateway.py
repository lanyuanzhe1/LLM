import asyncio
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request

from app.core.errors import ProviderUnavailable
from app.core.request_context import RequestContextStore
from app.rag.evidence import Evidence
from app.schemas.api import CaseData, Role
from app.schemas.events import WorkflowFrame
from app.schemas.tools import CitationValidateRequest
from app.services.citation_validation import CitationValidator
from app.services.workflow_gateway import WorkflowGateway
from app.tools.routes import validate_citations


EVIDENCE_1 = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="低温储粮",
    source="paper.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)
EVIDENCE_2 = Evidence(
    evidence_id="sha256:e2",
    document_id="sha256:d2",
    title="水分管理",
    source="manual.pdf",
    text="水分管理有助于安全储粮。",
    score=0.8,
    authority_level="industry",
)
SAFE_VALIDATION_FALLBACK = "回答未通过引用验证，无法安全展示生成内容。"


def workflow_frame(
    *choices: tuple[str, str | None],
) -> WorkflowFrame:
    return WorkflowFrame.model_validate(
        {
            "code": 0,
            "message": "provider-only-message",
            "id": "provider-session",
            "choices": [
                {
                    "delta": {
                        "role": "assistant",
                        "content": content,
                    },
                    "index": index,
                    "finish_reason": finish_reason,
                }
                for index, (content, finish_reason) in enumerate(choices)
            ],
            "usage": {"total_tokens": 99},
        }
    )


def parse_sse(chunk: str) -> tuple[str, dict]:
    assert chunk.endswith("\n\n")
    lines = chunk[:-2].splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("event: ")
    assert lines[1].startswith("data: ")
    return lines[0][7:], json.loads(lines[1][6:])


async def collect(gateway: WorkflowGateway, **overrides):
    arguments = {
        "message": "低温储粮",
        "session_id": None,
        "user_id": None,
        "role": Role.STUDENT,
        "task_type": "knowledge_qa",
    }
    arguments.update(overrides)
    chunks = [chunk async for chunk in gateway.stream(**arguments)]
    parsed = [parse_sse(chunk) for chunk in chunks]
    assert {event for event, _ in parsed} <= {
        "meta",
        "delta",
        "citations",
        "done",
        "error",
    }
    return parsed


class RecordingWorkflow:
    def __init__(self, frames: list[WorkflowFrame] | None = None) -> None:
        self.frames = frames or [workflow_frame(("", "stop"))]
        self.calls: list[tuple[dict, str]] = []

    async def stream(self, parameters: dict, uid: str):
        self.calls.append((parameters, uid))
        for frame in self.frames:
            yield frame


class RealCitationToolWorkflow:
    def __init__(
        self,
        contexts: RequestContextStore,
        answer: str,
    ) -> None:
        self.contexts = contexts
        self.answer = answer

    async def stream(self, parameters: dict, uid: str):
        request_id = parameters["REQUEST_ID"]
        await self.contexts.set_retrieval_result(
            request_id,
            [EVIDENCE_1],
            sufficient=True,
        )
        app = FastAPI()
        app.state.container = SimpleNamespace(
            citations=CitationValidator(),
            contexts=self.contexts,
        )
        tool_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/tools/v1/citations/validate",
                "headers": [],
                "app": app,
            }
        )
        response = await validate_citations(
            CitationValidateRequest(
                request_id=request_id,
                answer=self.answer,
                evidences=[EVIDENCE_1],
            ),
            tool_request,
        )
        assert response.valid is False
        yield workflow_frame((self.answer, "stop"))


class TamperedEvidenceToolWorkflow:
    def __init__(self, contexts: RequestContextStore, sentinel: str) -> None:
        self.contexts = contexts
        self.sentinel = sentinel

    async def stream(self, parameters: dict, uid: str):
        request_id = parameters["REQUEST_ID"]
        await self.contexts.set_retrieval_result(
            request_id,
            [EVIDENCE_1],
            sufficient=True,
        )
        injected = EVIDENCE_1.model_copy(
            update={"title": f"<script>{self.sentinel}</script>"}
        )
        answer = f"""## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] <script>{self.sentinel}</script>"""
        app = FastAPI()
        app.state.container = SimpleNamespace(
            citations=CitationValidator(),
            contexts=self.contexts,
        )
        tool_request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/tools/v1/citations/validate",
                "headers": [],
                "app": app,
            }
        )
        await validate_citations(
            CitationValidateRequest(
                request_id=request_id,
                answer=answer,
                evidences=[injected],
            ),
            tool_request,
        )
        yield workflow_frame((answer, "stop"))


@pytest.mark.asyncio
async def test_real_tool_metadata_tampering_never_reaches_gateway_delta():
    sentinel = "DANGEROUS_METADATA_SENTINEL"
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=TamperedEvidenceToolWorkflow(contexts, sentinel),
        contexts=contexts,
        id_factory=lambda: "metadata-tamper-request",
    )

    events = await collect(gateway)

    assert all(
        sentinel not in data.get("content", "")
        for _, data in events
    )
    assert [event for event, _ in events] == ["meta", "error"]


@pytest.mark.asyncio
async def test_real_citation_tool_blocks_source_bypass_from_gateway_deltas():
    dangerous = "DANGEROUS_OPERATION_SENTINEL"
    answer = f"""## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮
{dangerous} 立即执行设备控制。"""
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=RealCitationToolWorkflow(contexts, answer),
        contexts=contexts,
        id_factory=lambda: "source-bypass-request",
    )

    events = await collect(gateway)

    delta_contents = [
        data["content"] for event, data in events if event == "delta"
    ]
    assert delta_contents
    assert all(dangerous not in content for content in delta_contents)
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_real_citation_tool_blocks_obfuscated_critical_claim_from_gateway():
    dangerous = "DANGEROUS_OBFUSCATED_OPERATION_SENTINEL"
    answer = f"""## 结论
{dangerous} 立即执行磷**化铝熏**蒸。
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=RealCitationToolWorkflow(contexts, answer),
        contexts=contexts,
        id_factory=lambda: "obfuscated-critical-request",
    )

    events = await collect(gateway)

    assert all(
        dangerous not in data["content"]
        for event, data in events
        if event == "delta"
    )
    assert events[-1][0] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        "立即执行磷<!-- hidden -->化铝熏蒸。",
        "立即执行[磷化铝熏蒸](https://example.test)。",
        "立即执行磷\u037a化铝熏\u037a蒸。",
        "立即执行磷\u3192化铝熏蒸。",
        "立即通\n风处理。",
        "Ventilate the granary immediately.",
        "建议对仓房通风。",
        "可通过通风降低粮温。",
        "Fumigate the granary immediately.",
        "Fumigating the granary is required.",
        "Begin ventilation immediately.",
    ],
    ids=[
        "html-comment",
        "markdown-link",
        "nfkc-category-change",
        "non-han-normalizes-to-han",
        "cross-line-ventilation",
        "english-high-risk-operation",
        "chinese-recommended-ventilation",
        "chinese-ventilation-method",
        "english-fumigate-command",
        "english-fumigating-operation",
        "english-ventilation-command",
    ],
)
async def test_real_tool_blocks_renderer_constructs_from_gateway(claim):
    dangerous = "DANGEROUS_RENDERER_CONSTRUCT_SENTINEL"
    answer = f"""## 结论
{dangerous} {claim}
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
- [E1] 低温储粮"""
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=RealCitationToolWorkflow(contexts, answer),
        contexts=contexts,
        id_factory=lambda: "renderer-construct-request",
    )

    events = await collect(gateway)

    assert all(
        dangerous not in data["content"]
        for event, data in events
        if event == "delta"
    )
    assert events[-1][0] == "done"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    [
        "Ventilation is recommended.",
        "Ventilating grain is recommended.",
        "推荐通风。",
        "可以采用通风。",
    ],
)
async def test_real_tool_blocks_uncited_recommended_ventilation_from_gateway(
    claim,
):
    answer = f"""## 结论
{claim}
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库没有统一阈值。
## 来源
[E1] 低温储粮"""
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=RealCitationToolWorkflow(contexts, answer),
        contexts=contexts,
        id_factory=lambda: "recommended-ventilation-request",
    )

    events = await collect(gateway)
    delta_contents = [
        data["content"] for event, data in events if event == "delta"
    ]

    assert delta_contents == [SAFE_VALIDATION_FALLBACK]
    assert all(claim not in content for content in delta_contents)
    assert events[-1][0] == "done"


@pytest.mark.asyncio
async def test_gateway_preserves_explicit_correlation_and_exact_case_parameters():
    workflow = RecordingWorkflow(
        [
            workflow_frame(("第一段", None), ("第二段", None)),
            workflow_frame(("", "stop")),
        ]
    )
    id_factory_called = False

    def id_factory() -> str:
        nonlocal id_factory_called
        id_factory_called = True
        return "must-not-be-used"

    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "explicit-request",
        [],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "explicit-request",
        valid=True,
        answer="第一段第二段",
        citation_ids=[],
    )
    gateway = WorkflowGateway(
        workflow=workflow,
        contexts=contexts,
        id_factory=id_factory,
    )
    case = CaseData(
        grain_type="小麦",
        storage_type="平房仓",
        moisture_percent=13.2,
        goal="判断风险",
    )

    events = await collect(
        gateway,
        message="分析案例",
        request_id="explicit-request",
        session_id="explicit-session",
        user_id="explicit-user",
        role=Role.TECHNICIAN,
        task_type="case_analysis",
        case=case,
    )

    assert id_factory_called is False
    assert events == [
        (
            "meta",
            {
                "request_id": "explicit-request",
                "session_id": "explicit-session",
            },
        ),
        ("delta", {"content": "第一段"}),
        ("delta", {"content": "第二段"}),
        ("citations", {"items": []}),
        ("done", {"finish_reason": "stop", "missing_fields": []}),
    ]
    assert workflow.calls == [
        (
            {
                "AGENT_USER_INPUT": "分析案例",
                "REQUEST_ID": "explicit-request",
                "SESSION_ID": "explicit-session",
                "USER_ROLE": "technician",
                "TASK_TYPE": "case_analysis",
                "CASE_JSON": json.dumps(
                    case.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
                "PROJECT_ID": "",
            },
            "explicit-user",
        )
    ]


@pytest.mark.asyncio
async def test_gateway_generates_request_and_session_ids_and_correlates_uid():
    workflow = RecordingWorkflow()
    gateway = WorkflowGateway(
        workflow=workflow,
        contexts=RequestContextStore(ttl_seconds=300),
        id_factory=lambda: "generated-request",
    )

    events = await collect(gateway)

    meta = events[0][1]
    assert meta["request_id"] == "generated-request"
    uuid.UUID(meta["session_id"])
    parameters, uid = workflow.calls[0]
    assert parameters["REQUEST_ID"] == meta["request_id"]
    assert parameters["SESSION_ID"] == meta["session_id"]
    assert parameters["CASE_JSON"] == ""
    assert uid == meta["session_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("citation_ids", "expected_ids"),
    [
        (["sha256:e1"], ["sha256:e1"]),
        (
            ["sha256:e1", "sha256:e2"],
            ["sha256:e2", "sha256:e1"],
        ),
    ],
)
async def test_gateway_releases_validated_citations_in_retrieval_order(
    citation_ids,
    expected_ids,
):
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "req-1",
        [EVIDENCE_2, EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "req-1",
        valid=True,
        answer="回答补充",
        citation_ids=citation_ids,
    )
    workflow = RecordingWorkflow(
        [
            workflow_frame(("回答", None)),
            workflow_frame(("补充", None), ("", "stop")),
        ]
    )
    gateway = WorkflowGateway(
        workflow=workflow,
        contexts=contexts,
        id_factory=lambda: "req-1",
    )

    events = await collect(gateway, session_id="session")

    assert [event for event, _ in events] == [
        "meta",
        "delta",
        "delta",
        "citations",
        "done",
    ]
    assert [
        item["evidence_id"] for item in events[-2][1]["items"]
    ] == expected_ids
    assert await contexts.pop("req-1") is None
    serialized = json.dumps(events, ensure_ascii=False)
    assert "provider-only-message" not in serialized
    assert "provider-session" not in serialized


@pytest.mark.asyncio
async def test_gateway_rejects_validated_citation_not_in_retrieval():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "foreign-citation-request",
        [EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "foreign-citation-request",
        valid=True,
        answer="RAW_FOREIGN_CITATION_ANSWER",
        citation_ids=[EVIDENCE_2.evidence_id],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_FOREIGN_CITATION_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "foreign-citation-request",
    )

    events = await collect(gateway)

    assert [event for event, _ in events] == ["meta", "error"]
    assert events[-1][1]["code"] == "WORKFLOW_PROTOCOL_ERROR"
    assert "RAW_FOREIGN_CITATION_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_gateway_requires_explicitly_sufficient_retrieval_for_release():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_evidences(
        "unconfirmed-retrieval-request",
        [EVIDENCE_1],
    )
    await contexts.set_validation_result(
        "unconfirmed-retrieval-request",
        valid=True,
        answer="RAW_UNCONFIRMED_RETRIEVAL_ANSWER",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [
                workflow_frame(
                    ("RAW_UNCONFIRMED_RETRIEVAL_ANSWER", "stop")
                )
            ]
        ),
        contexts=contexts,
        id_factory=lambda: "unconfirmed-retrieval-request",
    )

    events = await collect(gateway)

    assert [event for event, _ in events] == ["meta", "error"]
    assert events[-1][1]["code"] == "WORKFLOW_PROTOCOL_ERROR"
    assert "RAW_UNCONFIRMED_RETRIEVAL_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_gateway_maps_case_context_to_needs_input():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_case_result(
        "case-request",
        needs_input=True,
        missing_fields=["storage_type", "goal"],
        question="请补充仓型和分析目标。",
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_CASE_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "case-request",
    )

    events = await collect(
        gateway,
        role=Role.TECHNICIAN,
        task_type="case_analysis",
        case=CaseData(grain_type="小麦"),
    )

    assert events == [
        (
            "meta",
            {
                "request_id": "case-request",
                "session_id": events[0][1]["session_id"],
            },
        ),
        ("delta", {"content": "请补充仓型和分析目标。"}),
        ("citations", {"items": []}),
        (
            "done",
            {
                "finish_reason": "needs_input",
                "missing_fields": ["storage_type", "goal"],
            },
        ),
    ]
    assert "RAW_CASE_ANSWER" not in json.dumps(events, ensure_ascii=False)


@pytest.mark.asyncio
async def test_gateway_missing_context_is_protocol_error_without_raw_output():
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_MISSING_CONTEXT_ANSWER", "stop"))]
        ),
        contexts=RequestContextStore(ttl_seconds=300),
        id_factory=lambda: "missing-context",
    )

    events = await collect(gateway)

    assert events == [
        (
            "meta",
            {
                "request_id": "missing-context",
                "session_id": events[0][1]["session_id"],
            },
        ),
        (
            "error",
            {
                "code": "WORKFLOW_PROTOCOL_ERROR",
                "message": "智能体工作流响应未通过安全校验",
                "retryable": False,
            },
        ),
    ]
    assert "RAW_MISSING_CONTEXT_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_gateway_discards_raw_answer_when_retrieval_is_insufficient():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "insufficient-request",
        [EVIDENCE_1],
        sufficient=False,
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_INSUFFICIENT_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "insufficient-request",
    )

    events = await collect(gateway)

    assert events[1:] == [
        ("delta", {"content": "知识库证据不足，无法提供可靠回答。"}),
        ("citations", {"items": []}),
        ("done", {"finish_reason": "stop", "missing_fields": []}),
    ]
    assert "RAW_INSUFFICIENT_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_gateway_failed_validation_emits_deterministic_evidence_fallback():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "invalid-request",
        [EVIDENCE_1, EVIDENCE_2],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "invalid-request",
        valid=False,
        answer="RAW_INVALID_ANSWER",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_INVALID_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "invalid-request",
    )

    first = await collect(gateway)

    assert first[1] == (
        "delta",
        {"content": SAFE_VALIDATION_FALLBACK},
    )
    assert [item["evidence_id"] for item in first[2][1]["items"]] == [
        EVIDENCE_1.evidence_id,
        EVIDENCE_2.evidence_id,
    ]
    assert first[3] == (
        "done",
        {"finish_reason": "stop", "missing_fields": []},
    )
    assert "RAW_INVALID_ANSWER" not in json.dumps(first, ensure_ascii=False)

    second_contexts = RequestContextStore(ttl_seconds=300)
    await second_contexts.set_retrieval_result(
        "invalid-request",
        [EVIDENCE_1, EVIDENCE_2],
        sufficient=True,
    )
    await second_contexts.set_validation_result(
        "invalid-request",
        valid=False,
        answer="ANOTHER_RAW_ANSWER",
        citation_ids=[],
    )
    second = await collect(
        WorkflowGateway(
            workflow=RecordingWorkflow(
                [workflow_frame(("ANOTHER_RAW_ANSWER", "stop"))]
            ),
            contexts=second_contexts,
            id_factory=lambda: "invalid-request",
        )
    )
    assert second[1:] == first[1:]


@pytest.mark.asyncio
async def test_failed_validation_fallback_never_serializes_evidence_metadata():
    sentinel = "DANGEROUS_EVIDENCE_SENTINEL"
    malicious = Evidence(
        evidence_id="sha256:malicious",
        document_id="sha256:document",
        title=f"<script>{sentinel}</script>",
        source=f"<img onerror={sentinel}>",
        text=f"[外链](javascript:{sentinel})\u200b",
        score=0.7,
        authority_level="unknown",
    )
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "malicious-fallback",
        [malicious],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "malicious-fallback",
        valid=False,
        answer="RAW_INVALID_ANSWER",
        citation_ids=[],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_INVALID_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "malicious-fallback",
    )

    events = await collect(gateway)
    serialized = json.dumps(events, ensure_ascii=False)

    assert events[1] == (
        "delta",
        {"content": SAFE_VALIDATION_FALLBACK},
    )
    assert events[2] == (
        "citations",
        {"items": [{"evidence_id": malicious.evidence_id}]},
    )
    assert sentinel not in serialized
    assert "<script>" not in serialized
    assert "<img" not in serialized
    assert "javascript:" not in serialized


@pytest.mark.asyncio
async def test_gateway_answer_mismatch_is_protocol_error_without_raw_output():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "mismatch-request",
        [EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "mismatch-request",
        valid=True,
        answer="DIFFERENT_VALIDATED_ANSWER",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_MISMATCH_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "mismatch-request",
    )

    events = await collect(gateway)

    assert [event for event, _ in events] == ["meta", "error"]
    assert events[-1][1]["code"] == "WORKFLOW_PROTOCOL_ERROR"
    assert "RAW_MISMATCH_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


@pytest.mark.asyncio
async def test_gateway_logs_safe_terminal_outcome(caplog):
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "logged-request",
        [EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "logged-request",
        valid=True,
        answer="已验证回答",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("已验证回答", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "logged-request",
    )

    with caplog.at_level(logging.INFO, logger="grain_core.workflow"):
        events = await collect(gateway)

    assert events[-1][0] == "done"
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "workflow_terminal"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.request_id == "logged-request"
    assert record.node_name == "gateway"
    assert record.result_code == "OK"
    assert record.finish_reason == "stop"
    assert record.citation_ids == [EVIDENCE_1.evidence_id]
    assert record.elapsed_ms >= 0
    assert not hasattr(record, "answer")
    assert not hasattr(record, "evidence_text")
    assert "已验证回答" not in record.getMessage()


async def close_immediately_after(
    stream,
    terminal_event: str,
) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    while True:
        parsed = parse_sse(await anext(stream))
        events.append(parsed)
        if parsed[0] == terminal_event:
            await stream.aclose()
            return events


def terminal_records(caplog, request_id: str):
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "workflow_terminal"
        and record.request_id == request_id
    ]


@pytest.mark.asyncio
async def test_success_terminal_is_locked_before_done_is_yielded(caplog):
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "close-success",
        [EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "close-success",
        valid=True,
        answer="已验证回答",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    stream = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("已验证回答", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "close-success",
    ).stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    with caplog.at_level(logging.INFO, logger="grain_core.workflow"):
        events = await close_immediately_after(stream, "done")

    assert events[-1][0] == "done"
    records = terminal_records(caplog, "close-success")
    assert len(records) == 1
    assert records[0].result_code == "OK"
    assert records[0].finish_reason == "stop"


@pytest.mark.asyncio
async def test_fallback_terminal_is_locked_before_done_is_yielded(caplog):
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "close-fallback",
        [EVIDENCE_1],
        sufficient=True,
    )
    await contexts.set_validation_result(
        "close-fallback",
        valid=False,
        answer="RAW_INVALID_ANSWER",
        citation_ids=[EVIDENCE_1.evidence_id],
    )
    stream = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_INVALID_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "close-fallback",
    ).stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    with caplog.at_level(logging.INFO, logger="grain_core.workflow"):
        events = await close_immediately_after(stream, "done")

    assert events[-1][0] == "done"
    records = terminal_records(caplog, "close-fallback")
    assert len(records) == 1
    assert records[0].result_code == "VALIDATION_FAILED_FALLBACK"
    assert records[0].finish_reason == "stop"
    assert not hasattr(records[0], "answer")
    assert not hasattr(records[0], "evidence_text")


@pytest.mark.asyncio
async def test_error_terminal_is_locked_before_error_is_yielded(caplog):
    stream = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_PROTOCOL_ANSWER", "stop"))]
        ),
        contexts=RequestContextStore(ttl_seconds=300),
        id_factory=lambda: "close-error",
    ).stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    with caplog.at_level(logging.INFO, logger="grain_core.workflow"):
        events = await close_immediately_after(stream, "error")

    assert events[-1][1]["code"] == "WORKFLOW_PROTOCOL_ERROR"
    records = terminal_records(caplog, "close-error")
    assert len(records) == 1
    assert records[0].result_code == "WORKFLOW_PROTOCOL_ERROR"
    assert records[0].finish_reason == "error"
    assert "RAW_PROTOCOL_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )


class AppErrorWorkflow:
    def __init__(self, contexts: RequestContextStore) -> None:
        self.contexts = contexts

    async def stream(self, parameters: dict, uid: str):
        await self.contexts.set_evidences(
            parameters["REQUEST_ID"],
            [EVIDENCE_1],
        )
        error = ProviderUnavailable(
            "WORKFLOW_UNAVAILABLE",
            "智能体工作流暂时不可用",
        )
        error.details = {"raw_provider_data": "RAW_APP_ERROR_SECRET"}
        raise error
        yield


@pytest.mark.asyncio
async def test_gateway_emits_only_safe_app_error_fields_and_cleans_context():
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=AppErrorWorkflow(contexts),
        contexts=contexts,
        id_factory=lambda: "failed-request",
    )

    events = await collect(gateway)

    assert events == [
        (
            "meta",
            {
                "request_id": "failed-request",
                "session_id": events[0][1]["session_id"],
            },
        ),
        (
            "error",
            {
                "code": "WORKFLOW_UNAVAILABLE",
                "message": "智能体工作流暂时不可用",
                "retryable": True,
            },
        ),
    ]
    assert "RAW_APP_ERROR_SECRET" not in json.dumps(
        events,
        ensure_ascii=False,
    )
    assert await contexts.pop("failed-request") is None


@pytest.mark.asyncio
async def test_app_error_context_is_absent_when_error_event_is_received():
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=AppErrorWorkflow(contexts),
        contexts=contexts,
        id_factory=lambda: "failed-lifecycle-request",
    )
    stream = gateway.stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    assert parse_sse(await anext(stream))[0] == "meta"
    assert parse_sse(await anext(stream))[0] == "error"

    assert await contexts.pop("failed-lifecycle-request") is None
    await stream.aclose()


class UnexpectedFailureWorkflow:
    def __init__(self, contexts: RequestContextStore) -> None:
        self.contexts = contexts

    async def stream(self, parameters: dict, uid: str):
        await self.contexts.set_evidences(
            parameters["REQUEST_ID"],
            [EVIDENCE_1],
        )
        raise RuntimeError("RAW_PROVIDER_SECRET")
        yield


@pytest.mark.asyncio
async def test_gateway_sanitizes_unexpected_failures_without_done():
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=UnexpectedFailureWorkflow(contexts),
        contexts=contexts,
        id_factory=lambda: "unexpected-request",
    )

    events = await collect(gateway)

    assert [event for event, _ in events] == ["meta", "error"]
    assert events[-1] == (
        "error",
        {
            "code": "WORKFLOW_UNAVAILABLE",
            "message": "智能体工作流暂时不可用",
            "retryable": True,
        },
    )
    assert "RAW_PROVIDER_SECRET" not in json.dumps(events, ensure_ascii=False)
    assert await contexts.pop("unexpected-request") is None


@pytest.mark.asyncio
async def test_unexpected_error_context_is_absent_when_error_event_is_received():
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=UnexpectedFailureWorkflow(contexts),
        contexts=contexts,
        id_factory=lambda: "unexpected-lifecycle-request",
    )
    stream = gateway.stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    assert parse_sse(await anext(stream))[0] == "meta"
    assert parse_sse(await anext(stream))[0] == "error"

    assert await contexts.pop("unexpected-lifecycle-request") is None
    await stream.aclose()


@pytest.mark.asyncio
async def test_gateway_consumer_disconnect_closes_stream_and_cleans_context():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_retrieval_result(
        "disconnected-request",
        [EVIDENCE_1],
        sufficient=True,
    )
    gateway = WorkflowGateway(
        workflow=RecordingWorkflow(
            [workflow_frame(("RAW_DISCONNECTED_ANSWER", "stop"))]
        ),
        contexts=contexts,
        id_factory=lambda: "disconnected-request",
    )
    stream = gateway.stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    assert parse_sse(await anext(stream))[0] == "meta"
    await stream.aclose()

    assert await contexts.pop("disconnected-request") is None


class CancelledWorkflow:
    def __init__(self, contexts: RequestContextStore) -> None:
        self.contexts = contexts

    async def stream(self, parameters: dict, uid: str):
        await self.contexts.set_evidences(
            parameters["REQUEST_ID"],
            [EVIDENCE_1],
        )
        raise asyncio.CancelledError("RAW_CANCEL_SECRET")
        yield


@pytest.mark.asyncio
async def test_gateway_propagates_cancellation_and_cleans_context():
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=CancelledWorkflow(contexts),
        contexts=contexts,
        id_factory=lambda: "cancelled-request",
    )
    stream = gateway.stream(
        message="问题",
        session_id=None,
        user_id=None,
        role=Role.STUDENT,
        task_type="knowledge_qa",
    )

    assert parse_sse(await anext(stream))[0] == "meta"
    with pytest.raises(asyncio.CancelledError):
        await anext(stream)

    assert await contexts.pop("cancelled-request") is None


class OversizedAnswerWorkflow:
    def __init__(self) -> None:
        self.finalized = False

    async def stream(self, parameters: dict, uid: str):
        try:
            yield workflow_frame(("RAW_OVERSIZED_ANSWER", None))
            yield workflow_frame(("", "stop"))
        finally:
            self.finalized = True


@pytest.mark.asyncio
async def test_gateway_buffer_overflow_fails_closed_and_finalizes_provider():
    workflow = OversizedAnswerWorkflow()
    contexts = RequestContextStore(ttl_seconds=300)
    gateway = WorkflowGateway(
        workflow=workflow,
        contexts=contexts,
        id_factory=lambda: "oversized-request",
        max_buffer_chars=3,
    )

    events = await collect(gateway)

    assert events == [
        (
            "meta",
            {
                "request_id": "oversized-request",
                "session_id": events[0][1]["session_id"],
            },
        ),
        (
            "error",
            {
                "code": "WORKFLOW_PROTOCOL_ERROR",
                "message": "智能体工作流响应未通过安全校验",
                "retryable": False,
            },
        ),
    ]
    assert "RAW_OVERSIZED_ANSWER" not in json.dumps(
        events,
        ensure_ascii=False,
    )
    assert workflow.finalized is True
