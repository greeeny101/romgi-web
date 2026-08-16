import { apiGet } from './client';

export interface GameMetadata {
	description: string | null;
	screenshot_urls: string[];
	artwork_urls: string[];
}

export const metadataApi = {
	entry: (slug: string) => apiGet<GameMetadata | null>(`/metadata/entries/${encodeURIComponent(slug)}`)
};
