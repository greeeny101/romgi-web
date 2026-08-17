import { auth } from './auth';

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8001/ws';

export type WsHandler = (type: string, data: unknown) => void;

export class ReconnectingSocket {
	private socket: WebSocket | null = null;
	private handlers = new Set<WsHandler>();
	private reconnectDelay = 1000;
	private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	private shouldRun = false;

	constructor(private path: string) {}

	connect() {
		this.shouldRun = true;
		if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
			return;
		}
		this._open();
	}

	private _open() {
		const tokens = auth.peek();
		if (!tokens || !this.shouldRun) return;

		const socket = new WebSocket(`${WS_BASE_URL}${this.path}?token=${encodeURIComponent(tokens.access)}`);
		this.socket = socket;

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
			this.reconnectTimer = setTimeout(() => this._open(), this.reconnectDelay);
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
