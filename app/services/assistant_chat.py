"""星火助手（智能体广场）对话桥接。

协议与讯飞 MaaS 同构（header/parameter/payload + choices.text 流式帧），
鉴权为 HMAC-SHA256 URL 签名（同 app/clients/iflytek_maas.py create_auth_url）。
本模块只产出 (event, data) 事件，SSE 封装由路由层负责。
"""
import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlencode, urlparse

from websockets.asyncio.client import connect

MAX_FRAMES = 1024


def _build_auth_url(
    url: str,
    api_key: str,
    api_secret: str,
) -> str:
    parsed = urlparse(url)
    date = format_datetime(datetime.now(timezone.utc), usegmt=True)
    origin = (
        f"host: {parsed.netloc}\n"
        f"date: {date}\n"
        f"GET {parsed.path} HTTP/1.1"
    )
    signature = base64.b64encode(
        hmac.new(
            api_secret.encode(),
            origin.encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
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
    return f"{url}?{query}"


async def stream_assistant(
    *,
    assistant_id: str,
    url_base: str,
    api_key: str,
    api_secret: str,
    app_id: str,
    uid: str,
    messages: list[dict[str, str]],
    timeout_seconds: float = 120.0,
) -> AsyncIterator[tuple[str, dict]]:
    """对话一个讯飞助手，逐段产出 ("delta", {content})，出错产出 ("error", {message})。"""
    url = f"{url_base.rstrip('/')}/{assistant_id}"
    payload = {
        "header": {"app_id": app_id, "uid": uid[:32]},
        "parameter": {
            "chat": {
                "domain": "generalv3",
                "temperature": 0.5,
                "top_k": 4,
                "max_tokens": 2048,
            }
        },
        "payload": {"message": {"text": messages}},
    }
    try:
        async with connect(
            _build_auth_url(url, api_key, api_secret),
            open_timeout=timeout_seconds,
            close_timeout=timeout_seconds,
        ) as ws:
            await ws.send(json.dumps(payload, ensure_ascii=False))
            for _ in range(MAX_FRAMES):
                raw = await asyncio.wait_for(
                    ws.recv(), timeout=timeout_seconds
                )
                frame = json.loads(raw)
                header = frame.get("header") or {}
                code = header.get("code")
                if code not in (0, None):
                    yield "error", {
                        "message": f"智能体服务错误 {code}：{header.get('message', '')}".strip()
                    }
                    return
                choices = frame.get("payload", {}).get("choices") or {}
                for item in choices.get("text") or []:
                    content = item.get("content")
                    if content:
                        yield "delta", {"content": content}
                header_status = header.get("status")
                choice_status = choices.get("status")
                if header_status == 2 or choice_status == 2:
                    return
            yield "error", {"message": "智能体响应帧数超限"}
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        yield "error", {"message": "智能体服务响应超时"}
    except Exception as exc:  # noqa: BLE001 - 把网络/协议错误转成可读事件
        yield "error", {"message": f"智能体服务暂时不可用（{type(exc).__name__}）"}
