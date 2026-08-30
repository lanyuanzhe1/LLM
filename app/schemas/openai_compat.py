from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OpenAICompatModel(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class ChatMessage(OpenAICompatModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(default="", max_length=32_000)


class ChatCompletionRequest(OpenAICompatModel):
    model: str = Field(min_length=1, max_length=128)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=256)
    stream: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def require_valid_user_message(self) -> "ChatCompletionRequest":
        message = next(
            (
                item.content
                for item in reversed(self.messages)
                if item.role == "user" and item.content
            ),
            None,
        )
        if message is None:
            raise ValueError("a non-empty user message is required")
        if len(message) > 8_000:
            raise ValueError("the last user message exceeds 8000 characters")
        return self

    def last_user_message(self) -> str:
        return next(
            item.content
            for item in reversed(self.messages)
            if item.role == "user" and item.content
        )


def validate_forwarded_identifier(
    value: str | None,
    field: str,
) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if (
        not 1 <= len(normalized) <= 128
        or any(
            ord(character) < 0x21 or ord(character) > 0x7E
            for character in normalized
        )
    ):
        raise ValueError(
            f"{field} must contain 1-128 visible ASCII characters"
        )
    return normalized
