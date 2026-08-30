# 三子容器一键起跑（docker compose）

把整套系统（app 领域服务 / webui 应用服务 / frontend SPA）容器化，
`docker compose up` 即可，无需本机装 Python/Node 环境。

compose 项目名 `grain-agent`（`docker-compose.yml` 顶层 `name:`），
容器/镜像即 `grain-agent-app` / `grain-agent-webui` / `grain-agent-frontend`。

## 启动

```bash
docker compose up -d --build
```

- 浏览器打开 **http://127.0.0.1:5173**（前端，vite dev，`/api` 反代到 webui）
- webui API 直连：http://127.0.0.1:8080
- app API 直连：http://127.0.0.1:8000

首次使用在浏览器注册一个账号即可（登录 → `/knowledge` 可看真实知识库 30 文件与分块）。

## 前置条件

- 根 `.env`（app 的 `XF_*`、`OPENAI_COMPAT_API_KEY`、`TOOLS_SERVICE_TOKEN` 等）
- `services/webui/.env`（`WEBUI_SECRET_KEY`、`OPENAI_COMPAT_API_KEY` 与 app 同值）
- `artifacts/chatdoc/base.json`（ChatDoc 清单，已在 git 跟踪；须先经 `ingest_knowledge.py --scope base` 生成）
- Docker + compose（本机 29.6.2 / v5.3.1）

## 常见坑

1. **端口冲突**：本机若还跑着 app/webui/vite 旧服务，先停掉再 `compose up`（8000/8080/5173）。
2. **出网代理**：容器默认直连 iFlytek。若必须经宿主代理（如本机 127.0.0.1:7897），
   给 `app`/`webui` 加 `environment: HTTP_PROXY/HTTPS_PROXY=http://host.docker.internal:7897`。
   ⚠️ MaaS 走 `websockets` 库，**不认代理环境变量**，经代理的 WebSocket 问答会失败——若必须代理访问，这是硬限制。
3. **SQLite 持久化**：webui 的 `webui_data` 卷挂在 `/app/data`，重启不丢账号/会话。
4. **改前端代码**：vite dev 容器内热重载，改完即生效；`/api` 代理目标由 `WEBUI_PROXY_TARGET` 控制（compose 已设 `http://webui:8080`）。
