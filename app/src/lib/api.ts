import { api } from './config';
import type { LeaderboardResponse, LeaderboardTab, LeaderboardPeriod } from './types';
import type { LeaderboardScope } from './boards';

/** The board response plus the server's echoed `scope` — used as the version-skew guard (a pre-scope
 *  server omits it or echoes `ranked`, so the store must not render its rows under a scoped view).
 *  Declared here (not types.ts, which is off-limits) as an extension of the shipped response shape. */
export type ScopedLeaderboardResponse = LeaderboardResponse & { scope?: string };

/**
 * GET /skinsync/leaderboard?tab=…&period=…&scope=…&limit=…
 * Live data source for the board. Same-origin in prod (nobd.net/app); Vite-proxied in dev.
 * `scope` defaults to `ranked` (legacy behaviour: ratings + tier titles + region fast-path).
 */
export async function fetchLeaderboard(
	tab: LeaderboardTab,
	period: LeaderboardPeriod,
	scope: LeaderboardScope = 'ranked',
	limit = 50,
	signal?: AbortSignal
): Promise<ScopedLeaderboardResponse> {
	const url = api(
		`/skinsync/leaderboard?tab=${encodeURIComponent(tab)}&period=${encodeURIComponent(period)}&scope=${encodeURIComponent(scope)}&limit=${limit}`
	);
	const res = await fetch(url, { signal, headers: { accept: 'application/json' } });
	if (!res.ok) throw new Error(`leaderboard ${res.status}`);
	const json = (await res.json()) as ScopedLeaderboardResponse;
	return json;
}
