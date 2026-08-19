import { apiGet } from './client';

export interface MediaItem {
	/** The original upload — used as the click-through target only. */
	full: string;
	/** Provider-scaled thumbnail for display; equals `full` when the provider has none. */
	thumb: string;
}

export interface GameMetadata {
	description: string | null;
	screenshots: MediaItem[];
	artwork: MediaItem[];
}

export const metadataApi = {
	entry: (slug: string) => apiGet<GameMetadata | null>(`/metadata/entries/${encodeURIComponent(slug)}`)
};
