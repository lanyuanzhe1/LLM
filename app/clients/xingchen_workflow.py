import asyncio
import time
from collections.abc import AsyncIterator
from collections.abc import Callable

import httpx

from app.core.errors import ProviderUnavailable
from app.schemas.events import WorkflowFrame


DEFAULT_MAX_FRAMES = 1_024
DEFAULT_MAX_PAYLOAD_BYTES = 2_097_152
DEFAULT_MAX_ANSWER_CHARS = 32_000


class _WorkflowLimitExceeded(Exception):
    pass


async def _bounded_raw_lines(
    response: httpx.Response,
    *,
    max_payload_bytes: int,
    deadline: float,
    clock: Callable[[], float],
) -> AsyncIterator[str]:
    payload_bytes = 0
    line = bytearray()
    pending_cr = False
    bytes_since_deadline_check = 0

    def decode_line() -> str:
        value = line.decode("utf-8")
        line.clear()
        return value

    async for chunk in response.aiter_bytes():
        if clock() >= deadline:
            raise _WorkflowLimitExceeded
        payload_bytes += len(chunk)
        if payload_bytes > max_payload_bytes:
            raise _WorkflowLimitExceeded
        for byte in chunk:
            bytes_since_deadline_check += 1
            if bytes_since_deadline_check >= 4_096:
                if clock() >= deadline:
                    raise _WorkflowLimitExceeded
                bytes_since_deadline_check = 0

            if pending_cr:
                pending_cr = False
                completed = decode_line()
                if clock() >= deadline:
                    raise _WorkflowLimitExceeded
                yield completed
                if byte == 0x0A:
                    continue

            if byte == 0x0D:
                pending_cr = True
            elif byte == 0x0A:
                completed = decode_line()
                if clock() >= deadline:
                    raise _WorkflowLimitExceeded
                yield completed
            else:
                line.append(byte)

    if pending_cr or line:
        completed = decode_line()
        if clock() >= deadline:
            raise _WorkflowLimitExceeded
        yield completed


class XingchenWorkflowClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        flow_id: str,
        url: str,
        timeout_seconds: float,
        http: httpx.AsyncClient | None = None,
        max_frames: int = DEFAULT_MAX_FRAMES,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.authorization = f"Bearer {api_key}:{api_secret}"
        self.flow_id = flow_id
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_frames = max_frames
        self.max_payload_bytes = max_payload_bytes
        self.max_answer_chars = max_answer_chars
        self._clock = clock
        self._http = http or httpx.AsyncClient()
        self._owns_http = http is None

    async def stream(
        self, parameters: dict, uid: str
    ) -> AsyncIterator[WorkflowFrame]:
        payload = {
            "flow_id": self.flow_id,
            "uid": uid,
            "parameters": parameters,
            "stream": True,
        }
        deadline = self._clock() + self.timeout_seconds
        frame_count = 0
        answer_chars = 0
        failed = False
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self._http.stream(
                    "POST",
                    self.url,
                    headers={
                        "Authorization": self.authorization,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                ) as response:
                    response.raise_for_status()
                    async for line in _bounded_raw_lines(
                        response,
                        max_payload_bytes=self.max_payload_bytes,
                        deadline=deadline,
                        clock=self._clock,
                    ):
                        value = line.strip()
                        if not value:
                            continue
                        if value.startswith("data:"):
                            value = value[5:].strip()

                        frame_count += 1
                        if frame_count > self.max_frames:
                            raise _WorkflowLimitExceeded

                        frame = WorkflowFrame.model_validate_json(value)
                        frame_answer_chars = sum(
                            len(choice.delta.content)
                            for choice in frame.choices
                        )
                        answer_chars += frame_answer_chars
                        if answer_chars > self.max_answer_chars:
                            raise _WorkflowLimitExceeded

                        if frame.code != 0:
                            raise ProviderUnavailable(
                                "WORKFLOW_UNAVAILABLE",
                                f"智能体工作流错误 {frame.code}",
                            )
                        terminal = any(
                            choice.finish_reason == "stop"
                            for choice in frame.choices
                        )
                        yield frame
                        if terminal:
                            return

            raise ProviderUnavailable(
                "WORKFLOW_UNAVAILABLE",
                "智能体工作流响应未正常结束",
            )
        except asyncio.CancelledError:
            raise
        except ProviderUnavailable:
            raise
        except Exception:
            failed = True

        if failed:
            raise ProviderUnavailable(
                "WORKFLOW_UNAVAILABLE",
                "智能体工作流暂时不可用",
            ) from None

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
