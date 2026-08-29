import { refreshAccessToken } from '$lib/api/client';
import { auth } from './auth';

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8001/ws';

/**
 * Refresh this far ahead of expiry. The token is checked once, at the
 * handshake, and the connection then lives for as long as it stays up — so
 * this only has to cover the dial itself, not the session.
 */
const TOKEN_SKEW_SECONDS = 30;

/**
 * Whether `token` is expired, or close enough that it may be by the time the
 * handshake lands.
 *
 * Reading `exp` locally rather than dialling and reacting to the rejection,
 * because there is nothing to react to: a consumer that closes during
 * connect() never completes the handshake, so the browser reports a generic
 * failure (1006) that is indistinguishable from the server being down. An
 * unreadable token returns false and lets the server be the judge.
 */
function expiresSoon(token: string, withinSeconds: number): boolean {
	try {
		const [, payload] = token.split('.');
		// JWT payloads are base64url; atob wants standard base64.
		const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
		const exp = JSON.parse(json).exp;
		if (typeof exp !== 'number') return false;
		return exp * 1000 - Date.now() < withinSeconds * 1000;
	} catch {
		return false;
	}
}

export type WsHandler = (type: string, data: unknown) => void;

export class ReconnectingSocket {
	private socket: WebSocket | null = null;
	private handlers = new Set<WsHandler>();
	private reconnectDelay = 1000;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private shouldRun = false;
	// _open awaits a possible refresh, so `this.socket` still holds the old,
	// closed socket while a dial is in flight — without this a second
	// connect() in that window would open a duplicate.
	private opening = false;

	constructor(private path: string) {}

	connect() {
		this.shouldRun = true;
		if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
			return;
		}
		void this._open();
	}

	private async _open() {
		if (this.opening || !this.shouldRun) return;
		this.opening = true;
		try {
			let tokens = auth.peek();
			if (!tokens) return;

			// The token is only checked at the handshake, so a socket opened
			// with a valid one keeps working indefinitely — but every
			// reconnect (a server restart, a sleeping laptop, a dropped
			// connection) re-authenticates. Without this the stored access
			// token just goes stale, every retry is rejected the same way,
			// and live progress dies silently until a full page reload.
			if (expiresSoon(tokens.access, TOKEN_SKEW_SECONDS)) {
				const fresh = await refreshAccessToken();
				// Null means the refresh token is dead too and auth was
				// cleared; there is nothing left to reconnect as.
				if (!fresh || !this.shouldRun) return;
				tokens = auth.peek();
				if (!tokens) return;
			}

			const socket = new WebSocket(`${WS_BASE_URL}${this.path}?token=${encodeURIComponent(tokens.access)}`);
			this.socket = socket;
			this._wire(socket);
		} finally {
			this.opening = false;
		}
	}

	private _wire(socket: WebSocket) {
		socket.onopen = () => {
			this.reconnectDelay = 1000;
		};
		socket.onmessage = (event) => {
			try {
				const msg = JSON.parse(event.data);
				this.handlers.forEach((h) => h(msg.type, msg.data));
			} catch {
				// ignore malformed frames
			}
		};
		socket.onclose = () => {
			if (!this.shouldRun) return;
			this.reconnectTimer = setTimeout(() => void this._open(), this.reconnectDelay);
			this.reconnectDelay = Math.min(this.reconnectDelay * 2, 15000);
		};
		socket.onerror = () => socket.close();
	}

	subscribe(handler: WsHandler): () => void {
		this.handlers.add(handler);
		return () => this.handlers.delete(handler);
	}

	disconnect() {
		this.shouldRun = false;
		if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
		this.socket?.close();
		this.socket = null;
	}
}

export const downloadsSocket = new ReconnectingSocket('/downloads/');
export const ingestionSocket = new ReconnectingSocket('/ingestion/');
export const romsetsSocket = new ReconnectingSocket('/romsets/');
export const biosSocket = new ReconnectingSocket('/bios/');
