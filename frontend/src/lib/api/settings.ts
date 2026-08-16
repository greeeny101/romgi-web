import { apiGet, apiPatch } from './client';

export interface UserSettings {
	theme: 'system' | 'light' | 'dark';
	max_concurrent_downloads: number;
	torrents_disabled: boolean;
	auto_extract_disabled: boolean;
	debrid_enabled: boolean;
	debrid_provider_id: string;
	metadata_enabled: boolean;
	preferred_source_ids: string[];
	disabled_source_ids: string[];
	default_platform_ids: string[];
	default_region_ids: string[];
	extract_disabled_platform_ids: string[];
}

export type UserSettingsUpdate = Partial<UserSettings>;

export const settingsApi = {
	get: () => apiGet<UserSettings>('/settings'),
	update: (payload: UserSettingsUpdate) => apiPatch<UserSettings>('/settings', payload)
};
