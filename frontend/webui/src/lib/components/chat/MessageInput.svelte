<script lang="ts">
	let {
		disabled = false,
		onsend
	}: { disabled?: boolean; onsend: (content: string) => void } = $props();

	let value = $state('');

	const submit = () => {
		const content = value.trim();
		if (!content || disabled) return;
		onsend(content);
		value = '';
	};

	const onkeydown = (event: KeyboardEvent) => {
		// 中文输入法组词期间的 Enter 是选词，不能触发发送
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
			event.preventDefault();
			submit();
		}
	};
</script>

<div class="flex items-end gap-2 rounded-2xl border border-gray-300 bg-white px-3 py-2">
	<textarea
		bind:value
		{onkeydown}
		{disabled}
		rows="1"
		class="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm outline-none placeholder:text-gray-400 disabled:opacity-60"
		placeholder={disabled ? '正在生成回答…' : '请输入问题，Enter 发送，Shift+Enter 换行'}
	></textarea>
	<button
		class="shrink-0 rounded-xl bg-gray-900 px-4 py-1.5 text-sm font-medium text-white hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40"
		onclick={submit}
		disabled={disabled || !value.trim()}
	>
		发送
	</button>
</div>
