<script lang="ts">
	import { goto } from '$app/navigation';
	import { signin, signup } from '$lib/apis/auths';
	import { user } from '$lib/stores';
	import { APP_NAME } from '$lib/constants';

	let mode: 'signin' | 'signup' = 'signin';

	let name = '';
	let email = '';
	let password = '';
	let confirmPassword = '';

	let submitting = false;
	let errorMessage = '';

	const submitHandler = async () => {
		if (submitting) return;
		errorMessage = '';

		if (!email.trim() || !password) {
			errorMessage = '请填写邮箱和密码';
			return;
		}
		if (mode === 'signup') {
			if (!name.trim()) {
				errorMessage = '请填写姓名';
				return;
			}
			if (password !== confirmPassword) {
				errorMessage = '两次输入的密码不一致';
				return;
			}
		}

		submitting = true;
		try {
			const sessionUser =
				mode === 'signin'
					? await signin(email.trim(), password)
					: await signup(name.trim(), email.trim(), password);

			if (sessionUser?.token) {
				localStorage.setItem('token', sessionUser.token);
				user.set(sessionUser);
				goto('/');
			} else {
				errorMessage = '服务响应异常，请稍后重试';
			}
		} catch (error) {
			errorMessage = `${error}`;
		} finally {
			submitting = false;
		}
	};
</script>

<svelte:head>
	<title>{APP_NAME} · {mode === 'signin' ? '登录' : '注册'}</title>
</svelte:head>

<div class="flex min-h-screen items-center justify-center bg-gray-50 px-4">
	<div class="w-full max-w-sm rounded-2xl bg-white p-8 shadow-sm">
		<h1 class="mb-1 text-center text-xl font-bold text-gray-900">{APP_NAME}</h1>
		<p class="mb-6 text-center text-sm text-gray-500">
			{mode === 'signin' ? '登录以继续使用' : '创建一个新账户'}
		</p>

		<form
			onsubmit={(event) => {
				event.preventDefault();
				void submitHandler();
			}}
			class="flex flex-col gap-4"
		>
			{#if mode === 'signup'}
				<div>
					<label class="mb-1 block text-sm text-gray-600" for="name">姓名</label>
					<input
						id="name"
						class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500"
						type="text"
						placeholder="请输入姓名"
						bind:value={name}
						required
					/>
				</div>
			{/if}

			<div>
				<label class="mb-1 block text-sm text-gray-600" for="email">邮箱</label>
				<input
					id="email"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500"
					type="email"
					placeholder="请输入邮箱"
					bind:value={email}
					required
				/>
			</div>

			<div>
				<label class="mb-1 block text-sm text-gray-600" for="password">密码</label>
				<input
					id="password"
					class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500"
					type="password"
					placeholder="请输入密码"
					bind:value={password}
					required
				/>
			</div>

			{#if mode === 'signup'}
				<div>
					<label class="mb-1 block text-sm text-gray-600" for="confirmPassword">确认密码</label>
					<input
						id="confirmPassword"
						class="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-gray-500"
						type="password"
						placeholder="请再次输入密码"
						bind:value={confirmPassword}
						required
					/>
				</div>
			{/if}

			{#if errorMessage}
				<div class="text-sm text-red-500">{errorMessage}</div>
			{/if}

			<button
				class="mt-2 w-full rounded-lg bg-gray-900 py-2 text-sm font-medium text-white hover:bg-gray-700 disabled:opacity-50"
				type="submit"
				disabled={submitting}
			>
				{submitting ? '请稍候…' : mode === 'signin' ? '登录' : '注册'}
			</button>
		</form>

		<div class="mt-4 text-center text-sm text-gray-500">
			{#if mode === 'signin'}
				还没有账户？
				<button class="font-medium text-gray-900 underline" onclick={() => (mode = 'signup')}>
					立即注册
				</button>
			{:else}
				已有账户？
				<button class="font-medium text-gray-900 underline" onclick={() => (mode = 'signin')}>
					去登录
				</button>
			{/if}
		</div>
	</div>
</div>
