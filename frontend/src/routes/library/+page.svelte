<script lang="ts">
	import { Spinner } from 'flowbite-svelte';
	import { TrashBinOutline, FolderOpenOutline } from 'flowbite-svelte-icons';
	import { catalogApi, type Platform } from '$lib/api/catalog';
	import { libraryApi, type RecentlyViewedEntry } from '$lib/api/library';
	import { downloadsApi, type DownloadTask } from '$lib/api/downloads';
	import { favorites } from '$lib/stores/favorites';
	import { downloads } from '$lib/stores/downloads';
	import { ApiError } from '$lib/api/client';
	import RomGridCard from '$lib/components/rom/RomGridCard.svelte';
	import RegionFlags from '$lib/components/region/RegionFlags.svelte';
	import DownloadedBadge from '$lib/components/downloads/DownloadedBadge.svelte';
	import SavedLocallyBadge from '$lib/components/downloads/SavedLocallyBadge.svelte';
	import SortSelect, { type SortDirection } from '$lib/components/filters/SortSelect.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import { formatBytes, formatExpiry } from '$lib/format';
	import {
		anchorDownload,
		chooseFolder,
		clearFolder,
		ensureFolder,
		getSavedFolder,
		isFolderPickerSupported,
		saveToFolder
	} from '$lib/downloadTarget';

	let tab = $state<'wishlist' | 'recent' | 'downloaded'>('wishlist');
	let recentlyViewed = $state<RecentlyViewedEntry[]>([]);
	let downloaded = $state<DownloadTask[]>([]);
	let platforms = $state<Platform[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let saveError = $state<string | null>(null);
	let saving = $state<number | null>(null);

	// Platform first: it's what makes "work down my Dreamcast ROMs" possible,
	// which is the whole point of pairing this with a chosen save folder.
	const sortOptions = [
		{ value: 'platform', name: 'Platform' },
		{ value: 'title', name: 'Title' },
		{ value: 'date', name: 'Date downloaded' },
		{ value: 'size', name: 'Size' },
		{ value: 'saved', name: 'Saved locally' }
	];
	let sortKey = $state('platform');
	let sortDir = $state<SortDirection>('asc');

	let folder = $state<FileSystemDirectoryHandle | null>(null);
	const folderPickerSupported = isFolderPickerSupported();

	async function load() {
		loading = true;
		error = null;
		try {
			await favorites.load();
			[recentlyViewed, platforms, downloaded] = await Promise.all([
				libraryApi.recentlyViewed(),
				catalogApi.platforms(),
				downloadsApi.list('completed')
			]);
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load your library.';
		} finally {
			loading = false;
		}
	}

	async function pickFolder() {
		folder = (await chooseFolder()) ?? folder;
	}

	async function forgetFolder() {
		await clearFolder();
		folder = null;
	}

	async function saveFile(task: DownloadTask) {
		if (saving !== null) return;

		// Before anything else: requestPermission and showDirectoryPicker both
		// need transient user activation, and awaiting the file fetch first
		// spends the click that got us here.
		const target = await ensureFolder(true);
		folder = target;

		saving = task.id;
		saveError = null;
		try {
			const { blob, filename } = await downloadsApi.file(task.id);
			const name = filename ?? task.title;
			if (target) await saveToFolder(target, name, blob);
			else anchorDownload(blob, name);

			// The GET already stamped these server-side; mirror them here so the
			// Saved badge updates straight away instead of waiting for the next
			// load(). Only after the write actually succeeded — a failed
			// saveToFolder throws past this. last_retrieved_at moves on every
			// save, first_retrieved_at only the first time.
			const savedAt = new Date().toISOString();
			downloaded = downloaded.map((t) =>
				t.id === task.id
					? { ...t, last_retrieved_at: savedAt, first_retrieved_at: t.first_retrieved_at ?? savedAt }
					: t
			);
		} catch (err) {
			// The retention sweep is an hourly beat and can't see a file removed
			// out from under it, so file_available can claim bytes that are
			// already gone. The server blanks staged_file on this 404; mirror it
			// locally rather than leaving the row looking saveable.
			if (err instanceof ApiError && err.status === 404) {
				downloaded = downloaded.map((t) =>
					t.id === task.id ? { ...t, file_available: false } : t
				);
			}
			// Inline, not the page-level `error` — that swaps the whole list out
			// for an ErrorView, and one failed save shouldn't cost you the list.
			saveError = err instanceof ApiError ? err.message : 'Failed to save the file.';
		} finally {
			saving = null;
		}
	}

	async function removeDownload(task: DownloadTask) {
		// Through the store, not downloadsApi directly: DownloadedBadge on
		// Browse reads the store, so cancelling here without telling it leaves
		// the badge claiming a ROM you no longer have until the next reload.
		await downloads.cancel(task.id);
		downloaded = downloaded.filter((t) => t.id !== task.id);
	}

	function platformName(id: string): string {
		return platforms.find((p) => p.id === id)?.name ?? id;
	}
	function platformBrand(id: string): string | undefined {
		return platforms.find((p) => p.id === id)?.brand;
	}

	$effect(() => {
		load();
	});

	// Restore a previously chosen folder just to label the toolbar. No
	// permission check here — that needs a user gesture, so it happens on the
	// first Save (or on Change folder) via ensureFolder.
	$effect(() => {
		getSavedFolder().then((handle) => (folder = handle));
	});

	let wishlistItems = $derived(Array.from($favorites.values()));

	// Every comparator breaks ties on id so the order can't shuffle between
	// re-sorts — same reason as the `|| b.id - a.id` on the downloads page.
	function compare(a: DownloadTask, b: DownloadTask): number {
		switch (sortKey) {
			case 'title':
				return a.title.localeCompare(b.title) || a.id - b.id;
			case 'date':
				// ISO strings, so lexicographic order is chronological order.
				return (
					(a.completed_at ?? a.created_at).localeCompare(b.completed_at ?? b.created_at) ||
					a.id - b.id
				);
			case 'size':
				// The saved size, not the transfer size — they diverge once a
				// disc set is collapsed into a .chd.
				return (a.file_size ?? a.total_bytes) - (b.file_size ?? b.total_bytes) || a.id - b.id;
			case 'saved':
				// Ascending puts the not-yet-saved ones first — that's the pile
				// you still have work to do on. Saved rows then fall back to
				// most recently saved.
				return (
					Number(Boolean(a.last_retrieved_at)) - Number(Boolean(b.last_retrieved_at)) ||
					(b.last_retrieved_at ?? '').localeCompare(a.last_retrieved_at ?? '') ||
					a.id - b.id
				);
			default:
				return (
					a.platform_name.localeCompare(b.platform_name) ||
					a.title.localeCompare(b.title) ||
					a.id - b.id
				);
		}
	}

	let sortedDownloads = $derived(
		[...downloaded].sort((a, b) => (sortDir === 'asc' ? compare(a, b) : -compare(a, b)))
	);
</script>

<svelte:head>
	<title>Library — romgi</title>
</svelte:head>

<div class="flex flex-col gap-4">
	<div class="flex gap-1 border-b border-gray-200 dark:border-gray-700">
		<button
			type="button"
			class="border-b-2 px-3 py-2 text-sm font-medium {tab === 'wishlist'
				? 'border-primary-600 text-primary-600 dark:border-primary-400 dark:text-primary-400'
				: 'border-transparent text-gray-500 dark:text-gray-400'}"
			onclick={() => (tab = 'wishlist')}
		>
			Wishlist
		</button>
		<button
			type="button"
			class="border-b-2 px-3 py-2 text-sm font-medium {tab === 'recent'
				? 'border-primary-600 text-primary-600 dark:border-primary-400 dark:text-primary-400'
				: 'border-transparent text-gray-500 dark:text-gray-400'}"
			onclick={() => (tab = 'recent')}
		>
			Recently Viewed
		</button>
		<button
			type="button"
			class="border-b-2 px-3 py-2 text-sm font-medium {tab === 'downloaded'
				? 'border-primary-600 text-primary-600 dark:border-primary-400 dark:text-primary-400'
				: 'border-transparent text-gray-500 dark:text-gray-400'}"
			onclick={() => (tab = 'downloaded')}
		>
			Downloaded
		</button>
	</div>

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if error}
		<ErrorView message={error} onRetry={load} />
	{:else if tab === 'wishlist'}
		{#if wishlistItems.length === 0}
			<EmptyState title="Nothing in your wishlist yet" description="Favorite a ROM from Browse to see it here." />
		{:else}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
				{#each wishlistItems as item (item.slug)}
					<RomGridCard
						entry={{
							slug: item.slug,
							title: item.title,
							platform_id: item.platform_id,
							boxart_url: item.boxart_url,
							ra_game_id: null,
							regions: item.regions
						}}
						platformName={platformName(item.platform_id)}
						platformBrand={platformBrand(item.platform_id)}
						href={`/entry/${item.slug}`}
					/>
				{/each}
			</div>
		{/if}
	{:else if tab === 'recent'}
		{#if recentlyViewed.length === 0}
			<EmptyState title="No recently viewed ROMs" description="Entries you open will show up here." />
		{:else}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
				{#each recentlyViewed as item (item.slug)}
					<RomGridCard
						entry={{
							slug: item.slug,
							title: item.title,
							platform_id: item.platform_id,
							boxart_url: item.boxart_url,
							ra_game_id: null,
							regions: item.regions
						}}
						platformName={platformName(item.platform_id)}
						platformBrand={platformBrand(item.platform_id)}
						href={`/entry/${item.slug}`}
					/>
				{/each}
			</div>
		{/if}
	{:else if downloaded.length === 0}
		<EmptyState title="Nothing downloaded yet" description="Completed downloads show up here." />
	{:else}
		<div class="flex flex-col gap-3">
			<div class="flex flex-wrap items-center justify-between gap-3">
				<SortSelect options={sortOptions} bind:key={sortKey} bind:direction={sortDir} />

				{#if folderPickerSupported}
					<div class="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400">
						<FolderOpenOutline class="h-4 w-4 shrink-0" />
						{#if folder}
							<span class="truncate">Saving to <span class="font-medium">{folder.name}</span></span>
							<button type="button" class="text-primary-600 hover:underline dark:text-primary-400" onclick={pickFolder}>
								Change
							</button>
							<button type="button" class="hover:text-gray-900 dark:hover:text-white" onclick={forgetFolder}>
								Clear
							</button>
						{:else}
							<button type="button" class="text-primary-600 hover:underline dark:text-primary-400" onclick={pickFolder}>
								Choose folder…
							</button>
						{/if}
					</div>
				{:else}
					<!-- showDirectoryPicker is Chromium-only; everywhere else the save
					     falls through to the browser's own download directory. -->
					<p class="text-xs text-gray-400 dark:text-gray-500">
						Choosing a download folder needs Chrome or Edge.
					</p>
				{/if}
			</div>

			{#if saveError}
				<p class="text-xs text-red-600 dark:text-red-400">{saveError}</p>
			{/if}

			{#each sortedDownloads as task (task.id)}
				<div class="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700">
					<div class="flex min-w-0 flex-col gap-1">
						<p class="truncate font-medium text-gray-900 dark:text-white">{task.title}</p>
						<div class="flex flex-wrap items-center gap-1.5 text-xs text-gray-500 dark:text-gray-400">
							<span class="shrink-0">{platformName(task.platform_id)}</span>
							<RegionFlags regions={task.region_ids} size="h-3.5 w-3.5" />
							{#if task.file_size ?? task.total_bytes}
								<span class="shrink-0">· {formatBytes(task.file_size ?? task.total_bytes)}</span>
							{/if}
						</div>
						<div class="flex flex-wrap items-center gap-2">
							<DownloadedBadge variant="pill" completedAt={task.completed_at ?? task.created_at} />
							<SavedLocallyBadge savedAt={task.last_retrieved_at} firstSavedAt={task.first_retrieved_at} />
							{#if !task.file_available}
								<span class="text-xs text-gray-400 dark:text-gray-500">File removed from server</span>
							{:else if formatExpiry(task.expires_at)}
								<span class="text-xs text-gray-400 dark:text-gray-500">{formatExpiry(task.expires_at)}</span>
							{/if}
						</div>
					</div>
					<div class="flex shrink-0 items-center gap-3">
						<button
							type="button"
							class="text-xs text-primary-600 hover:underline disabled:opacity-50 dark:text-primary-400"
							disabled={saving === task.id || !task.file_available}
							title={task.file_available ? undefined : 'The staged file is no longer on the server'}
							onclick={() => saveFile(task)}
						>
							{saving === task.id ? 'Saving…' : 'Save file'}
						</button>
						<button
							type="button"
							class="text-gray-400 hover:text-red-600"
							onclick={() => removeDownload(task)}
							aria-label="Remove"
						>
							<TrashBinOutline class="h-4 w-4" />
						</button>
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
