// Shapes mirror the live skinsync API (GET /skinsync/leaderboard) + the SSE bus.

/** One row from GET /skinsync/leaderboard?tab=…&period=…  */
export interface Player {
	steamid: string;
	name: string;
	cc?: string; // ISO-3166 alpha-2 country code ("represent")
	avatar?: string; // Steam avatar URL
	rating: number; // ELO
	wins: number;
	losses: number;
	confirmed_wins?: number; // wins verified by both-agree / replay
	verified_wins?: number;
	stat?: number; // the active tab's stat value (server-computed)
	rank?: string; // server-supplied tier name — never trusted; client derives from rating+games
}

export interface LeaderboardResponse {
	players: Player[];
	field?: string;
	period?: string;
	tab?: string;
}

export type LeaderboardTab =
	| 'rating'
	| 'wins'
	| 'streak'
	| 'ocv'
	| 'perfect'
	| 'comeback'
	| 'combo'
	| 'deficit';

export type LeaderboardPeriod = 'all' | 'day' | 'week' | 'month';

/** A `delta` frame on the SSE bus (leaderboard channel). */
export interface LeaderboardDelta {
	type: string; // "leaderboard"
	reason?: string; // "match"
	steamids?: string[];
}

/** A flat board item — either a player row or a tier-cutline divider (rating board only). */
export type BoardItem =
	| { kind: 'row'; key: string; player: Player; pos: number | null }
	| { kind: 'cut'; key: string; label: string; color: string };

/** Generic SSE frame payload as parsed from `data:`. */
export interface SseFrame {
	channel?: string;
	seq?: string;
	type?: string;
	[k: string]: unknown;
}
