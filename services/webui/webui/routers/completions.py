"""Slim OpenAI-compatible chat completions (spec §6.3, replaces middleware.py).

POST /api/chat/completions (Bearer JWT):
1. ``get_verified_user``；解析 ``{model, messages, chat_id?, stream?}``。
2. ``chat_id`` 提供且库中存在 → 校验属主（非属主 → 404，对参考 401 的显式
   偏离）；提供但库中不存在 → 沿用该 id 新建（参考前端客户端生成 id 的
   新建流）；未提供 → 新 uuid4。新建经 ``Chats.insert_new_chat``
   （title=末条 user 消息前 40 字符，初始 history
   ``{"messages": {}, "currentId": None}``，``messages: []``）。
3. 转发 messages = DB history（currentId 沿 parentId 回溯成链，content 为
   list[blocks] 时拼接 type=="text" 块的 text）+ 本轮末条 user 消息。
4. 首帧 ``data: {"event":{"type":"chat_id","data":{"chat_id":"..."}}}``，
   随后逐字节透传 ``upstream.stream_post("/v1/chat/completions", ...)``
   （头含服务密钥 + X-OpenWebUI-Chat-Id / X-OpenWebUI-User-Id），同时缓冲：
   ``chat.completion.chunk`` 的 ``delta.content`` 拼成 assistant 全文；
   ``{"event":{"type":"source"}}`` 收集进 sources；``{"error":...}`` 记失败。
5. 正常结束（见到 ``data: [DONE]`` 且无 error）→ 依序 upsert user 消息
   （parentId=旧 currentId 或 None）→ assistant 消息（parentId=user 消息
   id，带 sources），父消息 childrenIds 追加，history.currentId=assistant
   id，``chat.chat["messages"]`` 同步为回溯链，``update_chat_by_id`` 落库。
6. 失败（上游 HTTP 错或流中 error）→ yield 安全 error 事件 + [DONE]；
   整轮不落库；若 chat 系本次新建则删除（§6.3.7），不留空会话。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from webui.models.chats import ChatForm, ChatModel, Chats
from webui.utils import upstream
from webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()

SAFE_ERROR_MESSAGE = '粮储问答服务暂时不可用'
SAFE_ERROR_CODE = 'WORKFLOW_UNAVAILABLE'


class ChatCompletionMessage(BaseModel):
    model_config = ConfigDict(extra='ignore')

    role: str
    content: Any = None


class ChatCompletionForm(BaseModel):
    model_config = ConfigDict(extra='ignore')

    model: str
    messages: list[ChatCompletionMessage]
    chat_id: str | None = None
    # Slice 1 仅支持流式：该形参仅作外形兼容被忽略，上游恒以 stream=True 转发
    stream: bool = True


def _sse(payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return f'data: {data}\n\n'.encode('utf-8')


def _content_to_text(content: Any) -> str:
    """content 为 list[blocks] 时拼接 type=="text" 块的 text 为纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                parts.append(str(block.get('text') or ''))
            elif isinstance(block, str):
                parts.append(block)
        return ''.join(parts)
    return '' if content is None else str(content)


def _backtrack_messages(history: dict | None) -> list[dict]:
    """从 history.currentId 沿 parentId 回溯成时间正序消息链。"""
    history = history if isinstance(history, dict) else {}
    messages_map = history.get('messages') if isinstance(history.get('messages'), dict) else {}
    current_id = history.get('currentId')

    chain: list[dict] = []
    seen_ids = set()
    while current_id and current_id in messages_map and current_id not in seen_ids:
        seen_ids.add(current_id)
        message = messages_map[current_id]
        if isinstance(message, dict):
            chain.append(message)
            current_id = message.get('parentId')
        else:
            break
    chain.reverse()
    return chain


def _forward_messages(chat: ChatModel, user_text: str) -> list[dict]:
    """DB history 回溯链（文本化）+ 本轮末条 user 消息。"""
    history = (chat.chat or {}).get('history')
    messages = [
        {'role': message.get('role'), 'content': _content_to_text(message.get('content'))}
        for message in _backtrack_messages(history)
        if message.get('role') in ('user', 'assistant')
    ]
    messages.append({'role': 'user', 'content': user_text})
    return messages


async def _persist_turn(
    chat: ChatModel,
    *,
    user_content: str,
    assistant_content: str,
    sources: list,
) -> None:
    """按 spec §6.3 消息图契约落库一轮 user+assistant。"""
    chat_dict = dict(chat.chat or {})
    history = chat_dict.get('history') if isinstance(chat_dict.get('history'), dict) else {}
    history.setdefault('messages', {})
    chat_dict['history'] = history

    previous_current_id = Chats.get_current_message_id(chat_dict)
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())

    Chats.upsert_message_to_history(
        history,
        user_message_id,
        {
            'id': user_message_id,
            'role': 'user',
            'content': user_content,
            'parentId': previous_current_id,
            'childrenIds': [],
            'timestamp': int(time.time()),
        },
    )
    if previous_current_id and previous_current_id in history['messages']:
        history['messages'][previous_current_id].setdefault('childrenIds', []).append(user_message_id)

    Chats.upsert_message_to_history(
        history,
        assistant_message_id,
        {
            'id': assistant_message_id,
            'role': 'assistant',
            'content': assistant_content,
            'parentId': user_message_id,
            'childrenIds': [],
            'timestamp': int(time.time()),
            'sources': sources,
        },
    )
    history['messages'][user_message_id].setdefault('childrenIds', []).append(assistant_message_id)
    history['currentId'] = assistant_message_id

    # messages 数组与 history.messages map 同步为 currentId 回溯链
    chat_dict['messages'] = _backtrack_messages(history)

    updated = await Chats.update_chat_by_id(chat.id, chat_dict)
    if updated is None:
        log.error('persist turn failed: chat %s not updated', chat.id)


@router.post('/completions')
async def chat_completions(
    form_data: ChatCompletionForm,
    user=Depends(get_verified_user),
):
    last_user_message = next(
        (message for message in reversed(form_data.messages) if message.role == 'user'),
        None,
    )
    if last_user_message is None:
        raise HTTPException(status_code=400, detail='请求缺少 user 消息')
    user_text = _content_to_text(last_user_message.content)

    chat: ChatModel | None = None
    if form_data.chat_id:
        existing = await Chats.get_chat_by_id(form_data.chat_id)
        if existing is not None and existing.user_id != user.id:
            # 偏离参考：非属主一律 404（参考此处为 401）
            raise HTTPException(status_code=404, detail='会话不存在')
        chat = existing

    created_new = False
    if chat is None:
        chat_id = form_data.chat_id or str(uuid.uuid4())
        chat = await Chats.insert_new_chat(
            chat_id,
            user.id,
            ChatForm(
                chat={
                    'title': user_text[:40] or 'New Chat',
                    'models': [form_data.model],
                    'history': {'messages': {}, 'currentId': None},
                    'messages': [],
                }
            ),
        )
        if chat is None:
            raise HTTPException(status_code=500, detail='会话创建失败')
        created_new = True

    chat_id = chat.id
    forward_messages = _forward_messages(chat, user_text)

    async def event_stream() -> AsyncIterator[bytes]:
        # 首帧：自定义 chat_id 事件
        yield _sse({'event': {'type': 'chat_id', 'data': {'chat_id': chat_id}}})

        assistant_parts: list[str] = []
        sources: list = []
        failed = False
        terminal = False

        def handle_payload(payload: str) -> None:
            nonlocal failed
            try:
                data = json.loads(payload)
            except ValueError:
                return
            if not isinstance(data, dict):
                return
            if isinstance(data.get('error'), dict):
                failed = True  # 流中 error 事件同样视为失败
            elif data.get('object') == 'chat.completion.chunk':
                for choice in data.get('choices') or []:
                    delta = (choice or {}).get('delta') or {}
                    if delta.get('content'):
                        assistant_parts.append(str(delta['content']))
            elif (data.get('event') or {}).get('type') == 'source':
                sources.append(data['event'].get('data'))

        async def rollback_new_chat() -> None:
            # 整轮不落库；本次新建的 chat 一并撤销（§6.3.7）
            if created_new:
                deleted = await Chats.delete_chat_by_id_and_user_id(chat_id, user.id)
                if not deleted:
                    log.warning(
                        'failed-turn cleanup left empty chat behind (chat_id=%s)', chat_id
                    )

        # 逐帧透传：落库必须先于 yield "[DONE]" 完成。客户端读到 [DONE]
        # 即断开，若落库排在 yield 之后会被 uvicorn 的连接取消（CancelledError）
        # 打断——这正是真实链路 currentId 恒为 null 的根因。
        # 按 b"\n\n" 分帧是安全的：\n(0x0A) 不会出现在 UTF-8 多字节字符中间，
        # 帧内 decode 不会跨帧断字符。
        byte_buffer = b''
        try:
            async for raw in upstream.stream_post(
                '/v1/chat/completions',
                json_body={'model': form_data.model, 'messages': forward_messages, 'stream': True},
                headers=upstream.service_headers(
                    {
                        'X-OpenWebUI-Chat-Id': chat_id,
                        'X-OpenWebUI-User-Id': user.id,
                    }
                ),
            ):
                byte_buffer += raw
                while b'\n\n' in byte_buffer:
                    frame_bytes, byte_buffer = byte_buffer.split(b'\n\n', 1)
                    frame = frame_bytes.decode('utf-8', errors='replace')
                    done = False
                    for line in frame.splitlines():
                        if not line.startswith('data: '):
                            continue
                        payload = line[len('data: '):].strip()
                        if payload == '[DONE]':
                            done = True
                            terminal = True
                        else:
                            handle_payload(payload)
                    if done:
                        # 落库先于 yield [DONE]：即使客户端读到 [DONE] 立即
                        # 断开，本轮消息也已持久化。
                        if not failed:
                            await _persist_turn(
                                chat,
                                user_content=user_text,
                                assistant_content=''.join(assistant_parts),
                                sources=sources,
                            )
                        yield frame_bytes + b'\n\n'
                        return
                    yield frame_bytes + b'\n\n'
        except Exception:
            # 上游 HTTP 错误（stream_post raise_for_status）或连接中断
            log.exception('upstream chat completion failed (chat_id=%s)', chat_id)
            failed = True

        if failed:
            await rollback_new_chat()
            if not terminal:
                # 上游未给出 [DONE]（HTTP 错误/中断）：补安全错误事件收尾
                yield _sse({'error': {'message': SAFE_ERROR_MESSAGE, 'code': SAFE_ERROR_CODE}})
                yield b'data: [DONE]\n\n'
            return

        # 上游提前静默收尾（无 [DONE]）：视同失败
        await rollback_new_chat()
        yield _sse({'error': {'message': SAFE_ERROR_MESSAGE, 'code': SAFE_ERROR_CODE}})
        yield b'data: [DONE]\n\n'

    return StreamingResponse(event_stream(), media_type='text/event-stream')
