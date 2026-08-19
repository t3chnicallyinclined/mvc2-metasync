import { api } from '$lib/config';

// MvC2 team tier list store — the dataset's signature knowledge surface. rune-$state, modelled on
// RegionsStore: one fetch, keep-last-good on error (never blank a list that's already showing).
//   • data: GET /skinsync/tierlist  → { teams:[{team:"13,31,49", games, wins, winrate}, …] }
//           (already sorted by winrate desc; `team` = 3 comma-separated char-ids)
// Optional region filter (?country=US / ?city=Name) is supported by the server but skipped in the v1
// UI — the min-games gate is the priority. Types declared locally (types.ts is off-limits).

export interface TeamRow {
	team: string; // "13,31,49" — 3 comma-separated char-ids
	games: number;
	wins: number;
	winrate: number; // 0–100 (float, e.g. 97.7)
}

interface TierlistResponse {
	teams?: TeamRow[];
}

export class TierlistStore {
	teams = $state<TeamRow[]>([]);
	loading = $state(false);
	error = $state<string | null>(null);
	lastLoaded = $state(0);

	#reqId = 0;

	async load(country?: string, city?: string): Promise<void> {
		const myReq = ++this.#reqId;
		this.loading = true;
		const qs = new URLSearchParams();
		if (country) qs.set('country', country);
		if (city) qs.set('city', city);
		const q = qs.toString();
		try {
			const res = await fetch(api(`/skinsync/tierlist${q ? `?${q}` : ''}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) throw new Error(`tierlist ${res.status}`);
			const json = (await res.json()) as TierlistResponse;
			if (myReq !== this.#reqId) return; // superseded
			const list = (json.teams ?? []).filter((t) => t && typeof t.team === 'string');
			// Server sorts by winrate desc; sort defensively so the list is deterministic regardless.
			list.sort((a, b) => (b.winrate ?? 0) - (a.winrate ?? 0) || (b.games ?? 0) - (a.games ?? 0));
			this.teams = list;
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.teams on a transient blip.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}
}

export const tierlist = new TierlistStore();
