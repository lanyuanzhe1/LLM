<script lang="ts">
	import { tick } from 'svelte';
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';
	import type { ChatMessage } from '$lib/stores/chat.svelte';
	import Citations from './Citations.svelte';

	let { messages, generating = false }: { messages: ChatMessage[]; generating?: boolean } =
		$props();

	let container = $state<HTMLDivElement | null>(null);

	const renderMarkdown = (content: string): string => {
		const html = marked.parse(content, { async: false });
		return DOMPurify.sanitize(html);
	};

	// 消息内容增长时滚到底部
	$effect(() => {
		const last = messages[messages.length - 1];
		void messages.length;
		void last?.content;
		void last?.sources?.length;
		void tick().then(() => {
			if (container) container.scrollTop = container.scrollHeight;
		});
	});
</script>

<div bind:this={container} class="flex-1 overflow-y-auto py-6">
	{#if messages.length === 0}
		<div class="flex h-full items-center justify-center">
			<div class="text-center">
				<p class="text-lg font-medium text-gray-700">有什么可以帮你的？</p>
				<p class="mt-1 text-sm text-gray-400">
					提问粮食储藏、虫害防治、低温储粮、气调监测等问题
				</p>
			</div>
		</div>
	{:else}
		<div class="flex flex-col gap-5">
			{#each messages as message (message.id)}
				{#if message.role === 'user'}
					<div class="flex justify-end">
						<div
							class="max-w-[85%] rounded-2xl rounded-br-sm bg-gray-900 px-4 py-2.5 text-sm whitespace-pre-wrap text-white"
						>
							{message.content}
						</div>
					</div>
				{:else}
					<div class="flex justify-start">
						<div class="w-full max-w-[92%]">
							{#if message.content}
								<div class="prose-chat text-sm leading-6 text-gray-800">
									{@html renderMarkdown(message.content)}
								</div>
							{:else if generating}
								<div class="text-sm text-gray-400">正在生成回答…</div>
							{/if}
							<Citations sources={message.sources} />
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{/if}
</div>

<style>
	.prose-chat :global(p) {
		margin: 0.5em 0;
	}
	.prose-chat :global(ul),
	.prose-chat :global(ol) {
		margin: 0.5em 0;
		padding-left: 1.5em;
	}
	.prose-chat :global(ul) {
		list-style: disc;
	}
	.prose-chat :global(ol) {
		list-style: decimal;
	}
	.prose-chat :global(h1),
	.prose-chat :global(h2),
	.prose-chat :global(h3),
	.prose-chat :global(h4) {
		margin: 0.8em 0 0.4em;
		font-weight: 600;
	}
	.prose-chat :global(code) {
		border-radius: 4px;
		background: #f3f4f6;
		padding: 0.1em 0.35em;
		font-size: 0.9em;
	}
	.prose-chat :global(pre) {
		overflow-x: auto;
		border-radius: 8px;
		background: #f3f4f6;
		padding: 0.75em 1em;
		margin: 0.5em 0;
	}
	.prose-chat :global(pre code) {
		background: transparent;
		padding: 0;
	}
	.prose-chat :global(blockquote) {
		border-left: 3px solid #d1d5db;
		padding-left: 0.75em;
		color: #4b5563;
		margin: 0.5em 0;
	}
	.prose-chat :global(table) {
		border-collapse: collapse;
		margin: 0.5em 0;
	}
	.prose-chat :global(th),
	.prose-chat :global(td) {
		border: 1px solid #e5e7eb;
		padding: 0.3em 0.6em;
	}
</style>
