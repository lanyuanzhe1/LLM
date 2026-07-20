import json
import os

import httpx
import pytest


pytestmark = pytest.mark.online


def _online_base_url() -> str:
    if os.getenv("RUN_ONLINE") != "1":
        pytest.skip("set RUN_ONLINE=1 to run the end-to-end test")
    return os.environ["LOCAL_PUBLIC_API_URL"].rstrip("/")


async def _post_sse(path: str, payload: dict) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name: str | None = None
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{_online_base_url()}{path}",
            json=payload,
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    event_name = line.removeprefix("event: ")
                elif line.startswith("data: "):
                    assert event_name is not None
                    events.append(
                        (event_name, json.loads(line.removeprefix("data: ")))
                    )
                    event_name = None
    return events


@pytest.mark.asyncio
async def test_public_chat_end_to_end():
    events = await _post_sse(
        "/v1/chat",
        {"message": "低温储粮有什么作用？", "role": "student"},
    )
    event_names = [name for name, _ in events]

    assert "delta" in event_names
    assert "error" not in event_names
    answer = "".join(data["content"] for name, data in events if name == "delta")
    assert answer not in {
        "知识库证据不足，无法提供可靠回答。",
        "回答未通过引用验证，无法安全展示生成内容。",
    }
    for heading in ("结论", "依据", "适用条件", "不确定性", "来源"):
        assert heading in answer
    citations = next(data for name, data in events if name == "citations")
    assert citations["items"]
    assert all(
        {"evidence_id", "document_id", "title", "source", "text"}
        <= set(item)
        for item in citations["items"]
    )
    done = next(data for name, data in events if name == "done")
    assert done == {"finish_reason": "stop", "missing_fields": []}


@pytest.mark.asyncio
async def test_incomplete_case_requests_storage_type():
    events = await _post_sse(
        "/v1/cases/analyze",
        {
            "role": "technician",
            "case": {
                "grain_type": "小麦",
                "goal": "分析当前储藏风险",
            },
        },
    )

    assert all(name != "error" for name, _ in events)
    done = next(data for name, data in events if name == "done")
    assert done["finish_reason"] == "needs_input"
    assert "storage_type" in done["missing_fields"]
