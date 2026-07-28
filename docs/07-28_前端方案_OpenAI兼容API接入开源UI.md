# 前端对话界面方案：封装 OpenAI 兼容 API 接入开源前端 UI

> 日期：2026-07-28
> 状态：方案讨论定稿，待实施

## 1. 背景

仓库根目录的 `chat_ui.py`（7860 端口）是最初为测试 RAG 链路做的**临时调试工具**：单文件 `http.server` + 内嵌 HTML，知识库为纯内存实例，存在以下问题：

- 启动后知识库为空，强制上传文档才能对话（无检索结果时直接返回 404 "请先上传文档"）；
- 不读磁盘上的 `vector_store/base/` 底座库（该库属于 `app/` FastAPI 服务体系，由 `ingest_knowledge.py --scope base` 生成）；
- 无会话持久化、无用户体系，界面功能简陋。

与此同时，`app/` 下的 FastAPI 后端已经具备正规结构（api / rag / services / clients 分层、向量库磁盘加载、会话服务）。由此引出核心问题：**正规的 agent 软件应该如何做前端对话界面？**

## 2. 方案对比

| 方案 | 做法 | 前端工作量 | 定制自由度 | 适用场景 |
|---|---|---|---|---|
| A. Chainlit | Python 写少量代码挂在 RAG 链路上，自动生成聊天 UI | 小 | 中 | 内部演示、快速试用 |
| B. 前后端分离自研 | Vite + React + Vercel AI SDK / assistant-ui，对接 `app/` FastAPI | 大 | 高（完全自由） | 需要深度定制的正式产品 |
| **C. OpenAI 兼容 API + 现成开源 UI（选定）** | 给 FastAPI 加 `/v1/chat/completions` 兼容端点，接 Open WebUI 等现成前端 | **零** | 低（受现成 UI 限制） | 想要完整体验但不想写前端 |

**结论：采用方案 C。** `chat_ui.py` 保留为冒烟测试工具，不再继续加功能。

## 3. 方案 C 原理

OpenAI 的对话接口 `POST /v1/chat/completions`（请求为 `messages` 数组，响应支持 SSE 流式逐 token 返回）已成行业事实标准。社区围绕它出现了一批**开源的完整聊天应用**：它们本身不带模型，只是纯前端壳，在设置里填"API 地址 + 密钥"即可连接任何兼容该格式的后端。

因此只需在后端写一个**协议转换层**（约一两百行）：

1. 接收 OpenAI 格式请求 `{model, messages, stream: true}`；
2. 取用户最后一条消息 → 走 `app/` 现有 RAG 检索；
3. 调用讯飞 MaaS 生成，把讯飞 WebSocket 流式帧**逐 token 翻译成 OpenAI SSE 格式**：
   - 每个 token 发 `data: {"choices":[{"delta":{"content":"..."}}]}`
   - 结尾发 `data: [DONE]`

附带收益：任何兼容 OpenAI 的工具（SDK、插件、其他 UI）今后都能直接接入。

## 4. 现成开源 UI 选型

| 项目 | GitHub | 官网/文档 | 特点 |
|---|---|---|---|
| **Open WebUI（推荐）** | [open-webui/open-webui](https://github.com/open-webui/open-webui) | [docs.openwebui.com](https://docs.openwebui.com) | star 最多（10 万+），功能最全：会话历史、多会话、Markdown/代码渲染、文件上传、联网搜索、用户管理、移动端适配，相当于"私有部署的 ChatGPT 网页版"，Docker 一键部署 |
| LobeChat | [lobehub/lobe-chat](https://github.com/lobehub/lobe-chat) | [lobechat.com](https://lobechat.com) | 界面最精致，插件市场丰富，适合对外演示 |
| LibreChat | [danny-avila/LibreChat](https://github.com/danny-avila/LibreChat) | [librechat.ai](https://www.librechat.ai) | 多模型切换最好（一个界面配多个后端），偏极客向 |
| NextChat（原 ChatGPT-Next-Web） | [ChatGPTNextWeb/NextChat](https://github.com/ChatGPTNextWeb/NextChat) | [nextchat.dev](https://nextchat.dev) | 最轻量，Vercel 一键部署，适合个人快速使用 |

**推荐 Open WebUI**：部署最简单，自带完整用户体系，适合粮库团队内部使用。

## 5. 部署架构

用户浏览器只连 Open WebUI，由它转发到后端：

```
用户浏览器  ──→  http://服务器IP:3000  (Open WebUI 容器)
                        │  容器内部请求
                        ▼
                http://服务器:8000/v1  (FastAPI + RAG，app/)
                        │
                        ▼
                讯飞 Embedding / MaaS API
```

### 5.1 启动 FastAPI 后端

```bash
conda activate LLM
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` 必须加，使其监听所有网卡（默认仅本机回环）。

### 5.2 启动 Open WebUI（用户入口）

```bash
docker run -d --name open-webui \
  -p 3000:8080 \
  --add-host=host.docker.internal:host-gateway \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1 \
  -e OPENAI_API_KEY=sk-local \
  -v open-webui:/app/backend/data \
  --restart always \
  ghcr.io/open-webui/open-webui:main
```

要点：

- `-p 3000:8080`：用户通过 `http://服务器IP:3000` 访问；
- `--add-host=host.docker.internal:host-gateway`：Linux 上容器访问宿主机必须加（Mac/Windows Docker 自带），否则连不到宿主机的 FastAPI；
- `-v open-webui:...`：会话记录与用户数据持久化；
- `--restart always`：服务器重启后自动拉起。

### 5.3 用户体系（Open WebUI 自带，零开发）

- 首次打开 `http://服务器IP:3000`，**第一个注册的用户自动成为管理员**；
- 建议管理员后台关闭公开注册，改为手动创建账号或审批（或注册完管理员后用 `-e ENABLE_SIGNUP=false` 重启）；
- 知识库文档的入库管理仍走自己的入口（入库 CLI / 管理接口），现成 UI 只负责对话。

### 5.4 域名 + HTTPS（可选，公网场景）

前面套一层 Caddy（自动签 HTTPS 证书）：

```
# Caddyfile
rag.your-domain.com {
    reverse_proxy localhost:3000
}
```

防火墙只开放 443；SSE 流式输出 Caddy 默认正常转发（若用 nginx，加 `proxy_buffering off;`）。

### 5.5 内网场景（粮库系统大概率如此）

跳过 5.4，直接 `http://内网IP:3000` 给用户使用即可，无需 HTTPS。

### 5.6 运维建议

用 `docker-compose.yml` 把 FastAPI 与 Open WebUI 统一管理，`docker compose up -d` 一条命令全量启动，便于升级与迁移。

## 6. 方案的代价与限制

- **定制自由度低**：界面样式、来源引用展示方式受现成 UI 限制；RAG 来源一般只能由模型在回答末尾以文本标注（现有 system prompt 已如此），做不出"点击引用卡片跳转原文块"这类定制交互；
- **多一个部署组件**：需运行 Docker 容器；
- 若未来确需深度定制界面，再升级到方案 B（自研 React），协议转换层不浪费——任何前端都能继续复用。

## 7. 待办（下一步）

- [ ] 在 `app/` 实现 `/v1/chat/completions` 兼容端点：请求解析 → RAG 检索 → MaaS 流式生成 → OpenAI SSE 格式翻译；
- [ ] （可选）`GET /v1/models` 端点，供 UI 列出模型；
- [ ] 编写 `docker-compose.yml`（FastAPI + Open WebUI）；
- [ ] 服务器部署验证：注册管理员、关闭公开注册、实际问答测试；
- [ ] `chat_ui.py` 免上传对话小补丁（保留其冒烟测试工具定位，低优先级）。
