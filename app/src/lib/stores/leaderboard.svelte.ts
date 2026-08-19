import { fetchLeaderboard } from '$lib/api';
import { getChannel } from '$lib/rt.svelte';
import type { Player, LeaderboardTab, LeaderboardPeriod } from '$lib/types';

// The live board store. rune-$state so consumers re-render only on the fields that change (no
// full-DOM rebuild — the exact CPU tax the rewrite exists to kill). Wired to the shipped bus:
//   • data:  GET /skinsync/leaderboard?tab=…&period=…&limit=50
//   • live:  SSE channel "leaderboard" → on `delta`, debounced refetch (~500ms), matching the old app.
// Keep-last-good on fetch error: a transient blip (server restart / a live-refresh racing one) must
// never blank a board that's already showing (the bug we fixed in the old app).

export class LeaderboardStore {
	tab = $state<LeaderboardTab>('rating');
	period = $state<LeaderboardPeriod>('all');
	players = $state<Player[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	lastLoaded = $state(0);
	/** steamids whose value changed on the last live refetch — drives the one-shot row flash. */
	flashIds = $state<Set<string>>(new Set());

	#unsub: (() => void) | null = null;
	#deb: ReturnType<typeof setTimeout> | null = null;
	#flashTimer: ReturnType<typeof setTimeout> | null = null;
	#reqId = 0;

	/** Ranked (ELO) is cumulative skill → always all-time; the period switch is hidden for it. */
	get periodLocked(): boolean {
		return this.tab === 'rating';
	}

	setTab(t: LeaderboardTab) {
		if (t === this.tab) return;
		this.tab = t;
		if (this.periodLocked) this.period = 'all';
		void this.load(true);
	}

	setPeriod(p: LeaderboardPeriod) {
		if (p === this.period || this.periodLocked) return;
		this.period = p;
		void this.load(true);
	}

	async load(reset = false): Promise<void> {
		const myReq = ++this.#reqId;
		this.loading = true;
		const tab = this.tab;
		const period = this.period;
		try {
			const res = await fetchLeaderboard(tab, period, 50);
			if (myReq !== this.#reqId) return; // a newer request superseded this one
			const next = res.players ?? [];
			if (!reset) this.#computeFlash(next);
			this.players = next;
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.players.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}

	#computeFlash(next: Player[]) {
		if (!this.players.length) return;
		const prev = new Map(this.players.map((p) => [p.steamid, p]));
		const changed = new Set<string>();
		for (const p of next) {
			const o = prev.get(p.steamid);
			if (
				o &&
				(o.rating !== p.rating ||
					o.stat !== p.stat ||
					o.wins !== p.wins ||
					o.losses !== p.losses)
			) {
				changed.add(p.steamid);
			}
		}
		if (!changed.size) return;
		this.flashIds = changed;
		if (this.#flashTimer) clearTimeout(this.#flashTimer);
		this.#flashTimer = setTimeout(() => {
			this.flashIds = new Set();
		}, 900);
	}

	/** Open the live subscription (idempotent). Call from a browser $effect. */
	connect() {
		if (this.#unsub) return;
		const ch = getChannel('leaderboard');
		this.#unsub = ch.subscribe((frame) => {
			if (frame.type === 'connected') return; // handshake only — no refetch
			this.#debouncedReload();
		});
	}

	disconnect() {
		if (this.#unsub) {
			this.#unsub();
			this.#unsub = null;
		}
		if (this.#deb) {
			clearTimeout(this.#deb);
			this.#deb = null;
		}
	}

	// Coalesce a burst of deltas (a run of matches) into ONE refetch (~500ms) — mirrors rtLeaderboardRefresh.
	#debouncedReload() {
		if (this.#deb) return;
		this.#deb = setTimeout(() => {
			this.#deb = null;
			void this.load();
		}, 500);
	}
}

export const leaderboard = new LeaderboardStore();
