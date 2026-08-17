<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { Spinner, Table, TableBody, TableBodyCell, TableBodyRow, TableHead, TableHeadCell } from 'flowbite-svelte';
	import { catalogApi, type Source, type SourceHealth } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import SourceHealthBadge from '$lib/components/sources/SourceHealthBadge.svelte';
	import { ingestionSocket } from '$lib/stores/ws';

	let sources = $state<Source[]>([]);
	let health = $state<Map<string, SourceHealth>>(new Map());
	let loading = $state(true);
	let error = $state<string | null>(null);
	let unsubscribeWs: (() => void) | null = null;

	async function load() {
		loading = true;
		error = null;
		try {
			const [sourcesResult, healthResult] = await Promise.all([catalogApi.sources(), catalogApi.sourceHealth()]);
			sources = sourcesResult;
			health = new Map(healthResult.map((h) => [h.source_id, h]));
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
</script>

<svelte:head>
	<title>Sources — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Sources</h1>

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
						</TableBodyRow>
					{/each}
				</TableBody>
			</Table>
		</div>
	{/if}
</div>
