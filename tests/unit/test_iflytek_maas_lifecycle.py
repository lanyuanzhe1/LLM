import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.clients.iflytek_maas import IflytekMaaSClient
from app.core.errors import ProviderUnavailable
from tests.unit.iflytek_maas_fakes import (
    FakeConnectContext,
    FakeConnection,
    terminal_frame,
)


@pytest.mark.asyncio
async def test_generate_sanitizes_finalizer_error_after_terminal_success():
    class FinalizerErrorTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            try:
                yield terminal_frame()
            finally:
                raise RuntimeError("provider-private-finalizer-detail")

    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=FinalizerErrorTransport(),
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert "provider-private-finalizer-detail" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
async def test_finalizer_error_does_not_override_normalized_provider_failure():
    class ProviderAndFinalizerErrorTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            try:
                yield {
                    "header": {
                        "code": 10013,
                        "message": "provider-private-response-detail",
                        "status": 2,
                    },
                    "payload": {
                        "choices": {"status": 2, "text": []},
                    },
                }
            finally:
                raise RuntimeError("provider-private-finalizer-detail")

    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=ProviderAndFinalizerErrorTransport(),
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MAAS_UNAVAILABLE"
    assert "provider-private" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.asyncio
async def test_finalizer_error_does_not_override_generation_cancellation():
    started = asyncio.Event()
    finalized = asyncio.Event()

    class CancellationFinalizerErrorTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            try:
                started.set()
                await asyncio.Event().wait()
                yield {}
            finally:
                finalized.set()
                raise RuntimeError("provider-private-finalizer-detail")

    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=CancellationFinalizerErrorTransport(),
    )
    task = asyncio.create_task(
        client.generate([{"role": "user", "content": "问题"}], uid="req")
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert finalized.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [TimeoutError, ValueError])
async def test_websocket_cleanup_replacement_preserves_real_cancellation(
    monkeypatch,
    cleanup_error,
):
    receive_started = asyncio.Event()
    cleanup_cancelling_counts: list[int] = []

    class BlockingConnection(FakeConnection):
        async def recv(self) -> str:
            receive_started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    class CleanupErrorContext(FakeConnectContext):
        async def __aexit__(self, *exc_info) -> None:
            task = asyncio.current_task()
            assert task is not None
            cleanup_cancelling_counts.append(task.cancelling())
            raise cleanup_error("provider-private-cleanup-detail")

    connection = BlockingConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: CleanupErrorContext(connection),
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
    )
    generation = asyncio.create_task(
        client.generate([{"role": "user", "content": "问题"}], uid="req")
    )
    await asyncio.wait_for(receive_started.wait(), timeout=1)
    generation.cancel()

    try:
        with pytest.raises(asyncio.CancelledError):
            await generation
    finally:
        await client.close()

    assert cleanup_cancelling_counts == [1]
    assert connection.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [TimeoutError, ValueError])
async def test_websocket_cleanup_error_without_cancellation_is_normalized(
    monkeypatch,
    cleanup_error,
):
    cleanup_cancelling_counts: list[int] = []

    class CleanupErrorContext(FakeConnectContext):
        async def __aexit__(self, *exc_info) -> None:
            task = asyncio.current_task()
            assert task is not None
            cleanup_cancelling_counts.append(task.cancelling())
            raise cleanup_error("provider-private-cleanup-detail")

    connection = FakeConnection()
    monkeypatch.setattr(
        "app.clients.iflytek_maas.connect",
        lambda *args, **kwargs: CleanupErrorContext(connection),
    )
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
    )

    try:
        with pytest.raises(ProviderUnavailable) as exc:
            await client.generate(
                [{"role": "user", "content": "问题"}],
                uid="req",
            )
    finally:
        await client.close()

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert "provider-private" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert cleanup_cancelling_counts == [0]
    assert connection.closed is True


@pytest.mark.asyncio
async def test_generate_cancellation_propagates_and_finalizes_transport(
    monkeypatch,
):
    started = asyncio.Event()
    finalized = asyncio.Event()

    class BlockingTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            started.set()
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                finalized.set()

    async def forbidden_to_thread(*args, **kwargs):
        raise AssertionError("MaaS generation must not start a worker thread")

    monkeypatch.setattr(asyncio, "to_thread", forbidden_to_thread)
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=BlockingTransport(),
    )
    task = asyncio.create_task(
        client.generate([{"role": "user", "content": "问题"}], uid="req")
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(finalized.wait(), timeout=1)


@pytest.mark.asyncio
async def test_generate_cancellation_leaves_controlled_executor_thread_free():
    started = asyncio.Event()
    finalized = asyncio.Event()

    class BlockingTransport:
        async def exchange(self, url: str, payload: dict, timeout: float):
            started.set()
            try:
                await asyncio.Event().wait()
                yield {}
            finally:
                finalized.set()

    prefix = f"maas-cancel-{uuid.uuid4().hex}"
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=prefix)
    loop = asyncio.get_running_loop()
    previous_executor = getattr(loop, "_default_executor", None)

    def owned_threads() -> set[int | None]:
        return {
            thread.ident
            for thread in threading.enumerate()
            if thread.name.startswith(prefix)
        }

    baseline = owned_threads()
    loop.set_default_executor(executor)
    try:
        client = IflytekMaaSClient(
            app_id="app",
            api_key="key",
            api_secret="secret",
            resource_id="resource-id",
            service_id="service-id",
            url="wss://example.test/v1.1/chat",
            timeout_seconds=5,
            transport=BlockingTransport(),
        )
        task = asyncio.create_task(
            client.generate(
                [{"role": "user", "content": "问题"}],
                uid="req",
            )
        )
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(finalized.wait(), timeout=1)

        assert owned_threads() == baseline
    finally:
        loop._default_executor = previous_executor
        executor.shutdown(wait=True, cancel_futures=True)


@pytest.mark.asyncio
async def test_close_is_idempotent():
    class CloseableTransport:
        def __init__(self) -> None:
            self.close_calls = 0

        async def exchange(self, url: str, payload: dict, timeout: float):
            if False:
                yield {}

        async def close(self) -> None:
            self.close_calls += 1

    transport = CloseableTransport()
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

    await client.close()
    await client.close()

    assert transport.close_calls == 1


@pytest.mark.asyncio
async def test_concurrent_client_close_callers_wait_for_shared_close():
    class BlockingCloseTransport:
        def __init__(self) -> None:
            self.calls = 0
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def exchange(self, url: str, payload: dict, timeout: float):
            if False:
                yield {}

        async def close(self) -> None:
            self.calls += 1
            self.started.set()
            await self.release.wait()

    transport = BlockingCloseTransport()
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
    first = asyncio.create_task(client.close())
    await asyncio.wait_for(transport.started.wait(), timeout=1)
    second = asyncio.create_task(client.close())
    await asyncio.sleep(0)
    second_completed_early = second.done()
    transport.release.set()
    await asyncio.gather(first, second)

    assert second_completed_early is False
    assert transport.calls == 1


@pytest.mark.asyncio
async def test_client_rejects_generation_as_soon_as_close_starts():
    class BarrierCloseTransport:
        def __init__(self) -> None:
            self.exchange_calls = 0
            self.close_entered = asyncio.Event()
            self.release_close = asyncio.Event()

        async def exchange(self, url: str, payload: dict, timeout: float):
            self.exchange_calls += 1
            yield terminal_frame()

        async def close(self) -> None:
            self.close_entered.set()
            await self.release_close.wait()

    transport = BarrierCloseTransport()
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
    close_task = asyncio.create_task(client.close())
    await asyncio.wait_for(transport.close_entered.wait(), timeout=1)

    try:
        with pytest.raises(ProviderUnavailable):
            await client.generate(
                [{"role": "user", "content": "问题"}],
                uid="req",
            )
    finally:
        transport.release_close.set()
        await close_task

    assert transport.exchange_calls == 0


@pytest.mark.asyncio
async def test_client_close_retries_after_failure():
    class FailOnceTransport:
        def __init__(self) -> None:
            self.calls = 0

        async def exchange(self, url: str, payload: dict, timeout: float):
            if False:
                yield {}

        async def close(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first close failed")

    transport = FailOnceTransport()
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
        await client.close()
    await client.close()

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert exc.value.message == "模型服务暂时不可用"
    assert transport.calls == 2

@pytest.mark.asyncio
async def test_client_close_sanitizes_transport_failure_and_retries():
    class FailOnceTransport:
        def __init__(self) -> None:
            self.calls = 0

        async def exchange(self, url: str, payload: dict, timeout: float):
            if False:
                yield {}

        async def close(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("provider-private-close-detail")

    transport = FailOnceTransport()
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
        await client.close()

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert exc.value.message == "模型服务暂时不可用"
    assert exc.value.details == {}
    assert "provider-private-close-detail" not in str(exc.value)
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None

    await client.close()

    assert transport.calls == 2


@pytest.mark.asyncio
async def test_client_close_failure_remains_non_accepting_for_retry():
    class FailOnceTransport:
        def __init__(self) -> None:
            self.close_calls = 0
            self.exchange_calls = 0

        async def exchange(self, url: str, payload: dict, timeout: float):
            self.exchange_calls += 1
            yield terminal_frame()

        async def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("first close failed")

    transport = FailOnceTransport()
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
        await client.close()
    with pytest.raises(ProviderUnavailable):
        await client.generate(
            [{"role": "user", "content": "问题"}],
            uid="req",
        )
    await client.close()

    assert exc.value.code == "MODEL_UNAVAILABLE"
    assert exc.value.message == "模型服务暂时不可用"
    assert transport.close_calls == 2
    assert transport.exchange_calls == 0


@pytest.mark.asyncio
async def test_client_close_retries_after_close_task_cancellation():
    class CancelOnceTransport:
        def __init__(self) -> None:
            self.calls = 0

        async def exchange(self, url: str, payload: dict, timeout: float):
            if False:
                yield {}

        async def close(self) -> None:
            self.calls += 1
            if self.calls == 1:
                raise asyncio.CancelledError

    transport = CancelOnceTransport()
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

    with pytest.raises(asyncio.CancelledError):
        await client.close()
    await client.close()

    assert transport.calls == 2
