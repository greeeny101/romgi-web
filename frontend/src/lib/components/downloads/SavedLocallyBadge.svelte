<script lang="ts">
	import { FloppyDiskSolid } from 'flowbite-svelte-icons';
	import { formatDateTime } from '$lib/format';

	// Deliberately a different colour and icon from DownloadedBadge: the two
	// answer different questions. Green "Downloaded" means the server fetched
	// the ROM from the source; blue "Saved" means the bytes reached *this*
	// user's machine. A row can sit at the first for days without the second.
	let { savedAt }: { savedAt: string | null } = $props();

	let stamp = $derived(savedAt ? formatDateTime(savedAt) : null);
</script>

{#if stamp}
	<span
		class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 dark:border-blue-900 dark:bg-blue-900/30 dark:text-blue-300"
		title="You saved this file on {stamp}"
	>
		<FloppyDiskSolid class="h-3.5 w-3.5" />
		Saved
		<span class="font-normal text-blue-600 dark:text-blue-400">{stamp}</span>
	</span>
{:else}
	<!-- Absence of a badge is ambiguous — "not saved yet" has to be said out
	     loud, since not knowing is the whole problem this solves. -->
	<span
		class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-400 dark:border-gray-600 dark:text-gray-500"
		title="You haven't saved this file to your machine yet"
	>
		Not saved yet
	</span>
{/if}
