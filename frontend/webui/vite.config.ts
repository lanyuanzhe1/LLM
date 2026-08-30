import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vitest/config';

// /api 反代目标：docker compose 里用 WEBUI_PROXY_TARGET 指向 webui 容器
// （http://webui:8080）；本机开发默认 127.0.0.1:8080 不变。
// 用 globalThis.process 避免引入 @types/node 依赖（运行时与 process.env 等价）。
const proxyTarget =
	(globalThis as { process?: { env?: Record<string, string> } }).process?.env
		?.WEBUI_PROXY_TARGET ?? 'http://127.0.0.1:8080';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: { proxy: { '/api': proxyTarget } },
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}'],
		environment: 'node'
	}
});
