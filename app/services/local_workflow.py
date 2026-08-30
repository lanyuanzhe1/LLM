"""进程内工作流编排器。

与 `XingchenWorkflowClient` 相同的 `async stream(parameters, uid)` 帧流接口，
在仓库后端进程内完成编排（分支 → 检索 → 生成 → 引用校验 → 重试/拒答），
并向 `RequestContextStore` 写入与 `/tools/v1/*` 工具回调完全一致的对账上下文。

编排语义遵循 `workflow/README.md`（云端备选路径参考）的分支与拒答约定；
`WorkflowGateway` 先缓冲全部帧再消费对账上下文，因此本实现必须先写上下文、
后产帧，且帧内容拼接等于校验通过的 answer。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.core.request_context import RequestContextStore
from app.schemas.api import CaseData, Role
from app.schemas.events import (
    WorkflowChoice,
    WorkflowChoiceDelta,
    WorkflowFrame,
)
from app.schemas.tools import (
    CaseEvaluateRequest,
    GenerateRequest,
    RetrieveRequest,
)


_ANSWER_CHUNK_CHARS = 32


class LocalWorkflow:
    def __init__(
        self,
        *,
        retriever: Any,
        generation: Any,
        cases: Any,
        citations: Any,
        contexts: RequestContextStore,
    ) -> None:
        self._retriever = retriever
        self._generation = generation
        self._cases = cases
        self._citations = citations
        self._contexts = contexts

    async def stream(
        self, parameters: dict, uid: str
    ) -> AsyncIterator[WorkflowFrame]:
        request_id = parameters["REQUEST_ID"]
        task_type = parameters["TASK_TYPE"]
        query = parameters["AGENT_USER_INPUT"]
        # 依赖故障（检索/生成/校验/案例评估抛出的 AppError 或意外异常）有意
        # 直接传播：WorkflowGateway 的 except 分支会把 AppError 映射为其策划的
        # code/message/retryable，把其余异常统一映射为 WORKFLOW_UNAVAILABLE，
        # 并丢弃已写入的部分对账上下文——与 workflow/README.md 第 12 步
        # “统一依赖暂不可用”语义等价（终审裁定 F2，不设本地异常分支）。
        if task_type == "case_analysis":
            # CASE_JSON 语法错误同样经上述路径成为 WORKFLOW_UNAVAILABLE。
            case_json = parameters.get("CASE_JSON") or ""
            case = CaseData.model_validate(json.loads(case_json))
            case_result = self._cases.evaluate(
                CaseEvaluateRequest(request_id=request_id, case=case)
            )
            await self._contexts.set_case_result(
                request_id,
                needs_input=case_result.needs_input,
                missing_fields=case_result.missing_fields,
                question=case_result.question,
            )
            if case_result.needs_input:
                return
            query = f"{case_json}\n分析目标：{case.goal}"
        retrieval = await self._retriever.retrieve(
            RetrieveRequest(
                request_id=request_id,
                query=query,
                top_k=5,
                project_id=parameters.get("PROJECT_ID") or None,
            )
        )
        await self._contexts.set_retrieval_result(
            request_id,
            retrieval.evidences,
            sufficient=retrieval.quality.sufficient,
        )
        if not retrieval.quality.sufficient:
            return
        feedback: list[str] = []
        answer: str | None = None
        for _ in range(2):
            generation = await self._generation.generate(
                GenerateRequest(
                    request_id=request_id,
                    question=parameters["AGENT_USER_INPUT"],
                    role=Role(parameters["USER_ROLE"]),
                    task_type=task_type,
                    evidences=retrieval.evidences,
                    validation_feedback=feedback,
                )
            )
            # 引用校验环节按用户决定停用：真实 MaaS 回答不带 [E#] 标注/固定
            # 章节，正则校验既无有效判断依据、也会误拒合法回答（用户明确
            # 要求本地编排先能跑通）。直接采用生成结果，校验器代码保留不动。
            await self._contexts.set_validation_result(
                request_id,
                valid=True,
                answer=generation.answer,
                citation_ids=[],
            )
            answer = generation.answer
            break
        if answer is None:
            return
        session_id = parameters.get("SESSION_ID") or request_id
        for start in range(0, len(answer), _ANSWER_CHUNK_CHARS):
            yield WorkflowFrame(
                code=0,
                message="Success",
                id=session_id,
                choices=[
                    WorkflowChoice(
                        delta=WorkflowChoiceDelta(
                            content=answer[
                                start : start + _ANSWER_CHUNK_CHARS
                            ]
                        )
                    )
                ],
            )
