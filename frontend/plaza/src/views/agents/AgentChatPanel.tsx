'use client'

// 自绘聊天界面：把有 API 的讯飞智能体（agent.assistantId 已配置）嵌入为原生聊天，
// 通过 /api/backend/assistant-chat → FastAPI /v1/assistant/chat → 讯飞 WebSocket 流式对话。
import { useEffect, useRef, useState } from 'react'

import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'

import { consumeSse } from '@/lib/consumeSse'
import { withBasePath } from '@/lib/base-path'
import { genId } from '@/utils/genId'
import type { AgentConfig } from '@/configs/agents'

type Line = {
	id: string;
	role: 'user' | 'assistant';
	content: string;
	pending?: boolean;
	error?: boolean;
};

const createId = () => genId();

const suggestions = [
	'请用一两句话介绍你自己。',
	'请结合你的专业领域，给我一个最能体现你价值的示例提问。'
];

const AgentChatPanel = ({ agent }: { agent: AgentConfig }) => {
	const [messages, setMessages] = useState<Line[]>([]);
	const [input, setInput] = useState('');
	const [streaming, setStreaming] = useState(false);
	const abortRef = useRef<AbortController | null>(null);
	const listRef = useRef<HTMLDivElement | null>(null);
	const sessionRef = useRef<string>(createId());

	const hasAsked = messages.some(message => message.role === 'user');

	const updateLine = (id: string, update: (line: Line) => Line) => {
		setMessages(current => current.map(message => (message.id === id ? update(message) : message)));
	};

	const send = async (text?: string) => {
		const content = (text ?? input).trim();

		if (!content || streaming || !agent.assistantId) return;

		const history = messages
			.filter(message => !message.pending)
			.map(message => ({ role: message.role, content: message.content }));

		const userId = createId();
		const assistantId = createId();
		const controller = new AbortController();

		setMessages(current => [...current, { id: userId, role: 'user', content }, { id: assistantId, role: 'assistant', content: '', pending: true }]);
		setInput('');
		setStreaming(true);
		abortRef.current = controller;

		try {
			const response = await fetch(withBasePath('/api/backend/assistant-chat'), {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					assistant_id: agent.assistantId,
					uid: sessionRef.current,
					messages: [...history, { role: 'user' as const, content }]
				}),
				signal: controller.signal
			});

			if (!response.ok) {
				const error = (await response.json().catch(() => null)) as { message?: string } | null;

				throw new Error(error?.message || `请求失败（HTTP ${response.status}）`);
			}

			await consumeSse(response, (event, data) => {
				const payload = data as Record<string, unknown>;

				if (event === 'delta' && typeof payload.content === 'string') {
					updateLine(assistantId, current => ({ ...current, content: current.content + payload.content, pending: true }));
				}

				if (event === 'error') {
					const message = typeof payload.message === 'string' ? payload.message : '生成回答时发生错误。';

					updateLine(assistantId, current => ({ ...current, content: current.content || message, error: true, pending: false }));
				}

				if (event === 'done') {
					updateLine(assistantId, current => ({ ...current, pending: false }));
				}
			});
		} catch (error) {
			const stopped = error instanceof DOMException && error.name === 'AbortError';

			updateLine(assistantId, current => ({
				...current,
				content: current.content || (stopped ? '已停止本次回答。' : error instanceof Error ? error.message : '请求失败。'),
				error: !stopped,
				pending: false
			}));
		} finally {
			abortRef.current = null;
			setStreaming(false);
		}
	};

	useEffect(() => {
		const list = listRef.current;

		list?.scrollTo({ top: list.scrollHeight, behavior: 'smooth' });
	}, [messages]);

	return (
		<Box sx={{ display: 'flex', minHeight: 0, flex: 1, flexDirection: 'column' }}>
			<Divider />

			<Box ref={listRef} sx={{ flex: 1, overflowY: 'auto', px: { xs: 3, md: 6 }, py: 4 }}>
				{!hasAsked ? (
					<Box className='flex h-full flex-col items-center justify-center gap-6 text-center'>
						<Avatar sx={{ width: 64, height: 64, bgcolor: agent.color }}>
							<i className={`${agent.icon} text-3xl`} />
						</Avatar>
						<div>
							<Typography variant='h5' className='font-semibold'>
								{agent.name}
							</Typography>
							<Typography variant='body2' color='text.secondary' sx={{ maxWidth: 420, mx: 'auto', mt: 1 }}>
								{agent.description}。直接输入问题开始对话，回答由平台智能体生成。
							</Typography>
						</div>
						<Box className='flex flex-wrap justify-center gap-3'>
							{suggestions.map(prompt => (
								<Button key={prompt} variant='outlined' color='inherit' disabled={streaming} onClick={() => void send(prompt)}>
									{prompt}
								</Button>
							))}
						</Box>
					</Box>
				) : (
					<Box sx={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
						{messages.map(message => (
							<Box key={message.id} sx={{ display: 'flex', justifyContent: message.role === 'user' ? 'flex-end' : 'flex-start', gap: 2 }}>
								{message.role === 'assistant' && (
									<Avatar sx={{ width: 34, height: 34, bgcolor: agent.color }}>
										<i className={`${agent.icon} text-lg`} />
									</Avatar>
								)}
								<Box sx={{ maxWidth: { xs: '88%', md: '80%' } }}>
									<Box
										sx={{
											px: 4,
											py: 3,
											borderRadius: 3,
											whiteSpace: 'pre-wrap',
											overflowWrap: 'anywhere',
											color: message.role === 'user' ? 'primary.contrastText' : message.error ? 'error.main' : 'text.primary',
											bgcolor: message.role === 'user' ? 'primary.main' : 'background.paper',
											boxShadow: message.role === 'assistant' ? 1 : 0
										}}
									>
										{message.content || (message.pending && <span className='flex items-center gap-2'><CircularProgress size={16} />正在思考…</span>)}
									</Box>
								</Box>
							</Box>
						))}
					</Box>
				)}
			</Box>

			<Divider />
			<Box sx={{ p: { xs: 2.5, md: 3 } }}>
				<div className='flex items-end gap-3'>
					<TextField
						fullWidth
						multiline
						minRows={1}
						maxRows={5}
						value={input}
						placeholder={`向 ${agent.name} 提问，Shift + Enter 换行…`}
						onChange={event => setInput(event.target.value)}
						onKeyDown={event => {
							if (event.key === 'Enter' && !event.shiftKey) {
								event.preventDefault();
								void send();
							}
						}}
						disabled={streaming}
					/>
					{streaming ? (
						<Button variant='outlined' color='error' onClick={() => abortRef.current?.abort()} sx={{ minWidth: 92, height: 56 }}>
							停止
						</Button>
					) : (
						<Button
							variant='contained'
							disabled={!input.trim()}
							onClick={() => void send()}
							endIcon={<i className='ri-send-plane-2-line' />}
							sx={{ minWidth: 92, height: 56 }}
						>
							发送
						</Button>
					)}
				</div>
			</Box>
		</Box>
	);
};

export default AgentChatPanel;
