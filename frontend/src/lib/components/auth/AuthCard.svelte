<script lang="ts">
	import type { Snippet } from 'svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';

	let {
		title,
		subtitle,
		error,
		children
	}: {
		title: string;
		subtitle?: string;
		error?: string | null;
		children: Snippet;
	} = $props();
</script>

<div class="mx-auto flex max-w-sm flex-col gap-4 py-16">
	<h1 class="text-center text-2xl font-semibold text-gray-900 dark:text-white">romgi</h1>
	<div class="text-center">
		<h2 class="text-lg font-medium text-gray-900 dark:text-white">{title}</h2>
		{#if subtitle}
			<p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{subtitle}</p>
		{/if}
	</div>

	{#if error}
		<ErrorView message={error} />
	{/if}

	{@render children()}
</div>
