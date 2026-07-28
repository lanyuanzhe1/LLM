# -*- coding: utf-8 -*-
"""
Test fine-tuned model inference via MaaS WebSocket API
Endpoint: wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat
"""

import base64
import hashlib
import hmac
import json
import ssl
import sys
from datetime import datetime
from time import mktime
from urllib.parse import urlencode, urlparse
from wsgiref.handlers import format_date_time

import websocket

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============================================================
APP_ID = "5c75015a"
API_KEY = "d29f3016bcfa0ac8a46fcce888d7c0fb"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
RESOURCE_ID = "2066745321636515840"
SERVICE_ID = "xop3qwen32b"
# ============================================================

SPARK_URL = "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat"
parsed = urlparse(SPARK_URL)
HOST = parsed.netloc
PATH = parsed.path


def create_auth_url() -> str:
    """Generate HMAC-SHA256 signed WebSocket URL (official algorithm)."""
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))

    signature_origin = f"host: {HOST}\ndate: {date}\nGET {PATH} HTTP/1.1"
    signature_sha = hmac.new(
        API_SECRET.encode("utf-8"),
        signature_origin.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(signature_sha).decode("utf-8")

    authorization_origin = (
        f'api_key="{API_KEY}", '
        f'algorithm="hmac-sha256", '
        f'headers="host date request-line", '
        f'signature="{signature}"'
    )
    authorization = base64.b64encode(
        authorization_origin.encode("utf-8")
    ).decode("utf-8")

    params = {"authorization": authorization, "date": date, "host": HOST}
    return f"{SPARK_URL}?{urlencode(params)}"


def ask(question: str, system_prompt: str = None) -> str:
    """Send a question to the fine-tuned model via WebSocket."""
    full_content = []

    # Build messages
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": question})

    request = {
        "header": {
            "app_id": APP_ID,
            "uid": "gsid_test",
            "patch_id": [RESOURCE_ID],
        },
        "parameter": {
            "chat": {
                "domain": SERVICE_ID,
                "temperature": 0.5,
                "top_k": 4,
                "max_tokens": 2048,
                "auditing": "default",
            }
        },
        "payload": {"message": {"text": messages}},
    }

    def on_open(ws):
        ws.send(json.dumps(request))

    def on_message(ws, message):
        data = json.loads(message)
        code = data["header"]["code"]
        if code != 0:
            print(f"\n[ERROR {code}] {data['header'].get('message','')}")
            ws.close()
            return

        choices = data.get("payload", {}).get("choices", {})
        if choices.get("text"):
            content = choices["text"][0]["content"]
            full_content.append(content)
            print(content, end="", flush=True)

        if choices.get("status") == 2:
            usage = data.get("payload", {}).get("usage", {}).get("text", {})
            total = usage.get("total_tokens", 0)
            print(f"\n[Tokens: {total}]")
            ws.close()

    def on_error(ws, error):
        print(f"\n[WS Error] {error}")

    ws = websocket.WebSocketApp(
        create_auth_url(),
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
    )
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
    return "".join(full_content)


if __name__ == "__main__":
    print("=" * 55)
    print("  Fine-tuned Model Inference Test")
    print(f"  modelId: {SERVICE_ID}")
    print(f"  resourceId: {RESOURCE_ID}")
    print("=" * 55)

    SYSTEM = (
        "你是一位粮食储藏领域的资深专家，拥有20年以上从业经验。"
        "回答要求：专业准确、涉及标准时注明条款编号。"
    )

    queries = [
        "储粮害虫有哪些防治方法？",
        "低温储粮技术的原理是什么？",
        "粮食安全保障法对政府储备有什么要求？",
        "CO2监测在储粮安全中起什么作用？",
    ]
    for q in queries:
        print(f"\n  Q: {q}")
        print(f"  A: ", end="")
        try:
            ask(q, system_prompt=SYSTEM)
        except Exception as e:
            print(f"\n  [ERROR] {e}")
        print()
