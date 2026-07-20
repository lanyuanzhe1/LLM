import pytest

from app.clients.iflytek_maas import MaaSResult
from app.rag.evidence import Evidence
from app.schemas.tools import GenerateRequest
from app.services.citation_validation import (
    SOURCE_BIBLIOGRAPHY_INSTRUCTION,
    SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION,
)
from app.services.generation import GenerationService, SYSTEM_PROMPT


class FakeMaaS:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    async def generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult:
        self.messages = messages
        assert "[E1]" in messages[-1]["content"]
        return MaaSResult(
            content="结论：低温可抑制害虫活动。[E1]", total_tokens=20
        )


@pytest.mark.asyncio
async def test_generation_maps_alias_to_real_evidence_id():
    evidence = Evidence(
        evidence_id="sha256:real-id",
        document_id="sha256:doc",
        title="低温储粮",
        source="paper.pdf",
        text="低温可抑制害虫活动。",
        score=0.9,
        authority_level="unknown",
    )
    service = GenerationService(FakeMaaS())

    response = await service.generate(
        GenerateRequest(
            request_id="req",
            question="低温储粮有什么作用？",
            evidences=[evidence],
        )
    )

    assert response.cited_evidence_ids == ["sha256:real-id"]
    assert response.usage.total_tokens == 20


@pytest.mark.asyncio
async def test_generation_prompt_uses_the_validator_bibliography_contract():
    evidence = Evidence(
        evidence_id="sha256:real-id",
        document_id="sha256:doc",
        title="低温储粮",
        source="paper.pdf",
        text="低温可抑制害虫活动。",
        score=0.9,
        authority_level="unknown",
    )
    provider = FakeMaaS()
    service = GenerationService(provider)

    await service.generate(
        GenerateRequest(
            request_id="req",
            question="低温储粮有什么作用？",
            evidences=[evidence],
        )
    )

    assert SOURCE_BIBLIOGRAPHY_INSTRUCTION in SYSTEM_PROMPT
    assert SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION in SYSTEM_PROMPT
    assert "Markdown block" in SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION
    assert "裸 URL" in SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION
    assert "引用后链接或定义" in SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION
    assert "任意 scheme:// 链接" in SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION
    assert "危险 scheme" in SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION
    assert "结论 → 依据 → 适用条件 → 不确定性 → 来源" in SYSTEM_PROMPT
    assert "[E1] 低温储粮 — paper.pdf" in provider.messages[-1]["content"]
