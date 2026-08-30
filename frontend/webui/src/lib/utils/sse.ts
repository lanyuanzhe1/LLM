export type ChatStreamEvent =
	| { type: 'chat_id'; chatId: string }
	| { type: 'delta'; content: string }
	| { type: 'status'; description: string; done: boolean }
	| { type: 'source'; source: unknown }
	| { type: 'error'; message: string; code?: string }
	| { type: 'done' };

export function parseSseDataLine(payload: string): ChatStreamEvent | null {
	if (payload === '[DONE]') return { type: 'done' };
	let data: any;
	try {
		data = JSON.parse(payload);
	} catch {
		return null;
	}
	if (data?.error) {
		return {
			type: 'error',
			message: String(data.error.message ?? '服务暂时不可用'),
			code: data.error.code
		};
	}
	if (data?.event?.type === 'chat_id')
		return { type: 'chat_id', chatId: String(data.event.data.chat_id) };
	if (data?.event?.type === 'status') {
		return {
			type: 'status',
			description: String(data.event.data?.description ?? ''),
			done: Boolean(data.event.data?.done)
		};
	}
	if (data?.event?.type === 'source') return { type: 'source', source: data.event.data };
	const delta = data?.choices?.[0]?.delta?.content;
	if (typeof delta === 'string' && delta) return { type: 'delta', content: delta };
	return null;
}

/** Incremental SSE frame splitter over a text buffer. */
export function createSseParser(onEvent: (e: ChatStreamEvent) => void) {
	let buffer = '';
	return (chunk: string) => {
		buffer += chunk;
		let index;
		while ((index = buffer.indexOf('\n\n')) !== -1) {
			const frame = buffer.slice(0, index);
			buffer = buffer.slice(index + 2);
			for (const line of frame.split('\n')) {
				if (line.startsWith('data: ')) {
					const event = parseSseDataLine(line.slice(6));
					if (event) onEvent(event);
				}
			}
		}
	};
}
