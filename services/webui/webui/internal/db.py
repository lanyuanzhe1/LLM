"""Minimal async SQLAlchemy wiring (SQLite-only) for the extracted service."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import MetaData, event, types
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from webui.settings import DATABASE_URL


class JSONField(types.TypeDecorator):
    """TEXT-backed JSON storage (stdlib json codec)."""

    impl = types.UnicodeText
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Any:
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    def process_result_value(self, value: Any, dialect) -> Any:
        return json.loads(value) if value is not None else None

    def copy(self, **kwargs):
        return JSONField()


def _async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


async_engine = create_async_engine(
    _async_url(DATABASE_URL),
    connect_args=(
        {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
    ),
)
if "sqlite" in DATABASE_URL:
    # SQLite 并发写需要 WAL + busy_timeout；缺了它们，uvicorn 连接池下
    # 多连接并发写会抛 "database is locked"（见真实链路落库失败根因）。
    # 与参考 open_webui/internal/db.py 的 _apply_sqlite_pragmas 语义一致。
    @event.listens_for(async_engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base(metadata=MetaData())


async def get_async_session():
    async with AsyncSessionLocal() as db:
        yield db


@asynccontextmanager
async def get_async_db():
    async with AsyncSessionLocal() as db:
        yield db


@asynccontextmanager
async def get_async_db_context(db: AsyncSession | None = None):
    if isinstance(db, AsyncSession):
        yield db
    else:
        async with get_async_db() as session:
            yield session


async def create_all_tables() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
