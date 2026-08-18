import { apiDelete, apiGet, apiPost } from './client';

export interface FavoriteEntry {
	slug: string;
	title: string;
	platform_id: string;
	boxart_url: string | null;
	regions: string[];
	created_at: string;
}

export interface RecentlyViewedEntry {
	slug: string;
	title: string;
	platform_id: string;
	boxart_url: string | null;
	regions: string[];
	viewed_at: string;
}

export const libraryApi = {
	favorites: () => apiGet<FavoriteEntry[]>('/library/favorites'),
	addFavorite: (slug: string) => apiPost<FavoriteEntry>('/library/favorites', { slug }),
	removeFavorite: (slug: string) => apiDelete<void>(`/library/favorites/${encodeURIComponent(slug)}`),
	recentlyViewed: () => apiGet<RecentlyViewedEntry[]>('/library/recently-viewed'),
	recordRecentlyViewed: (slug: string) =>
		apiPost<void>(`/library/recently-viewed/${encodeURIComponent(slug)}`)
};
