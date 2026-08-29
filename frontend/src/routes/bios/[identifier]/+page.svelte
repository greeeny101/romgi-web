<script lang="ts">
	import { goto } from '$app/navigation';
	import { page as appPage } from '$app/state';
	import { Alert, Button, Checkbox, Search, Select, Spinner, Toggle } from 'flowbite-svelte';
	import { biosApi, type BiosItemDetail, type BiosSource } from '$lib/api/bios';
	import { catalogApi, type Platform } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import { formatBytes } from '$lib/format';
	import { bios } from '$lib/stores/bios';

	const identifier = $derived(appPage.params.identifier ?? '');
	const sourceId = $derived(appPage.url.searchParams.get('source') ?? '');

	let item = $state<BiosItemDetail | null>(null);
	let platforms = $state<Platform[]>([]);
	let sources = $state<BiosSource[]>([]);

	let selected = $state<Set<string>>(new Set());
	let platformId = $state('');
	let extract = $state(false);
	let filter = $state('');

	let loading = $state(true);
	let error = $state<string | null>(null);
	let submitError = $state<string | null>(null);
	let submitting = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			const [detail, platformList, sourceList] = await Promise.all([
				biosApi.item(identifier),
				catalogApi.platforms(),
				biosApi.sources()
			]);
			item = detail;
			platforms = platformList;
			sources = sourceList;
			// Everything preselected, matching /sets — an item whose files all
			// start unticked reads as broken. The filter box below is how you
			// get down to the one file you actually want out of a big pack.
			selected = new Set(detail.files.map((f) => f.name));

			const source = sourceList.find((s) => s.id === sourceId);
			if (source?.platform_id) platformId = source.platform_id;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load this item.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	function toggle(name: string) {
		const next = new Set(selected);
		if (next.has(name)) next.delete(name);
		else next.add(name);
		selected = next;
	}

	/** Select all / none act on what's visible, so they compose with the filter. */
	function selectAll() {
		const next = new Set(selected);
		for (const f of visible) next.add(f.name);
		selected = next;
	}

	function selectNone() {
		const next = new Set(selected);
		for (const f of visible) next.delete(f.name);
		selected = next;
	}

	const visible = $derived(
		(item?.files ?? []).filter((f) => f.name.toLowerCase().includes(filter.trim().toLowerCase()))
	);

	const selectedBytes = $derived(
		(item?.files ?? []).filter((f) => selected.has(f.name)).reduce((sum, f) => sum + f.size, 0)
	);

	const platformOptions = $derived([
		{ value: '', name: 'Unsorted' },
		...platforms.map((p) => ({ value: p.id, name: `${p.brand} — ${p.name}` }))
	]);

	async function download() {
		if (!item || selected.size === 0) return;
		submitting = true;
		submitError = null;
		try {
			await bios.enqueue({
				identifier: item.identifier,
				platform_id: platformId || null,
				source_id: sourceId,
				names: [...selected],
				extract
			});
			await goto('/bios');
		} catch (err) {
			submitError = err instanceof ApiError ? err.message : 'Could not start this download.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>{item?.title ?? 'BIOS'} — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<a href="/bios" class="text-sm text-primary-600 hover:underline dark:text-primary-400">
		← Back to BIOS
	</a>

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if error}
		<ErrorView message={error} onRetry={load} />
	{:else if item}
		<div class="flex flex-col gap-1">
			<h1 class="text-xl font-semibold text-gray-900 dark:text-white">{item.title}</h1>
			<p class="font-mono text-xs text-gray-500 dark:text-gray-400">{item.identifier}</p>
			<p class="text-xs text-gray-600 dark:text-gray-400">
				{formatBytes(item.total_size)} across {item.file_count} files
				{#if item.published}· published {item.published}{/if}
			</p>
		</div>

		{#if item.restricted}
			<Alert color="blue">
				<span class="font-medium">Restricted item.</span> archive.org only serves this to logged-in
				accounts, so it uses your
				<a href="/settings/internet-archive" class="underline">Internet Archive login</a>. Its
				description is readable without one, which is why the item can look browsable and then fail
				at the download.
			</Alert>
		{/if}

		{#if item.description}
			<div
				class="prose prose-sm max-h-40 max-w-none overflow-y-auto rounded-lg border border-gray-200 p-3 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300"
			>
				<!-- archive.org descriptions are author-supplied HTML; rendered as
				     text so an item page can't inject markup into ours. -->
				{item.description.replace(/<[^>]*>/g, ' ')}
			</div>
		{/if}

		<section class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
			<div class="flex flex-wrap items-center justify-between gap-2">
				<h2 class="text-sm font-semibold text-gray-900 dark:text-white">Files to download</h2>
				<div class="flex gap-2">
					<Button size="xs" color="alternative" onclick={selectAll}>Select all</Button>
					<Button size="xs" color="alternative" onclick={selectNone}>Select none</Button>
				</div>
			</div>

			<p class="text-xs text-gray-500 dark:text-gray-400">
				Each file is fetched individually over HTTP, so a multi-system pack costs only the files you
				tick. archive.org's own generated files ({'_meta.xml'}, {'_files.xml'}, the item torrent) are
				already filtered out.
			</p>

			{#if item.files.length > 12}
				<Search bind:value={filter} size="md" placeholder="Filter these files…" />
				{#if filter}
					<p class="text-xs text-gray-500 dark:text-gray-400">
						Showing {visible.length} of {item.files.length} files. Select all / none apply to what's
						shown.
					</p>
				{/if}
			{/if}

			{#if visible.length === 0}
				<p class="py-4 text-center text-sm text-gray-500 dark:text-gray-400">
					No files match “{filter}”.
				</p>
			{:else}
				<div class="flex max-h-[28rem] flex-col divide-y divide-gray-100 overflow-y-auto dark:divide-gray-700">
					{#each visible as file (file.name)}
						<label class="flex cursor-pointer items-center gap-3 py-2">
							<Checkbox
								checked={selected.has(file.name)}
								onchange={() => toggle(file.name)}
								classes={{ div: 'shrink-0' }}
							/>
							<span class="min-w-0 flex-1 truncate text-sm text-gray-900 dark:text-white">
								{file.name}
							</span>
							{#if file.format}
								<span class="shrink-0 text-xs text-gray-400 dark:text-gray-500">{file.format}</span>
							{/if}
							<span class="shrink-0 text-xs tabular-nums text-gray-600 dark:text-gray-400">
								{formatBytes(file.size)}
							</span>
						</label>
					{/each}
				</div>
			{/if}
		</section>

		<section class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
			<h2 class="text-sm font-semibold text-gray-900 dark:text-white">Where it goes</h2>

			<div class="flex flex-wrap items-center gap-3">
				<div class="w-72">
					<Select bind:value={platformId} items={platformOptions} />
				</div>
				<span class="font-mono text-xs text-gray-500 dark:text-gray-400">
					bios/{platformId || '_unsorted'}/
				</span>
			</div>

			<Toggle bind:checked={extract}>
				Extract archives after downloading (the archive is removed once expanded)
			</Toggle>
		</section>

		{#if submitError}
			<Alert color="red">{submitError}</Alert>
		{/if}

		<div class="flex flex-wrap items-center gap-3">
			<Button disabled={submitting || selected.size === 0} onclick={download}>
				{submitting
					? 'Starting…'
					: `Download ${selected.size.toLocaleString()} file${selected.size === 1 ? '' : 's'}`}
			</Button>
			<span class="text-sm text-gray-600 dark:text-gray-400">{formatBytes(selectedBytes)}</span>
		</div>
	{/if}
</div>
