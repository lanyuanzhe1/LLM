"""Chats router extracted (trimmed) from open_webui.routers.chats.

Kept endpoints: ``GET /`` (current user's chat list), ``GET /{id}`` (owner
detail), ``DELETE /{id}`` (owner delete). Response models follow the
reference ``ChatTitleIdResponse`` / ``ChatResponse`` shapes.

Explicit deviation (spec §6.2-11, task brief): a missing or non-owned chat
answers **404** "会话不存在" instead of the reference's 401 — non-owner
chats are simply invisible.

Dropped vs. reference: share/fork/clone/folder/tags/pin/archive/stats/
import/export/all/search endpoints; ``get_chat_by_id_for_user``'s
access_grants/folders branches (owner check only); the redis-backed
``add_active_state_to_chat_list`` overlay and ``stop_item_tasks``
cancellation (no Redis); orphan-tag cleanup and internal child-chat
cascade (tags/automations not extracted); ``publish_event`` calls
(the webui.events stub has no chat events); chat_message reconciliation
lives in the completions router's persistence path instead.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from webui.internal.db import get_async_session
from webui.models.chats import Chats, ChatTitleIdResponse
from webui.utils.auth import get_verified_user

log = logging.getLogger(__name__)

router = APIRouter()


class ChatResponse(BaseModel):
    """Reference open_webui.models.chats.ChatResponse shape (verbatim fields)."""

    id: str
    user_id: str
    title: str
    chat: dict
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch
    share_id: str | None = None  # id of the chat to be shared
    archived: bool
    pinned: bool | None = False
    meta: dict = {}
    variables: dict = {}
    folder_id: str | None = None

    tasks: list | None = None
    summary: str | None = None
    current_message_id: str | None = None

    @field_validator('variables', mode='before')
    @classmethod
    def normalize_variables(cls, value):
        return value if isinstance(value, dict) else {}


############################
# GetChatList
############################


@router.get('/', response_model=list[ChatTitleIdResponse])
async def get_session_user_chat_list(
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    return await Chats.get_chat_list_by_user_id(user.id, db=db)


############################
# GetChatById
############################


@router.get('/{id}', response_model=ChatResponse | None)
async def get_chat_by_id(
    id: str,
    request: Request,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    chat = await Chats.get_chat_by_id(id, db=db)

    # 偏离参考：非属主/不存在一律 404（参考此处为 401）
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    return ChatResponse.model_validate(chat, from_attributes=True)


############################
# DeleteChatById
############################


@router.delete('/{id}', response_model=bool)
async def delete_chat_by_id(
    request: Request,
    id: str,
    user=Depends(get_verified_user),
    db: AsyncSession = Depends(get_async_session),
):
    chat = await Chats.get_chat_by_id(id, db=db)

    # 偏离参考：非属主/不存在一律 404（参考此处为 401）
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")

    return await Chats.delete_chat_by_id_and_user_id(id, user.id, db=db)
