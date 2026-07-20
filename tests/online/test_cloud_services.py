import os

import pytest

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.clients.iflytek_maas import IflytekMaaSClient
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.config import Settings


pytestmark = pytest.mark.online


def online_settings() -> Settings:
    if os.getenv("RUN_ONLINE") != "1":
        pytest.skip("set RUN_ONLINE=1 to call real iFlytek services")
    return Settings()


@pytest.mark.asyncio
async def test_embedding_online():
    settings = online_settings()
    client = IflytekEmbeddingClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_embedding_api_key.get_secret_value(),
        api_secret=settings.xf_embedding_api_secret.get_secret_value(),
        url=settings.embedding_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    try:
        vector = await client.embed("低温储粮", domain="query")
        assert vector.shape == (2560,)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_maas_online():
    settings = online_settings()
    client = IflytekMaaSClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_maas_api_key.get_secret_value(),
        api_secret=settings.xf_maas_api_secret.get_secret_value(),
        resource_id=settings.xf_maas_resource_id,
        service_id=settings.xf_maas_service_id,
        url=settings.maas_url,
        timeout_seconds=settings.maas_timeout_seconds,
    )
    result = await client.generate(
        [{"role": "user", "content": "用一句话说明低温储粮。"}],
        uid="online-smoke",
    )
    assert result.content.strip()
    assert result.total_tokens > 0


@pytest.mark.asyncio
async def test_workflow_online():
    settings = online_settings()
    client = XingchenWorkflowClient(
        api_key=settings.xf_workflow_api_key.get_secret_value(),
        api_secret=settings.xf_workflow_api_secret.get_secret_value(),
        flow_id=settings.xf_workflow_flow_id,
        url=settings.workflow_url,
        timeout_seconds=settings.workflow_timeout_seconds,
    )
    try:
        content = []
        async for frame in client.stream(
            {
                "AGENT_USER_INPUT": "低温储粮有什么作用？",
                "REQUEST_ID": "online-workflow",
                "SESSION_ID": "online-session",
                "USER_ROLE": "student",
                "TASK_TYPE": "knowledge_qa",
                "CASE_JSON": "",
            },
            uid="online-user",
        ):
            content.extend(choice.delta.content for choice in frame.choices)
        assert "".join(content).strip()
    finally:
        await client.close()
