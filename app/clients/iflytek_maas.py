import asyncio
import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Protocol
from urllib.parse import urlencode, urlparse

from websockets.asyncio.client import connect

from app.core.errors import ProviderUnavailable


DEFAULT_MAX_FRAMES = 1024
DEFAULT_MAX_PAYLOAD_BYTES = 2_097_152
DEFAULT_MAX_ANSWER_CHARS = 32_000


class _MaaSBudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class MaaSResult:
    content: str
    total_tokens: int


class MaaSTransport(Protocol):
    def exchange(
        self, url: str, payload: dict, timeout: float
    ) -> AsyncIterator[dict]: ...


class WebSocketTransport:
    def __init__(
        self,
        *,
        max_frames: int = DEFAULT_MAX_FRAMES,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        self.max_frames = max_frames
        self.max_payload_bytes = max_payload_bytes
        self._connections: set[Any] = set()
        self._exchange_tasks: set[asyncio.Task[Any]] = set()
        self._transport_cancel_counts: dict[
            asyncio.Task[Any],
            tuple[int, int],
        ] = {}
        self._state_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._accepting = True
        self._closed = False

    async def exchange(
        self, url: str, payload: dict, timeout: float
    ) -> AsyncIterator[dict]:
        exchange_task = asyncio.current_task()
        if exchange_task is None:
            raise RuntimeError("MaaS exchange requires an asyncio task")
        async with self._state_lock:
            if not self._accepting:
                raise RuntimeError("MaaS transport is closed")
            self._exchange_tasks.add(exchange_task)
        try:
            connection_context = connect(
                url,
                open_timeout=timeout,
                close_timeout=timeout,
            )
            connection = await connection_context.__aenter__()
            self._connections.add(connection)
            pending_exception: BaseException | None = None
            try:
                await connection.send(
                    json.dumps(payload, ensure_ascii=False)
                )
                frame_count = 0
                payload_bytes = 0
                while True:
                    raw_frame = await asyncio.wait_for(
                        connection.recv(),
                        timeout=timeout,
                    )
                    frame_count += 1
                    if frame_count > self.max_frames:
                        raise _MaaSBudgetExceeded
                    if isinstance(raw_frame, str):
                        raw_size = len(raw_frame.encode("utf-8"))
                    elif isinstance(raw_frame, bytes):
                        raw_size = len(raw_frame)
                    else:
                        raise ValueError(
                            "MaaS websocket frame must be text or bytes"
                        )
                    payload_bytes += raw_size
                    if payload_bytes > self.max_payload_bytes:
                        raise _MaaSBudgetExceeded
                    frame = json.loads(raw_frame)
                    yield frame
                    header_status = frame.get("header", {}).get("status")
                    choice_status = (
                        frame.get("payload", {})
                        .get("choices", {})
                        .get("status")
                    )
                    if header_status == 2 or choice_status == 2:
                        break
            except BaseException as exc:
                suppressed = False
                try:
                    suppressed = await connection_context.__aexit__(
                        type(exc),
                        exc,
                        exc.__traceback__,
                    )
                except BaseException as cleanup_error:
                    cancel_counts = self._transport_cancel_counts.get(
                        exchange_task
                    )
                    current_cancels = exchange_task.cancelling()
                    externally_cancelled = (
                        current_cancels > 0
                        if cancel_counts is None
                        else (
                            cancel_counts[0] > 0
                            or current_cancels > cancel_counts[1]
                        )
                    )
                    if externally_cancelled:
                        pending_exception = asyncio.CancelledError()
                    else:
                        pending_exception = cleanup_error
                else:
                    self._connections.discard(connection)
                if not suppressed:
                    pending_exception = pending_exception or exc
            else:
                await connection_context.__aexit__(None, None, None)
                self._connections.discard(connection)
            if pending_exception is not None:
                raise pending_exception
        finally:
            async with self._state_lock:
                self._exchange_tasks.discard(exchange_task)

    async def _close_once(
        self,
        close_owner: asyncio.Task[Any] | None,
    ) -> None:
        current_task = asyncio.current_task()
        async with self._state_lock:
            exchange_tasks = tuple(
                task
                for task in self._exchange_tasks
                if task is not current_task and task is not close_owner
            )
        for task in exchange_tasks:
            cancellations_before = task.cancelling()
            task.cancel()
            self._transport_cancel_counts[task] = (
                cancellations_before,
                task.cancelling(),
            )
        try:
            results = await asyncio.gather(
                *exchange_tasks,
                return_exceptions=True,
            )
        finally:
            for task in exchange_tasks:
                self._transport_cancel_counts.pop(task, None)
        first_error = next(
            (
                result
                for result in results
                if isinstance(result, BaseException)
                and not isinstance(result, asyncio.CancelledError)
            ),
            None,
        )
        for connection in tuple(self._connections):
            try:
                await connection.close()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
            else:
                self._connections.discard(connection)
        if first_error is not None:
            raise first_error

    async def _shared_close_task(
        self,
        close_owner: asyncio.Task[Any] | None,
    ) -> asyncio.Task[None] | None:
        async with self._state_lock:
            if self._closed:
                return None
            task = self._close_task
            if task is not None and task.done():
                if task.cancelled() or task.exception() is not None:
                    self._close_task = None
                else:
                    self._closed = True
                    return None
            if self._close_task is None:
                self._accepting = False
                self._close_task = asyncio.create_task(
                    self._close_once(close_owner)
                )
            return self._close_task

    async def _settle_close_task(self, task: asyncio.Task[None]) -> None:
        if not task.done():
            return
        async with self._state_lock:
            if self._close_task is not task:
                return
            if task.cancelled() or task.exception() is not None:
                self._close_task = None
            else:
                self._closed = True

    async def close(self) -> None:
        task = await self._shared_close_task(asyncio.current_task())
        if task is None:
            return
        try:
            await asyncio.shield(task)
        finally:
            await self._settle_close_task(task)


class IflytekMaaSClient:
    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        resource_id: str,
        service_id: str,
        url: str,
        timeout_seconds: float,
        transport: MaaSTransport | None = None,
        max_frames: int = DEFAULT_MAX_FRAMES,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.resource_id = resource_id
        self.service_id = service_id
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_frames = max_frames
        self.max_payload_bytes = max_payload_bytes
        self.max_answer_chars = max_answer_chars
        self.clock = clock
        self.transport = transport or WebSocketTransport(
            max_frames=max_frames,
            max_payload_bytes=max_payload_bytes,
        )
        self._close_lock = asyncio.Lock()
        self._close_task: asyncio.Task[None] | None = None
        self._accepting = True
        self._closed = False

    def create_auth_url(self, now: datetime | None = None) -> str:
        parsed = urlparse(self.url)
        date = format_datetime(now or datetime.now(timezone.utc), usegmt=True)
        origin = (
            f"host: {parsed.netloc}\n"
            f"date: {date}\n"
            f"GET {parsed.path} HTTP/1.1"
        )
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                origin.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(
            authorization_origin.encode()
        ).decode()
        query = urlencode(
            {
                "authorization": authorization,
                "date": date,
                "host": parsed.netloc,
            }
        )
        return f"{self.url}?{query}"

    async def _generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult:
        payload = {
            "header": {
                "app_id": self.app_id,
                "uid": uid[:32],
                "patch_id": [self.resource_id],
            },
            "parameter": {
                "chat": {
                    "domain": self.service_id,
                    "temperature": 0.2,
                    "top_k": 2,
                    "max_tokens": 2048,
                    "auditing": "default",
                }
            },
            "payload": {"message": {"text": messages}},
        }
        chunks: list[str] = []
        answer_chars = 0
        frame_count = 0
        payload_bytes = 0
        total_tokens = 0
        terminal_complete = False
        failure: ProviderUnavailable | None = None
        cancellation: asyncio.CancelledError | None = None
        stream = self.transport.exchange(
            self.create_auth_url(), payload, self.timeout_seconds
        )
        deadline = self.clock() + self.timeout_seconds
        try:
            async for frame in stream:
                if self.clock() >= deadline:
                    raise TimeoutError
                frame_count += 1
                if frame_count > self.max_frames:
                    raise _MaaSBudgetExceeded
                try:
                    payload_bytes += len(
                        json.dumps(
                            frame,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        "MaaS frame must be JSON serializable"
                    ) from exc
                if payload_bytes > self.max_payload_bytes:
                    raise _MaaSBudgetExceeded
                if not isinstance(frame, dict):
                    raise ValueError("MaaS frame must be an object")
                header = frame.get("header")
                if not isinstance(header, dict):
                    raise ValueError("MaaS frame header must be an object")
                code = header.get("code")
                if not isinstance(code, int) or isinstance(code, bool):
                    raise ValueError("MaaS header code must be an integer")
                if code != 0:
                    raise ProviderUnavailable(
                        "MAAS_UNAVAILABLE",
                        f"模型服务错误 {code}",
                    )
                payload_frame = frame.get("payload")
                if not isinstance(payload_frame, dict):
                    raise ValueError("MaaS frame payload must be an object")
                choices = payload_frame.get("choices")
                if not isinstance(choices, dict):
                    raise ValueError("MaaS choices must be an object")

                header_status = header.get("status")
                choice_status = choices.get("status")
                valid_statuses = {0, 1, 2}
                if (
                    not isinstance(header_status, int)
                    or isinstance(header_status, bool)
                    or header_status not in valid_statuses
                    or not isinstance(choice_status, int)
                    or isinstance(choice_status, bool)
                    or choice_status not in valid_statuses
                ):
                    raise ValueError("MaaS frame status is missing or invalid")
                if header_status != choice_status:
                    raise ValueError("MaaS frame statuses are inconsistent")

                text_items = choices.get("text")
                if not isinstance(text_items, list):
                    raise ValueError("MaaS choices text must be a list")
                for item in text_items:
                    if not isinstance(item, dict):
                        raise ValueError("MaaS text item must be an object")
                    content = item.get("content")
                    if not isinstance(content, str):
                        raise ValueError(
                            "MaaS text item content must be a string"
                        )
                    answer_chars += len(content)
                    if answer_chars > self.max_answer_chars:
                        raise _MaaSBudgetExceeded
                    chunks.append(content)

                usage = payload_frame.get("usage")
                if usage is not None:
                    if not isinstance(usage, dict):
                        raise ValueError("MaaS usage must be an object")
                    usage_text = usage.get("text")
                    if not isinstance(usage_text, dict):
                        raise ValueError("MaaS usage text must be an object")
                    usage_tokens = usage_text.get("total_tokens")
                    if (
                        not isinstance(usage_tokens, int)
                        or isinstance(usage_tokens, bool)
                        or usage_tokens < 0
                    ):
                        raise ValueError(
                            "MaaS total token usage must be a non-negative integer"
                        )
                    total_tokens = usage_tokens

                if header_status == 2:
                    terminal_complete = True
                    break
            if not terminal_complete:
                raise ProviderUnavailable(
                    "MODEL_UNAVAILABLE",
                    "模型服务响应未正常结束",
                )
        except BaseException as exc:
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                cancellation = asyncio.CancelledError()
            elif isinstance(exc, asyncio.CancelledError):
                cancellation = exc
            elif isinstance(exc, ProviderUnavailable):
                failure = exc
            elif isinstance(exc, _MaaSBudgetExceeded):
                failure = ProviderUnavailable(
                    "MAAS_UNAVAILABLE",
                    "模型服务响应超出安全限制",
                )
            elif isinstance(exc, TimeoutError):
                failure = ProviderUnavailable(
                    "MODEL_UNAVAILABLE", "模型服务请求超时"
                )
            elif isinstance(exc, ValueError):
                failure = ProviderUnavailable(
                    "MAAS_UNAVAILABLE", "模型服务响应格式无效"
                )
            elif isinstance(exc, Exception):
                failure = ProviderUnavailable(
                    "MODEL_UNAVAILABLE", "模型服务暂时不可用"
                )
            else:
                raise
        close_stream = getattr(stream, "aclose", None)
        if close_stream is not None:
            try:
                await close_stream()
            except asyncio.CancelledError:
                raise
            except Exception:
                task = asyncio.current_task()
                if task is not None and task.cancelling():
                    cancellation = cancellation or asyncio.CancelledError()
                elif cancellation is None and failure is None:
                    failure = ProviderUnavailable(
                        "MODEL_UNAVAILABLE", "模型服务暂时不可用"
                    )
        if cancellation is not None:
            raise cancellation
        if failure is not None:
            raise failure
        content = "".join(chunks)
        if not content.strip():
            raise ProviderUnavailable(
                "MODEL_UNAVAILABLE",
                "模型服务未返回可用内容",
            ) from None
        return MaaSResult(content=content, total_tokens=total_tokens)

    async def generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult:
        if not self._accepting:
            raise ProviderUnavailable(
                "MAAS_UNAVAILABLE", "模型服务客户端已关闭"
            )
        timed_out = False
        try:
            result = await asyncio.wait_for(
                self._generate(messages, uid),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            timed_out = True

        if timed_out:
            raise ProviderUnavailable(
                "MODEL_UNAVAILABLE",
                "模型服务请求超时",
            ) from None
        return result

    async def _close_once(self) -> None:
        close_transport = getattr(self.transport, "close", None)
        if close_transport is None:
            return
        failure: ProviderUnavailable | None = None
        try:
            await close_transport()
        except asyncio.CancelledError:
            raise
        except Exception:
            failure = ProviderUnavailable(
                "MODEL_UNAVAILABLE", "模型服务暂时不可用"
            )
        if failure is not None:
            raise failure

    async def _shared_close_task(self) -> asyncio.Task[None] | None:
        async with self._close_lock:
            if self._closed:
                return None
            task = self._close_task
            if task is not None and task.done():
                if task.cancelled() or task.exception() is not None:
                    self._close_task = None
                else:
                    self._closed = True
                    return None
            if self._close_task is None:
                self._accepting = False
                self._close_task = asyncio.create_task(self._close_once())
            return self._close_task

    async def _settle_close_task(self, task: asyncio.Task[None]) -> None:
        if not task.done():
            return
        async with self._close_lock:
            if self._close_task is not task:
                return
            if task.cancelled() or task.exception() is not None:
                self._close_task = None
            else:
                self._closed = True

    async def close(self) -> None:
        task = await self._shared_close_task()
        if task is None:
            return
        try:
            await asyncio.shield(task)
        finally:
            await self._settle_close_task(task)
