from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rag.evidence import Evidence
from app.schemas.api import CaseData, Role


RequestId = Annotated[str, Field(min_length=1, max_length=128)]
ShortText = Annotated[str, Field(min_length=1, max_length=128)]
LongText = Annotated[str, Field(min_length=1, max_length=32000)]
QueryText = Annotated[str, Field(min_length=1, max_length=8000)]
StrictInteger = Annotated[int, Field(strict=True)]
StrictFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]
StrictBoolean = Annotated[bool, Field(strict=True)]


class StrictToolRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ResponseModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class RetrievalFilters(StrictToolRequest):
    source_type: ShortText | None = None
    authority_level: ShortText | None = None


class RetrieveRequest(StrictToolRequest):
    request_id: RequestId
    query: QueryText
    top_k: StrictInteger = Field(default=5, ge=1, le=20)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class RetrievalQuality(ResponseModel):
    top_score: StrictFloat = Field(ge=-1.0, le=1.0)
    sufficient: StrictBoolean


class RetrieveResponse(ResponseModel):
    request_id: RequestId
    query: QueryText
    evidences: list[Evidence] = Field(max_length=20)
    quality: RetrievalQuality


def _require_unique_evidence_ids(evidences: list[Evidence]) -> None:
    if len({evidence.evidence_id for evidence in evidences}) != len(evidences):
        raise ValueError("evidence_id must be unique")


class GenerateRequest(StrictToolRequest):
    request_id: RequestId
    question: LongText
    role: Role = Role.STUDENT
    task_type: ShortText = "knowledge_qa"
    evidences: list[Evidence] = Field(min_length=1, max_length=5)
    validation_feedback: list[LongText] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> "GenerateRequest":
        _require_unique_evidence_ids(self.evidences)
        return self


class GenerationUsage(ResponseModel):
    total_tokens: StrictInteger = Field(default=0, ge=0)


class GenerateResponse(ResponseModel):
    request_id: RequestId
    answer: LongText
    cited_evidence_ids: list[RequestId] = Field(max_length=20)
    usage: GenerationUsage = Field(default_factory=GenerationUsage)


class CaseEvaluateRequest(StrictToolRequest):
    request_id: RequestId
    case: CaseData


class RuleResult(ResponseModel):
    rule_id: ShortText
    conclusion: LongText
    evidence_ids: list[RequestId] = Field(max_length=20)
    conditions: dict[str, Any] = Field(max_length=20)


class CaseEvaluateResponse(ResponseModel):
    request_id: RequestId
    needs_input: StrictBoolean
    missing_fields: list[ShortText] = Field(max_length=20)
    question: LongText | None = None
    rules: list[RuleResult] = Field(default_factory=list, max_length=20)


class CitationValidateRequest(StrictToolRequest):
    request_id: RequestId
    answer: LongText
    evidences: list[Evidence] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def require_unique_evidence_ids(self) -> "CitationValidateRequest":
        _require_unique_evidence_ids(self.evidences)
        return self


class CitationCoverage(ResponseModel):
    total_sentences: StrictInteger = Field(ge=0)
    cited_sentences: StrictInteger = Field(ge=0)
    ratio: StrictFloat = Field(ge=0.0, le=1.0)


def _empty_citation_coverage() -> CitationCoverage:
    return CitationCoverage(
        total_sentences=0,
        cited_sentences=0,
        ratio=0.0,
    )


class CitationValidateResponse(ResponseModel):
    request_id: RequestId
    valid: StrictBoolean
    errors: list[LongText] = Field(max_length=20)
    unsupported_sentences: list[LongText] = Field(max_length=20)
    citation_ids: list[RequestId] = Field(max_length=20)
    coverage: CitationCoverage = Field(default_factory=_empty_citation_coverage)
