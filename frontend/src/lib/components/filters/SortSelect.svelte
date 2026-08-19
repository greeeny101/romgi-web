<script lang="ts">
	import { Select } from 'flowbite-svelte';
	import { SortOutline } from 'flowbite-svelte-icons';

	export type SortDirection = 'asc' | 'desc';
	export interface SortOption {
		value: string;
		name: string;
	}

	// Deliberately generic — it knows nothing about downloads, so the
	// /downloads queue page can adopt it later by passing its own options.
	let {
		options,
		key = $bindable(''),
		direction = $bindable<SortDirection>('asc')
	}: {
		options: SortOption[];
		key?: string;
		direction?: SortDirection;
	} = $props();

	let items = $derived(options.map((o) => ({ value: o.value, name: o.name })));
	let label = $derived(direction === 'asc' ? 'Sort ascending' : 'Sort descending');
</script>

<div class="flex items-center gap-2">
	<!-- No placeholder: sorting always has an answer, so an empty "no sort"
	     option would only ever produce an arbitrary order. -->
	<Select {items} bind:value={key} placeholder="" class="w-48" />
	<button
		type="button"
		class="rounded-lg border border-gray-300 p-2 text-gray-500 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-700"
		title={label}
		aria-label={label}
		onclick={() => (direction = direction === 'asc' ? 'desc' : 'asc')}
	>
		<SortOutline class="h-4 w-4 {direction === 'desc' ? 'rotate-180' : ''}" />
	</button>
</div>
