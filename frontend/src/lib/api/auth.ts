import { apiGet, apiPost } from './client';

export interface TokenPair {
	access: string;
	refresh: string;
}

export interface Me {
	id: number;
	email: string;
}

export const authApi = {
	register: (email: string, password: string) =>
		apiPost<TokenPair>('/auth/register', { email, password }),
	login: (email: string, password: string) => apiPost<TokenPair>('/auth/login', { email, password }),
	logout: (refresh: string) => apiPost<void>('/auth/logout', { refresh }),
	me: () => apiGet<Me>('/auth/me')
};
