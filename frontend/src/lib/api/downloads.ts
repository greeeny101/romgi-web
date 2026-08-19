import { apiDelete, apiDownload, apiGet, apiPost } from './client';

export type DownloadStatus =
	| 'pending'
	| 'downloading'
	| 'paused'
	| 'extracting'
	// Collapsing an extracted CD rip into a single .chd — see backend chd.py.
	| 'converting'
	| 'completed'
	| 'failed';

export interface DownloadTask {
	id: number;
	slug: string;
	title: string;
	platform_id: string;
	platform_name: string;
	status: DownloadStatus;
	progress: number;
	downloaded_bytes: number;
	total_bytes: number;
	bytes_per_second: number;
	link_name: string;
	link_host: string;
	link_is_torrent: boolean;
	source_id: string | null;
	source_name: string | null;
	// Snapshotted from the entry at enqueue — ids only, resolved to names
	// against catalogApi.regions().
	region_ids: string[];
	error: string;
	group_key: string;
	group_title: string;
	group_index: number | null;
	playlist_file: string;
	retry_count: number;
	created_at: string;
	completed_at: string | null;
	// Whether the staged bytes are still on the server, and when they go. A
	// completed task outlives its file (STAGED_FILE_RETENTION_HOURS), so
	// `status === 'completed'` alone doesn't mean Save file will work.
	file_available: boolean;
	expires_at: string | null;
	// Size of the file as it will actually be saved. Not total_bytes: that is
	// what the transfer moved, and a CD rip collapsed into a .chd is far
	// smaller than the tracks it came from.
	file_size: number | null;
	// When you first saved the bytes to your own machine. completed_at means
	// the server has it; this means you do.
	first_retrieved_at: string | null;
	// Torrent-only, live-only — present in WS progress updates while
	// downloading, never persisted (see downloads.progress.push_progress).
	num_seeds?: number;
	num_peers?: number;
}

export interface EnqueuePayload {
	slug: string;
	link_id?: number;
	group_id?: number;
}

export const downloadsApi = {
	list: (status?: DownloadStatus) => apiGet<DownloadTask[]>(status ? `/downloads?status=${status}` : '/downloads'),
	get: (id: number) => apiGet<DownloadTask>(`/downloads/${id}`),
	enqueue: (payload: EnqueuePayload) => apiPost<DownloadTask>('/downloads', payload),
	pause: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/pause`),
	resume: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/resume`),
	retry: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/retry`),
	cancel: (id: number) => apiDelete<void>(`/downloads/${id}`),
	file: (id: number) => apiDownload(`/downloads/${id}/file`)
};
