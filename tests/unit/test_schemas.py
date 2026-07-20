import pytest
from pydantic import ValidationError

from app.rag.evidence import Evidence
from app.schemas.api import CaseAnalyzeRequest, CaseData, ChatRequest
from app.schemas.events import WorkflowFrame
from app.schemas.tools import (
    CaseEvaluateRequest,
    CaseEvaluateResponse,
    CitationCoverage,
    CitationValidateRequest,
    CitationValidateResponse,
    GenerateRequest,
    GenerationUsage,
    RetrievalQuality,
    RetrieveRequest,
)


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="测试证据",
    source="test.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)


def test_chat_role_is_closed_enum():
    request = ChatRequest(message="你好", role="student")
    assert request.role.value == "student"

    with pytest.raises(ValidationError):
        ChatRequest(message="你好", role="administrator")


def test_retrieve_top_k_is_bounded():
    with pytest.raises(ValidationError):
        RetrieveRequest(request_id="req", query="问题", top_k=100)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ChatRequest, {"message": "你好", "unknown": True}),
        (
            CaseAnalyzeRequest,
            {"case": {"grain_type": "小麦", "unknown": True}},
        ),
        (
            RetrieveRequest,
            {"request_id": "req", "query": "问题", "unknown": True},
        ),
        (
            RetrieveRequest,
            {
                "request_id": "req",
                "query": "问题",
                "filters": {"unknown": True},
            },
        ),
        (
            GenerateRequest,
            {
                "request_id": "req",
                "question": "问题",
                "evidences": [EVIDENCE],
                "unknown": True,
            },
        ),
        (
            CaseEvaluateRequest,
            {"request_id": "req", "case": {}, "unknown": True},
        ),
        (
            CitationValidateRequest,
            {
                "request_id": "req",
                "answer": "回答",
                "evidences": [EVIDENCE],
                "unknown": True,
            },
        ),
    ],
)
def test_public_and_tool_requests_forbid_unknown_fields(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_provider_workflow_frames_remain_forward_compatible():
    frame = WorkflowFrame.model_validate(
        {
            "code": 0,
            "message": "ok",
            "id": "frame",
            "usage": {
                "total_tokens": 12,
                "latency_ms": 4.5,
                "cache": {"hit": True},
            },
            "provider_extension": {"future": True},
        }
    )

    assert frame.code == 0
    assert frame.usage == {
        "total_tokens": 12,
        "latency_ms": 4.5,
        "cache": {"hit": True},
    }


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (RetrieveRequest, {"request_id": "", "query": "问题"}),
        (RetrieveRequest, {"request_id": "r" * 129, "query": "问题"}),
        (
            GenerateRequest,
            {
                "request_id": " ",
                "question": "问题",
                "evidences": [EVIDENCE],
            },
        ),
        (
            CaseEvaluateRequest,
            {"request_id": "r" * 129, "case": {}},
        ),
        (
            CitationValidateRequest,
            {
                "request_id": "",
                "answer": "回答",
                "evidences": [EVIDENCE],
            },
        ),
    ],
)
def test_tool_request_ids_are_bounded(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_request_strings_are_stripped_and_bounded():
    chat = ChatRequest(
        message="  你好  ",
        session_id="  session  ",
        user_id="  user  ",
    )
    case = CaseData(
        grain_type="  小麦  ",
        storage_type="  平房仓  ",
        goal="  判断霉变风险  ",
    )
    generate = GenerateRequest(
        request_id="  req  ",
        question="  怎样储粮？  ",
        task_type="  knowledge_qa  ",
        evidences=[EVIDENCE],
        validation_feedback=["  补充引用  "],
    )

    assert chat.message == "你好"
    assert chat.session_id == "session"
    assert chat.user_id == "user"
    assert case.grain_type == "小麦"
    assert case.storage_type == "平房仓"
    assert case.goal == "判断霉变风险"
    assert generate.request_id == "req"
    assert generate.question == "怎样储粮？"
    assert generate.task_type == "knowledge_qa"
    assert generate.validation_feedback == ["补充引用"]

    for constructor in (
        lambda: ChatRequest(message=" "),
        lambda: ChatRequest(message="你好", session_id=" "),
        lambda: CaseData(grain_type=" "),
        lambda: CaseData(storage_type="s" * 129),
        lambda: CaseData(goal="g" * 1001),
        lambda: GenerateRequest(
            request_id="req",
            question=" ",
            evidences=[EVIDENCE],
        ),
        lambda: GenerateRequest(
            request_id="req",
            question="问题",
            task_type="t" * 129,
            evidences=[EVIDENCE],
        ),
    ):
        with pytest.raises(ValidationError):
            constructor()


def test_chat_and_query_retain_tighter_string_limits():
    with pytest.raises(ValidationError):
        ChatRequest(message="问" * 8001)
    with pytest.raises(ValidationError):
        RetrieveRequest(request_id="req", query="问" * 8001)


def test_tool_questions_and_answers_allow_at_most_32000_characters():
    GenerateRequest(
        request_id="req",
        question="问" * 32000,
        evidences=[EVIDENCE],
    )
    CitationValidateRequest(
        request_id="req",
        answer="答" * 32000,
        evidences=[EVIDENCE],
    )

    with pytest.raises(ValidationError):
        GenerateRequest(
            request_id="req",
            question="问" * 32001,
            evidences=[EVIDENCE],
        )
    with pytest.raises(ValidationError):
        CitationValidateRequest(
            request_id="req",
            answer="答" * 32001,
            evidences=[EVIDENCE],
        )


@pytest.mark.parametrize("model", [GenerateRequest, CitationValidateRequest])
def test_evidence_inputs_are_limited_to_one_through_five(model):
    field = "question" if model is GenerateRequest else "answer"
    common = {"request_id": "req", field: "内容"}

    with pytest.raises(ValidationError):
        model(**common, evidences=[])
    with pytest.raises(ValidationError):
        model(**common, evidences=[EVIDENCE] * 6)


@pytest.mark.parametrize("model", [GenerateRequest, CitationValidateRequest])
def test_tool_requests_require_unique_evidence_ids(model):
    content_field = "question" if model is GenerateRequest else "answer"
    duplicate = EVIDENCE.model_copy(update={"title": "重复证据"})

    with pytest.raises(ValidationError):
        model(
            request_id="req",
            **{content_field: "内容"},
            evidences=[EVIDENCE, duplicate],
        )


@pytest.mark.parametrize("model", [GenerateRequest, CitationValidateRequest])
def test_tool_requests_reject_invalid_nested_evidence(model):
    content_field = "question" if model is GenerateRequest else "answer"
    payload = {
        "request_id": "req",
        content_field: "内容",
        "evidences": [
            {
                "evidence_id": "sha256:e1",
                "document_id": "sha256:d1",
                "title": "证据",
                "source": "test.pdf",
                "text": "证据文本",
                "score": 0.9,
                "unexpected": True,
            }
        ],
    }

    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_feedback_error_and_citation_lists_are_limited_to_twenty():
    with pytest.raises(ValidationError):
        GenerateRequest(
            request_id="req",
            question="问题",
            evidences=[EVIDENCE],
            validation_feedback=["问题"] * 21,
        )

    common = {
        "request_id": "req",
        "valid": False,
        "unsupported_sentences": [],
        "citation_ids": [],
    }
    with pytest.raises(ValidationError):
        CitationValidateResponse(**common, errors=["错误"] * 21)
    with pytest.raises(ValidationError):
        CitationValidateResponse(
            **{
                **common,
                "errors": [],
                "citation_ids": ["sha256:e1"] * 21,
            },
        )


@pytest.mark.parametrize("score", [-1.001, 1.001])
def test_retrieval_scores_are_bounded(score):
    with pytest.raises(ValidationError):
        RetrievalQuality(top_score=score, sufficient=True)


def test_token_counts_are_non_negative():
    with pytest.raises(ValidationError):
        GenerationUsage(total_tokens=-1)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            CaseAnalyzeRequest,
            {
                "case": {
                    "moisture_percent": "13.2",
                    "storage_days": 60,
                }
            },
        ),
        (
            CaseAnalyzeRequest,
            {
                "case": {
                    "moisture_percent": 13.2,
                    "storage_days": True,
                }
            },
        ),
        (
            RetrieveRequest,
            {"request_id": "req", "query": "问题", "top_k": "5"},
        ),
        (
            RetrieveRequest,
            {"request_id": "req", "query": "问题", "top_k": True},
        ),
        (
            GenerateRequest,
            {
                "request_id": "req",
                "question": "问题",
                "evidences": [
                    {
                        **EVIDENCE.model_dump(),
                        "page": "1",
                    }
                ],
            },
        ),
        (
            CaseEvaluateRequest,
            {
                "request_id": "req",
                "case": {"pest_signs": 1},
            },
        ),
        (
            CitationValidateRequest,
            {
                "request_id": "req",
                "answer": "回答",
                "evidences": [
                    {
                        **EVIDENCE.model_dump(),
                        "score": "0.9",
                    }
                ],
            },
        ),
    ],
)
def test_public_and_all_tool_requests_reject_coerced_domain_scalars(
    model,
    payload,
):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize(
    ("constructor", "kwargs"),
    [
        (Evidence, {**EVIDENCE.model_dump(), "page": True}),
        (Evidence, {**EVIDENCE.model_dump(), "score": True}),
        (RetrievalQuality, {"top_score": "0.9", "sufficient": True}),
        (RetrievalQuality, {"top_score": 0.9, "sufficient": 1}),
        (GenerationUsage, {"total_tokens": "10"}),
        (
            CitationCoverage,
            {
                "total_sentences": "2",
                "cited_sentences": 1,
                "ratio": 0.5,
            },
        ),
        (
            CitationCoverage,
            {
                "total_sentences": 2,
                "cited_sentences": True,
                "ratio": 0.5,
            },
        ),
        (
            CitationCoverage,
            {
                "total_sentences": 2,
                "cited_sentences": 1,
                "ratio": "0.5",
            },
        ),
        (
            CaseEvaluateResponse,
            {
                "request_id": "req",
                "needs_input": "false",
                "missing_fields": [],
            },
        ),
        (
            CitationValidateResponse,
            {
                "request_id": "req",
                "valid": 1,
                "errors": [],
                "unsupported_sentences": [],
                "citation_ids": [],
            },
        ),
    ],
)
def test_domain_response_scalars_reject_booleans_and_numeric_strings(
    constructor,
    kwargs,
):
    with pytest.raises(ValidationError):
        constructor.model_validate(kwargs)


def test_json_integers_are_accepted_for_mathematically_float_fields():
    case = CaseData(moisture_percent=13)
    evidence = Evidence.model_validate(
        {**EVIDENCE.model_dump(), "score": 1}
    )
    coverage = CitationCoverage(
        total_sentences=2,
        cited_sentences=1,
        ratio=1,
    )

    assert case.moisture_percent == 13.0
    assert evidence.score == 1.0
    assert coverage.ratio == 1.0


@pytest.mark.parametrize(
    "field",
    [
        "moisture_percent",
        "grain_temperature_c",
        "ambient_temperature_c",
        "ambient_humidity_percent",
        "co2_ppm",
    ],
)
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_case_domain_floats_must_be_finite(field, value):
    with pytest.raises(ValidationError):
        CaseData.model_validate({field: value})


def test_overflowing_json_float_cannot_enter_case_serialization():
    with pytest.raises(ValidationError):
        CaseData.model_validate_json('{"co2_ppm":1e309}')


def test_chat_request_accepts_project_id():
    request = ChatRequest(message="test", project_id="demo")
    assert request.project_id == "demo"


def test_chat_request_project_id_defaults_none():
    request = ChatRequest(message="test")
    assert request.project_id is None


def test_chat_request_project_id_rejects_invalid():
    with pytest.raises(ValidationError):
        ChatRequest(message="test", project_id="")


def test_retrieve_request_accepts_project_id():
    from app.schemas.tools import RetrieveRequest
    request = RetrieveRequest(request_id="req", query="q", project_id="demo")
    assert request.project_id == "demo"


def test_case_analyze_request_accepts_project_id():
    request = CaseAnalyzeRequest(case=CaseData(grain_type="小麦"), project_id="demo")
    assert request.project_id == "demo"


def test_case_analyze_request_rejects_long_project_id():
    with pytest.raises(ValidationError):
        CaseAnalyzeRequest(case=CaseData(grain_type="小麦"), project_id="a" * 65)
