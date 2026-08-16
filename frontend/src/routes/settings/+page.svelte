<script lang="ts">
	import { Button, Label, MultiSelect, Select, Toggle, Spinner } from 'flowbite-svelte';
	import { settingsApi, type UserSettings } from '$lib/api/settings';
	import { catalogApi, type Platform } from '$lib/api/catalog';
	import { ApiError } from '$lib/api/client';
	import { theme } from '$lib/stores/theme';
	import ErrorView from '$lib/components/common/ErrorView.svelte';
	import CredentialForm from '$lib/components/credentials/CredentialForm.svelte';

	let platforms = $state<Platform[]>([]);
	catalogApi.platforms().then((result) => (platforms = result)).catch(() => {});

	const debridProviders = [
		{ id: 'torbox', name: 'TorBox' },
		{ id: 'realdebrid', name: 'Real-Debrid' }
	];
	const debridFields = [{ key: 'api_key', label: 'API Key', obscure: true }];

	const screenScraperFields = [
		{ key: 'username', label: 'Username' },
		{ key: 'password', label: 'Password', obscure: true },
		{ key: 'dev_id', label: 'Developer ID', optional: true },
		{ key: 'dev_password', label: 'Developer Password', obscure: true, optional: true }
	];
	const steamGridDbFields = [{ key: 'api_key', label: 'API Key', obscure: true }];

	let settings = $state<UserSettings | null>(null);
	let loading = $state(true);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let saved = $state(false);

	async function load() {
		loading = true;
		error = null;
		try {
			settings = await settingsApi.get();
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load settings.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	async function save() {
		if (!settings) return;
		saving = true;
		saved = false;
		error = null;
		try {
			settings = await settingsApi.update({
				theme: settings.theme,
				max_concurrent_downloads: settings.max_concurrent_downloads,
				torrents_disabled: settings.torrents_disabled,
				auto_extract_disabled: settings.auto_extract_disabled,
				extract_disabled_platform_ids: settings.extract_disabled_platform_ids,
				debrid_enabled: settings.debrid_enabled,
				debrid_provider_id: settings.debrid_provider_id,
				metadata_enabled: settings.metadata_enabled
			});
			theme.set(settings.theme);
			saved = true;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to save settings.';
		} finally {
			saving = false;
		}
	}

	const themeItems = [
		{ value: 'system', name: 'System' },
		{ value: 'light', name: 'Light' },
		{ value: 'dark', name: 'Dark' }
	];
</script>

<svelte:head>
	<title>Settings — romgi</title>
</svelte:head>

<div class="mx-auto flex max-w-lg flex-col gap-6">
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Settings</h1>

	{#if loading}
		<div class="flex justify-center py-16"><Spinner size="8" /></div>
	{:else if error && !settings}
		<ErrorView message={error} onRetry={load} />
	{:else if settings}
		{#if error}
			<ErrorView message={error} />
		{/if}

		<div>
			<Label for="theme" class="mb-1">Appearance</Label>
			<Select id="theme" items={themeItems} bind:value={settings.theme} />
		</div>

		<div>
			<Label for="max-downloads" class="mb-1">
				Max concurrent downloads: {settings.max_concurrent_downloads === 0
					? 'Unlimited'
					: settings.max_concurrent_downloads}
			</Label>
			<input
				id="max-downloads"
				type="range"
				min="0"
				max="10"
				bind:value={settings.max_concurrent_downloads}
				class="w-full accent-primary-600"
			/>
		</div>

		<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">Downloads</h2>
		<div class="flex items-center justify-between">
			<span class="text-sm text-gray-700 dark:text-gray-300">Disable torrents</span>
			<Toggle bind:checked={settings.torrents_disabled} />
		</div>
		<div class="flex items-center justify-between">
			<span class="text-sm text-gray-700 dark:text-gray-300">Disable auto-extract</span>
			<Toggle bind:checked={settings.auto_extract_disabled} />
		</div>
		{#if !settings.auto_extract_disabled && platforms.length > 0}
			<div>
				<Label for="extract-disabled-platforms" class="mb-1">Never auto-extract for these platforms</Label>
				<MultiSelect
					id="extract-disabled-platforms"
					items={platforms.map((p) => ({ value: p.id, name: p.name }))}
					bind:value={settings.extract_disabled_platform_ids}
					placeholder="None — auto-extract everywhere"
				/>
			</div>
		{/if}

		<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">Internet Archive</h2>
		<a
			href="/settings/internet-archive"
			class="rounded-lg border border-gray-200 p-4 text-sm text-primary-600 hover:bg-gray-50 dark:border-gray-700 dark:text-primary-400 dark:hover:bg-gray-800"
		>
			Manage Internet Archive login &rarr;
		</a>

		<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">Debrid resolution</h2>
		<div class="flex items-center justify-between">
			<span class="text-sm text-gray-700 dark:text-gray-300">
				Resolve torrents via debrid
				<span class="block text-xs text-gray-400">Downloads torrent files as direct HTTP instead of via qBittorrent</span>
			</span>
			<Toggle bind:checked={settings.debrid_enabled} />
		</div>
		{#if settings.debrid_enabled}
			<div>
				<Label for="debrid-provider" class="mb-1">Provider</Label>
				<Select
					id="debrid-provider"
					items={debridProviders.map((p) => ({ value: p.id, name: p.name }))}
					bind:value={settings.debrid_provider_id}
				/>
			</div>
			{#each debridProviders as provider (provider.id)}
				{#if settings.debrid_provider_id === provider.id}
					<CredentialForm kind="debrid" providerId={provider.id} providerName={provider.name} fields={debridFields} />
				{/if}
			{/each}
		{/if}

		<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">Game metadata</h2>
		<div class="flex items-center justify-between">
			<span class="text-sm text-gray-700 dark:text-gray-300">Show extended metadata on entry pages</span>
			<Toggle bind:checked={settings.metadata_enabled} />
		</div>
		{#if settings.metadata_enabled}
			<CredentialForm kind="metadata" providerId="screenscraper" providerName="ScreenScraper" fields={screenScraperFields} />
			<CredentialForm kind="metadata" providerId="steamgriddb" providerName="SteamGridDB" fields={steamGridDbFields} />
		{/if}

		<Button onclick={save} disabled={saving}>
			{saving ? 'Saving…' : saved ? 'Saved' : 'Save changes'}
		</Button>
	{/if}
</div>
