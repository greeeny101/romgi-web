import { apiDelete, apiGet, apiPost } from './client';

export interface Emulator {
	id: string;
	name: string;
	platform_id: string | null;
}

export interface SetSearchResult {
	identifier: string;
	title: string;
	size: number;
	downloads: number;
	published: string | null;
}

export interface SetSearchResponse {
	items: SetSearchResult[];
	total: number;
	page: number;
	page_size: number;
}

export interface SetFile {
	path: string;
	size: number;
	format: string | null;
	md5: string | null;
	sha1: string | null;
}

export interface SetItemDetail {
	identifier: string;
	title: string;
	description: string;
	collections: string[];
	published: string | null;
	item_size: number;
	infohash: string | null;
	/** archive.org's login-gated `loggedin` collection. */
	restricted: boolean;
	/** Capped — see `files_truncated`. Select by folder past the cap. */
	files: SetFile[];
	files_truncated: boolean;
	file_count: number;
	folders: SetFolder[];
	total_size: number;
}

export interface SetFolder {
	/** Top-level directory, or '' for files at the root of the torrent. */
	path: string;
	file_count: number;
	size: number;
}

export interface RomSetDownloadFile {
	path: string;
	size: number;
	wanted: boolean;
	progress: number;
	done: boolean;
}

export interface RomSetDownload {
	id: number;
	identifier: string;
	title: string;
	provider: string;
	platform_id: string | null;
	emulator_id: string;
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

export interface RomSetDownloadDetail extends RomSetDownload {
	files: RomSetDownloadFile[];
}

export interface LibrarySpace {
	free: number;
	committed: number;
	reserve: number;
	available: number;
}

export interface EnqueueSetPayload {
	identifier: string;
	platform_id?: string | null;
	emulator_id?: string;
	paths?: string[];
	/** Top-level folders, expanded to their files server-side. */
	folders?: string[];
	extract?: boolean;
}

export const romsetsApi = {
	emulators: () => apiGet<Emulator[]>('/romsets/emulators'),
	search: (emulator: string, q = '', page = 1) => {
		const params = new URLSearchParams({ emulator, page: String(page) });
		if (q) params.set('q', q);
		return apiGet<SetSearchResponse>(`/romsets/search?${params.toString()}`);
	},
	item: (identifier: string) =>
		apiGet<SetItemDetail>(`/romsets/items/${encodeURIComponent(identifier)}`),
	space: () => apiGet<LibrarySpace>('/romsets/space'),
	list: () => apiGet<RomSetDownload[]>('/romsets/downloads'),
	get: (id: number) => apiGet<RomSetDownloadDetail>(`/romsets/downloads/${id}`),
	enqueue: (payload: EnqueueSetPayload) =>
		apiPost<RomSetDownloadDetail>('/romsets/downloads', payload),
	pause: (id: number) => apiPost<RomSetDownloadDetail>(`/romsets/downloads/${id}/pause`),
	resume: (id: number) => apiPost<RomSetDownloadDetail>(`/romsets/downloads/${id}/resume`),
	cancel: (id: number) => apiDelete<void>(`/romsets/downloads/${id}`)
};
