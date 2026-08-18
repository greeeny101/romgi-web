<script lang="ts">
	import { Badge, Button, Input, Label } from 'flowbite-svelte';
	import {
		credentialsApi,
		type CredentialKind,
		type CredentialStatus
	} from '$lib/api/credentials';
	import { ApiError } from '$lib/api/client';

	let {
		kind,
		providerId,
		providerName,
		hint
	}: {
		kind: CredentialKind;
		providerId: string;
		providerName: string;
		hint?: string;
	} = $props();

	let status = $state<CredentialStatus | null>(null);
	let values = $state<Record<string, string>>({});
	let loading = $state(true);
	let saving = $state(false);
	let saved = $state(false);
	let testing = $state(false);
	let testResult = $state<{ ok: boolean; message?: string | null } | null>(null);
	let error = $state<string | null>(null);

	const fields = $derived(status?.fields ?? []);
	const storedKeys = $derived(new Set(status?.stored_keys ?? []));

	/**
	 * Required fields the vault is still missing. Saving is a merge, so a
	 * provider can sit half-configured indefinitely — say it out loud rather
	 * than letting "Test connection" fail with a generic auth error.
	 */
	const missingRequired = $derived(
		fields.filter((f) => !f.optional && !storedKeys.has(f.key)).map((f) => f.label)
	);
	const complete = $derived(status !== null && missingRequired.length === 0);

	/**
	 * Chrome honours `off` on text inputs but not on password ones, where only
	 * `new-password` reliably suppresses the fill — without it the browser
	 * offered the archive.org S3 secret saved from the Internet Archive login
	 * form as the value for every password box on this page.
	 */
	function autocompleteFor(obscure: boolean): AutoFill {
		return obscure ? 'new-password' : 'off';
	}

	function isFilled(key: string): boolean {
		return (values[key] ?? '').trim().length > 0;
	}

	/** Non-secret saved values are shown back; secrets only get a placeholder. */
	function applyStored(next: CredentialStatus) {
		status = next;
		values = { ...next.stored_values };
	}

	async function load() {
		loading = true;
		try {
			applyStored(await credentialsApi.getStatus(kind, providerId));
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to load status.';
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		load();
	});

	async function save() {
		saving = true;
		saved = false;
		testResult = null;
		error = null;
		try {
			// Blank boxes mean "leave what's stored alone" — the backend merges,
			// so only send what the user actually typed.
			const payload: Record<string, string> = {};
			for (const field of fields) {
				const value = (values[field.key] ?? '').trim();
				if (value) payload[field.key] = value;
			}
			applyStored(await credentialsApi.set(kind, providerId, payload));
			saved = true;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to save credentials.';
		} finally {
			saving = false;
		}
	}

	async function test() {
		testing = true;
		saved = false;
		testResult = null;
		try {
			testResult = await credentialsApi.test(kind, providerId);
			if (status) status.status = testResult.ok ? 'ok' : 'invalid';
		} catch (err) {
			testResult = { ok: false, message: err instanceof ApiError ? err.message : 'Test failed.' };
		} finally {
			testing = false;
		}
	}

	async function clearCredentials() {
		error = null;
		try {
			await credentialsApi.clear(kind, providerId);
			await load();
			testResult = null;
			saved = false;
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to clear credentials.';
		}
	}

	const statusColor: Record<string, 'gray' | 'green' | 'yellow' | 'red'> = {
		unverified: 'gray',
		ok: 'green',
		stale: 'yellow',
		invalid: 'red'
	};
</script>

<div class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
	<div class="flex items-center justify-between">
		<span class="font-medium text-gray-900 dark:text-white">{providerName}</span>
		{#if status}
			<Badge color={complete ? statusColor[status.status] : 'gray'}>
				{#if !status.configured}not configured{:else if !complete}incomplete{:else}{status.status}{/if}
			</Badge>
		{/if}
	</div>

	{#if hint}
		<p class="text-xs text-gray-500 dark:text-gray-400">{hint}</p>
	{/if}

	{#if !loading}
		<div class="flex flex-col gap-2">
			{#each fields as field (field.key)}
				<div>
					<Label for={`${kind}-${providerId}-${field.key}`} class="mb-1 text-xs">
						{field.label}{field.optional ? ' (optional)' : ''}
						{#if storedKeys.has(field.key)}
							<span class="ml-1 font-normal text-green-600 dark:text-green-400">saved</span>
						{/if}
					</Label>
					<Input
						id={`${kind}-${providerId}-${field.key}`}
						name={`${providerId}-${field.key}`}
						type={field.obscure ? 'password' : 'text'}
						bind:value={values[field.key]}
						placeholder={storedKeys.has(field.key) && field.obscure
							? '•••••••• (leave blank to keep)'
							: ''}
						autocomplete={autocompleteFor(field.obscure)}
						autocorrect="off"
						autocapitalize="none"
						spellcheck="false"
						data-1p-ignore
						data-lpignore="true"
						size="sm"
					/>
				</div>
			{/each}
		</div>

		{#if missingRequired.length > 0}
			<p class="text-xs text-yellow-600 dark:text-yellow-400">
				Still needed: {missingRequired.join(', ')}
			</p>
		{/if}

		<div class="flex items-center gap-2">
			<Button
				size="xs"
				onclick={save}
				disabled={saving || !fields.some((f) => isFilled(f.key))}
			>
				{saving ? 'Saving…' : 'Save'}
			</Button>
			<Button size="xs" color="alternative" onclick={test} disabled={testing || !complete}>
				{testing ? 'Testing…' : 'Test connection'}
			</Button>
			{#if status?.configured}
				<Button size="xs" color="alternative" onclick={clearCredentials}>Clear</Button>
			{/if}
		</div>

		{#if saved && !testResult}
			<p class="text-xs text-green-600 dark:text-green-400">
				Saved{complete ? ' — use Test connection to check it works.' : '.'}
			</p>
		{/if}
		{#if testResult}
			<p
				class="text-xs {testResult.ok
					? 'text-green-600 dark:text-green-400'
					: 'text-red-600 dark:text-red-400'}"
			>
				{testResult.ok ? 'Connection OK' : testResult.message}
			</p>
		{/if}
		{#if error}
			<p class="text-xs text-red-600 dark:text-red-400">{error}</p>
		{/if}
	{/if}
</div>
