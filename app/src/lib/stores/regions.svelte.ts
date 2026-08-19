import { api } from '$lib/config';

// Regions ("represent") store. rune-$state, modelled on LeaderboardStore: one fetch, keep-last-good
// on error. The list is small (one row per city ladder) so no virtualization / live channel is needed
// — a plain fetch snapshot is the right call for Phase 1b. Types declared locally (types.ts off-limits).
//   • data: GET /skinsync/regions  → { ok, level, min_games, regions:[…], sort }

export interface RegionTop {
	name?: string;
	steamid?: string;
	avatar?: string;
	cc?: string;
	wins?: number;
}

export interface Region {
	name: string; // city (or region) name
	region?: string; // scene/region label, e.g. "SoCal"
	cc?: string;
	country?: string;
	players?: number;
	games?: number;
	wins?: number;
	losses?: number;
	avg_rating?: number;
	top?: RegionTop;
}

interface RegionsResponse {
	ok?: boolean;
	level?: string;
	min_games?: number;
	sort?: string;
	regions?: Region[];
}

export class RegionsStore {
	regions = $state<Region[]>([]);
	level = $state('city');
	minGames = $state(5);
	loading = $state(false);
	error = $state<string | null>(null);
	lastLoaded = $state(0);

	#reqId = 0;

	async load(): Promise<void> {
		const myReq = ++this.#reqId;
		this.loading = true;
		try {
			const res = await fetch(api('/skinsync/regions'), { headers: { accept: 'application/json' } });
			if (!res.ok) throw new Error(`regions ${res.status}`);
			const json = (await res.json()) as RegionsResponse;
			if (myReq !== this.#reqId) return;
			// Server already sorts by wins, but sort defensively so the board is deterministic.
			const list = (json.regions ?? []).slice().sort((a, b) => (b.wins ?? 0) - (a.wins ?? 0));
			this.regions = list;
			this.level = json.level ?? 'city';
			this.minGames = json.min_games ?? 5;
			this.error = null;
			this.lastLoaded = Date.now();
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.regions on a transient blip.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}
}

export const regions = new RegionsStore();
