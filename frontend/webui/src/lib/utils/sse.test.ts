import { describe, expect, it } from 'vitest';
import { createSseParser, parseSseDataLine, type ChatStreamEvent } from './sse';

describe('parseSseDataLine', () => {
	it('[DONE] → done 事件', () => {
		expect(parseSseDataLine('[DONE]')).toEqual({ type: 'done' });
	});

	it('chat_id 事件', () => {
		const payload = JSON.stringify({ event: { type: 'chat_id', data: { chat_id: 'abc-123' } } });
		expect(parseSseDataLine(payload)).toEqual({ type: 'chat_id', chatId: 'abc-123' });
	});

	it('delta 内容帧（chat.completion.chunk）', () => {
		const payload = JSON.stringify({
			id: 'chatcmpl-1',
			object: 'chat.completion.chunk',
			choices: [{ index: 0, delta: { content: '低温' }, finish_reason: null }]
		});
		expect(parseSseDataLine(payload)).toEqual({ type: 'delta', content: '低温' });
	});

	it('status 事件（含缺省字段回退）', () => {
		const payload = JSON.stringify({
			event: { type: 'status', data: { description: '正在检索知识库', done: false } }
		});
		expect(parseSseDataLine(payload)).toEqual({
			type: 'status',
			description: '正在检索知识库',
			done: false
		});

		const minimal = JSON.stringify({ event: { type: 'status', data: {} } });
		expect(parseSseDataLine(minimal)).toEqual({ type: 'status', description: '', done: false });
	});

	it('source 事件原样透传 data', () => {
		const sourceData = {
			source: { id: 'doc-e1', name: '粮油储藏技术' },
			document: ['低温可抑制害虫繁殖'],
			metadata: [{ name: '粮油储藏技术', evidence_id: 'e1' }],
			distances: [0.9]
		};
		const payload = JSON.stringify({ event: { type: 'source', data: sourceData } });
		expect(parseSseDataLine(payload)).toEqual({ type: 'source', source: sourceData });
	});

	it('error 事件（含缺省文案与 code 透传）', () => {
		const payload = JSON.stringify({
			error: { message: '粮储问答服务暂时不可用', code: 'WORKFLOW_UNAVAILABLE' }
		});
		expect(parseSseDataLine(payload)).toEqual({
			type: 'error',
			message: '粮储问答服务暂时不可用',
			code: 'WORKFLOW_UNAVAILABLE'
		});

		const noMessage = JSON.stringify({ error: {} });
		expect(parseSseDataLine(noMessage)).toEqual({
			type: 'error',
			message: '服务暂时不可用',
			code: undefined
		});
	});

	it('垃圾行 / 无法识别的帧返回 null', () => {
		expect(parseSseDataLine('not json at all')).toBeNull();
		expect(parseSseDataLine('{"foo":"bar"}')).toBeNull();
		// 空 delta（role-only 首帧 / finish 帧）不产生事件
		const roleOnly = JSON.stringify({
			object: 'chat.completion.chunk',
			choices: [{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }]
		});
		expect(parseSseDataLine(roleOnly)).toBeNull();
		const finish = JSON.stringify({
			object: 'chat.completion.chunk',
			choices: [{ index: 0, delta: {}, finish_reason: 'stop' }]
		});
		expect(parseSseDataLine(finish)).toBeNull();
	});
});

describe('createSseParser', () => {
	const collect = () => {
		const events: ChatStreamEvent[] = [];
		const parse = createSseParser((e) => events.push(e));
		return { events, parse };
	};

	it('跨 chunk 半帧拼接：帧被拆开时只在拼齐后派发', () => {
		const { events, parse } = collect();
		const frame = 'data: {"choices":[{"delta":{"content":"你好"}}]}\n\n';
		parse(frame.slice(0, 15));
		expect(events).toHaveLength(0);
		parse(frame.slice(15));
		expect(events).toEqual([{ type: 'delta', content: '你好' }]);
	});

	it('单 chunk 内多帧依次派发', () => {
		const { events, parse } = collect();
		parse(
			'data: {"event":{"type":"chat_id","data":{"chat_id":"c1"}}}\n\n' +
				'data: {"choices":[{"delta":{"content":"低"}}]}\n\n' +
				'data: {"choices":[{"delta":{"content":"温"}}]}\n\n' +
				'data: [DONE]\n\n'
		);
		expect(events).toEqual([
			{ type: 'chat_id', chatId: 'c1' },
			{ type: 'delta', content: '低' },
			{ type: 'delta', content: '温' },
			{ type: 'done' }
		]);
	});

	it('忽略非 data 行与垃圾 data 行，其余事件不受影响', () => {
		const { events, parse } = collect();
		parse(': 注释行\n\nevent: message\n\n');
		parse('data: {这不是JSON}\n\n');
		parse('data: {"choices":[{"delta":{"content":"粮"}}]}\n\n');
		expect(events).toEqual([{ type: 'delta', content: '粮' }]);
	});

	it('多字节字符跨 chunk 不被 TextDecoder 流式解码腐蚀', () => {
		const { events, parse } = collect();
		const sse =
			'data: {"choices":[{"delta":{"content":"低温储粮"}}]}\n\n' + 'data: [DONE]\n\n';
		const bytes = new TextEncoder().encode(sse);
		// 从「低」（E4 BD 8E，3 字节）的第 1 字节后切开
		const marker = new TextEncoder().encode('低温');
		const splitAt = bytes.indexOf(marker[0]) + 1;

		const decoder = new TextDecoder();
		parse(decoder.decode(bytes.slice(0, splitAt), { stream: true }));
		parse(decoder.decode(bytes.slice(splitAt), { stream: true }));
		parse(decoder.decode());

		expect(events).toEqual([{ type: 'delta', content: '低温储粮' }, { type: 'done' }]);
		const delta = events[0] as Extract<ChatStreamEvent, { type: 'delta' }>;
		expect(delta.content).not.toContain('\uFFFD');
	});
});
