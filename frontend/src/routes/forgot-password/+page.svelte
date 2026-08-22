<script lang="ts">
	import { onMount } from 'svelte';
	import { Alert, Button, Input, Label } from 'flowbite-svelte';
	import { authApi } from '$lib/api/auth';
	import { ApiError } from '$lib/api/client';
	import AuthCard from '$lib/components/auth/AuthCard.svelte';

	let email = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);
	let sent = $state(false);
	// SMTP is optional for this app. When it isn't configured the request would
	// succeed and silently do nothing, so ask up front and say so instead.
	let emailEnabled = $state(true);

	onMount(async () => {
		try {
			emailEnabled = (await authApi.capabilities()).email_enabled;
		} catch {
			// Leave the optimistic default; the worst case is the generic
			// confirmation below, which is already deliberately vague.
		}
	});

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			await authApi.requestPasswordReset(email);
			sent = true;
		} catch (err) {
			error =
				err instanceof ApiError ? err.message : 'Something went wrong. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Reset your password — romgi</title>
</svelte:head>

<AuthCard title="Reset your password" {error}>
	{#if sent}
		<!-- Deliberately says nothing about whether the address is registered —
		     the endpoint answers the same way either way so it can't be used to
		     work out who has an account here. -->
		<Alert color="green">
			If that address has an account, a reset link is on its way. The link expires in 24 hours.
		</Alert>
		<a
			href="/login"
			class="text-center text-sm text-primary-600 hover:underline dark:text-primary-400"
		>
			Back to log in
		</a>
	{:else}
		{#if !emailEnabled}
			<Alert color="yellow">
				This instance doesn't have email set up, so it can't send you a reset link. Ask an
				administrator to generate one for you.
			</Alert>
		{/if}
		<form class="flex flex-col gap-4" onsubmit={submit}>
			<div>
				<Label for="email" class="mb-1">Email</Label>
				<Input id="email" type="email" bind:value={email} required autocomplete="email" />
			</div>
			<Button type="submit" disabled={submitting || !emailEnabled}>
				{submitting ? 'Please wait…' : 'Send reset link'}
			</Button>
		</form>
		<a
			href="/login"
			class="text-center text-sm text-primary-600 hover:underline dark:text-primary-400"
		>
			Back to log in
		</a>
	{/if}
</AuthCard>
