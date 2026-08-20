import { api } from '$lib/config';
import { getChannel, type SseChannel } from '$lib/rt.svelte';
import type { SseFrame } from '$lib/types';

// Live "match center" store. rune-$state off the app-wide `matches` SSE channel. On connect it SEEDS once
// from GET /skinsync/matches/feed (a snapshot of in-progress games + recent results) so the tab is never
// empty before the first live delta, then stays live — replaying the snapshot rows through the SAME
// #onStart/#onResult handlers the stream uses (no new parsing). Two capped lists, both newest-first:
//   • results     — finished match_result deltas (cap 40)
//   • nowPlaying   — active pairs from match_start, dropped on match_end OR when their result lands
// Modelled on ProfileStore.#applyMatch (the same channel) + LeaderboardStore's connect/disconnect shape.
// Types are declared locally (types.ts is off-limits).

const RESULTS_CAP = 40;
const NOWPLAYING_CAP = 24;

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
};

// The bus stamps ids in epoch-ms (seq "1787174728540-1"), so a result ts is ms too — but a stray
// seconds value (< ~1e12) would render as "56y ago", so promote it defensively before display.
function normTs(x: unknown): number {
	const n = Number(x);
	if (!n || !isFinite(n)) return Date.now();
	return n < 1e12 ? n * 1000 : n;
}

/** Order-independent key for a two-player pair. */
function pairKey(a: string, b: string): string {
	return a < b ? `${a}_${b}` : `${b}_${a}`;
}

export class MatchFeedStore {
	results = $state<MatchResult[]>([]);
	nowPlaying = $state<NowPlaying[]>([]);

	#unsub: (() => void) | null = null;
	#ch: SseChannel | null = null;
	#seeded = false;

	/** Whether the underlying stream is open + handshaken (rune-reactive via the channel). */
	get live(): boolean {
		return this.#ch?.connected ?? false;
	}

	/** Open the live subscription (idempotent). Call from a browser $effect/onMount. */
	connect() {
		void this.#seed(); // one-shot snapshot so the tab isn't empty before the first live delta
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

	/**
	 * Seed the two lists once from the feed snapshot (THE fix for the empty Match tab). Fetches the same
	 * shapes the stream pushes and replays them through #onStart/#onResult — OLDEST-first, because both
	 * handlers prepend, so this restores the server's newest-first order and lets a live delta that races
	 * the seed still sort to the top. Seeds once; a failed fetch resets the guard so the next connect (e.g.
	 * the visibility-change re-open) retries — a blip must never leave the feed permanently blank.
	 */
	async #seed(): Promise<void> {
		if (this.#seeded) return;
		this.#seeded = true;
		try {
			const res = await fetch(api('/skinsync/matches/feed?limit=40'), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) {
				this.#seeded = false;
				return;
			}
			const snap = (await res.json()) as { now_playing?: MatchFrame[]; results?: MatchFrame[] };
			const np = Array.isArray(snap.now_playing) ? snap.now_playing : [];
			const rs = Array.isArray(snap.results) ? snap.results : [];
			for (let i = np.length - 1; i >= 0; i--) this.#onStart(np[i]);
			for (let i = rs.length - 1; i >= 0; i--) this.#onResult(rs[i]);
		} catch {
			this.#seeded = false; // transient — let the next connect retry
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

	#onResult(d: MatchFrame) {
		const winner = String(d.winner ?? '');
		const loser = String(d.loser ?? '');
		if (!winner || !loser) return;
		const ts = normTs(d.ts);
		const verified = d.verified === true;
		const key = `${winner}_${loser}_${ts}`;
		const winner_name = String(d.winner_name ?? '') || winner;
		const loser_name = String(d.loser_name ?? '') || loser;
		const mode = typeof d.mode === 'string' && d.mode ? d.mode : undefined;
		// elo = the winner's rating gain; 0/absent for non-ranked → treat as "no delta" (undefined).
		const eloN = Number(d.elo);
		const elo = Number.isFinite(eloN) && eloN !== 0 ? Math.abs(eloN) : undefined;

		// A finished result ends any "now playing" row for that pair.
		this.#dropPair(pairKey(winner, loser));

		const idx = this.results.findIndex((r) => r.key === key);
		if (idx >= 0) {
			// Provisional already shown → upgrade in place when the verified copy lands (never re-order,
			// never duplicate). Also refresh names/mode/elo in case the verified pass carries better ones.
			const cur = this.results[idx];
			const next: MatchResult = {
				...cur,
				verified: cur.verified || verified,
				winner_name: winner_name || cur.winner_name,
				loser_name: loser_name || cur.loser_name,
				mode: mode ?? cur.mode,
				elo: elo ?? cur.elo
			};
			if (
				next.verified === cur.verified &&
				next.winner_name === cur.winner_name &&
				next.loser_name === cur.loser_name &&
				next.mode === cur.mode &&
				next.elo === cur.elo
			)
				return; // nothing changed — avoid a needless re-render
			this.results = this.results.map((r, i) => (i === idx ? next : r));
			return;
		}

		const row: MatchResult = { key, winner, loser, winner_name, loser_name, verified, ts, mode, elo };
		this.results = [row, ...this.results].slice(0, RESULTS_CAP);
	}

	#dropPair(key: string) {
		if (this.nowPlaying.some((p) => p.key === key)) {
			this.nowPlaying = this.nowPlaying.filter((p) => p.key !== key);
		}
	}
}

export const matchfeed = new MatchFeedStore();
