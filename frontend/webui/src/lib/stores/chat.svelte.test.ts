import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/apis/models', () => ({ getModels: vi.fn() }));
vi.mock('$lib/apis/chats', () => ({
	getChatList: vi.fn(),
	getChatById: vi.fn(),
	deleteChatById: vi.fn(),
	streamChatCompletion: vi.fn()
}));

import { goto } from '$app/navigation';
import { getModels } from '$lib/apis/models';
import { streamChatCompletion } from '$lib/apis/chats';
import { sendMessage, session } from './chat.svelte';

describe('sendMessage 双重发送守卫', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		vi.stubGlobal('localStorage', {
			getItem: vi.fn(() => 'tok'),
			setItem: vi.fn(),
			removeItem: vi.fn()
		});
		session.reset(null);
		session.touched = true;
		session.modelId = '';
	});

	it('ensureModelId 未 resolve 时第二次调用被拦截，不追加消息', async () => {
		// 首次发送卡在模型列表请求上（真实网络窗口的替身）
		vi.mocked(getModels).mockReturnValue(new Promise(() => {}));

		const first = sendMessage('问题一');
		await sendMessage('问题二'); // 应被 generating 守卫直接拦截

		expect(vi.mocked(getModels)).toHaveBeenCalledTimes(1);
		expect(session.messages).toHaveLength(0);
		expect(session.generating).toBe(true);
		void first; // 首个调用永远悬置，测试进程无需等待
	});

	it('await 期间切换会话后，旧发送的失败不复位新会话状态', async () => {
		let rejectA!: (reason: Error) => void;
		vi.mocked(getModels)
			.mockReturnValueOnce(
				new Promise((_, reject) => {
					rejectA = reject;
				})
			)
			.mockReturnValueOnce(new Promise(() => {})); // B 悬置于第二次模型请求

		const a = sendMessage('A 的问题'); // 同步段执行完：generating=true，卡在 getModels
		session.reset('other'); // 用户切换会话：runId bump、generating=false、errorMessage=''
		session.touched = true;
		const b = sendMessage('B 的问题'); // 新会话合法发送，generating=true 飞行中

		rejectA(new Error('boom'));
		await a;

		expect(session.generating).toBe(true); // B 的守卫未被旧失败清掉
		expect(session.errorMessage).toBe(''); // 未写入与 A 会话无关的错误横幅
		expect(session.messages).toHaveLength(0);
		void b;
	});

	it('模型列表获取失败时复位 generating，可再次发送', async () => {
		vi.mocked(getModels).mockRejectedValue(new Error('boom'));

		await sendMessage('问题');

		expect(session.generating).toBe(false);
		expect(session.errorMessage).toBe('模型列表获取失败，请稍后重试');
		expect(session.messages).toHaveLength(0);

		// 复位后重试可用
		vi.mocked(getModels).mockResolvedValue({ data: [{ id: 'm1' }] });
		vi.mocked(streamChatCompletion).mockResolvedValue(undefined);
		await sendMessage('问题');
		expect(session.messages).toHaveLength(2);
	});

	it('成功路径：首帧 chat_id 导航，delta 落入 assistant 气泡', async () => {
		vi.mocked(getModels).mockResolvedValue({ data: [{ id: 'm1' }] });
		vi.mocked(streamChatCompletion).mockImplementation(async (_token, body, onEvent) => {
			expect(body.model).toBe('m1');
			expect(body.messages).toEqual([{ role: 'user', content: '低温储粮要点？' }]);
			expect(body.chat_id).toBeNull();
			onEvent({ type: 'chat_id', chatId: 'c1' });
			onEvent({ type: 'delta', content: '你好' });
			onEvent({ type: 'done' });
		});

		await sendMessage('低温储粮要点？');

		expect(vi.mocked(goto)).toHaveBeenCalledWith('/c/c1', {
			replaceState: true,
			noScroll: true
		});
		expect(session.chatId).toBe('c1');
		expect(session.generating).toBe(false);
		expect(session.messages).toHaveLength(2);
		expect(session.messages[0].role).toBe('user');
		expect(session.messages[1]).toMatchObject({ role: 'assistant', content: '你好' });
	});

	it('modelId 缓存：后续发送不再请求模型列表', async () => {
		vi.mocked(getModels).mockResolvedValue({ data: [{ id: 'm1' }] });
		vi.mocked(streamChatCompletion).mockResolvedValue(undefined);

		await sendMessage('第一条');
		await sendMessage('第二条');

		expect(vi.mocked(getModels)).toHaveBeenCalledTimes(1);
		expect(session.messages).toHaveLength(4);
	});
});
