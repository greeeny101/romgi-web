<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { Button, Spinner, Table, TableBody, TableBodyCell, TableBodyRow, TableHead, TableHeadCell } from 'flowbite-svelte';
	import { catalogApi, type Source, type SourceHealth } from '$lib/api/catalog';
	import { ingestionApi } from '$lib/api/ingestion';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import SourceHealthBadge from '$lib/components/sources/SourceHealthBadge.svelte';
	import { ingestionSocket } from '$lib/stores/ws';

	let sources = $state<Source[]>([]);
	let health = $state<Map<string, SourceHealth>>(new Map());
	let loading = $state(true);
	let error = $state<string | null>(null);
	let unsubscribeWs: (() => void) | null = null;
	let triggering = $state<Set<string>>(new Set());
	let runErrors = $state<Map<string, string>>(new Map());
	// Ingestion takes a single global slot (apps.ingestion.api.run_source
	// rejects a second build with 409), so this gates every Run button, not
	// just the one whose source is mid-scrape.
	let buildRunning = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			const [sourcesResult, healthResult, status] = await Promise.all([
				catalogApi.sources(),
				catalogApi.sourceHealth(),
				ingestionApi.status()
			]);
			sources = sourcesResult;
			health = new Map(healthResult.map((h) => [h.source_id, h]));
			buildRunning = status.running;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load sources.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	onMount(() => {
		ingestionSocket.connect();
		unsubscribeWs = ingestionSocket.subscribe((type, data) => {
			if (type === 'source.health') {
				const h = data as SourceHealth;
				health = new Map(health).set(h.source_id, h);
			} else if (type === 'build.status') {
				buildRunning = (data as { running: boolean }).running;
			}
		});
	});

	onDestroy(() => {
		unsubscribeWs?.();
		ingestionSocket.disconnect();
	});

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		return new Date(iso).toLocaleString();
	}

	/** This particular source is the one being scraped. */
	function isRunning(sourceId: string): boolean {
		return triggering.has(sourceId) || health.get(sourceId)?.status === 'running';
	}

	/** Any run at all is in flight, including one started from another tab. */
	const anyRunning = $derived(buildRunning || triggering.size > 0);

	/** The source currently being scraped, if we can tell which it is. */
	const runningSource = $derived(sources.find((s) => isRunning(s.id))?.name ?? null);

	async function runSource(sourceId: string) {
		triggering = new Set(triggering).add(sourceId);
		runErrors = new Map(runErrors);
		runErrors.delete(sourceId);
		buildRunning = true;
		try {
			await catalogApi.runSource(sourceId);
			// Status flips to 'running' via the WS source.health event once
			// the Celery task actually starts — triggering just covers the
			// gap between clicking and that first event arriving.
		} catch (err) {
			// The optimistic lock above has to come back off, or a rejected
			// start would leave every button disabled until a reload.
			buildRunning = (await ingestionApi.status().catch(() => ({ running: false }))).running;
			runErrors = new Map(runErrors).set(
				sourceId,
				err instanceof ApiError ? err.message : 'Failed to start run.'
			);
		} finally {
			const next = new Set(triggering);
			next.delete(sourceId);
			triggering = next;
		}
	}
</script>

<svelte:head>
	<title>Sources — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Sources</h1>

	{#if anyRunning}
		<div
			class="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-800 dark:border-blue-900 dark:bg-blue-950 dark:text-blue-200"
		>
			<Spinner size="4" />
			<span>
				{runningSource ? `Running ${runningSource}` : 'An ingestion run is in progress'} — only one
				source can be checked at a time, so the other sources cannot be run at this time.
			</span>
		</div>
	{/if}

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if error}
		<ErrorView message={error} onRetry={load} />
	{:else}
		<div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
			<Table>
				<TableHead>
					<TableHeadCell>Source</TableHeadCell>
					<TableHeadCell>Status</TableHeadCell>
					<TableHeadCell>Entries</TableHeadCell>
					<TableHeadCell>Links</TableHeadCell>
					<TableHeadCell>Last checked</TableHeadCell>
					<TableHeadCell>Notes</TableHeadCell>
					<TableHeadCell>Run</TableHeadCell>
				</TableHead>
				<TableBody>
					{#each sources as source (source.id)}
						{@const h = health.get(source.id)}
						<TableBodyRow>
							<TableBodyCell>
								{#if source.homepage}
									<a href={source.homepage} target="_blank" rel="noopener" class="text-primary-600 hover:underline dark:text-primary-400">
										{source.name}
									</a>
								{:else}
									{source.name}
								{/if}
							</TableBodyCell>
							<TableBodyCell><SourceHealthBadge status={h?.status ?? 'unknown'} /></TableBodyCell>
							<TableBodyCell>{h?.entry_count ?? '—'}</TableBodyCell>
							<TableBodyCell>{h?.link_count ?? '—'}</TableBodyCell>
							<TableBodyCell>{formatDate(h?.last_checked_at ?? null)}</TableBodyCell>
							<TableBodyCell class="max-w-xs truncate text-xs text-gray-500 dark:text-gray-400" title={h?.notes ?? ''}>
								{h?.notes ?? ''}
							</TableBodyCell>
							<TableBodyCell>
								<Button
									size="xs"
									color="alternative"
									disabled={anyRunning}
									title={anyRunning && !isRunning(source.id)
										? 'Another ingestion run is in progress — only one can run at a time.'
										: ''}
									onclick={() => runSource(source.id)}
								>
									{isRunning(source.id) ? 'Running…' : 'Run'}
								</Button>
								{#if runErrors.get(source.id)}
									<p class="mt-1 max-w-[10rem] text-xs text-red-600 dark:text-red-400">{runErrors.get(source.id)}</p>
								{/if}
							</TableBodyCell>
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	{/if}
</div>
