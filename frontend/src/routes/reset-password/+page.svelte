<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Alert, Button } from 'flowbite-svelte';
	import { authApi } from '$lib/api/auth';
	import { ApiError } from '$lib/api/client';
	import { session } from '$lib/stores/session';
	import AuthCard from '$lib/components/auth/AuthCard.svelte';
	import PasswordField from '$lib/components/auth/PasswordField.svelte';

	const uid = page.url.searchParams.get('uid') ?? '';
	const token = page.url.searchParams.get('token') ?? '';
	const hasLink = uid !== '' && token !== '';

	let password = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			// Confirming returns a fresh token pair, so the user lands logged in
			// rather than being bounced to the login form they just came from.
			const tokens = await authApi.confirmPasswordReset(uid, token, password);
			await session.adopt(tokens);
			await goto('/');
		} catch (err) {
			error =
				err instanceof ApiError ? err.message : 'Something went wrong. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Choose a new password — romgi</title>
</svelte:head>

<AuthCard
	title="Choose a new password"
	subtitle="This will sign you out everywhere else."
	{error}
>
	{#if hasLink}
		<form class="flex flex-col gap-4" onsubmit={submit}>
			<PasswordField bind:value={password} label="New password" />
			<Button type="submit" disabled={submitting}>
				{submitting ? 'Please wait…' : 'Set new password'}
			</Button>
		</form>
	{:else}
		<Alert color="red">
			This reset link is incomplete. Open the link from your email exactly as it was sent.
		</Alert>
	{/if}

	<a
		href="/login"
		class="text-center text-sm text-primary-600 hover:underline dark:text-primary-400"
	>
		Back to log in
	</a>
</AuthCard>
