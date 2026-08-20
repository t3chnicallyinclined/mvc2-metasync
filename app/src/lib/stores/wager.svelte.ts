import { api } from '$lib/config';
import { getChannel, type SseChannel } from '$lib/rt.svelte';
import { auth } from '$lib/stores/auth.svelte';
import { wallet } from '$lib/stores/wallet.svelte';
import type { SseFrame } from '$lib/types';

// 🪙 QUARTER MATCH wager store. rune-$state, two live surfaces off the app-wide `matches` SSE channel:
//   • mine — the viewer's CURRENT wager (GET /wager/state?steamid=), drives the rail through its lifecycle.
//   • open — THE MARQUEE: open challenges anyone can attempt (GET /wager/open, a PUBLIC read).
// Every `wager_*` delta on `matches` carries the FULL wager row, so we patch both lists directly (no
// refetch needed) and keep-last-good on fetch errors. Writes go through auth.post (the single authed path;
// it handles 401→logout + {ok:false}). Types are local (types.ts off-limits) and mirror the live skinsync
// payload (metasync-srv/skinsync/src/wager.rs row()).

export interface Wager {
	id: string;
	challenger: string;
	challenger_name?: string;
	opp?: string; // "" = OPEN (on the marquee); a steamid = a directed challenge
	acceptor?: string;
	acceptor_name?: string;
	stake: number;
	pot?: number;
	status: string; // open | locked | settled | refunded | cancelled | expired
	ft?: number;
	cw?: number; // challenger game wins since lock
	aw?: number; // acceptor game wins since lock
	created_ms?: number;
	locked_ms?: number;
	winner?: string;
	lobby_id?: string;
	has_lobby?: boolean;
	live?: boolean; // 🔴 a game is being fought right now
}

type WagerFrame = SseFrame & Partial<Wager>;

/** offer / respond return the (updated) wager; share is the challenge link. */
interface OfferResult {
	ok?: boolean;
	wager?: Wager;
	share?: string;
	declined?: boolean;
}

export class WagerStore {
	/** the viewer's current wager (null = none) — drives the rail. */
	mine = $state<Wager | null>(null);
	/** open challenges on the marquee, newest-first. */
	open = $state<Wager[]>([]);

	#sid = '';
	#unsub: (() => void) | null = null;
	#ch: SseChannel | null = null;

	get live(): boolean {
		return this.#ch?.connected ?? false;
	}

	/** THE MARQUEE — every open quarter (public, works signed-out). */
	async loadOpen(): Promise<void> {
		try {
			const res = await fetch(api('/skinsync/wager/open'), { headers: { accept: 'application/json' } });
			if (!res.ok) return; // keep last-good
			const j = (await res.json()) as { ok?: boolean; wagers?: Wager[] };
			if (j?.ok) this.open = Array.isArray(j.wagers) ? j.wagers : [];
		} catch {
			/* keep last-good */
		}
	}

	/** the viewer's current wager (public read keyed by their steamid). */
	async loadMine(steamid: string | null | undefined): Promise<void> {
		const sid = String(steamid || '');
		this.#sid = sid;
		if (!sid) {
			this.mine = null;
			return;
		}
		try {
			const res = await fetch(api(`/skinsync/wager/state?steamid=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) return; // keep last-good
			const j = (await res.json()) as { ok?: boolean; wager?: Wager | null };
			if (j?.ok) this.mine = j.wager ?? null;
		} catch {
			/* keep last-good */
		}
	}

	/** Open the live subscription (idempotent). Pass the signed-in steamid so `mine` tracks it. */
	connect(steamid?: string | null): void {
		if (steamid !== undefined) this.#sid = String(steamid || '');
		if (this.#unsub) return;
		const ch = getChannel('matches');
		this.#ch = ch;
		this.#unsub = ch.subscribe((f) => this.#apply(f as WagerFrame));
	}

	disconnect(): void {
		if (this.#unsub) {
			this.#unsub();
			this.#unsub = null;
		}
	}

	#apply(d: WagerFrame): void {
		const type = String(d.type ?? '');
		if (!type.startsWith('wager_')) return; // ignore match_start/end/result + the `connected` handshake
		const w = d as Wager;
		if (!w.id) return;
		// marquee: keep an OPEN, undirected quarter present; drop it the moment it locks/settles/cancels.
		if (w.status === 'open' && !w.opp) {
			const i = this.open.findIndex((x) => x.id === w.id);
			this.open = i >= 0 ? this.open.map((x, j) => (j === i ? w : x)) : [w, ...this.open];
		} else if (this.open.some((x) => x.id === w.id)) {
			this.open = this.open.filter((x) => x.id !== w.id);
		}
		// mine: any wager I'm a party to (challenger, the accepted opponent, or the directed target).
		if (this.#sid && (w.challenger === this.#sid || w.acceptor === this.#sid || w.opp === this.#sid)) {
			this.mine = w;
		}
	}

	// ── writes (all via auth.post — the single authed path) ────────────────────────────────────────
	/** Put a quarter up: `opp` omitted = an OPEN marquee challenge; `opp` set = a directed challenge. */
	async offer(body: { stake: number; ft?: number; opp?: string }): Promise<{ ok: boolean; error?: string }> {
		const res = await auth.post<OfferResult>('/skinsync/wager/offer', body);
		if (res.ok && res.data?.wager) {
			this.mine = res.data.wager;
			void this.loadOpen();
			void wallet.load(auth.steamid);
		}
		return { ok: res.ok, error: res.error };
	}

	/** Accept (match) or decline an offer by id. */
	async respond(id: string, accept: boolean): Promise<{ ok: boolean; error?: string }> {
		const res = await auth.post<OfferResult>('/skinsync/wager/respond', { id, accept });
		if (res.ok && res.data?.wager) this.mine = res.data.wager;
		if (res.ok) {
			void this.loadOpen();
			void wallet.load(auth.steamid);
		}
		return { ok: res.ok, error: res.error };
	}

	/** Pull an OPEN quarter back off the marquee (challenger-only, server-enforced). */
	async cancel(id: string): Promise<{ ok: boolean; error?: string }> {
		const res = await auth.post('/skinsync/wager/cancel', { id });
		if (res.ok) {
			if (this.mine?.id === id) this.mine = null;
			void this.loadOpen();
			void wallet.load(auth.steamid);
		}
		return { ok: res.ok, error: res.error };
	}
}

export const wager = new WagerStore();
