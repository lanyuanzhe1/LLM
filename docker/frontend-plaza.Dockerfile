# 智能体广场 Next.js 前端：以 /agents 挂到 SvelteKit 同源入口。
FROM node:22-alpine

WORKDIR /app

RUN corepack enable

COPY frontend/plaza/package.json frontend/plaza/pnpm-lock.yaml frontend/plaza/.npmrc ./
COPY frontend/plaza/src/assets/iconify-icons/bundle-icons-css.ts ./src/assets/iconify-icons/
RUN pnpm install --frozen-lockfile

COPY frontend/plaza/ ./

ARG BASEPATH=/agents
ARG NEXT_PUBLIC_BASE_PATH=/agents
ENV BASEPATH=${BASEPATH}
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}

RUN pnpm build

EXPOSE 3000
CMD ["pnpm", "start", "-H", "0.0.0.0"]
