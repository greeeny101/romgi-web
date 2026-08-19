import type { DownloadStatus } from '$lib/api/downloads';

export type StatusColor = 'gray' | 'blue' | 'yellow' | 'purple' | 'green' | 'red';

/** Shared by the queue row's status badge and the downloads filter pills so
 *  the two can't drift apart. */
export const statusColor: Record<DownloadStatus, StatusColor> = {
	pending: 'gray',
	downloading: 'blue',
	paused: 'yellow',
	extracting: 'purple',
	converting: 'purple',
	completed: 'green',
	failed: 'red'
};

/** Queue order. Pills render all seven in this order regardless of which are
 *  currently present, so the row doesn't reflow as downloads change state. */
export const statusOrder: DownloadStatus[] = [
	'pending',
	'downloading',
	'paused',
	'extracting',
	'converting',
	'completed',
	'failed'
];
