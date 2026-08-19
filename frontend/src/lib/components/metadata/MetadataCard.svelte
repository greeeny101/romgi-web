<script lang="ts">
	import type { GameMetadata } from '$lib/api/metadata';

	let { metadata }: { metadata: GameMetadata } = $props();

	let expanded = $state(false);
	let media = $derived([...metadata.screenshots, ...metadata.artwork]);
	let isLong = $derived((metadata.description?.length ?? 0) > 300);
</script>

<div class="flex flex-col gap-3 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
	<h2 class="text-sm font-semibold tracking-wide text-gray-500 uppercase dark:text-gray-400">About</h2>

	{#if metadata.description}
		<p class="text-sm text-gray-700 dark:text-gray-300">
			{isLong && !expanded ? metadata.description.slice(0, 300) + '…' : metadata.description}
		</p>
		{#if isLong}
			<button
				type="button"
				class="self-start text-xs text-primary-600 hover:underline dark:text-primary-400"
				onclick={() => (expanded = !expanded)}
			>
				{expanded ? 'Show less' : 'Read more'}
			</button>
		{/if}
	{/if}

	{#if media.length > 0}
		<div class="flex gap-2 overflow-x-auto pb-1">
			{#each media as item (item.full)}
				<a href={item.full} target="_blank" rel="noopener" class="shrink-0">
					<!-- Reserving a box keeps the strip from reflowing as each
					     thumbnail lands, which also lets the browser defer the
					     ones scrolled off to the right. -->
					<img
						src={item.thumb}
						alt=""
						loading="lazy"
						decoding="async"
						class="h-32 w-48 rounded-md bg-gray-100 object-cover dark:bg-gray-800"
					/>
				</a>
			{/each}
		</div>
	{/if}
</div>
