<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import favicon from '$lib/assets/favicon.svg';
	import { auth } from '$lib/stores/auth';
	import { currentUser, session } from '$lib/stores/session';

	let { children } = $props();

	let ready = $state(false);

	onMount(async () => {
		await session.restore();
		ready = true;
	});

	$effect(() => {
		if (!ready) return;
		const isLoginPage = page.url.pathname === '/login';
		if (!$auth && !isLoginPage) {
			goto('/login');
		}
	});

	async function handleLogout() {
		await session.logout();
		await goto('/login');
	}
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="min-h-screen bg-gray-50 dark:bg-gray-900">
	<header class="border-b border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
		<div class="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
			<a href="/" class="text-lg font-semibold text-gray-900 dark:text-white">romgi</a>
			{#if $auth}
				<nav class="flex items-center gap-4 text-sm font-medium text-gray-500 dark:text-gray-400">
					<a href="/" class="text-primary-600 dark:text-primary-400">Browse</a>
					<a href="/downloads">Downloads</a>
					<a href="/library">Library</a>
					<a href="/sources">Sources</a>
					<a href="/settings">Settings</a>
					{#if $currentUser}
						<span class="text-xs text-gray-400">{$currentUser.email}</span>
					{/if}
					<button type="button" class="hover:text-gray-900 dark:hover:text-white" onclick={handleLogout}>
						Log out
					</button>
				</nav>
			{/if}
		</div>
	</header>

	<main class="mx-auto max-w-6xl px-4 py-6">
		{#if ready}
			{@render children()}
		{/if}
	</main>
</div>
