<script lang="ts">
	import { Select } from 'flowbite-svelte';
	import type { Platform, Region, Source } from '$lib/api/catalog';

	let {
		platforms,
		regions,
		sources,
		platform = $bindable(''),
		region = $bindable(''),
		source = $bindable('')
	}: {
		platforms: Platform[];
		regions: Region[];
		sources: Source[];
		platform?: string;
		region?: string;
		source?: string;
	} = $props();

	let platformItems = $derived(
		platforms.map((p) => ({ value: p.id, name: `${p.brand} — ${p.name}` }))
	);
	let regionItems = $derived(regions.map((r) => ({ value: r.id, name: r.name })));
	let sourceItems = $derived(sources.map((s) => ({ value: s.id, name: s.name })));
</script>

<div class="grid grid-cols-1 gap-3 sm:grid-cols-3">
	<Select items={platformItems} bind:value={platform} placeholder="All platforms" />
	<Select items={regionItems} bind:value={region} placeholder="All regions" />
	<Select items={sourceItems} bind:value={source} placeholder="All sources" />
</div>
