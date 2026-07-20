# Hybrid Technical Core Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the whole-branch review gaps so the technical entity enforces validated-evidence output, stable request isolation, exact domain/tool contracts, fail-closed runtime configuration, trustworthy vector artifacts, and cancellation-safe MaaS calls.

**Architecture:** Keep the approved hybrid topology unchanged: public `/v1/*` calls Xingchen, Xingchen calls only authenticated local `/tools/v1/*`, and local tools never call Xingchen. Strengthen the local request-context state machine so the gateway can independently distinguish validated answers, evidence-insufficient refusals, incomplete cases, and protocol failures. Repair domain, configuration, retrieval, build, provider, workflow-asset, and operator contracts without adding OCR, databases, multi-worker deployment, semantic entailment, or new product surfaces.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, httpx, websockets, NumPy, scikit-learn, pytest/pytest-asyncio.

## Global Constraints

- Run every command with `/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`.
- Follow strict RED-GREEN-REFACTOR; each task gets its own commit and independent review.
- Keep TLS verification enabled and all new secrets environment-only.
- Keep one Uvicorn worker/process because request context and vector state are in memory.
- Do not invent temperature, moisture, CO₂, fumigation, pesticide, or equipment-control thresholds.
- Citation validation remains structural; it does not claim semantic entailment.
- Do not call real cloud services unless `RUN_ONLINE=1` and all documented external prerequisites exist.
- Do not create or commit `.env`, `vector_store/`, `.superpowers/`, credentials, raw provider payloads, or review diffs.
- Previously exposed provider credentials require owner rotation/revocation; never reproduce their values.

---

### Task 1: Enforce the request safety state machine, auth-first tools, isolated IDs, and terminal observability

**Files:**
- Modify: `app/core/request_context.py`
- Modify: `app/core/observability.py`
- Modify: `app/tools/routes.py`
- Modify: `app/services/workflow_gateway.py`
- Modify: `app/main.py`
- Modify: `tests/unit/test_request_context.py`
- Modify: `tests/contract/test_tool_api.py`
- Modify: `tests/contract/test_public_api.py`
- Modify: `tests/integration/test_workflow_gateway.py`

**Interfaces:**
- Produces: request context fields `retrieval_sufficient`, `validation_valid`, `validated_answer`, and `question`.
- Produces: auth-first `/tools/v1/*` routing before body validation.
- Produces: a server-generated request ID used consistently by SSE, workflow parameters, tools, context, response headers, and logs.
- Produces: gateway terminal decisions that never release unvalidated workflow output.

- [ ] **Step 1: Write failing request-context and tool tests**

Add tests proving:

```python
async def test_context_records_retrieval_validation_and_case_terminal_state():
    await store.set_retrieval_result("req", [EVIDENCE], sufficient=True)
    await store.set_validation_result(
        "req",
        valid=True,
        answer="已验证回答。[E1]",
        citation_ids=[EVIDENCE.evidence_id],
    )
    await store.set_case_result(
        "req",
        needs_input=False,
        missing_fields=[],
        question=None,
    )
    context = await store.pop("req")
    assert context.retrieval_sufficient is True
    assert context.validation_valid is True
    assert context.validated_answer == "已验证回答。[E1]"
```

```python
def test_unauthenticated_malformed_tool_body_is_401():
    response = client.post("/tools/v1/retrieve", content=b"{")
    assert response.status_code == 401

def test_authenticated_malformed_tool_body_is_422():
    response = client.post(
        "/tools/v1/retrieve",
        headers={"Authorization": "Bearer tool-token"},
        content=b"{",
    )
    assert response.status_code == 422
```

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_request_context.py tests/contract/test_tool_api.py -v
```

Expected: failures because terminal state and auth-first routing are absent.

- [ ] **Step 2: Write failing gateway safety tests**

Add integration tests for these exact outcomes:

1. validated answer + matching `validated_answer` releases buffered deltas, cited evidence, then `done`;
2. validation false discards raw workflow content and emits a deterministic evidence-only fallback;
3. retrieval insufficient discards raw workflow content and emits the fixed insufficiency refusal;
4. incomplete case discards raw workflow content and emits the stored `question`, then `done(needs_input)`;
5. absent validation/context or answer mismatch emits `WORKFLOW_PROTOCOL_ERROR` with no raw `delta` and no `done`;
6. cancellation and consumer disconnect still clean context.

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/integration/test_workflow_gateway.py -v
```

Expected: current missing-context and failed-validation paths incorrectly emit raw `delta` and `done`.

- [ ] **Step 3: Write failing request-ID isolation and logging tests**

Add contract tests proving two calls with the same inbound `X-Request-ID` receive different UUID request IDs, and each response header, SSE `meta`, workflow `REQUEST_ID`, tool log, and terminal log uses its own server ID. Add `caplog` tests that require safe structured fields:

```python
assert record.event == "workflow_terminal"
assert record.request_id == server_request_id
assert record.finish_reason in {"stop", "needs_input", "error"}
assert not hasattr(record, "answer")
assert not hasattr(record, "evidence_text")
```

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_public_api.py tests/contract/test_tool_api.py tests/integration/test_workflow_gateway.py -v
```

Expected: duplicate client IDs are reflected and terminal/tool correlation logs are absent.

- [ ] **Step 4: Implement the state machine and auth-first route class**

Extend `RequestContext` and add atomic setters:

```python
retrieval_sufficient: bool | None = None
validation_valid: bool | None = None
validated_answer: str | None = None
question: str | None = None
```

`set_validation_result()` must clear `validated_answer` and `citation_ids` when `valid=False`. Configure the tools router with a custom `APIRoute` whose wrapper authenticates directly from headers before invoking FastAPI's generated body parser. Retrieval stores evidence plus sufficiency; validation stores valid state plus the exact validated answer.

Buffer workflow chunks until context is consumed. Choose one terminal branch in this order:

1. `needs_input=True`: emit stored question, empty citations, `done(needs_input)`;
2. `retrieval_sufficient=False`: emit the fixed evidence-insufficient refusal, empty citations, `done(stop)`;
3. `validation_valid=True` and buffered answer equals `validated_answer`: release buffered deltas, used citations, `done(stop)`;
4. `validation_valid=False`: emit a deterministic evidence-excerpt fallback and its citations, never the raw buffered answer;
5. otherwise: emit `WORKFLOW_PROTOCOL_ERROR`, no raw delta, no done.

- [ ] **Step 5: Implement server IDs and safe terminal logging**

Always generate a UUID as the authoritative request ID. A valid inbound ID may be retained only as non-authoritative `client_request_id` log metadata. Wrap the response body iterator so HTTP completion timing covers SSE consumption. Apply `settings.log_level` during lifespan startup. Log tool completion and workflow terminal outcome using IDs, node/tool name, elapsed time, result code, finish reason, and citation IDs only.

- [ ] **Step 6: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_request_context.py tests/contract/test_tool_api.py tests/contract/test_public_api.py tests/integration/test_workflow_gateway.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Expected: all tests pass, no answer/document text or secret appears in logs.

Commit:

```bash
git add app/core/request_context.py app/core/observability.py app/tools/routes.py app/services/workflow_gateway.py app/main.py tests/unit/test_request_context.py tests/contract/test_tool_api.py tests/contract/test_public_api.py tests/integration/test_workflow_gateway.py
git commit -m "fix: enforce validated workflow completion"
```

---

### Task 2: Complete goal-aware case and structural citation contracts

**Files:**
- Modify: `app/domain/cases/rules.py`
- Modify: `app/services/citation_validation.py`
- Modify: `app/schemas/api.py`
- Modify: `app/schemas/tools.py`
- Modify: `tests/unit/test_case_rules.py`
- Modify: `tests/unit/test_citation_validation.py`
- Modify: `tests/unit/test_schemas.py`
- Modify: `tests/contract/test_tool_api.py`

**Interfaces:**
- Produces: declarative goal-family field requirements with no numerical conclusions.
- Produces: parsed, non-empty answer sections; inline/source citation consistency; coverage statistics.
- Produces: strict bounded public/tool request models.

- [ ] **Step 1: Write failing goal-family tests**

Add table-driven tests for:

```python
GOAL_REQUIRED_FIELDS = {
    "mold": (
        "moisture_percent",
        "grain_temperature_c",
        "ambient_humidity_percent",
        "mold_signs",
        "condensation_signs",
    ),
    "pest": ("grain_temperature_c", "pest_signs"),
    "co2": ("co2_ppm", "co2_trend"),
    "temperature": (
        "grain_temperature_c",
        "temperature_trend",
        "ambient_temperature_c",
    ),
    "moisture": ("moisture_percent", "ambient_humidity_percent"),
}
```

Chinese goal keywords must map deterministically to those families; unknown goals require only base fields. Tests must assert `rules=[]` and that no threshold/risk conclusion is produced.

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_case_rules.py -v
```

Expected: mold/pest/CO₂/temperature goals currently pass without required measurements.

- [ ] **Step 2: Write failing section/citation/coverage tests**

Test optional Markdown headings and Chinese/ASCII colons, non-empty section bodies, source-only aliases, inline aliases missing from `来源`, unused source aliases, invalid aliases, critical sentences, and coverage:

```python
assert response.coverage.total_sentences >= 1
assert response.coverage.cited_sentences <= response.coverage.total_sentences
assert 0.0 <= response.coverage.ratio <= 1.0
```

Derive normalized `citation_ids` only from substantive sections, in first-use order. The `来源` section must declare exactly those used aliases.

- [ ] **Step 3: Write failing strict-schema tests**

Reject unknown request fields and bound all external strings/lists:

- request IDs: 1–128;
- questions/answers: 1–32,000, with chat/query remaining at their tighter limits;
- evidence inputs: 1–5;
- feedback/errors/citation lists: at most 20 items;
- grain/storage/goal/session/user/task strings: bounded and whitespace-normalized;
- numeric scores: `[-1, 1]`; token counts: non-negative.

Do not apply `extra="forbid"` to provider response frames.

- [ ] **Step 4: Implement the declarative evaluator, parsed validator, and strict request bases**

Define immutable goal declarations and keyword matching in `rules.py`. Parse answer sections line-by-line; accept headings such as `## 结论`, `结论：`, and `结论:`. Reject missing/empty/duplicate required sections. Exclude `来源` from substantive sentence coverage and critical-claim scans. Add:

```python
class CitationCoverage(BaseModel):
    total_sentences: int = Field(ge=0)
    cited_sentences: int = Field(ge=0)
    ratio: float = Field(ge=0.0, le=1.0)
```

Add `coverage` to `CitationValidateResponse`. Use strict request base models with `ConfigDict(extra="forbid", str_strip_whitespace=True)`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_case_rules.py tests/unit/test_citation_validation.py tests/unit/test_schemas.py tests/contract/test_tool_api.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Commit:

```bash
git add app/domain/cases/rules.py app/services/citation_validation.py app/schemas/api.py app/schemas/tools.py tests/unit/test_case_rules.py tests/unit/test_citation_validation.py tests/unit/test_schemas.py tests/contract/test_tool_api.py
git commit -m "fix: complete domain validation contracts"
```

---

### Task 3: Fail closed on runtime configuration and readiness

**Files:**
- Modify: `app/core/config.py`
- Modify: `app/api/health.py`
- Modify: `app/main.py`
- Modify: `tests/unit/test_config.py`
- Modify: `tests/contract/test_public_api.py`

**Interfaces:**
- Produces: non-empty settings, secure endpoint schemes, positive finite durations, validated log levels.
- Produces: `/ready` that checks vector artifacts and cloud configuration without network calls.

- [ ] **Step 1: Write failing settings tests**

Reject blank/whitespace values for every required identifier/secret, non-HTTPS Embedding/Workflow URLs, non-WSS MaaS URLs, unknown log levels, and zero/negative/non-finite timeouts or TTL.

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_config.py -v
```

Expected: current Settings accepts these invalid values.

- [ ] **Step 2: Write failing readiness tests**

With a loaded vector store but missing/blank injected cloud configuration, require:

```json
{
  "code": "CLOUD_CONFIG_NOT_READY",
  "message": "云端服务配置尚未就绪",
  "retryable": false
}
```

The response must list only missing/invalid variable names if details are included; never values. Valid static configuration plus a loaded vector store remains `200`.

- [ ] **Step 3: Implement validators and static readiness**

Use Pydantic field/model validators to strip and reject blanks, validate URL schemes, enforce finite positive values, and normalize `LOG_LEVEL` to a supported uppercase value. Implement a reusable static check for injected test settings and call it from `/ready`; do not make network requests.

- [ ] **Step 4: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_config.py tests/contract/test_public_api.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Commit:

```bash
git add app/core/config.py app/api/health.py app/main.py tests/unit/test_config.py tests/contract/test_public_api.py
git commit -m "fix: validate runtime readiness configuration"
```

---

### Task 4: Make evidence identity, retrieval filtering, and vector publication trustworthy

**Files:**
- Modify: `build_vector_store.py`
- Modify: `app/rag/evidence.py`
- Modify: `app/rag/vector_store.py`
- Modify: `app/rag/retriever.py`
- Modify: `tests/unit/test_build_script_config.py`
- Modify: `tests/unit/test_evidence.py`
- Modify: `tests/unit/test_vector_store.py`
- Modify: `tests/unit/test_retriever.py`
- Modify: `tests/contract/test_public_api.py`

**Interfaces:**
- Produces: normalized source paths and raw-file checksums propagated to every chunk.
- Produces: fail-closed staged vector publication and validated load artifacts.
- Produces: source/authority filtering before final top-k ranking.
- Produces: nullable source-detail relevance score.

- [ ] **Step 1: Write failing metadata identity tests**

Test that document IDs change when file bytes change, remain stable across Windows/POSIX separators, and that builder metadata contains `document_checksum` plus a normalized relative `source`. Missing legacy checksum must add a `checksum_missing` quality flag.

- [ ] **Step 2: Write failing builder and loader integrity tests**

Test partial embedding failure, zero/non-finite vectors, empty stores, malformed metadata, and preservation of a pre-existing store. `embed_all_chunks` must raise instead of injecting zeros. Staged artifacts must not replace a good store until all embeddings and metadata validate.

- [ ] **Step 3: Write failing filter and score tests**

Create candidates where the matching authority/source type is below the unfiltered `top_k`. Combined filters must return the best matching result. Missing metadata fails closed when a filter is requested. `/v1/sources` must return `score=null`; query results remain bounded cosine similarity in `[-1, 1]`.

- [ ] **Step 4: Implement normalized ingestion and staged publication**

Use `file_path.relative_to(doc_dir).as_posix()` and SHA-256 of raw file bytes. Propagate checksum through chunking and persisted metadata. Remove module-import directory creation. Abort on any embedding failure. Build in a sibling temporary directory, validate it with `VectorStore.load()`, then replace the output directory with rollback to the prior directory on failure.

- [ ] **Step 5: Implement loader validation and pre-top-k filtering**

Reject empty, non-2-D, non-finite, zero-norm, dimension-mismatched vectors and malformed metadata as `VectorStoreNotReady`. Reject invalid query vectors as `EMBEDDING_UNAVAILABLE`. Retrieve the candidate set, apply `source_type` and `authority_level` predicates, then truncate to requested top-k. Normalize source separators before evidence hashing.

- [ ] **Step 6: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_build_script_config.py tests/unit/test_evidence.py tests/unit/test_vector_store.py tests/unit/test_retriever.py tests/contract/test_public_api.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Commit:

```bash
git add build_vector_store.py app/rag/evidence.py app/rag/vector_store.py app/rag/retriever.py tests/unit/test_build_script_config.py tests/unit/test_evidence.py tests/unit/test_vector_store.py tests/unit/test_retriever.py tests/contract/test_public_api.py
git commit -m "fix: publish only valid evidence vectors"
```

---

### Task 5: Replace the blocking MaaS thread with cancellation-aware async WebSockets

**Files:**
- Modify: `requirements.txt`
- Modify: `app/clients/iflytek_maas.py`
- Modify: `app/main.py`
- Modify: `tests/unit/test_iflytek_maas.py`
- Modify: `tests/contract/test_public_api.py`

**Interfaces:**
- Produces: async `MaaSTransport.exchange(...) -> AsyncIterator[dict]`.
- Produces: `IflytekMaaSClient.close()` and prompt cancellation/timeout socket closure.

- [ ] **Step 1: Write failing async cancellation tests**

Add async fake transports that block during connect/receive. Cancel `generate()` and assert cancellation propagates, the transport generator finalizer runs, and no worker thread remains. Add timeout and owned-client shutdown tests.

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_maas.py -v
```

Expected: the current `asyncio.to_thread` worker remains active after cancellation.

- [ ] **Step 2: Implement native async WebSocket transport**

Use `websockets.asyncio.client.connect` with the existing signed WSS URL, explicit open/receive/close timeouts, and default TLS verification. Parse each JSON frame inside the async context. Convert `_generate_sync` to async frame consumption, preserve strict terminal protocol checks, sanitize normalized exception chains, and allow `CancelledError` to propagate. Add `websockets>=15,<17` as a direct dependency.

- [ ] **Step 3: Register MaaS lifecycle ownership**

Implement idempotent `close()` and register the MaaS client with application-owned closeables. Ensure injected containers remain untouched and partial startup cleanup includes MaaS.

- [ ] **Step 4: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/unit/test_iflytek_maas.py tests/contract/test_public_api.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Commit:

```bash
git add requirements.txt app/clients/iflytek_maas.py app/main.py tests/unit/test_iflytek_maas.py tests/contract/test_public_api.py
git commit -m "fix: make MaaS generation cancellation safe"
```

---

### Task 6: Export exact workflow schemas and complete cross-platform operations

**Files:**
- Modify: `workflow/tool_contracts.json`
- Modify: `workflow/README.md`
- Modify: `docs/星辰工作流联调指南.md`
- Modify: `README.md`
- Modify: `tests/contract/test_workflow_assets.py`

**Interfaces:**
- Produces: self-contained request/response JSON Schemas for all four tool nodes.
- Produces: macOS/Linux and Windows/PowerShell setup, verification, build, and single-worker launch commands.

- [ ] **Step 1: Write failing exact-schema tests**

For each tool, require `request_schema` and `response_schema` to equal the corresponding Pydantic `model_json_schema()` output after JSON round-trip. Require nested definitions, required fields, enums, bounds, defaults, and `additionalProperties` behavior. Keep existing exact path/method/auth/start-parameter tests.

- [ ] **Step 2: Write failing operator quick-start tests**

Require README/operator documentation to include:

- `conda activate LLM`;
- `python -m pip install -r requirements-dev.txt`;
- `.env.example` copy/configuration;
- offline test command;
- noninteractive vector rebuild;
- one-worker Uvicorn startup;
- expected `/health` and `/ready` behavior;
- PowerShell equivalents for environment loading, build, tests, and startup;
- the existing `/tools/v1/*` allowlist and anti-recursion boundary.

- [ ] **Step 3: Export self-contained schemas and update mappings**

Embed full request and response schemas under each tool entry. Update citation response mapping for `coverage` and preserve exact tool names, methods, paths, authentication, and six start parameters. Document how to map nested objects in Xingchen; do not claim a published platform export exists before online publication.

- [ ] **Step 4: Complete operator documentation**

Add concise installation/configuration/test/build/start sections for macOS/Linux and Windows. Use environment-neutral `python` after `conda activate LLM`, except where the repository's verified absolute interpreter is intentionally shown for this Mac. State that `/ready` remains 503 until both vectors and static cloud configuration are valid.

- [ ] **Step 5: Verify and commit**

Run:

```bash
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/contract/test_workflow_assets.py -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/online -v
/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest -m "not online" -q
git diff --check
```

Expected: online tests skip without network; all offline tests pass.

Commit:

```bash
git add workflow/tool_contracts.json workflow/README.md docs/星辰工作流联调指南.md README.md tests/contract/test_workflow_assets.py
git commit -m "docs: export exact Xingchen tool schemas"
```

---

## Review Feedback Disposition

The following review items are accepted by Tasks R1–R6: validated-answer gating, goal-aware case fields, source-only citation bypass, auth-first parsing, static readiness, server-generated correlation IDs, checksum-based document identity, pre-top-k filters, exact nested tool schemas, MaaS cancellation, terminal/tool observability, fail-closed vector publication, loader validation, nullable source-detail score, bounded strict request schemas, and cross-platform quick start.

The following calibrations are intentional:

- Cosine similarity remains in `[-1, 1]`; no `[0, 1]` reinterpretation is introduced.
- Provider response frames remain forward-compatible and do not use `extra="forbid"`.
- Goal requirements add field-presence declarations only; no domain threshold or risk conclusion is introduced.
- Citation checks remain structural and expose coverage statistics without claiming semantic support.
- The full workflow YAML/export remains an external publication artifact; the repository ships exact self-contained tool schemas and node mappings now.

## Final Verification

After R1–R6:

- [ ] Run the full offline suite fresh.
- [ ] Confirm online tests collect and skip without `RUN_ONLINE=1`.
- [ ] Run `compileall`, `git diff --check`, and repository artifact/credential scans.
- [ ] Start one local Uvicorn worker with safe fake configuration and inspect `/health`, `/ready`, and OpenAPI.
- [ ] Dispatch a fresh whole-branch reviewer over `fc0450d..HEAD`.
- [ ] Fix all remaining Critical/Important findings and re-review.
- [ ] Record external blockers separately: credential rotation, real vector rebuild, provider quota, published Flow ID, public HTTPS tool URL, Trace, and live end-to-end validation.
