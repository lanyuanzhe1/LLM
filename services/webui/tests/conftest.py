import asyncio
import os
import tempfile
from pathlib import Path

# ── 必须先于一切 webui.* import ──
_TMP = Path(tempfile.mkdtemp(prefix="webui-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DATA_DIR"] = str(_TMP)
os.environ["WEBUI_SECRET_KEY"] = "test-secret"
os.environ["OPENAI_COMPAT_API_KEY"] = "test-compat-key"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    from webui.internal.db import create_all_tables

    # Import model modules so their tables register on Base.metadata first.
    import webui.models.auths  # noqa: F401
    import webui.models.chat_messages  # noqa: F401
    import webui.models.chats  # noqa: F401
    import webui.models.config  # noqa: F401
    import webui.models.users  # noqa: F401

    asyncio.run(create_all_tables())


@pytest.fixture(autouse=True)
def clean_db():
    yield
    from webui.internal.db import AsyncSessionLocal
    from webui.models.auths import Auth
    from webui.models.chat_messages import ChatMessage
    from webui.models.chats import Chat
    from webui.models.config import Config
    from webui.models.users import User

    async def _wipe() -> None:
        async with AsyncSessionLocal() as db:
            for table in (ChatMessage, Chat, Auth, User, Config):
                await db.execute(table.__table__.delete())
            await db.commit()

    asyncio.run(_wipe())


@pytest.fixture()
def client():
    from webui.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
