<script lang="ts">
	import { Badge } from 'flowbite-svelte';
	import type { SourceHealth } from '$lib/api/catalog';

	let { status }: { status: SourceHealth['status'] } = $props();

	const colors: Record<SourceHealth['status'], 'green' | 'red' | 'gray'> = {
		ok: 'green',
		error: 'red',
		unknown: 'gray'
	};
</script>

<Badge color={colors[status]}>{status}</Badge>
