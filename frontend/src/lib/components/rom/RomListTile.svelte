<script lang="ts">
	import { ImageOutline } from 'flowbite-svelte-icons';
	import type { EntrySummary } from '$lib/api/catalog';
	import PlatformBadge from '$lib/components/platform/PlatformBadge.svelte';
	import FavoriteButton from '$lib/components/favorites/FavoriteButton.svelte';
	import DownloadedBadge from '$lib/components/downloads/DownloadedBadge.svelte';

	let {
		entry,
		platformName,
		platformBrand,
		href
	}: {
		entry: EntrySummary;
		platformName: string;
		platformBrand?: string;
		href: string;
	} = $props();

	let imageFailed = $state(false);
</script>

<a
	{href}
	class="flex items-center gap-3 rounded-lg border border-gray-200 bg-white p-2 transition hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700"
>
	<div class="flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded bg-gray-100 dark:bg-gray-900">
		{#if entry.boxart_url && !imageFailed}
			<img
				src={entry.boxart_url}
				alt={entry.title}
				loading="lazy"
				class="h-full w-full object-cover"
				onerror={() => (imageFailed = true)}
			/>
		{:else}
			<ImageOutline class="h-6 w-6 text-gray-300 dark:text-gray-600" />
		{/if}
	</div>
	<div class="min-w-0 flex-1">
		<p class="truncate text-sm font-medium text-gray-900 dark:text-white" title={entry.title}>
			{entry.title}
		</p>
		<div class="mt-1 flex items-center gap-2">
			<PlatformBadge name={platformName} brand={platformBrand} />
			{#if entry.ra_game_id}
				<span
					class="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-900 dark:text-amber-200"
				>
					RA
				</span>
			{/if}
		</div>
	</div>
	<div class="flex shrink-0 items-center gap-1">
		<DownloadedBadge slug={entry.slug} platformId={entry.platform_id} />
		<FavoriteButton slug={entry.slug} />
	</div>
</a>
