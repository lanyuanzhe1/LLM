import re
from typing import Protocol

from app.clients.iflytek_maas import MaaSResult
from app.rag.evidence import canonical_display_label
from app.schemas.tools import (
    GenerateRequest,
    GenerateResponse,
    GenerationUsage,
)
from app.services.citation_validation import (
    SOURCE_BIBLIOGRAPHY_INSTRUCTION,
    SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION,
)


class MaaSProvider(Protocol):
    async def generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult: ...


SYSTEM_PROMPT = f"""你是粮食储藏领域专用智能体。
只能依据用户消息中的证据回答，不得补充证据中不存在的数值、条款或操作要求。
关键结论后必须使用 [E1]、[E2] 形式引用证据。
输出必须使用独立章节，并严格按结论 → 依据 → 适用条件 → 不确定性 → 来源排序。
{SUBSTANTIVE_PLAIN_TEXT_INSTRUCTION}
{SOURCE_BIBLIOGRAPHY_INSTRUCTION}
证据不足时明确说明，不得猜测。"""


class GenerationService:
    def __init__(self, maas: MaaSProvider) -> None:
        self.maas = maas

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        aliases = {
            f"E{index}": evidence.evidence_id
            for index, evidence in enumerate(request.evidences, start=1)
        }
        evidence_text = "\n\n".join(
            f"[E{index}] {canonical_display_label(item.title)} — "
            f"{canonical_display_label(item.source)}\n{item.text}"
            for index, item in enumerate(request.evidences, start=1)
        )
        feedback = (
            "\n上次校验问题：\n- "
            + "\n- ".join(request.validation_feedback)
            if request.validation_feedback
            else ""
        )
        user_prompt = (
            f"用户角色：{request.role.value}\n"
            f"任务类型：{request.task_type}\n"
            f"问题：{request.question}\n\n"
            f"证据：\n{evidence_text}{feedback}"
        )
        result = await self.maas.generate(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            uid=request.request_id,
        )
        cited_aliases = re.findall(r"\[(E\d+)\]", result.content)
        cited_ids = list(
            dict.fromkeys(
                aliases[alias] for alias in cited_aliases if alias in aliases
            )
        )
        return GenerateResponse(
            request_id=request.request_id,
            answer=result.content,
            cited_evidence_ids=cited_ids,
            usage=GenerationUsage(total_tokens=result.total_tokens),
        )
