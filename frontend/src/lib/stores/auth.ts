import { writable } from 'svelte/store';
import { browser } from '$app/environment';

interface TokenPair {
	access: string;
	refresh: string;
}

const STORAGE_KEY = 'romgi.auth.v1';

function loadInitial(): TokenPair | null {
	if (!browser) return null;
	const raw = localStorage.getItem(STORAGE_KEY);
	if (!raw) return null;
	try {
		return JSON.parse(raw) as TokenPair;
	} catch {
		return null;
	}
}

function createAuthStore() {
	const { subscribe, set } = writable<TokenPair | null>(loadInitial());

	return {
		subscribe,
		setTokens(tokens: TokenPair) {
			if (browser) localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens));
			set(tokens);
		},
		// There is deliberately no setAccess(): refresh tokens rotate, so the
		// access token never changes on its own — both always move together.
		clear() {
			if (browser) localStorage.removeItem(STORAGE_KEY);
			set(null);
		},
		peek(): TokenPair | null {
			return loadInitial();
		}
	};
}

export const auth = createAuthStore();
