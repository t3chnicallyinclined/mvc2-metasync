import { api } from './config';
import type { SseFrame } from './types';

// ── Real-time bus (native EventSource, one connection per channel) ─────────────────────────────
// Mirrors the shipped bus: the gateway serves GET /skinsync/rt/stream/{channel} — first an
// `event: connected`, then `event: delta` frames. The browser's built-in reconnect replays the
// `Last-Event-ID` header from the `id:` line, so gap-fill is free (TOURNAMENT-REALTIME-ARCH §2.1).
//
// Unlike the old Tauri app (which bridged SSE through a Rust `rt_subscribe`), the PWA connects
// DIRECTLY — the browser is simpler here (REWRITE-ARCHITECTURE §3, "Client transport").

type Listener = (frame: SseFrame) => void;

export class SseChannel {
	readonly channel: string;
	/** Latest frame seen on this channel (rune-reactive). Includes the initial `connected`. */
	lastDelta = $state<SseFrame | null>(null);
	/** Whether the stream is currently open + has emitted `connected`. */
	connected = $state(false);

	#es: EventSource | null = null;
	#subs = new Set<Listener>();
	#refs = 0;

	constructor(channel: string) {
		this.channel = channel;
	}

	get url(): string {
		return api(`/skinsync/rt/stream/${this.channel}`);
	}

	#open() {
		if (this.#es) return;
		if (typeof window === 'undefined' || typeof EventSource === 'undefined') return;
		const es = new EventSource(this.url);
		this.#es = es;
		// `connected` — a handshake frame with no payload change; just flips the flag + forwards.
		es.addEventListener('connected', (e) => {
			this.connected = true;
			this.#emit(parse((e as MessageEvent).data));
		});
		// `delta` — the real event; forward the parsed frame.
		es.addEventListener('delta', (e) => {
			this.#emit(parse((e as MessageEvent).data));
		});
		// default (unnamed) events, if the server ever sends any.
		es.onmessage = (e) => this.#emit(parse(e.data));
		es.onerror = () => {
			// EventSource auto-reconnects (with Last-Event-ID). Just reflect the state.
			this.connected = false;
		};
	}

	#close() {
		if (this.#es) {
			this.#es.close();
			this.#es = null;
		}
		this.connected = false;
	}

	#emit(frame: SseFrame | null) {
		if (!frame) return;
		this.lastDelta = frame;
		for (const cb of this.#subs) {
			try {
				cb(frame);
			} catch {
				/* a bad listener must never tear down the stream */
			}
		}
	}

	/**
	 * Subscribe a callback. Opens the stream on the first subscriber and closes it when the last
	 * one leaves (ref-counted). Returns an unsubscribe fn.
	 */
	subscribe(cb: Listener): () => void {
		this.#subs.add(cb);
		this.#refs++;
		this.#open();
		return () => {
			if (this.#subs.delete(cb)) this.#refs--;
			if (this.#refs <= 0) this.#close();
		};
	}
}

function parse(data: unknown): SseFrame | null {
	if (data == null) return null;
	if (typeof data === 'object') return data as SseFrame;
	if (typeof data === 'string') {
		try {
			return JSON.parse(data) as SseFrame;
		} catch {
			return null;
		}
	}
	return null;
}

// ── App-wide singleton registry: one SseChannel instance per channel name ──────────────────────
const registry = new Map<string, SseChannel>();

export function getChannel(name: string): SseChannel {
	let c = registry.get(name);
	if (!c) {
		c = new SseChannel(name);
		registry.set(name, c);
	}
	return c;
}
