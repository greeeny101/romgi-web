<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Search, Button } from 'flowbite-svelte';
	import type { Platform, Region, Source } from '$lib/api/catalog';
	import FilterPanel from './FilterPanel.svelte';

	let {
		placeholder = 'Search…',
		query = $bindable(''),
		platforms,
		regions,
		sources,
		platform = $bindable(''),
		region = $bindable(''),
		source = $bindable(''),
		extraActive = false,
		onClear,
		actions,
		secondary
	}: {
		placeholder?: string;
		query?: string;
		platforms: Platform[];
		regions: Region[];
		sources: Source[];
		platform?: string;
		region?: string;
		source?: string;
		/** Set when a filter this bar doesn't own is active, so "Clear
		 * filters" still shows. Pair it with `onClear` to reset that filter. */
		extraActive?: boolean;
		onClear?: () => void;
		/** Rendered to the right of the search box — Browse's view toggle. */
		actions?: Snippet;
		/** Rendered between the search row and the selects — Downloads' status pills. */
		secondary?: Snippet;
	} = $props();

	let hasFilters = $derived(Boolean(query || platform || region || source || extraActive));

	function clearFilters() {
		query = '';
		platform = '';
		region = '';
		source = '';
		onClear?.();
	}
</script>

<div class="flex flex-col gap-3 sm:flex-row sm:items-center">
	<div class="flex-1">
		<Search {placeholder} bind:value={query} clearable />
	</div>
	<div class="flex gap-1">
		{#if hasFilters}
			<Button size="sm" color="alternative" onclick={clearFilters}>Clear filters</Button>
		{/if}
		{@render actions?.()}
	</div>
</div>

{@render secondary?.()}

<FilterPanel {platforms} {regions} {sources} bind:platform bind:region bind:source />
