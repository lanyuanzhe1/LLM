# 讯飞 ChatDoc 全托管 RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用讯飞 ChatDoc 的自动解析、切分、向量化和检索替换正式链路中的本地切块与 sklearn 向量库。

**Architecture:** 新增受控的 ChatDoc HTTP 客户端和全量导入 CLI；运行时通过兼容现有 `RetrieveResponse` 的云检索器调用 `vector/search`。导入全部成功后才原子发布 manifest 和切换 repoId，旧本地库保留但不再加载。

**Tech Stack:** Python 3.11、httpx、pydantic、pytest、讯飞 ChatDoc REST API

**Spec:** `docs/superpowers/specs/2026-08-27-iflytek-chatdoc-rag-design.md`

## Global Constraints

- 所有 Python 命令使用 `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`。
- ChatDoc 上传固定使用 `parseType=AUTO`、`fileType=wiki`、`stepByStep=false`。
- 单个上传文件不得超过 20 MB；超限文件记录后跳过，由用户手动拆分。
- 只有所有文件达到 `vectored` 并加入 repo 后才切换正式配置。
- 不删除旧本地向量库或远端资源，不在日志和异常中泄露凭据。
- 正式运行时不得混用 ChatDoc 和本地 Embedding 向量空间。

---

### Task 1: ChatDoc HTTP 客户端

**Files:**
- Create: `app/clients/iflytek_chatdoc.py`
- Create: `tests/unit/test_iflytek_chatdoc.py`
- Modify: `app/core/errors.py`

**Interfaces:**
- Produces: `ChatDocSearchHit`, `IflytekChatDocClient.create_repo()`, `upload_file()`, `file_statuses()`, `wait_until_vectored()`, `add_files()`, `search()`, `close()`。

- [ ] **Step 1: Write failing tests for HmacSHA1 headers and validated search results**
- [ ] **Step 2: Run `python -m pytest tests/unit/test_iflytek_chatdoc.py -q` and confirm expected failures**
- [ ] **Step 3: Implement the minimal async client with bounded retries and response validation**
- [ ] **Step 4: Run the client tests and confirm they pass**

### Task 2: 全量导入与超限文件跳过

**Files:**
- Create: `app/ingest/chatdoc_upload.py`
- Create: `ingest_chatdoc.py`
- Create: `tests/unit/test_chatdoc_upload.py`

**Interfaces:**
- Consumes: Task 1 `IflytekChatDocClient`。
- Produces: `prepare_uploads()`, `run_ingest()`，以及 `artifacts/chatdoc/base.json` schema。

- [ ] **Step 1: Write failing tests for source scanning, oversized-file skipping, batch size 20, and atomic manifest publication**
- [ ] **Step 2: Run the focused tests and confirm expected failures**
- [ ] **Step 3: Implement upload preparation plus orchestration**
- [ ] **Step 4: Run focused tests and CLI `--help`**

### Task 3: ChatDoc 运行时检索器

**Files:**
- Create: `app/rag/chatdoc_retriever.py`
- Create: `tests/unit/test_chatdoc_retriever.py`
- Modify: `app/rag/evidence.py`

**Interfaces:**
- Consumes: Task 1 `IflytekChatDocClient.search()` and Task 2 manifest。
- Produces: `ChatDocRetriever.retrieve()`, `ChatDocRetriever.get_evidence()`, `load_chatdoc_manifest()`。

- [ ] **Step 1: Write failing tests for score normalization, source mapping, filtering, stable IDs, and evidence cache**
- [ ] **Step 2: Run focused tests and confirm expected failures**
- [ ] **Step 3: Implement the retriever without altering public response schemas**
- [ ] **Step 4: Run focused tests and existing citation tests**

### Task 4: 应用装配、配置与端点兼容

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/main.py`
- Modify: `app/dependencies.py`
- Modify: `app/api/health.py`
- Modify: `app/api/sources.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/contract/test_public_api.py`

**Interfaces:**
- Consumes: `XF_CHATDOC_REPO_ID`, `CHATDOC_MANIFEST_PATH`, Task 1 客户端和 Task 3 检索器。
- Produces: ChatDoc-only production container and backend-neutral readiness/source endpoints。

- [ ] **Step 1: Write failing container and endpoint contract tests**
- [ ] **Step 2: Run focused tests and confirm expected failures**
- [ ] **Step 3: Wire ChatDoc into settings and `build_container`, removing local-store startup dependency**
- [ ] **Step 4: Run unit and contract suites**

### Task 5: 全量远端构建与正式切换

**Files:**
- Modify: `.env`
- Create at runtime: `artifacts/chatdoc/base.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-4。
- Produces: 全部 base 文档已 `vectored` 的 ChatDoc repo 和启用该 repo 的本地配置。

- [ ] **Step 1: Run the official ChatDoc ingest CLI against all `knowledge/` sources**
- [ ] **Step 2: Confirm manifest source coverage equals scanner source coverage and every upload is `vectored`**
- [ ] **Step 3: Update `.env` only after successful remote publication**
- [ ] **Step 4: Run one real `vector/search` smoke query**
- [ ] **Step 5: Run the full offline test suite and configuration validation**
