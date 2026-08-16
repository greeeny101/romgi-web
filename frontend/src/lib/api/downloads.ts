import { apiDelete, apiGet, apiPost } from './client';

export type DownloadStatus = 'pending' | 'downloading' | 'paused' | 'extracting' | 'completed' | 'failed';

export interface DownloadTask {
	id: number;
	slug: string;
	title: string;
	platform_id: string;
	status: DownloadStatus;
	progress: number;
	downloaded_bytes: number;
	total_bytes: number;
	bytes_per_second: number;
	link_name: string;
	link_host: string;
	link_is_torrent: boolean;
	error: string;
	group_key: string;
	group_title: string;
	group_index: number | null;
	playlist_file: string;
	retry_count: number;
	created_at: string;
	completed_at: string | null;
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

export interface VerifyResult {
	exists: boolean;
	message: string | null;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8001/api';

export const downloadsApi = {
	list: (status?: DownloadStatus) => apiGet<DownloadTask[]>(status ? `/downloads?status=${status}` : '/downloads'),
	get: (id: number) => apiGet<DownloadTask>(`/downloads/${id}`),
	enqueue: (payload: EnqueuePayload) => apiPost<DownloadTask>('/downloads', payload),
	pause: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/pause`),
	resume: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/resume`),
	retry: (id: number) => apiPost<DownloadTask>(`/downloads/${id}/retry`),
	cancel: (id: number) => apiDelete<void>(`/downloads/${id}`),
	verify: (id: number) => apiPost<VerifyResult>(`/downloads/${id}/verify`),
	fileUrl: (id: number) => `${API_BASE_URL}/downloads/${id}/file`
};
