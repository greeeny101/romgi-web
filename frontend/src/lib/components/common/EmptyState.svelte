<script lang="ts">
	import { FileSearchOutline } from 'flowbite-svelte-icons';

	let { title, description }: { title: string; description?: string } = $props();
</script>

<div class="flex flex-col items-center justify-center gap-2 py-16 text-center text-gray-500 dark:text-gray-400">
	<FileSearchOutline class="h-10 w-10" />
	<p class="text-sm font-medium">{title}</p>
	{#if description}
		<p class="text-xs">{description}</p>
	{/if}
</div>
