<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	import { PauseOutline, PlayOutline, TrashBinOutline } from 'flowbite-svelte-icons';
	import type { RomSetDownload } from '$lib/api/romsets';
	import { formatBytes } from '$lib/format';
	import { romsets } from '$lib/stores/romsets';

	let { romset }: { romset: RomSetDownload } = $props();

	let busy = $state(false);

	// Mirrors downloads/statusColor.ts. Not shared with it: the two state
	// machines only look alike — a set has fetching_metadata and no
	// converting — and collapsing them would couple two unrelated lifecycles.
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
			console.error('ROM set action failed', err);
		} finally {
			busy = false;
		}
	}

	const percent = $derived(Math.round(romset.progress * 100));
	const label = $derived(romset.status.replace('_', ' '));
</script>

<div class="flex flex-col gap-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div class="flex min-w-0 flex-col">
			<span class="truncate font-medium text-gray-900 dark:text-white">{romset.title}</span>
			<span class="truncate font-mono text-xs text-gray-500 dark:text-gray-400">
				{romset.save_dir || romset.identifier}
			</span>
		</div>
		<div class="flex items-center gap-2">
			<Badge color={statusColor[romset.status] ?? 'gray'}>{label}</Badge>
			{#if romset.status === 'downloading'}
				<button
					type="button"
					class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
					title="Pause"
					disabled={busy}
					onclick={() => act(() => romsets.pause(romset.id))}
				>
					<PauseOutline class="h-4 w-4" />
				</button>
			{:else if romset.status === 'paused'}
				<button
					type="button"
					class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
					title="Resume"
					disabled={busy}
					onclick={() => act(() => romsets.resume(romset.id))}
				>
					<PlayOutline class="h-4 w-4" />
				</button>
			{/if}
			<button
				type="button"
				class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-700"
				title="Remove from the queue (files already downloaded are kept)"
				disabled={busy}
				onclick={() => act(() => romsets.cancel(romset.id))}
			>
				<TrashBinOutline class="h-4 w-4" />
			</button>
		</div>
	</div>

	{#if romset.status !== 'completed' && romset.status !== 'failed'}
		<div class="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
			<div class="h-2 rounded-full bg-primary-600 transition-all" style="width: {percent}%"></div>
		</div>
	{/if}

	<div class="flex flex-wrap gap-x-3 text-xs text-gray-600 dark:text-gray-400">
		<span>{formatBytes(romset.downloaded_bytes)} of {formatBytes(romset.total_bytes)}</span>
		<span>{percent}%</span>
		{#if romset.bytes_per_second > 0}
			<span>{formatBytes(romset.bytes_per_second)}/s</span>
		{/if}
		<span>{romset.wanted_count} of {romset.file_count} files</span>
		{#if romset.extract}<span>extract after download</span>{/if}
	</div>

	{#if romset.error}
		<p class="text-xs text-red-600 dark:text-red-400">{romset.error}</p>
	{/if}
</div>
