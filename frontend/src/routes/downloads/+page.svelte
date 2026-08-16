<script lang="ts">
	import { onMount } from 'svelte';
	import { Spinner } from 'flowbite-svelte';
	import { downloads } from '$lib/stores/downloads';
	import DownloadQueueRow from '$lib/components/downloads/DownloadQueueRow.svelte';

	let loading = $state(true);

	onMount(async () => {
		await downloads.load();
		loading = false;
	});
</script>

<svelte:head>
	<title>Downloads — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Downloads</h1>

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if $downloads.length === 0}
		<p class="text-sm text-gray-500 dark:text-gray-400">No downloads yet. Start one from an entry's page.</p>
	{:else}
		<div class="flex flex-col gap-3">
			{#each $downloads as task (task.id)}
				<DownloadQueueRow {task} />
			{/each}
		</div>
	{/if}
</div>
