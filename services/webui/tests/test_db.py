"""回归：SQLite 并发写配置（WAL + busy_timeout）——真实链路落库静默失败的根因。"""

import asyncio
import uuid

from sqlalchemy import text

from webui.internal.db import async_engine
from webui.models.chats import ChatForm, Chats


async def test_sqlite_pragmas_configured_for_concurrent_writes():
    async with async_engine.connect() as conn:
        mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
        timeout = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
    assert mode == "wal"
    assert timeout == 5000


async def test_concurrent_chat_inserts_do_not_lock():
    async def insert_one(i: int) -> str:
        cid = f"concurrent-{i}-{uuid.uuid4().hex[:6]}"
        chat = await Chats.insert_new_chat(
            cid,
            "u1",
            ChatForm(
                chat={
                    "title": f"会话{i}",
                    "models": ["grain-storage-agent"],
                    "history": {"messages": {}, "currentId": None},
                    "messages": [],
                }
            ),
        )
        assert chat is not None
        return cid

    cids = await asyncio.gather(*(insert_one(i) for i in range(5)))
    try:
        for cid in cids:
            loaded = await Chats.get_chat_by_id_and_user_id(cid, "u1")
            assert loaded is not None
    finally:
        for cid in cids:
            await Chats.delete_chat_by_id_and_user_id(cid, "u1")
