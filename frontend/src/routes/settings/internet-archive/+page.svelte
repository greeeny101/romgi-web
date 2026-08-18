<script lang="ts">
	import { Badge, Button, Input, Label, Spinner } from 'flowbite-svelte';
	import { credentialsApi, type InternetArchiveStatus } from '$lib/api/credentials';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';

	let status = $state<InternetArchiveStatus | null>(null);
	let loading = $state(true);
	let username = $state('');
	let password = $state('');
	let accessKey = $state('');
	let secretKey = $state('');
	// Two ways in: drive archive.org's own login page server-side with the
	// user's password, or let the user sign in to archive.org themselves
	// and paste the keypair from /account/s3.php. The keys are what the
	// password flow ends up storing anyway, so pasting them skips a
	// headless browser that archive.org can refuse at any time.
	let mode = $state<'password' | 'keys'>('password');
	let submitting = $state(false);
	let error = $state<string | null>(null);

	function setMode(next: 'password' | 'keys') {
		mode = next;
		error = null;
	}

	async function loadStatus() {
		loading = true;
		try {
			status = await credentialsApi.iaStatus();
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load status.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		loadStatus();
	});

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			const { task_id } = await credentialsApi.iaLogin(username, password);
			// Poll the login task until it settles — mirrors the WebView
			// screen's loading spinner while the s3.php key exchange runs.
			// The window is generous because the server side is: a slow
			// archive.org page load plus a retry of the whole browser
			// login can legitimately run past two minutes, and giving up
			// early here would show a timeout for a login that then
			// quietly succeeds.
			for (let i = 0; i < 180; i++) {
				await new Promise((r) => setTimeout(r, 1000));
				const result = await credentialsApi.iaLoginStatus(task_id);
				if (result.state === 'success') {
					password = '';
					await loadStatus();
					submitting = false;
					return;
				}
				if (result.state === 'error') {
					error = result.message ?? 'Could not retrieve Internet Archive credentials. Please try again.';
					submitting = false;
					return;
				}
			}
			error = 'Login is taking longer than expected — check back in a moment.';
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Login failed.';
		} finally {
			submitting = false;
		}
	}

	async function submitKeys(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			// Verified inline server-side against archive.org's S3 auth
			// endpoint, so a bad paste comes straight back as an error
			// rather than being stored and failing at download time.
			status = await credentialsApi.iaSetKeys(accessKey, secretKey);
			accessKey = '';
			secretKey = '';
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Could not save those keys.';
		} finally {
			submitting = false;
		}
	}

	async function logout() {
		await credentialsApi.iaLogout();
		await loadStatus();
	}

	const statusColor: Record<string, 'gray' | 'green' | 'yellow' | 'red'> = {
		unverified: 'gray',
		ok: 'green',
		stale: 'yellow',
		invalid: 'red'
	};
</script>

<svelte:head>
	<title>Internet Archive — romgi</title>
</svelte:head>

<div class="mx-auto flex max-w-sm flex-col gap-4">
	<a href="/settings" class="text-sm text-primary-600 hover:underline dark:text-primary-400">&larr; Back to Settings</a>
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Internet Archive</h1>

	{#if loading}
		<div class="flex justify-center py-8"><Spinner size="6" /></div>
	{:else if status?.logged_in}
		<div class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
			<div class="flex items-center justify-between">
				<span class="text-sm text-gray-700 dark:text-gray-300">Logged in as {status.username}&nbsp;</span>
				<Badge color={statusColor[status.status]}>{status.status}</Badge>
			</div>
			<Button size="xs" color="alternative" onclick={logout}>Log out</Button>
		</div>
	{:else}
		{#if error}
			<ErrorView message={error} />
		{/if}
		<p class="text-sm text-gray-500 dark:text-gray-400">
			Connect your Internet Archive account to download login-required items.
		</p>

		<div class="flex rounded-lg border border-gray-200 p-1 dark:border-gray-700">
			<button
				type="button"
				class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition {mode === 'password'
					? 'bg-primary-600 text-white'
					: 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'}"
				onclick={() => setMode('password')}>Username &amp; password</button
			>
			<button
				type="button"
				class="flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition {mode === 'keys'
					? 'bg-primary-600 text-white'
					: 'text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-800'}"
				onclick={() => setMode('keys')}>API keys</button
			>
		</div>

		{#if mode === 'password'}
			<form class="flex flex-col gap-4" onsubmit={submit}>
				<div>
					<Label for="ia-username" class="mb-1">Username or email</Label>
					<Input id="ia-username" bind:value={username} required autocomplete="username" />
				</div>
				<div>
					<Label for="ia-password" class="mb-1">Password</Label>
					<Input id="ia-password" type="password" bind:value={password} required autocomplete="current-password" />
				</div>
				<Button type="submit" disabled={submitting}>{submitting ? 'Logging in…' : 'Log in'}</Button>
			</form>
		{:else}
			<form class="flex flex-col gap-4" onsubmit={submitKeys}>
				<p class="text-sm text-gray-500 dark:text-gray-400">
					Sign in to archive.org in your browser, open
					<a
						href="https://archive.org/account/s3.php"
						target="_blank"
						rel="noopener noreferrer"
						class="text-primary-600 hover:underline dark:text-primary-400">archive.org/account/s3.php</a
					>, and paste your keys below. They don't expire, so you won't be asked to sign in again.
				</p>
				<div>
					<Label for="ia-access-key" class="mb-1">Access key</Label>
					<Input id="ia-access-key" bind:value={accessKey} required autocomplete="off" spellcheck="false" />
				</div>
				<div>
					<Label for="ia-secret-key" class="mb-1">Secret key</Label>
					<Input
						id="ia-secret-key"
						type="password"
						bind:value={secretKey}
						required
						autocomplete="off"
						spellcheck="false"
					/>
				</div>
				<Button type="submit" disabled={submitting}>{submitting ? 'Verifying…' : 'Save keys'}</Button>
			</form>
		{/if}
	{/if}
</div>
