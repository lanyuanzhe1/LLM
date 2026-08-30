<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { getFileChunks, type KnowledgeChunk } from '$lib/apis/knowledge';
	import { APP_NAME, TOKEN_STORAGE_KEY } from '$lib/constants';

	let fileId = $derived(page.params.fileId ?? '');
	let name = $state('');
	let chunks = $state<KnowledgeChunk[]>([]);
	let loading = $state(true);
	let error = $state(false);
	let expanded = $state<Record<number, boolean>>({});

	const isExpanded = (index: number): boolean => expanded[index] ?? true;

	const toggle = (index: number): void => {
		expanded = { ...expanded, [index]: !isExpanded(index) };
	};

	const load = async (): Promise<void> => {
		loading = true;
		error = false;
		const token = localStorage.getItem(TOKEN_STORAGE_KEY);
		if (!token) return;
		try {
			const data = await getFileChunks(token, fileId);
			name = data.name;
			chunks = data.chunks;
			expanded = {};
		} catch {
			error = true;
		} finally {
			loading = false;
		}
	};

	onMount(() => void load());
</script>

<svelte:head>
	<title>{name || '知识库分块'} - {APP_NAME}</title>
</svelte:head>

<div class="mx-auto max-w-3xl px-6 py-6">
	<a href="/knowledge" class="text-sm text-gray-500 hover:text-gray-800">← 返回知识库</a>
	<h1 class="mb-1 mt-3 text-lg font-bold text-gray-900">{name || '文件分块'}</h1>
	{#if chunks.length > 0}
		<p class="mb-4 text-xs text-gray-400">共 {chunks.length} 个分块</p>
	{/if}

	{#if loading}
		<div class="py-16 text-center text-sm text-gray-400">正在加载分块…</div>
	{:else if error}
		<div class="rounded-lg border border-red-200 bg-red-50 px-4 py-8 text-center">
			<p class="mb-3 text-sm text-red-700">文件分块加载失败</p>
			<button
				class="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-700 hover:bg-gray-100"
				onclick={() => void load()}
			>
				重试
			</button>
		</div>
	{:else if chunks.length === 0}
		<div class="py-16 text-center text-sm text-gray-400">该文件暂无分块</div>
	{:else}
		<div class="space-y-2">
			{#each chunks as chunk (chunk.index)}
				<div class="overflow-hidden rounded-lg border border-gray-200">
					<button
						class="flex w-full items-center justify-between bg-gray-50 px-4 py-2.5 text-left text-sm font-medium text-gray-800 hover:bg-gray-100"
						onclick={() => toggle(chunk.index)}
					>
						<span>分块 #{chunk.index}</span>
						<span class="text-xs text-gray-400">{isExpanded(chunk.index) ? '收起' : '展开'}</span>
					</button>
					{#if isExpanded(chunk.index)}
						<div class="whitespace-pre-wrap break-words bg-white px-4 py-3 text-sm leading-relaxed text-gray-700">
							{chunk.text}
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
