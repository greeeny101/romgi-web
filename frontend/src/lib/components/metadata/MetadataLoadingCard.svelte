<script lang="ts">
	import { Spinner } from 'flowbite-svelte';

	// Deliberately the same shell as MetadataCard — same border, padding, gap
	// and "About" heading — so the real card replaces this in place instead of
	// the page jumping when it lands. The bars below stand in for the
	// description and the thumbnail strip at the sizes those actually render
	// at (h-32 w-48 matches MetadataCard's images).
	const DESCRIPTION_BARS = ['w-full', 'w-11/12', 'w-4/6'];
	// Array.from, not Array(n): a sparse array is a quiet way to render nothing.
	const THUMBNAILS = Array.from({ length: 4 }, (_, i) => i);
</script>

<div
	class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700"
	role="status"
	aria-live="polite"
>
	<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">About</h2>

	<div class="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
		<Spinner size="4" />
		<span>Fetching description and artwork&hellip;</span>
	</div>

	<!-- Purely decorative: the sentence above is what gets announced, and
	     reading out a row of empty placeholders would just be noise. -->
	<div class="flex flex-col gap-2" aria-hidden="true">
		{#each DESCRIPTION_BARS as width (width)}
			<div class="h-3 {width} animate-pulse rounded bg-gray-200 dark:bg-gray-700"></div>
		{/each}
	</div>

	<div class="flex gap-2 overflow-hidden pb-1" aria-hidden="true">
		{#each THUMBNAILS as i (i)}
			<div class="h-32 w-48 shrink-0 animate-pulse rounded-md bg-gray-100 dark:bg-gray-800"></div>
		{/each}
	</div>
</div>
