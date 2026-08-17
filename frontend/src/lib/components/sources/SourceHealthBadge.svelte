<script lang="ts">
	import { Badge, Spinner } from 'flowbite-svelte';
	import type { SourceHealth } from '$lib/api/catalog';

	let { status }: { status: SourceHealth['status'] } = $props();

	const colors: Record<SourceHealth['status'], 'green' | 'red' | 'gray' | 'yellow'> = {
		ok: 'green',
		error: 'red',
		unknown: 'gray',
		running: 'yellow'
	};
</script>

<Badge color={colors[status]}>
	{#if status === 'running'}<Spinner size="4" class="me-1 inline" />{/if}
	{status}
</Badge>
