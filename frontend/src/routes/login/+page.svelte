<script lang="ts">
	import { goto } from '$app/navigation';
	import { Button, Input, Label } from 'flowbite-svelte';
	import { session } from '$lib/stores/session';
	import { ApiError } from '$lib/api/client';
	import AuthCard from '$lib/components/auth/AuthCard.svelte';

	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			await session.login(email, password);
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
	<title>Log in — romgi</title>
</svelte:head>

<AuthCard title="Log in" {error}>
	<form class="flex flex-col gap-4" onsubmit={submit}>
		<div>
			<Label for="email" class="mb-1">Email</Label>
			<Input id="email" type="email" bind:value={email} required autocomplete="email" />
		</div>
		<div>
			<Label for="password" class="mb-1">Password</Label>
			<Input
				id="password"
				type="password"
				bind:value={password}
				required
				autocomplete="current-password"
			/>
		</div>
		<Button type="submit" disabled={submitting}>
			{submitting ? 'Please wait…' : 'Log in'}
		</Button>
	</form>

	<div class="flex flex-col gap-2 text-center text-sm">
		<a href="/forgot-password" class="text-primary-600 hover:underline dark:text-primary-400">
			Forgot your password?
		</a>
		<!-- There is no signup link on purpose: accounts exist only by invite,
		     so offering one would just lead everybody to a dead end. -->
		<p class="text-gray-500 dark:text-gray-400">
			Registration is invite-only. Ask an administrator for an invite link.
		</p>
	</div>
</AuthCard>
