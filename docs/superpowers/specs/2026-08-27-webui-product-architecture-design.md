# webui 分支正式 Web 产品架构设计

> 日期：2026-08-27（2026-08-28 经多视角对抗审查后修订）
> 状态：已获用户确认（2026-08-27）
> 输入：`docs/Temp/2026-08-27-webui-branch-handoff.md`、Open WebUI v0.11.1 参考源码调研、`develop-openwebUI` 分支 OpenAI 兼容层审查、4 视角 spec 对抗审查（27 条发现已全部处置）

## 1. 背景与目标

`webui` 分支要在不放弃现有粮储领域服务（`app/`，ChatDoc RAG + 星辰工作流）的前提下，产出一个正式 Web 产品：注册/登录、聊天与历史会话、公共基础知识库真实文件/分块展示、可跳转的智能体广场。Open WebUI v0.11.1 仅作为 `example/openwebui/` 下的只读参考，从其提取必要核心模块，不整体启用再删减。

## 2. 范围

### 2.1 第一阶段实现

- 用户注册/登录与基础权限校验（未登录不可进入受保护页面）。
- 新建对话、流式粮储问答、历史会话保存与刷新后恢复。
- 公共基础知识库：ChatDoc 真实文件列表、单文件真实分块列表（只读）。
- 智能体广场：卡片展示与外部跳转契约。
- 基础粮储品牌与精简导航；个人设置；管理员保留用户管理入口。

### 2.2 第一阶段不做

- Open WebUI 通用模块：Channels / Workspace / Models / Prompts / Tools / Functions / Notes / Calendar / Automations / Playground / 自带知识库（导航与路由均不出现）。
- 教师/学生业务角色、班级/课程/群组权限（未决，不自行扩展；沿用 Open WebUI 原生 admin/user/pending）。
- 个人/项目知识库、知识库上传/编辑/删除/重切分。
- 聊天附件（文件/图片上传）、语音、斜杠命令。
- 智能体具体列表、卡片文案与详细视觉（配置先行，内容为空的诚实空态）。
- 生产部署拓扑、SSO/OAuth、正式品牌规范。
- 任何 Mock 数据/Mock 运行模式；任何本地解析、OCR、Embedding、sklearn/FAISS、本地向量库 fallback。

## 3. 决策记录

| # | 决策 | 理由 |
|---|------|------|
| D1 | 双服务拓扑：提取的 Open WebUI 应用核心（`services/webui/`）+ 现有粮储领域服务（`app/`），两进程 | handoff §3 已确认边界 |
| D2 | 浏览器单入口：只与 `services/webui` 通信；知识库/智能体/聊天补全全部由它代理到 `app` | 免 CORS/双 base-url，鉴权收口于应用服务；`app` 绑定 127.0.0.1 不直接暴露 |
| D3 | 最小提取而非全量运行裁剪 | handoff 明确禁止"先运行全部再删减"；Open WebUI `main.py`（3039 行）与 `utils/middleware.py`（6300+ 行）是耦合黑洞，整体搬运不可维护 |
| D4 | 聊天历史持久化在 `services/webui`（移植 chats 模型）；`app` 保持无状态 | 沿用 Open WebUI 成熟能力，领域服务不引入用户/会话概念 |
| D5 | 聊天补全瘦编排：自写 slim `/api/chat/completions`（鉴权 → 从 DB 装载历史 → 转发 → 流式回传 → 落库），不搬 `utils/middleware.py` | 调研确认 middleware.py 牵涉 tasks/socket/redis/tool 执行，无法局部提取 |
| D6 | `app` 新增 OpenAI 兼容层，从 `develop-openwebUI` 选择性移植协议机器，不整体合并分支 | handoff §5；两分支 `WorkflowGateway`/内部 SSE 协议逐字节一致，契约测试大部分可复用 |
| D7 | 不移植 `learning_tasks.py`/`learning_artifacts.py` 的任务路由；第一阶段固定 `task_type="knowledge_qa"` | 教学任务（练习生成/反馈、课程总结）属未决产品面；YAGNI |
| D8 | 多轮上下文：兼容层将最近历史打包进 `AGENT_USER_INPUT`，轮数/字符数可配（`OPENAI_COMPAT_HISTORY_MAX_TURNS` 默认 6、`OPENAI_COMPAT_HISTORY_MAX_CHARS` 默认 4000），总开关 `OPENAI_COMPAT_HISTORY_ENABLED`（默认开；置关即回退为仅传最后一条 user 消息） | 当前星辰客户端不再传 `chat_id`，工作流无服务端记忆；纯文本打包不需改工作流；配置开关即 §11 风险项的回退路径 |
| D9 | 注册策略：开放注册、首个用户自动 admin、默认角色 user；JWT HS256 + Bearer（沿用参考实现）；显式偏离参考：删除"首用户注册后自动关闭注册"行为 | 满足验收"用户能注册/登录"；审批流（pending）属未决权限模型 |
| D10 | 数据库：SQLAlchemy + SQLite（`create_all`，不搬 Alembic 迁移链）；`DATABASE_URL` 可后续换 Postgres | 提取最小依赖；模型层本来就是 SQLAlchemy，换库成本已隔离 |
| D11 | 不做任何许可层面的加工（用户决定，2026-08-27/28）：私有学习/试点项目、无真实用户、不对外分发。`example/openwebui/` 参考副本原样不动；拷贝提取的源文件保持原样（不主动添加也不删除文件内已有声明） | 用户明确指示；若未来公开分发或真实部署需重新评估 |
| D12 | 知识库数据源只有 ChatDoc API：客户端新增 `repo/file/list` 与 `file/chunks` 两个方法。唯一合法的本地 manifest 是 `artifacts/chatdoc/base.json`（ChatDoc 管线产物），仅用于 file_id 成员判定与来源路径显示名；严禁引用 vector_store 时代的 `manifest.json`/`chunks_metadata.json` | handoff §6 红线；08-27 技术方案的本地数据源已随本地向量库删除而失效 |
| D13 | 智能体首版：`GET /v1/agents` 从受控 JSON 配置读取，读取时校验 `launch_url` 必须是 `https:` scheme（非法条目剔除），卡片 `window.open(launch_url, "_blank", "noopener,noreferrer")`；无真实 URL 时展示诚实空态，不放假卡片 | handoff §7（含"受信任 HTTPS"建议）；禁止 Mock |
| D14 | 前端新骨架 + 选择性移植组件，不整体拷 `src/`；i18n 用 stub；Slice 1 输入框新写极简 textarea，不移植 MessageInput（2730 行/约 90 import） | 参考前端有 65 个 locales、pyodide/onnx 联网构建钩子、MessageInput 拖带 tiptap/语音/文件上传等重依赖；整体拷贝无法构建也无法裁剪 |
| D15 | 会话与消息的唯一持久化路径是 slim `/api/chat/completions` 服务端落库；第一阶段前端不调用 `POST /api/v1/chats/new` 或 `POST /api/v1/chats/{id}` 写消息内容 | 消除"客户端整份 chat JSON 覆盖"与"服务端 upsert"双写冲突（last-writer-wins 丢数据） |

## 4. 总体架构

```text
浏览器（SPA，由 services/webui 托管静态产物；开发期 vite dev server 代理）
  │  仅同源 HTTP(S)，Bearer JWT
  ▼
services/webui/        Open WebUI 应用核心提取（FastAPI，:8080）
  ├─ 注册/登录/用户/角色（JWT HS256，admin/user/pending）
  ├─ 会话与聊天历史（SQLite，chats/chat_messages）
  ├─ slim /api/chat/completions：装载历史 → 转发 → 流式回传 → 落库
  └─ 只读代理：/api/v1/knowledge/*、/api/v1/agents → app（需登录用户 JWT）
        │  loopback HTTP，携带服务密钥；聊天补全另带 X-OpenWebUI-Chat-Id/User-Id
        ▼
app/                   粮储领域服务（FastAPI，:8000，绑 127.0.0.1）
  ├─ 新增 GET /v1/models、POST /v1/chat/completions（OpenAI 兼容）
  ├─ 新增 GET /v1/knowledge/files、GET /v1/knowledge/files/{file_id}/chunks
  ├─ 新增 GET /v1/agents（受控 JSON 配置）
  │  （以上新端点均要求服务密钥 Bearer）
  └─ 现有 /v1/chat、/tools/v1/*、/health、/ready 保持不变
        │
        ▼
讯飞 ChatDoc（知识库文件/分块/检索）与星辰工作流（问答编排）
```

正式代码边界：

```text
LLM/
├── example/openwebui/     # 只读参考，不修改
├── frontend/webui/        # 新 SvelteKit SPA（正式前端）
├── services/webui/        # 提取的 Open WebUI 应用核心（正式应用服务）
│   ├── webui/             # Python 包：models/ routers/ utils/ internal/ main.py settings.py events.py
│   ├── tests/
│   ├── requirements.txt
│   └── data/              # SQLite（gitignored）
├── app/                   # 现有粮储领域服务（本次新增三个 API 面）
└── config/agents.json     # 智能体广场受控配置（首版可为空数组）
```

## 5. `app/` 领域服务设计

### 5.1 OpenAI 兼容层（移植）

从 `develop-openwebUI` 选择性移植（`git show develop-openwebUI:<path>` 取文件，逐文件审查后落地，不 merge 分支）：

| 文件 | 移植方式 |
|------|---------|
| `app/schemas/openai_compat.py`（61 行） | 原样：请求模型、`extra="ignore"`、`validate_forwarded_identifier` |
| `app/services/openai_compat.py`（379 行） | 移植协议机器：`_parse_internal_event`/`_chunk`/`_source(s)`/`preflight_openai_stream`/`openai_stream`/`collect_openai_completion`/三种时态的错误表达；**删去** `learning_tasks`/`learning_artifacts` 依赖：status 事件改为固定 knowledge_qa 文案（"正在检索粮储知识库并核对依据"→ 完成态），删 embeds 事件 |
| `app/api/openai_compat.py`（226 行） | 移植端点/鉴权中间件/错误外形；`LearningTurnResolver.resolve(...)` 替换为：取最后一条 user 消息 + 按 D8 打包历史；`task_type` 固定 `knowledge_qa`；`USER_ROLE` 沿用旧逻辑传 `Role.STUDENT`——注意这只是星辰工作流的输入参数（供工作流提示词使用），与产品侧 admin/user/pending 角色无关，不代表教师/学生权限模型落地；`project_id` 取 `settings.openai_compat_project_id`，客户端传入忽略 |
| `tests/contract/test_openai_compat_api.py`（884 行，22 个测试函数、26 个收集用例） | 移植鉴权/模型/校验/身份映射/安全/流式/故障用例；删任务路由与 embeds 用例；新增"历史打包进 AGENT_USER_INPUT"用例（断言轮数与字符封顶生效、开关关闭时仅传末条消息）；夹具适配：去掉 `ServiceContainer(vector_store=...)`、settings 命名空间对齐 webui Settings |

装配改动（`app/main.py` 三处，与旧分支 diff 已确认）：

1. `include_router(openai_compat.router)`；
2. `middleware("http")(openai_compat.auth_middleware)`——在旧分支基础上**扩展路径覆盖**到 `/v1/knowledge/*` 与 `/v1/agents`（同一服务密钥校验；这两类端点的 401 用 `{"error": {"message": "未授权", "code": "UNAUTHORIZED"}}` 安全外形，不必 OpenAI 形）；
3. `RequestValidationError` handler 对 `/v1/chat/completions` 返回 422 OpenAI 错误外形（否则破契约）。

配置新增（`app/core/config.py`，连 validator 一起移植）：`OPENAI_COMPAT_API_KEY`（SecretStr，必填）、`OPENAI_COMPAT_MODEL_ID`、`OPENAI_COMPAT_MODEL_NAME`、`OPENAI_COMPAT_PROJECT_ID`（可空）、`OPENAI_COMPAT_HISTORY_ENABLED`（默认 true）、`OPENAI_COMPAT_HISTORY_MAX_TURNS`（默认 6）、`OPENAI_COMPAT_HISTORY_MAX_CHARS`（默认 4000）。

流式协议（对外）：标准 `chat.completion.chunk` 序列 + Open WebUI `status`/`source` 扩展事件（仅带 `X-OpenWebUI-*` 头时发 status）；错误三时态（preflight 前 502 JSON / 流中途 SSE error + `[DONE]` / 协议违规 `WORKFLOW_PROTOCOL_ERROR`），全程脱敏（不泄露凭据与原始错误体）。已知差异：ChatDoc 证据无 `page`/`section`、`authority_level` 恒 `unknown`，引用卡片不显示页码——`_source()` 对缺字段宽容，前端按无页码渲染。

### 5.2 知识库只读 API（新增）

ChatDoc 客户端新增两方法（`app/clients/iflytek_chatdoc.py`，复用现有 `_request_json`、重试与安全错误映射）：

- `repo_file_list(repo_id)` → `POST /openapi/v1/repo/file/list`
- `file_chunks(file_id)` → `POST /openapi/v1/file/chunks`（form-data `fileId`）→ `data[].dataIndex/content`

对外接口（`app/api/knowledge.py` + `app/services/knowledge_catalog.py` + `app/schemas/knowledge.py`，挂载于 `app/main.py`，服务密钥鉴权）：

```text
GET /v1/knowledge/files
  → 调 ChatDoc repo/file/list，由 app 层规范化映射为固定对外契约：
    {files: [{file_id, name, status, chunk_count?, size_bytes?, source_path?}]}
  → status 枚举原样透传 ChatDoc 状态机：uploaded/texted/ocring/spliting/
    splited/vectoring/vectored/failed
  → source_path 来自 artifacts/chatdoc/base.json 的 file_id→source 映射；
    manifest 缺失对应 file_id 时省略该字段（不编造）
  → ChatDoc 失败 → 服务层捕获 ProviderUnavailable 统一换码
    503 KNOWLEDGE_UNAVAILABLE（中文安全文案，不含供应商原始错误体/业务码）

GET /v1/knowledge/files/{file_id}/chunks
  → 先用内存 manifest（artifacts/chatdoc/base.json，启动时经 ChatDocRetriever
    加载并校验）做成员判定：file_id 不在 manifest → 404 DOCUMENT_NOT_FOUND
    （零额外上游调用）
  → 在 manifest → 调 ChatDoc file/chunks，按 dataIndex 排序返回：
    {file_id, name, chunks: [{index, text}]}（name 取 manifest source 的 basename）
  → ChatDoc 失败 → 503 KNOWLEDGE_UNAVAILABLE（同上）
```

映射注意：仓库内 `docs/官网文档/讯飞_ChatDoc_API.md` 未列出 `repo/file/list` 的响应字段明细；实现时以官方在线文档（https://www.xfyun.cn/doc/spark/ChatDoc-API.html）为准确定上游字段→对外契约的映射表，契约测试 stub 的响应外形即对外契约的唯一事实来源，前端 fetch stub 复用同一份 fixture；额度恢复后用真实响应校准一次。前端文件列表的"块数"列在 `chunk_count` 缺失时显示 `-`。

仅公共基础库（`settings.xf_chatdoc_repo_id`）；个人/项目库后续在同一接口模型上扩展。第一阶段不做缓存（真实数据直读；若配额/时延成为问题再加短 TTL 缓存，届时单独评审）。

### 5.3 智能体配置 API（新增）

```text
GET /v1/agents（服务密钥鉴权）
  → 读 config/agents.json（路径由 settings.agents_config_path 配置，默认 config/agents.json）
  → {agents: [{id, name, description, category, color, icon, launch_url}]}
  → 逐条校验：launch_url 必须是 https: scheme，非法条目剔除（记 warning 日志）
  → 配置文件缺失/解析失败 → 503 AGENTS_UNAVAILABLE（安全文案）；配置为空数组或全部被剔除 → 200 {agents: []}
```

## 6. `services/webui/` 应用服务设计（提取）

### 6.1 提取清单

**从 `example/openwebui/backend/open_webui/` 拷贝后按下述规则裁剪**，保持原相对结构（`open_webui/` → `webui/`），源文件保持原样不做任何声明层面加工（D11）：

- `internal/db.py`（引擎+Base+session 依赖）
- `constants.py`（ERROR_MESSAGES）
- `models/{config,users,auths,chats,chat_messages}.py`
- `utils/auth.py`（JWT、密码哈希、`get_current_user/get_verified_user/get_admin_user`）
- `utils/{misc,validate,response,json_codec}.py` 的**最小子集**（见断边规则）
- `routers/auths.py`（只留 `GET /`（session 用户）、`/signin`、`/signup`、`/signout`、`/update/password`）
- `routers/users.py`（只留 `POST /user/settings`、`GET /all`（管理员）、`POST /{user_id}/update`（管理员角色更新））
- `routers/chats.py`（只留 `GET /`、`GET /{id}`、`DELETE /{id}`）

**新写**：

- `webui/settings.py`：极简设置模块（pydantic-settings 或纯 os.environ），替代 `open_webui.env`；符号清单：`DATA_DIR`、`DATABASE_URL`（默认 `sqlite:///{DATA_DIR}/webui.db`）、`WEBUI_SECRET_KEY`（必填，未设置启动报错，语义沿用参考 env.py:765）、`WEBUI_AUTH`（默认 True）、`JWT_EXPIRES_IN`、`ENABLE_ADMIN_CHAT_ACCESS`（默认 False）、`APP_UPSTREAM_BASE_URL`（默认 `http://127.0.0.1:8000`）、`OPENAI_COMPAT_API_KEY`（转发用服务密钥）、`FRONTEND_BUILD_DIR`、`CORS_ALLOW_ORIGIN`
- `webui/events.py`：no-op stub（`EVENTS` 空注册表、`publish_event` 空实现），替代 `open_webui.events`（其原实现 import retrieval/webhook，均不取）
- slim `main.py`：lifespan（`create_all`、配置种子）、CORS、挂上述 router + `/api/chat/completions`（D5 瘦编排）+ `/api/models`、`/api/config`、`/api/version` + 知识库/智能体代理 + SPA 静态托管
- `utils/upstream.py`：到 `app` 的 httpx 转发（服务密钥、转发头、超时、流式）

**明确不取**：`utils/middleware.py`、`socket/`、`retrieval/`、`storage/`、`oauth`/`scim`/`ldap`、`models/{folders,tags,shared_chats,access_grants,automations,groups,files,...}`、Alembic 迁移链、pyodide/workers、Redis、`utils/{rate_limit,groups,access_control}`、API key 机制、加密 token（AESGCM）机制。

**最小依赖清单（`services/webui/requirements.txt`）**：`fastapi`、`uvicorn`、`pydantic`、`pydantic-settings`、`sqlalchemy[asyncio]`、`aiosqlite`、`PyJWT`、`bcrypt`、`httpx`、`pytz`。不引入：`cryptography`、`requests`、`orjson`、`engineio`/`python-socketio`、`aiohttp`、`mimeparse`、`ldap3`（对应代码路径全部裁掉）。

### 6.2 断边与裁剪规则（逐文件，经实际 import 核对）

1. **所有** `from open_webui.env import ...` → 改 `from webui.settings import ...`，未列入 settings 符号清单的名字一律连同其功能分支删除。
2. `models/chats.py`：断开对 `folders`/`tags`/`shared_chats`/`access_grants`/`automations`/`models.files`/`utils.access_control.folders` 的 import 及对应方法（folder/tag/share/fork/clone/access 相关）；`utils.misc` 只保留被实际使用的 `get_output_text`/`sanitize_data_for_db`/`sanitize_text_for_db` 的最小实现。
3. `models/chat_messages.py`、`models/auths.py`、`models/users.py`：`utils/validate`、`utils/misc` 同上最小化；`utils/response` 最小化。
4. `utils/json_codec.py`：删除 `engineio` 依赖（socket 栈不取）；JSONCodec 若仅被 db.py 用于 JSON 列编解码，可内联简化。
5. `utils/auth.py`：删除 API key 认证路径（`get_current_user_by_api_key` 及 `utils.access_control.has_permission` 调用）、加密 token 加解密（`cryptography` ed25519/AESGCM）、`requests` 出站调用路径；`utils.misc.parse_duration` 保留最小实现。
6. `routers/auths.py`：删除顶层 `ldap3`/`aiohttp`/`open_webui.config`/`models.groups`/`models.oauth_sessions`/`utils.groups`/`utils.rate_limit`/`utils.redis` import 与对应端点；删除模块级 `RateLimiter` 实例化；`events.publish_event` 改调 no-op stub。
7. `routers/chats.py`：删除顶层 `socket.main`/`tasks`/`utils.context_compaction`/`utils.chat_fork`/`utils.models` import 与对应端点。
8. `Config` 配置表种子只留：`ui.default_user_role`（`user`）、`auth.jwt_expiry`、`ui.enable_signup`（`true`）、`ui.enable_login_form`（`true`）。
9. **显式偏离参考逻辑三处**（D9）：
   - 删除 `signup_handler` 首用户创建后的 `Config.upsert({'ui.enable_signup': False})`（保持开放注册）；
   - 删除 signup 中 `ui.default_group_id` 读取与 `apply_default_group_assignment` 调用；
   - 删除 `create_session_response` 的 `get_permissions(...)` 装配（`user.permissions` 未种子会 500，且其依赖 Groups 模型），session 响应的 `permissions` 字段返回空对象。
10. 无用户时首个 signup 自动 admin（沿用参考逻辑）。
11. **显式偏离参考语义一处**：chats 路由 `GET /{id}` 的非属主/不存在分支由参考的 401 改写为 404（统一"非属主即不可见"语义）。
12. `profile_image_url`：不取头像端点，signin/signup/session 响应中该字段返回空字符串，前端用占位头像。
13. 所有 `request.app.state.redis` 调用点删除（不引入 Redis）。
14. 不搬 socket.io：聊天流式走 fetch stream，前端无 `$socket` 依赖。

### 6.3 slim 聊天补全（新写，替代 middleware.py）

```text
POST /api/chat/completions  (Bearer JWT)
1. get_verified_user；解析 {model, messages, chat_id?}
2. chat_id 存在 → 校验归属（非属主 404）并以 DB 历史为唯一权威，
   请求体仅提供本轮新 user 消息（末条）；chat_id 不存在 → 用 Chats 表方法
   新建 chat（初始 JSON：{id, title: 首条消息前 40 字符, models: [model],
   history: {messages: {}, currentId: null}, messages: []}，实现时以
   models/chats.py 的 ChatForm/insert_new_chat 实际外形为准）
3. 构造转发 messages = DB 历史（按 currentId 沿 parentId 回溯的消息链，
   content 为 list-of-blocks 时拼接其 text 块为纯文本）+ 本轮 user 消息
4. 转发 POST app:/v1/chat/completions（Bearer 服务密钥；
   X-OpenWebUI-Chat-Id=<chat_id>、X-OpenWebUI-User-Id=<user_id>；stream=true）
5. 流式回传浏览器，同时缓冲 assistant 全文与 source 事件
6. 流正常结束（收到终止 chunk）→ 依次 upsert：
   a. user 消息 {id: uuid4, role: "user", content, parentId: 上一叶消息 id 或 null,
      childrenIds: [], timestamp}，并把父消息 childrenIds 追加该 id；
   b. assistant 消息 {id: uuid4, role: "assistant", content, parentId: user 消息 id,
      childrenIds: [], timestamp, sources: <source 事件累积数组>}，
      user 消息 childrenIds 追加该 id，history.currentId = assistant 消息 id；
   c. messages 数组与 history.messages map 同步更新（对齐
      upsert_message_to_history 的实际行为，实现时以其为准）
7. 上游失败（preflight 502 / 流中 error）→ 本轮 user+assistant 均不落库
   （整轮不落，前端本地保留显示与错误提示）；错误事件透传（脱敏后）
```

说明：消息图契约（parentId/childrenIds/currentId）与参考前端 `createMessagesList` 的恢复算法（从 currentId 沿 parentId 回溯）对齐，是"刷新恢复历史"验收的关键；`sources` 字段名与参考前端引用卡片渲染（`message.sources`）一致。

## 7. `frontend/webui/` 前端设计

- 新 SvelteKit 2 + Svelte 5 + TypeScript + Tailwind 4 + adapter-static（SPA，`fallback: 'index.html'`）；构建无联网步骤。
- 最小 `package.json` 依赖：`@sveltejs/kit`、`@sveltejs/adapter-static`、`svelte`、`vite`、`typescript`、`tailwindcss`（@4）、`marked`、`dompurify`、`dayjs`、`uuid`。katex/highlight.js 第一阶段不引入（代码块按纯文本渲染，后续迭代再移植 CodeBlock/KatexRenderer 裁剪版）。`svelte-sonner` 可选（toast）。
- `$lib/stores`、`$lib/utils`、`$lib/constants` 新写最小集（user/config/chatId 等），不整体移植；i18n stub（`$i18n.t` 直返中文 key）。
- 登录态：token 存 localStorage、API 调用带 Bearer（沿用参考实现方式）。
- 路由：`/auth`、`/`（新聊天）、`/c/[id]`（会话）、`/knowledge`、`/knowledge/[fileId]`、`/agents`、`/settings`、`/admin/users`；`(app)` layout 做认证守卫，未登录跳 `/auth`。
- 组件策略：新写应用壳/侧边栏（仅 对话/知识库/智能体广场/设置，管理员多"用户管理"）。聊天区：消息列表/Markdown 渲染可移植参考组件（裁剪 pyodide/katex/highlight 依赖），`Chat.svelte`（4663 行）与 `MessageInput.svelte`（2730 行）**不移植**——输入框新写极简 textarea（纯文本、Enter 发送、生成中禁用）；Chat 核心按"发送→流式渲染→历史恢复"重写，**必须解析并渲染**标准 chunk 之外的三类 SSE 扩展事件：`status`（进行中状态条）、`source`（引用卡片，数据写入 `message.sources` 形状）、`error`（安全错误文案，含流中途失败）；历史恢复从 `GET /api/v1/chats/{id}` 读取，按 currentId→parentId 回溯构造消息链（与 §6.3 落库契约对齐）。
- 页面：知识库文件列表（名称/状态/块数，`chunk_count` 缺失显示 `-`；失败显示"知识库暂时无法加载"+重试）、分块详情（序号+正文折叠卡片）、智能体广场（卡片网格、空态、`launch_url` 为空时按钮禁用——正常配置下不应出现，因服务端已剔除非 https 条目）。
- 构建产物由 `services/webui` 静态托管；开发期 vite proxy → `:8080`。

## 8. 错误处理与安全

- 凭据只存于 `.env`（`app`）与 `services/webui/.env`（`WEBUI_SECRET_KEY`、`OPENAI_COMPAT_API_KEY`、`APP_UPSTREAM_BASE_URL`），不进源码/前端包/日志。
- ChatDoc 失败 → 知识库端点统一 503 `KNOWLEDGE_UNAVAILABLE`（服务层换码，不透传 `CHATDOC_UNAVAILABLE_*` 业务码）；智能体配置故障 → 503 `AGENTS_UNAVAILABLE`；均不返回供应商原始错误体、认证头。
- 聊天上游失败：preflight 前 → 502 OpenAI 错误外形；流中途 → SSE error + `[DONE]`；协议违规 → `WORKFLOW_PROTOCOL_ERROR`。前端显示可理解错误，不伪造回答。
- 未登录访问受保护 API → 401；非属主访问他人 chat → 404（显式偏离参考的 401，见 §6.2.11）；管理员接口校验 admin。
- `app` 绑定 127.0.0.1；`/v1/models`、`/v1/chat/completions`、`/v1/knowledge/*`、`/v1/agents` 均要求服务密钥 Bearer（auth_middleware 路径覆盖，见 §5.1）；`services/webui` 侧代理端点要求登录用户 JWT。

## 9. 测试策略

- `app`（pytest，离线）：移植并适配 openai_compat 契约测试（见 §5.1）；新增 knowledge 契约测试（stub ChatDoc 客户端：规范化映射、status 枚举透传、manifest 成员判定 404、ProviderUnavailable→503 KNOWLEDGE_UNAVAILABLE、超时）与 agents 契约测试（合法配置、空配置、https 校验剔除、文件缺失 503）；命令 `python -m pytest -m "not online" -q`。
- `services/webui`（pytest，离线）：注册/登录/JWT/首用户 admin/开放注册不自动关闭、chats 属主隔离（404）、slim completions（stub 上游：流式回传+消息图落库（parentId/childrenIds/currentId/sources）、上游失败整轮不落库、DB 历史权威合成）、知识库/智能体代理鉴权与透传。
- `frontend/webui`（vitest + `vite build`）：API 层与守卫单测、SSE 扩展事件解析（status/source/error）单测、知识库/智能体页渲染（fetch stub 复用后端契约 fixture——仅单测替身，不是运行时 Mock 模式）；构建必须通过。
- 真实端到端（注册→登录→流式问答→刷新恢复→知识库真实数据）：依赖 ChatDoc 66001 额度恢复；恢复前以离线测试 + 构建为完成标准，恢复后补人工联调。

## 10. 分阶段实施计划

| 切片 | 内容 | 验收 |
|------|------|------|
| Slice 1 | `app` OpenAI 兼容层移植 + `services/webui` 最小骨架（auth+chats+slim completions）+ `frontend/webui` 外壳（/auth、/、/c/[id]） | 离线：三服务测试+前端构建绿；stub 上游下演示 注册/登录 → 发消息 → 流式回答 → 刷新恢复历史、未登录被守卫拦截。真实链路（真 ChatDoc+星辰）待额度恢复后补测 |
| Slice 2 | ChatDoc 客户端两方法 + `/v1/knowledge/*` + 代理 + 知识库两页面 | 契约测试绿（规范化映射/404/503/状态透传）；额度恢复后：真实文件列表/分块展示，ChatDoc 失败显示安全错误 |
| Slice 3 | `/v1/agents` + 代理 + 智能体广场页 | 契约测试绿（含 https 剔除与空配置）；卡片渲染与 `_blank/noopener` 跳转契约；空配置诚实空态；有真实 URL 时可跳转 |
| Slice 4 | 品牌/导航精简/个人设置/管理员用户管理入口、响应式与可访问性收尾、全量离线测试 + 构建 +（额度恢复后）真实 E2E | handoff §10 验收清单全过 |

## 11. 开发约束

- Python 解释器：`/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`（conda `LLM` 环境，Python 3.11）；包安装用该解释器的 `python -m pip`；禁止系统 Python 与 base 环境 pip。
- 凭据只从 `.env` 读取，不得进入源码、前端包或日志。
- 供应商错误必须转换为安全应用错误，不返回原始错误体或认证头。
- `example/openwebui/` 只读，不修改不删除其中任何文件。
- 不整体合并 `develop-openwebUI` 分支；只用 `git show` 取文件后审查落地。

## 12. 外部依赖与风险

- **ChatDoc 66001（额度/余额不可用）**：远端知识库未入库、`XF_CHATDOC_REPO_ID` 未配置，`app` 当前无法完整启动。不阻塞代码与离线测试；阻塞真实 E2E 与知识库页面真实数据联调。禁止伪造 manifest 或切换 repo 配置。
- **未决项（不自行扩展）**：教师/学生模型、个人/项目知识库、智能体具体列表与 URL、品牌规范、部署拓扑/SSO。
- **星辰工作流行为**：多轮历史打包进 `AGENT_USER_INPUT` 的效果需额度恢复后实测校准；若工作流对输入格式敏感，置 `OPENAI_COMPAT_HISTORY_ENABLED=false` 回退为仅传最后一条 user 消息。
