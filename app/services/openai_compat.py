import json
from collections.abc import AsyncIterator
from typing import Any

_STATUS_RUNNING = "正在检索粮储知识库并核对依据"
_STATUS_COMPLETE = "已核对知识库依据"
_STATUS_FAILED = "本轮处理未完成，请稍后重试"


class OpenAICompatUpstreamError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_internal_event(chunk: str) -> tuple[str, dict[str, Any]]:
    if not chunk.endswith("\n\n"):
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        )
    lines = chunk[:-2].splitlines()
    if (
        len(lines) != 2
        or not lines[0].startswith("event: ")
        or not lines[1].startswith("data: ")
    ):
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        )
    try:
        data = json.loads(lines[1][6:])
    except json.JSONDecodeError as exc:
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        ) from exc
    if not isinstance(data, dict):
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        )
    return lines[0][7:], data


def _openai_sse(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        data = payload
    else:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"data: {data}\n\n"


def _status(description: str, *, done: bool) -> dict[str, Any]:
    return {
        "event": {
            "type": "status",
            "data": {
                "description": description,
                "done": done,
            },
        }
    }


def _chunk(
    *,
    completion_id: str,
    model: str,
    created: int,
    delta: dict[str, Any],
    finish_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _source(item: dict[str, Any]) -> dict[str, Any]:
    evidence_id = str(item.get("evidence_id") or "unknown-evidence")
    document_id = str(item.get("document_id") or evidence_id)
    name = str(item.get("title") or evidence_id)
    metadata: dict[str, Any] = {
        "name": name,
        "evidence_id": evidence_id,
    }
    for field in ("source", "page", "section", "authority_level"):
        value = item.get(field)
        if value is not None:
            metadata[field] = value

    result: dict[str, Any] = {
        "source": {"id": document_id, "name": name},
        "document": [str(item["text"])] if item.get("text") else [],
        "metadata": [metadata],
    }
    if item.get("score") is not None:
        result["distances"] = [item["score"]]
    return result


def _sources(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items", [])
    if not isinstance(items, list):
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        )
    return [_source(item) for item in items if isinstance(item, dict)]


def _error_payload(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "message": str(data.get("message") or "智能体工作流暂时不可用"),
            "type": "server_error",
            "param": None,
            "code": str(data.get("code") or "WORKFLOW_UNAVAILABLE"),
        }
    }


async def _close_iterator(events: AsyncIterator[str]) -> None:
    close = getattr(events, "aclose", None)
    if close is not None:
        await close()


async def _replay_events(
    prefetched: list[str],
    events: AsyncIterator[str],
) -> AsyncIterator[str]:
    try:
        for event in prefetched:
            yield event
        async for event in events:
            yield event
    finally:
        await _close_iterator(events)


async def preflight_openai_stream(
    events: AsyncIterator[str],
    *,
    return_after_meta: bool = False,
) -> AsyncIterator[str]:
    prefetched: list[str] = []
    try:
        while True:
            raw_event = await anext(events)
            event, data = _parse_internal_event(raw_event)
            if event == "error":
                raise OpenAICompatUpstreamError(
                    str(data.get("code") or "WORKFLOW_UNAVAILABLE"),
                    str(
                        data.get("message")
                        or "智能体工作流暂时不可用"
                    ),
                )
            prefetched.append(raw_event)
            if return_after_meta and event == "meta":
                return _replay_events(prefetched, events)
            if event != "meta":
                return _replay_events(prefetched, events)
    except StopAsyncIteration as exc:
        raise OpenAICompatUpstreamError(
            "WORKFLOW_PROTOCOL_ERROR",
            "智能体工作流响应未通过安全校验",
        ) from exc
    except BaseException:
        await _close_iterator(events)
        raise


async def openai_stream(
    events: AsyncIterator[str],
    *,
    completion_id: str,
    model: str,
    created: int,
    emit_openwebui_status: bool = False,
) -> AsyncIterator[str]:
    terminal = False
    status_started = False
    status_completed = False
    try:
        async for raw_event in events:
            event, data = _parse_internal_event(raw_event)
            if event == "meta":
                yield _openai_sse(
                    _chunk(
                        completion_id=completion_id,
                        model=model,
                        created=created,
                        delta={"role": "assistant", "content": ""},
                    )
                )
                if emit_openwebui_status and not status_started:
                    status_started = True
                    yield _openai_sse(
                        _status(_STATUS_RUNNING, done=False)
                    )
            elif event == "delta":
                if status_started and not status_completed:
                    status_completed = True
                    yield _openai_sse(
                        _status(_STATUS_COMPLETE, done=True)
                    )
                yield _openai_sse(
                    _chunk(
                        completion_id=completion_id,
                        model=model,
                        created=created,
                        delta={"content": str(data.get("content") or "")},
                    )
                )
            elif event == "citations":
                sources = _sources(data)
                for source in sources:
                    yield _openai_sse(
                        {
                            "event": {
                                "type": "source",
                                "data": source,
                            }
                        }
                    )
            elif event == "done":
                if status_started and not status_completed:
                    status_completed = True
                    yield _openai_sse(
                        _status(_STATUS_COMPLETE, done=True)
                    )
                terminal = True
                yield _openai_sse(
                    _chunk(
                        completion_id=completion_id,
                        model=model,
                        created=created,
                        delta={},
                        finish_reason="stop",
                    )
                )
                yield _openai_sse("[DONE]")
                return
            elif event == "error":
                if status_started and not status_completed:
                    status_completed = True
                    yield _openai_sse(
                        _status(_STATUS_FAILED, done=True)
                    )
                terminal = True
                yield _openai_sse(_error_payload(data))
                yield _openai_sse("[DONE]")
                return
            else:
                raise OpenAICompatUpstreamError(
                    "WORKFLOW_PROTOCOL_ERROR",
                    "智能体工作流响应未通过安全校验",
                )
        if not terminal:
            if status_started and not status_completed:
                status_completed = True
                yield _openai_sse(
                    _status(_STATUS_FAILED, done=True)
                )
            yield _openai_sse(
                _error_payload(
                    {
                        "code": "WORKFLOW_PROTOCOL_ERROR",
                        "message": "智能体工作流响应未通过安全校验",
                    }
                )
            )
            yield _openai_sse("[DONE]")
    except OpenAICompatUpstreamError as exc:
        if status_started and not status_completed:
            status_completed = True
            yield _openai_sse(
                _status(_STATUS_FAILED, done=True)
            )
        yield _openai_sse(
            _error_payload({"code": exc.code, "message": exc.message})
        )
        yield _openai_sse("[DONE]")
    finally:
        await _close_iterator(events)


async def collect_openai_completion(
    events: AsyncIterator[str],
    *,
    completion_id: str,
    model: str,
    created: int,
) -> dict[str, Any]:
    content: list[str] = []
    sources: list[dict[str, Any]] = []
    completed = False
    try:
        async for raw_event in events:
            event, data = _parse_internal_event(raw_event)
            if event == "delta":
                content.append(str(data.get("content") or ""))
            elif event == "citations":
                sources = _sources(data)
            elif event == "done":
                completed = True
                break
            elif event == "error":
                raise OpenAICompatUpstreamError(
                    str(data.get("code") or "WORKFLOW_UNAVAILABLE"),
                    str(data.get("message") or "智能体工作流暂时不可用"),
                )
            elif event != "meta":
                raise OpenAICompatUpstreamError(
                    "WORKFLOW_PROTOCOL_ERROR",
                    "智能体工作流响应未通过安全校验",
                )
        if not completed:
            raise OpenAICompatUpstreamError(
                "WORKFLOW_PROTOCOL_ERROR",
                "智能体工作流响应未通过安全校验",
            )
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "".join(content),
                    },
                    "finish_reason": "stop",
                }
            ],
            "sources": sources,
        }
    finally:
        await _close_iterator(events)


def build_workflow_message(
    messages: list[tuple[str, str]],
    *,
    enabled: bool,
    max_turns: int,
    max_chars: int,
) -> str:
    """Compose AGENT_USER_INPUT: packed recent history + last user message.

    ``messages`` is the ordered (role, content) list from the request.
    A "turn" is a user/assistant pair; only complete pairs are packed,
    newest first until max_turns or max_chars is reached.
    """
    last_index = max(
        index
        for index, (role, content) in enumerate(messages)
        if role == "user" and content
    )
    last_user = messages[last_index][1]
    if not enabled:
        return last_user
    candidates = messages[:last_index]
    pairs: list[tuple[str, str]] = []
    index = len(candidates)
    while index >= 2 and len(pairs) < max_turns:
        user_role, user_text = candidates[index - 2]
        asst_role, asst_text = candidates[index - 1]
        if user_role == "user" and asst_role == "assistant" and user_text and asst_text:
            pairs.append((user_text, asst_text))
        index -= 2
    pairs.reverse()
    lines: list[str] = []
    total = 0
    for user_text, asst_text in pairs:
        block = f"用户: {user_text}\n助手: {asst_text}"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    if not lines:
        return last_user
    return "[对话历史]\n" + "\n".join(lines) + "\n[当前问题]\n" + last_user
