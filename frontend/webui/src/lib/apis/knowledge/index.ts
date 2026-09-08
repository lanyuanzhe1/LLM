const BASE = '/api/v1/knowledge';

export type KnowledgeFile = {
	file_id: string;
	name: string;
	status: string;
	chunk_count?: number | null;
	size_bytes?: number | null;
	source_path?: string | null;
};

export type KnowledgeFileList = { files: KnowledgeFile[] };

export type KnowledgeChunk = { index: number; text: string };

export type KnowledgeFileChunks = {
	file_id: string;
	name: string;
	chunks: KnowledgeChunk[];
};

/** 知识库文件列表（只读代理，需登录）。503 为知识库暂不可用。 */
export async function getKnowledgeFiles(token: string): Promise<KnowledgeFileList> {
	const res = await fetch(`${BASE}/files`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (res.status === 503 || !res.ok) throw new Error('知识库暂时无法加载');
	return res.json();
}

/** 单文件分块列表（只读代理，需登录）。404 为文件不存在。 */
export async function getFileChunks(
	token: string,
	fileId: string
): Promise<KnowledgeFileChunks> {
	const res = await fetch(`${BASE}/files/${encodeURIComponent(fileId)}/chunks`, {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('文件分块加载失败');
	return res.json();
}
