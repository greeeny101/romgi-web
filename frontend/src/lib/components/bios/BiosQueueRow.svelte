<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	import { PauseOutline, PlayOutline, TrashBinOutline } from 'flowbite-svelte-icons';
	import type { BiosDownload } from '$lib/api/bios';
	import { formatBytes } from '$lib/format';
	import { bios as biosStore } from '$lib/stores/bios';

	let { bios }: { bios: BiosDownload } = $props();

	let busy = $state(false);

	// Mirrors romsets/RomSetQueueRow.svelte, which in turn mirrors
	// downloads/statusColor.ts. Deliberately still not shared: the three
	// lifecycles only look alike, and a BIOS request pauses by having its
	// worker notice a column change rather than by stopping a torrent.
	const statusColor: Record<string, 'gray' | 'blue' | 'yellow' | 'purple' | 'green' | 'red'> = {
		pending: 'gray',
		fetching_metadata: 'gray',
		downloading: 'blue',
		paused: 'yellow',
		extracting: 'purple',
		completed: 'green',
		failed: 'red'
	};

	async function act(fn: () => Promise<unknown>) {
		if (busy) return;
		busy = true;
		try {
			await fn();
		} catch (err) {
			console.error('BIOS action failed', err);
		} finally {
			busy = false;
		}
	}

	const percent = $derived(Math.round(bios.progress * 100));
	const label = $derived(bios.status.replace('_', ' '));
</script>

<div class="flex flex-col gap-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex min-w-0 flex-col">
			<span class="truncate font-medium text-gray-900 dark:text-white">{bios.title}</span>
			<span class="truncate font-mono text-xs text-gray-500 dark:text-gray-400">
				{bios.save_dir || bios.identifier}
			</span>
		</div>
		<div class="flex items-center gap-2">
			<Badge color={statusColor[bios.status] ?? 'gray'}>{label}</Badge>
			{#if bios.status === 'downloading' || bios.status === 'pending'}
				<button
					type="button"
					class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
					title="Pause"
					disabled={busy}
					onclick={() => act(() => biosStore.pause(bios.id))}
				>
					<PauseOutline class="h-4 w-4" />
				</button>
			{:else if bios.status === 'paused'}
				<button
					type="button"
					class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
					title="Resume"
					disabled={busy}
					onclick={() => act(() => biosStore.resume(bios.id))}
				>
					<PlayOutline class="h-4 w-4" />
				</button>
			{/if}
			<button
				type="button"
				class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
				title="Remove from the queue (files already downloaded are kept)"
				disabled={busy}
				onclick={() => act(() => biosStore.cancel(bios.id))}
			>
				<TrashBinOutline class="h-4 w-4" />
			</button>
		</div>
	</div>

	{#if bios.status !== 'completed' && bios.status !== 'failed'}
		<div class="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
			<div class="h-2 rounded-full bg-primary-600 transition-all" style="width: {percent}%"></div>
		</div>
	{/if}

	<div class="flex flex-wrap gap-x-3 text-xs text-gray-600 dark:text-gray-400">
		<span>{formatBytes(bios.downloaded_bytes)} of {formatBytes(bios.total_bytes)}</span>
		<span>{percent}%</span>
		{#if bios.bytes_per_second > 0}
			<span>{formatBytes(bios.bytes_per_second)}/s</span>
		{/if}
		<span>{bios.wanted_count} of {bios.file_count} files</span>
		{#if bios.extract}<span>extract after download</span>{/if}
	</div>

	{#if bios.error}
		<p class="text-xs text-red-600 dark:text-red-400">{bios.error}</p>
	{/if}
</div>
