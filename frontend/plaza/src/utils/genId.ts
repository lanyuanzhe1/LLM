/**
 * 生成随机 ID。
 *
 * 优先用 crypto.randomUUID()，但它只在浏览器安全上下文（HTTPS / localhost）可用；
 * 裸 HTTP + IP 部署（如 http://服务器IP）下 crypto.randomUUID 是 undefined，
 * 直接调用会抛 TypeError 导致整页客户端崩溃，故回退到时间戳+随机数方案。
 */
export const genId = (): string =>
  typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
