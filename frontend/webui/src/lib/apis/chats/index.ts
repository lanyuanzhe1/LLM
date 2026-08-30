import { createSseParser, type ChatStreamEvent } from '$lib/utils/sse';

const BASE = '/api/v1/chats';

export type ChatSummary = {
	id: string;
	title: string;
	created_at?: number;
	updated_at?: number;
	[key: string]: unknown;
};

export type ChatDetail = {
	id: string;
	title?: string;
	chat?: {
		title?: string;
		models?: string[];
		history?: {
			messages?: Record<string, unknown>;
			currentId?: string | null;
		};
		messages?: unknown[];
		[key: string]: unknown;
	};
	[key: string]: unknown;
};

export async function getChatList(token: string): Promise<ChatSummary[]> {
	const res = await fetch(`${BASE}/`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('获取会话列表失败');
	return res.json();
}

export async function getChatById(token: string, id: string): Promise<ChatDetail> {
	const res = await fetch(`${BASE}/${id}`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('获取会话详情失败');
	return res.json();
}

export async function deleteChatById(token: string, id: string): Promise<boolean> {
	const res = await fetch(`${BASE}/${id}`, {
		method: 'DELETE',
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('删除会话失败');
	return res.json();
}

export type ChatCompletionRequest = {
	model: string;
	messages: { role: string; content: string }[];
	chat_id?: string | null;
};

/**
 * 流式聊天补全：POST /api/chat/completions，逐帧解析 SSE。
 * 多字节字符可能跨字节块到达，必须用 TextDecoder 流式解码，
 * 不能按块 toString（会把汉字腐蚀成 U+FFFD）。
 */
export async function streamChatCompletion(
	token: string,
	body: ChatCompletionRequest,
	onEvent: (event: ChatStreamEvent) => void
): Promise<void> {
	const res = await fetch('/api/chat/completions', {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			model: body.model,
			messages: body.messages,
			chat_id: body.chat_id ?? undefined,
			stream: true
		})
	});
	if (!res.ok || !res.body) {
		throw new Error('发送失败，请稍后重试');
	}

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	const parse = createSseParser(onEvent);
	try {
		for (;;) {
			const { done, value } = await reader.read();
			if (done) break;
			parse(decoder.decode(value, { stream: true }));
		}
		// 流末 flush：补齐悬在半空的尾部多字节字符
		parse(decoder.decode());
	} finally {
		reader.releaseLock();
	}
}
