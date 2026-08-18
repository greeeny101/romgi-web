<script lang="ts">
	import { tick } from 'svelte';
	import { page as appPage } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { Spinner, Button } from 'flowbite-svelte';
	import { GridOutline, ListOutline } from 'flowbite-svelte-icons';
	import { catalogApi, type Platform, type Region, type Source, type PaginatedEntries } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import { browseState } from '$lib/stores/browseState';
	import RomGridCard from '$lib/components/rom/RomGridCard.svelte';
	import RomListTile from '$lib/components/rom/RomListTile.svelte';
	import FilterBar from '$lib/components/filters/FilterBar.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';

	let platforms = $state<Platform[]>([]);
	let regions = $state<Region[]>([]);
	let sources = $state<Source[]>([]);
	let lookupsError = $state<string | null>(null);

	// Filters live in the URL so that leaving for an entry and coming back —
	// via the back button, the entry page's back link, or a reload — restores
	// exactly what the user was looking at.
	const initialParams = appPage.url.searchParams;
	const initialFilters = {
		query: initialParams.get('q') ?? '',
		platformFilter: initialParams.get('platform') ?? '',
		regionFilter: initialParams.get('region') ?? '',
		sourceFilter: initialParams.get('source') ?? ''
	};

	let query = $state(initialFilters.query);
	let platformFilter = $state(initialFilters.platformFilter);
	let regionFilter = $state(initialFilters.regionFilter);
	let sourceFilter = $state(initialFilters.sourceFilter);
	let page = $state(Math.max(1, Number.parseInt(initialParams.get('page') ?? '1', 10) || 1));
	let viewMode = $state<'grid' | 'list'>(initialParams.get('view') === 'list' ? 'list' : 'grid');

	// The entry the user opened last, to be scrolled back into view once the
	// first result set lands. Read at init so it is claimed before any effect.
	let pendingFocusSlug: string | null = browseState.takeFocus();
	let highlightedSlug = $state<string | null>(null);

	let result = $state<PaginatedEntries | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	const PAGE_SIZE = 40;

	async function loadLookups() {
		try {
			[platforms, regions, sources] = await Promise.all([
				catalogApi.platforms(),
				catalogApi.regions(),
				catalogApi.sources()
			]);
		} catch (err) {
			lookupsError = err instanceof ApiError ? err.message : 'Failed to load filters.';
		}
	}

	async function loadEntries() {
		loading = true;
		error = null;
		try {
			result = await catalogApi.entries({
				q: query || undefined,
				platform: platformFilter || undefined,
				region: regionFilter || undefined,
				source: sourceFilter || undefined,
				page,
				page_size: PAGE_SIZE
			});
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load the catalog.';
			result = null;
		} finally {
			loading = false;
		}
		await restoreFocus();
	}

	// Bring the entry the user came back from into view, once, after its card
	// has actually rendered.
	async function restoreFocus() {
		if (!pendingFocusSlug) return;
		const slug = pendingFocusSlug;
		pendingFocusSlug = null;
		await tick();
		const card = document.getElementById(`entry-${slug}`);
		if (!card) return;
		// Instant, not smooth — smooth scrolling fights SvelteKit's own scroll
		// restoration when arriving via the back button.
		card.scrollIntoView({ block: 'center' });
		highlightedSlug = slug;
		setTimeout(() => {
			if (highlightedSlug === slug) highlightedSlug = null;
		}, 2000);
	}

	function platformName(id: string): string {
		return platforms.find((p) => p.id === id)?.name ?? id;
	}
	function platformBrand(id: string): string | undefined {
		return platforms.find((p) => p.id === id)?.brand;
	}

	// Reset to page 1 whenever a filter changes; re-fetch on any relevant change.
	// The comparison matters: a bare read-and-reset would also fire on the first
	// run and stomp a page number restored from the URL.
	let lastFilters = { ...initialFilters };

	$effect(() => {
		const now = { query, platformFilter, regionFilter, sourceFilter };
		if (
			now.query === lastFilters.query &&
			now.platformFilter === lastFilters.platformFilter &&
			now.regionFilter === lastFilters.regionFilter &&
			now.sourceFilter === lastFilters.sourceFilter
		) {
			return;
		}
		lastFilters = now;
		page = 1;
	});

	// Mirror the current view into the URL, and remember it for the entry page's
	// "Back to Browse" link. replaceState, not goto — typing in the search box
	// must not pile up history entries.
	$effect(() => {
		const params = new URLSearchParams();
		if (query) params.set('q', query);
		if (platformFilter) params.set('platform', platformFilter);
		if (regionFilter) params.set('region', regionFilter);
		if (sourceFilter) params.set('source', sourceFilter);
		if (page > 1) params.set('page', String(page));
		if (viewMode !== 'grid') params.set('view', viewMode);

		const qs = params.toString();
		const search = qs ? `?${qs}` : '';
		if (search !== appPage.url.search) replaceState(`/${search}`, {});
		browseState.rememberSearch(search);
	});

	$effect(() => {
		void query;
		void platformFilter;
		void regionFilter;
		void sourceFilter;
		void page;
		loadEntries();
	});

	$effect(() => {
		loadLookups();
	});
</script>

<svelte:head>
	<title>Browse — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	{#if lookupsError}
		<ErrorView message={lookupsError} onRetry={loadLookups} />
	{/if}

	<FilterBar
		placeholder="Search the catalog…"
		bind:query
		{platforms}
		{regions}
		{sources}
		bind:platform={platformFilter}
		bind:region={regionFilter}
		bind:source={sourceFilter}
	>
		{#snippet actions()}
			<Button
				size="sm"
				color={viewMode === 'grid' ? 'primary' : 'alternative'}
				onclick={() => (viewMode = 'grid')}
				aria-label="Grid view"
			>
				<GridOutline class="h-4 w-4" />
			</Button>
			<Button
				size="sm"
				color={viewMode === 'list' ? 'primary' : 'alternative'}
				onclick={() => (viewMode = 'list')}
				aria-label="List view"
			>
				<ListOutline class="h-4 w-4" />
			</Button>
		{/snippet}
	</FilterBar>

	{#if loading && !result}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if error}
		<ErrorView message={error} onRetry={loadEntries} />
	{:else if result && result.items.length === 0}
		<EmptyState title="No ROMs found" description="Try a different search term or clear your filters." />
	{:else if result}
		<p class="text-sm text-gray-500 dark:text-gray-400">{result.total.toLocaleString()} results</p>

		{#if viewMode === 'grid'}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
				{#each result.items as entry (entry.slug)}
					<RomGridCard
						{entry}
						platformName={platformName(entry.platform_id)}
						platformBrand={platformBrand(entry.platform_id)}
						href={`/entry/${entry.slug}`}
						id={`entry-${entry.slug}`}
						highlighted={highlightedSlug === entry.slug}
					/>
				{/each}
			</div>
		{:else}
			<div class="flex flex-col gap-2">
				{#each result.items as entry (entry.slug)}
					<RomListTile
						{entry}
						platformName={platformName(entry.platform_id)}
						platformBrand={platformBrand(entry.platform_id)}
						href={`/entry/${entry.slug}`}
						id={`entry-${entry.slug}`}
						highlighted={highlightedSlug === entry.slug}
					/>
				{/each}
			</div>
		{/if}

		<Pagination {page} pageSize={PAGE_SIZE} total={result.total} onChange={(p) => (page = p)} />
	{/if}
</div>
