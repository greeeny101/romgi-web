<script lang="ts">
	import { onMount } from 'svelte';
	import { page as appPage } from '$app/state';
	import { replaceState } from '$app/navigation';
	import { Spinner } from 'flowbite-svelte';
	import { catalogApi, type Platform, type Region, type Source } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import type { DownloadStatus, DownloadTask } from '$lib/api/downloads';
	import { downloads } from '$lib/stores/downloads';
	import DownloadQueueRow from '$lib/components/downloads/DownloadQueueRow.svelte';
	import StatusPills from '$lib/components/downloads/StatusPills.svelte';
	import { statusOrder } from '$lib/components/downloads/statusColor';
	import FilterBar from '$lib/components/filters/FilterBar.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';

	let loading = $state(true);

	// Filters live in the URL, same as Browse, so a reload or a shared link
	// comes back to the same view.
	const initialParams = appPage.url.searchParams;
	const initialStatus = initialParams.get('status') ?? '';

	let query = $state(initialParams.get('q') ?? '');
	let status = $state<DownloadStatus | ''>(
		statusOrder.includes(initialStatus as DownloadStatus) ? (initialStatus as DownloadStatus) : ''
	);
	let platformFilter = $state(initialParams.get('platform') ?? '');
	let regionFilter = $state(initialParams.get('region') ?? '');
	let sourceFilter = $state(initialParams.get('source') ?? '');

	let platforms = $state<Platform[]>([]);
	let regions = $state<Region[]>([]);
	let sources = $state<Source[]>([]);
	let lookupsError = $state<string | null>(null);

	async function loadLookups() {
		lookupsError = null;
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

	// Only offer values that actually appear in the queue — the catalog has
	// dozens of platforms and a user's downloads span a handful. The options
	// stay real catalog objects so FilterPanel's labelling works unchanged.
	let presentPlatforms = $derived(new Set($downloads.map((t) => t.platform_id)));
	let presentRegions = $derived(new Set($downloads.flatMap((t) => t.region_ids ?? [])));
	let presentSources = $derived(
		new Set($downloads.map((t) => t.source_id).filter((id): id is string => Boolean(id)))
	);

	let platformOptions = $derived(platforms.filter((p) => presentPlatforms.has(p.id)));
	let regionOptions = $derived(regions.filter((r) => presentRegions.has(r.id)));
	let sourceOptions = $derived(sources.filter((s) => presentSources.has(s.id)));

	function matchesQuery(task: DownloadTask, needle: string): boolean {
		if (!needle) return true;
		return `${task.title} ${task.link_name}`.toLowerCase().includes(needle.toLowerCase().trim());
	}

	// Everything except the status filter — the pill counts are taken from
	// this, so each number says what selecting that pill would actually show.
	let countable = $derived(
		$downloads
			.filter((t) => !platformFilter || t.platform_id === platformFilter)
			.filter((t) => !regionFilter || (t.region_ids ?? []).includes(regionFilter))
			.filter((t) => !sourceFilter || t.source_id === sourceFilter)
			.filter((t) => matchesQuery(t, query))
	);

	let statusCounts = $derived(
		countable.reduce(
			(acc, t) => {
				acc[t.status] += 1;
				return acc;
			},
			Object.fromEntries(statusOrder.map((s) => [s, 0])) as Record<DownloadStatus, number>
		)
	);

	// Newest first: a queue page is read from the top. created_at is ISO, so
	// it compares lexicographically; id breaks ties within a group enqueue.
	let visible = $derived(
		countable
			.filter((t) => !status || t.status === status)
			.sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id)
	);

	// Mirror the filters into the URL. replaceState, not goto — typing in the
	// search box must not pile up history entries.
	$effect(() => {
		const params = new URLSearchParams();
		if (query) params.set('q', query);
		if (status) params.set('status', status);
		if (platformFilter) params.set('platform', platformFilter);
		if (regionFilter) params.set('region', regionFilter);
		if (sourceFilter) params.set('source', sourceFilter);

		const qs = params.toString();
		const search = qs ? `?${qs}` : '';
		if (search !== appPage.url.search) replaceState(`/downloads${search}`, {});
	});

	$effect(() => {
		loadLookups();
	});

	onMount(async () => {
		await downloads.load();
		loading = false;
	});
</script>

<svelte:head>
	<title>Downloads — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Downloads</h1>

	{#if lookupsError}
		<ErrorView message={lookupsError} onRetry={loadLookups} />
	{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if $downloads.length === 0}
		<p class="text-sm text-gray-500 dark:text-gray-400">
			No downloads yet. Start one from an entry's page.
		</p>
	{:else}
		<FilterBar
			placeholder="Search downloads…"
			bind:query
			platforms={platformOptions}
			regions={regionOptions}
			sources={sourceOptions}
			bind:platform={platformFilter}
			bind:region={regionFilter}
			bind:source={sourceFilter}
			extraActive={Boolean(status)}
			onClear={() => (status = '')}
		>
			{#snippet secondary()}
				<StatusPills counts={statusCounts} total={countable.length} bind:value={status} />
			{/snippet}
		</FilterBar>

		{#if visible.length === 0}
			<EmptyState
				title="No downloads match"
				description="Try a different search term or clear your filters."
			/>
		{:else}
			<div class="flex flex-col gap-3">
				{#each visible as task (task.id)}
					<DownloadQueueRow {task} />
				{/each}
			</div>
		{/if}
	{/if}
</div>
