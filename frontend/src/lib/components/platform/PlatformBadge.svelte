<script lang="ts">
	import { Badge } from 'flowbite-svelte';

	let { brand, name }: { brand?: string; name: string } = $props();
</script>

<Badge color="gray" class="whitespace-nowrap" title={brand ? `${brand} — ${name}` : name}>
	{name}
</Badge>
