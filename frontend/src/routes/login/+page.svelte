<script lang="ts">
	import { goto } from '$app/navigation';
	import { Button, Input, Label } from 'flowbite-svelte';
	import { session } from '$lib/stores/session';
	import { ApiError } from '$lib/api/client';
	import ErrorView from '$lib/components/common/ErrorView.svelte';

	let mode = $state<'login' | 'register'>('login');
	let email = $state('');
	let password = $state('');
	let error = $state<string | null>(null);
	let submitting = $state(false);

	async function submit(e: Event) {
		e.preventDefault();
		error = null;
		submitting = true;
		try {
			if (mode === 'login') {
				await session.login(email, password);
			} else {
				await session.register(email, password);
			}
			await goto('/');
		} catch (err) {
			error =
				err instanceof ApiError
					? err.message
					: 'Something went wrong. Please try again.';
		} finally {
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>{mode === 'login' ? 'Log in' : 'Sign up'} — romgi</title>
</svelte:head>

<div class="mx-auto flex max-w-sm flex-col gap-4 py-16">
	<h1 class="text-center text-2xl font-semibold text-gray-900 dark:text-white">romgi</h1>

	{#if error}
		<ErrorView message={error} />
	{/if}

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
				minlength={8}
				autocomplete={mode === 'login' ? 'current-password' : 'new-password'}
			/>
		</div>
		<Button type="submit" disabled={submitting}>
			{submitting ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}
		</Button>
	</form>

	<button
		type="button"
		class="text-center text-sm text-primary-600 hover:underline dark:text-primary-400"
		onclick={() => (mode = mode === 'login' ? 'register' : 'login')}
	>
		{mode === 'login' ? "Don't have an account? Sign up" : 'Already have an account? Log in'}
	</button>
</div>
