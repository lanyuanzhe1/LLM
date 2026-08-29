const BASE = '/api/v1/auths';

export async function signin(email: string, password: string) {
	const res = await fetch(`${BASE}/signin`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ email, password })
	});
	if (!res.ok) throw new Error('登录失败，请检查邮箱和密码');
	return res.json();
}

export async function signup(name: string, email: string, password: string) {
	const res = await fetch(`${BASE}/signup`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ name, email, password })
	});
	if (!res.ok) throw new Error('注册失败，邮箱可能已被使用');
	return res.json();
}

export async function getSessionUser(token: string) {
	const res = await fetch(`${BASE}/`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('会话已过期');
	return res.json();
}

export async function signout(token: string) {
	const res = await fetch(`${BASE}/signout`, {
		method: 'POST',
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('登出失败');
	return res.json();
}
