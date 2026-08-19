<script lang="ts">
	import { page } from '$app/state';
	import { Spinner, Badge } from 'flowbite-svelte';
	import { ImageOutline, DownloadOutline } from 'flowbite-svelte-icons';
	import { catalogApi, type EntryDetail, type Link as CatalogLink, type Platform } from '$lib/api/catalog';
	import { libraryApi } from '$lib/api/library';
	import { downloads } from '$lib/stores/downloads';
	import { browseState } from '$lib/stores/browseState';
	import { metadataApi, type GameMetadata } from '$lib/api/metadata';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import PlatformBadge from '$lib/components/platform/PlatformBadge.svelte';
	import RegionFlags from '$lib/components/region/RegionFlags.svelte';
	import FavoriteButton from '$lib/components/favorites/FavoriteButton.svelte';
	import MetadataCard from '$lib/components/metadata/MetadataCard.svelte';
	import DownloadQueueRow from '$lib/components/downloads/DownloadQueueRow.svelte';

	let slug = $derived(page.params.slug ?? '');

	let entry = $state<EntryDetail | null>(null);
	let links = $state<CatalogLink[]>([]);
	let platforms = $state<Platform[]>([]);
	let metadata = $state<GameMetadata | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let enqueuingLinkId = $state<number | null>(null);

	// The store holds every task, whatever its status, so this is the same
	// row the downloads page shows — including finished and failed ones.
	let queuedTask = $derived($downloads.find((t) => t.slug === entry?.slug) ?? null);

	async function enqueueLink(link: CatalogLink) {
		if (!entry) return;
		enqueuingLinkId = link.id;
		try {
			// Replaces queuedTask server-side rather than queuing a second
			// copy of this title — see downloads.api._discard_existing.
			await downloads.enqueue({ slug: entry.slug, link_id: link.id });
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to start download.';
		} finally {
			enqueuingLinkId = null;
		}
	}

	async function load() {
		loading = true;
		error = null;
		try {
			const [entryResult, linksResult, platformsResult] = await Promise.all([
				catalogApi.entry(slug),
				catalogApi.entryLinks(slug),
				catalogApi.platforms()
			]);
			entry = entryResult;
			links = linksResult;
			platforms = platformsResult;
			libraryApi.recordRecentlyViewed(slug).catch(() => {});
			// Eager but non-blocking, and silent on failure — mirrors the
			// original app's metadata card just not appearing rather than
			// showing a spinner/error state.
			metadata = null;
			metadataApi
				.entry(slug)
				.then((result) => (metadata = result))
				.catch(() => {});
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load this entry.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void slug;
		load();
	});

	// Browse restores its filters from the query string it last recorded, and
	// scrolls this entry back into view.
	let browseHref = $derived($browseState.search ? `/${$browseState.search}` : '/');

	$effect(() => {
		if (slug) browseState.rememberFocus(slug);
	});

	let platformName = $derived(platforms.find((p) => p.id === entry?.platform_id)?.name ?? entry?.platform_id);
	let platformBrand = $derived(platforms.find((p) => p.id === entry?.platform_id)?.brand);
</script>

<svelte:head>
	<title>{entry?.title ?? 'Loading…'} — romgi</title>
</svelte:head>

<a
	href={browseHref}
	class="mb-4 inline-block text-sm text-primary-600 hover:underline dark:text-primary-400"
	>&larr; Back to Browse</a
>

{#if loading}
	<div class="flex justify-center py-16"><Spinner size="8" /></div>
{:else if error}
	<ErrorView message={error} onRetry={load} />
{:else if entry}
	<div class="flex flex-col gap-6 sm:flex-row">
		<div class="flex aspect-[3/4] w-full max-w-xs shrink-0 items-center justify-center overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-800">
			{#if entry.boxart_url}
				<img src={entry.boxart_url} alt={entry.title} class="h-full w-full object-cover" />
			{:else}
				<ImageOutline class="h-16 w-16 text-gray-300 dark:text-gray-600" />
			{/if}
		</div>

		<div class="flex min-w-0 flex-1 flex-col gap-3">
			<h1 class="text-2xl font-semibold break-words text-gray-900 dark:text-white">{entry.title}</h1>
			<div class="flex flex-wrap items-center gap-2">
				<FavoriteButton slug={entry.slug} size="md" />
				{#if platformName}
					<PlatformBadge name={platformName} brand={platformBrand} />
				{/if}
				{#each entry.regions as region (region)}
					<Badge color="gray" class="items-center gap-1">
						<RegionFlags regions={[region]} size="h-3.5 w-3.5" />
						{region.toUpperCase()}
					</Badge>
				{/each}
				{#if entry.ra_game_id}
					<Badge color="yellow">
						RetroAchievements{entry.ra_num_achievements ? ` · ${entry.ra_num_achievements}` : ''}
					</Badge>
				{/if}
			</div>

			{#if metadata && (metadata.description || metadata.screenshots.length || metadata.artwork.length)}
				<MetadataCard {metadata} />
			{/if}

			{#if queuedTask}
				<h2 class="mt-4 text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">
					Download status
				</h2>
				<DownloadQueueRow task={queuedTask} />
				<p class="text-xs text-gray-500 dark:text-gray-400">
					Shown on your <a href="/downloads" class="text-primary-600 hover:underline dark:text-primary-400"
						>downloads page</a
					>. Starting another link below replaces this download.
				</p>
			{/if}

			<h2 class="mt-4 text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">
				Download links
			</h2>
			{#if links.length === 0}
				<p class="text-sm text-gray-500 dark:text-gray-400">No links found for this entry.</p>
			{:else}
				<ul class="flex flex-col gap-2">
					{#each links as link (link.id)}
						<li
							class="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700"
						>
							<div class="min-w-0">
								<p class="truncate font-medium text-gray-900 dark:text-white">{link.name}</p>
								<p class="text-xs text-gray-500 dark:text-gray-400">
									{link.host}
									{#if link.size_str} · {link.size_str}{/if}
									{#if link.is_torrent} · torrent{/if}
									{#if link.requires_auth} · login required{/if}
								</p>
							</div>
							<button
								type="button"
								class="flex shrink-0 items-center gap-1 rounded bg-primary-600 px-2 py-1 text-xs text-white hover:bg-primary-700 disabled:opacity-50"
								disabled={enqueuingLinkId !== null}
								onclick={() => enqueueLink(link)}
							>
								<DownloadOutline class="h-3.5 w-3.5" />
								{enqueuingLinkId === link.id
									? 'Starting…'
									: queuedTask
										? 'Replace'
										: 'Download'}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</div>
{/if}
