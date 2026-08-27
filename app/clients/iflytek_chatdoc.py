"""Async client for iFlytek ChatDoc managed knowledge bases.

ChatDoc authentication is MD5(appId + timestamp) followed by HmacSHA1.
It is intentionally separate from the Embedding API's HMAC-SHA256 scheme.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.errors import ProviderUnavailable


@dataclass(frozen=True)
class ChatDocSearchHit:
    content: str
    score: float
    file_id: str
    index: int
    retrieval_type: str


class IflytekChatDocClient:
    def __init__(
        self,
        *,
        app_id: str,
        api_secret: str,
        base_url: str = "https://chatdoc.xfyun.cn",
        timeout_seconds: float = 60.0,
        http: httpx.AsyncClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self.app_id = app_id
        self.api_secret = api_secret
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._http = http or httpx.AsyncClient()
        self._owns_http = http is None

    def auth_headers(self, now: datetime | None = None) -> dict[str, str]:
        current = now or datetime.now(timezone.utc)
        timestamp = str(int(current.timestamp()))
        auth = hashlib.md5((self.app_id + timestamp).encode()).hexdigest()
        digest = hmac.new(
            self.api_secret.encode(),
            auth.encode(),
            hashlib.sha1,
        ).digest()
        return {
            "appId": self.app_id,
            "timeStamp": timestamp,
            "signature": base64.b64encode(digest).decode(),
        }

    async def _request_json(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        business_code: str | None = None
        for attempt in range(self.max_retries):
            try:
                response = await self._http.post(
                    url,
                    headers=self.auth_headers(),
                    json=json_body,
                    data=data,
                    files=files,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt + 1 < self.max_retries:
                        await asyncio.sleep(0.4 * (attempt + 1))
                        continue
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("invalid ChatDoc business response")
                if payload.get("code") != 0:
                    raw_code = str(payload.get("code", ""))
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", raw_code):
                        business_code = raw_code
                    break
                return payload.get("data")
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
            except (TypeError, ValueError):
                break
        raise ProviderUnavailable(
            (
                f"CHATDOC_UNAVAILABLE_{business_code}"
                if business_code
                else "CHATDOC_UNAVAILABLE"
            ),
            "讯飞知识库服务暂时不可用",
        ) from None

    async def create_repo(self, name: str, description: str = "") -> str:
        data = await self._request_json(
            "/openapi/v1/repo/create",
            json_body={
                "repoName": name,
                "repoDesc": description,
                "repoTags": "粮食储藏,RAG",
            },
        )
        if not isinstance(data, str) or not data.strip():
            raise ProviderUnavailable(
                "CHATDOC_PROTOCOL_ERROR",
                "讯飞知识库响应格式无效",
            )
        return data.strip()

    async def upload_file(self, path: Path, *, upload_name: str | None = None) -> str:
        path = Path(path)
        name = upload_name or path.name
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            with path.open("rb") as stream:
                data = await self._request_json(
                    "/openapi/v1/file/upload",
                    data={
                        "fileType": "wiki",
                        "parseType": "AUTO",
                        "stepByStep": "false",
                    },
                    files={"file": (name, stream, content_type)},
                )
        except OSError as exc:
            raise ProviderUnavailable(
                "CHATDOC_UPLOAD_ERROR",
                "知识文件无法上传",
            ) from exc
        if not isinstance(data, dict):
            raise ProviderUnavailable(
                "CHATDOC_PROTOCOL_ERROR",
                "讯飞知识库响应格式无效",
            )
        file_id = data.get("fileId")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ProviderUnavailable(
                "CHATDOC_PROTOCOL_ERROR",
                "讯飞知识库响应格式无效",
            )
        return file_id.strip()

    async def file_statuses(self, file_ids: list[str]) -> dict[str, str]:
        if not file_ids:
            return {}
        data = await self._request_json(
            "/openapi/v1/file/status",
            data={"fileIds": ",".join(file_ids)},
        )
        if not isinstance(data, list):
            raise ProviderUnavailable(
                "CHATDOC_PROTOCOL_ERROR",
                "讯飞知识库响应格式无效",
            )
        statuses: dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                raise ProviderUnavailable(
                    "CHATDOC_PROTOCOL_ERROR",
                    "讯飞知识库响应格式无效",
                )
            file_id = item.get("fileId")
            status = item.get("fileStatus")
            if not isinstance(file_id, str) or not isinstance(status, str):
                raise ProviderUnavailable(
                    "CHATDOC_PROTOCOL_ERROR",
                    "讯飞知识库响应格式无效",
                )
            statuses[file_id] = status
        return statuses

    async def wait_until_vectored(
        self,
        file_ids: list[str],
        *,
        poll_interval_seconds: float = 3.0,
        max_polls: int = 200,
    ) -> dict[str, str]:
        expected = set(file_ids)
        for _ in range(max_polls):
            statuses = await self.file_statuses(file_ids)
            if any(status == "failed" for status in statuses.values()):
                raise ProviderUnavailable(
                    "CHATDOC_VECTORING_FAILED",
                    "讯飞知识库文档处理失败",
                )
            if expected and expected <= {
                file_id
                for file_id, status in statuses.items()
                if status == "vectored"
            }:
                return statuses
            await asyncio.sleep(poll_interval_seconds)
        raise ProviderUnavailable(
            "CHATDOC_VECTORING_TIMEOUT",
            "讯飞知识库文档处理超时",
        )

    async def add_files(self, repo_id: str, file_ids: list[str]) -> None:
        if not file_ids:
            return
        if len(file_ids) > 20:
            raise ValueError("ChatDoc accepts at most 20 files per add request")
        await self._request_json(
            "/openapi/v1/repo/file/add",
            json_body={"repoId": repo_id, "fileIds": file_ids},
        )

    async def search(
        self,
        *,
        repo_id: str,
        query: str,
        top_n: int,
    ) -> list[ChatDocSearchHit]:
        data = await self._request_json(
            "/openapi/v1/vector/search",
            json_body={
                "repoIds": [repo_id],
                "topN": top_n,
                "esTopN": top_n,
                "content": query,
                "es": True,
                "embedding": True,
                "reRank": True,
                "chatExtends": {"retrievalFilterPolicy": "REGULAR"},
            },
        )
        if not isinstance(data, list):
            raise ProviderUnavailable(
                "CHATDOC_PROTOCOL_ERROR",
                "讯飞知识库响应格式无效",
            )
        hits: list[ChatDocSearchHit] = []
        for item in data:
            try:
                if not isinstance(item, dict):
                    raise TypeError
                content = item["content"]
                score = float(item["score"])
                file_id = item["fileId"]
                index = int(item.get("index", 0))
                retrieval_type = str(item.get("type", "vector"))
                if not isinstance(content, str) or not content.strip():
                    raise ValueError
                if not isinstance(file_id, str) or not file_id.strip():
                    raise ValueError
            except (KeyError, TypeError, ValueError, OverflowError):
                raise ProviderUnavailable(
                    "CHATDOC_PROTOCOL_ERROR",
                    "讯飞知识库响应格式无效",
                ) from None
            hits.append(
                ChatDocSearchHit(
                    content=content.strip(),
                    score=score,
                    file_id=file_id.strip(),
                    index=index,
                    retrieval_type=retrieval_type,
                )
            )
        return hits

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
