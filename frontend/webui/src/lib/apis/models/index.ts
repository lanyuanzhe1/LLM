export type ModelEntry = {
	id: string;
	object?: string;
	[key: string]: unknown;
};

export async function getModels(token: string): Promise<{ data: ModelEntry[] }> {
	const res = await fetch('/api/models', {
		headers: { Authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw new Error('获取模型列表失败');
	return res.json();
}
