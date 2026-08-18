<script lang="ts">
	import usFlag from '$lib/assets/flags/us.svg';
	import euFlag from '$lib/assets/flags/eu.svg';
	import jpFlag from '$lib/assets/flags/jp.svg';
	import otherFlag from '$lib/assets/flags/other.svg';

	// Closed set — seeded by catalog migration 0002 and FK-constrained, so these four ids
	// are the only ones that can reach us. Anything else is dropped, not guessed at.
	const FLAGS: Record<string, { src: string; label: string }> = {
		us: { src: usFlag, label: 'USA' },
		eu: { src: euFlag, label: 'Europe' },
		jp: { src: jpFlag, label: 'Japan' },
		other: { src: otherFlag, label: 'Other region' }
	};
	const ORDER = ['us', 'eu', 'jp', 'other'];

	let { regions = [], size = 'h-4 w-4' }: { regions?: string[]; size?: string } = $props();

	// The regions M2M comes back unordered; sort so an entry always looks the same.
	let shown = $derived(
		[...new Set(regions)]
			.filter((region) => region in FLAGS)
			.sort((a, b) => ORDER.indexOf(a) - ORDER.indexOf(b))
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
