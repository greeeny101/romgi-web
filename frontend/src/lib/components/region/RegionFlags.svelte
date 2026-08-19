<script lang="ts">
	import usFlag from '$lib/assets/flags/us.svg';
	import euFlag from '$lib/assets/flags/eu.svg';
	import ukFlag from '$lib/assets/flags/uk.svg';
	import deFlag from '$lib/assets/flags/de.svg';
	import frFlag from '$lib/assets/flags/fr.svg';
	import auFlag from '$lib/assets/flags/au.svg';
	import jpFlag from '$lib/assets/flags/jp.svg';
	import worldFlag from '$lib/assets/flags/world.svg';
	import otherFlag from '$lib/assets/flags/other.svg';
	import { REGION_ORDER } from '$lib/regions';

	// Closed set — seeded by catalog migrations 0002/0004 and FK-constrained, so these
	// ids are the only ones that can reach us. Anything else is dropped, not guessed at.
	const FLAGS: Record<string, { src: string; label: string }> = {
		world: { src: worldFlag, label: 'World' },
		us: { src: usFlag, label: 'USA' },
		eu: { src: euFlag, label: 'Europe' },
		uk: { src: ukFlag, label: 'United Kingdom' },
		de: { src: deFlag, label: 'Germany' },
		fr: { src: frFlag, label: 'France' },
		au: { src: auFlag, label: 'Australia' },
		jp: { src: jpFlag, label: 'Japan' },
		other: { src: otherFlag, label: 'Other region' }
	};

	let { regions = [], size = 'h-4 w-4' }: { regions?: string[]; size?: string } = $props();

	// The regions M2M comes back unordered; sort so an entry always looks the same.
	let shown = $derived(
		[...new Set(regions)]
			.filter((region) => region in FLAGS)
			.sort((a, b) => REGION_ORDER.indexOf(a) - REGION_ORDER.indexOf(b))
	);
</script>

{#if shown.length}
	<span class="flex shrink-0 items-center gap-0.5">
		{#each shown as region (region)}
			<img
				src={FLAGS[region].src}
				alt={FLAGS[region].label}
				title={FLAGS[region].label}
				class={size}
			/>
		{/each}
	</span>
{/if}
