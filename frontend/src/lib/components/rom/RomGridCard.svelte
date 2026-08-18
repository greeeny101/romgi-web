<script lang="ts">
	import { GridPlusSolid } from 'flowbite-svelte-icons';
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
	class="group flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm transition hover:shadow-md dark:border-gray-700 dark:bg-gray-800"
>
	<div class="relative flex aspect-[3/4] items-center justify-center overflow-hidden bg-gray-100 dark:bg-gray-900">
		<div class="absolute top-2 right-2 z-10 flex items-center gap-1">
			<DownloadedBadge slug={entry.slug} platformId={entry.platform_id} />
			<FavoriteButton slug={entry.slug} />
		</div>
		{#if entry.boxart_url && !imageFailed}
			<img
				src={entry.boxart_url}
				alt={entry.title}
				loading="lazy"
				class="h-full w-full object-cover transition duration-200 group-hover:scale-105"
				onerror={() => (imageFailed = true)}
			/>
		{:else}
			<GridPlusSolid class="h-10 w-10 text-gray-300 dark:text-gray-600" />
		{/if}
	</div>
	<div class="flex flex-1 flex-col gap-2 p-3">
		<p class="line-clamp-2 text-sm font-medium text-gray-900 dark:text-white" title={entry.title}>
			{entry.title}
		</p>
		<div class="mt-auto flex items-center justify-between gap-2">
			<PlatformBadge name={platformName} brand={platformBrand} />
			{#if entry.ra_game_id}
				<span
					class="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-900 dark:text-amber-200"
					title="Has RetroAchievements support"
				>
					RA
				</span>
			{/if}
		</div>
	</div>
</a>
