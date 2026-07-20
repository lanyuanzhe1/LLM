import asyncio

import pytest

from app.clients.iflytek_maas import WebSocketTransport
from tests.unit.iflytek_maas_fakes import (
    FakeConnectContext,
    FakeConnection,
)


@pytest.mark.asyncio
async def test_websocket_transport_uses_explicit_timeouts_and_default_tls(
    monkeypatch,
):
    connection = FakeConnection()
    called: dict = {}

    def fake_connect(url: str, **kwargs):
        called["url"] = url
        called["kwargs"] = kwargs
        return FakeConnectContext(connection)

    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        fake_connect,
    )

    frames = [
        frame
        async for frame in WebSocketTransport().exchange(
            "wss://example.test/v1.1/chat",
            {"payload": {}},
            timeout=5,
        )
    ]

    assert frames[0]["header"]["status"] == 2
    assert called == {
        "url": "wss://example.test/v1.1/chat",
        "kwargs": {"open_timeout": 5, "close_timeout": 5},
    }
    assert connection.closed is True

@pytest.mark.asyncio
async def test_websocket_transport_concurrent_close_callers_wait_together(
    monkeypatch,
):
    receive_started = asyncio.Event()
    close_started = asyncio.Event()
    allow_close = asyncio.Event()

    class BlockingConnection(FakeConnection):
        async def recv(self) -> str:
            receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def close(self) -> None:
            close_started.set()
            await allow_close.wait()
            self.closed = True

    connection = BlockingConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: FakeConnectContext(connection),
    )
    transport = WebSocketTransport()
    stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    exchange_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(receive_started.wait(), timeout=1)

    first = asyncio.create_task(transport.close())
    await asyncio.wait_for(close_started.wait(), timeout=1)
    second = asyncio.create_task(transport.close())
    await asyncio.sleep(0)
    second_completed_early = second.done()
    allow_close.set()
    await asyncio.gather(first, second)
    exchange_finished_with_close = exchange_task.done()
    if not exchange_task.done():
        exchange_task.cancel()
    await asyncio.gather(exchange_task, return_exceptions=True)

    assert second_completed_early is False
    assert exchange_finished_with_close is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_websocket_transport_cancellation_while_connecting_propagates(
    monkeypatch,
):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingConnect:
        async def __aenter__(self):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        async def __aexit__(self, *exc_info):
            raise AssertionError("connection was never opened")

    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: BlockingConnect(),
    )
    stream = WebSocketTransport().exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), timeout=1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_websocket_transport_close_cancels_connect_in_progress(
    monkeypatch,
):
    connect_started = asyncio.Event()
    connect_cancelled = asyncio.Event()

    class BlockingConnect:
        async def __aenter__(self):
            connect_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                connect_cancelled.set()

        async def __aexit__(self, *exc_info):
            raise AssertionError("connection was never opened")

    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: BlockingConnect(),
    )
    transport = WebSocketTransport()
    stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    exchange_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(connect_started.wait(), timeout=1)

    await transport.close()
    exchange_finished_with_close = exchange_task.done()
    if not exchange_task.done():
        exchange_task.cancel()
    await asyncio.gather(exchange_task, return_exceptions=True)

    assert exchange_finished_with_close is True
    assert connect_cancelled.is_set()


@pytest.mark.asyncio
async def test_websocket_transport_close_retries_failed_connection_cleanup(
    monkeypatch,
):
    receive_started = asyncio.Event()

    class FailOnceCloseConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        async def recv(self) -> str:
            receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("first socket close failed")
            self.closed = True

    connection = FailOnceCloseConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: FakeConnectContext(connection),
    )
    transport = WebSocketTransport()
    stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    exchange_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(receive_started.wait(), timeout=1)

    with pytest.raises(RuntimeError, match="first socket close failed"):
        await transport.close()
    await transport.close()
    await asyncio.gather(exchange_task, return_exceptions=True)

    assert connection.close_calls == 2
    assert connection.closed is True


@pytest.mark.asyncio
async def test_external_cancel_wins_when_transport_close_joins_cleanup(
    monkeypatch,
):
    receive_started = asyncio.Event()
    cleanup_entered = asyncio.Event()
    transport_cancel_seen = asyncio.Event()
    allow_cleanup_error = asyncio.Event()
    cleanup_counts: list[int] = []

    class BlockingConnection(FakeConnection):
        async def recv(self) -> str:
            receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def close(self) -> None:
            self.closed = True

    class BarrierCleanupContext(FakeConnectContext):
        async def __aexit__(self, *exc_info) -> None:
            task = asyncio.current_task()
            assert task is not None
            cleanup_counts.append(task.cancelling())
            cleanup_entered.set()
            try:
                await allow_cleanup_error.wait()
            except asyncio.CancelledError:
                transport_cancel_seen.set()
                await allow_cleanup_error.wait()
            raise TimeoutError("provider-private-cleanup-detail")

    connection = BlockingConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: BarrierCleanupContext(connection),
    )
    transport = WebSocketTransport()
    stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    exchange_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(receive_started.wait(), timeout=1)

    exchange_task.cancel()
    await asyncio.wait_for(cleanup_entered.wait(), timeout=1)
    close_task = asyncio.create_task(transport.close())
    await asyncio.wait_for(transport_cancel_seen.wait(), timeout=1)
    allow_cleanup_error.set()
    exchange_result, close_result = await asyncio.wait_for(
        asyncio.gather(
            exchange_task,
            close_task,
            return_exceptions=True,
        ),
        timeout=1,
    )

    assert cleanup_counts == [1]
    assert isinstance(exchange_result, asyncio.CancelledError)
    assert exchange_result.__cause__ is None
    assert exchange_result.__context__ is None
    assert "provider-private" not in str(exchange_result)
    assert close_result is None
    assert connection.closed is True
    assert transport._exchange_tasks == set()
    assert transport._transport_cancel_counts == {}
    assert transport._connections == set()


@pytest.mark.asyncio
async def test_transport_internal_cancel_keeps_cleanup_failure_retry_semantics(
    monkeypatch,
):
    receive_started = asyncio.Event()

    class FailOnceCloseConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0

        async def recv(self) -> str:
            receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise TimeoutError("controlled internal close failure")
            self.closed = True

    connection = FailOnceCloseConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: FakeConnectContext(connection),
    )
    transport = WebSocketTransport()
    stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    exchange_task = asyncio.create_task(anext(stream))
    await asyncio.wait_for(receive_started.wait(), timeout=1)

    with pytest.raises(
        TimeoutError,
        match="controlled internal close failure",
    ):
        await transport.close()
    exchange_result = await asyncio.gather(
        exchange_task,
        return_exceptions=True,
    )
    await transport.close()

    assert isinstance(exchange_result[0], TimeoutError)
    assert connection.close_calls == 2
    assert connection.closed is True
    assert transport._exchange_tasks == set()
    assert transport._transport_cancel_counts == {}
    assert transport._connections == set()


@pytest.mark.asyncio
async def test_websocket_transport_self_close_preserves_owner_and_cleans_others(
    monkeypatch,
):
    owner_ready = asyncio.Event()
    other_receive_started = asyncio.Event()

    class OwnerConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__(
                [
                    (
                        '{"header":{"code":0,"status":0},'
                        '"payload":{"choices":{"status":0,"text":[]}}}'
                    )
                ]
            )

    class OtherConnection(FakeConnection):
        async def recv(self) -> str:
            other_receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    owner_connection = OwnerConnection()
    other_connection = OtherConnection()
    contexts = iter(
        [
            FakeConnectContext(owner_connection),
            FakeConnectContext(other_connection),
        ]
    )
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: next(contexts),
    )
    transport = WebSocketTransport()

    async def close_from_active_owner() -> str:
        stream = transport.exchange(
            "wss://example.test/v1.1/chat",
            {"payload": {}},
            timeout=5,
        )
        try:
            await anext(stream)
            owner_ready.set()
            await other_receive_started.wait()
            await transport.close()
            return "closed"
        finally:
            await stream.aclose()

    owner_task = asyncio.create_task(close_from_active_owner())
    await asyncio.wait_for(owner_ready.wait(), timeout=1)
    other_stream = transport.exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=5,
    )
    other_task = asyncio.create_task(anext(other_stream))
    await asyncio.wait_for(other_receive_started.wait(), timeout=1)
    owner_result, other_result = await asyncio.wait_for(
        asyncio.gather(
            owner_task,
            other_task,
            return_exceptions=True,
        ),
        timeout=1,
    )
    await transport.close()

    assert owner_result == "closed"
    assert isinstance(other_result, asyncio.CancelledError)
    assert owner_connection.closed is True
    assert other_connection.closed is True


@pytest.mark.asyncio
async def test_websocket_transport_receive_timeout_closes_connection(
    monkeypatch,
):
    class BlockingConnection(FakeConnection):
        async def recv(self) -> str:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    connection = BlockingConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: FakeConnectContext(connection),
    )
    stream = WebSocketTransport().exchange(
        "wss://example.test/v1.1/chat",
        {"payload": {}},
        timeout=0.01,
    )

    with pytest.raises(TimeoutError):
        await anext(stream)

    assert connection.closed is True
