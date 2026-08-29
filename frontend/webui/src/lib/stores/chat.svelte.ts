import { goto } from '$app/navigation';
import { getChatById, streamChatCompletion } from '$lib/apis/chats';
import { getModels } from '$lib/apis/models';
import { TOKEN_STORAGE_KEY } from '$lib/constants';
import { generateUuid } from '$lib/utils';

export type SourceItem = {
	name: string;
	excerpt: string;
};

export type ChatMessage = {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	sources: SourceItem[];
};

type HistoryMessage = {
	id?: string;
	role?: string;
	content?: unknown;
	parentId?: string | null;
	childrenIds?: string[];
	timestamp?: number;
	sources?: unknown[];
};

/** source 事件 data 外形：{source:{id,name}, document:[摘录], metadata:[{name,evidence_id}]} */
export const normalizeSource = (raw: unknown): SourceItem => {
	const data = (raw ?? {}) as {
		source?: { name?: unknown };
		document?: unknown;
		metadata?: { name?: unknown }[];
	};
	const name = data.source?.name ?? data.metadata?.[0]?.name ?? '未命名来源';
	const docs = Array.isArray(data.document) ? data.document : [];
	const excerpt = typeof docs[0] === 'string' ? docs[0] : '';
	return { name: String(name), excerpt };
};

const dedupeSources = (sources: SourceItem[]): SourceItem[] => {
	const seen = new Set<string>();
	return sources.filter((s) => {
		const key = `${s.name}${s.excerpt}`;
		if (seen.has(key)) return false;
		seen.add(key);
		return true;
	});
};

export const contentToText = (content: unknown): string => {
	if (typeof content === 'string') return content;
	if (Array.isArray(content)) {
		return content
			.map((block) => {
				if (typeof block === 'string') return block;
				if (block && typeof block === 'object' && (block as { type?: unknown }).type === 'text') {
					return String((block as { text?: unknown }).text ?? '');
				}
				return '';
			})
			.join('');
	}
	return content == null ? '' : String(content);
};

/** 从 history.currentId 沿 parentId 回溯成时间正序消息链（createMessagesList 语义）。 */
export const createMessagesList = (history: unknown): ChatMessage[] => {
	const h = (history ?? {}) as {
		messages?: Record<string, HistoryMessage>;
		currentId?: string | null;
	};
	const map = h.messages && typeof h.messages === 'object' ? h.messages : {};
	const chain: ChatMessage[] = [];
	const seen = new Set<string>();
	let cursor: string | null | undefined = h.currentId;
	while (cursor && map[cursor] && !seen.has(cursor)) {
		seen.add(cursor);
		const message = map[cursor];
		if (message.role === 'user' || message.role === 'assistant') {
			chain.unshift({
				id: message.id ?? cursor,
				role: message.role,
				content: contentToText(message.content),
				sources: Array.isArray(message.sources)
					? dedupeSources(message.sources.map(normalizeSource))
					: []
			});
		}
		cursor = message.parentId ?? null;
	}
	return chain;
};

/**
 * 聊天会话单例：状态与流式生成全部挂在模块级单例上，
 * 使「/ 发送 → 收到 chat_id → goto /c/[id]」导致的页面组件重挂载
 * 不打断生成中的流（组件只渲染本状态，不持有它）。
 */
class ChatSession {
	chatId = $state<string | null>(null);
	messages = $state<ChatMessage[]>([]);
	generating = $state(false);
	loadingHistory = $state(false);
	statusText = $state('');
	errorMessage = $state('');
	/** true 表示本会话已初始化（历史已载入或生成已开始），重挂载时直接沿用 */
	touched = $state(false);
	modelId = '';
	/** 每次发送 / 切换会话时 +1，失效回调据此丢弃写入 */
	runId = 0;

	reset(id: string | null): number {
		this.runId += 1;
		this.chatId = id;
		this.messages = [];
		this.generating = false;
		this.loadingHistory = false;
		this.statusText = '';
		this.errorMessage = '';
		this.touched = false;
		return this.runId;
	}
}

export const session = new ChatSession();

const getTokenOrRedirect = (): string | null => {
	const token = localStorage.getItem(TOKEN_STORAGE_KEY);
	if (!token) goto('/auth');
	return token;
};

/** 载入（或清空为）指定会话；组件挂载 / chatId 变化时调用。 */
export const loadChat = async (id: string | null): Promise<void> => {
	if (session.chatId === id && session.touched) return; // 沿用进行中会话
	const myRun = session.reset(id);
	if (!id) {
		session.touched = true;
		return;
	}
	const token = getTokenOrRedirect();
	if (!token) return;
	session.loadingHistory = true;
	try {
		const detail = await getChatById(token, id);
		if (myRun !== session.runId) return;
		session.messages = createMessagesList(detail?.chat?.history);
		session.touched = true;
	} catch {
		if (myRun !== session.runId) return;
		session.errorMessage = '会话加载失败，请稍后重试';
		session.touched = true;
	} finally {
		if (myRun === session.runId) session.loadingHistory = false;
	}
};

const ensureModelId = async (token: string): Promise<string> => {
	if (session.modelId) return session.modelId;
	const models = await getModels(token);
	const id = models?.data?.[0]?.id;
	if (!id) throw new Error('模型列表为空');
	session.modelId = id;
	return id;
};

export const sendMessage = async (rawContent: string): Promise<void> => {
	const content = rawContent.trim();
	if (!content || session.generating) return;
	const token = getTokenOrRedirect();
	if (!token) return;

	session.errorMessage = '';
	session.statusText = '';
	// 先占位再 await：关闭 ensureModelId 网络窗口内的双重发送
	session.generating = true;
	const startRun = session.runId;

	let model: string;
	try {
		model = await ensureModelId(token);
	} catch {
		// 与成功路径对称：await 期间已切换会话（reset 已 bump runId），
		// 本次失败与当前会话无关，不得清掉新会话飞行中的守卫或写错误横幅
		if (session.runId === startRun) {
			session.errorMessage = '模型列表获取失败，请稍后重试';
			session.generating = false;
		}
		return;
	}
	if (session.runId !== startRun) return; // await 期间已切换会话，放弃本次发送

	const myRun = ++session.runId;
	const userMessage: ChatMessage = { id: generateUuid(), role: 'user', content, sources: [] };
	const assistantMessage: ChatMessage = {
		id: generateUuid(),
		role: 'assistant',
		content: '',
		sources: []
	};
	session.messages = [...session.messages, userMessage, assistantMessage];
	// 必须经由 $state 代理句柄追加流式内容：直接改写原始对象不会触发视图更新
	const assistant = session.messages[session.messages.length - 1];
	session.touched = true;
	session.statusText = '正在思考…';

	let failed = false;
	try {
		await streamChatCompletion(
			token,
			{
				model,
				messages: [{ role: 'user', content }],
				chat_id: session.chatId
			},
			(event) => {
				if (myRun !== session.runId) return; // 已切换会话，丢弃失效写入
				switch (event.type) {
					case 'chat_id':
						if (!session.chatId) {
							session.chatId = event.chatId;
							goto(`/c/${event.chatId}`, { replaceState: true, noScroll: true });
						}
						break;
					case 'delta':
						assistant.content += event.content;
						break;
					case 'status':
						session.statusText = event.description;
						break;
					case 'source': {
						const item = normalizeSource(event.source);
						if (!assistant.sources.some((s) => s.name === item.name && s.excerpt === item.excerpt)) {
							assistant.sources = [...assistant.sources, item];
						}
						break;
					}
					case 'error':
						failed = true;
						session.errorMessage = event.message || '服务暂时不可用';
						break;
					case 'done':
						break;
				}
			}
		);
	} catch {
		if (myRun === session.runId) {
			failed = true;
			session.errorMessage = '网络异常，请稍后重试';
		}
	} finally {
		if (myRun === session.runId) {
			// 失败且一字未答：撤掉空气泡，只留错误横幅（不伪造回答）
			if (failed && !assistant.content) {
				session.messages = session.messages.filter((m) => m.id !== assistant.id);
			}
			session.generating = false;
			session.statusText = '';
		}
	}
};
