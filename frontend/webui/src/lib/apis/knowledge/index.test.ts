import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getFileChunks, getKnowledgeFiles } from './index';

const mockFetch = (ok: boolean, status: number, body: unknown) => {
	return vi.fn().mockResolvedValue({
		ok,
		status,
		json: () => Promise.resolve(body)
	});
};

// 契约 fixture：与后端 tests/contract/test_knowledge_api.py 归一化外形一致
const FILES_FIXTURE = {
	files: [
		{
			file_id: 'file-1',
			name: '低温储粮.pdf',
			status: 'vectored',
			chunk_count: null,
			size_bytes: null,
			source_path: '知识库/低温储粮.pdf'
		}
	]
};

const CHUNKS_FIXTURE = {
	file_id: 'file-1',
	name: '低温储粮.pdf',
	chunks: [
		{ index: 0, text: '仓储管理基础。' },
		{ index: 1, text: '低温抑制呼吸。' }
	]
};

describe('knowledge api', () => {
	beforeEach(() => {
		vi.stubGlobal('fetch', mockFetch(true, 200, {}));
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('getKnowledgeFiles 携带 Bearer 调文件列表接口', async () => {
		vi.stubGlobal('fetch', mockFetch(true, 200, FILES_FIXTURE));

		const res = await getKnowledgeFiles('tok-abc');
		expect(res.files[0].file_id).toBe('file-1');

		const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/api/v1/knowledge/files');
		expect(init.headers.Authorization).toBe('Bearer tok-abc');
	});

	it('getKnowledgeFiles 503 时抛知识库不可用', async () => {
		vi.stubGlobal('fetch', mockFetch(false, 503, { detail: 'KNOWLEDGE_UNAVAILABLE' }));
		await expect(getKnowledgeFiles('tok')).rejects.toThrow('知识库暂时无法加载');
	});

	it('getFileChunks 携带 Bearer 调分块接口并解析', async () => {
		vi.stubGlobal('fetch', mockFetch(true, 200, CHUNKS_FIXTURE));

		const res = await getFileChunks('tok-abc', 'file-1');
		expect(res.name).toBe('低温储粮.pdf');
		expect(res.chunks).toHaveLength(2);

		const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0];
		expect(url).toBe('/api/v1/knowledge/files/file-1/chunks');
		expect(init.headers.Authorization).toBe('Bearer tok-abc');
	});

	it('getFileChunks 404 时抛加载失败', async () => {
		vi.stubGlobal('fetch', mockFetch(false, 404, { detail: 'DOCUMENT_NOT_FOUND' }));
		await expect(getFileChunks('tok', 'file-missing')).rejects.toThrow('文件分块加载失败');
	});
});
