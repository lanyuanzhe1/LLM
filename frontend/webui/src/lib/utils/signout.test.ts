import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/apis/auths', () => ({ signout: vi.fn() }));

import { goto } from '$app/navigation';
import { signout } from '$lib/apis/auths';
import { user } from '$lib/stores';
import { signOut } from './signout';

describe('signOut 登出闭环', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.stubGlobal('localStorage', {
			getItem: vi.fn(() => 'tok-abc'),
			setItem: vi.fn(),
			removeItem: vi.fn()
		});
		user.set({
			token: 'tok-abc',
			id: 'u1',
			email: 'a@b.com'
		});
	});

	it('先调后端 signout 删除 cookie，再清本地状态并跳 /auth', async () => {
		vi.mocked(signout).mockResolvedValue({ status: true });

		await signOut();

		expect(signout).toHaveBeenCalledWith('tok-abc');
		expect(localStorage.removeItem).toHaveBeenCalledWith('token');
		expect(get(user)).toBeNull();
		expect(goto).toHaveBeenCalledWith('/auth');
	});

	it('后端 signout 失败时本地状态仍清空并跳 /auth', async () => {
		vi.mocked(signout).mockRejectedValue(new Error('登出失败'));

		await signOut();

		expect(signout).toHaveBeenCalledWith('tok-abc');
		expect(localStorage.removeItem).toHaveBeenCalledWith('token');
		expect(get(user)).toBeNull();
		expect(goto).toHaveBeenCalledWith('/auth');
	});

	it('本地无 token 时跳过后端调用，仍清状态并跳 /auth', async () => {
		vi.mocked(localStorage.getItem).mockReturnValue(null);

		await signOut();

		expect(signout).not.toHaveBeenCalled();
		expect(localStorage.removeItem).toHaveBeenCalledWith('token');
		expect(get(user)).toBeNull();
		expect(goto).toHaveBeenCalledWith('/auth');
	});
});
