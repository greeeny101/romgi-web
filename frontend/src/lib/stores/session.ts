import { writable } from 'svelte/store';
import { authApi, type Me, type TokenPair } from '$lib/api/auth';
import { settingsApi } from '$lib/api/settings';
import { auth } from './auth';
import { downloads } from './downloads';
import { favorites } from './favorites';
import { theme } from './theme';

export const currentUser = writable<Me | null>(null);

async function afterAuth() {
	const me = await authApi.me();
	currentUser.set(me);
	await favorites.load();
	downloads.start();
	settingsApi
		.get()
		.then((s) => theme.set(s.theme))
		.catch(() => {});
}

export const session = {
	async login(email: string, password: string) {
		const tokens = await authApi.login(email, password);
		auth.setTokens(tokens);
		await afterAuth();
	},
	async register(email: string, password: string, inviteCode: string) {
		const tokens = await authApi.register(email, password, inviteCode);
		auth.setTokens(tokens);
		await afterAuth();
	},

	/** Adopt a pair returned by a password reset/change and warm the app. */
	async adopt(tokens: TokenPair) {
		auth.setTokens(tokens);
		await afterAuth();
	},
	async restore() {
		const tokens = auth.peek();
		if (!tokens) return;
		try {
			await afterAuth();
		} catch {
			auth.clear();
			currentUser.set(null);
		}
	},
	async logout() {
		const tokens = auth.peek();
		if (tokens) {
			await authApi.logout(tokens.refresh).catch(() => {});
		}
		auth.clear();
		currentUser.set(null);
		downloads.stop();
		favorites.clear();
		theme.set('system');
	}
};
