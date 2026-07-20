from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowChoiceDelta(BaseModel):
    role: str = "assistant"
    content: str = ""


class WorkflowChoice(BaseModel):
    delta: WorkflowChoiceDelta
    index: int = 0
    finish_reason: str | None = None


class WorkflowFrame(BaseModel):
    code: int
    message: str
    id: str
    choices: list[WorkflowChoice] = Field(default_factory=list)
    usage: dict[str, Any] | None = None


class ErrorEvent(BaseModel):
    code: str
    message: str
    retryable: bool = Field(strict=True)


class DoneEvent(BaseModel):
    finish_reason: Literal["stop", "needs_input"] = "stop"
    missing_fields: list[str] = Field(default_factory=list)


def sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    import json

    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
