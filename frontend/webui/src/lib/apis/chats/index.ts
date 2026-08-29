const BASE = '/api/v1/chats';

// 占位：聊天 API 客户端将在 Task 15+ 中实现。
export async function getChatList(token: string) {
	const res = await fetch(`${BASE}/`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('获取会话列表失败');
	return res.json();
}
