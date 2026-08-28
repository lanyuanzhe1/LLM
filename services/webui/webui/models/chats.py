"""Chat models, forms, and database operations.

Trimmed from open_webui.models.chats (see task-7 report):
- Kept verbatim: Chat table, ChatModel, ChatForm, ChatTitleIdResponse,
  ``upsert_message_to_history`` (message-graph core), ``merge_history``,
  ``get_current_message_id``, ``_repair_chat_current_id``,
  ``_sanitize_chat_row``, ``_clean_null_bytes``, ``_last_descendant_id``.
- ``insert_new_chat``: chat_message dual-write try block removed (slice 1
  does not dual-write).
- ``delete_chat_by_id_and_user_id``: AutomationRun update removed
  (automations not extracted); shared-chat cleanup removed (shared_chats
  not extracted) — returns True right after commit.
- Dropped: everything referencing access_grants/automations/folders/tags/
  shared_chats/files/groups/utils.access_control, all search/pin/archive/
  folder/tag/stats/import methods, ChatFile/ChatFileModel, and the
  module-level search/order helpers only used by dropped methods.
"""

from __future__ import annotations

import logging
import time

# local imports
from webui.internal.db import Base, get_async_db_context
from webui.models.chat_messages import ChatMessage
from webui.utils.misc import sanitize_data_for_db
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Index,
    String,
    Text,
    delete,
    select,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

log = logging.getLogger(__name__)


class Chat(Base):  # database table mapping for chat entity
    __tablename__ = 'chat'

    id = Column(String, primary_key=True, unique=True)
    user_id = Column(String, index=True)  # owner user id
    title = Column(Text)  # user-visible conversation title
    chat = Column(JSON)

    created_at = Column(BigInteger, index=True)  # conversation creation timestamp
    updated_at = Column(BigInteger, index=True)  # conversation modification timestamp

    share_id = Column(Text, unique=True, nullable=True)  # public share link token
    archived = Column(Boolean, default=False)  # hidden from main chat list
    pinned = Column(Boolean, default=False, nullable=True)

    meta = Column(JSON, server_default='{}')
    variables = Column(JSON, nullable=True)
    folder_id = Column(Text, nullable=True)

    tasks = Column(JSON, nullable=True)
    summary = Column(Text, nullable=True)
    current_message_id = Column(Text, nullable=True)

    last_read_at = Column(BigInteger, nullable=True)
    timer_at = Column(BigInteger, nullable=True)  # ns due time, set only while a timer chat waits to be claimed

    __table_args__ = (
        # Performance indexes for common queries
        Index('folder_id_idx', 'folder_id'),
        Index('user_id_pinned_idx', 'user_id', 'pinned'),
        Index('user_id_archived_idx', 'user_id', 'archived'),
        Index('updated_at_user_id_idx', 'updated_at', 'user_id'),
        Index('folder_id_user_id_idx', 'folder_id', 'user_id'),
        Index('user_id_updated_at_id_idx', 'user_id', updated_at.desc(), 'id'),
        Index(
            'timer_at_idx',
            'timer_at',
            sqlite_where=text('timer_at IS NOT NULL'),
            postgresql_where=text('timer_at IS NOT NULL'),
        ),
        # timer_at key column turns the IS NOT NULL into a seek, so this beats the plain user_id indexes
        Index(
            'user_id_timer_at_idx',
            'user_id',
            'timer_at',
            sqlite_where=text('timer_at IS NOT NULL'),
            postgresql_where=text('timer_at IS NOT NULL'),
        ),
        # covering index: lets SQLite serve count_unread_by_folder_ids without reading chat rows
        Index('user_id_folder_unread_idx', 'user_id', 'folder_id', 'archived', 'updated_at', 'last_read_at', 'id'),
    )


class ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # allows ORM model binding
    id: str
    user_id: str
    title: str
    chat: dict

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    share_id: str | None = None
    archived: bool = False
    pinned: bool | None = False

    meta: dict = {}
    variables: dict = {}
    folder_id: str | None = None

    tasks: list | None = None
    summary: str | None = None
    current_message_id: str | None = None

    last_read_at: int | None = None
    timer_at: int | None = None

    @field_validator('variables', mode='before')
    @classmethod
    def normalize_variables(cls, value):
        return value if isinstance(value, dict) else {}


####################
# Forms
####################


class ChatForm(BaseModel):
    chat: dict
    variables: dict | None = None
    folder_id: str | None = None


class ChatTitleIdResponse(BaseModel):
    id: str
    title: str
    updated_at: int
    created_at: int
    last_read_at: int | None = None
    snippet: str | None = None
    active: bool = False


class ChatTable:
    def _clean_null_bytes(self, obj):
        """Recursively remove null bytes from strings in dict/list structures."""
        return sanitize_data_for_db(obj)

    def get_current_message_id(self, chat: dict | None) -> str | None:
        chat = chat or {}
        history = chat.get('history') if isinstance(chat.get('history'), dict) else {}
        current_id = history.get('currentId') or chat.get('currentId') or chat.get('branchPointMessageId')
        if current_id:
            return current_id

        messages = chat.get('messages')
        if isinstance(messages, list):
            for message in reversed(messages):
                if isinstance(message, dict) and message.get('id'):
                    return message['id']

        return None

    def _sanitize_chat_row(self, chat_item):
        """
        Clean a Chat SQLAlchemy model's title + chat JSON,
        and return True if anything changed.

        The message write paths (upsert/status/delete) rely on this
        leaving the blob clean and sanitize only the data they add.
        """
        changed = False

        # Clean title
        if chat_item.title:
            cleaned = self._clean_null_bytes(chat_item.title)
            if cleaned != chat_item.title:
                chat_item.title = cleaned
                changed = True

        # Clean JSON
        if chat_item.chat:
            cleaned = self._clean_null_bytes(chat_item.chat)
            if cleaned != chat_item.chat:
                chat_item.chat = cleaned
                changed = True

        return changed

    @staticmethod
    def _last_descendant_id(messages: dict, message_id: str) -> str:
        seen_ids = set()
        while message_id in messages and message_id not in seen_ids:
            seen_ids.add(message_id)
            message = messages[message_id]
            child_ids = message.get('childrenIds') if isinstance(message, dict) else []
            child_ids = child_ids if isinstance(child_ids, list) else []
            next_id = next((child_id for child_id in reversed(child_ids) if child_id in messages), None)
            if not next_id:
                break
            message_id = next_id
        return message_id

    def _repair_chat_current_id(self, chat: dict) -> bool:
        history = chat.get('history')
        if not isinstance(history, dict):
            return False

        messages = history.get('messages')
        if not isinstance(messages, dict):
            return False

        current_id = history.get('currentId')
        current_message = messages.get(current_id)
        output = []
        if isinstance(current_message, dict):
            output = current_message.get('output') or []

        output_role = next(
            (item.get('role') for item in output if isinstance(item, dict) and item.get('role')),
            None,
        )
        current_is_bad_leaf = (
            isinstance(current_message, dict)
            and output_role == 'assistant'
            and current_message.get('parentId') is None
            and not current_message.get('timestamp')
            and len(messages) > 1
        )
        if (
            isinstance(current_message, dict)
            and current_message.get('id')
            and current_message.get('role')
            and not current_is_bad_leaf
        ):
            if current_message.get('contextSummary') or current_message.get('context_summary'):
                last_descendant_id = self._last_descendant_id(messages, current_id)
                if last_descendant_id != current_id:
                    history['currentId'] = last_descendant_id
                    return True

            return False

        latest_leaf_id = None
        latest_timestamp = -1
        for message_id, message in messages.items():
            if not isinstance(message, dict) or not message.get('role'):
                continue

            children_ids = message.get('childrenIds') if isinstance(message.get('childrenIds'), list) else []
            timestamp = message.get('timestamp') or 0
            if len(children_ids) == 0 and timestamp > latest_timestamp:
                latest_leaf_id = message_id
                latest_timestamp = timestamp

        if not latest_leaf_id or latest_leaf_id == current_id:
            return False

        history['currentId'] = latest_leaf_id
        return True

    async def insert_new_chat(
        self,
        id: str,
        user_id: str,
        form_data: ChatForm,
        db: AsyncSession | None = None,
        *,
        internal_meta: dict | None = None,
        timer_at: int | None = None,
    ) -> ChatModel | None:
        async with get_async_db_context(db) as session:
            chat = ChatModel(
                **{
                    'id': id,
                    'user_id': user_id,
                    'title': self._clean_null_bytes(
                        form_data.chat['title'] if 'title' in form_data.chat else 'New Chat'
                    ),
                    'chat': self._clean_null_bytes(form_data.chat),
                    'folder_id': form_data.folder_id,
                    'meta': internal_meta or {},
                    'timer_at': timer_at,
                    'variables': form_data.variables or {},
                    'current_message_id': self.get_current_message_id(form_data.chat),
                    'created_at': int(time.time()),
                    'updated_at': int(time.time()),
                    'last_read_at': int(time.time()),
                }
            )

            chat_item = Chat(**chat.model_dump())
            session.add(chat_item)
            await session.commit()

            return ChatModel.model_validate(chat_item) if chat_item else None

    async def update_chat_by_id(
        self,
        id: str,
        chat: dict,
        db: AsyncSession | None = None,
        *,
        touch: bool = True,
    ) -> ChatModel | None:
        """Patch top-level chat keys; history is merged so stale writers don't drop messages."""
        try:
            async with get_async_db_context(db) as session:
                chat_item = await session.get(
                    Chat,
                    id,
                    populate_existing=True,
                    with_for_update=session.bind.dialect.name == 'postgresql',
                )
                if chat_item is None:
                    return None

                stored = chat_item.chat or {}
                updated = {**stored, **chat}
                if 'history' in chat:
                    # The caller built its history from an earlier read; merge so messages saved since then survive.
                    updated['history'] = self.merge_history(stored.get('history'), chat['history'])

                updated = self._clean_null_bytes(updated)
                chat_item.chat = updated
                chat_item.title = updated.get('title', 'New Chat')
                if any(key in chat for key in ('history', 'messages', 'currentId', 'branchPointMessageId')):
                    chat_item.current_message_id = self.get_current_message_id(updated)

                if touch:
                    chat_item.updated_at = int(time.time())

                await session.commit()

                return ChatModel.model_validate(chat_item)
        except Exception:
            return

    @staticmethod
    def merge_history(existing_history: dict | None, incoming_history: dict | None) -> dict:
        existing = (existing_history or {}).get('messages') or {}
        incoming = (incoming_history or {}).get('messages') or {}
        merged = {
            message_id: {**message, 'childrenIds': []}
            for message_id, message in {**existing, **incoming}.items()
            if isinstance(message, dict)
        }

        for message_id, message in merged.items():
            parent_id = message.get('parentId')
            if parent_id in merged:
                merged[parent_id]['childrenIds'].append(message_id)

        current_id = (incoming_history or {}).get('currentId')
        if current_id not in merged:
            current_id = (existing_history or {}).get('currentId')
            if current_id not in merged:
                current_id = None

        return {**(existing_history or {}), **(incoming_history or {}), 'messages': merged, 'currentId': current_id}

    @staticmethod
    def upsert_message_to_history(history: dict, message_id: str, message: dict) -> dict:
        messages = history.setdefault('messages', {})

        if message_id in messages:
            messages[message_id] = {
                **messages[message_id],
                **message,
            }
        else:
            message_parent_id = message.get('parentId')
            parent_id = message_parent_id
            if parent_id is None:
                for existing_id, existing_message in messages.items():
                    if message_id in existing_message.get('childrenIds', []):
                        parent_id = existing_id
                        break

            parent = messages.get(parent_id) if parent_id else None
            output = message.get('output') or []
            output_role = next(
                (item.get('role') for item in output if isinstance(item, dict) and item.get('role')),
                None,
            )
            role = message.get('role') or output_role
            if not role:
                parent_role = parent.get('role') if parent else None
                if parent_role == 'user':
                    role = 'assistant'
                elif parent_role == 'assistant':
                    role = 'user'
                else:
                    role = 'assistant'

            messages[message_id] = {
                **message,
                'id': message.get('id') or message_id,
                'parentId': message_parent_id if message_parent_id is not None else parent_id,
                'childrenIds': (message.get('childrenIds') if isinstance(message.get('childrenIds'), list) else []),
                'role': role,
                'timestamp': message.get('timestamp') or int(time.time()),
            }
            history['currentId'] = message_id
        return messages[message_id]

    async def get_chat_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        filter: dict | None = None,
        skip: int = 0,
        limit: int = 50,
        db: AsyncSession | None = None,
    ) -> list[ChatTitleIdResponse]:
        async with get_async_db_context(db) as session:
            stmt = select(Chat.id, Chat.title, Chat.updated_at, Chat.created_at, Chat.last_read_at).filter_by(
                user_id=user_id
            )
            stmt = stmt.where(Chat.meta['internal'].as_boolean().is_not(True))
            if not include_archived:
                stmt = stmt.filter_by(archived=False)

            if filter:
                query_key = filter.get('query')
                if query_key:
                    stmt = stmt.filter(Chat.title.ilike(f'%{query_key}%'))

                order_by = filter.get('order_by')
                direction = filter.get('direction')

                if order_by and direction and getattr(Chat, order_by):
                    if direction.lower() == 'asc':
                        stmt = stmt.order_by(getattr(Chat, order_by).asc(), Chat.id)
                    elif direction.lower() == 'desc':
                        stmt = stmt.order_by(getattr(Chat, order_by).desc(), Chat.id)
                    else:
                        raise ValueError('Invalid direction for ordering')
            else:
                stmt = stmt.order_by(Chat.updated_at.desc(), Chat.id)

            if skip:
                stmt = stmt.offset(skip)
            if limit:
                stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            all_chats = result.all()
            return [
                ChatTitleIdResponse.model_validate(
                    {
                        'id': chat[0],
                        'title': chat[1],
                        'updated_at': chat[2],
                        'created_at': chat[3],
                        'last_read_at': chat[4],
                    }
                )
                for chat in all_chats
            ]

    async def get_chat_by_id_and_user_id(
        self, id: str, user_id: str, db: AsyncSession | None = None
    ) -> ChatModel | None:
        try:
            async with get_async_db_context(db) as session:
                result = await session.execute(select(Chat).filter_by(id=id, user_id=user_id))
                chat = result.scalars().first()
                if not chat:
                    return None

                repaired_history = self._repair_chat_current_id(chat.chat or {})
                if repaired_history:
                    chat.current_message_id = self.get_current_message_id(chat.chat)
                    flag_modified(chat, 'chat')
                if self._sanitize_chat_row(chat) or repaired_history:
                    await session.commit()

                return ChatModel.model_validate(chat)
        except Exception:
            return None

    async def delete_chat_by_id_and_user_id(self, id: str, user_id: str, db: AsyncSession | None = None) -> bool:
        """Delete a chat and its chat_message rows.

        Trimmed: the reference also nulls ``AutomationRun.chat_id`` and
        deletes the shared-chat snapshot; both tables are not extracted, so
        those steps are removed.
        """
        try:
            async with get_async_db_context(db) as session:
                await session.execute(delete(ChatMessage).filter_by(chat_id=id))
                await session.execute(delete(Chat).filter_by(id=id, user_id=user_id))
                await session.commit()

                return True
        except Exception:
            return False


Chats = ChatTable()  # singleton chats repository
