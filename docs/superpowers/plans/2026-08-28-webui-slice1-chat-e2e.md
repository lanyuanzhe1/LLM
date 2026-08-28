# Slice 1：登录 → 聊天 → 历史 端到端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通"注册/登录 → 新建对话 → 流式粮储问答 → 刷新恢复历史"最小闭环，三进程（`frontend/webui` SPA、`services/webui` 应用服务、`app` 领域服务）全部离线可测。

**Architecture:** 按 spec §4 拓扑：浏览器只与 `services/webui` 通信；`services/webui` 把聊天补全（带服务密钥 + X-OpenWebUI-* 转发头）代理到 `app` 新增的 OpenAI 兼容层；会话历史持久化在 `services/webui` 的 SQLite。本计划只覆盖 Slice 1；知识库（Slice 2）、智能体广场（Slice 3）、品牌/管理收尾（Slice 4）各自另有计划。

**Tech Stack:** FastAPI + SQLAlchemy[asyncio] + aiosqlite + PyJWT + bcrypt（services/webui）；FastAPI + pydantic-settings（app，现有）；SvelteKit 2 + Svelte 5 + Tailwind 4 + adapter-static + marked + dompurify（frontend/webui）。

**Spec:** `docs/superpowers/specs/2026-08-27-webui-product-architecture-design.md`（决策 D1–D15 是本计划的依据）

## Global Constraints

- Python 解释器：`/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`；安装用 `python -m pip`；禁止系统 Python/base pip。
- 工作分支：本计划在 worktree 分支 `worktree-webui-product`（基于 `webui` tip `31765ec`）上执行；提交落在该分支。
- 禁止 Mock 数据/Mock 运行模式；测试中的 stub/fake 仅作单测替身。
- 禁止恢复本地解析、OCR、Embedding、sklearn/FAISS、本地向量库 fallback。
- `example/openwebui/` 只读，不修改其中任何文件；提取 = 从该目录**拷贝**后在新位置裁剪。
- 不整体合并 `develop-openwebUI`；只用 `git show develop-openwebUI:<path>` 取文件。
- 凭据只从 `.env` 读取；不进入源码、前端包、日志；供应商错误脱敏。
- 从参考拷贝的源文件保持原样，不添加也不删除文件内已有声明（D11）。
- 每个 Task 完成后按其 Commit 步骤提交；测试命令中的 `python` 均指上面的解释器绝对路径。

## 文件地图

```text
app/                                  # 现有领域服务（Task 1-6 新增/修改）
  app/core/config.py                  # 修改：新增 OPENAI_COMPAT_* 字段与校验
  app/schemas/openai_compat.py        # 新增（原样移植）
  app/services/openai_compat.py       # 新增（移植 + 删 learning 依赖 + 历史打包）
  app/api/openai_compat.py            # 新增（移植 + 换任务路由为历史打包）
  app/main.py                         # 修改：三处装配
  tests/unit/test_openai_compat.py    # 新增（移植裁剪）
  tests/contract/test_openai_compat_api.py  # 新增（移植适配）

services/webui/                       # Task 7-13 新建
  requirements.txt  pytest.ini  .env.example
  webui/__init__.py  settings.py  events.py  main.py
  webui/internal/__init__.py  db.py
  webui/models/{__init__,config,users,auths,chats,chat_messages}.py
  webui/utils/{__init__,auth,misc,upstream}.py
  webui/routers/{__init__,auths,chats,completions,proxy}.py
  tests/{conftest.py,test_auth.py,test_chats.py,test_completions.py}

frontend/webui/                       # Task 14-16 新建
  package.json  svelte.config.js  vite.config.ts  tsconfig.json  tailwind.config…
  src/app.html  src/routes/…  src/lib/{stores,apis,utils}/…
```

---

## Phase A：`app` OpenAI 兼容层

### Task 1: `app/core/config.py` 新增 OPENAI_COMPAT_* 配置

**Files:**
- Modify: `app/core/config.py`
- Test: `tests/unit/test_config.py`（现有文件，增补）

**Interfaces:**
- Produces（后续任务依赖）: `Settings.openai_compat_api_key: SecretStr`（必填）、`openai_compat_model_id: str = "grain-storage-agent"`、`openai_compat_model_name: str = "粮储知识助手"`、`openai_compat_project_id: str | None = None`、`openai_compat_history_enabled: bool = True`、`openai_compat_history_max_turns: int = 6`、`openai_compat_history_max_chars: int = 4000`。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_config.py` 末尾追加（沿用该文件现有 fixture 风格；若文件已有构造完整 Settings 的辅助函数，把新必填字段加进去）：

```python
def test_openai_compat_defaults_and_validators():
    from app.core.config import Settings

    settings = Settings(
        xf_app_id="app",
        xf_embedding_api_secret="emb",
        xf_maas_api_key="k",
        xf_maas_api_secret="s",
        xf_maas_resource_id="r",
        xf_maas_service_id="svc",
        xf_workflow_api_key="wk",
        xf_workflow_api_secret="ws",
        xf_workflow_flow_id="flow",
        tools_service_token="t" * 16,
        xf_chatdoc_repo_id="repo",
        openai_compat_api_key="compat-key-1",
    )
    assert settings.openai_compat_model_id == "grain-storage-agent"
    assert settings.openai_compat_history_enabled is True
    assert settings.openai_compat_history_max_turns == 6
    assert settings.openai_compat_history_max_chars == 4000


def test_openai_compat_api_key_rejects_invisible_chars():
    import pytest
    from app.core.config import Settings

    with pytest.raises(ValueError):
        Settings(
            xf_app_id="app",
            xf_embedding_api_secret="emb",
            xf_maas_api_key="k",
            xf_maas_api_secret="s",
            xf_maas_resource_id="r",
            xf_maas_service_id="svc",
            xf_workflow_api_key="wk",
            xf_workflow_api_secret="ws",
            xf_workflow_flow_id="flow",
            tools_service_token="t" * 16,
            xf_chatdoc_repo_id="repo",
            openai_compat_api_key="bad key with spaces\t",
        )
```

同时运行全量离线配置测试，找出所有构造 `Settings(...)` 的现有 fixture：

```bash
grep -rn "Settings(" tests/unit/test_config.py tests/contract/ tests/integration/ | head -20
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_config.py -q`
Expected: FAIL（`Settings` 无 `openai_compat_api_key` 参数 → TypeError/ValidationError）

- [ ] **Step 3: 实现**

`app/core/config.py` 三处修改：

1. `SECRET_FIELDS` 元组末尾追加 `"openai_compat_api_key"`；`cloud_configuration_issues` 中密钥校验器选择条件由 `if field == "tools_service_token"` 改为 `if field in {"tools_service_token", "openai_compat_api_key"}`。
2. `Settings` 字段区（`tools_service_token` 之后）追加：

```python
    openai_compat_api_key: SecretStr
    openai_compat_model_id: str = "grain-storage-agent"
    openai_compat_model_name: str = "粮储知识助手"
    openai_compat_project_id: str | None = None
    openai_compat_history_enabled: bool = True
    openai_compat_history_max_turns: int = Field(default=6, gt=0, le=50)
    openai_compat_history_max_chars: int = Field(default=4000, gt=0)
```

3. 新增/扩展 validator：

```python
    @field_validator("tools_service_token", "openai_compat_api_key")
    @classmethod
    def validate_tools_service_token(cls, value: SecretStr) -> SecretStr:
        normalized = _valid_tools_token(value)
        if normalized is None:
            raise ValueError("must be a visible ASCII bearer token")
        return normalized

    @field_validator("openai_compat_model_id", "openai_compat_model_name")
    @classmethod
    def validate_openai_compat_display(cls, value: str) -> str:
        normalized = _non_blank_string(value)
        if normalized is None or len(normalized) > 128:
            raise ValueError("must contain 1-128 characters")
        return normalized

    @field_validator("openai_compat_project_id")
    @classmethod
    def validate_openai_compat_project_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = _non_blank_string(value)
        if normalized is None:
            raise ValueError("must not be blank")
        return normalized
```

注意：原有 `@field_validator("tools_service_token")` 与新 decorator 合并为上面的双字段版本（不要重复注册同名字段）。

- [ ] **Step 4: 修复所有因新必填字段而失败的现有测试 fixture**（在相应 `Settings(...)`/`SimpleNamespace(...)` 构造处补 `openai_compat_api_key="test-compat-key"`）

- [ ] **Step 5: 运行确认通过**

Run: `python -m pytest tests/unit/test_config.py -q && python -m pytest -m "not online" -q`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py tests/
git commit -m "feat(app): add OPENAI_COMPAT_* settings for the OpenAI compatibility layer"
```

---

### Task 2: 移植 `app/schemas/openai_compat.py`（原样）

**Files:**
- Create: `app/schemas/openai_compat.py`
- Test: `tests/unit/test_openai_compat.py`（本任务先建文件，Task 3 继续补充）

**Interfaces:**
- Produces: `ChatMessage(role, content)`、`ChatCompletionRequest(model, messages, stream)`（`last_user_message()`、`extra="ignore"`）、`validate_forwarded_identifier(value, field)`。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_openai_compat.py`：

```python
import pytest
from pydantic import ValidationError

from app.schemas.openai_compat import (
    ChatCompletionRequest,
    validate_forwarded_identifier,
)


def test_request_requires_non_empty_user_message():
    with pytest.raises(ValidationError):
        ChatCompletionRequest(
            model="grain-storage-agent",
            messages=[{"role": "assistant", "content": "你好"}],
        )


def test_request_ignores_extra_fields():
    request = ChatCompletionRequest(
        model="grain-storage-agent",
        messages=[{"role": "user", "content": "低温储粮要点？"}],
        chat_id="should-be-ignored",
    )
    assert request.last_user_message() == "低温储粮要点？"


def test_forwarded_identifier_rejects_non_visible_ascii():
    assert validate_forwarded_identifier("chat-1", "X-OpenWebUI-Chat-Id") == "chat-1"
    assert validate_forwarded_identifier(None, "X-OpenWebUI-Chat-Id") is None
    with pytest.raises(ValueError):
        validate_forwarded_identifier("带中文", "X-OpenWebUI-Chat-Id")
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_openai_compat.py -q`
Expected: FAIL（`ModuleNotFoundError: app.schemas.openai_compat`）

- [ ] **Step 3: 原样移植**

```bash
git show develop-openwebUI:app/schemas/openai_compat.py > app/schemas/openai_compat.py
```

（61 行，零改动；内容已在调研中逐行核对：只依赖 pydantic。）

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_openai_compat.py -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/schemas/openai_compat.py tests/unit/test_openai_compat.py
git commit -m "feat(app): port OpenAI-compat request schemas from develop-openwebUI"
```

---

### Task 3: 移植 `app/services/openai_compat.py`（删 learning 依赖）

**Files:**
- Create: `app/services/openai_compat.py`
- Test: `tests/unit/test_openai_compat.py`（追加）

**Interfaces:**
- Consumes: `app/schemas/events.py` 的内部 SSE 帧格式（`event: <name>\ndata: <json>\n\n`，事件名 `meta/delta/citations/done/error`）——两分支逐字节一致，无需改动。
- Produces: `OpenAICompatUpstreamError(code, message)`、`preflight_openai_stream(events, *, return_after_meta)`、`openai_stream(events, *, completion_id, model, created, emit_openwebui_status=False)`、`collect_openai_completion(events, *, completion_id, model, created)`、`build_workflow_message(messages, *, enabled, max_turns, max_chars)`。

- [ ] **Step 1: 写失败测试（追加到 `tests/unit/test_openai_compat.py`）**

```python
from app.services.openai_compat import (
    OpenAICompatUpstreamError,
    build_workflow_message,
    collect_openai_completion,
    openai_stream,
    preflight_openai_stream,
)


def _frame(event: str, payload: dict) -> str:
    import json
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _agen(frames):
    for frame in frames:
        yield frame


def _sse_payloads(text: str) -> list[str]:
    prefix = "data: "
    return [
        part[len(prefix):]
        for part in text.strip().split("\n\n")
        if part.startswith(prefix)
    ]


async def test_stream_emits_chunks_sources_and_done():
    frames = [
        _frame("meta", {"request_id": "r1"}),
        _frame("delta", {"content": "低温"}),
        _frame("delta", {"content": "储粮"}),
        _frame("citations", {"items": [{"evidence_id": "e1", "title": "粮油储藏", "text": "原文", "score": 0.9}]}),
        _frame("done", {"finish_reason": "stop"}),
    ]
    events = await preflight_openai_stream(_agen(frames), return_after_meta=True)
    text = "".join([
        chunk
        async for chunk in openai_stream(
            events, completion_id="chatcmpl-r1", model="grain-storage-agent",
            created=1, emit_openwebui_status=True,
        )
    ])
    payloads = _sse_payloads(text)
    # 流顺序：role chunk → status(running) → status(complete) → 内容 chunks → source → finish → [DONE]
    assert '"role":"assistant"' in payloads[0]
    assert any('"content":"低温"' in p for p in payloads)
    assert any('"content":"储粮"' in p for p in payloads)
    statuses = [p for p in payloads if '"type":"status"' in p]
    assert len(statuses) == 2 and '"done":false' in statuses[0] and '"done":true' in statuses[1]
    assert any('"type":"source"' in p and '"e1"' in p for p in payloads)
    assert '"finish_reason":"stop"' in payloads[-2]
    assert payloads[-1] == "[DONE]"


async def test_stream_protocol_violation_is_safe_error():
    async def bad():
        yield "garbage\r\n\r\n"
    text = "".join([
        chunk
        async for chunk in openai_stream(
            bad(), completion_id="c", model="m", created=1,
        )
    ])
    payloads = _sse_payloads(text)
    assert "WORKFLOW_PROTOCOL_ERROR" in payloads[-2]
    assert payloads[-1] == "[DONE]"


async def test_collect_non_streaming_completion():
    frames = [
        _frame("meta", {}),
        _frame("delta", {"content": "答案"}),
        _frame("done", {}),
    ]
    result = await collect_openai_completion(
        _agen(frames), completion_id="c1", model="m", created=1,
    )
    assert result["object"] == "chat.completion"
    assert result["choices"][0]["message"]["content"] == "答案"
    assert result["sources"] == []


def test_build_workflow_message_packs_recent_turns():
    messages = [
        ("user", "第一问"), ("assistant", "第一答"),
        ("user", "第二问"), ("assistant", "第二答"),
        ("user", "那温度呢"),
    ]
    packed = build_workflow_message(messages, enabled=True, max_turns=6, max_chars=4000)
    assert "第一问" in packed and "第二答" in packed
    assert packed.rstrip().endswith("那温度呢")


def test_build_workflow_message_disabled_returns_last_user_only():
    messages = [("user", "旧问题"), ("assistant", "旧回答"), ("user", "新问题")]
    assert build_workflow_message(messages, enabled=False, max_turns=6, max_chars=4000) == "新问题"


def test_build_workflow_message_respects_turn_cap():
    messages = []
    for i in range(10):
        messages += [("user", f"问{i}"), ("assistant", f"答{i}")]
    messages.append(("user", "当前"))
    packed = build_workflow_message(messages, enabled=True, max_turns=2, max_chars=4000)
    assert "问9" in packed and "答9" in packed
    assert "问8" in packed
    assert "问7" not in packed
```

（pytest.ini 已是 `asyncio_mode=auto`，异步测试直接写。）

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/unit/test_openai_compat.py -q`
Expected: FAIL（`ModuleNotFoundError: app.services.openai_compat`）

- [ ] **Step 3: 移植并改造**

```bash
git show develop-openwebUI:app/services/openai_compat.py > app/services/openai_compat.py
```

对拷贝结果做四处确定性修改：

1. 删除 `from app.services.learning_artifacts import learning_artifact_embed` 与 `from app.services.learning_tasks import (LearningTaskType, status_for)`，替换为：

```python
_STATUS_RUNNING = "正在检索粮储知识库并核对依据"
_STATUS_COMPLETE = "已核对知识库依据"
```

2. `openai_stream` 签名改为：

```python
async def openai_stream(
    events: AsyncIterator[str],
    *,
    completion_id: str,
    model: str,
    created: int,
    emit_openwebui_status: bool = False,
) -> AsyncIterator[str]:
```

函数体首行 `task_status = status_for(task_type)` 删除；`task_status.running` → `_STATUS_RUNNING`，`task_status.complete` → `_STATUS_COMPLETE`（共 4 处）；`done` 分支中 `embed = learning_artifact_embed(...)` 到 `if emit_openwebui_learning_artifact ...` 整个 embeds 块删除。

3. 文件末尾新增历史打包（D8）：

```python
def build_workflow_message(
    messages: list[tuple[str, str]],
    *,
    enabled: bool,
    max_turns: int,
    max_chars: int,
) -> str:
    """Compose AGENT_USER_INPUT: packed recent history + last user message.

    ``messages`` is the ordered (role, content) list from the request.
    A "turn" is a user/assistant pair; only complete pairs are packed,
    newest first until max_turns or max_chars is reached.
    """
    last_index = max(
        index
        for index, (role, content) in enumerate(messages)
        if role == "user" and content
    )
    last_user = messages[last_index][1]
    if not enabled:
        return last_user
    candidates = messages[:last_index]
    pairs: list[tuple[str, str]] = []
    index = len(candidates)
    while index >= 2 and len(pairs) < max_turns:
        user_role, user_text = candidates[index - 2]
        asst_role, asst_text = candidates[index - 1]
        if user_role == "user" and asst_role == "assistant" and user_text and asst_text:
            pairs.append((user_text, asst_text))
        index -= 2
    pairs.reverse()
    lines: list[str] = []
    total = 0
    for user_text, asst_text in pairs:
        block = f"用户: {user_text}\n助手: {asst_text}"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    if not lines:
        return last_user
    return "[对话历史]\n" + "\n".join(lines) + "\n[当前问题]\n" + last_user
```

4. 从 `develop-openwebUI:tests/unit/test_openai_compat.py`（786 行）中把**仅涉及协议机器**的测试合并进 `tests/unit/test_openai_compat.py`：先 `git show develop-openwebUI:tests/unit/test_openai_compat.py > /tmp/oc_test_ref.py`，`grep -n "def test_" /tmp/oc_test_ref.py` 列出全部测试，拷贝不引用 `LearningTaskType`/`status_for`/`learning_artifact`/`embeds`/`course_name` 的用例并适配签名（`openai_stream` 已无 `task_type`/`emit_openwebui_learning_artifact` 参数）；引用上述符号的用例整段删除。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/unit/test_openai_compat.py -q`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add app/services/openai_compat.py tests/unit/test_openai_compat.py
git commit -m "feat(app): port OpenAI-compat stream translator, drop learning-task deps, add history packing"
```

---

### Task 4: 移植 `app/api/openai_compat.py` + `app/main.py` 装配

**Files:**
- Create: `app/api/openai_compat.py`
- Modify: `app/main.py`（三处）
- Test: `tests/contract/test_openai_compat_api.py`（Task 5 落地，本任务先让服务可装配）

**Interfaces:**
- Consumes: Task 1 的 settings 字段；Task 2 的 schemas；Task 3 的 `build_workflow_message`/`openai_stream`/`preflight_openai_stream`/`collect_openai_completion`/`OpenAICompatUpstreamError`；现有 `WorkflowGateway`（`app/services/workflow_gateway.py`）。
- Produces: `router`（`GET /v1/models`、`POST /v1/chat/completions`）、`auth_middleware`、`openai_error_response(...)`。

- [ ] **Step 1: 移植并改造**

```bash
git show develop-openwebUI:app/api/openai_compat.py > app/api/openai_compat.py
```

对拷贝结果做以下确定性修改：

1. 删除 `from app.services.learning_tasks import LearningTurnResolver`；`from app.services.openai_compat import ...` 的导入清单中追加 `build_workflow_message`。
2. `chat_completions` 内把：

```python
    learning_turn = LearningTurnResolver.resolve(
        [(item.role, item.content) for item in payload.messages]
    )
    user_message = learning_turn.workflow_message
    task_type = learning_turn.task_type
```

替换为：

```python
    settings = request.app.state.settings
    user_message = build_workflow_message(
        [(item.role, item.content) for item in payload.messages],
        enabled=settings.openai_compat_history_enabled,
        max_turns=settings.openai_compat_history_max_turns,
        max_chars=settings.openai_compat_history_max_chars,
    )
    task_type = "knowledge_qa"
```

3. `gateway.stream(..., task_type=task_type.value, ...)` 改为 `task_type=task_type`。
4. `openai_stream(...)` 调用删除 `emit_openwebui_learning_artifact`、`course_name`、`task_type` 三个实参。
5. 函数内其余 `request.app.state.settings.xxx` 引用保持不变（字段名与 Task 1 新增一致）。

- [ ] **Step 2: `app/main.py` 三处装配**

1. 第 11 行 `from app.api import cases, chat, health, sources` 改为 `from app.api import cases, chat, health, openai_compat, sources`。
2. `application.add_middleware(RequestIdMiddleware)` 之后追加 `application.middleware("http")(openai_compat.auth_middleware)`。
3. `request_validation_error_handler` 函数体开头追加：

```python
        if request.url.path == "/v1/chat/completions":
            return openai_compat.openai_error_response(
                status_code=422,
                message="聊天请求无效",
                error_type="invalid_request_error",
                code="invalid_request_error",
            )
```

4. `application.include_router(health.router)` 之后追加 `application.include_router(openai_compat.router)`。

- [ ] **Step 3: import 冒烟**

Run: `python -c "import app.main"`
Expected: 无异常（注意：本机沙箱中该命令已在 settings.local.json 允许列表内）

- [ ] **Step 4: Commit**

```bash
git add app/api/openai_compat.py app/main.py
git commit -m "feat(app): wire OpenAI-compatible /v1/models and /v1/chat/completions"
```

---

### Task 5: 移植契约测试并适配

**Files:**
- Create: `tests/contract/test_openai_compat_api.py`

**Interfaces:**
- Consumes: Task 1–4 全部产物。

- [ ] **Step 1: 移植**

```bash
git show develop-openwebUI:tests/contract/test_openai_compat_api.py > tests/contract/test_openai_compat_api.py
```

- [ ] **Step 2: 适配（逐条执行）**

1. `grep -n "vector_store" tests/contract/test_openai_compat_api.py`：删除 `ServiceContainer(...)` 调用中的 `vector_store=None` 实参（webui 分支容器无此字段）。
2. `grep -n "LearningTaskType\|task_type\|embeds\|练习\|课程总结\|study_planning\|course_summary" tests/contract/test_openai_compat_api.py`：任务路由参数化用例与 embeds 用例整段删除。
3. `_settings()` 工厂函数：对照 webui 分支 `Settings` 字段裁剪（删除 embedding/bailian/vector 相关键，保留 chatdoc/maas/workflow 键 + 新增 `openai_compat_*` 键），或改为直接构造真实 `Settings(...)`（推荐，与 Task 1 测试同款参数全集 + `openai_compat_history_enabled=True`）。
4. 本地 provider（`LocalWorkflow`/`_local_provider_client`）相关用例与夹具整段删除（webui 无 `workflow_provider` 设置）。
5. 新增历史打包契约用例：

```python
def test_history_packed_into_workflow_input(contract_client, recording_workflow):
    response = contract_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer test-compat-key"},
        json={
            "model": "grain-storage-agent",
            "stream": False,
            "messages": [
                {"role": "user", "content": "什么是低温储粮"},
                {"role": "assistant", "content": "指利用低温抑制害虫霉菌"},
                {"role": "user", "content": "那仓房气密性呢"},
            ],
        },
    )
    assert response.status_code == 200
    sent = recording_workflow.last_parameters["AGENT_USER_INPUT"]
    assert "低温储粮" in sent and "仓房气密性" in sent
    assert recording_workflow.last_parameters["TASK_TYPE"] == "knowledge_qa"
```

（`recording_workflow`/`contract_client` 夹具名沿用移植文件中的实际定义；断言对象按 `RecordingWorkflow.stream(parameters, uid)` 的真实记录结构调整。）

- [ ] **Step 3: 运行并修到全绿**

Run: `python -m pytest tests/contract/test_openai_compat_api.py -q`
Expected: 全绿（移植后约 15–18 个用例）

- [ ] **Step 4: 全量离线回归**

Run: `python -m pytest -m "not online" -q`
Expected: 全绿（基线 626 passed + 新增）

- [ ] **Step 5: Commit**

```bash
git add tests/contract/test_openai_compat_api.py
git commit -m "test(app): port OpenAI-compat contract tests, adapt to ChatDoc backend"
```

---

## Phase B：`services/webui` 应用服务

### Task 6: 骨架（settings / events stub / db / requirements）

**Files:**
- Create: `services/webui/requirements.txt`、`services/webui/pytest.ini`、`services/webui/.env.example`
- Create: `services/webui/webui/__init__.py`（空）、`services/webui/webui/settings.py`、`services/webui/webui/events.py`、`services/webui/webui/internal/__init__.py`（空）、`services/webui/webui/internal/db.py`
- Test: `services/webui/tests/test_smoke.py`

**Interfaces:**
- Produces: `webui.settings`（`DATA_DIR/DATABASE_URL/WEBUI_SECRET_KEY/WEBUI_AUTH/JWT_EXPIRES_IN/APP_UPSTREAM_BASE_URL/OPENAI_COMPAT_API_KEY/FRONTEND_BUILD_DIR/CORS_ALLOW_ORIGIN` + `validate_startup()`）；`webui.events.publish_event(...)`（no-op）、`webui.events.EVENTS`；`webui.internal.db`（`Base`、`JSONField`、`async_engine`、`get_async_session`、`get_async_db`、`get_async_db_context`、`create_all_tables`）。

- [ ] **Step 1: 写失败测试**

`services/webui/tests/test_smoke.py`：

```python
def test_settings_and_db_importable():
    from webui import events, settings
    from webui.internal import db

    assert settings.DATABASE_URL
    assert hasattr(db, "Base") and hasattr(db, "create_all_tables")
    assert events.publish_event is not None
```

`services/webui/pytest.ini`：

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`services/webui/requirements.txt`：

```text
fastapi
uvicorn
pydantic
sqlalchemy[asyncio]
aiosqlite
PyJWT
bcrypt
httpx
```

（dev 依赖 pytest/pytest-asyncio 已在 conda LLM 环境；不重复列。）

- [ ] **Step 2: 运行确认失败**

Run: `cd services/webui && /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python -m pytest tests/test_smoke.py -q`
Expected: FAIL（`ModuleNotFoundError: webui`）

- [ ] **Step 3: 实现**

`webui/settings.py`：

```python
"""Minimal settings for the extracted webui service (replaces open_webui.env)."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR}/webui.db")
WEBUI_SECRET_KEY = os.environ.get("WEBUI_SECRET_KEY", "")
WEBUI_AUTH = os.environ.get("WEBUI_AUTH", "true").strip().lower() != "false"
JWT_EXPIRES_IN = os.environ.get("JWT_EXPIRES_IN", "4w")

APP_UPSTREAM_BASE_URL = os.environ.get(
    "APP_UPSTREAM_BASE_URL", "http://127.0.0.1:8000"
).rstrip("/")
OPENAI_COMPAT_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", "")

FRONTEND_BUILD_DIR = os.environ.get(
    "FRONTEND_BUILD_DIR",
    str(BASE_DIR.parent.parent / "frontend" / "webui" / "build"),
)
CORS_ALLOW_ORIGIN = os.environ.get("CORS_ALLOW_ORIGIN", "*")


def validate_startup() -> None:
    if WEBUI_AUTH and not WEBUI_SECRET_KEY:
        raise RuntimeError(
            "WEBUI_SECRET_KEY must be set when WEBUI_AUTH is enabled"
        )
```

`webui/events.py`：

```python
"""No-op event stub replacing open_webui.events (audit/webhook 不取）。"""


class EVENTS:
    AUTH_LOGIN = "auth.login"
    AUTH_SIGNUP = "auth.signup"
    USER_CREATED = "user.created"


async def publish_event(*args, **kwargs) -> None:
    return None
```

`webui/internal/db.py`（极简重写，只保留 SQLite 异步路径；接口名与参考一致）：

```python
"""Minimal async SQLAlchemy wiring (SQLite-only) for the extracted service."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import MetaData, types
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

from webui.settings import DATABASE_URL


class JSONField(types.TypeDecorator):
    """TEXT-backed JSON storage (stdlib json codec)."""

    impl = types.UnicodeText
    cache_ok = True

    def process_bind_param(self, value: Any, dialect) -> Any:
        return json.dumps(value, ensure_ascii=False) if value is not None else None

    def process_result_value(self, value: Any, dialect) -> Any:
        return json.loads(value) if value is not None else None

    def copy(self, **kwargs):
        return JSONField()


def _async_url(url: str) -> str:
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


async_engine = create_async_engine(
    _async_url(DATABASE_URL),
    connect_args=(
        {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
    ),
)
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

Base = declarative_base(metadata=MetaData())


async def get_async_session():
    async with AsyncSessionLocal() as db:
        yield db


@asynccontextmanager
async def get_async_db():
    async with AsyncSessionLocal() as db:
        yield db


@asynccontextmanager
async def get_async_db_context(db: AsyncSession | None = None):
    if isinstance(db, AsyncSession):
        yield db
    else:
        async with get_async_db() as session:
            yield session


async def create_all_tables() -> None:
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

`services/webui/.env.example`：

```bash
WEBUI_SECRET_KEY=change-me
OPENAI_COMPAT_API_KEY=match-app-env
APP_UPSTREAM_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 4: 安装依赖并运行测试**

Run: `python -m pip install -r services/webui/requirements.txt`（如需）
Run: `cd services/webui && python -m pytest tests/test_smoke.py -q`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add services/webui/
echo "services/webui/data/" >> .gitignore
git add .gitignore
git commit -m "feat(webui-service): package skeleton with settings, event stub, sqlite db wiring"
```

---

### Task 7: 提取 models（config / users / auths / chat_messages / chats）

**Files:**
- Create: `services/webui/webui/models/__init__.py`（空）及五个模型文件
- Test: `services/webui/tests/test_models.py`

**Interfaces:**
- Produces:
  - `webui.models.config.Config`（`configure(defaults=...)`、`get(key, default)`、`upsert(dict)`）
  - `webui.models.users.User`、`UserModel`、`Users`（`has_users`、`get_num_users`、`get_user_by_id`、`get_user_by_email`、`insert_new_user`、`update_user_role_by_id`、`update_user_settings_by_id`、`get_users`）
  - `webui.models.auths.Auth`、`Auths`（`authenticate_user_by_email`、`insert_new_auth`、`update_password_by_id`）
  - `webui.models.chats.Chat`、`ChatModel`、`ChatForm`、`Chats`（`insert_new_chat`、`get_chat_list_by_user_id`、`get_chat_by_id_and_user_id`、`update_chat_by_id`、`delete_chat_by_id_and_user_id`、`upsert_message_to_history`、`get_current_message_id`）
  - `webui.models.chat_messages.ChatMessage`（表定义保留，第一阶段不写双写）

**提取规则（对每个文件同样适用）：**
1. 从 `example/openwebui/backend/open_webui/models/<name>.py` 拷贝**保留集**符号（逐字保留函数体），`open_webui.` 前缀改 `webui.`。
2. `from open_webui.env import ...` → `from webui.settings import ...`，仅保留 settings 符号清单内的名字（`ENABLE_ADMIN_CHAT_ACCESS` 加入 settings.py，默认 `False`）。
3. 引用未提取模块（access_grants/automations/folders/tags/shared_chats/files/groups/utils.access_control）的方法**整个不提取**。
4. `Config.get(...)` 对未种子 key 返回 default——配合 Task 11 的种子集（`ui.default_user_role=user`、`auth.jwt_expiry`、`ui.enable_signup=true`、`ui.enable_login_form=true`）。
5. `models/chats.py` 保留 `upsert_message_to_history` 时**逐字**拷贝（参考文件 959-1001 行，消息图核心，含 parentId/childrenIds/currentId 与 role 推断语义）；`insert_new_chat` 中 chat_message 双写 try 块删除；`ChatFile`/`ChatFileModel` 不提取；`_repair_chat_current_id`/`_sanitize_chat_row`/`_clean_null_bytes`/`get_current_message_id` 保留。
6. `models/users.py` 只保留上述列出方法；`models/auths.py` 同；不提取 API key 相关（`ApiKey` 表、`authenticate_user_by_api_key`）。
7. `models/chat_messages.py` 保留表与 `ChatMessageModel`；`utils/response` 的引用若仅为类型标注则内联替代。

- [ ] **Step 1: 写失败测试**

先建 `services/webui/tests/conftest.py`（env 必须先于一切 webui.* import；全会话共用临时 DB，`clean_db` autouse 清表；Task 9 再追加 `client` fixture）：

```python
import asyncio
import os
import tempfile
from pathlib import Path

# ── 必须先于一切 webui.* import ──
_TMP = Path(tempfile.mkdtemp(prefix="webui-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DATA_DIR"] = str(_TMP)
os.environ["WEBUI_SECRET_KEY"] = "test-secret"
os.environ["OPENAI_COMPAT_API_KEY"] = "test-compat-key"

import pytest


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    from webui.internal.db import create_all_tables

    asyncio.run(create_all_tables())


@pytest.fixture(autouse=True)
def clean_db():
    yield
    from webui.internal.db import AsyncSessionLocal
    from webui.models.auths import Auth
    from webui.models.chat_messages import ChatMessage
    from webui.models.chats import Chat
    from webui.models.config import Config
    from webui.models.users import User

    async def _wipe() -> None:
        async with AsyncSessionLocal() as db:
            for table in (ChatMessage, Chat, Auth, User, Config):
                await db.execute(table.__table__.delete())
            await db.commit()

    asyncio.run(_wipe())
```

`services/webui/tests/test_models.py`：

```python
async def test_user_auth_chat_roundtrip():
    from webui.models.auths import Auths
    from webui.models.chats import Chats, ChatForm
    from webui.models.users import Users

    user = await Auths.insert_new_auth(
        email="a@b.c", password="hashed", name="甲", role="user",
    )
    assert await Users.has_users()
    assert await Users.get_num_users() == 1

    chat = await Chats.insert_new_chat(
        id="c1",
        user_id=user.id,
        form_data=ChatForm(chat={
            "title": "测试会话",
            "models": ["grain-storage-agent"],
            "history": {"messages": {}, "currentId": None},
            "messages": [],
        }),
    )
    assert chat.id == "c1"

    history = {}
    Chats.upsert_message_to_history(
        history, "m1",
        {"id": "m1", "role": "user", "content": "问题", "parentId": None,
         "childrenIds": [], "timestamp": 1},
    )
    Chats.upsert_message_to_history(
        history, "m2",
        {"id": "m2", "role": "assistant", "content": "回答",
         "parentId": "m1", "childrenIds": [], "timestamp": 2,
         "sources": [{"source": {"id": "e1", "name": "粮油储藏"}}]},
    )
    assert history["currentId"] == "m2"
    assert history["messages"]["m2"]["role"] == "assistant"
    assert history["messages"]["m2"]["sources"][0]["source"]["id"] == "e1"

    loaded = await Chats.get_chat_by_id_and_user_id("c1", user.id)
    assert loaded is not None and loaded.user_id == user.id
    assert await Chats.delete_chat_by_id_and_user_id("c1", user.id) is True
```

注意：`upsert_message_to_history` 是 `@staticmethod`，接受可变 `history` dict（`history.setdefault('messages', {})`）。

- [ ] **Step 2: 运行确认失败 → 提取 → 运行确认通过**

Run: `cd services/webui && python -m pytest tests/test_models.py -q`

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/models/ services/webui/tests/test_models.py
git commit -m "feat(webui-service): extract config/users/auths/chats/chat_messages models (trimmed)"
```

---

### Task 8: 提取 `webui/utils/auth.py` + `webui/utils/misc.py`

**Files:**
- Create: `services/webui/webui/utils/__init__.py`（空）、`auth.py`、`misc.py`
- Test: `services/webui/tests/test_utils_auth.py`

**Interfaces:**
- Produces: `create_token(data, expires_delta=None)`、`decode_token(token)`、`get_password_hash(password)`、`verify_password(plain, hashed)`、`get_current_user`、`get_verified_user`、`get_admin_user`（FastAPI Depends 用）；`misc.parse_duration(text)`。

**提取规则：**
- 从 `example/openwebui/backend/open_webui/utils/auth.py` 逐字提取上述符号（含其直接 helper）；**删除** API key 认证（`get_current_user_by_api_key`）、加密 token（AESGCM/ed25519/`JSONCodec`）、`requests` 出站调用、trusted-header 分支；`open_webui.env` → `webui.settings`（只用 `WEBUI_SECRET_KEY`、`WEBUI_AUTH`）。
- `misc.parse_duration` 从 `utils/misc.py` 逐字提取（支持 `"4w"/"7d"/"30m"` 形式），其余 misc 函数不取。

- [ ] **Step 1: 写失败测试**

```python
def test_token_roundtrip_and_expiry():
    from webui.utils.auth import create_token, decode_token

    token = create_token(data={"id": "u1"})
    assert decode_token(token)["id"] == "u1"


def test_password_hash_verify():
    from webui.utils.auth import get_password_hash, verify_password

    hashed = get_password_hash("secret-123")
    assert verify_password("secret-123", hashed)
    assert not verify_password("wrong", hashed)


def test_parse_duration():
    from datetime import timedelta
    from webui.utils.misc import parse_duration

    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("7d") == timedelta(days=7)
    assert parse_duration("4w") == timedelta(weeks=4)
    assert parse_duration("") is None
```

（参考实现使用 PyJWT（`import jwt`）；提取结果应与之相同，测试不需要额外的 JWT 库 import。）

- [ ] **Step 2: 失败 → 提取 → 通过**

Run: `cd services/webui && python -m pytest tests/test_utils_auth.py -q`

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/utils/ services/webui/tests/test_utils_auth.py
git commit -m "feat(webui-service): extract jwt/password auth utils and parse_duration"
```

---

### Task 9: 提取 `routers/auths.py`（含三处显式偏离）

**Files:**
- Create: `services/webui/webui/routers/__init__.py`（空）、`services/webui/webui/routers/auths.py`
- Test: `services/webui/tests/test_auth.py`

**Interfaces:**
- Produces: `router`（prefix `/api/v1/auths`）：`GET /`（session 用户）、`POST /signin`、`POST /signup`、`POST /signout`、`POST /update/password`。响应外形与参考一致：`{token, token_type, expires_at, id, email, name, role, profile_image_url, permissions}`，其中 **`profile_image_url` 恒为 `""`、`permissions` 恒为 `{}`**（偏离 §6.2.9/.12）。

**提取规则（以参考 `routers/auths.py` 为蓝本逐字提取后修改）：**
- 只保留上述 5 端点 + `create_session_response` + `signup_handler` + 表单模型（`SigninForm`/`SignupForm`/`UpdatePasswordForm`/session 响应模型）。
- 删除：ldap/oauth/api_key/admin config/trusted-header 全部端点与 import（`ldap3`、`aiohttp`、`open_webui.config`、`models.groups`、`models.oauth_sessions`、`utils.groups`、`utils.rate_limit`、`utils.redis`）；模块级 `RateLimiter` 实例化删除。
- **偏离 1**：`signup_handler` 删除 `await Config.upsert({'ui.enable_signup': False})`（保持开放注册，D9）。
- **偏离 2**：`signup_handler` 删除 `apply_default_group_assignment(...)` 调用与 `ui.default_group_id` 读取。
- **偏离 3**：`create_session_response` 删除 `get_permissions(...)`；返回 `permissions: {}`、`profile_image_url: ""`。
- `signup` 端点保留 `ui.enable_signup`/`ui.enable_login_form` 检查（种子值均为 true，见 Task 11）；`ENABLE_INITIAL_ADMIN_SIGNUP` 分支删除（首用户注册始终允许）。
- `publish_event` 改调 `webui.events`（no-op）。
- 邮箱/密码校验：`validate_email_format`/`validate_password` 从参考 `utils/validate.py` 逐字提取到 `webui/utils/validate.py`。
- Cookie：`signin`/`signup` 沿用参考 `set_cookie` 行为（`token` HttpOnly cookie + JSON token 双发）；cookie 相关常量 `WEBUI_AUTH_COOKIE_SAME_SITE="lax"`、`WEBUI_AUTH_COOKIE_SECURE=False` 加入 settings。

- [ ] **Step 1: 写失败测试（TestClient 端到端）**

`services/webui/tests/conftest.py`（**关键：env 必须在任何 webui.* import 之前设置**；整个测试会话共用一个临时 DB 文件，靠 `clean_db` autouse fixture 在测试间清表，避免模块缓存导致的多 DB 混乱）：

```python
import asyncio
import os
import tempfile
from pathlib import Path

# ── 必须先于一切 webui.* import ──
_TMP = Path(tempfile.mkdtemp(prefix="webui-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["DATA_DIR"] = str(_TMP)
os.environ["WEBUI_SECRET_KEY"] = "test-secret"
os.environ["OPENAI_COMPAT_API_KEY"] = "test-compat-key"

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    from webui.internal.db import create_all_tables

    asyncio.run(create_all_tables())


@pytest.fixture(autouse=True)
def clean_db():
    yield
    from webui.internal.db import AsyncSessionLocal
    from webui.models.auths import Auth
    from webui.models.chat_messages import ChatMessage
    from webui.models.chats import Chat
    from webui.models.config import Config
    from webui.models.users import User

    async def _wipe() -> None:
        async with AsyncSessionLocal() as db:
            for table in (ChatMessage, Chat, Auth, User, Config):
                await db.execute(table.__table__.delete())
            await db.commit()

    asyncio.run(_wipe())


@pytest.fixture()
def client():
    from webui.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
```

（`clean_db` 清 Config 表意味着每个测试后种子被清；`create_app` 的 lifespan 在下次进入时重新种子——Task 11 的种子逻辑必须幂等。）

`services/webui/tests/test_auth.py`：

```python
def test_signup_first_user_becomes_admin_and_signup_stays_open(client):
    first = client.post("/api/v1/auths/signup", json={
        "name": "管理员", "email": "admin@example.com", "password": "secret-123",
    })
    assert first.status_code == 200, first.text
    assert first.json()["role"] == "admin"
    assert first.json()["permissions"] == {}
    assert first.json()["profile_image_url"] == ""

    second = client.post("/api/v1/auths/signup", json={
        "name": "学生", "email": "u@example.com", "password": "secret-456",
    })
    assert second.status_code == 200, second.text
    assert second.json()["role"] == "user"  # 开放注册不自动关闭（偏离 1）


def test_signin_and_session_user(client):
    client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": "a@example.com", "password": "secret-123",
    })
    signin = client.post("/api/v1/auths/signin", json={
        "email": "a@example.com", "password": "secret-123",
    })
    assert signin.status_code == 200
    token = signin.json()["token"]

    session = client.get("/api/v1/auths/", headers={"Authorization": f"Bearer {token}"})
    assert session.status_code == 200
    assert session.json()["email"] == "a@example.com"

    assert client.get("/api/v1/auths/").status_code == 401


def test_signin_wrong_password(client):
    client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": "a@example.com", "password": "secret-123",
    })
    bad = client.post("/api/v1/auths/signin", json={
        "email": "a@example.com", "password": "wrong",
    })
    assert bad.status_code in (400, 401)
```

- [ ] **Step 2: 失败 → 提取 → 通过**

Run: `cd services/webui && python -m pytest tests/test_auth.py -q`
（本任务测试依赖 Task 10 的 `webui.main.create_app`；若 main 尚未存在，先在 Task 11 建好最小 main 再回来跑绿——或按 Phase B 顺序把 Task 11 的最小装配提前。实施时允许把 Task 11 Step 3 的最小 `create_app`（只挂 auths router + lifespan）作为本任务的一部分先行落地。）

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/routers/auths.py services/webui/tests/
git commit -m "feat(webui-service): auth router (signin/signup/session) with open-signup deviations"
```

---

### Task 10: 提取 `routers/chats.py`（列表/详情/删除，404 偏离）

**Files:**
- Create: `services/webui/webui/routers/chats.py`
- Test: `services/webui/tests/test_chats.py`

**Interfaces:**
- Produces: `router`（prefix `/api/v1/chats`）：`GET /`（当前用户会话列表）、`GET /{id}`（属主详情，**非属主/不存在 → 404**，偏离参考的 401）、`DELETE /{id}`（属主删除）。响应模型沿用参考 `ChatModel`/`ChatResponse` 外形。

**提取规则：** 逐字提取这三端点及其直接依赖（`Chats` 表方法、响应模型）；删除 share/fork/clone/folder/tags/pin/archive/stats 等其余端点；`get_chat_by_id_for_user` 的 access_grants/folders 分支不提取（只保留属主判定）；非属主分支改写：

```python
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
```

- [ ] **Step 1: 写失败测试**

```python
def _signup(client, email, name="甲"):
    res = client.post("/api/v1/auths/signup", json={
        "name": name, "email": email, "password": "secret-123",
    })
    return res.json()["token"]


def _new_chat(client, token):
    import uuid
    chat_id = str(uuid.uuid4())
    res = client.post(
        "/api/chat/completions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": "grain-storage-agent",
            "chat_id": chat_id,
            "messages": [{"role": "user", "content": "低温储粮如何抑虫"}],
            "stream": True,
        },
    )
    assert res.status_code == 200, res.text
    return chat_id
```

```python
def test_chat_list_detail_delete_and_isolation(client):
    token_a = _signup(client, "a@example.com")
    token_b = _signup(client, "b@example.com", name="乙")

    # 用 stub 上游产生一个会话（上游 stub 在 conftest 中装配，见 Task 12）
    chat_id = _new_chat(client, token_a)

    listing = client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token_a}"})
    assert listing.status_code == 200
    assert any(item["id"] == chat_id for item in listing.json())

    detail = client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_a}"})
    assert detail.status_code == 200

    # 非属主 → 404（偏离参考 401）
    assert client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404
    assert client.delete(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404

    assert client.delete(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token_a}"}).status_code == 200
    assert client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token_a}"}).json() == []

    # 未登录
    assert client.get("/api/v1/chats/").status_code == 401
```

（本测试与 Task 12 的 stub 上游耦合，实施顺序上并入 Task 12 一起跑绿亦可。）

- [ ] **Step 2: 失败 → 提取 → （随 Task 12）通过**

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/routers/chats.py services/webui/tests/test_chats.py
git commit -m "feat(webui-service): chats router (list/detail/delete) with owner-only 404 semantics"
```

---

### Task 11: slim `main.py` 装配 + `/api/version` + `/api/models` 代理 + 静态托管

**Files:**
- Create: `services/webui/webui/main.py`、`services/webui/webui/utils/upstream.py`
- Test: 随 conftest 的 `create_app` 被各测试覆盖

**Interfaces:**
- Produces: `create_app() -> FastAPI`；lifespan 内 `validate_startup()` → `create_all_tables()` → `Config.configure(defaults={...})` 并种子四个 key；挂载 auths/chats/completions router；`GET /api/version` → `{"version": "0.1.0"}`；`GET /api/models`（登录用户，代理到 `app GET /v1/models`，带服务密钥）；`GET /api/config` → `{"status": True, "name": "粮储智研助手", "version": "0.1.0"}`；SPA 静态托管 `FRONTEND_BUILD_DIR`（存在才挂）。

`webui/utils/upstream.py`：

```python
"""HTTP client toward the grain domain service (app)."""

from collections.abc import AsyncIterator

import httpx

from webui.settings import APP_UPSTREAM_BASE_URL, OPENAI_COMPAT_API_KEY


def service_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {OPENAI_COMPAT_API_KEY}"}
    if extra:
        headers.update(extra)
    return headers


def build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=APP_UPSTREAM_BASE_URL,
        timeout=httpx.Timeout(120.0, connect=10.0),
    )


async def get_json(path: str) -> httpx.Response:
    async with build_client() as client:
        response = await client.get(path, headers=service_headers())
        return response


async def stream_post(
    path: str, *, json_body: dict, headers: dict[str, str]
) -> AsyncIterator[bytes]:
    """Yield raw upstream bytes; caller owns framing. Test hook: 替换 build_client。"""
    async with build_client() as client:
        async with client.stream(
            "POST", path, json=json_body, headers=headers
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                yield chunk
```

（`build_client` 作为唯一测试替身注入点：conftest 中 monkeypatch 为 `httpx.AsyncClient(transport=httpx.MockTransport(...), base_url="http://testserver")`。）

- [ ] **Step 1: 写失败测试**

```python
def test_version_and_config(client):
    assert client.get("/api/version").json()["version"] == "0.1.0"
    config = client.get("/api/config")
    assert config.status_code == 200 and config.json()["status"] is True


def test_models_requires_login(client):
    assert client.get("/api/models").status_code == 401
```

- [ ] **Step 2: 失败 → 实现 → 通过**

lifespan 种子（Task 7 规则 4 的落地）：

```python
CONFIG_DEFAULTS = {
    "ui.default_user_role": "user",
    "auth.jwt_expiry": settings.JWT_EXPIRES_IN,
    "ui.enable_signup": True,
    "ui.enable_login_form": True,
}
```

启动时对每个 key `if await Config.get(key) is None: await Config.upsert({key: value})`。

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/main.py services/webui/webui/utils/upstream.py
git commit -m "feat(webui-service): slim app assembly, version/config endpoints, upstream client"
```

---

### Task 12: slim `/api/chat/completions`（编排 + 消息图落库）

**Files:**
- Create: `services/webui/webui/routers/completions.py`
- Test: `services/webui/tests/test_completions.py`

**Interfaces:**
- Consumes: Task 7 的 `Chats`/`ChatForm`、Task 8 的 `get_verified_user`、Task 11 的 `upstream.stream_post`/`service_headers`。
- Produces: `POST /api/chat/completions`（Bearer JWT）。请求 `{model, messages, chat_id?, stream?}`；响应 SSE；首个事件为自定义 `data: {"event":{"type":"chat_id","data":{"chat_id":"..."}}}`；落库契约严格按 spec §6.3。

**实现规格（新写，约 200 行）：**

```text
1. get_verified_user；解析请求体（pydantic：model str、messages[{role,content}]、
   chat_id 可选、stream 默认 true）。
2. chat_id 存在 → Chats.get_chat_by_id_and_user_id；None → 404。
   不存在 → 生成新 chat_id（uuid4），Chats.insert_new_chat(ChatForm(chat={
     "title": 末条 user 消息前 40 字符, "models": [model],
     "history": {"messages": {}, "currentId": None}, "messages": []}))。
3. 组装转发 messages：DB history 从 currentId 沿 parentId 回溯成链
   （content 为 list[blocks] 时拼接 type=="text" 块的 text），追加本轮末条 user 消息。
4. StreamingResponse：先 yield chat_id 事件，再逐字节转发上游
   upstream.stream_post("/v1/chat/completions",
     json_body={"model": model, "messages": messages, "stream": True},
     headers=service_headers({"X-OpenWebUI-Chat-Id": chat_id,
                              "X-OpenWebUI-User-Id": user.id}))
   同时缓冲：chat.completion.chunk 的 delta.content 拼接为 assistant 全文；
   {"event":{"type":"source",...}} 收集进 sources 列表；
   {"error": ...} 记录失败标记。
5. 流正常结束（见到 data: [DONE] 且无 error）→ _persist_turn：
   user 消息 {id: uuid4, role:"user", content, parentId: 旧 currentId 或 None,
              childrenIds: [], timestamp}
   assistant 消息 {id: uuid4, role:"assistant", content: 全文,
                   parentId: user_id_msg, childrenIds: [], timestamp, sources}
   依次 Chats.upsert_message_to_history(chat.chat["history"], ...)，
   父消息 childrenIds 追加；chat.chat["messages"] 同步为 currentId 回溯链；
   chat.current_message_id = assistant id；update_chat_by_id 落库。
6. 上游 HTTP 错误（stream_post raise）→ 先 yield
   data: {"error": {"message": "粮储问答服务暂时不可用", "code": "WORKFLOW_UNAVAILABLE"}}
   再 yield data: [DONE]；流中出现 {"error"} 事件同样视为失败。
   失败时整轮不落库，且**若 chat 是本次请求新建的则将其删除**
   （Chats.delete_chat_by_id_and_user_id），不留空会话（§6.3.7）。
7. 测试替身：conftest monkeypatch upstream.build_client 为 MockTransport，
   返回录制好的 SSE 字节流（含 chunk/source/[DONE]）。
```

- [ ] **Step 1: 写失败测试**

```python
def _signup(client, email="a@example.com"):
    return client.post("/api/v1/auths/signup", json={
        "name": "甲", "email": email, "password": "secret-123",
    }).json()["token"]


def test_completion_streams_persists_and_restores(client):
    token = _signup(client)
    res = client.post("/api/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "低温储粮如何抑制害虫"}],
        "stream": True,
    })
    assert res.status_code == 200
    frames = [f for f in res.text.split("\n\n") if f.startswith("data: ")]
    assert '"type":"chat_id"' in frames[0]
    chat_id = __import__("json").loads(frames[0][6:])["event"]["data"]["chat_id"]

    detail = client.get(f"/api/v1/chats/{chat_id}", headers={"Authorization": f"Bearer {token}"})
    assert detail.status_code == 200
    history = detail.json()["chat"]["history"]
    assert history["currentId"] is not None
    current = history["messages"][history["currentId"]]
    assert current["role"] == "assistant"
    assert current["content"]  # stub 上游全文
    assert current["sources"]  # source 事件已落库
    user_msg = history["messages"][current["parentId"]]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == "低温储粮如何抑制害虫"


def test_completion_upstream_failure_persists_nothing(client):
    # conftest 提供 failing_upstream fixture：MockTransport 返回 502
    token = _signup(client)
    res = client.post("/api/chat/completions", headers={"Authorization": f"Bearer {token}"}, json={
        "model": "grain-storage-agent",
        "messages": [{"role": "user", "content": "会失败的问题"}],
        "stream": True,
    }, )
    assert res.status_code == 200  # SSE 外形保持，错误以事件表达
    assert '"error"' in res.text
    listing = client.get("/api/v1/chats/", headers={"Authorization": f"Bearer {token}"}).json()
    # 失败轮整轮不落库，新建的空 chat 一并撤销
    assert listing == []
```

（conftest 的 MockTransport 路由：`POST /v1/chat/completions` → 录制 SSE；`GET /v1/models` → `{"object":"list","data":[...]}`；失败 fixture 返回 502。录制流内容：meta→2 个 delta→1 条 source→finish chunk→[DONE]，与 Task 3 单测同构。）

- [ ] **Step 2: 失败 → 实现 → 通过**（连同 Task 10 测试一起跑绿）

Run: `cd services/webui && python -m pytest -q`
Expected: 全绿

- [ ] **Step 3: Commit**

```bash
git add services/webui/webui/routers/completions.py services/webui/tests/
git commit -m "feat(webui-service): slim chat completions with message-graph persistence"
```

---

### Task 13: Phase B 全量验证

- [ ] `cd services/webui && python -m pytest -q` 全绿
- [ ] `python -m pytest -m "not online" -q`（仓库根，app 侧）全绿
- [ ] Commit（如有遗留改动）

---

## Phase C：`frontend/webui` 前端

### Task 14: SvelteKit 骨架 + `/auth` 页 + 守卫 layout

**Files:**
- Create: `frontend/webui/package.json`、`svelte.config.js`、`vite.config.ts`、`tsconfig.json`、`src/app.html`、`src/app.css`
- Create: `src/lib/constants.ts`、`src/lib/stores/index.ts`、`src/lib/apis/auths/index.ts`、`src/lib/apis/chats/index.ts`、`src/lib/utils/index.ts`
- Create: `src/routes/+layout.ts`（`ssr=false`）、`src/routes/auth/+page.svelte`、`src/routes/(app)/+layout.svelte`
- Test: `frontend/webui/vitest` 配置 + `src/lib/apis/auths.test.ts`

**实现规格：**

`package.json`（版本以 `npm install` 时解析为准；devDependencies: `@sveltejs/kit@^2`、`@sveltejs/adapter-static`、`svelte@^5`、`vite@^5`（或 kit 2 当前配套）、`typescript`、`tailwindcss@^4`、`@tailwindcss/vite`、`vitest`；dependencies: `marked`、`dompurify`、`dayjs`、`uuid`）：

`svelte.config.js`：

```js
import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  kit: { adapter: adapter({ fallback: 'index.html' }) },
};
```

`vite.config.ts`：

```ts
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: { proxy: { '/api': 'http://127.0.0.1:8080' } },
});
```

`src/routes/+layout.ts`：`export const ssr = false;`（纯 SPA）。`src/app.css` 首行 `@import "tailwindcss";`（Tailwind 4 写法，不需要 tailwind.config 文件）。

`src/lib/apis/auths/index.ts`（Bearer 取自 localStorage，与参考一致）：

```ts
const BASE = '/api/v1/auths';

export async function signin(email: string, password: string) {
  const res = await fetch(`${BASE}/signin`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error('登录失败，请检查邮箱和密码');
  return res.json();
}

export async function signup(name: string, email: string, password: string) {
  const res = await fetch(`${BASE}/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password }),
  });
  if (!res.ok) throw new Error('注册失败，邮箱可能已被使用');
  return res.json();
}

export async function getSessionUser(token: string) {
  const res = await fetch(`${BASE}/`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error('会话已过期');
  return res.json();
}
```

`src/lib/stores/index.ts`：`export const user = writable<User|null>(null); export const config = writable(null); export const chatId = writable('');`

`src/routes/auth/+page.svelte`：登录/注册双模式表单（参考 `example/openwebui/src/routes/auth/+page.svelte` 的表单字段与校验，删除 oauth/trusted-header 分支）；成功后 `localStorage.setItem('token', session.token)` → `goto('/')`。

`src/routes/(app)/+layout.svelte`：onMount 读 token → `getSessionUser` → 失败 `goto('/auth')`；成功渲染侧边栏（对话 / 知识库 / 智能体广场 / 设置——后三项首版为占位路由）+ `<slot>`。

- [ ] **Step 1: 单测（vitest，fetch stub）**

`src/lib/apis/auths.test.ts`：stub `globalThis.fetch`，断言 signin 401 时抛中文错误、成功时返回 token。

- [ ] **Step 2: `npm install` → `npm run build` 必须通过；`npm run test` 绿**

- [ ] **Step 3: Commit**

```bash
git add frontend/webui/
git commit -m "feat(frontend): sveltekit shell with auth page and guard layout"
```

---

### Task 15: 聊天页（发送 → 流式渲染 → 历史恢复）

**Files:**
- Create: `src/lib/apis/chat/index.ts`（`streamChatCompletion`：fetch + ReadableStream 解析 SSE）、`src/lib/utils/sse.ts`（事件解析，纯函数）
- Create: `src/routes/(app)/+page.svelte`、`src/routes/(app)/c/[id]/+page.svelte`
- Create: `src/lib/components/chat/{Chat,MessageList,MessageInput,Citations}.svelte`
- Test: `src/lib/utils/sse.test.ts`

**`src/lib/utils/sse.ts`（核心纯函数，完整实现）：**

```ts
export type ChatStreamEvent =
  | { type: 'chat_id'; chatId: string }
  | { type: 'delta'; content: string }
  | { type: 'status'; description: string; done: boolean }
  | { type: 'source'; source: unknown }
  | { type: 'error'; message: string; code?: string }
  | { type: 'done' };

export function parseSseDataLine(payload: string): ChatStreamEvent | null {
  if (payload === '[DONE]') return { type: 'done' };
  let data: any;
  try { data = JSON.parse(payload); } catch { return null; }
  if (data?.error) {
    return { type: 'error', message: String(data.error.message ?? '服务暂时不可用'), code: data.error.code };
  }
  if (data?.event?.type === 'chat_id') return { type: 'chat_id', chatId: String(data.event.data.chat_id) };
  if (data?.event?.type === 'status') {
    return { type: 'status', description: String(data.event.data?.description ?? ''), done: Boolean(data.event.data?.done) };
  }
  if (data?.event?.type === 'source') return { type: 'source', source: data.event.data };
  const delta = data?.choices?.[0]?.delta?.content;
  if (typeof delta === 'string' && delta) return { type: 'delta', content: delta };
  return null;
}

/** Incremental SSE frame splitter over a text buffer. */
export function createSseParser(onEvent: (e: ChatStreamEvent) => void) {
  let buffer = '';
  return (chunk: string) => {
    buffer += chunk;
    let index;
    while ((index = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, index);
      buffer = buffer.slice(index + 2);
      for (const line of frame.split('\n')) {
        if (line.startsWith('data: ')) {
          const event = parseSseDataLine(line.slice(6));
          if (event) onEvent(event);
        }
      }
    }
  };
}
```

**Chat.svelte 流程规格：**
- 进入 `/c/[id]`：`GET /api/v1/chats/{id}`（Bearer）→ 从 `chat.history` 的 `currentId` 沿 `parentId` 回溯构造消息数组（`createMessagesList` 语义，自写 30 行）→ 渲染。
- 发送：POST `/api/chat/completions`（Bearer，body `{model, messages: [{role:'user',content}], chat_id?}`），用 `createSseParser` 消费响应流：`chat_id` → 更新地址栏 `goto('/c/'+id, {replaceState:true, noScroll:true})`；`delta` → 追加到当前 assistant 气泡；`status` → 状态条；`source` → 累积引用；`error` → 错误横幅（安全文案）；`done` → 结束生成态。
- 消息渲染：`marked` + `dompurify`；引用卡片从消息 `sources` 渲染（名称 + 原文摘要，无页码）。
- MessageInput：极简 textarea，Enter 发送 / Shift+Enter 换行，生成中禁用。

- [ ] **Step 1: `sse.test.ts` 覆盖六种事件 + 跨 chunk 半帧拼接 + 垃圾行忽略**

- [ ] **Step 2: 实现 → `npm run test && npm run build` 绿**

- [ ] **Step 3: Commit**

```bash
git add frontend/webui/
git commit -m "feat(frontend): chat pages with SSE streaming, citations, history restore"
```

---

### Task 16: 占位路由 + 端到端联调验证

**Files:**
- Create: `src/routes/(app)/{knowledge,agents,settings}/+page.svelte`（各 20 行占位：标题 + "即将上线"——属于导航框架，不是 Mock 数据）

- [ ] **Step 1: 双服务真实联调（stub-free 范围内）**

```bash
# 终端 1（app 会因 ChatDoc 66001 未入库而无法启动属预期——本步只验证 services/webui + 前端）
cd services/webui && set -a && source .env && set +a && python -m uvicorn webui.main:app --host 127.0.0.1 --port 8080
# 终端 2
cd frontend/webui && npm run dev
```

手工验收（离线，无真实上游）：注册两个账号、登录、未登录访问 `/` 被重定向 `/auth`。（真实问答流待额度恢复后按 spec §9 补测。）

- [ ] **Step 2: 全量验证**

```bash
python -m pytest -m "not online" -q          # app 侧
cd services/webui && python -m pytest -q      # 应用服务
cd ../../frontend/webui && npm run test && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add frontend/webui/src/routes/
git commit -m "feat(frontend): placeholder routes for knowledge/agents/settings nav"
```

---

## Self-Review 记录（计划作者已核对）

- spec D8 历史打包 → Task 3 Step 3.3 + Task 5 Step 2.5；D9 开放注册 → Task 9 偏离 1；D15 唯一持久化路径 → Task 12（前端不调 POST /new）；§6.3 消息图契约 → Task 7 Step 1 测试 + Task 12；§6.2 断边 → Task 7/8/9 提取规则；首用户 admin → Task 9 测试。
- Slice 2/3 的 auth_middleware 路径扩展（/v1/knowledge、/v1/agents）不在本计划——届时在对应计划中修改 `app/api/openai_compat.py` 的 `protected_route` 判定。
- 类型一致性：`build_workflow_message(messages, *, enabled, max_turns, max_chars)` 在 Task 3 定义、Task 4 使用；`upsert_message_to_history(history, message_id, message)` 静态方法签名在 Task 7 测试与 Task 12 使用一致。
