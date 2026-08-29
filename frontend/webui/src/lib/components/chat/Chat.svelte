<script lang="ts">
	import { untrack } from 'svelte';
	import { loadChat, sendMessage, session } from '$lib/stores/chat.svelte';
	import MessageList from './MessageList.svelte';
	import MessageInput from './MessageInput.svelte';

	let { chatId = null }: { chatId?: string | null } = $props();

	// chatId 变化（含挂载）时载入历史；生成中重挂载则沿用会话单例。
	// untrack：loadChat 对 session 的读写不注册为本 effect 的依赖，
	// 否则 reset 引起的状态变更会反复重触发本 effect。
	$effect(() => {
		const id = chatId ?? null;
		untrack(() => void loadChat(id));
	});
</script>

<div class="mx-auto flex h-full max-w-3xl flex-col px-4">
	{#if session.errorMessage}
		<div
			class="mt-4 flex items-start justify-between gap-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
		>
			<span>{session.errorMessage}</span>
			<button
				class="shrink-0 text-red-400 hover:text-red-600"
				aria-label="关闭错误提示"
				onclick={() => (session.errorMessage = '')}
			>
				✕
			</button>
		</div>
	{/if}

	{#if session.loadingHistory}
		<div class="flex flex-1 items-center justify-center text-sm text-gray-400">
			正在载入会话…
		</div>
	{:else}
		<MessageList messages={session.messages} generating={session.generating} />
	{/if}

	{#if session.statusText && session.generating}
		<div class="pb-2 text-xs text-gray-400">
			<span class="mr-1 inline-block animate-pulse">●</span>{session.statusText}
		</div>
	{/if}

	<div class="pb-4">
		<MessageInput disabled={session.generating} onsend={(content) => void sendMessage(content)} />
	</div>
</div>
