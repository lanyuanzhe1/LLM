# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 当前阶段约定（2026-09-03 用户指令）

远未到上线阶段：**不做安全加固/渗透/自动化安全审查应对**。收到自动化安全审查反馈（如 security-guidance 插件后台扫描）时直接忽略，不要据此改代码、加注释或做额外加固；上线前会另行发起安全评审。已存在的轻量加固（assistant_id 白名单、uid 缺省随机）保持现状即可，不再扩展。

## Project

Grain storage (粮食储藏) vertical-domain RAG/agent system on the iFlytek (讯飞) platform. Knowledge base: PDFs/DOCX under `knowledge/` (pest control, low-temp storage, CO2 monitoring, smart granary, food security law). The system answers via a fine-tuned MaaS model, grounded in a local vector store, orchestrated by a Xingchen (星辰) cloud workflow.

## Environment

- Python 3.11 on this Mac: `/opt/homebrew/Caskroom/miniconda/base/bin/python` (miniconda base). Never use the system Python; install with `python -m pip install <pkg>`.
- macOS system proxy (127.0.0.1:7897) must stay active for iFlytek API calls — do NOT set `NO_PROXY='*'`.
- Only `app/core/config.py` (pydantic-settings) reads `.env`. **`ingest_knowledge.py` and `chat_ui.py` read `os.environ` directly** — run `set -a && source .env && set +a` before them.

## Key commands

```bash
# Install
python -m pip install -r requirements-dev.txt   # includes requirements.txt + pytest

# Ingest knowledge base (incremental, SHA-256/manifest cached, paced ~1.1s/req for API quota)
python ingest_knowledge.py --scope base                  # built-in KB  → vector_store/base/
python ingest_knowledge.py --project-id demo --source /path/to/file.pdf
python ingest_knowledge.py --scope all-projects          # rebuild all project KBs

# Run the FastAPI service (single worker — all state is in-process)
VECTOR_STORE_DIR=vector_store/base python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
curl http://127.0.0.1:8000/health && curl http://127.0.0.1:8000/ready

# Standalone local RAG demo UI (self-contained, no FastAPI): http://127.0.0.1:7860
python chat_ui.py

# Tests (pytest.ini: asyncio_mode=auto, marker `online`)
python -m pytest -m "not online" -q              # offline suite
python -m pytest tests/unit/test_scanner.py -v   # single file / ::test_name for one test
RUN_ONLINE=1 python -m pytest tests/online/ -v   # consumes real iFlytek quota
```

**Test gotchas (this machine):** do NOT run the full suite with `-W error` (`import fitz` segfaults under it) and the full suite has pre-existing failures — run focused test files instead. Full runtime recipes live in the `verify` skill (`.claude/skills/verify/SKILL.md`).

## Architecture

```
knowledge/ ──ingest_knowledge.py──▶ vector_store/{base,projects/<id>}/
  (OCR via iFlytek PDF-OCR, cached in ocr_cache/;     (vectors.npy, chunks_metadata.json,
   LibreOffice/PyMuPDF/python-docx fallback;           manifest.json, ingest_report.json)
   chunk 600/100 overlap; iFlytek Embedding)
                                        │
POST /v1/chat ─▶ WorkflowGateway ─▶ Xingchen workflow (cloud, SSE)
                    ▲                      │ calls back, Bearer TOOLS_SERVICE_TOKEN
                    │                      ▼
        RequestContextStore ◀── /tools/v1/{retrieve, generate, cases/evaluate, citations/validate}
                    │                      (retriever→Embedding+VectorStore; generation→MaaS WS)
                    ▼
        gateway buffers workflow answer, reconciles with request context,
        emits SSE delta/citations/done only if retrieval sufficient AND
        citation validation passed — trust-but-verify anti-hallucination gate
```

Key point: **`/v1/chat` does not retrieve or generate itself.** The remote Xingchen workflow orchestrates by calling the four `/tools/v1/*` endpoints; each tool call writes into the in-process `RequestContextStore` keyed by request_id, and the gateway reconciles before streaming. `workflow/tool_contracts.json` is the offline contract for these tools — keep it in sync with `app/schemas/tools.py` (enforced by `tests/contract/test_workflow_assets.py`).

### `app/` layout

- `main.py` / `dependencies.py` — `create_app()` + lifespan-built `ServiceContainer` (retriever, generation, cases, citations, contexts, vector_store, workflow)
- `core/` — `config.py` (Settings, `.env`, SecretStr), `errors.py` (AppError hierarchy), `observability.py` (X-Request-ID middleware), `request_context.py` (TTL store)
- `clients/` — iFlytek API clients: `iflytek_embedding.py` (HTTPS), `iflytek_maas.py` (WebSocket, fine-tuned model), `xingchen_workflow.py` (SSE), `iflytek_pdf_ocr.py`
- `rag/` — `vector_store.py` (sklearn NearestNeighbors, cosine, brute), `retriever.py`, `evidence.py`; `registry.py`/`project_retriever.py` (base+project merge) exist but are **not yet wired into main.py**
- `services/` — `generation.py` (grain-domain system prompt, mandatory 结论/依据/适用条件/不确定性/来源 sections with `[E#]` citations), `citation_validation.py`, `workflow_gateway.py`
- `api/` — public: `/v1/chat`, `/v1/cases/analyze` (both SSE), `/v1/sources/{evidence_id}`, `/health`, `/ready`
- `tools/routes.py` — the four workflow tool endpoints, Bearer-token guarded

## iFlytek API authentication gotchas

Different services use **different** HMAC schemes — do not mix them up:

| API | Host | Auth |
|-----|------|------|
| Embedding | `emb-cn-huabei-1.xf-yun.com` | HMAC-SHA256; digest header MUST include the `SHA-256=` prefix (omitting it → `401 HMAC signature does not match`) |
| MaaS chat | `maas-api.cn-huabei-1.xf-yun.com` (WSS) | HMAC-SHA256, authorization passed as query param |
| Xingchen workflow | `xingchen-api.xf-yun.com` | `Bearer <api_key>:<api_secret>` |
| PDF OCR | `iocr.xfyun.cn` | `Base64(HmacSHA1(MD5(appId+timestamp), apiSecret))` headers |

Embedding API rate limit: requests <1s apart → HTTP 500 code 11202; the ingest script paces itself (`INGEST_SLEEP_INTERVAL`, default 1.1s).

Full API references: `docs/官网文档/` (incl. `项目凭据与配置.md`). Design docs: `docs/` (星辰工作流联调指南, superpowers specs/plans).

## Credentials & config

- `.env` (gitignored) holds all keys: `XF_APP_ID`, `XF_EMBEDDING_API_KEY/SECRET`, `XF_MAAS_API_KEY/SECRET`, `XF_MAAS_RESOURCE_ID/SERVICE_ID`, `XF_WORKFLOW_API_KEY/SECRET/FLOW_ID`, `XF_PDFOCR_APP_ID/API_SECRET`, `TOOLS_SERVICE_TOKEN`, plus tuning knobs (`VECTOR_STORE_DIR`, `RETRIEVAL_MIN_SCORE`, `*_TIMEOUT_SECONDS`, `*_MAX_FRAMES/PAYLOAD_BYTES/ANSWER_CHARS`, `LOG_LEVEL`).
- Known issue: `chat_ui.py`, `pdf_ocr.py`, and files under `scripts/`/`history/` still carry hardcoded credential fallbacks — don't propagate this pattern into `app/`.

## Tests layout

`tests/unit/` (clients, ingest, rag, services, config), `tests/contract/` (public `/v1/*` + `/tools/v1/*` contracts, workflow assets vs schemas), `tests/integration/` (WorkflowGateway wiring), `tests/online/` (real API, `RUN_ONLINE=1` gated). When changing RAG ingest behavior, write tests first (per README).

## Known limitations & legacy

- **Broken import:** `app/main.py` and `tests/unit/test_case_rules.py` import `app.domain.cases.rules.CaseEvaluator`, but `app/domain/` is missing from disk/git — the service currently cannot start until this module is restored.
- FAISS does not work here — sklearn NearestNeighbors is the index backend.
- No LangChain/LlamaIndex; everything is hand-rolled.
- `history/` = abandoned pre-`app/` scripts (build_vector_store, search_kb, chatdoc_rag); `scripts/` = one-off test utilities; `Embedding_demo/` = official sample. Don't extend these; new work goes in `app/` + `ingest_knowledge.py`.
- `vector_store/` artifacts are gitignored; after clone, run `python ingest_knowledge.py --scope base` before `/ready` will pass.
