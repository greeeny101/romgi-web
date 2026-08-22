<script lang="ts">
	import { Input, Label } from 'flowbite-svelte';

	let {
		value = $bindable(),
		id = 'password',
		label = 'Password',
		autocomplete = 'new-password',
		showHint = true
	}: {
		value: string;
		id?: string;
		label?: string;
		autocomplete?: 'new-password' | 'current-password';
		showHint?: boolean;
	} = $props();

	/**
	 * A hint, not a gate. The real policy is AUTH_PASSWORD_VALIDATORS on the
	 * server (see apps/accounts/services/passwords.py) — this only tells the
	 * user what it's about to check so a rejection isn't the first feedback.
	 */
	const rules = $derived([
		{ label: 'At least 8 characters', met: value.length >= 8 },
		{ label: 'Not entirely numbers', met: value.length > 0 && !/^\d+$/.test(value) },
		{ label: "Not a password everyone's tried", met: value.length >= 10 }
	]);
</script>

<div>
	<Label for={id} class="mb-1">{label}</Label>
	<Input {id} type="password" bind:value required minlength={8} {autocomplete} />
	{#if showHint && value.length > 0}
		<ul class="mt-2 space-y-0.5 text-xs">
			{#each rules as rule (rule.label)}
				<li class={rule.met ? 'text-green-600 dark:text-green-400' : 'text-gray-500 dark:text-gray-400'}>
					{rule.met ? '✓' : '·'}
					{rule.label}
				</li>
			{/each}
		</ul>
	{/if}
</div>
