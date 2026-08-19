import { api } from '$lib/config';

// Companion store for a profile's RIVALRIES + recent FORM, off the public read endpoint:
//   GET /skinsync/playerstats?steamid=…
//     → { found, form:[1,1,0,…] (W=1/L=0, NEWEST FIRST), nemesis, victim, vs[] }
// nemesis = the opponent this player LOSES to most; victim = the one they BEAT most. Both wins/losses
// are counted from THIS player's perspective and may be null when there aren't enough games. Modelled on
// ProfileStore: fetch on demand, reqId-guarded, keep-last-good on a transient blip (never blank a card
// that's already showing). Types are declared locally (types.ts is off-limits).

export interface Rival {
	opp_id: string;
	name?: string;
	avatar?: string;
	cc?: string;
	wins: number; // this player's wins vs that opponent
	losses: number; // this player's losses vs that opponent
}

export interface PlayerStats {
	found: boolean;
	steamid: string;
	form?: number[]; // 1=W / 0=L, newest first
	nemesis?: Rival | null;
	victim?: Rival | null;
}

export class PlayerStatsStore {
	steamid = $state('');
	data = $state<PlayerStats | null>(null);
	loading = $state(false);
	error = $state<string | null>(null);

	#reqId = 0;

	async load(steamid: string): Promise<void> {
		const sid = String(steamid || '');
		if (sid !== this.steamid) {
			// New player → drop the previous rivalries immediately (keep-last-good is per-player only).
			this.steamid = sid;
			this.data = null;
			this.error = null;
		}
		if (!sid) return;
		const myReq = ++this.#reqId;
		this.loading = true;
		try {
			const res = await fetch(api(`/skinsync/playerstats?steamid=${encodeURIComponent(sid)}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) throw new Error(`playerstats ${res.status}`);
			const json = (await res.json()) as PlayerStats;
			if (myReq !== this.#reqId) return; // superseded by a newer load
			this.data = json;
			this.error = null;
		} catch (e) {
			if (myReq !== this.#reqId) return;
			// keep-last-good — do NOT clear this.data on a transient blip for the same player.
			this.error = e instanceof Error ? e.message : 'error';
		} finally {
			if (myReq === this.#reqId) this.loading = false;
		}
	}
}
