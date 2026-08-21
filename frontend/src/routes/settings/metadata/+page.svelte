<script lang="ts">
	import CredentialForm from '$lib/components/credentials/CredentialForm.svelte';

	// Field lists come from the backend now (GET /credentials/{kind}/{id}) so
	// they can't disagree with what each provider actually requires.
	// The developer credentials ScreenScraper's API authenticates on belong to
	// this romgi server, not to you — they're set once by whoever runs it. A
	// personal account is separate and only affects your quota.
	const screenScraperHint =
		'Your own free ScreenScraper account. It is not what authenticates the API — ' +
		'that is a developer credential the server administrator configures — so this ' +
		'only raises the request quota and thread limit used when scraping for you.';
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
