# Slice 2 交接：知识库文件与 chunk 展示

> 日期：2026-08-30
> 分支：`webui`（本地，含 Slice 1 + 本地编排器恢复 + 引用校验停用）
> 目标：把 `frontend/webui` 的知识库页从占位升级为**真实 ChatDoc 数据**：文件列表 + 单文件按 chunk 展示。

## 1. 当前状态（已跑通的基线）

- 三服务在跑：app `:8000`（本地编排器默认）、services/webui `:8080`、前端 `:5173`。
- 真实链路已验证：注册/登录 → 流式问答（308 字完整回答）→ 落库 → 刷新恢复 → 多轮，全绿。
- 关键修复（已提交）：`60e7dae` 本地编排器默认；`a389121` SQLite WAL；`1b3d3c5` 落库提前到 `[DONE]` 前（修连接取消竞态）；`3861fbb` **引用校验已按用户决定停用**（本地编排不再拒答，sources 恒空）。
- 密钥已就位：根 `.env` 与 `services/webui/.env` 都有 `OPENAI_COMPAT_API_KEY`（同值），后者有 `WEBUI_SECRET_KEY`。ChatDoc 库已入库 30 文件（repo `0a13762a64ed`，`/ready` 报告 sources:30）。
- 测试基线：app 离线 **673 passed**；services/webui **18 passed**；前端 vitest 27 + check 0/0 + build 绿。

## 2. 待实现：知识库 chunk 展示（spec §5.2 + §7）

### 后端 `app`（新增三个面，全部服务密钥鉴权）

**ChatDoc 客户端**（`app/clients/iflytek_chatdoc.py`）新增两个方法，复用现有 `_request_json`/错误映射：
- `repo_file_list(repo_id)` → `POST /openapi/v1/repo/file/list`
- `file_chunks(file_id)` → `POST /openapi/v1/file/chunks`（form-data `fileId`）→ `data[].dataIndex/content`

**对外只读 API**（新增 `app/api/knowledge.py` + `app/services/knowledge_catalog.py` + `app/schemas/knowledge.py`，挂 `app/main.py`）：
```text
GET /v1/knowledge/files
  → ChatDoc repo/file/list → 规范化契约 {files: [{file_id, name, status, chunk_count?, size_bytes?, source_path?}]}
  → status 原样透传 ChatDoc 状态机（uploaded/texted/ocring/spliting/splited/vectoring/vectored/failed）
  → source_path 来自 artifacts/chatdoc/base.json 的 file_id→source 映射（缺失省略）
  → ChatDoc 失败 → 503 KNOWLEDGE_UNAVAILABLE（不透传业务码）

GET /v1/knowledge/files/{file_id}/chunks
  → 用内存 manifest（ChatDocRetriever 已加载）成员判定：不在 → 404 DOCUMENT_NOT_FOUND
  → 在 → ChatDoc file/chunks → 按 dataIndex 排序 {file_id, name, chunks: [{index, text}]}
  → ChatDoc 失败 → 503 KNOWLEDGE_UNAVAILABLE
```
- 鉴权：`app/api/openai_compat.py` 的 `auth_middleware` 扩展 `protected_route` 覆盖 `/v1/knowledge/*`（401 用 `{"error":{"message":"未授权","code":"UNAUTHORIZED"}}` 安全外形，不必 OpenAI 形）。
- 注意：**本地 manifest 仅作 file_id 成员判定与来源名映射**；数据主体必须来自 ChatDoc API，禁止恢复本地向量库/manifest 数据源（handoff 红线）。`settings.xf_chatdoc_repo_id` 是 repo。

### 应用服务 `services/webui`（新增只读代理）
- `webui/utils/upstream.py` 已有 `get_json`；加两个路由（需登录用户）代理到 `app`：
  - `GET /api/v1/knowledge/files` → app `/v1/knowledge/files`
  - `GET /api/v1/knowledge/files/{file_id}/chunks` → app 同路径
  - 挂 `webui/main.py`；Bearer 转发服务密钥；404/503 原样透传。

### 前端 `frontend/webui`（替换占位页）
- `src/routes/(app)/knowledge/+page.svelte`：文件列表页（名称/状态/块数；`chunk_count` 缺失显示 `-`；失败显示"知识库暂时无法加载"+重试）。数据从 `GET /api/v1/knowledge/files`。
- 新增 `src/routes/(app)/knowledge/[fileId]/+page.svelte`：单文件 chunk 详情（序号+正文折叠卡片；无页码）。数据从 chunks 接口。
- `src/lib/apis/knowledge/index.ts`：两个 API 封装（Bearer）。
- 侧边栏"知识库"已存在指向 `/knowledge`，无需改导航。

## 3. 验收（必须真实跑）

- 单元/契约测试：app 侧 stub ChatDoc 客户端测规范化映射/404/503/status 透传；services/webui 测代理鉴权与透传；前端 vitest 页渲染（fetch stub 复用后端契约 fixture）。
- 全量：`python -m pytest -m "not online" -q`（app，现 673）、`cd services/webui && python -m pytest -q`（18）、`cd frontend/webui && npm run test && npm run check && npm run build`。
- **真实联调**：三服务跑着（见 §1 启动命令），浏览器注册登录后打开 `/knowledge` 应看到真实 30 文件，点文件应看到真实 chunk。ChatDoc 现在可用（已入库、额度 OK）。

## 4. 环境与坑

- Python：`/opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python`；pytest 在对应子目录跑。
- 服务启动（复用现跑着的，若需重启）：
  - app：`set -a && source .env && set +a && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
  - services/webui：`cd services/webui && set -a && source .env && set +a && python -m uvicorn webui.main:create_app --factory --host 127.0.0.1 --port 8080`
  - 前端：`cd frontend/webui && npm run dev`
- 重启 app 会让 `/ready` 重新加载 manifest；`source_path` 映射以 `artifacts/chatdoc/base.json` 为准。
- 本仓库 `.claude/settings.json` 已设 `worktree.bgIsolation=none`，后台会话可直写主检出（用户允许）。
- 不改 `example/openwebui/`；不引入本地向量库/解析/Embedding fallback；前端不放假数据。

## 5. 建议技能

- `superpowers:test-driven-development`：契约测试先行。
- `superpowers:verification-before-completion`：真实联调 + 三套测试证据。
- 参考：`docs/superpowers/specs/2026-08-27-webui-product-architecture-design.md` §5.2/§7；`docs/官网文档/讯飞_ChatDoc_API.md`（file/list、file/chunks）。

## 6. 下一位智能体启动提示词

```text
在 LLM 仓库 webui 分支完成 Slice 2：知识库文件与 chunk 展示。先读 docs/Temp/2026-08-30-slice2-knowledge-chunks-handoff.md（本交接，含全部契约与环境）。

按序实现：
1. app：ChatDoc 客户端加 repo_file_list/file_chunks；新增 /v1/knowledge/files 与 /v1/knowledge/files/{file_id}/chunks（服务密钥鉴权，扩展 openai_compat 的 auth_middleware 路径覆盖）；契约测试（stub ChatDoc）先写。
2. services/webui：加两个只读代理路由（需登录）。
3. 前端：knowledge 列表页 + [fileId] chunk 详情页，替换占位页。
4. 三套测试全绿 + 真实联调：浏览器打开 /knowledge 应看到真实 30 文件与真实 chunk。

约束：数据主体必须来自 ChatDoc API；本地 manifest 仅做 file_id 成员判定与来源名映射；禁止恢复本地向量库数据源；不动 example/openwebui/；Python 用 /opt/homebrew/Caskroom/miniconda/base/envs/LLM/bin/python。完成后提交清晰 commit（落在 webui 分支）并报告真实测试与联调证据。
```
