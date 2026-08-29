<script lang="ts">
	import { page } from '$app/state';
	import Chat from '$lib/components/chat/Chat.svelte';
	import { APP_NAME } from '$lib/constants';
</script>

<svelte:head>
	<title>{APP_NAME} · 会话</title>
</svelte:head>

<Chat chatId={page.params.id ?? null} />
