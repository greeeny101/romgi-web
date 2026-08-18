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

export interface CredentialField {
	key: string;
	label: string;
	obscure: boolean;
	optional: boolean;
}

export interface CredentialStatus {
	provider: string;
	configured: boolean;
	status: 'unverified' | 'ok' | 'stale' | 'invalid';
	/** The provider's credential shape, as the backend defines it. */
	fields: CredentialField[];
	/** Keys currently held in the vault — obscure ones included, by name only. */
	stored_keys: string[];
	/** Saved values for the non-secret fields, so the form can show them back. */
	stored_values: Record<string, string>;
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
	iaSetKeys: (access_key: string, secret_key: string) =>
		apiPut<InternetArchiveStatus>('/credentials/internet-archive/keys', { access_key, secret_key }),
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
