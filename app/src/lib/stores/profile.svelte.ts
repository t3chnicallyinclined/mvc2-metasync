import { api } from '$lib/config';
import { getChannel } from '$lib/rt.svelte';
import type { SseFrame } from '$lib/types';

// Public player profile store. rune-$state, modelled on LeaderboardStore: fetch on demand, keep the
// last-good card on a transient error (never blank a card that's already showing), and — as a bonus —
// patch the "🟢 in a match now" banner live off the app-wide `matches` SSE channel (push-only, no poll).
//   • data:  GET /skinsync/profile?steamid=…
//   • live:  SSE channel "matches" → match_start/match_end/match_result involving THIS steamid.
// Types are declared locally (types.ts is off-limits) and mirror the live /profile payload.

export interface RecentMatch {
	opp: string;
	opp_id?: string;
	my_team?: number[];
	opp_team?: number[];
	won: boolean;
	winner?: string;
	loser?: string;
	ocv?: boolean;
	perfect?: boolean;
	comeback?: boolean;
	combo?: number;
	meters?: number;
	elo?: number;
	confirmed?: boolean;
	verified?: boolean;
	attested?: boolean;
	ts?: number;
	mid?: string;
	match_key?: string;
	mode?: string; // "ranked" | "lobby" | "tourney" | "money" (server-derived from ingest stamps)
}

export interface ModeRecord {
	wins: number;
	losses: number;
	public?: boolean;
}

export interface CurrentMatch {
	opp?: string;
	opp_name?: string;
	since?: number;
	my_chars?: number[];
	opp_chars?: number[];
}

export interface Profile {
	found: boolean;
	steamid: string;
	name?: string;
	aliases?: string[];
	avatar?: string;
	cc?: string;
	country?: string;
	city?: string;
	region?: string;
	rank?: string; // server-supplied — never trusted; client derives tier from rating+games
	rating?: number;
	peak_rating?: number;
	wins?: number;
	losses?: number;
	verified_wins?: number;
	ocvs?: number;
	comebacks?: number;
	perfects?: number;
	meters?: number;
	best_streak?: number;
	best_combo?: number;
	best_chip?: number;
	best_comeback?: number;
	best_damage?: number;
	current_match?: CurrentMatch | null;
	recent?: RecentMatch[];
	// Game-mode records (ranked/lobby/tournament/money policy). tourney+money are public; lobby is
	// owner-or-public (null when hidden). Rebuild-derived server-side.
	season_registered?: boolean;
	tourney?: ModeRecord;
	money?: ModeRecord;
	lobby?: ModeRecord | null;
}

type MatchFrame = SseFrame & {
	players?: unknown[];
	names?: Record<string, string>;
	winner?: unknown;
	loser?: unknown;
};

export class ProfileStore {
	steamid = $state('');
	data = $state<Profile | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);
	lastLoaded = $state(0);

	#reqId = 0;
	#unsub: (() => void) | null = null;

	async load(steamid: string): Promise<void> {
		const sid = String(steamid || '');
		if (sid !== this.steamid) {
			// A different player → drop the previous card immediately (keep-last-good is per-player only,
			// so we never flash player A's stats under player B's URL).
			this.steamid = sid;
			this.data = null;
			this.error = null;
		}
		if (!sid) return;
		const myReq = ++this.#reqId;
		this.loading = true;
		try {
			const res = await fetch(api(`/skinsync/profile?steamid=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) throw new Error(`profile ${res.status}`);
			const json = (await res.json()) as Profile;
			if (myReq !== this.#reqId) return; // a newer load superseded this one
			this.data = json;
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.data on a transient blip for the same player.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}

	/** Open the live current-match subscription (idempotent). Call from a browser $effect/onMount. */
	connect() {
		if (this.#unsub) return;
		const ch = getChannel('matches');
		this.#unsub = ch.subscribe((frame) => this.#applyMatch(frame as MatchFrame));
	}

	disconnect() {
		if (this.#unsub) {
			this.#unsub();
			this.#unsub = null;
		}
	}

	// Patch the current_match banner from a `matches` delta (mirrors the old pfLiveMatchDelta).
	#applyMatch(d: MatchFrame) {
		const cur = this.data;
		if (!cur || !cur.found || !this.steamid) return;
		const sid = this.steamid;
		const type = String(d.type ?? '');
		const players = Array.isArray(d.players) ? d.players.map(String) : [];
		if (type === 'match_start' && players.includes(sid)) {
			const opp = players.find((x) => x !== sid) ?? '';
			const opp_name = (d.names && d.names[opp]) || 'opponent';
			this.data = { ...cur, current_match: { opp, opp_name } };
		} else if (
			(type === 'match_end' && players.includes(sid)) ||
			(type === 'match_result' && (String(d.winner) === sid || String(d.loser) === sid))
		) {
			if (cur.current_match) this.data = { ...cur, current_match: null };
		}
	}
}
