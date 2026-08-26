<script lang="ts">
	import CredentialForm from '$lib/components/credentials/CredentialForm.svelte';

	// Field lists come from the backend now (GET /credentials/{kind}/{id}) so
	// they can't disagree with what each provider actually requires.
	const screenScraperHint =
		"ScreenScraper's API authenticates on a developer ID and password — a personal " +
		'account alone will not connect. Request developer access on the ScreenScraper ' +
		'forum, then add your own account below to raise the request quota.';
</script>

<svelte:head>
	<title>Game metadata — romgi</title>
</svelte:head>

<div class="mx-auto flex max-w-sm flex-col gap-4">
	<a href="/settings" class="text-sm text-primary-600 hover:underline dark:text-primary-400">&larr; Back to Settings</a>
	<h1 class="text-xl font-semibold text-gray-900 dark:text-white">Game metadata</h1>

	<p class="text-sm text-gray-500 dark:text-gray-400">
		These accounts supply the descriptions, screenshots and artwork shown on entry pages. Each one
		saves on its own — the toggle for showing metadata lives back on Settings.
	</p>

	<CredentialForm
		kind="metadata"
		providerId="screenscraper"
		providerName="ScreenScraper"
		hint={screenScraperHint}
	/>
	<CredentialForm kind="metadata" providerId="steamgriddb" providerName="SteamGridDB" />
</div>
