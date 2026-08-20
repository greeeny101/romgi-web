<script lang="ts">
	import {
		CloseCircleSolid,
		DownloadSolid,
		ExclamationCircleSolid,
		FloppyDiskSolid
	} from 'flowbite-svelte-icons';
	import { downloads } from '$lib/stores/downloads';
	import type { DownloadStatus, DownloadTask } from '$lib/api/downloads';
	import { formatDateTime } from '$lib/format';

	// Two ways in. Browse's cards have only a slug and look the task up in the
	// store; the Library's Downloaded rows already hold the task, so they pass
	// completedAt directly and skip a scan of every task the user has.
	//
	// The slug path shows the whole life of a download in one 16px slot —
	// in-flight ring, then the green arrow, then a warning once the staged file
	// expires unsaved, or a red cross if the transfer never made it. The
	// completedAt path is the Library's pill and only ever means "finished";
	// the Library says the rest in words next to it.
	let {
		slug,
		platformId,
		completedAt,
		size = 'sm',
		variant = 'icon'
	}: {
		slug?: string;
		platformId?: string;
		completedAt?: string | null;
		size?: 'sm' | 'md';
		variant?: 'icon' | 'pill';
	} = $props();

	// Statuses where bytes are still moving. `paused` is deliberately not one of
	// them: it gets the same ring frozen, so a paused download doesn't sit there
	// spinning as if it were making progress.
	const ACTIVE: DownloadStatus[] = ['pending', 'downloading', 'extracting', 'converting'];

	const ACTIVE_LABEL: Record<string, string> = {
		pending: 'Queued for download',
		downloading: 'Downloading',
		extracting: 'Extracting',
		converting: 'Converting to CHD'
	};

	// Slugs are built as `<title>-<platform>-<regions>` (create_slug in the
	// ingestion pipeline) and are unique per catalog build, so a different
	// platform or region release of the same game is a different slug and
	// never borrows this badge. platform_id is matched as well because a
	// DownloadTask outlives the build it was enqueued from — if a rebuild
	// ever changed how slugs are derived, a stale task shouldn't be able to
	// light up an unrelated entry.
	//
	// enqueue keeps one task per slug, but a retry or a group enqueue can leave
	// more than one in the list briefly, so pick deliberately: whatever is
	// happening now outranks whatever happened last, and a download that did
	// land outranks one that didn't — a slug with both a completed task and a
	// failed one is a slug the user has the bytes for.
	let matched = $derived.by((): DownloadTask | null => {
		if (!slug) return null;
		const mine = $downloads.filter((t) => t.slug === slug && t.platform_id === platformId);
		return (
			mine.find((t) => ACTIVE.includes(t.status)) ??
			mine.find((t) => t.status === 'paused') ??
			mine.find((t) => t.status === 'completed') ??
			mine.find((t) => t.status === 'failed') ??
			null
		);
	});

	let completed = $derived(matched?.status === 'completed' ? matched : null);
	let when = $derived(completedAt ?? completed?.completed_at ?? null);
	let isDownloaded = $derived(completedAt !== undefined ? Boolean(when) : completed !== null);
	let stamp = $derived(when ? formatDateTime(when) : null);
	let downloadedTitle = $derived(stamp ? `Downloaded ${stamp}` : 'Already downloaded');
	let dimension = $derived(size === 'sm' ? 'h-4 w-4' : 'h-5 w-5');

	let savedAt = $derived(matched?.last_retrieved_at ?? null);

	// Staged files are reaped after STAGED_FILE_RETENTION_HOURS, so a completed
	// task can outlive its bytes. file_available is the server's answer and is
	// authoritative; expires_at only covers the window between the deadline
	// passing and the next payload arriving. Evaluated whenever the store
	// pushes an update rather than on a timer — a badge that flips to the
	// warning a few minutes late costs nothing, and the Save button already
	// refuses on its own.
	let expired = $derived(
		!!completed && !savedAt && (!completed.file_available || isPast(completed.expires_at))
	);

	function isPast(iso: string | null): boolean {
		if (!iso) return false;
		return new Date(iso).getTime() <= Date.now();
	}

	let state = $derived.by(() => {
		if (!matched) return 'none';
		if (ACTIVE.includes(matched.status)) return 'active';
		if (matched.status === 'paused') return 'paused';
		if (matched.status === 'completed') return expired ? 'expired' : 'downloaded';
		if (matched.status === 'failed') return 'failed';
		return 'none';
	});

	let percent = $derived(Math.round((matched?.progress ?? 0) * 100));

	// A ring rather than a spinner: the store already knows how far along the
	// transfer is, so the badge may as well say. r=9 in a 24-box leaves room for
	// the 3-wide stroke without clipping.
	const RING = 2 * Math.PI * 9;
	// pending has no bytes yet, and extract/convert report none either, so those
	// spin a fixed quarter-arc instead of showing a permanently empty circle.
	let indeterminate = $derived(state === 'active' && (matched?.status !== 'downloading' || percent === 0));

	let progressTitle = $derived.by(() => {
		if (!matched) return '';
		if (matched.status === 'paused') return `Download paused at ${percent}%`;
		const label = ACTIVE_LABEL[matched.status] ?? 'Downloading';
		return matched.status === 'downloading' ? `${label}… ${percent}%` : `${label}…`;
	});

	const expiredTitle =
		'This download expired before you saved it — download it again to get the file';
	// The task's `error` is the backend's own message and can be a stack-trace
	// tail, so it's a tooltip rather than anything the tile lays out; the
	// downloads queue is where the user goes to read it and retry.
	let failedTitle = $derived(
		matched?.error ? `Download failed — ${matched.error}` : 'Download failed — try again'
	);
	let savedTitle = $derived(`You saved this file on ${savedAt ? formatDateTime(savedAt) : ''}`);
</script>

{#if variant === 'pill'}
	{#if isDownloaded}
		<span
			class="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700 dark:border-green-900 dark:bg-green-900/30 dark:text-green-300"
			title={downloadedTitle}
		>
			<DownloadSolid class="h-3.5 w-3.5" />
			Downloaded
			{#if stamp}
				<span class="font-normal text-green-600 dark:text-green-400">{stamp}</span>
			{/if}
		</span>
	{/if}
{:else}
	<!-- One slot, every state: the ring, the green arrow, the expiry warning
	     and the failure cross all land in the same place so the row doesn't
	     reflow as a download runs. -->
	{#if state === 'active' || state === 'paused'}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			title={progressTitle}
			role="img"
			aria-label={progressTitle}
		>
			<svg
				viewBox="0 0 24 24"
				class="{dimension} {indeterminate ? 'animate-spin' : '-rotate-90'}"
				fill="none"
				aria-hidden="true"
			>
				<circle
					cx="12"
					cy="12"
					r="9"
					stroke-width="3"
					class={state === 'paused'
						? 'stroke-amber-200 dark:stroke-amber-900'
						: 'stroke-blue-200 dark:stroke-blue-900'}
				/>
				<circle
					cx="12"
					cy="12"
					r="9"
					stroke-width="3"
					stroke-linecap="round"
					stroke-dasharray={indeterminate
						? `${RING * 0.25} ${RING}`
						: `${(RING * percent) / 100} ${RING}`}
					class="transition-[stroke-dasharray] duration-300 {state === 'paused'
						? 'stroke-amber-500 dark:stroke-amber-400'
						: 'stroke-blue-600 dark:stroke-blue-400'}"
				/>
			</svg>
		</span>
	{:else if state === 'expired'}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			title={expiredTitle}
			role="img"
			aria-label={expiredTitle}
		>
			<ExclamationCircleSolid class="{dimension} text-amber-500 dark:text-amber-400" />
		</span>
	{:else if state === 'failed'}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			title={failedTitle}
			role="img"
			aria-label={failedTitle}
		>
			<CloseCircleSolid class="{dimension} text-red-600 dark:text-red-400" />
		</span>
	{:else if state === 'downloaded'}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			title={downloadedTitle}
			role="img"
			aria-label={downloadedTitle}
		>
			<DownloadSolid class="{dimension} text-green-600 dark:text-green-400" />
		</span>
	{/if}

	<!-- Its own slot, next to the download state rather than instead of it:
	     "the server fetched it" and "I have a copy" are separate facts, and a
	     saved file stays saved after the staged copy expires. Matches the
	     blue floppy the Library's SavedLocallyBadge uses. -->
	{#if savedAt}
		<span
			class="flex items-center justify-center rounded-full bg-white/80 p-1.5 shadow dark:bg-gray-800/80"
			title={savedTitle}
			role="img"
			aria-label={savedTitle}
		>
			<FloppyDiskSolid class="{dimension} text-blue-600 dark:text-blue-400" />
		</span>
	{/if}
{/if}
