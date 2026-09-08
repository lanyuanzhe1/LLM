# frontend/webui 镜像：SvelteKit SPA（vite dev，/api 反代到 webui 容器）
# build context 必须是仓库根：docker build -f docker/frontend.Dockerfile .
FROM node:22-alpine

WORKDIR /app

COPY frontend/webui/package.json frontend/webui/package-lock.json ./
RUN npm ci

COPY frontend/webui/ ./

EXPOSE 5173
# vite dev 需 --host 0.0.0.0 才能在容器外访问；/api 代理目标由
# WEBUI_PROXY_TARGET 控制（见 vite.config.ts），compose 里指向 webui 容器。
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
