<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page as appPage } from '$app/state';
	import { Button, Search, Select, Spinner } from 'flowbite-svelte';
	import { biosApi, type BiosSearchResponse, type BiosSource } from '$lib/api/bios';
	import { ApiError } from '$lib/api/client';
	import BiosQueueRow from '$lib/components/bios/BiosQueueRow.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import { formatBytes } from '$lib/format';
	import { bios } from '$lib/stores/bios';

	const SEARCH_DEBOUNCE_MS = 250;

	let sources = $state<BiosSource[]>([]);
	let source = $state(appPage.url.searchParams.get('source') ?? '');
	let query = $state(appPage.url.searchParams.get('q') ?? '');
	let page = $state(Number(appPage.url.searchParams.get('page') ?? '1'));

	let result = $state<BiosSearchResponse | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Only the newest response may write `result` — a slow first query must
	// not overwrite the fast second one.
	let latestRequest = 0;
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let lastFilters = '';

	async function loadSources() {
		try {
			sources = await biosApi.sources();
			if (!source && sources.length > 0) source = sources[0].id;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load systems.';
		}
	}

	async function search() {
		if (!source) return;
		const requestId = ++latestRequest;
		loading = true;
		error = null;
		try {
			const response = await biosApi.search(source, query, page);
			if (requestId === latestRequest) result = response;
		} catch (err) {
			if (requestId === latestRequest) {
				error = err instanceof ApiError ? err.message : 'Search failed.';
				result = null;
			}
		} finally {
			if (requestId === latestRequest) loading = false;
		}
	}

	$effect(() => {
		loadSources();
	});

	// Reset to page 1 only when the filters really changed, so a page restored
	// from the URL on mount isn't stomped back to 1.
	$effect(() => {
		const filters = `${source}|${query}`;
		if (lastFilters && filters !== lastFilters) page = 1;
		lastFilters = filters;
	});

	$effect(() => {
		// Track the values this effect depends on before the async hop.
		const args = { source, query, page };
		if (!args.source) return;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(search, SEARCH_DEBOUNCE_MS);
	});

	$effect(() => {
		const params = new URLSearchParams();
		if (source) params.set('source', source);
		if (query) params.set('q', query);
		if (page > 1) params.set('page', String(page));
		const qs = params.toString();
		replaceState(qs ? `/bios?${qs}` : '/bios', {});
	});

	const sourceOptions = $derived(sources.map((s) => ({ value: s.id, name: s.name })));
	const active = $derived($bios.filter((b) => b.status !== 'completed' && b.status !== 'failed'));
	const finished = $derived($bios.filter((b) => b.status === 'completed' || b.status === 'failed'));
</script>

<svelte:head>
	<title>BIOS — romgi</title>
</svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-baseline justify-between gap-2">
		<h1 class="text-xl font-semibold text-gray-900 dark:text-white">BIOS</h1>
	</div>

	<p class="max-w-3xl text-sm text-gray-600 dark:text-gray-400">
		The system files a PlayStation, Saturn, Dreamcast or CD-i emulator refuses to boot without,
		fetched from archive.org straight into <span class="font-mono">bios/</span> in your ROM library.
		Pick a system to see what's published, then choose the individual files you need — the
		multi-system packs are large, but taking one BIOS out of one costs only that file.
	</p>

	{#if $bios.length > 0}
		<section class="flex flex-col gap-2">
			<h2 class="text-sm font-semibold text-gray-900 dark:text-white">
				Your BIOS downloads{active.length > 0 ? ` — ${active.length} in progress` : ''}
			</h2>
			<div class="flex flex-col gap-2">
				{#each [...active, ...finished] as row (row.id)}
					<BiosQueueRow bios={row} />
				{/each}
			</div>
		</section>
	{/if}

	<section class="flex flex-col gap-3">
		<div class="flex flex-wrap items-center gap-2">
			<div class="w-56">
				<Select bind:value={source} items={sourceOptions} placeholder="Choose a system" />
			</div>
			<div class="min-w-[16rem] flex-1">
				<Search bind:value={query} placeholder="Narrow these results (optional)…" />
			</div>
			{#if query}
				<Button size="sm" color="alternative" onclick={() => (query = '')}>Clear</Button>
			{/if}
		</div>

		{#if loading}
			<div class="flex justify-center py-16"><Spinner size="8" /></div>
		{:else if error}
			<ErrorView message={error} onRetry={search} />
		{:else if result && result.items.length === 0}
			<EmptyState
				title="No BIOS items found"
				description="Try a different system, or clear the extra search text."
			/>
		{:else if result}
			<div class="flex flex-col gap-2">
				{#each result.items as item (item.identifier)}
					<!-- The source rides along so the detail page can preselect the
					     platform its files belong to. -->
					<a
						href="/bios/{encodeURIComponent(item.identifier)}?source={encodeURIComponent(source)}"
						class="flex flex-col gap-1 rounded-lg border border-gray-200 p-3 transition hover:border-primary-500 hover:bg-gray-50 dark:border-gray-700 dark:hover:border-primary-500 dark:hover:bg-gray-800"
					>
						<span class="font-medium text-gray-900 dark:text-white">{item.title}</span>
						<span class="font-mono text-xs text-gray-500 dark:text-gray-400">{item.identifier}</span>
						<span class="text-xs text-gray-600 dark:text-gray-400">
							{formatBytes(item.size)}
							{#if item.published}· published {item.published}{/if}
							{#if item.downloads}· {item.downloads.toLocaleString()} downloads{/if}
						</span>
					</a>
				{/each}
			</div>
			<Pagination
				{page}
				pageSize={result.page_size}
				total={result.total}
				onChange={(p) => (page = p)}
			/>
		{/if}
	</section>
</div>
