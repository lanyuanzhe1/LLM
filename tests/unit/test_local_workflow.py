import json

import pytest

from app.core.request_context import RequestContextStore
from app.rag.evidence import Evidence
from app.schemas.api import CaseData, Role
from app.schemas.tools import (
    CaseEvaluateResponse,
    CitationValidateResponse,
    GenerateResponse,
    RetrieveResponse,
    RetrievalQuality,
)
from app.services.local_workflow import LocalWorkflow


EVIDENCE_1 = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="低温储粮技术应用进展研究",
    source="knowledge/其他论文/低温储粮.pdf",
    page=3,
    section="低温对害虫的影响",
    text="低温条件可抑制储粮害虫的生长发育。",
    score=0.9,
    authority_level="research",
)
EVIDENCE_2 = Evidence(
    evidence_id="sha256:e2",
    document_id="sha256:d2",
    title="粮食水分控制技术",
    source="knowledge/其他论文/水分控制.pdf",
    text="控制粮食水分有助于安全储粮。",
    score=0.8,
    authority_level="industry",
)
ANSWER = "低温能够抑制储粮害虫活动。[E1]"


class StubRetriever:
    def __init__(self, response: RetrieveResponse) -> None:
        self.response = response
        self.calls = []

    async def retrieve(self, request):
        self.calls.append(request)
        return self.response


class StubGeneration:
    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.calls = []

    async def generate(self, request):
        self.calls.append(request)
        answer = (
            self._answers.pop(0)
            if len(self._answers) > 1
            else self._answers[0]
        )
        return GenerateResponse(
            request_id=request.request_id,
            answer=answer,
            cited_evidence_ids=[],
        )


class StubCitations:
    def __init__(self, *responses: CitationValidateResponse) -> None:
        self._responses = list(responses)
        self.calls = []

    def validate(self, request):
        self.calls.append(request)
        return (
            self._responses.pop(0)
            if len(self._responses) > 1
            else self._responses[0]
        )


class StubCases:
    def __init__(self, response: CaseEvaluateResponse | None = None) -> None:
        self.response = response
        self.calls = []

    def evaluate(self, request):
        self.calls.append(request)
        return self.response


def retrieval_response(
    request_id: str,
    *,
    evidences=(EVIDENCE_1, EVIDENCE_2),
    sufficient=True,
) -> RetrieveResponse:
    return RetrieveResponse(
        request_id=request_id,
        query="查询",
        evidences=list(evidences),
        quality=RetrievalQuality(
            top_score=evidences[0].score if evidences else 0.0,
            sufficient=sufficient,
        ),
    )


def validation_response(
    request_id: str,
    *,
    valid: bool,
    citation_ids=(),
    errors=(),
    unsupported=(),
) -> CitationValidateResponse:
    return CitationValidateResponse(
        request_id=request_id,
        valid=valid,
        errors=list(errors),
        unsupported_sentences=list(unsupported),
        citation_ids=list(citation_ids),
    )


def parameters(**overrides):
    values = {
        "AGENT_USER_INPUT": "低温为何抑制害虫？",
        "REQUEST_ID": "req-1",
        "SESSION_ID": "session-1",
        "USER_ROLE": "student",
        "TASK_TYPE": "knowledge_qa",
        "CASE_JSON": "",
        "PROJECT_ID": "course-2026",
    }
    values.update(overrides)
    return values


def make_workflow(
    *,
    retriever,
    generation,
    citations,
    cases=None,
    contexts=None,
):
    contexts = contexts or RequestContextStore(ttl_seconds=300)
    workflow = LocalWorkflow(
        retriever=retriever,
        generation=generation,
        cases=cases or StubCases(),
        citations=citations,
        contexts=contexts,
    )
    return workflow, contexts


def frame_contents(frames):
    return "".join(
        choice.delta.content for frame in frames for choice in frame.choices
    )


async def test_qa_happy_path_writes_reconciliation_contexts_and_streams_answer():
    retriever = StubRetriever(retrieval_response("req-1"))
    generation = StubGeneration(ANSWER)
    citations = StubCitations(
        validation_response(
            "req-1",
            valid=True,
            citation_ids=[EVIDENCE_1.evidence_id],
        )
    )
    cases = StubCases()
    workflow, contexts = make_workflow(
        retriever=retriever,
        generation=generation,
        citations=citations,
        cases=cases,
    )

    frames = [
        frame
        async for frame in workflow.stream(parameters(), uid="user-1")
    ]

    assert frame_contents(frames) == ANSWER
    assert all(frame.code == 0 for frame in frames)

    context = await contexts.pop("req-1")
    assert context is not None
    assert context.retrieval_sufficient is True
    assert list(context.evidences) == [EVIDENCE_1, EVIDENCE_2]
    assert context.validation_valid is True
    assert context.validated_answer == ANSWER
    assert context.citation_ids == []

    assert cases.calls == []
    retrieve_call = retriever.calls[0]
    assert retrieve_call.request_id == "req-1"
    assert retrieve_call.query == "低温为何抑制害虫？"
    assert retrieve_call.top_k == 5
    assert retrieve_call.project_id == "course-2026"

    assert len(generation.calls) == 1
    generate_call = generation.calls[0]
    assert generate_call.request_id == "req-1"
    assert generate_call.question == "低温为何抑制害虫？"
    assert generate_call.role == Role.STUDENT
    assert generate_call.task_type == "knowledge_qa"
    assert generate_call.evidences == [EVIDENCE_1, EVIDENCE_2]
    assert generate_call.validation_feedback == []

    # 引用校验已按用户决定停用：编排器不再调用校验器
    assert citations.calls == []


async def test_insufficient_retrieval_skips_generation_and_emits_no_frames():
    retriever = StubRetriever(
        retrieval_response(
            "req-1",
            evidences=(EVIDENCE_1,),
            sufficient=False,
        )
    )
    generation = StubGeneration(ANSWER)
    citations = StubCitations(
        validation_response(
            "req-1",
            valid=True,
            citation_ids=[EVIDENCE_1.evidence_id],
        )
    )
    workflow, contexts = make_workflow(
        retriever=retriever,
        generation=generation,
        citations=citations,
    )

    frames = [
        frame
        async for frame in workflow.stream(parameters(), uid="user-1")
    ]

    assert frames == []
    assert generation.calls == []
    assert citations.calls == []
    context = await contexts.pop("req-1")
    assert context is not None
    assert context.retrieval_sufficient is False
    assert list(context.evidences) == [EVIDENCE_1]
    assert context.validation_valid is None
    assert context.validated_answer is None
    assert context.citation_ids == []




async def test_case_branch_needs_input_writes_question_context_without_frames():
    cases = StubCases(
        CaseEvaluateResponse(
            request_id="req-1",
            needs_input=True,
            missing_fields=["grain_temperature_c", "pest_signs"],
            question="请补充以下关键信息：粮温、虫害迹象。",
        )
    )
    retriever = StubRetriever(retrieval_response("req-1"))
    generation = StubGeneration(ANSWER)
    citations = StubCitations(
        validation_response(
            "req-1",
            valid=True,
            citation_ids=[EVIDENCE_1.evidence_id],
        )
    )
    workflow, contexts = make_workflow(
        retriever=retriever,
        generation=generation,
        citations=citations,
        cases=cases,
    )

    frames = [
        frame
        async for frame in workflow.stream(case_parameters(), uid="user-1")
    ]

    assert frames == []
    assert retriever.calls == []
    assert generation.calls == []
    assert citations.calls == []
    assert len(cases.calls) == 1
    assert cases.calls[0].request_id == "req-1"
    assert cases.calls[0].case == CASE
    context = await contexts.pop("req-1")
    assert context is not None
    assert context.needs_input is True
    assert context.missing_fields == ["grain_temperature_c", "pest_signs"]
    assert context.question == "请补充以下关键信息：粮温、虫害迹象。"
    assert context.validation_valid is None


async def test_case_branch_complete_case_runs_mainline_with_case_query():
    cases = StubCases(
        CaseEvaluateResponse(
            request_id="req-1",
            needs_input=False,
            missing_fields=[],
        )
    )
    retriever = StubRetriever(retrieval_response("req-1"))
    generation = StubGeneration(ANSWER)
    citations = StubCitations(
        validation_response(
            "req-1",
            valid=True,
            citation_ids=[EVIDENCE_1.evidence_id],
        )
    )
    workflow, contexts = make_workflow(
        retriever=retriever,
        generation=generation,
        citations=citations,
        cases=cases,
    )

    frames = [
        frame
        async for frame in workflow.stream(case_parameters(), uid="user-1")
    ]

    assert frame_contents(frames) == ANSWER
    assert len(cases.calls) == 1
    assert cases.calls[0].case == CASE
    retrieve_call = retriever.calls[0]
    assert retrieve_call.query == f"{case_json()}\n分析目标：判断虫害风险"
    assert retrieve_call.top_k == 5
    assert retrieve_call.project_id == "course-2026"
    generate_call = generation.calls[0]
    assert generate_call.question == "判断虫害风险"
    assert generate_call.role == Role.TECHNICIAN
    assert generate_call.task_type == "case_analysis"
    assert generate_call.evidences == [EVIDENCE_1, EVIDENCE_2]
    context = await contexts.pop("req-1")
    assert context is not None
    assert context.needs_input is False
    assert context.retrieval_sufficient is True
    assert context.validation_valid is True
    assert context.validated_answer == ANSWER
    assert context.citation_ids == []


async def test_blank_project_id_maps_to_none_for_retrieval():
    retriever = StubRetriever(retrieval_response("req-1"))
    workflow, _ = make_workflow(
        retriever=retriever,
        generation=StubGeneration(ANSWER),
        citations=StubCitations(
            validation_response(
                "req-1",
                valid=True,
                citation_ids=[EVIDENCE_1.evidence_id],
            )
        ),
    )

    frames = [
        frame
        async for frame in workflow.stream(
            parameters(PROJECT_ID=""), uid="user-1"
        )
    ]

    assert frame_contents(frames) == ANSWER
    assert retriever.calls[0].project_id is None


@pytest.fixture
def bad_case_json() -> str:
    return '{"grain_type": "小麦", '  # 截断的 JSON → json.loads 抛异常


CASE = CaseData(
    grain_type="小麦",
    storage_type="平房仓",
    storage_days=30,
    goal="判断虫害风险",
    grain_temperature_c=20.0,
    pest_signs=True,
)


def case_json(case: CaseData = CASE) -> str:
    return json.dumps(case.model_dump(mode="json"), ensure_ascii=False)


def case_parameters(**overrides):
    values = {
        "AGENT_USER_INPUT": "判断虫害风险",
        "USER_ROLE": "technician",
        "TASK_TYPE": "case_analysis",
        "CASE_JSON": case_json(),
    }
    values.update(overrides)
    return parameters(**values)


LONG_ANSWER = (
    "低温能够抑制储粮害虫活动，并延缓粮食生化变化。[E1]"
    "因此低温是实现长期安全储粮的重要条件。"
)


async def test_long_answer_streams_multiple_frames_matching_validation():
    generation = StubGeneration(LONG_ANSWER)
    citations = StubCitations(
        validation_response(
            "req-1",
            valid=True,
            citation_ids=[EVIDENCE_1.evidence_id],
        )
    )
    workflow, contexts = make_workflow(
        retriever=StubRetriever(retrieval_response("req-1")),
        generation=generation,
        citations=citations,
    )

    frames = [
        frame
        async for frame in workflow.stream(parameters(), uid="user-1")
    ]

    assert len(LONG_ANSWER) > 32
    assert len(frames) > 1
    assert frame_contents(frames) == LONG_ANSWER
    context = await contexts.pop("req-1")
    assert context is not None
    assert context.validated_answer == LONG_ANSWER



async def test_malformed_case_json_propagates_for_gateway_error_mapping(
    bad_case_json,
):
    # CASE_JSON 语法错误有意不就地处理：异常传播给网关，
    # 由其统一映射为 WORKFLOW_UNAVAILABLE（见 local_workflow.stream 注释）
    cases = StubCases(
        CaseEvaluateResponse(
            request_id="req-1",
            needs_input=False,
            missing_fields=[],
        )
    )
    workflow, _ = make_workflow(
        retriever=StubRetriever(retrieval_response("req-1")),
        generation=StubGeneration(ANSWER),
        citations=StubCitations(
            validation_response(
                "req-1",
                valid=True,
                citation_ids=[EVIDENCE_1.evidence_id],
            )
        ),
        cases=cases,
    )

    with pytest.raises(json.JSONDecodeError):
        async for _ in workflow.stream(
            case_parameters(CASE_JSON=bad_case_json), uid="user-1"
        ):
            pass

    assert cases.calls == []
