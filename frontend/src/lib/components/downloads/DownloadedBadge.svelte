<script lang="ts">
	import { DownloadSolid } from 'flowbite-svelte-icons';
	import { downloads } from '$lib/stores/downloads';

	let {
		slug,
		platformId,
		size = 'sm'
	}: { slug: string; platformId: string; size?: 'sm' | 'md' } = $props();

	// The downloads store carries every task the user has, finished ones
	// included, and enqueue keeps exactly one per slug — so a completed
	// task here means this ROM is sitting on the downloads page ready to
	// save. Renders nothing at all otherwise.
	//
	// Slugs are built as `<title>-<platform>-<regions>` (create_slug in the
	// ingestion pipeline) and are unique per catalog build, so a different
	// platform or region release of the same game is a different slug and
	// never borrows this badge. platform_id is matched as well because a
	// DownloadTask outlives the build it was enqueued from — if a rebuild
	// ever changed how slugs are derived, a stale task shouldn't be able to
	// light up an unrelated entry.
	let isDownloaded = $derived(
		$downloads.some((t) => t.slug === slug && t.platform_id === platformId && t.status === 'completed')
	);
	let dimension = $derived(size === 'sm' ? 'h-4 w-4' : 'h-5 w-5');
</script>

{#if isDownloaded}
	<span
		class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
		title="Already downloaded"
		aria-label="Already downloaded"
	>
		<DownloadSolid class="{dimension} text-green-600 dark:text-green-400" />
	</span>
{/if}
