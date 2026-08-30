<script lang="ts">
	import Chat from '$lib/components/chat/Chat.svelte';
	import { APP_NAME } from '$lib/constants';
</script>

<svelte:head>
	<title>{APP_NAME}</title>
</svelte:head>

<Chat chatId={null} />
