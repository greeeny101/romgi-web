<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	import {
		PauseOutline,
		PlayOutline,
		RefreshOutline,
		TrashBinOutline,
		FileZipSolid
	} from 'flowbite-svelte-icons';
	import { downloadsApi, type DownloadTask } from '$lib/api/downloads';
	import { downloads } from '$lib/stores/downloads';
	import PlatformBadge from '$lib/components/platform/PlatformBadge.svelte';
	import RegionFlags from '$lib/components/region/RegionFlags.svelte';
	import { statusColor } from './statusColor';

	let { task }: { task: DownloadTask } = $props();

	let saving = $state(false);

	async function saveFile() {
		if (saving) return;
		saving = true;
		try {
			const { blob, filename } = await downloadsApi.file(task.id);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = filename ?? task.title;
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		} catch (err) {
			console.error('Failed to download file', err);
		} finally {
			saving = false;
		}
	}

	function formatBytes(n: number): string {
		if (!n) return '0 B';
		const units = ['B', 'KB', 'MB', 'GB'];
		let value = n;
		let i = 0;
		while (value >= 1024 && i < units.length - 1) {
			value /= 1024;
			i++;
		}
		return `${value.toFixed(1)} ${units[i]}`;
	}
</script>

<div class="flex flex-col gap-2 rounded-lg border border-gray-200 p-3 dark:border-gray-700">
	<div class="flex items-center justify-between gap-2">
		<div class="min-w-0">
			<p class="truncate font-medium text-gray-900 dark:text-white">{task.title}</p>
			<div class="mt-1 -ml-2.5 flex flex-wrap items-center gap-1.5">
				<PlatformBadge name={task.platform_name} />
				<RegionFlags regions={task.region_ids} />
				<Badge color="indigo" class="whitespace-nowrap">
					{task.source_name ?? task.link_host}{#if task.link_is_torrent} &nbsp;· torrent{/if}
				</Badge>
			</div>
			<p class="mt-1 truncate text-xs text-gray-500 dark:text-gray-400">
				{task.link_name}
				{#if task.total_bytes}
					· {formatBytes(task.downloaded_bytes)} / {formatBytes(task.total_bytes)}
				{/if}
				{#if task.status === 'downloading' && task.bytes_per_second}
					 · {formatBytes(task.bytes_per_second)}/s
				{/if}
				{#if task.link_is_torrent && task.status === 'downloading' && task.num_seeds != null}
					&nbsp;· {task.num_seeds} seeds · {task.num_peers} peers
				{/if}
			</p>
		</div>
		<Badge color={statusColor[task.status]}>{task.status}</Badge>
	</div>

	{#if task.status === 'downloading' || task.status === 'extracting'}
		<div class="h-2 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
			<div
				class="h-2 rounded-full bg-primary-600 transition-all"
				style="width: {Math.round(task.progress * 100)}%"
			></div>
		</div>
	{/if}

	{#if task.status === 'failed' && task.error}
		<p class="text-xs text-red-600 dark:text-red-400">{task.error}</p>
	{/if}

	<div class="flex items-center gap-3">
		{#if task.status === 'downloading' || task.status === 'pending'}
			<button
				type="button"
				class="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white"
				onclick={() => downloads.pause(task.id)}
			>
				<PauseOutline class="h-4 w-4" /> Pause
			</button>
		{/if}
		{#if task.status === 'paused'}
			<button
				type="button"
				class="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white"
				onclick={() => downloads.resume(task.id)}
			>
				<PlayOutline class="h-4 w-4" /> Resume
			</button>
		{/if}
		{#if task.status === 'failed'}
			<button
				type="button"
				class="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-white"
				onclick={() => downloads.retry(task.id)}
			>
				<RefreshOutline class="h-4 w-4" /> Retry
			</button>
		{/if}
		{#if task.status === 'completed'}
			<button
				type="button"
				class="flex items-center gap-1 text-xs text-primary-600 hover:underline disabled:opacity-50 dark:text-primary-400"
				disabled={saving}
				onclick={saveFile}
			>
				<FileZipSolid class="h-4 w-4" /> {saving ? 'Saving…' : 'Save file'}
			</button>
		{/if}
		<button
			type="button"
			class="ml-auto flex items-center gap-1 text-xs text-gray-400 hover:text-red-600"
			onclick={() => downloads.cancel(task.id)}
		>
			<TrashBinOutline class="h-4 w-4" />
		</button>
	</div>
</div>
