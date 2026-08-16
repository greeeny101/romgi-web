import { apiGet } from './client';

export interface Platform {
	id: string;
	brand: string;
	name: string;
}

export interface Region {
	id: string;
	name: string;
}

export interface Source {
	id: string;
	name: string;
	homepage: string | null;
	kind: string;
	auth_required: boolean;
	priority: number;
}

export interface SourceHealth {
	source_id: string;
	status: 'ok' | 'error' | 'unknown';
	last_checked_at: string | null;
	reason: string | null;
	entry_count: number;
	link_count: number;
}

export interface EntrySummary {
	slug: string;
	title: string;
	platform_id: string;
	boxart_url: string | null;
	ra_game_id: number | null;
}

export interface EntryDetail {
	slug: string;
	title: string;
	rom_id: string | null;
	platform_id: string;
	boxart_url: string | null;
	ra_game_id: number | null;
	ra_num_achievements: number | null;
	regions: string[];
	group_id: number | null;
}

export interface Link {
	id: number;
	name: string;
	type: string;
	format: string;
	url: string;
	filename: string;
	host: string;
	size: number;
	size_str: string;
	source_id: string | null;
	requires_auth: boolean;
	is_torrent: boolean;
	torrent_file_index: number | null;
}

export interface PaginatedEntries {
	items: EntrySummary[];
	total: number;
	page: number;
	page_size: number;
}

export interface EntryFilters {
	q?: string;
	platform?: string;
	region?: string;
	source?: string;
	page?: number;
	page_size?: number;
}

function toQueryString(filters: EntryFilters): string {
	const params = new URLSearchParams();
	for (const [key, value] of Object.entries(filters)) {
		if (value !== undefined && value !== '') params.set(key, String(value));
	}
	const qs = params.toString();
	return qs ? `?${qs}` : '';
}

export const catalogApi = {
	platforms: () => apiGet<Platform[]>('/catalog/platforms'),
	regions: () => apiGet<Region[]>('/catalog/regions'),
	sources: () => apiGet<Source[]>('/catalog/sources'),
	sourceHealth: () => apiGet<SourceHealth[]>('/catalog/sources/health'),
	entries: (filters: EntryFilters = {}) =>
		apiGet<PaginatedEntries>(`/catalog/entries${toQueryString(filters)}`),
	entry: (slug: string) => apiGet<EntryDetail>(`/catalog/entries/${encodeURIComponent(slug)}`),
	entryLinks: (slug: string) => apiGet<Link[]>(`/catalog/entries/${encodeURIComponent(slug)}/links`)
};
