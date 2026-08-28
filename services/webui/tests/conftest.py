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
import httpx
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


# ── 上游替身（Task 10/12）：monkeypatch upstream.build_client 为 MockTransport ──
# 录制流与 Task 3 单测同构：meta(role chunk) → 2 个 delta → 1 条 source
# → finish chunk → [DONE]。仅作单测替身，不进生产路径。
_RECORDED_SSE = (
    'data: {"id":"chatcmpl-stub","object":"chat.completion.chunk","created":1,'
    '"model":"grain-storage-agent","choices":[{"index":0,'
    '"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-stub","object":"chat.completion.chunk","created":1,'
    '"model":"grain-storage-agent","choices":[{"index":0,'
    '"delta":{"content":"低温"},"finish_reason":null}]}\n\n'
    'data: {"id":"chatcmpl-stub","object":"chat.completion.chunk","created":1,'
    '"model":"grain-storage-agent","choices":[{"index":0,'
    '"delta":{"content":"储粮"},"finish_reason":null}]}\n\n'
    'data: {"event":{"type":"source","data":{"source":{"id":"doc-e1",'
    '"name":"粮油储藏技术"},"document":["低温可抑制害虫繁殖"],'
    '"metadata":[{"name":"粮油储藏技术","evidence_id":"e1"}],'
    '"distances":[0.9]}}}\n\n'
    'data: {"id":"chatcmpl-stub","object":"chat.completion.chunk","created":1,'
    '"model":"grain-storage-agent","choices":[{"index":0,"delta":{},'
    '"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n"
)


def _recorded_transport_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/chat/completions":
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_RECORDED_SSE.encode("utf-8"),
        )
    if request.url.path == "/v1/models":
        return httpx.Response(
            200,
            json={
                "object": "list",
                "data": [{"id": "grain-storage-agent", "object": "model"}],
            },
        )
    return httpx.Response(404, json={"detail": "not stubbed"})


def _failing_transport_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/chat/completions":
        return httpx.Response(502, json={"detail": "bad gateway"})
    return _recorded_transport_handler(request)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://testserver"
    )


@pytest.fixture(autouse=True)
def stub_upstream(monkeypatch):
    """默认成功路径：所有测试的上游均为录制 SSE；个别测试可自行覆盖。"""
    from webui.utils import upstream

    monkeypatch.setattr(
        upstream, "build_client", lambda: _mock_client(_recorded_transport_handler)
    )


@pytest.fixture()
def failing_upstream(monkeypatch):
    """失败路径：POST /v1/chat/completions 返回 502（在 autouse stub 之后生效）。"""
    from webui.utils import upstream

    monkeypatch.setattr(
        upstream, "build_client", lambda: _mock_client(_failing_transport_handler)
    )
