import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getSessionUser, signin, signup } from './auths';

const mockFetch = (ok: boolean, body: unknown) => {
	return vi.fn().mockResolvedValue({
		ok,
		status: ok ? 200 : 401,
		json: () => Promise.resolve(body)
	});
};

describe('auths api', () => {
	beforeEach(() => {
		vi.stubGlobal('fetch', mockFetch(true, {}));
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('signin 成功返回 token', async () => {
		const payload = { token: 't-123', id: 'u1', email: 'a@b.com' };
		vi.stubGlobal('fetch', mockFetch(true, payload));

		const res = await signin('a@b.com', 'pw');
		expect(res.token).toBe('t-123');

		const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/api/v1/auths/signin');
		expect(init.method).toBe('POST');
		expect(JSON.parse(init.body)).toEqual({ email: 'a@b.com', password: 'pw' });
	});

	it('signin 401 时抛出中文错误', async () => {
		vi.stubGlobal('fetch', mockFetch(false, { detail: 'unauthorized' }));
		await expect(signin('a@b.com', 'wrong')).rejects.toThrow('登录失败，请检查邮箱和密码');
	});

	it('signup 成功返回用户', async () => {
		const payload = { token: 't-456', id: 'u2', email: 'c@d.com', name: '张三' };
		vi.stubGlobal('fetch', mockFetch(true, payload));

		const res = await signup('张三', 'c@d.com', 'pw');
		expect(res.token).toBe('t-456');

		const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/api/v1/auths/signup');
		expect(JSON.parse(init.body)).toEqual({ name: '张三', email: 'c@d.com', password: 'pw' });
	});

	it('signup 失败时抛出中文错误', async () => {
		vi.stubGlobal('fetch', mockFetch(false, {}));
		await expect(signup('张三', 'c@d.com', 'pw')).rejects.toThrow('注册失败，邮箱可能已被使用');
	});

	it('getSessionUser 携带 Bearer token', async () => {
		const payload = { id: 'u1', email: 'a@b.com' };
		vi.stubGlobal('fetch', mockFetch(true, payload));

		const res = await getSessionUser('tok-abc');
		expect(res.id).toBe('u1');

		const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/api/v1/auths/');
		expect(init.headers.Authorization).toBe('Bearer tok-abc');
	});

	it('getSessionUser 401 时抛出会话过期', async () => {
		vi.stubGlobal('fetch', mockFetch(false, {}));
		await expect(getSessionUser('bad')).rejects.toThrow('会话已过期');
	});
});
