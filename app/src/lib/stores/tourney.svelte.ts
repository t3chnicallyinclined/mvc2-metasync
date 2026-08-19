import { api } from '$lib/config';
import type { Registration, TournamentDoc } from '$lib/tourney';

// Tournament DETAIL store. Two live inputs, mirroring the discipline of SseChannel but with its OWN
// EventSource because the URL + verbs differ from the generic channel bus:
//   1. data:   GET /skinsync/tourney/get?id=<id>            → { ok, tournament } (fast initial paint)
//   2. live:   SSE GET /skinsync/rt/tourney/<id>/stream     → `event: snapshot` (authoritative full doc)
//              then `event: delta` frames patched by `type`.
//
// Delta handling (server shapes verified against metasync-srv/skinsync/src/tourney.rs):
//   • snapshot            → REPLACE doc with data.tournament (may arrive more than once; always authoritative)
//   • status              → patch doc.status inline (instant; single authoritative field)
//   • deleted             → mark `gone` (the tournament was removed)
//   • registration        → optimistic inline upsert/remove by steamid, THEN a debounced authoritative
//                            refetch (the delta carries only steamid/seed/checked_in, not the row's status)
//   • bracket_advance / match_update / host_update / alert / unknown
//                         → debounced authoritative refetch of /tourney/get (the bracket is structural and
//                            arrives as minimal match rows — a full replace is the safest, defensive apply)
// Keep-last-good on fetch error; pause on document.hidden (handled by the route via connect/disconnect).
//
// Player display (name/avatar/cc) is NOT stored on the tournament — it resolves live from the shared
// /profile path (same rule as the rest of the app), cached here in `players`.

export interface PlayerLite {
	steamid: string;
	name?: string;
	avatar?: string;
	cc?: string;
	rating?: number;
}

type Delta = Record<string, unknown>;

interface GetResponse {
	ok?: boolean;
	tournament?: TournamentDoc;
}

interface ProfileLite {
	found?: boolean;
	name?: string;
	avatar?: string;
	cc?: string;
	rating?: number;
}

export class TourneyStore {
	id = $state('');
	doc = $state<TournamentDoc | null>(null);
	/** steamid → resolved display (name/avatar/cc/rating), lazily fetched from /profile. */
	players = $state<Record<string, PlayerLite>>({});
	connected = $state(false);
	loading = $state(false);
	error = $state<string | null>(null);
	notFound = $state(false);
	gone = $state(false);
	lastLoaded = $state(0);

	#es: EventSource | null = null;
	#reqId = 0;
	#deb: ReturnType<typeof setTimeout> | null = null;
	#resolving = new Set<string>();

	/** Point the store at `id` (resetting when it changes), fetch the doc, and open the live stream.
	 *  Idempotent: safe to call on mount, on a route-param change, AND on visibility-resume. */
	connect(id: string): void {
		const next = String(id ?? '');
		if (!next) return;
		if (next !== this.id) {
			this.id = next;
			this.doc = null;
			this.players = {};
			this.notFound = false;
			this.gone = false;
			this.#closeEs();
		}
		void this.load(next); // refetch on every connect (fast paint / catch-up after a hidden gap)
		this.#openEs();
	}

	disconnect(): void {
		this.#closeEs();
		if (this.#deb) {
			clearTimeout(this.#deb);
			this.#deb = null;
		}
	}

	async load(id: string): Promise<void> {
		const sid = String(id ?? '');
		if (!sid) return;
		const myReq = ++this.#reqId;
		this.loading = true;
		try {
			const res = await fetch(api(`/skinsync/tourney/get?id=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			});
			if (res.status === 404) {
				if (myReq === this.#reqId && sid === this.id) {
					this.notFound = true;
					this.doc = null;
				}
				return;
			}
			if (!res.ok) throw new Error(`tourney ${res.status}`);
			const json = (await res.json()) as GetResponse;
			if (myReq !== this.#reqId || sid !== this.id) return; // superseded / route changed
			const doc = json.tournament ?? null;
			if (doc) {
				this.doc = doc;
				this.notFound = false;
				this.gone = false;
				this.#resolveDocPlayers();
			} else if (json.ok === false) {
				this.notFound = true;
			}
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.doc on a transient blip for the same tournament.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}

	// ── live stream ────────────────────────────────────────────────────────────────────────────────
	#openEs(): void {
		if (this.#es) return;
		if (typeof window === 'undefined' || typeof EventSource === 'undefined') return;
		if (!this.id) return;
		const url = api(`/skinsync/rt/tourney/${encodeURIComponent(this.id)}/stream`);
		const es = new EventSource(url);
		this.#es = es;
		// `snapshot` — the authoritative full doc; always REPLACE (may resend on reconnect gap-fill).
		es.addEventListener('snapshot', (e) => {
			this.connected = true;
			const frame = parse((e as MessageEvent).data);
			const doc = frame?.tournament as TournamentDoc | undefined;
			if (doc && (!doc.id || doc.id === this.id)) {
				this.doc = doc;
				this.notFound = false;
				this.gone = false;
				this.error = null;
				this.lastLoaded = Date.now();
				this.#resolveDocPlayers();
			}
		});
		// `delta` — a minimal patch; apply by type.
		es.addEventListener('delta', (e) => {
			const frame = parse((e as MessageEvent).data);
			if (frame) this.#applyDelta(frame);
		});
		es.onerror = () => {
			// EventSource auto-reconnects (with Last-Event-ID); the gateway resends a snapshot if needed.
			this.connected = false;
		};
	}

	#closeEs(): void {
		if (this.#es) {
			this.#es.close();
			this.#es = null;
		}
		this.connected = false;
	}

	#applyDelta(d: Delta): void {
		const type = String(d.type ?? '');
		if (!type || type === 'connected') return;
		if (type === 'deleted') {
			this.gone = true;
			return;
		}
		if (!this.doc) {
			// A delta arrived before the doc — pull it authoritatively.
			this.#debouncedReload();
			return;
		}
		if (type === 'status') {
			const st = typeof d.status === 'string' ? d.status : this.doc.status;
			this.doc = { ...this.doc, status: st };
			return;
		}
		if (type === 'registration') {
			this.#applyRegistration(d); // optimistic instant appearance
			this.#debouncedReload(); // reconcile authoritative seed/status
			return;
		}
		// bracket_advance | match_update | host_update | alert | anything else → authoritative refetch.
		this.#debouncedReload();
	}

	// Optimistically upsert/remove a registration so a new entrant pops instantly; the debounced refetch
	// then reconciles the authoritative row (status/seed the minimal delta doesn't carry).
	#applyRegistration(d: Delta): void {
		const doc = this.doc;
		const sid = String(d.steamid ?? '');
		if (!doc || !sid) return;
		const action = String(d.action ?? '');
		const regs = (doc.registrations ?? []).slice();
		const idx = regs.findIndex((r) => r.steamid === sid);
		if (action === 'remove') {
			if (idx >= 0) regs.splice(idx, 1);
		} else {
			const base: Registration = idx >= 0 ? { ...regs[idx] } : { steamid: sid, status: 'registered' };
			if (typeof d.seed === 'number') base.seed = d.seed;
			if (typeof d.checked_in === 'boolean') base.checked_in = d.checked_in;
			if (Array.isArray(d.team)) base.team = (d.team as unknown[]).map((n) => Number(n));
			if (idx >= 0) regs[idx] = base;
			else regs.push(base);
		}
		this.doc = { ...doc, registrations: regs };
		this.#resolveDocPlayers();
	}

	#debouncedReload(): void {
		if (this.#deb) return;
		this.#deb = setTimeout(() => {
			this.#deb = null;
			void this.load(this.id);
		}, 400);
	}

	// ── player display resolution (name/avatar/cc via the shared /profile path) ──────────────────────
	#resolveDocPlayers(): void {
		const doc = this.doc;
		if (!doc) return;
		const ids = new Set<string>();
		if (doc.to_steamid) ids.add(doc.to_steamid);
		for (const c of doc.co_tos ?? []) if (c) ids.add(c);
		for (const r of doc.registrations ?? []) if (r?.steamid) ids.add(r.steamid);
		// bracket seats, so match cards can show names too.
		for (const m of doc.bracket?.matches ?? []) {
			if (m?.p1) ids.add(m.p1);
			if (m?.p2) ids.add(m.p2);
		}
		this.#resolve([...ids]);
	}

	#resolve(sids: string[]): void {
		if (typeof window === 'undefined') return;
		for (const sid of sids) {
			if (!sid || this.players[sid] || this.#resolving.has(sid)) continue;
			this.#resolving.add(sid);
			fetch(api(`/skinsync/profile?steamid=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			})
				.then((r) => (r.ok ? (r.json() as Promise<ProfileLite>) : null))
				.then((p) => {
					const lite: PlayerLite =
						p && p.found
							? { steamid: sid, name: p.name, avatar: p.avatar, cc: p.cc, rating: p.rating }
							: { steamid: sid };
					this.players = { ...this.players, [sid]: lite };
				})
				.catch(() => {
					// resolution is best-effort; the row still renders with a short-id fallback.
				})
				.finally(() => this.#resolving.delete(sid));
		}
	}
}

function parse(data: unknown): Delta | null {
	if (data == null) return null;
	if (typeof data === 'object') return data as Delta;
	if (typeof data === 'string') {
		try {
			return JSON.parse(data) as Delta;
		} catch {
			return null;
		}
	}
	return null;
}
