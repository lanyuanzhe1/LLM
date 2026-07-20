import asyncio
import base64
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.clients.iflytek_maas import IflytekMaaSClient
from app.core.errors import ProviderUnavailable
from tests.unit.iflytek_maas_fakes import (
    FakeConnectContext,
    FakeConnection,
    terminal_frame,
)


class FakeTransport:
    async def exchange(self, url: str, payload: dict, timeout: float):
        assert payload["header"]["patch_id"] == ["resource-id"]
        assert payload["parameter"]["chat"]["domain"] == "service-id"
        assert timeout == 5
        yield {
            "header": {"code": 0, "message": "Success", "status": 0},
            "payload": {
                "choices": {
                    "status": 0,
                    "text": [
                        {"content": "结论", "role": "assistant", "index": 0}
                    ],
                }
            },
        }
        yield {
            "header": {"code": 0, "message": "Success", "status": 2},
            "payload": {
                "choices": {
                    "status": 2,
                    "text": [
                        {"content": "[E1]", "role": "assistant", "index": 0}
                    ],
                },
                "usage": {"text": {"total_tokens": 12}},
            },
        }


class TimeoutTransport:
    async def exchange(self, url: str, payload: dict, timeout: float):
        raise TimeoutError("secret provider timeout detail")
        yield


class InterruptedTransport:
    async def exchange(self, url: str, payload: dict, timeout: float):
        raise ConnectionError("provider-private-stream-detail")
        yield


class FramesTransport:
    def __init__(self, frames: list[object]) -> None:
        self.frames = frames

    async def exchange(self, url: str, payload: dict, timeout: float):
        for frame in self.frames:
            yield frame


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_auth_url_contains_base64_authorization():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat",
        timeout_seconds=5,
        transport=FakeTransport(),
    )

    url = client.create_auth_url(datetime(2026, 7, 19, tzinfo=timezone.utc))
    auth = parse_qs(urlparse(url).query)["authorization"][0]
    decoded = base64.b64decode(auth).decode()
    assert 'api_key="key"' in decoded
    assert 'algorithm="hmac-sha256"' in decoded


@pytest.mark.asyncio
async def test_generate_joins_stream_and_usage():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=FakeTransport(),
    )

    result = await client.generate(
        [{"role": "user", "content": "问题"}], uid="req-1"
    )

    assert result.content == "结论[E1]"
    assert result.total_tokens == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["", " ", "\n\t"])
async def test_terminal_success_with_empty_answer_is_safe_model_error(content):
    frame = terminal_frame()
    frame["payload"]["choices"]["text"] = [{"content": content}]
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=FramesTransport([frame]),
    )

    with pytest.raises(ProviderUnavailable) as caught:
        await client.generate(
            [{"role": "user", "content": "问题"}],
            uid="req",
        )

    assert caught.value.code == "MODEL_UNAVAILABLE"
    assert caught.value.message == "模型服务未返回可用内容"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
async def test_generate_total_deadline_stops_continuous_small_frames():
    clock = ManualClock()
    finalized = False

    class EndlessAdvancingTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            nonlocal finalized
            try:
                while True:
                    clock.advance(0.4)
                    yield {
                        "header": {
                            "code": 0,
                            "message": "Success",
                            "status": 0,
                        },
                        "payload": {
                            "choices": {
                                "status": 0,
                                "text": [{"content": "x"}],
                            }
                        },
                    }
            finally:
                finalized = True

    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=1,
        transport=EndlessAdvancingTransport(),
        clock=clock,
    )

    with pytest.raises(ProviderUnavailable) as caught:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert caught.value.code == "MODEL_UNAVAILABLE"
    assert caught.value.message == "模型服务请求超时"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert finalized is True


@pytest.mark.asyncio
async def test_generate_total_deadline_bounds_websocket_send(monkeypatch):
    send_started = asyncio.Event()
    send_cancelled = asyncio.Event()

    class BlockingSendConnection(FakeConnection):
        async def send(self, payload: str) -> None:
            send_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                send_cancelled.set()

    connection = BlockingSendConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: FakeConnectContext(connection),
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=0.01,
    )

    with pytest.raises(ProviderUnavailable) as caught:
        await asyncio.wait_for(
            client.generate(
                [{"role": "user", "content": "问题"}],
                uid="req",
            ),
            timeout=1,
        )

    assert send_started.is_set()
    assert send_cancelled.is_set()
    assert connection.closed is True
    assert caught.value.code == "MODEL_UNAVAILABLE"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limits", "frames"),
    [
        (
            {"max_frames": 1},
            [
                {
                    "header": {"code": 0, "message": "ok", "status": 0},
                    "payload": {
                        "choices": {"status": 0, "text": [{"content": "a"}]}
                    },
                },
                terminal_frame(),
            ],
        ),
        (
            {"max_payload_bytes": 1},
            [terminal_frame()],
        ),
        (
            {"max_answer_chars": 3},
            [
                {
                    "header": {"code": 0, "message": "ok", "status": 2},
                    "payload": {
                        "choices": {
                            "status": 2,
                            "text": [{"content": "1234"}],
                        }
                    },
                }
            ],
        ),
    ],
)
async def test_generate_enforces_frame_byte_and_answer_budgets(
    limits,
    frames,
):
    finalized = False

    class FinalizingFramesTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            nonlocal finalized
            try:
                for item in frames:
                    yield item
            finally:
                finalized = True

    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=FinalizingFramesTransport(),
        **limits,
    )

    with pytest.raises(ProviderUnavailable) as caught:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert caught.value.code == "MAAS_UNAVAILABLE"
    assert caught.value.message == "模型服务响应超出安全限制"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert finalized is True


@pytest.mark.asyncio
async def test_generate_maps_transport_timeout():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=TimeoutTransport(),
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert "secret provider timeout detail" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
async def test_generate_maps_stream_interruption_to_model_unavailable():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=InterruptedTransport(),
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert "provider-private-stream-detail" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
async def test_generate_maps_nonzero_provider_code():
    transport = FramesTransport(
        [
            {
                "header": {
                    "code": 10013,
                    "message": "provider rejected secret-token",
                    "status": 2,
                },
                "payload": {
                    "choices": {"status": 2, "text": []},
                },
            }
        ]
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MAAS_UNAVAILABLE"
    assert "secret-token" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
async def test_generate_rejects_malformed_terminal_frame():
    transport = FramesTransport(
        [
            {
                "header": {"code": 0, "message": "Success", "status": 2},
                "payload": {},
            }
        ]
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MAAS_UNAVAILABLE"


@pytest.mark.asyncio
async def test_generate_rejects_incomplete_nonterminal_stream():
    transport = FramesTransport(
        [
            {
                "header": {"code": 0, "message": "Success", "status": 0},
                "payload": {
                    "choices": {
                        "status": 0,
                        "text": [
                            {
                                "content": "partial",
                                "role": "assistant",
                                "index": 0,
                            }
                        ],
                    }
                },
            }
        ]
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MODEL_UNAVAILABLE"


@pytest.mark.asyncio
async def test_generate_rejects_inconsistent_terminal_statuses():
    transport = FramesTransport(
        [
            {
                "header": {"code": 0, "message": "Success", "status": 2},
                "payload": {
                    "choices": {
                        "status": 0,
                        "text": [],
                    }
                },
            }
        ]
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=transport,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MAAS_UNAVAILABLE"
