<script lang="ts">
	import { onMount } from 'svelte';
	import { getKnowledgeFiles, type KnowledgeFile } from '$lib/apis/knowledge';
	import { APP_NAME, TOKEN_STORAGE_KEY } from '$lib/constants';

	let files = $state<KnowledgeFile[]>([]);
	let loading = $state(true);
	let error = $state(false);

	const STATUS_LABELS: Record<string, string> = {
		uploaded: '已上传',
		texted: '已提取',
		ocring: 'OCR中',
		spliting: '切分中',
		splited: '已切分',
		vectoring: '向量化中',
		vectored: '已入库',
		failed: '处理失败'
	};

	const statusLabel = (status: string): string => STATUS_LABELS[status] ?? status;

	const load = async (): Promise<void> => {
		loading = true;
		error = false;
		const token = localStorage.getItem(TOKEN_STORAGE_KEY);
		if (!token) return;
		try {
			const data = await getKnowledgeFiles(token);
			files = data.files;
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	};

	onMount(() => void load());
</script>

<svelte:head>
	<title>知识库 - {APP_NAME}</title>
</svelte:head>

<div class="mx-auto max-w-4xl px-6 py-6">
	<h1 class="mb-4 text-lg font-bold text-gray-900">知识库</h1>

	{#if loading}
		<div class="py-16 text-center text-sm text-gray-400">正在加载知识库…</div>
	{:else if error}
		<div class="rounded-lg border border-red-200 bg-red-50 px-4 py-8 text-center">
			<p class="mb-3 text-sm text-red-700">知识库暂时无法加载</p>
			<button
				class="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
				onclick={() => void load()}
			>
				重试
			</button>
		</div>
	{:else if files.length === 0}
		<div class="py-16 text-center text-sm text-gray-400">知识库暂无文件</div>
	{:else}
		<div class="overflow-hidden rounded-lg border border-gray-200">
			<table class="w-full text-left text-sm">
				<thead class="border-b border-gray-200 bg-gray-50 text-xs text-gray-500">
					<tr>
						<th class="px-4 py-2 font-medium">文件</th>
						<th class="w-28 px-4 py-2 font-medium">状态</th>
						<th class="w-20 px-4 py-2 text-right font-medium">块数</th>
					</tr>
				</thead>
				<tbody>
					{#each files as file (file.file_id)}
						<tr
							class="cursor-pointer border-b border-gray-100 last:border-b-0 hover:bg-gray-50"
							onclick={() => (location.href = `/knowledge/${file.file_id}`)}
						>
							<td class="px-4 py-3">
								<div class="text-gray-900">{file.name}</div>
								{#if file.source_path}
									<div class="mt-0.5 truncate text-xs text-gray-400">{file.source_path}</div>
								{/if}
							</td>
							<td class="px-4 py-3">
								<span
									class="inline-block rounded-full px-2 py-0.5 text-xs {file.status === 'vectored'
										? 'bg-green-50 text-green-700'
										: file.status === 'failed'
											? 'bg-red-50 text-red-700'
											: 'bg-gray-100 text-gray-600'}"
								>
									{statusLabel(file.status)}
								</span>
							</td>
							<td class="px-4 py-3 text-right text-gray-600">
								{file.chunk_count ?? '-'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
