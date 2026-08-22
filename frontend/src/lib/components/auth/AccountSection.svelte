<script lang="ts">
	import { Alert, Button, Input, Label, Spinner } from 'flowbite-svelte';
	import { authApi, type Session } from '$lib/api/auth';
	import { ApiError } from '$lib/api/client';
	import { session as sessionStore } from '$lib/stores/session';
	import PasswordField from './PasswordField.svelte';

	// This section commits immediately rather than joining the page's batched
	// "Save changes" — changing a password or revoking a device is not something
	// to leave sitting in an unsaved form.

	let currentPassword = $state('');
	let newPassword = $state('');
	let changing = $state(false);
	let changeError = $state<string | null>(null);
	let changed = $state(false);

	let sessions = $state<Session[]>([]);
	let loadingSessions = $state(true);
	let sessionError = $state<string | null>(null);
	let busySessionId = $state<number | null>(null);

	async function loadSessions() {
		loadingSessions = true;
		sessionError = null;
		try {
			sessions = await authApi.sessions();
		} catch (err) {
			sessionError = err instanceof ApiError ? err.message : 'Failed to load sessions.';
		} finally {
			loadingSessions = false;
		}
	}

	$effect(() => {
		loadSessions();
	});

	async function changePassword(e: Event) {
		e.preventDefault();
		changing = true;
		changed = false;
		changeError = null;
		try {
			// Changing the password revokes every session including this one, so
			// the response carries a replacement pair to keep this tab working.
			const tokens = await authApi.changePassword(currentPassword, newPassword);
			await sessionStore.adopt(tokens);
			currentPassword = '';
			newPassword = '';
			changed = true;
			await loadSessions();
		} catch (err) {
			changeError = err instanceof ApiError ? err.message : 'Failed to change password.';
		} finally {
			changing = false;
		}
	}

	async function revoke(id: number) {
		busySessionId = id;
		sessionError = null;
		try {
			await authApi.revokeSession(id);
			await loadSessions();
		} catch (err) {
			sessionError = err instanceof ApiError ? err.message : 'Failed to revoke session.';
		} finally {
			busySessionId = null;
		}
	}

	async function revokeOthers() {
		sessionError = null;
		try {
			await authApi.revokeOtherSessions();
			await loadSessions();
		} catch (err) {
			sessionError = err instanceof ApiError ? err.message : 'Failed to revoke sessions.';
		}
	}

	function describe(s: Session): string {
		const ua = s.user_agent || 'Unknown device';
		// Full UA strings are unreadable in a list; the leading product token is
		// enough to tell one device from another.
		const short = ua.length > 60 ? `${ua.slice(0, 60)}…` : ua;
		return s.ip_address ? `${short} · ${s.ip_address}` : short;
	}

	const otherSessionCount = $derived(sessions.filter((s) => !s.current).length);
</script>

<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">
	Account
</h2>

<form class="flex flex-col gap-4" onsubmit={changePassword}>
	{#if changeError}
		<Alert color="red">{changeError}</Alert>
	{:else if changed}
		<Alert color="green">Password changed. Other devices have been signed out.</Alert>
	{/if}
	<div>
		<Label for="current-password" class="mb-1">Current password</Label>
		<Input
			id="current-password"
			type="password"
			bind:value={currentPassword}
			required
			autocomplete="current-password"
		/>
	</div>
	<PasswordField bind:value={newPassword} id="new-password" label="New password" />
	<Button type="submit" size="sm" disabled={changing}>
		{changing ? 'Changing…' : 'Change password'}
	</Button>
</form>

<div class="flex flex-col gap-2">
	<div class="flex items-center justify-between">
		<span class="text-sm font-medium text-gray-700 dark:text-gray-300">Active sessions</span>
		{#if otherSessionCount > 0}
			<Button size="xs" color="alternative" onclick={revokeOthers}>Sign out everywhere else</Button>
		{/if}
	</div>

	{#if sessionError}
		<Alert color="red">{sessionError}</Alert>
	{/if}

	{#if loadingSessions}
		<div class="flex justify-center py-4"><Spinner size="6" /></div>
	{:else}
		<ul class="divide-y divide-gray-200 dark:divide-gray-700">
			{#each sessions as s (s.id)}
				<li class="flex items-center justify-between gap-4 py-2">
					<div class="min-w-0">
						<p class="truncate text-sm text-gray-700 dark:text-gray-300">{describe(s)}</p>
						<p class="text-xs text-gray-500 dark:text-gray-400">
							Last used {new Date(s.last_used_at).toLocaleString()}
							{#if s.current}
								· <span class="text-green-600 dark:text-green-400">this device</span>
							{/if}
						</p>
					</div>
					{#if !s.current}
						<Button
							size="xs"
							color="red"
							disabled={busySessionId === s.id}
							onclick={() => revoke(s.id)}
						>
							Revoke
						</Button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>
