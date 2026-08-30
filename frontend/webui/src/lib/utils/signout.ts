import { goto } from '$app/navigation';
import { signout } from '$lib/apis/auths';
import { user } from '$lib/stores';

// 登出闭环：先通知后端删除 HttpOnly token cookie；即使后端调用失败，
// 也必须清空本地状态并跳回登录页，不能在共享浏览器上留下可用会话。
export const signOut = async () => {
	const token = localStorage.getItem('token');
	try {
		if (token) {
			await signout(token);
		}
	} catch {
		// 后端登出失败不阻塞本地清理
	} finally {
		localStorage.removeItem('token');
		user.set(null);
		goto('/auth');
	}
};
