<script lang="ts">
	import { goto } from '$app/navigation';
	import { page as appPage } from '$app/state';
	import { Alert, Button, Checkbox, Select, Spinner, Toggle } from 'flowbite-svelte';
	import { catalogApi, type Platform } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import { romsetsApi, type Emulator, type LibrarySpace, type SetItemDetail } from '$lib/api/romsets';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import { formatBytes } from '$lib/format';
	import { romsets } from '$lib/stores/romsets';

	const identifier = $derived(appPage.params.identifier ?? '');

	let item = $state<SetItemDetail | null>(null);
	let platforms = $state<Platform[]>([]);
	let emulators = $state<Emulator[]>([]);
	let space = $state<LibrarySpace | null>(null);

	let selected = $state<Set<string>>(new Set());
	let selectedFolders = $state<Set<string>>(new Set());
	let platformId = $state('');
	let extract = $state(false);

	let loading = $state(true);
	let error = $state<string | null>(null);
	let submitError = $state<string | null>(null);
	let submitting = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			const [detail, platformList, emulatorList] = await Promise.all([
				romsetsApi.item(identifier),
				catalogApi.platforms(),
				romsetsApi.emulators()
			]);
			item = detail;
			platforms = platformList;
			emulators = emulatorList;
			// Everything preselected: the common case is wanting the whole set,
			// and a set whose files all start unticked reads as broken.
			selectedFolders = new Set(detail.folders.map((f) => f.path));
			selected = new Set(detail.files.map((f) => f.path));

			const fromQuery = appPage.url.searchParams.get('emulator');
			const emulator = emulatorList.find((e) => e.id === fromQuery);
			if (emulator?.platform_id) platformId = emulator.platform_id;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load this set.';
		} finally {
			loading = false;
		}
		romsetsApi
			.space()
			.then((s) => (space = s))
			.catch(() => {});
	}

	$effect(() => {
		load();
	});

	function folderOf(path: string): string {
		const cut = path.indexOf('/');
		return cut === -1 ? '' : path.slice(0, cut);
	}

	function toggle(path: string) {
		const next = new Set(selected);
		if (next.has(path)) next.delete(path);
		else next.add(path);
		selected = next;
	}

	function toggleFolder(folder: string) {
		const folders = new Set(selectedFolders);
		const on = !folders.has(folder);
		if (on) folders.add(folder);
		else folders.delete(folder);
		selectedFolders = folders;

		// Below the cap the file list is authoritative, so keep the two in
		// step — a folder tick there means "tick all of its files".
		if (item && !item.files_truncated) {
			const next = new Set(selected);
			for (const f of item.files) {
				if (folderOf(f.path) !== folder) continue;
				if (on) next.add(f.path);
				else next.delete(f.path);
			}
			selected = next;
		}
	}

	function selectAll() {
		selectedFolders = new Set(item?.folders.map((f) => f.path) ?? []);
		selected = new Set(item?.files.map((f) => f.path) ?? []);
	}

	function selectNone() {
		selectedFolders = new Set();
		selected = new Set();
	}

	/** Past the cap only folders are selectable, so they carry the total. */
	const selectedBytes = $derived(
		item?.files_truncated
			? item.folders.filter((f) => selectedFolders.has(f.path)).reduce((sum, f) => sum + f.size, 0)
			: (item?.files ?? []).filter((f) => selected.has(f.path)).reduce((sum, f) => sum + f.size, 0)
	);

	const selectedCount = $derived(
		item?.files_truncated
			? item.folders
					.filter((f) => selectedFolders.has(f.path))
					.reduce((sum, f) => sum + f.file_count, 0)
			: selected.size
	);

	const platformOptions = $derived([
		{ value: '', name: 'Unsorted' },
		...platforms.map((p) => ({ value: p.id, name: `${p.brand} — ${p.name}` }))
	]);

	const fitsInLibrary = $derived(space === null || selectedBytes <= space.available);

	async function download() {
		if (!item || selectedCount === 0) return;
		submitting = true;
		submitError = null;
		try {
			await romsets.enqueue({
				identifier: item.identifier,
				platform_id: platformId || null,
				emulator_id: appPage.url.searchParams.get('emulator') ?? '',
				// Past the cap the client has never seen most of the paths, so
				// it names folders and lets the server expand them.
				paths: item.files_truncated ? undefined : [...selected],
				folders: item.files_truncated ? [...selectedFolders] : undefined,
				extract
			});
			await goto('/sets');
		} catch (err) {
			submitError = err instanceof ApiError ? err.message : 'Could not start this download.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>{item?.title ?? 'ROM Set'} — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<a href="/sets" class="text-sm text-primary-600 hover:underline dark:text-primary-400">
		← Back to ROM Sets
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
				{formatBytes(item.total_size)} across {item.files.length} files
				{#if item.published}· published {item.published}{/if}
			</p>
		</div>

		{#if item.restricted}
			<Alert color="blue">
				<span class="font-medium">Restricted item.</span> archive.org only serves this to logged-in
				accounts, so it uses your
				<a href="/settings/internet-archive" class="underline">Internet Archive login</a>. The transfer
				itself comes from other peers rather than archive.org's servers, so it can be slow — or stall
				entirely if nobody is seeding.
			</Alert>
		{/if}

		{#if item.description}
			<div
				class="prose prose-sm max-h-40 max-w-none overflow-y-auto rounded-lg border border-gray-200 p-3 text-sm text-gray-700 dark:border-gray-700 dark:text-gray-300"
			>
				<!-- archive.org descriptions are author-supplied HTML; rendered as
				     text so a set page can't inject markup into ours. -->
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
				Listed from the item's torrent, so this is exactly what can be transferred — it won't match
				the archive.org file listing exactly.
			</p>

			{#if item.folders.length > 1 || item.files_truncated}
				<div class="flex flex-col divide-y divide-gray-100 dark:divide-gray-700">
					{#each item.folders as folder (folder.path)}
						<label class="flex cursor-pointer items-center gap-3 py-2">
							<Checkbox
								checked={selectedFolders.has(folder.path)}
								onchange={() => toggleFolder(folder.path)}
								classes={{ div: 'shrink-0' }}
							/>
							<span class="min-w-0 flex-1 truncate text-sm font-medium text-gray-900 dark:text-white">
								{folder.path ? `${folder.path}/` : 'files at the top level'}
							</span>
							<span class="shrink-0 text-xs text-gray-500 dark:text-gray-400">
								{folder.file_count.toLocaleString()} file{folder.file_count === 1 ? '' : 's'}
							</span>
							<span class="shrink-0 text-xs tabular-nums text-gray-600 dark:text-gray-400">
								{formatBytes(folder.size)}
							</span>
						</label>
					{/each}
				</div>
			{/if}

			{#if item.files_truncated}
				<p class="text-xs text-gray-500 dark:text-gray-400">
					This set has {item.file_count.toLocaleString()} files, too many to tick individually — choose
					whole folders above. Unzip or prune afterwards if you want a subset.
				</p>
			{:else}
				<div class="flex flex-col divide-y divide-gray-100 dark:divide-gray-700">
					{#each item.files as file (file.path)}
						<label class="flex cursor-pointer items-center gap-3 py-2">
							<Checkbox
								checked={selected.has(file.path)}
								onchange={() => toggle(file.path)}
								classes={{ div: 'shrink-0' }}
							/>
							<span class="min-w-0 flex-1 truncate text-sm text-gray-900 dark:text-white">
								{file.path}
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
					{platformId || '_unsorted'}/{item.identifier}/
				</span>
			</div>

			<Toggle bind:checked={extract}>
				Extract archives after downloading (the archive is removed once expanded)
			</Toggle>
		</section>

		{#if submitError}
			<Alert color="red">{submitError}</Alert>
		{/if}

		{#if !fitsInLibrary && space}
			<Alert color="yellow">
				This selection needs {formatBytes(selectedBytes)} but only {formatBytes(space.available)} is
				usable — {formatBytes(space.reserve)} is held back so the server keeps working. Deselect some
				files or free up space.
			</Alert>
		{/if}

		<div class="flex flex-wrap items-center gap-3">
			<Button disabled={submitting || selectedCount === 0 || !fitsInLibrary} onclick={download}>
				{submitting
					? 'Starting…'
					: `Download ${selectedCount.toLocaleString()} file${selectedCount === 1 ? '' : 's'}`}
			</Button>
			<span class="text-sm text-gray-600 dark:text-gray-400">{formatBytes(selectedBytes)}</span>
		</div>
	{/if}
</div>
