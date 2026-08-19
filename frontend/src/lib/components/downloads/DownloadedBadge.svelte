<script lang="ts">
	import { DownloadSolid } from 'flowbite-svelte-icons';
	import { downloads } from '$lib/stores/downloads';
	import { formatDateTime } from '$lib/format';

	// Two ways in. Browse's cards have only a slug and look the task up in the
	// store; the Library's Downloaded rows already hold the task, so they pass
	// completedAt directly and skip a scan of every task the user has.
	let {
		slug,
		platformId,
		completedAt,
		size = 'sm',
		variant = 'icon'
	}: {
		slug?: string;
		platformId?: string;
		completedAt?: string | null;
		size?: 'sm' | 'md';
		variant?: 'icon' | 'pill';
	} = $props();

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
	let matched = $derived(
		slug
			? ($downloads.find(
					(t) => t.slug === slug && t.platform_id === platformId && t.status === 'completed'
				) ?? null)
			: null
	);

	let when = $derived(completedAt ?? matched?.completed_at ?? null);
	let isDownloaded = $derived(completedAt !== undefined ? Boolean(when) : matched !== null);
	let stamp = $derived(when ? formatDateTime(when) : null);
	let title = $derived(stamp ? `Downloaded ${stamp}` : 'Already downloaded');
	let dimension = $derived(size === 'sm' ? 'h-4 w-4' : 'h-5 w-5');
</script>

{#if isDownloaded}
	{#if variant === 'pill'}
		<span
			class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700 dark:border-green-900 dark:bg-green-900/30 dark:text-green-300"
			{title}
		>
			<DownloadSolid class="h-3.5 w-3.5" />
			Downloaded
			{#if stamp}
				<span class="font-normal text-green-600 dark:text-green-400">{stamp}</span>
			{/if}
		</span>
	{:else}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			{title}
			aria-label={title}
		>
			<DownloadSolid class="{dimension} text-green-600 dark:text-green-400" />
		</span>
	{/if}
{/if}
