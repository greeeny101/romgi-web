<script lang="ts">
	import { Search, Spinner, Button } from 'flowbite-svelte';
	import { GridOutline, ListOutline } from 'flowbite-svelte-icons';
	import { catalogApi, type Platform, type Region, type Source, type PaginatedEntries } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import RomGridCard from '$lib/components/rom/RomGridCard.svelte';
	import RomListTile from '$lib/components/rom/RomListTile.svelte';
	import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';

	let platforms = $state<Platform[]>([]);
	let regions = $state<Region[]>([]);
	let sources = $state<Source[]>([]);
	let lookupsError = $state<string | null>(null);

	let query = $state('');
	let platformFilter = $state('');
	let regionFilter = $state('');
	let sourceFilter = $state('');
	let page = $state(1);
	let viewMode = $state<'grid' | 'list'>('grid');

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
	}

	function platformName(id: string): string {
		return platforms.find((p) => p.id === id)?.name ?? id;
	}
	function platformBrand(id: string): string | undefined {
		return platforms.find((p) => p.id === id)?.brand;
	}

	// Reset to page 1 whenever a filter changes; re-fetch on any relevant change.
	$effect(() => {
		void query;
		void platformFilter;
		void regionFilter;
		void sourceFilter;
		page = 1;
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

	<div class="flex flex-col gap-3 sm:flex-row sm:items-center">
		<div class="flex-1">
			<Search placeholder="Search the catalog…" bind:value={query} clearable />
		</div>
		<div class="flex gap-1">
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
		</div>
	</div>

	<FilterPanel
		{platforms}
		{regions}
		{sources}
		bind:platform={platformFilter}
		bind:region={regionFilter}
		bind:source={sourceFilter}
	/>

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
					/>
				{/each}
			</div>
		{/if}

		<Pagination {page} pageSize={PAGE_SIZE} total={result.total} onChange={(p) => (page = p)} />
	{/if}
</div>
