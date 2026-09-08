# 交接：智能体广场 → 同伴 Next.js 前端（Route B 已定）

> 日期：2026-08-31 · 分支：webui（git status clean）· 相关 memory：webui-slice1-sdd-state（Slice 1 已合并 1c96ab6）、refusal-semantics-confirmed、app-domain-missing

## 结论一句话

自己前端（SvelteKit `frontend/webui` :5173）左侧"智能体广场"点击后**同域跳转**到同伴 Next.js 前端（`example/frontend`）承载的广场页；登录系统（`services/webui` JWT）两套前端通用；Docker 一键起。**路线已定：Route B（同域路径挂载）**，用户最后确认"就按这个B方案"。

## 本会话已完成

1. **`/knowledge` 修复**（example/frontend 4 文件）：数据源 manifest.json → ChatDoc `vector_store/base/download_report.json`；env 改名 `VECTOR_STORE_REPORT`；KnowledgeOverview 隐藏"向量规格 0 维"卡片。已端到端验证（API ready / 页面渲染 / dashboard 正常）。**未 commit**；`example/` 整体未跟踪。
2. 架构探索结论（详见下方计划文件）：
   - SvelteKit vite 代理 `/api → WEBUI_PROXY_TARGET`；`next.config.mjs` **已有** `basePath: process.env.BASEPATH`。
   - 登录共享可行性：HttpOnly `token` cookie（Lax / 非 Secure）同 host 跨端口共享；localStorage 按 origin 不跨端口 → **Route B 同域下双通道都免费共享**。
   - `get_current_user`（services/webui）接受 Bearer 头或 cookie。

## 实施计划（下一步直接开工）

详细设计见计划文件：`/Users/lanyuanzhe/.claude/plans/docker-docker-brainstorming-nifty-yeti.md`

- **Phase 1（不阻塞）**：Docker 第 4 容器（example/frontend，`BASEPATH=/agents`）+ SvelteKit vite 代理 `/agents` + 侧栏"智能体广场"入口（→ `/agents`）+ Next.js 登录接线（auths 代理 → webui:8080、死登录页接通、守卫校验）+ knowledge 数据 volume 挂载。
- **Phase 2（阻塞）**：广场页 + `GET /v1/agents`（`config/agents.json`）。**需要用户提供真实 iFlytek 智能体分享链接**；到位前诚实空态。

## 待用户提供 / 待决策

- 真实 iFlytek 智能体分享链接（Phase 2 前置）。
- `example/frontend` 是否纳入 git（当前整个 untracked；`/knowledge` 修复也随它一起 commit）。

## 风险与坑

- `.dockerignore` 排除了 `example/`、`vector_store/` → 需放开 frontend 并挂只读 volume。
- `/agents/api` 与现有 `/api` 代理边界需实测确认（basePath 自动前缀应天然隔离）。
- 全量 pytest 有预置失败 → 只跑单文件：`python -m pytest tests/<file>.py -v`。
- `app/domain` 缺失仍会导致 `app.main` 启动失败（见 memory app-domain-missing）——本任务不动它，验收时注意。
- macOS 代理 127.0.0.1:7897 需保持（iFlytek 出网）；容器内出外网注意。

## suggested skills

- `superpowers:executing-plans` — 按计划文件实施 Phase 1。
- `verify` — Docker 起跑 + 端到端验收配方（app/webui/frontend 三容器起跑姿势）。
- `superpowers:brainstorming` — 若还要讨论路线/范围（当前已收敛，一般不需要）。
- `/handoff` — 下次交接沿用同一流程与 `docs/Temp/` 位置。
