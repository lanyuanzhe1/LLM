import asyncio
import inspect
import json
import traceback

import httpx
import pytest

from app.clients import xingchen_workflow
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.errors import ProviderUnavailable


RAW_SECRET = "RAW-PROVIDER-SECRET"


def frame(content: str, finish_reason=None, code=0) -> dict:
    return {
        "code": code,
        "message": "Success" if code == 0 else "failed",
        "id": "workflow-session",
        "choices": [
            {
                "delta": {"role": "assistant", "content": content},
                "index": 0,
                "finish_reason": finish_reason,
            }
        ],
    }


def workflow_client(
    http: httpx.AsyncClient | None = None,
    **overrides,
) -> XingchenWorkflowClient:
    options = {
        "api_key": "key",
        "api_secret": "secret",
        "flow_id": "flow",
        "url": "https://example.test/workflow",
        "timeout_seconds": 5,
        "http": http,
    }
    options.update(overrides)
    return XingchenWorkflowClient(
        **options,
    )


@pytest.mark.asyncio
async def test_workflow_sends_exact_request_and_parses_json_lines():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["content_type"] = request.headers["Content-Type"]
        seen["body"] = json.loads(request.content)
        seen["timeout"] = request.extensions["timeout"]
        body = "\n".join(
            [json.dumps(frame("你好，")), json.dumps(frame("世界", "stop"))]
        )
        return httpx.Response(200, text=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    frames = [
        item
        async for item in client.stream(
            {"AGENT_USER_INPUT": "你好"}, uid="user"
        )
    ]

    assert seen == {
        "method": "POST",
        "url": "https://example.test/workflow",
        "authorization": "Bearer key:secret",
        "content_type": "application/json",
        "body": {
            "flow_id": "flow",
            "uid": "user",
            "parameters": {"AGENT_USER_INPUT": "你好"},
            "stream": True,
        },
        "timeout": {
            "connect": 5,
            "read": 5,
            "write": 5,
            "pool": 5,
        },
    }
    assert "".join(item.choices[0].delta.content for item in frames) == (
        "你好，世界"
    )
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_accepts_data_sse_lines_and_ignores_blanks():
    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n\n".join(
            [
                f"data: {json.dumps(frame('第一段'))}",
                "   ",
                f"data:{json.dumps(frame('第二段', 'stop'))}",
            ]
        )
        return httpx.Response(200, text=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    frames = [
        item async for item in client.stream({"INPUT": "x"}, uid="user")
    ]

    assert [item.choices[0].delta.content for item in frames] == [
        "第一段",
        "第二段",
    ]
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_nonzero_code_after_content_is_stable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        body = "\n".join(
            [
                json.dumps(frame("partial")),
                json.dumps(frame("", code=22302)),
            ]
        )
        return httpx.Response(200, text=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)
    yielded = []

    with pytest.raises(ProviderUnavailable) as exc:
        async for item in client.stream({"AGENT_USER_INPUT": "x"}, uid="user"):
            yielded.append(item)

    assert [item.choices[0].delta.content for item in yielded] == ["partial"]
    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert "key" not in exc.value.message
    assert "secret" not in exc.value.message
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        httpx.Response(
            200,
            text=json.dumps(
                {
                    "code": RAW_SECRET,
                    "message": "failed",
                    "id": "workflow-session",
                    "choices": [],
                }
            ),
        ),
        httpx.ReadTimeout(RAW_SECRET),
    ],
)
async def test_workflow_error_drops_raw_provider_exception_state(result):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(result, Exception):
            result.request = request
            raise result
        return result

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream(
            {"PRIVATE_INPUT": RAW_SECRET}, uid="user"
        ):
            pass

    formatted = "".join(
        traceback.format_exception(
            type(exc.value),
            exc.value,
            exc.value.__traceback__,
        )
    )
    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert RAW_SECRET not in exc.value.message
    assert RAW_SECRET not in formatted
    await http.aclose()


class TwoPartStream(httpx.AsyncByteStream):
    def __init__(self, trailing_line: str) -> None:
        self.trailing_line = trailing_line
        self.read_count = 0

    async def __aiter__(self):
        self.read_count += 1
        yield f"{json.dumps(frame('done', 'stop'))}\n".encode()
        self.read_count += 1
        yield self.trailing_line.encode()


class ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class AdvancingStream(httpx.AsyncByteStream):
    def __init__(self, clock: ManualClock, lines: list[str]) -> None:
        self.clock = clock
        self.lines = lines
        self.closed = False

    async def __aiter__(self):
        for line in self.lines:
            self.clock.value += 0.4
            yield f"{line}\n".encode()

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.entered.set()
        await self.release.wait()
        yield f"{json.dumps(frame('late', 'stop'))}\n".encode()

    async def aclose(self) -> None:
        self.closed = True


class RawChunksStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yield_count = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.yield_count += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def compact_terminal_frame(content: str = "") -> bytes:
    value = {
        "code": 0,
        "message": "",
        "id": "",
        "choices": [
            {
                "delta": {"content": content},
                "finish_reason": "stop",
            }
        ],
    }
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trailing_line",
    [
        f'{{"malformed":"{RAW_SECRET}"',
        json.dumps(frame("", code=22302)),
    ],
)
async def test_workflow_stop_frame_ends_before_later_data(trailing_line):
    stream = TwoPartStream(trailing_line)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    frames = [
        item async for item in client.stream({"INPUT": "x"}, uid="user")
    ]

    assert [item.choices[0].delta.content for item in frames] == ["done"]
    assert stream.read_count == 1
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_total_deadline_stops_continuous_small_frames():
    clock = ManualClock()
    stream = AdvancingStream(
        clock,
        [
            json.dumps(frame("a")),
            json.dumps(frame("b")),
            json.dumps(frame("c")),
            json.dumps(frame("d", "stop")),
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, timeout_seconds=1, clock=clock)
    yielded = []

    with pytest.raises(ProviderUnavailable) as exc:
        async for item in client.stream({"INPUT": "x"}, uid="user"):
            yielded.append(item)

    assert [item.choices[0].delta.content for item in yielded] == ["a", "b"]
    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert exc.value.message == "智能体工作流暂时不可用"
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "body", "expected_yielded"),
    [
        (
            {"max_frames": 1},
            "\n".join(
                [
                    json.dumps(frame("a")),
                    json.dumps(frame("b", "stop")),
                ]
            ),
            ["a"],
        ),
        (
            {"max_payload_bytes": 1},
            json.dumps(frame("a", "stop")),
            [],
        ),
        (
            {"max_answer_chars": 3},
            json.dumps(frame("four", "stop")),
            [],
        ),
    ],
)
async def test_workflow_budget_overflow_fails_closed(
    overrides, body, expected_yielded
):
    stream = AdvancingStream(ManualClock(), body.splitlines())

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, **overrides)
    yielded = []

    with pytest.raises(ProviderUnavailable) as exc:
        async for item in client.stream({"INPUT": "x"}, uid="user"):
            yielded.append(item)

    assert [
        item.choices[0].delta.content for item in yielded
    ] == expected_yielded
    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert exc.value.message == "智能体工作流暂时不可用"
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flood",
    [b"\n" * 10_000, b"\r\n" * 10_000],
    ids=["lf", "crlf"],
)
async def test_workflow_raw_blank_line_flood_counts_every_byte(flood):
    terminal = compact_terminal_frame()
    assert len(terminal) <= 96
    stream = RawChunksStream([flood, terminal])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, max_payload_bytes=96)

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream({"INPUT": "x"}, uid="user"):
            pass

    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert exc.value.message == "智能体工作流暂时不可用"
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert stream.yield_count == 1
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_raw_budget_uses_utf8_bytes_not_characters():
    terminal = compact_terminal_frame("你")
    assert len(terminal) > len(terminal.decode("utf-8"))
    stream = RawChunksStream([terminal])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(
        http,
        max_payload_bytes=len(terminal) - 1,
    )

    with pytest.raises(ProviderUnavailable):
        async for _ in client.stream({"INPUT": "x"}, uid="user"):
            pass

    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_incremental_raw_parser_handles_real_chunk_boundaries():
    first = (
        "data:"
        + json.dumps(
            frame("你"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    ).encode("utf-8")
    second = (
        "data: "
        + json.dumps(
            frame("好", "stop"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    ).encode("utf-8")
    body = b"\r\n" + first + b"\r\n\r\n" + second
    split = body.index("你".encode("utf-8")) + 1
    stream = RawChunksStream(
        [
            body[:split],
            body[split : split + 1],
            body[split + 1 :],
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, max_payload_bytes=len(body))

    frames = [
        item async for item in client.stream({"INPUT": "x"}, uid="user")
    ]

    assert [item.choices[0].delta.content for item in frames] == ["你", "好"]
    assert stream.yield_count == 3
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_raw_parser_handles_split_crlf_and_bare_cr():
    first = json.dumps(
        frame("a"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    second = json.dumps(
        frame("b"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    terminal = compact_terminal_frame("c")
    body = first + b"\r\n" + second + b"\r" + terminal
    stream = RawChunksStream(
        [
            first + b"\r",
            b"\n" + second + b"\r" + terminal,
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, max_payload_bytes=len(body))

    frames = [
        item async for item in client.stream({"INPUT": "x"}, uid="user")
    ]

    assert [item.choices[0].delta.content for item in frames] == [
        "a",
        "b",
        "c",
    ]
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_raw_parser_rejects_invalid_final_utf8_safely():
    stream = RawChunksStream([b"data: \xe4\xb8"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream({"INPUT": "x"}, uid="user"):
            pass

    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert exc.value.message == "智能体工作流暂时不可用"
    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None
    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_one_byte_fragments_complete_within_linear_bound():
    terminal = compact_terminal_frame("done")
    body = b" " * 32_768 + terminal
    stream = RawChunksStream(
        [body[index : index + 1] for index in range(len(body))]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http, max_payload_bytes=len(body))

    async def collect_frames():
        return [
            item
            async for item in client.stream({"INPUT": "x"}, uid="user")
        ]

    frames = await asyncio.wait_for(collect_frames(), timeout=1)

    assert [item.choices[0].delta.content for item in frames] == ["done"]
    assert stream.yield_count == len(body)
    assert stream.closed is True
    await http.aclose()


def test_raw_line_decoder_avoids_copying_the_bytearray_before_decode():
    source = inspect.getsource(xingchen_workflow._bounded_raw_lines)

    assert "bytes(line).decode" not in source
    assert 'line.decode("utf-8")' in source


@pytest.mark.asyncio
async def test_workflow_external_cancellation_propagates_and_closes_stream():
    stream = BlockingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    async def consume() -> None:
        async for _ in client.stream({"INPUT": "x"}, uid="user"):
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(stream.entered.wait(), timeout=1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert stream.closed is True
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        httpx.Response(503, text="upstream leaked payload"),
        httpx.Response(200, text='data: {"code":'),
        httpx.ReadTimeout("transport leaked payload"),
    ],
)
async def test_workflow_transport_http_and_malformed_failures_are_stable(result):
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(result, Exception):
            raise result
        return result

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream(
            {"PRIVATE_INPUT": "do-not-leak"}, uid="user"
        ):
            pass

    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    assert "do-not-leak" not in exc.value.message
    assert "upstream leaked payload" not in exc.value.message
    assert "transport leaked payload" not in exc.value.message
    assert "secret" not in exc.value.message
    await http.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        "",
        json.dumps(frame("partial")),
        json.dumps(
            {
                "code": 0,
                "message": "Success",
                "id": "workflow-session",
                "choices": [],
            }
        ),
    ],
)
async def test_workflow_rejects_stream_without_terminal_stop(body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = workflow_client(http)

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream({"AGENT_USER_INPUT": "x"}, uid="user"):
            pass

    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    await http.aclose()


@pytest.mark.asyncio
async def test_close_closes_owned_http_client():
    client = workflow_client()

    assert client._http.is_closed is False
    await client.close()

    assert client._http.is_closed is True


@pytest.mark.asyncio
async def test_close_leaves_borrowed_http_client_open():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None))
    client = workflow_client(http)

    await client.close()

    assert http.is_closed is False
    await http.aclose()
