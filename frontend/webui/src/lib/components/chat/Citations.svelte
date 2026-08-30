<script lang="ts">
	import type { SourceItem } from '$lib/stores/chat.svelte';

	let { sources = [] }: { sources?: SourceItem[] } = $props();
</script>

{#if sources.length > 0}
	<div class="mt-3 border-t border-gray-100 pt-2">
		<div class="mb-1.5 text-xs font-medium text-gray-500">参考来源</div>
		<div class="flex flex-col gap-1.5">
			{#each sources as source (source.name + source.excerpt)}
				<div class="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
					<div class="text-xs font-medium text-gray-700">{source.name}</div>
					{#if source.excerpt}
						<div class="mt-0.5 line-clamp-2 text-xs text-gray-500">{source.excerpt}</div>
					{/if}
				</div>
			{/each}
		</div>
	</div>
{/if}
