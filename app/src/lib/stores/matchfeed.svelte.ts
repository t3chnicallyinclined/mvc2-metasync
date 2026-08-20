import { api } from '$lib/config';
import { getChannel, type SseChannel } from '$lib/rt.svelte';
import type { SseFrame } from '$lib/types';

// Live "match center" store. rune-$state off the app-wide `matches` SSE channel. On connect (and on a
// mode switch) it SEEDS from GET /skinsync/matches/feed?mode=<mode>&limit=20 (a snapshot of in-progress
// games + recent results for the selected mode) so the tab is never empty before the first live delta,
// then stays live. Two capped lists, both newest-first:
//   • results     — finished match_result deltas for the ACTIVE mode (cap 20 → 4 pages of 5)
//   • nowPlaying   — active pairs from match_start (all-mode; deltas carry no mode), dropped on
//                    match_end OR when their result lands
// The Live Results surface is mode-scoped (⚔ Ranked / 🎮 Lobby / 🏆 Tournament); Now Playing is not
// (match_start deltas don't carry a mode) so it seeds once and is maintained by the stream after.
// Modelled on ProfileStore.#applyMatch (the same channel) + LeaderboardStore's connect/disconnect shape.
// Types are declared locally (types.ts is off-limits).

const RESULTS_CAP = 20;
const NOWPLAYING_CAP = 24;

/** Live Results filter — which match origin feeds the board. `ranked` is the default (rating deltas). */
export type FeedMode = 'ranked' | 'lobby' | 'tourney';

export interface MatchResult {
	/** dedupe key — winner+loser+ts (provisional and its later verified copy share this). */
	key: string;
	winner: string;
	loser: string;
	winner_name: string;
	loser_name: string;
	verified: boolean;
	ts: number; // normalized epoch-ms
	/** match origin — ranked | lobby | tourney | money (undefined on older/mode-less deltas). */
	mode?: string;
	/** the WINNER's rating gain for a ranked result (loser's is the negative); undefined when unrated. */
	elo?: number;
	/** char-id triples for the arena matchup line (via charName); undefined until the seed carries them. */
	winner_team?: number[];
	loser_team?: number[];
	/** biggest combo landed in the set (hit count); undefined/0 → no callout. */
	combo?: number;
	/** highlight flags — one-character victory, flawless game, last-character comeback. */
	ocv?: boolean;
	perfect?: boolean;
	comeback?: boolean;
}

export interface NowPlaying {
	/** sorted sidA_sidB — stable across the start/end pair. */
	key: string;
	a: string;
	b: string;
	names: Record<string, string>;
	since: number;
}

type MatchFrame = SseFrame & {
	players?: unknown[];
	names?: Record<string, string>;
	winner?: unknown;
	loser?: unknown;
	winner_name?: unknown;
	loser_name?: unknown;
	verified?: unknown;
	ts?: unknown;
	mode?: unknown;
	elo?: unknown;
	winner_team?: unknown;
	loser_team?: unknown;
	combo?: unknown;
	ocv?: unknown;
	perfect?: unknown;
	comeback?: unknown;
};

// The bus stamps ids in epoch-ms (seq "1787174728540-1"), so a result ts is ms too — but a stray
// seconds value (< ~1e12) would render as "56y ago", so promote it defensively before display.
function normTs(x: unknown): number {
	const n = Number(x);
	if (!n || !isFinite(n)) return Date.now();
	return n < 1e12 ? n * 1000 : n;
}

/** Coerce a payload team field into a clean char-id array (or undefined when absent/empty). */
function toTeam(x: unknown): number[] | undefined {
	if (!Array.isArray(x)) return undefined;
	const ids = x.map(Number).filter((n) => Number.isFinite(n));
	return ids.length ? ids : undefined;
}

/** Order-independent key for a two-player pair. */
function pairKey(a: string, b: string): string {
	return a < b ? `${a}_${b}` : `${b}_${a}`;
}

export class MatchFeedStore {
	results = $state<MatchResult[]>([]);
	nowPlaying = $state<NowPlaying[]>([]);
	/** Active Live-Results filter — refetches the feed when changed. */
	mode = $state<FeedMode>('ranked');
	loading = $state(false);

	#unsub: (() => void) | null = null;
	#ch: SseChannel | null = null;
	#npSeeded = false; // now-playing is all-mode → seed once, then let the stream maintain it
	#reqId = 0;

	/** Whether the underlying stream is open + handshaken (rune-reactive via the channel). */
	get live(): boolean {
		return this.#ch?.connected ?? false;
	}

	/** Open the live subscription (idempotent). Call from a browser $effect/onMount. */
	connect() {
		void this.load(); // snapshot for the active mode so the tab isn't empty before the first delta
		if (this.#unsub) return;
		const ch = getChannel('matches');
		this.#ch = ch;
		this.#unsub = ch.subscribe((frame) => this.#apply(frame as MatchFrame));
	}

	disconnect() {
		if (this.#unsub) {
			this.#unsub();
			this.#unsub = null;
		}
	}

	/** Switch the Live-Results filter → clear stale rows + refetch that mode's snapshot. */
	setMode(m: FeedMode) {
		if (m === this.mode) return;
		this.mode = m;
		this.results = []; // instant clear so the board doesn't flash the old mode's rows
		void this.load();
	}

	/**
	 * Seed / refresh the results list for the ACTIVE mode from the feed snapshot, and seed now-playing
	 * once. Newest-first. A `#reqId` guard drops a stale response when a newer mode switch has fired.
	 * Merge (not blind replace) so a live delta that raced the fetch survives; rows from a different
	 * mode never carry across a switch (filtered by the active mode). A failed fetch keeps last-good.
	 */
	async load(): Promise<void> {
		const myReq = ++this.#reqId;
		const mode = this.mode;
		this.loading = true;
		try {
			const res = await fetch(api(`/skinsync/matches/feed?mode=${mode}&limit=${RESULTS_CAP}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) return; // keep-last-good; a later connect/switch retries
			const snap = (await res.json()) as { now_playing?: MatchFrame[]; results?: MatchFrame[] };
			if (myReq !== this.#reqId) return; // superseded by a newer mode switch

			const seeded = (Array.isArray(snap.results) ? snap.results : [])
				.map((d) => this.#toResult(d))
				.filter((r): r is MatchResult => r != null);
			const seen = new Set(seeded.map((r) => r.key));
			// carry only same-mode live rows the snapshot didn't include (raced the fetch) — newest-first.
			const carry = this.results.filter((r) => (r.mode ?? 'ranked') === mode && !seen.has(r.key));
			this.results = [...carry, ...seeded].slice(0, RESULTS_CAP);

			if (!this.#npSeeded) {
				const np = Array.isArray(snap.now_playing) ? snap.now_playing : [];
				for (let i = np.length - 1; i >= 0; i--) this.#onStart(np[i]); // oldest-first (prepends)
				this.#npSeeded = true;
			}
		} catch {
			// transient — keep last-good; the next connect/switch retries.
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}

	#apply(d: MatchFrame) {
		const type = String(d.type ?? '');
		if (type === 'connected') return; // handshake only
		if (type === 'match_start') this.#onStart(d);
		else if (type === 'match_end') this.#onEnd(d);
		else if (type === 'match_result') this.#onResult(d);
	}

	#onStart(d: MatchFrame) {
		const players = Array.isArray(d.players) ? d.players.map(String).filter(Boolean) : [];
		if (players.length < 2) return;
		const [a, b] = players;
		const key = pairKey(a, b);
		const names = d.names && typeof d.names === 'object' ? { ...d.names } : {};
		const existing = this.nowPlaying.find((p) => p.key === key);
		if (existing) {
			// same pair re-announced — refresh names, keep it where it is (and its since).
			this.nowPlaying = this.nowPlaying.map((p) =>
				p.key === key ? { ...p, names: { ...p.names, ...names } } : p
			);
			return;
		}
		const row: NowPlaying = { key, a, b, names, since: Date.now() };
		this.nowPlaying = [row, ...this.nowPlaying].slice(0, NOWPLAYING_CAP);
	}

	#onEnd(d: MatchFrame) {
		const players = Array.isArray(d.players) ? d.players.map(String).filter(Boolean) : [];
		if (players.length < 2) return;
		this.#dropPair(pairKey(players[0], players[1]));
	}

	/** Normalize a match_result frame (stream OR seed) into a row — including the richer detail fields. */
	#toResult(d: MatchFrame): MatchResult | null {
		const winner = String(d.winner ?? '');
		const loser = String(d.loser ?? '');
		if (!winner || !loser) return null;
		const ts = normTs(d.ts);
		const winner_name = String(d.winner_name ?? '') || winner;
		const loser_name = String(d.loser_name ?? '') || loser;
		const mode = typeof d.mode === 'string' && d.mode ? d.mode : undefined;
		// elo = the winner's rating gain; 0/absent for non-ranked → treat as "no delta" (undefined).
		const eloN = Number(d.elo);
		const elo = Number.isFinite(eloN) && eloN !== 0 ? Math.abs(eloN) : undefined;
		const comboN = Number(d.combo);
		const combo = Number.isFinite(comboN) && comboN > 1 ? Math.round(comboN) : undefined;
		return {
			key: `${winner}_${loser}_${ts}`,
			winner,
			loser,
			winner_name,
			loser_name,
			verified: d.verified === true,
			ts,
			mode,
			elo,
			winner_team: toTeam(d.winner_team),
			loser_team: toTeam(d.loser_team),
			combo,
			ocv: d.ocv === true,
			perfect: d.perfect === true,
			comeback: d.comeback === true
		};
	}

	#onResult(d: MatchFrame) {
		const row = this.#toResult(d);
		if (!row) return;

		// A finished result ends any "now playing" row for that pair — regardless of the active filter.
		this.#dropPair(pairKey(row.winner, row.loser));

		// Only surface it on the board when it belongs to the active mode (legacy mode-less → ranked).
		if ((row.mode ?? 'ranked') !== this.mode) return;

		const idx = this.results.findIndex((r) => r.key === row.key);
		if (idx >= 0) {
			// Provisional already shown → upgrade in place when a richer/verified copy lands (never
			// re-order, never duplicate). Prefer existing non-empty teams/flags over a barer delta.
			const cur = this.results[idx];
			const next: MatchResult = {
				...cur,
				verified: cur.verified || row.verified,
				winner_name: row.winner_name || cur.winner_name,
				loser_name: row.loser_name || cur.loser_name,
				mode: row.mode ?? cur.mode,
				elo: row.elo ?? cur.elo,
				winner_team: row.winner_team ?? cur.winner_team,
				loser_team: row.loser_team ?? cur.loser_team,
				combo: row.combo ?? cur.combo,
				ocv: cur.ocv || row.ocv,
				perfect: cur.perfect || row.perfect,
				comeback: cur.comeback || row.comeback
			};
			if (
				next.verified === cur.verified &&
				next.winner_name === cur.winner_name &&
				next.loser_name === cur.loser_name &&
				next.mode === cur.mode &&
				next.elo === cur.elo &&
				next.winner_team === cur.winner_team &&
				next.loser_team === cur.loser_team &&
				next.combo === cur.combo &&
				next.ocv === cur.ocv &&
				next.perfect === cur.perfect &&
				next.comeback === cur.comeback
			)
				return; // nothing changed — avoid a needless re-render
			this.results = this.results.map((r, i) => (i === idx ? next : r));
			return;
		}

		this.results = [row, ...this.results].slice(0, RESULTS_CAP);
	}

	#dropPair(key: string) {
		if (this.nowPlaying.some((p) => p.key === key)) {
			this.nowPlaying = this.nowPlaying.filter((p) => p.key !== key);
		}
	}
}

export const matchfeed = new MatchFeedStore();
