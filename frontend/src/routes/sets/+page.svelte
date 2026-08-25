<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page as appPage } from '$app/state';
	import { Button, Search, Select, Spinner } from 'flowbite-svelte';
	import { ApiError } from '$lib/api/client';
	import { romsetsApi, type Emulator, type LibrarySpace, type SetSearchResponse } from '$lib/api/romsets';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import Pagination from '$lib/components/common/Pagination.svelte';
	import RomSetQueueRow from '$lib/components/romsets/RomSetQueueRow.svelte';
	import { formatBytes } from '$lib/format';
	import { romsets } from '$lib/stores/romsets';

	const SEARCH_DEBOUNCE_MS = 250;

	let emulators = $state<Emulator[]>([]);
	let emulator = $state(appPage.url.searchParams.get('emulator') ?? '');
	let query = $state(appPage.url.searchParams.get('q') ?? '');
	let page = $state(Number(appPage.url.searchParams.get('page') ?? '1'));

	let result = $state<SetSearchResponse | null>(null);
	let space = $state<LibrarySpace | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	// Only the newest response may write `result` — a slow first query must
	// not overwrite the fast second one.
	let latestRequest = 0;
	let debounceTimer: ReturnType<typeof setTimeout> | null = null;
	let lastFilters = '';

	async function loadEmulators() {
		try {
			emulators = await romsetsApi.emulators();
			if (!emulator && emulators.length > 0) emulator = emulators[0].id;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load emulators.';
		}
	}

	async function loadSpace() {
		try {
			space = await romsetsApi.space();
		} catch {
			// The space banner is a nicety; its absence must not block searching.
		}
	}

	async function search() {
		if (!emulator) return;
		const requestId = ++latestRequest;
		loading = true;
		error = null;
		try {
			const response = await romsetsApi.search(emulator, query, page);
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
		loadEmulators();
		loadSpace();
	});

	// Reset to page 1 only when the filters really changed, so a page restored
	// from the URL on mount isn't stomped back to 1.
	$effect(() => {
		const filters = `${emulator}|${query}`;
		if (lastFilters && filters !== lastFilters) page = 1;
		lastFilters = filters;
	});

	$effect(() => {
		// Track the values this effect depends on before the async hop.
		const args = { emulator, query, page };
		if (!args.emulator) return;
		if (debounceTimer) clearTimeout(debounceTimer);
		debounceTimer = setTimeout(search, SEARCH_DEBOUNCE_MS);
	});

	$effect(() => {
		const params = new URLSearchParams();
		if (emulator) params.set('emulator', emulator);
		if (query) params.set('q', query);
		if (page > 1) params.set('page', String(page));
		const qs = params.toString();
		replaceState(qs ? `/sets?${qs}` : '/sets', {});
	});

	const emulatorOptions = $derived(emulators.map((e) => ({ value: e.id, name: e.name })));
	const active = $derived(
		$romsets.filter((r) => r.status !== 'completed' && r.status !== 'failed')
	);
	const finished = $derived(
		$romsets.filter((r) => r.status === 'completed' || r.status === 'failed')
	);
</script>

<svelte:head>
	<title>ROM Sets — romgi</title>
</svelte:head>

<div class="flex flex-col gap-6">
	<div class="flex flex-wrap items-baseline justify-between gap-2">
		<h1 class="text-xl font-semibold text-gray-900 dark:text-white">ROM Sets</h1>
		{#if space}
			<p class="text-xs text-gray-500 dark:text-gray-400">
				{formatBytes(space.available)} usable in the library
				<span class="text-gray-400 dark:text-gray-500">
					({formatBytes(space.free)} free, {formatBytes(space.reserve)} reserved for the system)
				</span>
			</p>
		{/if}
	</div>

	<p class="max-w-3xl text-sm text-gray-600 dark:text-gray-400">
		Whole published romsets from archive.org, downloaded over BitTorrent straight into your ROM
		library. Pick an emulator to see the set versions available, then choose which files inside a
		set you actually want.
	</p>

	{#if $romsets.length > 0}
		<section class="flex flex-col gap-2">
			<h2 class="text-sm font-semibold text-gray-900 dark:text-white">
				Your sets{active.length > 0 ? ` — ${active.length} in progress` : ''}
			</h2>
			<div class="flex flex-col gap-2">
				{#each [...active, ...finished] as romset (romset.id)}
					<RomSetQueueRow {romset} />
				{/each}
			</div>
		</section>
	{/if}

	<section class="flex flex-col gap-3">
		<div class="flex flex-wrap items-center gap-2">
			<div class="w-56">
				<Select bind:value={emulator} items={emulatorOptions} placeholder="Choose an emulator" />
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
				title="No sets found"
				description="Try a different emulator, or clear the extra search text."
			/>
		{:else if result}
			<div class="flex flex-col gap-2">
				{#each result.items as item (item.identifier)}
					<a
						href="/sets/{encodeURIComponent(item.identifier)}"
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
