<script lang="ts">
	import { Spinner } from 'flowbite-svelte';
	import { TrashBinOutline } from 'flowbite-svelte-icons';
	import { catalogApi, type Platform } from '$lib/api/catalog';
	import { libraryApi, type RecentlyViewedEntry } from '$lib/api/library';
	import { downloadsApi, type DownloadTask } from '$lib/api/downloads';
	import { favorites } from '$lib/stores/favorites';
	import { ApiError } from '$lib/api/client';
	import RomGridCard from '$lib/components/rom/RomGridCard.svelte';
	import EmptyState from '$lib/components/common/EmptyState.svelte';
	import ErrorView from '$lib/components/common/ErrorView.svelte';

	let tab = $state<'wishlist' | 'recent' | 'downloaded'>('wishlist');
	let recentlyViewed = $state<RecentlyViewedEntry[]>([]);
	let downloaded = $state<DownloadTask[]>([]);
	let platforms = $state<Platform[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let verifying = $state<number | null>(null);
	let saving = $state<number | null>(null);

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

	async function verify(task: DownloadTask) {
		verifying = task.id;
		try {
			const result = await downloadsApi.verify(task.id);
			if (!result.exists) {
				downloaded = downloaded.filter((t) => t.id !== task.id);
			}
		} finally {
			verifying = null;
		}
	}

	async function saveFile(task: DownloadTask) {
		if (saving !== null) return;
		saving = task.id;
		try {
			const { blob, filename } = await downloadsApi.file(task.id);
			const url = URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = filename ?? task.title;
			document.body.appendChild(a);
			a.click();
			a.remove();
			URL.revokeObjectURL(url);
		} finally {
			saving = null;
		}
	}

	async function removeDownload(task: DownloadTask) {
		await downloadsApi.cancel(task.id);
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

	let wishlistItems = $derived(Array.from($favorites.values()));
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
		<div class="flex flex-col gap-2">
			{#each downloaded as task (task.id)}
				<div class="flex items-center justify-between gap-3 rounded-lg border border-gray-200 p-3 text-sm dark:border-gray-700">
					<div class="min-w-0">
						<p class="truncate font-medium text-gray-900 dark:text-white">{task.title}</p>
						<p class="text-xs text-gray-500 dark:text-gray-400">
							{platformName(task.platform_id)} · completed {new Date(task.completed_at ?? task.created_at).toLocaleDateString()}
						</p>
					</div>
					<div class="flex shrink-0 items-center gap-3">
						<button
							type="button"
							class="text-xs text-primary-600 hover:underline disabled:opacity-50 dark:text-primary-400"
							disabled={saving === task.id}
							onclick={() => saveFile(task)}
						>
							{saving === task.id ? 'Saving…' : 'Save file'}
						</button>
						<button
							type="button"
							class="text-xs text-gray-500 hover:text-gray-900 disabled:opacity-50 dark:hover:text-white"
							disabled={verifying === task.id}
							onclick={() => verify(task)}
						>
							{verifying === task.id ? 'Verifying…' : 'Verify'}
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
