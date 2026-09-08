# 交接：智能体广场自绘聊天界面（讯飞助手 WS→SSE 桥）端到端已通

> 日期：2026-09-03 · 分支：webui（baseline `86574b2`；本特性改动**未 commit**）· 相关 memory：agent-plaza-embed-state（API 凭据/映射/调用配方）、webui-slice1-sdd-state、app-domain-missing

## 结论一句话

plaza 里 2 个有 API 的讯飞智能体（粮食行业知识库、助教·星廪智枢）已从 iframe 换成**自绘原生聊天 UI**：浏览器 → plaza `api/backend/assistant-chat`（Next route handler）→ app `POST /v1/assistant/chat`（FastAPI WS→SSE 桥）→ 讯飞星火助手 WebSocket 流式回话。**真实对话端到端 curl 验证通过，用户浏览器确认 UI 可用**。无 API 的 2 个（科研、助学）仍走 iframe。

## 本会话已完成（全在 git status 里，未 commit）

**后端（FastAPI app，容器 grain-agent-app）：**
- `app/services/assistant_chat.py`（新）：`stream_assistant()` — HMAC-SHA256 构造 WSS URL（host\ndate\nGET 路径签名，镜像 iflytek_maas）+ 帧协议；yield `("delta",{content})` / `("error",{message})`；status==2 结束；MAX_FRAMES=1024。
- `app/api/assistant.py`（新）：`POST /v1/assistant/chat`，`response_model=None`（**必须**——否则 StreamingResponse|JSONResponse 联合注解被 FastAPI 当 response model，容器启动即崩）。凭据缺失→503 `ASSISTANT_NOT_CONFIGURED`；assistant_id 不在白名单→400 `ASSISTANT_NOT_ALLOWED`。
- `app/schemas/api.py`：+`AssistantTurn`(role Literal["user","assistant"], content 1-8000)、`AssistantChatRequest`(assistant_id, messages 1-64, uid optional)。
- `app/core/config.py`：+可选字段 `xf_assistant_app_id/api_key/api_secret`（SecretStr）+ `assistant_api_url`（缺省 `wss://spark-openapi.cn-huabei-1.xf-yun.com/v1/assistants`）；未配置时服务仍能启动。
- `app/main.py`：挂 `assistant.router`。

**前端（plaza，容器 grain-agent-frontend-plaza，basePath=/agents）：**
- `frontend/plaza/src/views/agents/AgentChatPanel.tsx`（新）：'use client' 自绘聊天。**多轮 = 每次把全部历史发给后端**；consumeSse 消费 delta/error/done；右侧用户气泡/左侧带色头像助手气泡/empty-state 示例提问/停止按钮/流式打字。缺省 uid 用 sessionRef(page-load randomUUID)。
- `frontend/plaza/src/views/agents/AgentChat.tsx`：有 `assistantId` → `<AgentChatPanel/>`；否则 iframe。
- `frontend/plaza/src/app/api/backend/assistant-chat/route.ts`（新）：复用 `proxySse(request, '/v1/assistant/chat')`。
- `frontend/plaza/src/app/(dashboard)/plaza/[id]/page.tsx` + `frontend/plaza/src/configs/agents.ts`：`AgentConfig.assistantId` 字段；2 个 agent 已配。
- `frontend/plaza/src/components/layout/vertical/VerticalMenu.tsx`（改）：4 个智能体侧栏入口。

**构建修复：**
- `frontend/plaza/src/@core/theme/index.ts`（改）：**移除 `next/font/google` Inter**——容器 build 期无法访问 fonts.gstatic.com（宿主机代理 127.0.0.1:7897 不进 build），改为系统字体栈。tsc/eslint/build 全绿。这是非显式需求的环境 workaround，见「待决策」。

## 已端到端验证（curl，实况）

1. 后端直连：`curl -N -X POST 127.0.0.1:8000/v1/assistant/chat -H 'Content-Type: application/json' -d '{"assistant_id":"kpevnp8z2ff2_v1","messages":[{"role":"user","content":"用一句话介绍你自己"}],"uid":"x"}'` → `event: delta` 逐帧（"我是专注于粮食产业链的全链条信息专家…"）+ `event: done`。
2. 助教 `xyzrra1uxi9w_v1` 同验通过。
3. 代理链：`POST 127.0.0.1:5173/agents/api/backend/assistant-chat`（浏览器真实路径：SvelteKit 5173 → plaza 3000 → app 8000）→ 流式通过。
4. 白名单：未知 id → HTTP 400 `ASSISTANT_NOT_ALLOWED`；4 个 `/agents/plaza/<id>` 路由全 200。
5. UI：grain-knowledge 页浏览器人工确认聊天正常（用户"ok了，可以了"）。

## 扩展智能体的配方（用户明确下一步方向）

新增一个有 API 的讯飞智能体，**只改两处**：
1. `frontend/plaza/src/configs/agents.ts` → 该 agent 加 `assistantId: '<assistant_id>'`（id 形如 `kpevnp8z2ff2_v1`，平台智能体页可查）。
2. `app/api/assistant.py` → `_ALLOWED_ASSISTANT_IDS` frozenset 加同一个 id。

无 API 的智能体（分享链接才能用）→ 只配链接走 iframe，别加 assistantId。若需限定开放给某些登录用户再讨论鉴权。

## 凭据（位置只读，值别外泄）

- `.env`（gitignored）：`XF_ASSISTANT_APP_ID` / `XF_ASSISTANT_API_KEY` / `XF_ASSISTANT_API_SECRET`。
- 仓库根 `讯飞agent平台智能体链接.md` 也追加了同名凭据 + 4 agent 分享链接（已被 git status 标记 modified）。**交接/文档不要复制密钥值**；app_id `911d520f` 非敏感可提。
- macOS 代理 127.0.0.1:7897 必须保持（讯飞出网）；容器内 WebSocket 不受代理 env 影响（compose 注释已注明）。

## 未 commit 清单（建议一条 commit）

```
M app/core/config.py  M app/main.py  M app/schemas/api.py
M frontend/plaza/src/@core/theme/index.ts
M frontend/plaza/src/components/layout/vertical/VerticalMenu.tsx
M 讯飞agent平台智能体链接.md（含凭据——是否入库需斟酌，gitignore 已挡 .env 但此 md 在库内）
?? app/api/assistant.py  ?? app/services/assistant_chat.py
?? frontend/plaza/src/app/(dashboard)/plaza/  ?? frontend/plaza/src/app/api/backend/assistant-chat/
?? frontend/plaza/src/configs/agents.ts  ?? frontend/plaza/src/views/agents/
```
建议消息：`feat(plaza): 自绘聊天界面接入讯飞助手 API（WS→SSE 桥，2 智能体）`。

## 待决策 / 待办

- **theme 字体 workaround 去留**：`@core/theme/index.ts` 移除了 Inter。若想在 Docker build 期恢复 google 字体，需给 build 提供代理或改用本地字体——当前系统字体栈可用，建议保持并接受。
- 讯飞 md 凭据已入库改动，建议把它从仓库跟踪中移除（或加密/占位）避免密钥进 git 历史。
- 智枢是否要 4 个都接入统一登录态（uid 目前是浏览器 randomUUID，非账号绑定）——暂无鉴权需求，扩展时再说。

## 风险与坑

- `StreamingResponse | JSONResponse` 联合注解必须配 `response_model=None`，否则 FastAPI 启动崩（本次踩过）。
- Docker build 外网不稳（registry/fonts 均偶发 EOF/TLS 超时）→ 用重试循环；基础镜像层已缓存，重建 app 很快。
- 全量 pytest 有预置失败 → 只跑单文件。app/domain 缺失在**当前 webui 分支不存在**（服务能起），勿照 memory 旧条目误判。
- 白名单是纯代码常量，忘加新 assistant_id 会 400——报错文案已含"不在白名单"帮助定位。

## suggested skills

- `/handoff` — 下次交接沿用 `docs/Temp/` 位置与本节结构（本任务已按此生成）。
- `verify` — Docker 起跑/端到端验收配方（app/webui/frontend/plaza 四容器健康检查 + curl SSE）。
- `write-memory` — 会话要点持久化（本任务已同步执行）。
- `superpowers:brainstorming` — 若要讨论广场整体规划/鉴权再开。
