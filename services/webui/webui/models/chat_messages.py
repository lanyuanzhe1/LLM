"""ChatMessage table definition and pydantic mirror.

Trimmed from open_webui.models.chat_messages (see task-7 report): only the
``ChatMessage`` table and ``ChatMessageModel`` are kept — slice 1 does not
dual-write messages, so the whole ``ChatMessageTable`` operations class and
its helpers (usage/analytics) are dropped, along with the
``webui.utils.response`` import they required.
"""

from typing import Any, Optional

from webui.internal.db import Base
from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Text,
)

####################
# ChatMessage DB Schema
####################


class ChatMessage(Base):
    __tablename__ = 'chat_message'

    # Identity
    id = Column(Text, primary_key=True)
    chat_id = Column(Text, ForeignKey('chat.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Text, index=True)

    # Structure
    role = Column(Text, nullable=False)  # user, assistant, system
    parent_id = Column(Text, nullable=True)

    # Content
    content = Column(JSON, nullable=True)  # Can be str or list of blocks
    output = Column(JSON, nullable=True)

    # Model (for assistant messages)
    model_id = Column(Text, nullable=True, index=True)

    # Attachments
    files = Column(JSON, nullable=True)
    sources = Column(JSON, nullable=True)
    embeds = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    # Status
    done = Column(Boolean, default=True)
    status_history = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)

    # Usage (tokens, timing, etc.)
    usage = Column(JSON, nullable=True)

    # Context compaction checkpoint
    context_summary = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(BigInteger, index=True)
    updated_at = Column(BigInteger)

    __table_args__ = (
        Index('chat_message_chat_parent_idx', 'chat_id', 'parent_id'),
        Index('chat_message_model_created_idx', 'model_id', 'created_at'),
        Index('chat_message_user_created_idx', 'user_id', 'created_at'),
        Index('chat_message_chat_role_done_idx', 'chat_id', 'role', 'done'),  # unfinished-assistant probe
    )


####################
# Pydantic Models
####################


class ChatMessageModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    chat_id: str
    user_id: str
    role: str
    parent_id: Optional[str] = None
    content: Optional[Any] = None  # str or list of blocks
    output: Optional[list] = None
    model_id: Optional[str] = None
    files: Optional[list] = None
    sources: Optional[list] = None
    embeds: Optional[list] = None
    meta: Optional[dict] = None
    done: bool = True
    status_history: Optional[list] = None
    error: Optional[dict | str] = None
    usage: Optional[dict] = None
    context_summary: Optional[str] = None
    created_at: int
    updated_at: int
