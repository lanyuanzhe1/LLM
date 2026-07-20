import asyncio
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urlparse

import httpx
import numpy as np

from app.core.errors import ProviderUnavailable


class IflytekEmbeddingClient:
    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        url: str,
        timeout_seconds: float,
        http: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._http = http or httpx.AsyncClient()
        self._owns_http = http is None

    def _headers(self, body: bytes, now: datetime | None = None) -> dict[str, str]:
        parsed = urlparse(self.url)
        current = now or datetime.now(timezone.utc)
        date = format_datetime(current, usegmt=True)
        digest_value = base64.b64encode(hashlib.sha256(body).digest()).decode()
        digest = f"SHA-256={digest_value}"
        path = parsed.path or "/"
        origin = (
            f"host: {parsed.netloc}\n"
            f"date: {date}\n"
            f"POST {path} HTTP/1.1\n"
            f"digest: {digest}"
        )
        signature = base64.b64encode(
            hmac.new(
                self.api_secret.encode(),
                origin.encode(),
                hashlib.sha256,
            ).digest()
        ).decode()
        authorization = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line digest", signature="{signature}"'
        )
        return {
            "Host": parsed.netloc,
            "Date": date,
            "Digest": digest,
            "Authorization": authorization,
            "Content-Type": "application/json",
        }

    async def embed(self, text: str, domain: str) -> np.ndarray:
        messages = json.dumps(
            {"messages": [{"content": text, "role": "user"}]},
            ensure_ascii=False,
        )
        encoded = base64.b64encode(messages.encode()).decode()
        payload = {
            "header": {
                "app_id": self.app_id,
                "uid": str(uuid.uuid4()),
                "status": 3,
            },
            "parameter": {
                "emb": {
                    "domain": domain,
                    "feature": {
                        "encoding": "utf8",
                        "compress": "raw",
                        "format": "plain",
                    },
                }
            },
            "payload": {
                "messages": {
                    "encoding": "utf8",
                    "compress": "raw",
                    "format": "json",
                    "status": 3,
                    "text": encoded,
                }
            },
        }
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        for attempt in range(self.max_retries):
            try:
                response = await self._http.post(
                    self.url,
                    headers=self._headers(body),
                    content=body,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in {500, 503}:
                    if attempt + 1 < self.max_retries:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                response.raise_for_status()
                result = response.json()
                header = result.get("header", {})
                if header.get("code") == 0:
                    raw = base64.b64decode(result["payload"]["feature"]["text"])
                    return np.frombuffer(raw, dtype="<f4").copy()
                break
            except httpx.TransportError:
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
            except (
                httpx.HTTPStatusError,
                AttributeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                break
        raise ProviderUnavailable(
            "EMBEDDING_UNAVAILABLE",
            "向量化服务暂时不可用",
        ) from None

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
