import { api } from '$lib/config';
import { getChannel } from '$lib/rt.svelte';
import { statusRank, type TournamentSummary } from '$lib/tourney';

// Tournament BROWSE store. rune-$state, modelled on LeaderboardStore: one fetch, keep-last-good on
// error, and a live subscription to the shared `tourney_index` SSE channel — on any delta
// (tourney_created / tourney_updated / tourney_deleted) we DEBOUNCED-REFETCH the whole list, exactly
// like the leaderboard reacts to its channel (the list is small; a refetch is the simplest correct move).
//   • data: GET /skinsync/tourney/list  → { ok, tournaments:[…summary…] }
//   • live: SSE channel "tourney_index" → debounced refetch.

interface ListResponse {
	ok?: boolean;
	tournaments?: TournamentSummary[];
}

export class TournamentsStore {
	list = $state<TournamentSummary[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	lastLoaded = $state(0);

	#reqId = 0;
	#unsub: (() => void) | null = null;
	#deb: ReturnType<typeof setTimeout> | null = null;

	async load(): Promise<void> {
		const myReq = ++this.#reqId;
		this.loading = true;
		try {
			const res = await fetch(api('/skinsync/tourney/list'), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) throw new Error(`tourney list ${res.status}`);
			const json = (await res.json()) as ListResponse;
			if (myReq !== this.#reqId) return; // superseded
			this.list = sortTournaments(json.tournaments ?? []);
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — never blank a list that's already showing on a transient blip.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}

	/** Open the live subscription (idempotent). Call from a browser $effect/onMount. */
	connect(): void {
		if (this.#unsub) return;
		const ch = getChannel('tourney_index');
		this.#unsub = ch.subscribe((frame) => {
			if (frame.type === 'connected') return; // handshake only
			this.#debouncedReload();
		});
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

	// Coalesce a burst of index deltas (a run of edits) into ONE refetch (~500ms) — mirrors the board.
	#debouncedReload(): void {
		if (this.#deb) return;
		this.#deb = setTimeout(() => {
			this.#deb = null;
			void this.load();
		}, 500);
	}
}

/** Running first, then check-in, open, upcoming; finished/cancelled last. Ties → soonest start (or,
 *  for finished events, most-recent first). Deterministic so the grid never jitters between refetches. */
export function sortTournaments(list: TournamentSummary[]): TournamentSummary[] {
	return list.slice().sort((a, b) => {
		const ra = statusRank(a.status);
		const rb = statusRank(b.status);
		if (ra !== rb) return ra - rb;
		const sa = a.starts_ms ?? 0;
		const sb = b.starts_ms ?? 0;
		return ra >= 4 ? sb - sa : sa - sb; // done/cancelled newest-first; active soonest-first
	});
}

export const tournaments = new TournamentsStore();
