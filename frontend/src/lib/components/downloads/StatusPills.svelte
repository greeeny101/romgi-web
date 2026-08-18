<script lang="ts">
	import { Button } from 'flowbite-svelte';
	import type { DownloadStatus } from '$lib/api/downloads';
	import { statusColor, statusOrder } from './statusColor';

	let {
		counts,
		total,
		value = $bindable<DownloadStatus | ''>('')
	}: {
		counts: Record<DownloadStatus, number>;
		total: number;
		value?: DownloadStatus | '';
	} = $props();

	// Clicking the selected pill goes back to All, so the filter can be undone
	// without reaching for "Clear filters".
	function toggle(status: DownloadStatus) {
		value = value === status ? '' : status;
	}
</script>

<div class="flex flex-wrap gap-1">
	<Button size="xs" color={value === '' ? 'primary' : 'alternative'} onclick={() => (value = '')}>
		All <span class="ml-1.5 opacity-70">{total}</span>
	</Button>
	{#each statusOrder as status (status)}
		<Button
			size="xs"
			color={value === status ? statusColor[status] : 'alternative'}
			disabled={counts[status] === 0 && value !== status}
			class={counts[status] === 0 ? 'opacity-50' : ''}
			onclick={() => toggle(status)}
		>
			{status} <span class="ml-1.5 opacity-70">{counts[status]}</span>
		</Button>
	{/each}
</div>
