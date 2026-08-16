<script lang="ts">
	import { Button } from 'flowbite-svelte';
	import { ChevronLeftOutline, ChevronRightOutline } from 'flowbite-svelte-icons';

	let {
		page,
		pageSize,
		total,
		onChange
	}: { page: number; pageSize: number; total: number; onChange: (page: number) => void } = $props();

	let totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
</script>

{#if totalPages > 1}
	<div class="flex items-center justify-center gap-3 py-4">
		<Button
			size="sm"
			color="alternative"
			disabled={page <= 1}
			onclick={() => onChange(page - 1)}
			aria-label="Previous page"
		>
			<ChevronLeftOutline class="h-4 w-4" />
		</Button>
		<span class="text-sm text-gray-600 dark:text-gray-300">Page {page} of {totalPages}</span>
		<Button
			size="sm"
			color="alternative"
			disabled={page >= totalPages}
			onclick={() => onChange(page + 1)}
			aria-label="Next page"
		>
			<ChevronRightOutline class="h-4 w-4" />
		</Button>
	</div>
{/if}
