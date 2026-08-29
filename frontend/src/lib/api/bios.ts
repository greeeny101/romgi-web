import { apiDelete, apiGet, apiPost } from './client';

export interface BiosSource {
	id: string;
	name: string;
	platform_id: string | null;
}

export interface BiosSearchResult {
	identifier: string;
	title: string;
	size: number;
	downloads: number;
	published: string | null;
}

export interface BiosSearchResponse {
	items: BiosSearchResult[];
	total: number;
	page: number;
	page_size: number;
}

export interface BiosItemFile {
	name: string;
	size: number;
	format: string | null;
	md5: string | null;
}

export interface BiosItemDetail {
	identifier: string;
	title: string;
	description: string;
	collections: string[];
	published: string | null;
	item_size: number;
	/** archive.org's login-gated `loggedin` collection. */
	restricted: boolean;
	/** The whole list — a BIOS item is tens of files, so nothing is capped. */
	files: BiosItemFile[];
	file_count: number;
	total_size: number;
}

export interface BiosDownloadFile {
	name: string;
	size: number;
	wanted: boolean;
	progress: number;
	done: boolean;
	error: string;
}

export interface BiosDownload {
	id: number;
	identifier: string;
	title: string;
	provider: string;
	platform_id: string | null;
	source_id: string;
	status: string;
	progress: number;
	downloaded_bytes: number;
	total_bytes: number;
	bytes_per_second: number;
	save_dir: string;
	extract: boolean;
	error: string;
	file_count: number;
	wanted_count: number;
	created_at: string;
	completed_at: string | null;
}

export interface BiosDownloadDetail extends BiosDownload {
	files: BiosDownloadFile[];
}

export interface EnqueueBiosPayload {
	identifier: string;
	platform_id?: string | null;
	source_id?: string;
	names?: string[];
	extract?: boolean;
}

export const biosApi = {
	sources: () => apiGet<BiosSource[]>('/bios/sources'),
	search: (source: string, q = '', page = 1) => {
		const params = new URLSearchParams({ source, page: String(page) });
		if (q) params.set('q', q);
		return apiGet<BiosSearchResponse>(`/bios/search?${params.toString()}`);
	},
	item: (identifier: string) =>
		apiGet<BiosItemDetail>(`/bios/items/${encodeURIComponent(identifier)}`),
	list: () => apiGet<BiosDownload[]>('/bios/downloads'),
	get: (id: number) => apiGet<BiosDownloadDetail>(`/bios/downloads/${id}`),
	enqueue: (payload: EnqueueBiosPayload) =>
		apiPost<BiosDownloadDetail>('/bios/downloads', payload),
	pause: (id: number) => apiPost<BiosDownloadDetail>(`/bios/downloads/${id}/pause`),
	resume: (id: number) => apiPost<BiosDownloadDetail>(`/bios/downloads/${id}/resume`),
	cancel: (id: number) => apiDelete<void>(`/bios/downloads/${id}`)
};
