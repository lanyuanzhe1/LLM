# 粮储智学前端

该目录基于 Materio Free MUI Next.js Admin Template v2.0.0 的 TypeScript 版本改造，
用于替代本地预览阶段的 Open WebUI 页面。原模板采用 MIT 许可证，许可证副本见
`MATERIO-LICENSE`，页脚保留 ThemeSelection 署名。

## 已实现页面

- `/`：学习工作台，展示真实后端和向量库状态；
- `/chat`：SSE 流式问答、角色选择、会话 ID、停止生成和证据来源卡片；
- `/knowledge`：从本地 ChatDoc 下载清单读取资料分类、文件和知识片段统计；
- `/cases`：储粮案例指标录入、信息完整性检查、流式分析和引用展示。

浏览器请求先进入 `src/app/api/` 下的 Next.js 服务端代理，再转发到 FastAPI。
`GRAIN_API_BASE_URL` 只在服务端读取，讯飞密钥不需要也不应写入前端环境文件。

## 本地运行

先在仓库根目录启动 FastAPI：

```powershell
$env:VECTOR_STORE_DIR='vector_store/base'
$env:VECTOR_STORE_ROOT_DIR='vector_store'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

再打开另一个终端：

```powershell
cd frontend
corepack prepare pnpm@9.15.9 --activate
corepack pnpm install --frozen-lockfile
Copy-Item .env.example .env
corepack pnpm dev
```

访问 `http://127.0.0.1:3000`。

## 构建检查

```powershell
corepack pnpm build
```

默认配置：

```dotenv
GRAIN_API_BASE_URL=http://127.0.0.1:8000
VECTOR_STORE_REPORT=../../vector_store/base/download_report.json
```

目前只完成本地接入，尚未把前端加入 Docker Compose，也没有替换服务器部署方案。
