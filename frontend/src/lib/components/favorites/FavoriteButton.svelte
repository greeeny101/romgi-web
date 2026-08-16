<script lang="ts">
	import { HeartOutline, HeartSolid } from 'flowbite-svelte-icons';
	import { favorites } from '$lib/stores/favorites';

	let { slug, size = 'sm' }: { slug: string; size?: 'sm' | 'md' } = $props();

	let isFavorited = $derived($favorites.has(slug));
	let pending = $state(false);
	let dimension = $derived(size === 'sm' ? 'h-4 w-4' : 'h-5 w-5');

	async function toggle(e: MouseEvent) {
		e.preventDefault();
		e.stopPropagation();
		if (pending) return;
		pending = true;
		try {
			await favorites.toggle(slug);
		} finally {
			pending = false;
		}
	}
</script>

<button
	type="button"
	onclick={toggle}
	disabled={pending}
	class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow transition hover:bg-white disabled:opacity-50 dark:bg-gray-800/80 dark:hover:bg-gray-800"
	aria-label={isFavorited ? 'Remove from wishlist' : 'Add to wishlist'}
	title={isFavorited ? 'Remove from wishlist' : 'Add to wishlist'}
>
	{#if isFavorited}
		<HeartSolid class="{dimension} text-red-500" />
	{:else}
		<HeartOutline class="{dimension} text-gray-500 dark:text-gray-300" />
	{/if}
</button>
