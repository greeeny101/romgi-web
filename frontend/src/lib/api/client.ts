import { auth } from '$lib/stores/auth';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8001/api';

export class ApiError extends Error {
	status: number;
	constructor(status: number, message: string) {
		super(message);
		this.status = status;
	}
}

/**
 * Refresh tokens rotate: /auth/refresh blacklists the token it was given and
 * returns a whole new pair, so the replacement MUST be stored. Keeping the old
 * refresh token (as this did when the endpoint only returned an access token)
 * would make the next refresh fail and log the user out.
 *
 * Concurrent 401s would otherwise each try to redeem the same now-dead refresh
 * token and all but one would fail, so in-flight refreshes share one promise.
 */
let inFlightRefresh: Promise<string | null> | null = null;

async function doRefresh(): Promise<string | null> {
	const tokens = auth.peek();
	if (!tokens) return null;
	const res = await fetch(`${API_BASE_URL}/auth/refresh`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ refresh: tokens.refresh })
	});
	if (!res.ok) {
		auth.clear();
		return null;
	}
	const body = (await res.json()) as { access: string; refresh: string };
	auth.setTokens(body);
	return body.access;
}

function refreshAccessToken(): Promise<string | null> {
	if (!inFlightRefresh) {
		const pending = doRefresh().finally(() => {
			if (inFlightRefresh === pending) inFlightRefresh = null;
		});
		inFlightRefresh = pending;
	}
	return inFlightRefresh;
}

async function request<T>(path: string, init?: RequestInit, _retried = false): Promise<T> {
	const tokens = auth.peek();
	const res = await fetch(`${API_BASE_URL}${path}`, {
		...init,
		headers: {
			Accept: 'application/json',
			...(init?.body ? { 'Content-Type': 'application/json' } : {}),
			...(tokens ? { Authorization: `Bearer ${tokens.access}` } : {}),
			...init?.headers
		}
	});

	if (res.status === 401 && tokens && !_retried) {
		const newAccess = await refreshAccessToken();
		if (newAccess) {
			return request<T>(path, init, true);
		}
	}

	if (!res.ok) {
		let message = res.statusText;
		try {
			const body = await res.json();
			message = body.detail ?? message;
		} catch {
			// response wasn't JSON — keep statusText
		}
		throw new ApiError(res.status, message);
	}

	if (res.status === 204) return undefined as T;
	return res.json() as Promise<T>;
}

export function apiGet<T>(path: string): Promise<T> {
	return request<T>(path);
}

export function apiPost<T>(path: string, body?: unknown): Promise<T> {
	return request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
}

export function apiPatch<T>(path: string, body?: unknown): Promise<T> {
	return request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined });
}

export function apiPut<T>(path: string, body?: unknown): Promise<T> {
	return request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined });
}

export function apiDelete<T>(path: string): Promise<T> {
	return request<T>(path, { method: 'DELETE' });
}

function filenameFromDisposition(header: string | null): string | null {
	if (!header) return null;
	const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(header);
	if (utf8Match) return decodeURIComponent(utf8Match[1]);
	const plainMatch = /filename="?([^";]+)"?/i.exec(header);
	return plainMatch ? plainMatch[1] : null;
}

/**
 * Plain <a href> navigation can't attach the bearer token, so authenticated
 * file downloads have to go through fetch + blob instead.
 */
export async function apiDownload(
	path: string,
	_retried = false
): Promise<{ blob: Blob; filename: string | null }> {
	const tokens = auth.peek();
	const res = await fetch(`${API_BASE_URL}${path}`, {
		headers: {
			...(tokens ? { Authorization: `Bearer ${tokens.access}` } : {})
		}
	});

	if (res.status === 401 && tokens && !_retried) {
		const newAccess = await refreshAccessToken();
		if (newAccess) {
			return apiDownload(path, true);
		}
	}

	if (!res.ok) {
		let message = res.statusText;
		try {
			const body = await res.json();
			message = body.detail ?? message;
		} catch {
			// response wasn't JSON — keep statusText
		}
		throw new ApiError(res.status, message);
	}

	const blob = await res.blob();
	return { blob, filename: filenameFromDisposition(res.headers.get('Content-Disposition')) };
}
