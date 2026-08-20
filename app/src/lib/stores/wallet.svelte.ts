import { api } from '$lib/config';
import { getChannel, type SseChannel } from '$lib/rt.svelte';
import type { SseFrame } from '$lib/types';

// 🪙 QUARTERS wallet store. rune-$state, modelled on LeaderboardStore: one cheap public GET, keep the
// last-good balance on a transient blip (never blank a chip that's already showing), and refetch live
// whenever a wager or a match result could have moved the balance.
//   • data: GET /skinsync/coins?steamid=  → { ok, balance, genesis, recent[] }  (public read; play money)
//   • live: SSE channel "matches" → on any `wager_*` / `match_result` delta, debounced refetch (~600ms).
// The balance is the single global home of the quarters figure (DESIGN §5). Types are local (types.ts
// is off-limits) and mirror the live skinsync ledger payload (metasync-srv/skinsync/src/ledger.rs).

/** One ledger line from `recent[]`. `kind` is the flow name; `delta` is signed for THIS account. */
export interface CoinTx {
	ts?: number;
	kind?: string; // genesis|entry|refund|payout|grant|match-stake|match-settle|match-fee|match-refund
	amount?: number; // magnitude, whole quarters
	delta?: number; // signed: +in / −out for the queried account
	memo?: string;
}

interface CoinsResponse {
	ok?: boolean;
	balance?: number;
	genesis?: number;
	recent?: CoinTx[];
}

export class WalletStore {
	/** null = not yet known (chip hidden); a number = the live balance (kept last-good on error). */
	balance = $state<number | null>(null);
	genesis = $state(20);
	recent = $state<CoinTx[]>([]);

	#sid = '';
	#reqId = 0;
	#unsub: (() => void) | null = null;
	#ch: SseChannel | null = null;
	#deb: ReturnType<typeof setTimeout> | null = null;

	/** Load (or refresh) the wallet for a steamid. A NEW user clears last-good; a re-load keeps it. */
	async load(steamid: string | null | undefined): Promise<void> {
		const sid = String(steamid || '');
		if (sid !== this.#sid) {
			// switched user (or signed out) → drop the previous wallet so one user's balance never shows
			// under another's identity.
			this.#sid = sid;
			this.balance = null;
			this.recent = [];
		}
		if (!sid) return;
		const myReq = ++this.#reqId;
		try {
			const res = await fetch(api(`/skinsync/coins?steamid=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) return; // keep last-good
			const j = (await res.json()) as CoinsResponse;
			if (myReq !== this.#reqId) return; // superseded
			if (j?.ok) {
				if (typeof j.balance === 'number') this.balance = j.balance;
				if (typeof j.genesis === 'number') this.genesis = j.genesis;
				this.recent = Array.isArray(j.recent) ? j.recent : [];
			}
		} catch {
			/* keep last-good on a transient blip */
		}
	}

	/** Open the live subscription (idempotent). Call from a browser $effect/onMount. */
	connect(): void {
		if (this.#unsub) return;
		const ch = getChannel('matches');
		this.#ch = ch;
		this.#unsub = ch.subscribe((f) => this.#onDelta(f));
	}

	disconnect(): void {
		if (this.#unsub) {
			this.#unsub();
			this.#unsub = null;
		}
		if (this.#deb) {
			clearTimeout(this.#deb);
			this.#deb = null;
		}
	}

	#onDelta(f: SseFrame): void {
		const t = String(f.type ?? '');
		if (t.startsWith('wager_') || t === 'match_result') this.#debouncedReload();
	}

	// Coalesce a burst of deltas (a settle + a fee + a payout land together) into ONE refetch.
	#debouncedReload(): void {
		if (this.#deb || !this.#sid) return;
		this.#deb = setTimeout(() => {
			this.#deb = null;
			void this.load(this.#sid);
		}, 600);
	}
}

export const wallet = new WalletStore();
