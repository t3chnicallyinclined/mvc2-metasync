import { api } from './config';
import type { LeaderboardResponse, LeaderboardTab, LeaderboardPeriod } from './types';

/**
 * GET /skinsync/leaderboard?tab=…&period=…&limit=…
 * Live data source for the board. Same-origin in prod (nobd.net/app); Vite-proxied in dev.
 */
export async function fetchLeaderboard(
	tab: LeaderboardTab,
	period: LeaderboardPeriod,
	limit = 50,
	signal?: AbortSignal
): Promise<LeaderboardResponse> {
	const url = api(`/skinsync/leaderboard?tab=${encodeURIComponent(tab)}&period=${encodeURIComponent(period)}&limit=${limit}`);
	const res = await fetch(url, { signal, headers: { accept: 'application/json' } });
	if (!res.ok) throw new Error(`leaderboard ${res.status}`);
	const json = (await res.json()) as LeaderboardResponse;
	return json;
}
