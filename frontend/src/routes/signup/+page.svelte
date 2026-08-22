<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { Button, Input, Label } from 'flowbite-svelte';
	import { session } from '$lib/stores/session';
	import { ApiError } from '$lib/api/client';
	import AuthCard from '$lib/components/auth/AuthCard.svelte';
	import PasswordField from '$lib/components/auth/PasswordField.svelte';

	// Invites are normally opened as /signup?invite=<code>, but the field stays
	// editable so someone who was sent a bare code can paste it.
	let inviteCode = $state(page.url.searchParams.get('invite') ?? '');
	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			await session.register(email, password, inviteCode.trim());
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
	<title>Create your account — romgi</title>
</svelte:head>

<AuthCard title="Create your account" subtitle="You'll need an invite code to sign up." {error}>
	<form class="flex flex-col gap-4" onsubmit={submit}>
		<div>
			<Label for="invite" class="mb-1">Invite code</Label>
			<Input id="invite" type="text" bind:value={inviteCode} required autocomplete="off" />
		</div>
		<div>
			<Label for="email" class="mb-1">Email</Label>
			<Input id="email" type="email" bind:value={email} required autocomplete="email" />
		</div>
		<PasswordField bind:value={password} />
		<Button type="submit" disabled={submitting}>
			{submitting ? 'Please wait…' : 'Create account'}
		</Button>
	</form>

	<a
		href="/login"
		class="text-center text-sm text-primary-600 hover:underline dark:text-primary-400"
	>
		Already have an account? Log in
	</a>
</AuthCard>
