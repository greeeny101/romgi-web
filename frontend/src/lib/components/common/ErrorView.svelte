<script lang="ts">
	import { Alert, Button } from 'flowbite-svelte';

	let { message, onRetry }: { message: string; onRetry?: () => void } = $props();
</script>

<Alert color="red" class="flex items-center justify-between gap-4">
	<span>{message}</span>
	{#if onRetry}
		<Button size="xs" color="alternative" onclick={onRetry}>Retry</Button>
	{/if}
</Alert>
