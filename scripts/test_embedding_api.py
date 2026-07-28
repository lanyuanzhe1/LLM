# -*- coding: utf-8 -*-
"""
iFlytek Embedding API Connectivity Test
Based on: https://www.xfyun.cn/doc/spark/Embedding_api.html

Interface: HTTP POST, HMAC-SHA256 signature authentication
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
import sys
from datetime import datetime, timezone
import requests
import numpy as np

# Force UTF-8 output on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ============================================================
# Your credentials
# ============================================================
APP_ID = "5c75015a"
API_KEY = "d29f3016bcfa0ac8a46fcce888d7c0fb"
API_SECRET = "YTQxNzQ1MjhkNzljODMxYTQ1OTRiMWZh"
# ============================================================


def generate_signature(api_key, api_secret, host, date_str,
                       method, path, body_digest=None):
    """Generate HMAC-SHA256 signature (iFlytek HTTP API standard auth)."""
    signature_origin = f"host: {host}\ndate: {date_str}\n{method} {path} HTTP/1.1"
    if body_digest:
        signature_origin += f"\ndigest: {body_digest}"

    signature_sha = hmac.new(
        api_secret.encode('utf-8'),
        signature_origin.encode('utf-8'),
        digestmod=hashlib.sha256
    ).digest()

    signature = base64.b64encode(signature_sha).decode('utf-8')

    headers_part = "host date request-line"
    if body_digest:
        headers_part += " digest"

    authorization = (
        f'api_key="{api_key}", '
        f'algorithm="hmac-sha256", '
        f'headers="{headers_part}", '
        f'signature="{signature}"'
    )

    return authorization, signature_origin


def embed_text(text, domain="query"):
    """
    Call iFlytek Embedding API to convert text to vector.

    Args:
        text: Text to vectorize
        domain: "query" (user question) or "para" (knowledge base document)
    Returns:
        2560-dim float32 numpy array, or None on failure
    """
    host = "emb-cn-huabei-1.xf-yun.com"
    path = "/"
    method = "POST"
    url = f"https://{host}/"

    # UTC time in HTTP-date format
    now = datetime.now(timezone.utc)
    date_str = now.strftime('%a, %d %b %Y %H:%M:%S GMT')

    # Prepare request body
    messages_text = json.dumps({
        "messages": [
            {"content": text, "role": "user"}
        ]
    })
    text_base64 = base64.b64encode(messages_text.encode('utf-8')).decode('utf-8')

    request_body = {
        "header": {
            "app_id": APP_ID,
            "uid": str(uuid.uuid4()),
            "status": 3
        },
        "parameter": {
            "emb": {
                "domain": domain,
                "feature": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "plain"
                }
            }
        },
        "payload": {
            "messages": {
                "encoding": "utf8",
                "compress": "raw",
                "format": "json",
                "status": 3,
                "text": text_base64
            }
        }
    }

    body_str = json.dumps(request_body)
    body_digest_sha = base64.b64encode(
        hashlib.sha256(body_str.encode('utf-8')).digest()
    ).decode('utf-8')

    # Full digest with prefix for signature (must be "SHA-256=xxx")
    body_digest_full = f"SHA-256={body_digest_sha}"

    # Generate signature
    authorization, sig_origin = generate_signature(
        API_KEY, API_SECRET, host, date_str, method, path, body_digest_full
    )

    # Build request headers
    headers = {
        "Host": host,
        "Date": date_str,
        "Digest": body_digest_full,
        "Authorization": authorization,
        "Content-Type": "application/json",
    }

    print(f"[SEND] domain={domain}")
    print(f"       text: {text[:50]}...")
    print(f"       sig_origin: {sig_origin}")

    try:
        response = requests.post(url, headers=headers, data=body_str, timeout=30)
    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None

    print(f"       HTTP status: {response.status_code}")

    if response.status_code == 200:
        result = response.json()
        code = result.get("header", {}).get("code", -1)
        message = result.get("header", {}).get("message", "")
        print(f"       API code: {code}, msg: {message}")

        if code == 0:
            feature_text_b64 = result["payload"]["feature"]["text"]
            vector_bytes = base64.b64decode(feature_text_b64)
            # little-endian float32
            vector = np.frombuffer(vector_bytes, dtype=np.dtype(np.float32).newbyteorder("<"))
            print(f"       [OK] Vector dim: {len(vector)}")
            print(f"       First 5 values: {vector[:5]}")
            return vector
        else:
            print(f"       [FAIL] API code={code}, message={message}")
            print(f"       Full response: {json.dumps(result, indent=2, ensure_ascii=False)}")
            return None
    else:
        print(f"       [FAIL] HTTP {response.status_code}")
        print(f"       Response: {response.text[:500]}")
        return None


if __name__ == "__main__":
    print("=" * 60)
    print("  iFlytek Embedding API - Connectivity Test")
    print("=" * 60)
    print(f"  APP_ID: {APP_ID}")
    print(f"  API_KEY: {API_KEY[:8]}...")
    print()

    # Test 1: query mode
    print("[Test 1] query mode vectorization")
    vec1 = embed_text("你好，这是一个测试文本", domain="query")

    if vec1 is not None:
        print()
        print("[Test 2] para mode vectorization")
        vec2 = embed_text("人工智能是计算机科学的一个分支", domain="para")

        if vec2 is not None:
            # Cosine similarity
            similarity = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
            print(f"\n[RESULT] Cosine similarity: {similarity:.4f}")

    print()
    print("=" * 60)
    if vec1 is not None:
        print("  [OK] Embedding API test passed!")
    else:
        print("  [FAIL] Test failed - check error messages above")
    print("=" * 60)
