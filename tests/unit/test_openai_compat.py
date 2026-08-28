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


from app.services.openai_compat import (
    OpenAICompatUpstreamError,
    build_workflow_message,
    collect_openai_completion,
    openai_stream,
    preflight_openai_stream,
)


def _frame(event: str, payload: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _agen(frames):
    for frame in frames:
        yield frame


def _sse_payloads(text: str) -> list[str]:
    prefix = "data: "
    return [
        part[len(prefix):]
        for part in text.strip().split("\n\n")
        if part.startswith(prefix)
    ]


async def test_stream_emits_chunks_sources_and_done():
    frames = [
        _frame("meta", {"request_id": "r1"}),
        _frame("delta", {"content": "低温"}),
        _frame("delta", {"content": "储粮"}),
        _frame("citations", {"items": [{"evidence_id": "e1", "title": "粮油储藏", "text": "原文", "score": 0.9}]}),
        _frame("done", {"finish_reason": "stop"}),
    ]
    events = await preflight_openai_stream(_agen(frames), return_after_meta=True)
    text = "".join([
        chunk
        async for chunk in openai_stream(
            events, completion_id="chatcmpl-r1", model="grain-storage-agent",
            created=1, emit_openwebui_status=True,
        )
    ])
    payloads = _sse_payloads(text)
    # 流顺序：role chunk → status(running) → status(complete) → 内容 chunks → source → finish → [DONE]
    assert '"role":"assistant"' in payloads[0]
    assert any('"content":"低温"' in p for p in payloads)
    assert any('"content":"储粮"' in p for p in payloads)
    statuses = [p for p in payloads if '"type":"status"' in p]
    assert len(statuses) == 2 and '"done":false' in statuses[0] and '"done":true' in statuses[1]
    assert any('"type":"source"' in p and '"e1"' in p for p in payloads)
    assert '"finish_reason":"stop"' in payloads[-2]
    assert payloads[-1] == "[DONE]"


async def test_stream_protocol_violation_is_safe_error():
    async def bad():
        yield "garbage\r\n\r\n"
    text = "".join([
        chunk
        async for chunk in openai_stream(
            bad(), completion_id="c", model="m", created=1,
        )
    ])
    payloads = _sse_payloads(text)
    assert "WORKFLOW_PROTOCOL_ERROR" in payloads[-2]
    assert payloads[-1] == "[DONE]"


async def test_collect_non_streaming_completion():
    frames = [
        _frame("meta", {}),
        _frame("delta", {"content": "答案"}),
        _frame("done", {}),
    ]
    result = await collect_openai_completion(
        _agen(frames), completion_id="c1", model="m", created=1,
    )
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "答案"
    assert result["sources"] == []


def test_build_workflow_message_packs_recent_turns():
    messages = [
        ("user", "第一问"), ("assistant", "第一答"),
        ("user", "第二问"), ("assistant", "第二答"),
        ("user", "那温度呢"),
    ]
    packed = build_workflow_message(messages, enabled=True, max_turns=6, max_chars=4000)
    assert "第一问" in packed and "第二答" in packed
    assert packed.rstrip().endswith("那温度呢")


def test_build_workflow_message_disabled_returns_last_user_only():
    messages = [("user", "旧问题"), ("assistant", "旧回答"), ("user", "新问题")]
    assert build_workflow_message(messages, enabled=False, max_turns=6, max_chars=4000) == "新问题"


def test_build_workflow_message_respects_turn_cap():
    messages = []
    for i in range(10):
        messages += [("user", f"问{i}"), ("assistant", f"答{i}")]
    messages.append(("user", "当前"))
    packed = build_workflow_message(messages, enabled=True, max_turns=2, max_chars=4000)
    assert "问9" in packed and "答9" in packed
    assert "问8" in packed
    assert "问7" not in packed


# --- Protocol-machine cases merged from develop-openwebUI (786-line file) ---
# Learning-task / embeds / course_name cases were dropped; status strings were
# adapted to the grain-domain _STATUS_RUNNING/_STATUS_COMPLETE constants.

import asyncio


def _decode_openai_sse(chunks):
    import json

    payloads = []
    for chunk in chunks:
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        raw = chunk[6:-2]
        payloads.append(
            "[DONE]" if raw == "[DONE]" else json.loads(raw)
        )
    return payloads


async def test_openai_stream_preserves_content_sources_and_terminal_order():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-1", "session_id": "chat-1"},
        )
        yield _frame("delta", {"content": "低温"})
        yield _frame("delta", {"content": "抑制害虫。"})
        yield _frame(
            "citations",
            {
                "items": [
                    {
                        "evidence_id": "sha256:evidence",
                        "document_id": "sha256:document",
                        "title": "低温储粮技术应用进展研究",
                        "source": "knowledge/其他论文/低温储粮.pdf",
                        "page": 3,
                        "section": "低温对害虫的影响",
                        "text": "低温条件可抑制储粮害虫的生长发育。",
                        "score": 0.88,
                        "authority_level": "research",
                    }
                ]
            },
        )
        yield _frame("done", {"finish_reason": "stop"})

    chunks = [
        chunk
        async for chunk in openai_stream(
            events(),
            completion_id="chatcmpl-req-1",
            model="grain-storage-agent",
            created=123,
        )
    ]
    payloads = _decode_openai_sse(chunks)

    assert payloads[0]["choices"][0]["delta"] == {
        "role": "assistant",
        "content": "",
    }
    assert [
        payload["choices"][0]["delta"]["content"]
        for payload in payloads[1:3]
    ] == ["低温", "抑制害虫。"]
    assert payloads[3]["event"]["type"] == "source"
    assert payloads[3]["event"]["data"] == {
        "source": {
            "id": "sha256:document",
            "name": "低温储粮技术应用进展研究",
        },
        "document": ["低温条件可抑制储粮害虫的生长发育。"],
        "metadata": [
            {
                "source": "knowledge/其他论文/低温储粮.pdf",
                "name": "低温储粮技术应用进展研究",
                "page": 3,
                "evidence_id": "sha256:evidence",
                "section": "低温对害虫的影响",
                "authority_level": "research",
            }
        ],
        "distances": [0.88],
    }
    assert "choices" not in payloads[3]
    assert payloads[4]["choices"][0]["finish_reason"] == "stop"
    assert payloads[5] == "[DONE]"


async def test_openai_stream_completes_status_when_done_has_no_delta():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-empty", "session_id": "chat-empty"},
        )
        yield _frame("done", {"finish_reason": "stop"})

    payloads = _decode_openai_sse(
        [
            chunk
            async for chunk in openai_stream(
                events(),
                completion_id="chatcmpl-empty",
                model="grain-storage-agent",
                created=123,
                emit_openwebui_status=True,
            )
        ]
    )
    statuses = [
        item["event"]["data"]
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
    ]

    assert statuses == [
        {
            "description": "正在检索粮储知识库并核对依据",
            "done": False,
        },
        {
            "description": "已核对知识库依据",
            "done": True,
        },
    ]
    assert payloads[-2]["choices"][0]["finish_reason"] == "stop"
    assert payloads[-1] == "[DONE]"


async def test_openai_stream_finishes_pending_status_before_stream_error():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-error", "session_id": "chat-error"},
        )
        yield _frame("citations", {"items": []})
        yield _frame(
            "error",
            {
                "code": "WORKFLOW_UNAVAILABLE",
                "message": "智能体工作流暂时不可用",
                "retryable": True,
            },
        )

    payloads = _decode_openai_sse(
        [
            chunk
            async for chunk in openai_stream(
                events(),
                completion_id="chatcmpl-stream-error",
                model="grain-storage-agent",
                created=123,
                emit_openwebui_status=True,
            )
        ]
    )
    statuses = [
        item["event"]["data"]
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
    ]

    assert statuses == [
        {
            "description": "正在检索粮储知识库并核对依据",
            "done": False,
        },
        {
            "description": "本轮处理未完成，请稍后重试",
            "done": True,
        },
    ]
    assert payloads[-2]["error"]["code"] == "WORKFLOW_UNAVAILABLE"
    assert payloads[-1] == "[DONE]"


async def test_openai_stream_finishes_pending_status_on_protocol_error():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-protocol", "session_id": "chat-protocol"},
        )
        yield _frame("citations", {"items": []})
        yield "malformed upstream event\n\n"

    payloads = _decode_openai_sse(
        [
            chunk
            async for chunk in openai_stream(
                events(),
                completion_id="chatcmpl-protocol",
                model="grain-storage-agent",
                created=123,
                emit_openwebui_status=True,
            )
        ]
    )
    statuses = [
        item["event"]["data"]
        for item in payloads
        if isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
    ]

    assert statuses[-1] == {
        "description": "本轮处理未完成，请稍后重试",
        "done": True,
    }
    assert payloads[-2]["error"]["code"] == "WORKFLOW_PROTOCOL_ERROR"
    assert payloads[-1] == "[DONE]"


async def test_openai_stream_omits_status_for_generic_client():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-generic", "session_id": "chat-generic"},
        )
        yield _frame("delta", {"content": "回答"})
        yield _frame("done", {"finish_reason": "stop"})

    payloads = _decode_openai_sse(
        [
            chunk
            async for chunk in openai_stream(
                events(),
                completion_id="chatcmpl-generic",
                model="grain-storage-agent",
                created=123,
            )
        ]
    )

    assert not any(
        isinstance(item, dict)
        and item.get("event", {}).get("type") == "status"
        for item in payloads
    )
    assert payloads[1]["choices"][0]["delta"]["content"] == "回答"
    assert payloads[-1] == "[DONE]"


async def test_collect_openai_completion_aggregates_answer_and_sources():
    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-2", "session_id": "chat-2"},
        )
        yield _frame("delta", {"content": "第一段"})
        yield _frame("delta", {"content": "第二段"})
        yield _frame(
            "citations",
            {
                "items": [
                    {
                        "evidence_id": "sha256:e2",
                        "document_id": "sha256:d2",
                        "title": "粮温资料",
                        "source": "knowledge/粮温.pdf",
                        "text": "证据",
                        "score": None,
                        "authority_level": "industry",
                    }
                ]
            },
        )
        yield _frame("done", {"finish_reason": "stop"})

    response = await collect_openai_completion(
        events(),
        completion_id="chatcmpl-req-2",
        model="grain-storage-agent",
        created=456,
    )

    assert response["object"] == "chat.completion"
    assert response["choices"][0]["message"] == {
        "role": "assistant",
        "content": "第一段第二段",
    }
    assert response["sources"][0]["source"]["id"] == "sha256:d2"
    assert "distances" not in response["sources"][0]


async def test_openai_stream_converts_internal_error_without_leaking_details():
    async def events():
        yield _frame(
            "error",
            {
                "code": "WORKFLOW_UNAVAILABLE",
                "message": "智能体工作流暂时不可用",
                "retryable": True,
                "provider_secret": "must-not-leak",
            },
        )

    chunks = [
        chunk
        async for chunk in openai_stream(
            events(),
            completion_id="chatcmpl-error",
            model="grain-storage-agent",
            created=789,
        )
    ]
    payloads = _decode_openai_sse(chunks)

    assert payloads == [
        {
            "error": {
                "message": "智能体工作流暂时不可用",
                "type": "server_error",
                "param": None,
                "code": "WORKFLOW_UNAVAILABLE",
            }
        },
        "[DONE]",
    ]
    assert "must-not-leak" not in "".join(chunks)


async def test_stream_preflight_closes_internal_generator_on_early_error():
    state = {"closed": False}

    async def events():
        try:
            yield _frame(
                "meta",
                {"request_id": "req-preflight", "session_id": "chat"},
            )
            yield _frame(
                "error",
                {
                    "code": "WORKFLOW_UNAVAILABLE",
                    "message": "智能体工作流暂时不可用",
                },
            )
        finally:
            state["closed"] = True

    with pytest.raises(
        OpenAICompatUpstreamError,
        match="智能体工作流暂时不可用",
    ):
        await preflight_openai_stream(events())

    assert state["closed"] is True


async def test_openwebui_preflight_returns_after_meta_while_workflow_runs():
    release_workflow = asyncio.Event()

    async def events():
        yield _frame(
            "meta",
            {"request_id": "req-live-status", "session_id": "chat-live"},
        )
        await release_workflow.wait()
        yield _frame("delta", {"content": "回答"})

    replay = await asyncio.wait_for(
        preflight_openai_stream(
            events(),
            return_after_meta=True,
        ),
        timeout=0.05,
    )
    try:
        assert await anext(replay) == _frame(
            "meta",
            {"request_id": "req-live-status", "session_id": "chat-live"},
        )
    finally:
        release_workflow.set()
        await replay.aclose()


async def test_openai_stream_closes_internal_generator_when_client_stops():
    state = {"closed": False}

    async def events():
        try:
            yield _frame(
                "meta",
                {"request_id": "req-3", "session_id": "chat-3"},
            )
            yield _frame("delta", {"content": "不应继续"})
        finally:
            state["closed"] = True

    stream = openai_stream(
        events(),
        completion_id="chatcmpl-req-3",
        model="grain-storage-agent",
        created=999,
    )
    await anext(stream)
    await stream.aclose()

    assert state["closed"] is True
