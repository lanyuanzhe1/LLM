import pytest
from pydantic import ValidationError

from app.schemas.openai_compat import (
    ChatCompletionRequest,
    validate_forwarded_identifier,
)


def test_request_requires_non_empty_user_message():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="grain-storage-agent",
            messages=[{"role": "assistant", "content": "你好"}],
        )


def test_request_ignores_extra_fields():
    request = ChatCompletionRequest(
        model="grain-storage-agent",
        messages=[{"role": "user", "content": "低温储粮要点？"}],
        chat_id="should-be-ignored",
    )
    assert request.last_user_message() == "低温储粮要点？"


def test_forwarded_identifier_rejects_non_visible_ascii():
    assert validate_forwarded_identifier("chat-1", "X-OpenWebUI-Chat-Id") == "chat-1"
    assert validate_forwarded_identifier(None, "X-OpenWebUI-Chat-Id") is None
    with pytest.raises(ValueError):
        validate_forwarded_identifier("带中文", "X-OpenWebUI-Chat-Id")
