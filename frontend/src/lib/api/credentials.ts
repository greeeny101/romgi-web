import { apiDelete, apiGet, apiPost, apiPut } from './client';

export interface InternetArchiveStatus {
	logged_in: boolean;
	username: string | null;
	status: 'unverified' | 'ok' | 'stale' | 'invalid';
	last_validated_at: string | null;
}

export interface LoginTask {
	task_id: string;
}

export interface LoginStatus {
	state: 'pending' | 'success' | 'error';
	message?: string | null;
}

export interface CredentialStatus {
	provider: string;
	configured: boolean;
	status: 'unverified' | 'ok' | 'stale' | 'invalid';
}

export interface TestResult {
	ok: boolean;
	message?: string | null;
}

export type CredentialKind = 'debrid' | 'metadata';

export const credentialsApi = {
	iaLogin: (username: string, password: string) =>
		apiPost<LoginTask>('/credentials/internet-archive/login', { username, password }),
	iaLoginStatus: (taskId: string) => apiGet<LoginStatus>(`/credentials/internet-archive/login/${taskId}`),
	iaStatus: () => apiGet<InternetArchiveStatus>('/credentials/internet-archive/status'),
	iaLogout: () => apiPost<void>('/credentials/internet-archive/logout'),

	getStatus: (kind: CredentialKind, providerId: string) =>
		apiGet<CredentialStatus>(`/credentials/${kind}/${providerId}`),
	set: (kind: CredentialKind, providerId: string, data: Record<string, string>) =>
		apiPut<CredentialStatus>(`/credentials/${kind}/${providerId}`, { data }),
	test: (kind: CredentialKind, providerId: string) =>
		apiPost<TestResult>(`/credentials/${kind}/${providerId}/test`),
	clear: (kind: CredentialKind, providerId: string) => apiDelete<void>(`/credentials/${kind}/${providerId}`)
};
