import { apiDelete, apiGet, apiPost } from './client';

export interface TokenPair {
	access: string;
	refresh: string;
}

export interface Me {
	id: number;
	email: string;
}

export interface Capabilities {
	/** False when the instance has no mail server, so the UI can stop promising emails. */
	email_enabled: boolean;
}

export interface Session {
	id: number;
	ip_address: string | null;
	user_agent: string;
	created_at: string;
	last_used_at: string;
	expires_at: string;
	current: boolean;
}

export const authApi = {
	register: (email: string, password: string, inviteCode: string) =>
		apiPost<TokenPair>('/auth/register', { email, password, invite_code: inviteCode }),
	login: (email: string, password: string) => apiPost<TokenPair>('/auth/login', { email, password }),
	logout: (refresh: string) => apiPost<void>('/auth/logout', { refresh }),
	me: () => apiGet<Me>('/auth/me'),
	capabilities: () => apiGet<Capabilities>('/auth/capabilities'),

	requestPasswordReset: (email: string) => apiPost<void>('/auth/password/reset', { email }),
	confirmPasswordReset: (uid: string, token: string, newPassword: string) =>
		apiPost<TokenPair>('/auth/password/reset/confirm', {
			uid,
			token,
			new_password: newPassword
		}),
	changePassword: (currentPassword: string, newPassword: string) =>
		apiPost<TokenPair>('/auth/password/change', {
			current_password: currentPassword,
			new_password: newPassword
		}),

	sessions: () => apiGet<Session[]>('/auth/sessions'),
	revokeSession: (id: number) => apiDelete<void>(`/auth/sessions/${id}`),
	revokeOtherSessions: () => apiPost<void>('/auth/sessions/revoke-all')
};
