<script lang="ts">
	import { GridPlusSolid } from 'flowbite-svelte-icons';
	import type { EntrySummary } from '$lib/api/catalog';
	import PlatformBadge from '$lib/components/platform/PlatformBadge.svelte';
	import RegionFlags from '$lib/components/region/RegionFlags.svelte';
	import FavoriteButton from '$lib/components/favorites/FavoriteButton.svelte';
	import DownloadedBadge from '$lib/components/downloads/DownloadedBadge.svelte';

	let {
		entry,
		platformName,
		platformBrand,
		href,
		id,
		highlighted = false
	}: {
		entry: EntrySummary;
		platformName: string;
		platformBrand?: string;
		href: string;
		id?: string;
		highlighted?: boolean;
	} = $props();

	let imageFailed = $state(false);
</script>

<a
	{href}
	{id}
	class="group flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm transition hover:shadow-md dark:border-gray-700 dark:bg-gray-800"
	class:ring-2={highlighted}
	class:ring-primary-500={highlighted}
>
	<div class="relative flex aspect-[3/4] items-center justify-center overflow-hidden bg-gray-100 dark:bg-gray-900">
		<div class="absolute top-2 right-2 z-10 flex items-center gap-1">
			<DownloadedBadge slug={entry.slug} platformId={entry.platform_id} />
			<FavoriteButton slug={entry.slug} />
		</div>
		{#if entry.boxart_url && !imageFailed}
			<!-- Box art comes in mixed ratios (libretro Named_Boxarts, GameTDB covers), so the
			     cover is contained rather than cropped. A blurred copy of the same image fills
			     the leftover space; it reuses the cached URL, so there's no extra request.
			     scale-110 hides the feathered edge the blur leaves at the image boundary. -->
			<img
				src={entry.boxart_url}
				alt=""
				aria-hidden="true"
				loading="lazy"
				class="pointer-events-none absolute inset-0 h-full w-full scale-110 object-cover blur-xl brightness-75 dark:brightness-50"
			/>
			<!-- p-1 gives group-hover:scale-105 room to grow into: object-contain leaves the art
			     flush with the box on its constrained axis, so without the inset the zoom clips it. -->
			<img
				src={entry.boxart_url}
				alt={entry.title}
				loading="lazy"
				class="relative h-full w-full object-contain p-1 transition duration-200 group-hover:scale-105"
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
			<!-- Clipped here rather than at the card edge: platform names run long
			     ("Super Nintendo Entertainment System") and the badge is whitespace-nowrap,
			     so without this the overflow pushes the RA pill off the card. -->
			<div class="flex min-w-0 items-center gap-1.5 overflow-hidden">
				<PlatformBadge name={platformName} brand={platformBrand} />
				<RegionFlags regions={entry.regions} />
			</div>
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
