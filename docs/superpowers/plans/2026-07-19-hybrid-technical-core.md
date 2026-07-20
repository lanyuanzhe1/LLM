# Hybrid Technical Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable grain-storage technical core in which a local FastAPI service calls the iFlytek Xingchen workflow, the workflow calls local domain tools, and those tools use iFlytek Embedding, the local vector store, and the fine-tuned MaaS model to return traceable answers.

**Architecture:** The Xingchen workflow is the top-level orchestrator. One local FastAPI process exposes both public `/v1/*` endpoints and authenticated `/tools/v1/*` endpoints; a request-scoped in-memory context joins tool results back to the public SSE stream. Cloud protocols are isolated behind three clients so offline tests can replace every external dependency.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pydantic-settings, HTTPX, websocket-client, NumPy, scikit-learn, pytest, pytest-asyncio.

## Global Constraints

- Use the `LLM` Conda environment for every command. On macOS use `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`; on Windows use `A:\Anaconda_envs\envs\LLM\python.exe`.
- Install packages only with the selected environment's `python -m pip`; never invoke plain `pip`.
- Keep Python compatible with 3.11.11 on Windows and 3.11.15 on macOS.
- Use scikit-learn `NearestNeighbors`; do not add FAISS.
- The v1 process runs with one Uvicorn worker because request citation context is in memory.
- The main path must exercise Xingchen Workflow Open API, iFlytek Embedding API, the local vector store, and the fine-tuned MaaS WebSocket API.
- All secrets come from environment variables. Do not add real credentials to source, tests, examples, logs, or documentation.
- Keep TLS certificate verification enabled for every HTTPS and WebSocket call.
- Every external request has an explicit timeout and maps provider failures to stable application error codes.
- Existing root scripts remain migration references; new application modules must not import their hard-coded globals.
- Unknown page, section, article, version, or authority metadata remains `null`/`unknown`; never synthesize source metadata.
- Do not add OCR, BM25, RRF, reranking, a database, a Web UI, a WeChat mini program, users, or long-term memory in this plan.
- Do not encode unsourced temperature, moisture, CO₂, fumigation, or pesticide thresholds.
- Preserve all unrelated user changes, including the current modifications to `AGENTS.md`, `CLAUDE.md`, `requirements.txt`, `chat_finetuned.py`, and temporary files.

## Accepted v1 Limitations

- The runtime vector store is currently absent in this checkout. Offline tests use fixtures; online end-to-end verification requires rebuilding `vector_store/`.
- Retrieval is dense cosine nearest-neighbor search only. `RETRIEVAL_MIN_SCORE=0.35` is a configurable starting threshold, not a validated domain metric.
- Citation validation is structural: it checks allowed evidence IDs, critical-sentence citations, and required sections. It does not claim expert-level semantic entailment.
- Tool-to-gateway citation correlation uses an in-memory TTL registry and therefore requires one process/replica.
- Xingchen platform creation and publication require the authenticated platform UI; repository artifacts define the exact node and parameter contract.

## File Responsibility Map

| Area | Files | Responsibility |
|---|---|---|
| Foundation | `requirements*.txt`, `.env.example`, `.gitignore`, `pytest.ini`, `app/core/*` | Dependencies, settings, stable errors |
| Contracts | `app/schemas/*`, `app/rag/evidence.py`, `app/core/request_context.py` | Public/tool schemas, evidence IDs, request correlation |
| Retrieval | `app/rag/vector_store.py`, `app/rag/retriever.py` | Load and search the current vector artifacts |
| Cloud clients | `app/clients/*` | Provider authentication, protocols, streaming, error mapping |
| Domain services | `app/services/*`, `app/domain/cases/*` | Prompt assembly, case completeness, citation validation |
| Tool API | `app/tools/routes.py`, `app/dependencies.py` | Xingchen-callable authenticated atomic tools |
| Public API | `app/api/*`, `app/main.py` | Workflow gateway, SSE, sources, health/readiness |
| Platform assets | `workflow/*`, `docs/星辰工作流联调指南.md` | Exact Xingchen node graph and publication procedure |
| Verification | `tests/unit`, `tests/contract`, `tests/integration`, `tests/online` | Offline and opt-in online evidence |

---

### Task 1: Application foundation, configuration, and stable errors

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `pytest.ini`
- Create: `app/__init__.py`
- Create: `app/core/__init__.py`
- Create: `app/core/config.py`
- Create: `app/core/errors.py`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_config.py`
- Create: `tests/unit/test_errors.py`

**Interfaces:**
- Consumes: environment variables listed in the approved design.
- Produces: `Settings`, `get_settings()`, `AppError`, `ConfigurationError`, `ProviderUnavailable`, `VectorStoreNotReady`.

- [ ] **Step 1: Add failing settings and error tests**

```python
# tests/unit/test_config.py
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings


REQUIRED_ENV = {
    "XF_APP_ID": "app-id",
    "XF_EMBEDDING_API_KEY": "embedding-key",
    "XF_EMBEDDING_API_SECRET": "embedding-secret",
    "XF_MAAS_API_KEY": "maas-key",
    "XF_MAAS_API_SECRET": "maas-secret",
    "XF_MAAS_RESOURCE_ID": "resource-id",
    "XF_MAAS_SERVICE_ID": "service-id",
    "XF_WORKFLOW_API_KEY": "workflow-key",
    "XF_WORKFLOW_API_SECRET": "workflow-secret",
    "XF_WORKFLOW_FLOW_ID": "flow-id",
    "TOOLS_SERVICE_TOKEN": "tool-token",
}


def test_settings_load_required_values(monkeypatch, tmp_path: Path):
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path))

    settings = Settings(_env_file=None)

    assert settings.xf_app_id == "app-id"
    assert settings.vector_store_dir == tmp_path
    assert settings.retrieval_min_score == 0.35
    assert settings.workflow_url.endswith("/workflow/v1/chat/completions")


def test_settings_reject_missing_secrets(monkeypatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

```python
# tests/unit/test_errors.py
from app.core.errors import ProviderUnavailable


def test_provider_error_has_stable_public_shape():
    error = ProviderUnavailable("MAAS_UNAVAILABLE", "模型暂时不可用")

    assert error.status_code == 502
    assert error.retryable is True
    assert error.to_dict() == {
        "code": "MAAS_UNAVAILABLE",
        "message": "模型暂时不可用",
        "retryable": True,
    }
```

- [ ] **Step 2: Run the focused tests and verify the package is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_config.py tests/unit/test_errors.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app'`.

- [ ] **Step 3: Add dependencies and test configuration**

Append these exact runtime lines to `requirements.txt`, preserving its existing lines:

```text
fastapi>=0.116,<1
uvicorn[standard]>=0.35,<1
pydantic>=2.11,<3
pydantic-settings>=2.10,<3
httpx>=0.28,<1
```

Create:

```text
# requirements-dev.txt
-r requirements.txt
pytest>=8.4,<9
pytest-asyncio>=1.1,<2
```

```ini
# pytest.ini
[pytest]
testpaths = tests
asyncio_mode = auto
markers =
    online: requires real iFlytek credentials and network access
```

```gitignore
# .gitignore
.env
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
```

```text
# .env.example
XF_APP_ID=
XF_EMBEDDING_API_KEY=
XF_EMBEDDING_API_SECRET=
XF_MAAS_API_KEY=
XF_MAAS_API_SECRET=
XF_MAAS_RESOURCE_ID=
XF_MAAS_SERVICE_ID=
XF_WORKFLOW_API_KEY=
XF_WORKFLOW_API_SECRET=
XF_WORKFLOW_FLOW_ID=
TOOLS_SERVICE_TOKEN=
VECTOR_STORE_DIR=vector_store
RETRIEVAL_MIN_SCORE=0.35
LOG_LEVEL=INFO
```

- [ ] **Step 4: Implement settings and errors**

```python
# app/core/config.py
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    xf_app_id: str
    xf_embedding_api_key: SecretStr
    xf_embedding_api_secret: SecretStr
    xf_maas_api_key: SecretStr
    xf_maas_api_secret: SecretStr
    xf_maas_resource_id: str
    xf_maas_service_id: str
    xf_workflow_api_key: SecretStr
    xf_workflow_api_secret: SecretStr
    xf_workflow_flow_id: str
    tools_service_token: SecretStr

    vector_store_dir: Path = Path("vector_store")
    retrieval_min_score: float = Field(default=0.35, ge=-1.0, le=1.0)
    log_level: str = "INFO"
    embedding_url: str = "https://emb-cn-huabei-1.xf-yun.com/"
    maas_url: str = "wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat"
    workflow_url: str = (
        "https://xingchen-api.xf-yun.com/workflow/v1/chat/completions"
    )
    embedding_timeout_seconds: float = 30.0
    maas_timeout_seconds: float = 60.0
    workflow_timeout_seconds: float = 120.0
    request_context_ttl_seconds: float = 300.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# app/core/errors.py
from typing import Any


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.details:
            payload["details"] = self.details
        return payload


class ConfigurationError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(
            "CONFIGURATION_ERROR", message, status_code=500, retryable=False
        )


class ProviderUnavailable(AppError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=502, retryable=True)


class VectorStoreNotReady(AppError):
    def __init__(self, message: str = "向量库尚未就绪") -> None:
        super().__init__(
            "VECTOR_STORE_NOT_READY", message, status_code=503, retryable=True
        )
```

Create `app/__init__.py`, `app/core/__init__.py`, `tests/__init__.py`, and `tests/unit/__init__.py` as empty files.

- [ ] **Step 5: Install dependencies and run the tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pip install -r requirements-dev.txt
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_config.py tests/unit/test_errors.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 1**

```bash
git add requirements.txt requirements-dev.txt .gitignore .env.example pytest.ini app tests/unit/test_config.py tests/unit/test_errors.py
git commit -m "build: add technical core foundation"
```

---

### Task 2: Shared API contracts, evidence identity, and request context

**Files:**
- Create: `app/schemas/__init__.py`
- Create: `app/schemas/api.py`
- Create: `app/schemas/tools.py`
- Create: `app/schemas/events.py`
- Create: `app/rag/__init__.py`
- Create: `app/rag/evidence.py`
- Create: `app/core/request_context.py`
- Create: `tests/unit/test_evidence.py`
- Create: `tests/unit/test_request_context.py`
- Create: `tests/unit/test_schemas.py`

**Interfaces:**
- Consumes: `Settings.request_context_ttl_seconds`.
- Produces: `Role`, `ChatRequest`, `CaseData`, `CaseAnalyzeRequest`, all four tool request/response types, `Evidence`, `build_evidence()`, and `RequestContextStore`.

- [ ] **Step 1: Write failing contract tests**

```python
# tests/unit/test_evidence.py
from app.rag.evidence import build_evidence


def test_evidence_id_is_stable_and_missing_metadata_is_explicit():
    metadata = {
        "text": "低温能够抑制储粮害虫活动。",
        "source": "其他论文/低温储粮技术.pdf",
        "start_pos": 100,
        "char_count": 15,
    }

    first = build_evidence(metadata, score=0.82)
    second = build_evidence(metadata, score=0.82)

    assert first.evidence_id == second.evidence_id
    assert first.page is None
    assert first.authority_level == "unknown"
    assert "metadata_incomplete" in first.quality_flags
```

```python
# tests/unit/test_request_context.py
import pytest

from app.core.request_context import RequestContextStore
from app.rag.evidence import Evidence


@pytest.mark.asyncio
async def test_context_round_trip_and_pop():
    store = RequestContextStore(ttl_seconds=300)
    evidence = Evidence(
        evidence_id="sha256:e1",
        document_id="sha256:d1",
        title="测试文档",
        source="测试文档.pdf",
        text="证据",
        score=0.9,
        authority_level="unknown",
    )

    await store.set_evidences("req-1", [evidence])
    await store.set_citations("req-1", ["sha256:e1"])

    context = await store.pop("req-1")
    assert context is not None
    assert context.evidences == [evidence]
    assert context.citation_ids == ["sha256:e1"]
    assert await store.pop("req-1") is None
```

```python
# tests/unit/test_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas.api import ChatRequest
from app.schemas.tools import RetrieveRequest


def test_chat_role_is_closed_enum():
    request = ChatRequest(message="你好", role="student")
    assert request.role.value == "student"

    with pytest.raises(ValidationError):
        ChatRequest(message="你好", role="administrator")


def test_retrieve_top_k_is_bounded():
    with pytest.raises(ValidationError):
        RetrieveRequest(request_id="req", query="问题", top_k=100)
```

- [ ] **Step 2: Run tests and verify imports fail**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_evidence.py tests/unit/test_request_context.py tests/unit/test_schemas.py -v
```

Expected: collection fails because `app.rag.evidence` and `app.schemas` do not exist.

- [ ] **Step 3: Implement the evidence and public schemas**

```python
# app/rag/evidence.py
import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    evidence_id: str
    document_id: str
    title: str
    source: str
    page: int | None = None
    section: str | None = None
    article_no: str | None = None
    text: str
    score: float
    authority_level: str = "unknown"
    version: str | None = None
    quality_flags: list[str] = Field(default_factory=list)


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def build_evidence(metadata: dict[str, Any], score: float) -> Evidence:
    source = str(metadata["source"])
    text = str(metadata["text"])
    start_pos = int(metadata.get("start_pos", 0))
    document_checksum = metadata.get("document_checksum")
    document_id = _sha256(f"{source}\n{document_checksum or ''}")
    evidence_id = _sha256(f"{document_id}\n{start_pos}\n{text}")
    optional = ("page", "section", "article_no", "version", "authority_level")
    flags = list(metadata.get("quality_flags", []))
    if any(metadata.get(key) in (None, "") for key in optional):
        flags.append("metadata_incomplete")
    return Evidence(
        evidence_id=evidence_id,
        document_id=document_id,
        title=str(metadata.get("title") or Path(source).stem),
        source=source,
        page=metadata.get("page"),
        section=metadata.get("section"),
        article_no=metadata.get("article_no"),
        text=text,
        score=score,
        authority_level=str(metadata.get("authority_level") or "unknown"),
        version=metadata.get("version"),
        quality_flags=sorted(set(flags)),
    )
```

```python
# app/schemas/api.py
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Role(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"
    RESEARCHER = "researcher"
    TECHNICIAN = "technician"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    role: Role = Role.STUDENT


class CaseData(BaseModel):
    grain_type: str | None = None
    storage_type: str | None = None
    moisture_percent: float | None = Field(default=None, ge=0, le=100)
    grain_temperature_c: float | None = Field(default=None, ge=-50, le=100)
    temperature_trend: Literal["rising", "stable", "falling"] | None = None
    ambient_temperature_c: float | None = Field(default=None, ge=-50, le=100)
    ambient_humidity_percent: float | None = Field(default=None, ge=0, le=100)
    co2_ppm: float | None = Field(default=None, ge=0)
    co2_trend: Literal["rising", "stable", "falling"] | None = None
    pest_signs: bool | None = None
    mold_signs: bool | None = None
    condensation_signs: bool | None = None
    storage_days: int | None = Field(default=None, ge=0)
    goal: str | None = Field(default=None, max_length=1000)


class CaseAnalyzeRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=128)
    user_id: str | None = Field(default=None, max_length=128)
    role: Role = Role.TECHNICIAN
    case: CaseData
```

- [ ] **Step 4: Implement tool schemas and SSE event models**

```python
# app/schemas/tools.py
from typing import Any

from pydantic import BaseModel, Field

from app.rag.evidence import Evidence
from app.schemas.api import CaseData, Role


class RetrievalFilters(BaseModel):
    source_type: str | None = None
    authority_level: str | None = None


class RetrieveRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=8000)
    top_k: int = Field(default=5, ge=1, le=20)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)


class RetrievalQuality(BaseModel):
    top_score: float
    sufficient: bool


class RetrieveResponse(BaseModel):
    request_id: str
    query: str
    evidences: list[Evidence]
    quality: RetrievalQuality


class GenerateRequest(BaseModel):
    request_id: str
    question: str
    role: Role = Role.STUDENT
    task_type: str = "knowledge_qa"
    evidences: list[Evidence] = Field(min_length=1, max_length=5)
    validation_feedback: list[str] = Field(default_factory=list)


class GenerationUsage(BaseModel):
    total_tokens: int = 0


class GenerateResponse(BaseModel):
    request_id: str
    answer: str
    cited_evidence_ids: list[str]
    usage: GenerationUsage = Field(default_factory=GenerationUsage)


class CaseEvaluateRequest(BaseModel):
    request_id: str
    case: CaseData


class RuleResult(BaseModel):
    rule_id: str
    conclusion: str
    evidence_ids: list[str]
    conditions: dict[str, Any]


class CaseEvaluateResponse(BaseModel):
    request_id: str
    needs_input: bool
    missing_fields: list[str]
    question: str | None = None
    rules: list[RuleResult] = Field(default_factory=list)


class CitationValidateRequest(BaseModel):
    request_id: str
    answer: str
    evidences: list[Evidence]


class CitationValidateResponse(BaseModel):
    request_id: str
    valid: bool
    errors: list[str]
    unsupported_sentences: list[str]
    citation_ids: list[str]
```

```python
# app/schemas/events.py
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.rag.evidence import Evidence


class WorkflowChoiceDelta(BaseModel):
    role: str = "assistant"
    content: str = ""


class WorkflowChoice(BaseModel):
    delta: WorkflowChoiceDelta
    index: int = 0
    finish_reason: str | None = None


class WorkflowFrame(BaseModel):
    code: int
    message: str
    id: str
    choices: list[WorkflowChoice] = Field(default_factory=list)
    usage: dict[str, int] | None = None


class ErrorEvent(BaseModel):
    code: str
    message: str
    retryable: bool


class DoneEvent(BaseModel):
    finish_reason: Literal["stop", "needs_input"] = "stop"
    missing_fields: list[str] = Field(default_factory=list)


def sse(event: str, data: BaseModel | dict[str, Any]) -> str:
    import json

    payload = data.model_dump(mode="json") if isinstance(data, BaseModel) else data
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
```

- [ ] **Step 5: Implement the TTL request context**

```python
# app/core/request_context.py
import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.rag.evidence import Evidence


@dataclass
class RequestContext:
    evidences: list[Evidence] = field(default_factory=list)
    citation_ids: list[str] = field(default_factory=list)
    needs_input: bool = False
    missing_fields: list[str] = field(default_factory=list)
    expires_at: float = 0.0


class RequestContextStore:
    def __init__(
        self,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._items: dict[str, RequestContext] = {}
        self._lock = asyncio.Lock()

    async def _get_or_create(self, request_id: str) -> RequestContext:
        now = self._clock()
        self._items = {
            key: value
            for key, value in self._items.items()
            if value.expires_at > now
        }
        context = self._items.get(request_id)
        if context is None:
            context = RequestContext(expires_at=now + self._ttl)
            self._items[request_id] = context
        return context

    async def set_evidences(
        self, request_id: str, evidences: list[Evidence]
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.evidences = list(evidences)

    async def set_citations(
        self, request_id: str, citation_ids: list[str]
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.citation_ids = list(citation_ids)

    async def set_case_result(
        self,
        request_id: str,
        *,
        needs_input: bool,
        missing_fields: list[str],
    ) -> None:
        async with self._lock:
            context = await self._get_or_create(request_id)
            context.needs_input = needs_input
            context.missing_fields = list(missing_fields)

    async def pop(self, request_id: str) -> RequestContext | None:
        async with self._lock:
            context = self._items.pop(request_id, None)
            if context is None or context.expires_at <= self._clock():
                return None
            return context
```

Create empty `app/schemas/__init__.py` and `app/rag/__init__.py`.

- [ ] **Step 6: Run the contract tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_evidence.py tests/unit/test_request_context.py tests/unit/test_schemas.py -v
```

Expected: `4 passed`.

- [ ] **Step 7: Commit Task 2**

```bash
git add app/schemas app/rag app/core/request_context.py tests/unit/test_evidence.py tests/unit/test_request_context.py tests/unit/test_schemas.py
git commit -m "feat: define technical core contracts"
```

---

### Task 3: Load and query the local vector store

**Files:**
- Create: `app/rag/vector_store.py`
- Create: `app/rag/retriever.py`
- Create: `tests/fixtures/vector_store/vectors.npy` during the test, not as a committed binary
- Create: `tests/unit/test_vector_store.py`
- Create: `tests/unit/test_retriever.py`

**Interfaces:**
- Consumes: `Evidence`, `RetrieveRequest`, and an embedding provider implementing `async embed(text: str, domain: str) -> np.ndarray`.
- Produces: `VectorStore.load()`, `VectorStore.search()`, `VectorStore.get_evidence()`, `Retriever.retrieve()`.

- [ ] **Step 1: Write failing vector store and retriever tests**

```python
# tests/unit/test_vector_store.py
import json
from pathlib import Path

import numpy as np
import pytest

from app.core.errors import VectorStoreNotReady
from app.rag.vector_store import VectorStore


def write_store(path: Path) -> None:
    path.mkdir()
    np.save(
        path / "vectors.npy",
        np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    (path / "chunks_metadata.json").write_text(
        json.dumps(
            [
                {"text": "低温储粮", "source": "a.pdf", "start_pos": 0},
                {"text": "害虫防治", "source": "b.pdf", "start_pos": 10},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_load_and_search_exact_cosine(tmp_path: Path):
    write_store(tmp_path)
    store = VectorStore.load(tmp_path)

    hits = store.search(np.array([0.9, 0.1], dtype=np.float32), top_k=1)

    assert hits[0].metadata["source"] == "a.pdf"
    assert hits[0].score > 0.9


def test_missing_store_is_readiness_error(tmp_path: Path):
    with pytest.raises(VectorStoreNotReady):
        VectorStore.load(tmp_path)
```

```python
# tests/unit/test_retriever.py
from pathlib import Path

import numpy as np
import pytest

from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.schemas.tools import RetrieveRequest
from tests.unit.test_vector_store import write_store


class FakeEmbedding:
    async def embed(self, text: str, domain: str) -> np.ndarray:
        assert domain == "query"
        return np.array([1.0, 0.0], dtype=np.float32)


@pytest.mark.asyncio
async def test_retriever_returns_evidence_and_quality(tmp_path: Path):
    write_store(tmp_path)
    retriever = Retriever(
        store=VectorStore.load(tmp_path),
        embedding=FakeEmbedding(),
        min_score=0.35,
    )

    response = await retriever.retrieve(
        RetrieveRequest(request_id="req", query="低温", top_k=1)
    )

    assert response.evidences[0].source == "a.pdf"
    assert response.quality.sufficient is True
```

- [ ] **Step 2: Run tests and verify the modules are absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_vector_store.py tests/unit/test_retriever.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.rag.vector_store'`.

- [ ] **Step 3: Implement vector loading, validation, and search**

```python
# app/rag/vector_store.py
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import normalize

from app.core.errors import VectorStoreNotReady
from app.rag.evidence import Evidence, build_evidence


@dataclass(frozen=True)
class SearchHit:
    index: int
    score: float
    metadata: dict[str, Any]


class VectorStore:
    def __init__(
        self,
        vectors: np.ndarray,
        metadata: list[dict[str, Any]],
    ) -> None:
        if vectors.ndim != 2 or vectors.shape[0] != len(metadata):
            raise VectorStoreNotReady("向量数量与知识块元数据不一致")
        self.vectors = normalize(vectors.astype(np.float32), norm="l2")
        self.metadata = metadata
        self.index = NearestNeighbors(metric="cosine", algorithm="brute")
        self.index.fit(self.vectors)
        self._evidence_by_id: dict[str, Evidence] = {}
        for item in metadata:
            evidence = build_evidence(item, score=0.0)
            self._evidence_by_id[evidence.evidence_id] = evidence

    @classmethod
    def load(cls, directory: Path) -> "VectorStore":
        vectors_path = directory / "vectors.npy"
        metadata_path = directory / "chunks_metadata.json"
        if not vectors_path.exists() or not metadata_path.exists():
            raise VectorStoreNotReady(
                f"缺少 {vectors_path.name} 或 {metadata_path.name}"
            )
        try:
            vectors = np.load(vectors_path, allow_pickle=False)
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise VectorStoreNotReady(f"向量库无法加载: {exc}") from exc
        if not isinstance(metadata, list):
            raise VectorStoreNotReady("知识块元数据必须是 JSON 数组")
        return cls(vectors=vectors, metadata=metadata)

    @property
    def dimension(self) -> int:
        return int(self.vectors.shape[1])

    def search(self, query_vector: np.ndarray, top_k: int) -> list[SearchHit]:
        vector = np.asarray(query_vector, dtype=np.float32).reshape(1, -1)
        if vector.shape[1] != self.dimension:
            raise VectorStoreNotReady(
                f"查询向量维度 {vector.shape[1]} 与索引维度 {self.dimension} 不一致"
            )
        count = min(top_k, len(self.metadata))
        distances, indices = self.index.kneighbors(vector, n_neighbors=count)
        return [
            SearchHit(
                index=int(index),
                score=1.0 - float(distance),
                metadata=self.metadata[int(index)],
            )
            for distance, index in zip(distances[0], indices[0])
        ]

    def get_evidence(self, evidence_id: str) -> Evidence | None:
        return self._evidence_by_id.get(evidence_id)
```

- [ ] **Step 4: Implement the retriever**

```python
# app/rag/retriever.py
from typing import Protocol

import numpy as np

from app.rag.evidence import build_evidence
from app.rag.vector_store import VectorStore
from app.schemas.tools import (
    RetrieveRequest,
    RetrieveResponse,
    RetrievalQuality,
)


class EmbeddingProvider(Protocol):
    async def embed(self, text: str, domain: str) -> np.ndarray: ...


class Retriever:
    def __init__(
        self,
        store: VectorStore,
        embedding: EmbeddingProvider,
        min_score: float,
    ) -> None:
        self.store = store
        self.embedding = embedding
        self.min_score = min_score

    async def retrieve(self, request: RetrieveRequest) -> RetrieveResponse:
        query_vector = await self.embedding.embed(request.query, domain="query")
        hits = self.store.search(query_vector, top_k=request.top_k)
        evidences = [build_evidence(hit.metadata, hit.score) for hit in hits]
        if request.filters.authority_level:
            evidences = [
                item
                for item in evidences
                if item.authority_level == request.filters.authority_level
            ]
        top_score = evidences[0].score if evidences else 0.0
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=evidences,
            quality=RetrievalQuality(
                top_score=top_score,
                sufficient=bool(evidences and top_score >= self.min_score),
            ),
        )
```

- [ ] **Step 5: Run retrieval tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_vector_store.py tests/unit/test_retriever.py -v
```

Expected: `3 passed`.

- [ ] **Step 6: Commit Task 3**

```bash
git add app/rag/vector_store.py app/rag/retriever.py tests/unit/test_vector_store.py tests/unit/test_retriever.py
git commit -m "feat: serve the local vector store"
```

---

### Task 4: iFlytek Embedding API adapter

**Files:**
- Create: `app/clients/__init__.py`
- Create: `app/clients/iflytek_embedding.py`
- Create: `tests/unit/test_iflytek_embedding.py`

**Interfaces:**
- Consumes: iFlytek application ID, Embedding API key/secret, HTTPS endpoint, timeout.
- Produces: `IflytekEmbeddingClient.embed(text: str, domain: str) -> np.ndarray` and `IflytekEmbeddingClient.close()`.

- [ ] **Step 1: Write failing signature, decode, and retry tests**

```python
# tests/unit/test_iflytek_embedding.py
import base64
import json

import httpx
import numpy as np
import pytest

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.core.errors import ProviderUnavailable


@pytest.mark.asyncio
async def test_embedding_request_has_digest_prefix_and_decodes_float32():
    seen: dict[str, str] = {}
    vector = np.array([0.25, 0.75], dtype="<f4")

    def handler(request: httpx.Request) -> httpx.Response:
        seen["digest"] = request.headers["Digest"]
        seen["authorization"] = request.headers["Authorization"]
        body = json.loads(request.content)
        assert body["parameter"]["emb"]["domain"] == "query"
        return httpx.Response(
            200,
            json={
                "header": {"code": 0, "message": "success"},
                "payload": {
                    "feature": {
                        "text": base64.b64encode(vector.tobytes()).decode()
                    }
                },
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://emb-cn-huabei-1.xf-yun.com/",
        timeout_seconds=1,
        http=http,
    )

    result = await client.embed("测试", domain="query")

    assert seen["digest"].startswith("SHA-256=")
    assert 'algorithm="hmac-sha256"' in seen["authorization"]
    np.testing.assert_allclose(result, vector)
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_retries_transient_503():
    attempts = 0
    vector = np.array([1.0, 0.0], dtype="<f4")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, text="temporary")
        return httpx.Response(
            200,
            json={
                "header": {"code": 0, "message": "success"},
                "payload": {
                    "feature": {
                        "text": base64.b64encode(vector.tobytes()).decode()
                    }
                },
            },
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=2,
    )

    result = await client.embed("测试", domain="query")

    assert attempts == 2
    np.testing.assert_allclose(result, vector)
    await http.aclose()


@pytest.mark.asyncio
async def test_embedding_maps_provider_code_to_stable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"header": {"code": 10001, "message": "bad request"}}
        )

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = IflytekEmbeddingClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        url="https://example.test/",
        timeout_seconds=1,
        http=http,
        max_retries=1,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.embed("测试", domain="query")

    assert exc.value.code == "EMBEDDING_UNAVAILABLE"
    await http.aclose()
```

- [ ] **Step 2: Run the tests and verify the adapter is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_embedding.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.clients'`.

- [ ] **Step 3: Implement the Embedding adapter**

```python
# app/clients/iflytek_embedding.py
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
        last_reason = "unknown error"
        for attempt in range(self.max_retries):
            try:
                response = await self._http.post(
                    self.url,
                    headers=self._headers(body),
                    content=body,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in {500, 503}:
                    last_reason = f"HTTP {response.status_code}"
                    if attempt + 1 < self.max_retries:
                        await asyncio.sleep(0.2 * (attempt + 1))
                        continue
                response.raise_for_status()
                result = response.json()
                header = result.get("header", {})
                if header.get("code") == 0:
                    raw = base64.b64decode(result["payload"]["feature"]["text"])
                    return np.frombuffer(raw, dtype="<f4").copy()
                last_reason = f"{header.get('code')}: {header.get('message')}"
                break
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_reason = type(exc).__name__
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(0.2 * (attempt + 1))
            except (httpx.HTTPStatusError, KeyError, ValueError) as exc:
                last_reason = str(exc)
                break
        raise ProviderUnavailable(
            "EMBEDDING_UNAVAILABLE",
            f"向量化服务暂时不可用 ({last_reason})",
        )

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
```

Create an empty `app/clients/__init__.py`.

- [ ] **Step 4: Run the adapter tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_embedding.py -v
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 4**

```bash
git add app/clients tests/unit/test_iflytek_embedding.py
git commit -m "feat: add iFlytek embedding adapter"
```

---

### Task 5: Fine-tuned MaaS adapter and evidence-constrained generation

**Files:**
- Create: `app/clients/iflytek_maas.py`
- Create: `app/services/__init__.py`
- Create: `app/services/generation.py`
- Create: `tests/unit/test_iflytek_maas.py`
- Create: `tests/unit/test_generation_service.py`

**Interfaces:**
- Consumes: `GenerateRequest`, MaaS credentials, resource ID, service ID.
- Produces: `MaaSResult`, `IflytekMaaSClient.generate()`, `GenerationService.generate()`.

- [ ] **Step 1: Write failing MaaS and generation tests**

```python
# tests/unit/test_iflytek_maas.py
import base64
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.clients.iflytek_maas import IflytekMaaSClient
from app.core.errors import ProviderUnavailable


class FakeTransport:
    def exchange(self, url: str, payload: dict, timeout: float):
        assert payload["header"]["patch_id"] == ["resource-id"]
        yield {
            "header": {"code": 0, "message": "Success", "status": 0},
            "payload": {
                "choices": {
                    "status": 0,
                    "text": [{"content": "结论", "role": "assistant", "index": 0}],
                }
            },
        }
        yield {
            "header": {"code": 0, "message": "Success", "status": 2},
            "payload": {
                "choices": {
                    "status": 2,
                    "text": [{"content": "[E1]", "role": "assistant", "index": 0}],
                },
                "usage": {"text": {"total_tokens": 12}},
            },
        }


class TimeoutTransport:
    def exchange(self, url: str, payload: dict, timeout: float):
        raise TimeoutError("timed out")
        yield


def test_auth_url_contains_base64_authorization():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://maas-api.cn-huabei-1.xf-yun.com/v1.1/chat",
        timeout_seconds=5,
        transport=FakeTransport(),
    )

    url = client.create_auth_url(datetime(2026, 7, 19, tzinfo=timezone.utc))
    auth = parse_qs(urlparse(url).query)["authorization"][0]
    decoded = base64.b64decode(auth).decode()
    assert 'api_key="key"' in decoded
    assert 'algorithm="hmac-sha256"' in decoded


@pytest.mark.asyncio
async def test_generate_joins_stream_and_usage():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=FakeTransport(),
    )

    result = await client.generate(
        [{"role": "user", "content": "问题"}], uid="req-1"
    )

    assert result.content == "结论[E1]"
    assert result.total_tokens == 12


@pytest.mark.asyncio
async def test_generate_maps_transport_timeout():
    client = IflytekMaaSClient(
        app_id="app",
        api_key="key",
        api_secret="secret",
        resource_id="resource-id",
        service_id="service-id",
        url="wss://example.test/v1.1/chat",
        timeout_seconds=5,
        transport=TimeoutTransport(),
    )

    with pytest.raises(ProviderUnavailable) as exc:
        await client.generate([{"role": "user", "content": "问题"}], uid="req")

    assert exc.value.code == "MAAS_UNAVAILABLE"
```

```python
# tests/unit/test_generation_service.py
import pytest

from app.clients.iflytek_maas import MaaSResult
from app.rag.evidence import Evidence
from app.schemas.tools import GenerateRequest
from app.services.generation import GenerationService


class FakeMaaS:
    async def generate(self, messages: list[dict[str, str]], uid: str) -> MaaSResult:
        assert "[E1]" in messages[-1]["content"]
        return MaaSResult(content="结论：低温可抑制害虫活动。[E1]", total_tokens=20)


@pytest.mark.asyncio
async def test_generation_maps_alias_to_real_evidence_id():
    evidence = Evidence(
        evidence_id="sha256:real-id",
        document_id="sha256:doc",
        title="低温储粮",
        source="paper.pdf",
        text="低温可抑制害虫活动。",
        score=0.9,
        authority_level="unknown",
    )
    service = GenerationService(FakeMaaS())

    response = await service.generate(
        GenerateRequest(
            request_id="req",
            question="低温储粮有什么作用？",
            evidences=[evidence],
        )
    )

    assert response.cited_evidence_ids == ["sha256:real-id"]
    assert response.usage.total_tokens == 20
```

- [ ] **Step 2: Run the tests and verify failures**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_maas.py tests/unit/test_generation_service.py -v
```

Expected: collection fails because the MaaS adapter and generation service do not exist.

- [ ] **Step 3: Implement the synchronous WebSocket transport and async MaaS client**

```python
# app/clients/iflytek_maas.py
import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Iterable, Protocol
from urllib.parse import urlencode, urlparse

import websocket

from app.core.errors import ProviderUnavailable


@dataclass(frozen=True)
class MaaSResult:
    content: str
    total_tokens: int


class MaaSTransport(Protocol):
    def exchange(
        self, url: str, payload: dict, timeout: float
    ) -> Iterable[dict]: ...


class WebSocketTransport:
    def exchange(
        self, url: str, payload: dict, timeout: float
    ) -> Iterable[dict]:
        connection = websocket.create_connection(url, timeout=timeout)
        try:
            connection.send(json.dumps(payload, ensure_ascii=False))
            while True:
                frame = json.loads(connection.recv())
                yield frame
                header_status = frame.get("header", {}).get("status")
                choice_status = (
                    frame.get("payload", {}).get("choices", {}).get("status")
                )
                if header_status == 2 or choice_status == 2:
                    break
        finally:
            connection.close()


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
    ) -> None:
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.resource_id = resource_id
        self.service_id = service_id
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.transport = transport or WebSocketTransport()

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
        return f"{self.url}?{urlencode({'authorization': authorization, 'date': date, 'host': parsed.netloc})}"

    def _generate_sync(
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
        total_tokens = 0
        try:
            for frame in self.transport.exchange(
                self.create_auth_url(), payload, self.timeout_seconds
            ):
                header = frame.get("header", {})
                if header.get("code") != 0:
                    raise ProviderUnavailable(
                        "MAAS_UNAVAILABLE",
                        f"模型服务错误 {header.get('code')}: {header.get('message')}",
                    )
                choices = frame.get("payload", {}).get("choices", {})
                for item in choices.get("text", []):
                    chunks.append(item.get("content", ""))
                usage = frame.get("payload", {}).get("usage", {}).get("text", {})
                total_tokens = int(usage.get("total_tokens", total_tokens))
        except ProviderUnavailable:
            raise
        except Exception as exc:
            raise ProviderUnavailable(
                "MAAS_UNAVAILABLE", f"模型服务暂时不可用 ({type(exc).__name__})"
            ) from exc
        return MaaSResult(content="".join(chunks), total_tokens=total_tokens)

    async def generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._generate_sync, messages, uid),
                timeout=self.timeout_seconds + 5,
            )
        except TimeoutError as exc:
            raise ProviderUnavailable(
                "MAAS_UNAVAILABLE", "模型服务请求超时"
            ) from exc
```

- [ ] **Step 4: Implement evidence-constrained prompt assembly**

```python
# app/services/generation.py
import re
from typing import Protocol

from app.clients.iflytek_maas import MaaSResult
from app.schemas.tools import (
    GenerateRequest,
    GenerateResponse,
    GenerationUsage,
)


class MaaSProvider(Protocol):
    async def generate(
        self, messages: list[dict[str, str]], uid: str
    ) -> MaaSResult: ...


SYSTEM_PROMPT = """你是粮食储藏领域专用智能体。
只能依据用户消息中的证据回答，不得补充证据中不存在的数值、条款或操作要求。
关键结论后必须使用 [E1]、[E2] 形式引用证据。
输出必须包含：结论、依据、适用条件、不确定性、来源。
证据不足时明确说明，不得猜测。"""


class GenerationService:
    def __init__(self, maas: MaaSProvider) -> None:
        self.maas = maas

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        aliases = {
            f"E{index}": evidence.evidence_id
            for index, evidence in enumerate(request.evidences, start=1)
        }
        evidence_text = "\n\n".join(
            f"[E{index}] {item.title}\n{item.text}"
            for index, item in enumerate(request.evidences, start=1)
        )
        feedback = (
            "\n上次校验问题：\n- " + "\n- ".join(request.validation_feedback)
            if request.validation_feedback
            else ""
        )
        user_prompt = (
            f"用户角色：{request.role.value}\n"
            f"任务类型：{request.task_type}\n"
            f"问题：{request.question}\n\n"
            f"证据：\n{evidence_text}{feedback}"
        )
        result = await self.maas.generate(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            uid=request.request_id,
        )
        cited_aliases = re.findall(r"\[(E\d+)\]", result.content)
        cited_ids = list(
            dict.fromkeys(aliases[alias] for alias in cited_aliases if alias in aliases)
        )
        return GenerateResponse(
            request_id=request.request_id,
            answer=result.content,
            cited_evidence_ids=cited_ids,
            usage=GenerationUsage(total_tokens=result.total_tokens),
        )
```

Create an empty `app/services/__init__.py`.

- [ ] **Step 5: Run MaaS and generation tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_maas.py tests/unit/test_generation_service.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit Task 5**

```bash
git add app/clients/iflytek_maas.py app/services tests/unit/test_iflytek_maas.py tests/unit/test_generation_service.py
git commit -m "feat: generate answers with the fine-tuned model"
```

---

### Task 6: Case completeness and structural citation validation

**Files:**
- Create: `app/domain/__init__.py`
- Create: `app/domain/cases/__init__.py`
- Create: `app/domain/cases/rules.py`
- Create: `app/services/citation_validation.py`
- Create: `tests/unit/test_case_rules.py`
- Create: `tests/unit/test_citation_validation.py`

**Interfaces:**
- Consumes: `CaseEvaluateRequest`, `CitationValidateRequest`.
- Produces: `CaseEvaluator.evaluate()` and `CitationValidator.validate()`.

- [ ] **Step 1: Write failing case and citation tests**

```python
# tests/unit/test_case_rules.py
from app.domain.cases.rules import CaseEvaluator
from app.schemas.api import CaseData
from app.schemas.tools import CaseEvaluateRequest


def test_case_evaluator_asks_only_for_required_base_fields():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=CaseData(grain_type="小麦", goal="判断霉变风险"),
        )
    )

    assert response.needs_input is True
    assert response.missing_fields == ["storage_type", "storage_days"]
    assert "仓型" in response.question


def test_case_evaluator_does_not_invent_threshold_rules():
    response = CaseEvaluator().evaluate(
        CaseEvaluateRequest(
            request_id="req",
            case=CaseData(
                grain_type="小麦",
                storage_type="平房仓",
                storage_days=60,
                goal="判断霉变风险",
            ),
        )
    )

    assert response.needs_input is False
    assert response.rules == []
```

```python
# tests/unit/test_citation_validation.py
from app.rag.evidence import Evidence
from app.schemas.tools import CitationValidateRequest
from app.services.citation_validation import CitationValidator


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="低温储粮",
    source="paper.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)


def test_valid_answer_requires_sections_and_allowed_alias():
    answer = """## 结论
低温能够抑制害虫活动。[E1]
## 依据
证据表明低温具有抑制作用。[E1]
## 适用条件
需结合粮种与仓储条件。
## 不确定性
知识库未提供统一温度阈值。
## 来源
[E1] 低温储粮"""
    response = CitationValidator().validate(
        CitationValidateRequest(
            request_id="req", answer=answer, evidences=[EVIDENCE]
        )
    )
    assert response.valid is True
    assert response.citation_ids == ["sha256:e1"]


def test_numeric_claim_without_citation_is_rejected():
    answer = """## 结论
温度必须保持在10℃。
## 依据
暂无。
## 适用条件
一般情况。
## 不确定性
暂无。
## 来源
暂无。"""
    response = CitationValidator().validate(
        CitationValidateRequest(
            request_id="req", answer=answer, evidences=[EVIDENCE]
        )
    )
    assert response.valid is False
    assert "温度必须保持在10℃。" in response.unsupported_sentences
```

- [ ] **Step 2: Run tests and verify the services are absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_case_rules.py tests/unit/test_citation_validation.py -v
```

Expected: collection fails because the case and citation modules do not exist.

- [ ] **Step 3: Implement case completeness without unsourced thresholds**

```python
# app/domain/cases/rules.py
from app.schemas.tools import CaseEvaluateRequest, CaseEvaluateResponse


BASE_FIELDS = ("grain_type", "storage_type", "storage_days", "goal")
FIELD_LABELS = {
    "grain_type": "粮种",
    "storage_type": "仓型与储藏方式",
    "storage_days": "储藏时间",
    "goal": "分析目标",
}


class CaseEvaluator:
    def evaluate(self, request: CaseEvaluateRequest) -> CaseEvaluateResponse:
        missing = [
            field
            for field in BASE_FIELDS
            if getattr(request.case, field) in (None, "")
        ]
        question = None
        if missing:
            labels = "、".join(FIELD_LABELS[field] for field in missing)
            question = f"请补充以下关键信息：{labels}。"
        return CaseEvaluateResponse(
            request_id=request.request_id,
            needs_input=bool(missing),
            missing_fields=missing,
            question=question,
            rules=[],
        )
```

- [ ] **Step 4: Implement deterministic citation validation**

```python
# app/services/citation_validation.py
import re

from app.schemas.tools import (
    CitationValidateRequest,
    CitationValidateResponse,
)


REQUIRED_SECTIONS = ("结论", "依据", "适用条件", "不确定性", "来源")
CRITICAL_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s*(?:℃|°C|%|ppm|天|小时|mg|kg))"
    r"|法律|法规|标准|条款|必须|禁止|应当"
    r"|药剂|熏蒸|通风|制冷|设备控制"
)
CITATION_PATTERN = re.compile(r"\[(E\d+)\]")
SENTENCE_PATTERN = re.compile(r"[^。！？\n]+[。！？]?")


class CitationValidator:
    def validate(
        self, request: CitationValidateRequest
    ) -> CitationValidateResponse:
        aliases = {
            f"E{index}": item.evidence_id
            for index, item in enumerate(request.evidences, start=1)
        }
        errors = [
            f"缺少必要章节：{section}"
            for section in REQUIRED_SECTIONS
            if section not in request.answer
        ]
        found_aliases = CITATION_PATTERN.findall(request.answer)
        invalid_aliases = sorted(set(found_aliases) - set(aliases))
        if invalid_aliases:
            errors.append(f"包含无效引用：{', '.join(invalid_aliases)}")
        unsupported: list[str] = []
        for sentence in SENTENCE_PATTERN.findall(request.answer):
            clean = sentence.strip()
            if clean and CRITICAL_PATTERN.search(clean) and not CITATION_PATTERN.search(
                clean
            ):
                unsupported.append(clean)
        if unsupported:
            errors.append("关键结论缺少引用")
        citation_ids = list(
            dict.fromkeys(aliases[item] for item in found_aliases if item in aliases)
        )
        if not citation_ids:
            errors.append("回答没有使用任何检索证据")
        return CitationValidateResponse(
            request_id=request.request_id,
            valid=not errors,
            errors=errors,
            unsupported_sentences=unsupported,
            citation_ids=citation_ids,
        )
```

Create empty `app/domain/__init__.py` and `app/domain/cases/__init__.py`.

- [ ] **Step 5: Run domain service tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_case_rules.py tests/unit/test_citation_validation.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit Task 6**

```bash
git add app/domain app/services/citation_validation.py tests/unit/test_case_rules.py tests/unit/test_citation_validation.py
git commit -m "feat: validate cases and answer citations"
```

---

### Task 7: Authenticated Xingchen tool API

**Files:**
- Create: `app/dependencies.py`
- Create: `app/tools/__init__.py`
- Create: `app/tools/routes.py`
- Create: `tests/contract/test_tool_api.py`

**Interfaces:**
- Consumes: `Retriever`, `GenerationService`, `CaseEvaluator`, `CitationValidator`, `RequestContextStore`, `Settings.tools_service_token`.
- Produces: a FastAPI router exposing the four `/tools/v1/*` contracts.

- [ ] **Step 1: Write failing tool authentication and persistence tests**

```python
# tests/contract/test_tool_api.py
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.rag.evidence import Evidence
from app.schemas.tools import (
    CitationValidateResponse,
    GenerateResponse,
    GenerationUsage,
    RetrievalQuality,
    RetrieveResponse,
)
from app.tools.routes import router


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="测试",
    source="test.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)


class FakeRetriever:
    async def retrieve(self, request):
        return RetrieveResponse(
            request_id=request.request_id,
            query=request.query,
            evidences=[EVIDENCE],
            quality=RetrievalQuality(top_score=0.9, sufficient=True),
        )


class FakeGeneration:
    async def generate(self, request):
        return GenerateResponse(
            request_id=request.request_id,
            answer="结论。[E1]",
            cited_evidence_ids=[EVIDENCE.evidence_id],
            usage=GenerationUsage(total_tokens=10),
        )


class FakeCases:
    def evaluate(self, request):
        from app.schemas.tools import CaseEvaluateResponse

        return CaseEvaluateResponse(
            request_id=request.request_id,
            needs_input=False,
            missing_fields=[],
            rules=[],
        )


class FakeValidator:
    def validate(self, request):
        return CitationValidateResponse(
            request_id=request.request_id,
            valid=True,
            errors=[],
            unsupported_sentences=[],
            citation_ids=[EVIDENCE.evidence_id],
        )


def make_client() -> tuple[TestClient, RequestContextStore]:
    contexts = RequestContextStore(ttl_seconds=300)
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        tools_service_token=SimpleNamespace(
            get_secret_value=lambda: "tool-token"
        )
    )
    app.state.container = ServiceContainer(
        retriever=FakeRetriever(),
        generation=FakeGeneration(),
        cases=FakeCases(),
        citations=FakeValidator(),
        contexts=contexts,
        vector_store=None,
        workflow=None,
    )
    app.include_router(router)
    return TestClient(app), contexts


def test_tools_reject_missing_token():
    client, _ = make_client()
    response = client.post(
        "/tools/v1/retrieve",
        json={"request_id": "req", "query": "低温", "top_k": 1},
    )
    assert response.status_code == 401


def test_retrieve_and_validate_store_request_context():
    client, contexts = make_client()
    headers = {"Authorization": "Bearer tool-token"}
    with client:
        retrieved = client.post(
            "/tools/v1/retrieve",
            headers=headers,
            json={"request_id": "req", "query": "低温", "top_k": 1},
        )
        validated = client.post(
            "/tools/v1/citations/validate",
            headers=headers,
            json={
                "request_id": "req",
                "answer": "结论。[E1]",
                "evidences": [EVIDENCE.model_dump()],
            },
        )

        assert retrieved.status_code == 200
        assert validated.status_code == 200
        context = client.portal.call(contexts.pop, "req")
        assert context.evidences == [EVIDENCE]
        assert context.citation_ids == [EVIDENCE.evidence_id]
```

- [ ] **Step 2: Run the contract tests and verify failures**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_tool_api.py -v
```

Expected: collection fails because `app.dependencies` and `app.tools.routes` do not exist.

- [ ] **Step 3: Implement the service container**

```python
# app/dependencies.py
from dataclasses import dataclass
from typing import Any

from app.core.request_context import RequestContextStore
from app.rag.vector_store import VectorStore


@dataclass
class ServiceContainer:
    retriever: Any
    generation: Any
    cases: Any
    citations: Any
    contexts: RequestContextStore
    vector_store: VectorStore | None
    workflow: Any
```

- [ ] **Step 4: Implement token authentication and four tool routes**

```python
# app/tools/routes.py
import secrets

from fastapi import APIRouter, Header, HTTPException, Request

from app.schemas.tools import (
    CaseEvaluateRequest,
    CaseEvaluateResponse,
    CitationValidateRequest,
    CitationValidateResponse,
    GenerateRequest,
    GenerateResponse,
    RetrieveRequest,
    RetrieveResponse,
)


router = APIRouter(prefix="/tools/v1", tags=["xingchen-tools"])


def _authorize(request: Request, authorization: str | None) -> None:
    expected = (
        "Bearer "
        + request.app.state.settings.tools_service_token.get_secret_value()
    )
    if authorization is None or not secrets.compare_digest(
        authorization, expected
    ):
        raise HTTPException(status_code=401, detail="invalid tool token")


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    payload: RetrieveRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> RetrieveResponse:
    _authorize(request, authorization)
    response = await request.app.state.container.retriever.retrieve(payload)
    await request.app.state.container.contexts.set_evidences(
        payload.request_id, response.evidences
    )
    return response


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    payload: GenerateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> GenerateResponse:
    _authorize(request, authorization)
    return await request.app.state.container.generation.generate(payload)


@router.post("/cases/evaluate", response_model=CaseEvaluateResponse)
async def evaluate_case(
    payload: CaseEvaluateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> CaseEvaluateResponse:
    _authorize(request, authorization)
    response = request.app.state.container.cases.evaluate(payload)
    await request.app.state.container.contexts.set_case_result(
        payload.request_id,
        needs_input=response.needs_input,
        missing_fields=response.missing_fields,
    )
    return response


@router.post("/citations/validate", response_model=CitationValidateResponse)
async def validate_citations(
    payload: CitationValidateRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> CitationValidateResponse:
    _authorize(request, authorization)
    response = request.app.state.container.citations.validate(payload)
    await request.app.state.container.contexts.set_citations(
        payload.request_id, response.citation_ids
    )
    return response
```

Create an empty `app/tools/__init__.py`.

- [ ] **Step 5: Run tool API tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_tool_api.py -v
```

Expected: `2 passed`.

- [ ] **Step 6: Commit Task 7**

```bash
git add app/dependencies.py app/tools tests/contract/test_tool_api.py
git commit -m "feat: expose authenticated Xingchen tools"
```

---

### Task 8: Xingchen Workflow Open API streaming client

**Files:**
- Create: `app/clients/xingchen_workflow.py`
- Create: `tests/unit/test_xingchen_workflow.py`

**Interfaces:**
- Consumes: Workflow API key/secret, flow ID, URL, start-node parameters.
- Produces: `XingchenWorkflowClient.stream(parameters, uid) -> AsyncIterator[WorkflowFrame]` and `close()`.

- [ ] **Step 1: Write failing request and frame parsing tests**

```python
# tests/unit/test_xingchen_workflow.py
import json

import httpx
import pytest

from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.errors import ProviderUnavailable


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


@pytest.mark.asyncio
async def test_workflow_sends_bearer_and_parses_stream_lines():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        body = "\n".join(
            [json.dumps(frame("你好，")), json.dumps(frame("世界", "stop"))]
        )
        return httpx.Response(200, text=body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XingchenWorkflowClient(
        api_key="key",
        api_secret="secret",
        flow_id="flow",
        url="https://example.test/workflow",
        timeout_seconds=5,
        http=http,
    )

    frames = [
        item
        async for item in client.stream(
            {"AGENT_USER_INPUT": "你好"}, uid="user"
        )
    ]

    assert seen["authorization"] == "Bearer key:secret"
    assert seen["body"]["flow_id"] == "flow"
    assert "".join(item.choices[0].delta.content for item in frames) == "你好，世界"
    await http.aclose()


@pytest.mark.asyncio
async def test_workflow_nonzero_code_is_stable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=json.dumps(frame("", "stop", 22302)))

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = XingchenWorkflowClient(
        api_key="key",
        api_secret="secret",
        flow_id="flow",
        url="https://example.test/workflow",
        timeout_seconds=5,
        http=http,
    )

    with pytest.raises(ProviderUnavailable) as exc:
        async for _ in client.stream({"AGENT_USER_INPUT": "x"}, uid="user"):
            pass

    assert exc.value.code == "WORKFLOW_UNAVAILABLE"
    await http.aclose()
```

- [ ] **Step 2: Run tests and verify the client is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_xingchen_workflow.py -v
```

Expected: collection fails because `app.clients.xingchen_workflow` does not exist.

- [ ] **Step 3: Implement the streaming Workflow client**

```python
# app/clients/xingchen_workflow.py
import json
from collections.abc import AsyncIterator

import httpx

from app.core.errors import ProviderUnavailable
from app.schemas.events import WorkflowFrame


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
    ) -> None:
        self.authorization = f"Bearer {api_key}:{api_secret}"
        self.flow_id = flow_id
        self.url = url
        self.timeout_seconds = timeout_seconds
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
        try:
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
                async for line in response.aiter_lines():
                    value = line.strip()
                    if not value:
                        continue
                    if value.startswith("data:"):
                        value = value[5:].strip()
                    frame = WorkflowFrame.model_validate_json(value)
                    if frame.code != 0:
                        raise ProviderUnavailable(
                            "WORKFLOW_UNAVAILABLE",
                            f"智能体工作流错误 {frame.code}: {frame.message}",
                        )
                    yield frame
        except ProviderUnavailable:
            raise
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            raise ProviderUnavailable(
                "WORKFLOW_UNAVAILABLE",
                f"智能体工作流暂时不可用 ({type(exc).__name__})",
            ) from exc

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()
```

- [ ] **Step 4: Run Workflow client tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_xingchen_workflow.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 8**

```bash
git add app/clients/xingchen_workflow.py tests/unit/test_xingchen_workflow.py
git commit -m "feat: stream Xingchen workflow responses"
```

---

### Task 9: Convert Workflow frames into the public SSE contract

**Files:**
- Create: `app/services/workflow_gateway.py`
- Create: `tests/integration/test_workflow_gateway.py`

**Interfaces:**
- Consumes: `XingchenWorkflowClient.stream()`, `RequestContextStore`, `ChatRequest`, `CaseAnalyzeRequest`.
- Produces: `WorkflowGateway.stream()` yielding only `meta`, `delta`, `citations`, `done`, and `error` SSE events.

- [ ] **Step 1: Write failing SSE correlation and failure tests**

```python
# tests/integration/test_workflow_gateway.py
import pytest

from app.core.errors import ProviderUnavailable
from app.core.request_context import RequestContextStore
from app.rag.evidence import Evidence
from app.schemas.api import Role
from app.schemas.events import WorkflowFrame
from app.services.workflow_gateway import WorkflowGateway


EVIDENCE = Evidence(
    evidence_id="sha256:e1",
    document_id="sha256:d1",
    title="低温储粮",
    source="paper.pdf",
    text="低温能够抑制害虫活动。",
    score=0.9,
    authority_level="unknown",
)


class FakeWorkflow:
    async def stream(self, parameters: dict, uid: str):
        assert parameters["REQUEST_ID"] == "req-1"
        yield WorkflowFrame.model_validate(
            {
                "code": 0,
                "message": "Success",
                "id": "sid",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "回答"},
                        "finish_reason": None,
                    }
                ],
            }
        )
        yield WorkflowFrame.model_validate(
            {
                "code": 0,
                "message": "Success",
                "id": "sid",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
            }
        )


class FailingWorkflow:
    async def stream(self, parameters: dict, uid: str):
        raise ProviderUnavailable(
            "WORKFLOW_UNAVAILABLE", "智能体工作流暂时不可用"
        )
        yield


@pytest.mark.asyncio
async def test_gateway_emits_citations_after_deltas():
    contexts = RequestContextStore(ttl_seconds=300)
    await contexts.set_evidences("req-1", [EVIDENCE])
    await contexts.set_citations("req-1", [EVIDENCE.evidence_id])
    gateway = WorkflowGateway(
        workflow=FakeWorkflow(),
        contexts=contexts,
        id_factory=lambda: "req-1",
    )

    events = [
        event
        async for event in gateway.stream(
            message="低温储粮",
            session_id=None,
            user_id=None,
            role=Role.STUDENT,
            task_type="knowledge_qa",
        )
    ]
    body = "".join(events)

    assert body.index("event: meta") < body.index("event: delta")
    assert body.index("event: delta") < body.index("event: citations")
    assert body.index("event: citations") < body.index("event: done")
    assert "sha256:e1" in body


@pytest.mark.asyncio
async def test_gateway_maps_provider_failure_to_error_event():
    gateway = WorkflowGateway(
        workflow=FailingWorkflow(),
        contexts=RequestContextStore(ttl_seconds=300),
        id_factory=lambda: "req-1",
    )

    body = "".join(
        [
            event
            async for event in gateway.stream(
                message="问题",
                session_id=None,
                user_id=None,
                role=Role.STUDENT,
                task_type="knowledge_qa",
            )
        ]
    )

    assert "event: error" in body
    assert "WORKFLOW_UNAVAILABLE" in body
    assert "event: done" not in body
```

- [ ] **Step 2: Run tests and verify the gateway is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/integration/test_workflow_gateway.py -v
```

Expected: collection fails because `app.services.workflow_gateway` does not exist.

- [ ] **Step 3: Implement Workflow-to-SSE conversion**

```python
# app/services/workflow_gateway.py
import json
import uuid
from collections.abc import AsyncIterator, Callable

from app.core.errors import AppError
from app.core.request_context import RequestContextStore
from app.schemas.api import CaseData, Role
from app.schemas.events import DoneEvent, ErrorEvent, sse


class WorkflowGateway:
    def __init__(
        self,
        *,
        workflow,
        contexts: RequestContextStore,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self.workflow = workflow
        self.contexts = contexts
        self.id_factory = id_factory

    async def stream(
        self,
        *,
        message: str,
        request_id: str | None = None,
        session_id: str | None,
        user_id: str | None,
        role: Role,
        task_type: str,
        case: CaseData | None = None,
    ) -> AsyncIterator[str]:
        request_id = request_id or self.id_factory()
        resolved_session_id = session_id or str(uuid.uuid4())
        uid = (user_id or resolved_session_id)[:128]
        yield sse(
            "meta",
            {
                "request_id": request_id,
                "session_id": resolved_session_id,
            },
        )
        parameters = {
            "AGENT_USER_INPUT": message,
            "REQUEST_ID": request_id,
            "SESSION_ID": resolved_session_id,
            "USER_ROLE": role.value,
            "TASK_TYPE": task_type,
            "CASE_JSON": (
                json.dumps(case.model_dump(mode="json"), ensure_ascii=False)
                if case is not None
                else ""
            ),
        }
        try:
            async for frame in self.workflow.stream(parameters, uid=uid):
                for choice in frame.choices:
                    if choice.delta.content:
                        yield sse("delta", {"content": choice.delta.content})
            context = await self.contexts.pop(request_id)
            evidences = context.evidences if context else []
            citation_ids = set(context.citation_ids if context else [])
            citations = [
                item for item in evidences if item.evidence_id in citation_ids
            ]
            yield sse(
                "citations",
                {"items": [item.model_dump(mode="json") for item in citations]},
            )
            needs_input = bool(context and context.needs_input)
            yield sse(
                "done",
                DoneEvent(
                    finish_reason="needs_input" if needs_input else "stop",
                    missing_fields=context.missing_fields if context else [],
                ),
            )
        except AppError as exc:
            await self.contexts.pop(request_id)
            yield sse(
                "error",
                ErrorEvent(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
```

- [ ] **Step 4: Run gateway tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/integration/test_workflow_gateway.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit Task 9**

```bash
git add app/services/workflow_gateway.py tests/integration/test_workflow_gateway.py
git commit -m "feat: expose a stable workflow event stream"
```

---

### Task 10: Assemble the FastAPI application and public endpoints

**Files:**
- Create: `app/api/__init__.py`
- Create: `app/api/chat.py`
- Create: `app/api/cases.py`
- Create: `app/api/sources.py`
- Create: `app/api/health.py`
- Create: `app/core/observability.py`
- Create: `app/main.py`
- Create: `tests/contract/test_public_api.py`

**Interfaces:**
- Consumes: all clients and services from Tasks 1–9.
- Produces: `create_app()`, `POST /v1/chat`, `POST /v1/cases/analyze`, `GET /v1/sources/{evidence_id}`, `GET /health`, and `GET /ready`.

- [ ] **Step 1: Write failing public API tests**

```python
# tests/contract/test_public_api.py
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.main import create_app
from app.schemas.events import WorkflowFrame


class FakeWorkflow:
    async def stream(self, parameters: dict, uid: str):
        yield WorkflowFrame.model_validate(
            {
                "code": 0,
                "message": "Success",
                "id": "sid",
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "回答"},
                        "finish_reason": "stop",
                    }
                ],
            }
        )


def make_client(vector_store=None) -> TestClient:
    container = ServiceContainer(
        retriever=None,
        generation=None,
        cases=None,
        citations=None,
        contexts=RequestContextStore(ttl_seconds=300),
        vector_store=vector_store,
        workflow=FakeWorkflow(),
    )
    settings = SimpleNamespace(
        tools_service_token=SimpleNamespace(
            get_secret_value=lambda: "tool-token"
        )
    )
    return TestClient(create_app(settings=settings, container=container))


def test_health_is_live_and_ready_reports_missing_store():
    client = make_client()
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready")
    assert ready.status_code == 503
    assert ready.json()["code"] == "VECTOR_STORE_NOT_READY"


def test_chat_uses_sse_contract():
    client = make_client()
    response = client.post(
        "/v1/chat",
        json={"message": "低温储粮", "role": "student"},
        headers={"X-Request-ID": "req-test"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in response.text
    assert "event: delta" in response.text
    assert "event: citations" in response.text
    assert "event: done" in response.text
    assert '"request_id": "req-test"' in response.text


def test_case_endpoint_uses_same_stream():
    client = make_client()
    response = client.post(
        "/v1/cases/analyze",
        json={
            "role": "technician",
            "case": {
                "grain_type": "小麦",
                "storage_type": "平房仓",
                "storage_days": 60,
                "goal": "判断霉变风险",
            },
        },
    )
    assert response.status_code == 200
    assert "event: done" in response.text
```

- [ ] **Step 2: Run tests and verify the application is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_public_api.py -v
```

Expected: collection fails because `app.main` does not exist.

- [ ] **Step 3: Implement public routes**

```python
# app/api/chat.py
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import ChatRequest
from app.services.workflow_gateway import WorkflowGateway


router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat")
async def chat(payload: ChatRequest, request: Request) -> StreamingResponse:
    container = request.app.state.container
    gateway = WorkflowGateway(
        workflow=container.workflow,
        contexts=container.contexts,
    )
    return StreamingResponse(
        gateway.stream(
            message=payload.message,
            request_id=request.state.request_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            role=payload.role,
            task_type="knowledge_qa",
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

```python
# app/api/cases.py
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import CaseAnalyzeRequest
from app.services.workflow_gateway import WorkflowGateway


router = APIRouter(prefix="/v1/cases", tags=["cases"])


@router.post("/analyze")
async def analyze(
    payload: CaseAnalyzeRequest, request: Request
) -> StreamingResponse:
    container = request.app.state.container
    gateway = WorkflowGateway(
        workflow=container.workflow,
        contexts=container.contexts,
    )
    return StreamingResponse(
        gateway.stream(
            message=payload.case.goal or "分析储粮安全案例",
            request_id=request.state.request_id,
            session_id=payload.session_id,
            user_id=payload.user_id,
            role=payload.role,
            task_type="case_analysis",
            case=payload.case,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

```python
# app/api/sources.py
from fastapi import APIRouter, HTTPException, Request

from app.rag.evidence import Evidence


router = APIRouter(prefix="/v1/sources", tags=["sources"])


@router.get("/{evidence_id}", response_model=Evidence)
async def source(evidence_id: str, request: Request) -> Evidence:
    store = request.app.state.container.vector_store
    evidence = store.get_evidence(evidence_id) if store is not None else None
    if evidence is None:
        raise HTTPException(status_code=404, detail="EVIDENCE_NOT_FOUND")
    return evidence
```

```python
# app/api/health.py
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse


router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request):
    store = request.app.state.container.vector_store
    if store is None:
        return JSONResponse(
            status_code=503,
            content={
                "code": "VECTOR_STORE_NOT_READY",
                "message": "向量库尚未就绪",
                "retryable": True,
            },
        )
    return {
        "status": "ready",
        "vectors": len(store.metadata),
        "dimension": store.dimension,
    }
```

- [ ] **Step 4: Implement application assembly and lifecycle**

```python
# app/core/observability.py
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


logger = logging.getLogger("grain_core.http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return response
```

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import cases, chat, health, sources
from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.clients.iflytek_maas import IflytekMaaSClient
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.config import Settings, get_settings
from app.core.errors import AppError, VectorStoreNotReady
from app.core.observability import RequestIdMiddleware
from app.core.request_context import RequestContextStore
from app.dependencies import ServiceContainer
from app.domain.cases.rules import CaseEvaluator
from app.rag.retriever import Retriever
from app.rag.vector_store import VectorStore
from app.services.citation_validation import CitationValidator
from app.services.generation import GenerationService
from app.tools.routes import router as tools_router


class UnavailableRetriever:
    def __init__(self, error: VectorStoreNotReady) -> None:
        self.error = error

    async def retrieve(self, request):
        raise self.error


def build_container(settings: Settings):
    embedding = IflytekEmbeddingClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_embedding_api_key.get_secret_value(),
        api_secret=settings.xf_embedding_api_secret.get_secret_value(),
        url=settings.embedding_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    try:
        store = VectorStore.load(settings.vector_store_dir)
        retriever = Retriever(
            store=store,
            embedding=embedding,
            min_score=settings.retrieval_min_score,
        )
    except VectorStoreNotReady as exc:
        store = None
        retriever = UnavailableRetriever(exc)
    maas = IflytekMaaSClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_maas_api_key.get_secret_value(),
        api_secret=settings.xf_maas_api_secret.get_secret_value(),
        resource_id=settings.xf_maas_resource_id,
        service_id=settings.xf_maas_service_id,
        url=settings.maas_url,
        timeout_seconds=settings.maas_timeout_seconds,
    )
    workflow = XingchenWorkflowClient(
        api_key=settings.xf_workflow_api_key.get_secret_value(),
        api_secret=settings.xf_workflow_api_secret.get_secret_value(),
        flow_id=settings.xf_workflow_flow_id,
        url=settings.workflow_url,
        timeout_seconds=settings.workflow_timeout_seconds,
    )
    container = ServiceContainer(
        retriever=retriever,
        generation=GenerationService(maas),
        cases=CaseEvaluator(),
        citations=CitationValidator(),
        contexts=RequestContextStore(settings.request_context_ttl_seconds),
        vector_store=store,
        workflow=workflow,
    )
    return container, (embedding, workflow)


def create_app(
    *,
    settings=None,
    container: ServiceContainer | None = None,
) -> FastAPI:
    resolved_settings = settings

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal resolved_settings, container
        resolved_settings = resolved_settings or get_settings()
        app.state.settings = resolved_settings
        if container is None:
            app.state.container, closeables = build_container(resolved_settings)
        else:
            app.state.container = container
            closeables = ()
        yield
        for item in closeables:
            await item.close()

    app = FastAPI(title="粮储智研助手技术实体", lifespan=lifespan)
    if resolved_settings is not None:
        app.state.settings = resolved_settings
    if container is not None:
        app.state.container = container
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(cases.router)
    app.include_router(sources.router)
    app.include_router(tools_router)
    return app


app = create_app()
```

Create an empty `app/api/__init__.py`.

- [ ] **Step 5: Run all offline tests**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -v
```

Expected: all offline tests pass and no test performs a real network request.

- [ ] **Step 6: Start one local worker and inspect OpenAPI**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

In another terminal:

```bash
curl -s http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
```

Expected:

```text
{"status":"ok"}
HTTP/1.1 503 Service Unavailable
```

The `503` is expected until `vector_store/` is rebuilt.

- [ ] **Step 7: Commit Task 10**

```bash
git add app/api app/main.py tests/contract/test_public_api.py
git commit -m "feat: assemble the technical core API"
```

---

### Task 11: Xingchen workflow assets, online smoke tests, and operator guide

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `build_vector_store.py`
- Create: `workflow/tool_contracts.json`
- Create: `workflow/README.md`
- Create: `docs/星辰工作流联调指南.md`
- Create: `tests/contract/test_workflow_assets.py`
- Create: `tests/unit/test_build_script_config.py`
- Create: `tests/online/test_cloud_services.py`
- Create: `tests/online/test_end_to_end.py`

**Interfaces:**
- Consumes: the four tool APIs, the six workflow start parameters, the three real cloud clients, and a public HTTPS tool base URL.
- Produces: an exact Xingchen build contract, opt-in online verification, and operator commands for the complete technical entity.

- [ ] **Step 1: Write the failing workflow asset contract test**

```python
# tests/contract/test_workflow_assets.py
import json
from pathlib import Path


def test_workflow_contract_has_exact_inputs_and_tools():
    contract = json.loads(
        Path("workflow/tool_contracts.json").read_text(encoding="utf-8")
    )
    assert contract["start_parameters"] == [
        "AGENT_USER_INPUT",
        "REQUEST_ID",
        "SESSION_ID",
        "USER_ROLE",
        "TASK_TYPE",
        "CASE_JSON",
    ]
    assert [tool["path"] for tool in contract["tools"]] == [
        "/tools/v1/retrieve",
        "/tools/v1/generate",
        "/tools/v1/cases/evaluate",
        "/tools/v1/citations/validate",
    ]
    assert all(tool["method"] == "POST" for tool in contract["tools"])
    assert contract["authentication"]["header"] == "Authorization"
    assert contract["authentication"]["value"] == "Bearer ${TOOLS_SERVICE_TOKEN}"
```

```python
# tests/unit/test_build_script_config.py
from pathlib import Path


def test_vector_build_reads_credentials_from_environment():
    source = Path("build_vector_store.py").read_text(encoding="utf-8")
    assert 'APP_ID = "5c75015a"' not in source
    assert "XF_APP_ID" in source
    assert "XF_EMBEDDING_API_KEY" in source
    assert "XF_EMBEDDING_API_SECRET" in source
    assert "SKIP_VECTOR_SEARCH" in source
```

- [ ] **Step 2: Run the contract test and verify the asset is absent**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_workflow_assets.py tests/unit/test_build_script_config.py -v
```

Expected: one failure for missing `workflow/tool_contracts.json` and one failure because the build script still contains embedded credentials.

- [ ] **Step 3: Create the machine-readable workflow contract**

```json
{
  "name": "粮储智研助手技术实体_v1",
  "start_parameters": [
    "AGENT_USER_INPUT",
    "REQUEST_ID",
    "SESSION_ID",
    "USER_ROLE",
    "TASK_TYPE",
    "CASE_JSON"
  ],
  "authentication": {
    "header": "Authorization",
    "value": "Bearer ${TOOLS_SERVICE_TOKEN}"
  },
  "tools": [
    {
      "name": "grain_retrieve",
      "method": "POST",
      "path": "/tools/v1/retrieve",
      "request_fields": ["request_id", "query", "top_k", "filters"],
      "response_fields": ["request_id", "query", "evidences", "quality"]
    },
    {
      "name": "grain_generate",
      "method": "POST",
      "path": "/tools/v1/generate",
      "request_fields": [
        "request_id",
        "question",
        "role",
        "task_type",
        "evidences",
        "validation_feedback"
      ],
      "response_fields": [
        "request_id",
        "answer",
        "cited_evidence_ids",
        "usage"
      ]
    },
    {
      "name": "grain_case_evaluate",
      "method": "POST",
      "path": "/tools/v1/cases/evaluate",
      "request_fields": ["request_id", "case"],
      "response_fields": [
        "request_id",
        "needs_input",
        "missing_fields",
        "question",
        "rules"
      ]
    },
    {
      "name": "grain_citation_validate",
      "method": "POST",
      "path": "/tools/v1/citations/validate",
      "request_fields": ["request_id", "answer", "evidences"],
      "response_fields": [
        "request_id",
        "valid",
        "errors",
        "unsupported_sentences",
        "citation_ids"
      ]
    }
  ]
}
```

- [ ] **Step 4: Create the exact Xingchen node graph**

Write `workflow/README.md` with this content:

```markdown
# 粮储智研助手星辰工作流 v1

## 开始节点

按字符串类型创建六个输入：

1. `AGENT_USER_INPUT`
2. `REQUEST_ID`
3. `SESSION_ID`
4. `USER_ROLE`
5. `TASK_TYPE`
6. `CASE_JSON`

## 节点与分支

1. 开始节点。
2. `TASK_TYPE == "case_analysis"` 进入案例分支，否则进入知识问答分支。
3. 案例分支调用 `grain_case_evaluate`，传入 `REQUEST_ID` 和解析后的 `CASE_JSON`。
4. `needs_input == true` 时，消息节点输出工具返回的 `question`，然后结束。
5. 问答分支和完整案例分支调用 `grain_retrieve`：
   - `request_id = REQUEST_ID`
   - `query = AGENT_USER_INPUT`；案例分支把 `CASE_JSON` 与分析目标拼接为查询
   - `top_k = 5`
   - `filters = {}`
6. `quality.sufficient == false` 时输出“当前知识库没有找到足够证据，暂时无法给出可靠结论。”，然后结束。
7. 调用 `grain_generate`，传入问题、角色、任务类型和 `evidences`。
8. 调用 `grain_citation_validate`，传入 `answer` 和相同的 `evidences`。
9. `valid == false` 时只重试一次 `grain_generate`，并把 `errors` 和 `unsupported_sentences` 传入 `validation_feedback`。
10. 第二次验证仍失败时，输出检索证据摘要、适用条件和不确定性，不输出未验证结论。
11. 验证成功时输出 `answer`。
12. 所有工具节点配置超时异常分支，输出统一的依赖暂不可用提示。

## 工具配置

- 基础 URL 使用测试 HTTPS 地址。
- 路径和参数读取 `tool_contracts.json`。
- Header 固定为 `Authorization: Bearer ${TOOLS_SERVICE_TOKEN}`。
- 不在工作流提示词或固定变量中保存任何讯飞 API 密钥。

## 发布

1. 在星辰平台完成调试。
2. 发布为 API。
3. 绑定用于本项目的讯飞应用。
4. 记录 API Flow ID 到本地 `XF_WORKFLOW_FLOW_ID`。
5. 每次工作流变更后点击“更新绑定”，再执行在线回归。
```

- [ ] **Step 5: Add opt-in cloud adapter tests**

```python
# tests/online/test_cloud_services.py
import os

import pytest

from app.clients.iflytek_embedding import IflytekEmbeddingClient
from app.clients.iflytek_maas import IflytekMaaSClient
from app.clients.xingchen_workflow import XingchenWorkflowClient
from app.core.config import Settings


pytestmark = pytest.mark.online


def online_settings() -> Settings:
    if os.getenv("RUN_ONLINE") != "1":
        pytest.skip("set RUN_ONLINE=1 to call real iFlytek services")
    return Settings()


@pytest.mark.asyncio
async def test_embedding_online():
    settings = online_settings()
    client = IflytekEmbeddingClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_embedding_api_key.get_secret_value(),
        api_secret=settings.xf_embedding_api_secret.get_secret_value(),
        url=settings.embedding_url,
        timeout_seconds=settings.embedding_timeout_seconds,
    )
    try:
        vector = await client.embed("低温储粮", domain="query")
        assert vector.shape == (2560,)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_maas_online():
    settings = online_settings()
    client = IflytekMaaSClient(
        app_id=settings.xf_app_id,
        api_key=settings.xf_maas_api_key.get_secret_value(),
        api_secret=settings.xf_maas_api_secret.get_secret_value(),
        resource_id=settings.xf_maas_resource_id,
        service_id=settings.xf_maas_service_id,
        url=settings.maas_url,
        timeout_seconds=settings.maas_timeout_seconds,
    )
    result = await client.generate(
        [{"role": "user", "content": "用一句话说明低温储粮。"}],
        uid="online-smoke",
    )
    assert result.content.strip()
    assert result.total_tokens > 0


@pytest.mark.asyncio
async def test_workflow_online():
    settings = online_settings()
    client = XingchenWorkflowClient(
        api_key=settings.xf_workflow_api_key.get_secret_value(),
        api_secret=settings.xf_workflow_api_secret.get_secret_value(),
        flow_id=settings.xf_workflow_flow_id,
        url=settings.workflow_url,
        timeout_seconds=settings.workflow_timeout_seconds,
    )
    try:
        content = []
        async for frame in client.stream(
            {
                "AGENT_USER_INPUT": "低温储粮有什么作用？",
                "REQUEST_ID": "online-workflow",
                "SESSION_ID": "online-session",
                "USER_ROLE": "student",
                "TASK_TYPE": "knowledge_qa",
                "CASE_JSON": "",
            },
            uid="online-user",
        ):
            content.extend(choice.delta.content for choice in frame.choices)
        assert "".join(content).strip()
    finally:
        await client.close()
```

- [ ] **Step 6: Add the full external end-to-end test**

```python
# tests/online/test_end_to_end.py
import os

import httpx
import pytest


pytestmark = pytest.mark.online


@pytest.mark.asyncio
async def test_public_chat_end_to_end():
    if os.getenv("RUN_ONLINE") != "1":
        pytest.skip("set RUN_ONLINE=1 to run the end-to-end test")
    base_url = os.environ["LOCAL_PUBLIC_API_URL"].rstrip("/")
    async with httpx.AsyncClient(timeout=180) as client:
        async with client.stream(
            "POST",
            f"{base_url}/v1/chat",
            json={"message": "低温储粮有什么作用？", "role": "student"},
        ) as response:
            assert response.status_code == 200
            body = "".join([line async for line in response.aiter_lines()])
    assert "event: delta" in body
    assert "event: citations" in body
    assert "event: done" in body
    assert "event: error" not in body
```

- [ ] **Step 7: Write the operator guide and README entry**

Replace the credential constants in `build_vector_store.py` with:

```python
APP_ID = os.environ.get("XF_APP_ID", "")
API_KEY = os.environ.get("XF_EMBEDDING_API_KEY", "")
API_SECRET = os.environ.get("XF_EMBEDDING_API_SECRET", "")
```

Add this validation as the first lines inside `main()`:

```python
    missing = [
        name
        for name, value in {
            "XF_APP_ID": APP_ID,
            "XF_EMBEDDING_API_KEY": API_KEY,
            "XF_EMBEDDING_API_SECRET": API_SECRET,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing)
        )
```

Add this guard immediately before the interactive search loop:

```python
    if os.environ.get("SKIP_VECTOR_SEARCH") == "1":
        print("  Search verification skipped by SKIP_VECTOR_SEARCH=1")
        return
```

Write `docs/星辰工作流联调指南.md` with these exact sections and commands:

```markdown
# 星辰工作流联调指南

## 1. 准备配置

复制 `.env.example` 为 `.env`，填写三个讯飞服务的真实配置和独立的 `TOOLS_SERVICE_TOKEN`。不要提交 `.env`。

## 2. 重建本地向量库

当前检出中没有 `vector_store/`。在确认 Embedding 账号额度后运行：

```bash
set -a
source .env
set +a
SKIP_VECTOR_SEARCH=1 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python build_vector_store.py
```

完成后必须存在：

- `vector_store/vectors.npy`
- `vector_store/chunks_metadata.json`

## 3. 启动单进程服务

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

`GET /ready` 必须返回 `status=ready`、向量数量和维度。

## 4. 暴露工具接口

使用团队批准的 HTTPS 隧道把本机 8000 端口映射到公网。只把公网地址配置给星辰工具；不要把隧道访问令牌写入仓库。

## 5. 创建并发布工作流

严格按照 `workflow/README.md` 和 `workflow/tool_contracts.json` 创建节点、参数和异常分支。发布为 API 后，把 Flow ID 写入本地 `.env` 的 `XF_WORKFLOW_FLOW_ID`。

## 6. 在线验证

先运行三个云端适配器测试：

```bash
RUN_ONLINE=1 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/online/test_cloud_services.py -v
```

再运行完整链路：

```bash
RUN_ONLINE=1 LOCAL_PUBLIC_API_URL=http://127.0.0.1:8000 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/online/test_end_to_end.py -v
```

## 7. Trace 定位

在星辰发布管理中打开工作流详情和 Trace 日志，用本地日志中的 `REQUEST_ID` 对照工作流输入参数，定位失败节点。日志中不得记录任何密钥。
```

Append this section to `README.md`:

```markdown
## 技术实体 v1

技术实体采用“本地 FastAPI + 讯飞星辰工作流 + 讯飞 Embedding + 本地向量库 + 讯飞 MaaS 微调模型”的混合架构。

安装、配置、工作流创建和在线验证见：

- `docs/superpowers/specs/2026-07-19-hybrid-technical-core-design.md`
- `docs/superpowers/plans/2026-07-19-hybrid-technical-core.md`
- `docs/星辰工作流联调指南.md`
- `workflow/README.md`

本地启动：

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```
```

Append `vector_store/` to `.gitignore`; runtime vectors remain local build artifacts.

- [ ] **Step 8: Run all offline verification**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -v
git diff --check
```

Expected: all offline tests pass; `git diff --check` prints nothing.

- [ ] **Step 9: Build the missing vector store and run online verification**

Run only after `.env` is populated, the Xingchen workflow is published, its tool URL points to the running HTTPS service, and the account has sufficient quota:

```bash
set -a
source .env
set +a
SKIP_VECTOR_SEARCH=1 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python build_vector_store.py
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

In a second terminal:

```bash
RUN_ONLINE=1 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/online/test_cloud_services.py -v
RUN_ONLINE=1 LOCAL_PUBLIC_API_URL=http://127.0.0.1:8000 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/online/test_end_to_end.py -v
```

Expected:

- `GET /ready` reports `1023` vectors with dimension `2560`, unless a deliberate knowledge rebuild changes the chunk count.
- All three cloud adapter tests pass.
- The end-to-end response contains `delta`, at least one validated citation, and `done`, with no `error` event.
- A second case-analysis smoke request with missing `storage_type` returns `finish_reason="needs_input"` and includes `storage_type` in `missing_fields`.

- [ ] **Step 10: Commit Task 11**

```bash
git add .gitignore README.md build_vector_store.py workflow docs/星辰工作流联调指南.md tests/contract/test_workflow_assets.py tests/unit/test_build_script_config.py tests/online
git commit -m "docs: add Xingchen workflow integration"
```

---

## Spec Coverage Matrix

| Approved design requirement | Implemented by |
|---|---|
| Hybrid topology and no recursive calls | Tasks 7–10 |
| Public chat, case, source, health, readiness APIs | Tasks 9–10 |
| Four authenticated Xingchen tools | Task 7 |
| Stable evidence model and nullable metadata | Tasks 2–3 |
| Existing dense vector store | Task 3 |
| iFlytek Embedding adapter | Task 4 |
| Fine-tuned MaaS adapter | Task 5 |
| Case completeness without invented thresholds | Task 6 |
| Structural citation validation and one-retry workflow | Tasks 6 and 11 |
| Xingchen Workflow Open API and Trace correlation | Tasks 8–11 |
| Stable SSE event contract and provider degradation | Tasks 8–10 |
| Environment-only new runtime configuration | Tasks 1 and 11 |
| Offline, contract, integration, and online tests | Tasks 1–11 |
| Local/tunnel/stable-test deployment instructions | Task 11 |

Self-review result: every approved v1 requirement maps to at least one implementation task. OCR, hybrid retrieval, Web UI, databases, multi-worker deployment, and semantic entailment validation remain explicitly outside this plan.

## Final Verification Checklist

- [ ] Run `python -m pytest -m "not online" -v` in the `LLM` environment.
- [ ] Run `git diff --check`.
- [ ] Confirm `git status --short` contains no generated vector artifacts, `.env`, caches, or unrelated staged files.
- [ ] Confirm `/health` returns 200 and `/ready` returns 200 after the vector store exists.
- [ ] Confirm `/openapi.json` exposes two public POST endpoints and four authenticated tool POST endpoints.
- [ ] Confirm tool requests without the service token return 401.
- [ ] Confirm the real Embedding result has 2560 dimensions.
- [ ] Confirm the real MaaS response is non-empty and reports token usage.
- [ ] Confirm Xingchen Trace contains the same `REQUEST_ID` emitted by `/v1/chat`.
- [ ] Confirm a knowledge question produces at least one validated citation.
- [ ] Confirm an evidence-poor question refuses to produce an unsupported answer.
- [ ] Confirm an incomplete case produces a structured follow-up.
- [ ] Confirm a simulated provider outage produces an `error` SSE event without secrets.
- [ ] Confirm every implementation task was committed separately and no unrelated user file was committed.
