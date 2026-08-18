import { apiGet } from './client';

export interface IngestionStatus {
	/** True while a build holds the one-at-a-time ingestion slot. */
	running: boolean;
	build_id: number | null;
	started_at: string | null;
}

export const ingestionApi = {
	status: () => apiGet<IngestionStatus>('/ingestion/status')
};
