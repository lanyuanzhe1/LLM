<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { getSessionUser } from '$lib/apis/auths';
	import { user } from '$lib/stores';
	import { APP_NAME } from '$lib/constants';

	let { children } = $props();

	let loaded = false;

	onMount(async () => {
		const token = localStorage.getItem('token');
		if (!token) {
			goto('/auth');
			return;
		}
		try {
			const sessionUser = await getSessionUser(token);
			user.set(sessionUser);
			loaded = true;
		} catch {
			localStorage.removeItem('token');
			goto('/auth');
		}
	});

	const signOut = () => {
		localStorage.removeItem('token');
		user.set(null);
		goto('/auth');
	};

	const navItems = [
		{ href: '/', label: '对话' },
		{ href: '/knowledge', label: '知识库' },
		{ href: '/agents', label: '智能体广场' },
		{ href: '/settings', label: '设置' }
	];
</script>

{#if loaded}
	<div class="flex h-screen">
		<aside class="flex w-56 shrink-0 flex-col border-r border-gray-200 bg-gray-50">
			<div class="px-4 py-4 text-base font-bold text-gray-900">{APP_NAME}</div>
			<nav class="flex-1 px-2">
				{#each navItems as item}
					<a
						href={item.href}
						class="mb-1 block rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-200"
					>
						{item.label}
					</a>
				{/each}
			</nav>
			<div class="border-t border-gray-200 p-3">
				<div class="mb-2 truncate px-1 text-sm text-gray-600">{$user?.name ?? $user?.email ?? ''}</div>
				<button
					class="w-full rounded-lg border border-gray-300 py-1.5 text-sm text-gray-700 hover:bg-gray-200"
					on:click={signOut}
				>
					退出登录
				</button>
			</div>
		</aside>
		<main class="min-w-0 flex-1 overflow-y-auto">
			{@render children()}
		</main>
	</div>
{:else}
	<div class="flex h-screen items-center justify-center text-sm text-gray-400">加载中…</div>
{/if}
