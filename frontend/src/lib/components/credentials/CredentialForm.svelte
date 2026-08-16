<script lang="ts">
	import { Badge, Button, Input, Label } from 'flowbite-svelte';
	import { credentialsApi, type CredentialKind, type CredentialStatus } from '$lib/api/credentials';
	import { ApiError } from '$lib/api/client';

	interface FieldDef {
		key: string;
		label: string;
		obscure?: boolean;
		optional?: boolean;
	}

	let {
		kind,
		providerId,
		providerName,
		fields
	}: {
		kind: CredentialKind;
		providerId: string;
		providerName: string;
		fields: FieldDef[];
	} = $props();

	let status = $state<CredentialStatus | null>(null);
	let values = $state<Record<string, string>>({});
	let loading = $state(true);
	let saving = $state(false);
	let testing = $state(false);
	let testResult = $state<{ ok: boolean; message?: string | null } | null>(null);
	let error = $state<string | null>(null);

	async function load() {
		loading = true;
		try {
			status = await credentialsApi.getStatus(kind, providerId);
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
		testResult = null;
		error = null;
		try {
			status = await credentialsApi.set(kind, providerId, values);
			values = {};
		} catch (err) {
			error = err instanceof ApiError ? err.message : 'Failed to save credentials.';
		} finally {
			saving = false;
		}
	}

	async function test() {
		testing = true;
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
			status = { provider: providerId, configured: false, status: 'unverified' };
			testResult = null;
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
			<Badge color={statusColor[status.status]}>{status.configured ? status.status : 'not configured'}</Badge>
		{/if}
	</div>

	{#if !loading}
		<div class="flex flex-col gap-2">
			{#each fields as field (field.key)}
				<div>
					<Label for={`${kind}-${providerId}-${field.key}`} class="mb-1 text-xs">
						{field.label}{field.optional ? ' (optional)' : ''}
					</Label>
					<Input
						id={`${kind}-${providerId}-${field.key}`}
						type={field.obscure ? 'password' : 'text'}
						bind:value={values[field.key]}
						placeholder={status?.configured ? '••••••••' : ''}
						size="sm"
					/>
				</div>
			{/each}
		</div>

		<div class="flex items-center gap-2">
			<Button size="xs" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</Button>
			<Button size="xs" color="alternative" onclick={test} disabled={testing || !status?.configured}>
				{testing ? 'Testing…' : 'Test connection'}
			</Button>
			{#if status?.configured}
				<Button size="xs" color="alternative" onclick={clearCredentials}>Clear</Button>
			{/if}
		</div>

		{#if testResult}
			<p class="text-xs {testResult.ok ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}">
				{testResult.ok ? 'Connection OK' : testResult.message}
			</p>
		{/if}
		{#if error}
			<p class="text-xs text-red-600 dark:text-red-400">{error}</p>
		{/if}
	{/if}
</div>
