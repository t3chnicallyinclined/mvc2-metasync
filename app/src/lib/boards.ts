import type { LeaderboardTab, LeaderboardPeriod, Player, BoardItem } from './types';
import { rankOf, gamesOf, RK_PLATE, TIER_FLOOR } from './ranks';

// Board metadata ported from web/index.html (LB_MAST / LB_STAT_INFO / LB_UNIT / LB_STAT_LABEL).
// Phase 1 mirrors the player-stat boards; the character 'tierlist' board (different data shape /
// endpoint) is deferred.

/**
 * Board SCOPE (gs-217 game modes): which games feed the boards. `ranked` is the ELO ladder — it
 * carries ratings + tier titles. `lobby`/`tourney` are pure records off the typed match log (NO
 * rating/rank on their rows). Declared here — not types.ts (off-limits) — as the board vocabulary.
 */
export type LeaderboardScope = 'ranked' | 'lobby' | 'tourney';

export const SCOPES: { id: LeaderboardScope; label: string; short: string; icon: string }[] = [
	{ id: 'ranked', label: 'Ranked', short: 'Rank', icon: '⚔️' },
	{ id: 'lobby', label: 'Lobby', short: 'Lobby', icon: '🎮' },
	{ id: 'tourney', label: 'Tournament', short: 'Tourney', icon: '🏆' }
];

// The stat-tab strip. NOTE the 'rating' tab is labelled "Rating" (not "Ranked") on purpose — the
// scope switch owns the word "Ranked" now, so the ELO board reads as "Rating" to avoid two "Ranked"
// controls sitting side-by-side (§4 design lesson).
export const TABS: { id: LeaderboardTab; label: string }[] = [
	{ id: 'rating', label: 'Rating' },
	{ id: 'wins', label: 'Wins' },
	{ id: 'streak', label: 'Streak' },
	{ id: 'ocv', label: 'OCV' },
	{ id: 'perfect', label: 'Perfect' },
	{ id: 'comeback', label: 'Comeback' },
	{ id: 'combo', label: 'Combo' },
	{ id: 'deficit', label: 'Clutch' }
];

export const PERIODS: { id: LeaderboardPeriod; label: string }[] = [
	{ id: 'all', label: 'All-time' },
	{ id: 'day', label: 'Today' },
	{ id: 'week', label: 'Week' },
	{ id: 'month', label: 'Month' }
];

// [title, ghost-watermark, accent] — the masthead per board.
export const MAST: Record<LeaderboardTab, [string, string, string]> = {
	rating: ['MARVEL LADDER', 'RANKED', '#e8b93c'],
	wins: ['MOST WINS', 'WINS', '#4ade80'],
	streak: ['WIN STREAKS', 'STREAK', '#ff8a3c'],
	ocv: ['ONE-CHARACTER VICTORIES', 'OCV', '#ff5555'],
	perfect: ['PERFECTS', 'PERFECT', '#9fd4ef'],
	comeback: ['COMEBACKS', 'COMEBACK', '#b98cff'],
	combo: ['MAX COMBOS', 'COMBO', '#4aa8ff'],
	deficit: ['CLUTCH WINS', 'CLUTCH', '#34d39a']
};

// The right-aligned numeric column header per board.
export const STAT_LABEL: Record<LeaderboardTab, string> = {
	rating: 'Rating',
	wins: 'Wins',
	streak: 'Streak',
	ocv: 'OCVs',
	perfect: 'Perfects',
	comeback: 'Comebacks',
	combo: 'Max Combo',
	deficit: 'Clutch'
};

// Short description under the masthead (condensed from LB_STAT_INFO).
export const STAT_DESC: Record<LeaderboardTab, string> = {
	rating:
		'A skill rating that rises when you beat stronger players and dips on losses. Iron → Galactus. Everyone starts at 1000; play 5 games to get ranked.',
	wins: "Every match you've won across all your synced games.",
	streak: 'Your longest run of consecutive wins with no loss in between.',
	ocv: 'Sweeping all three of the opponent’s characters with a single character — never tagging out.',
	perfect: 'Winning a game without your team’s health ever being touched.',
	comeback: 'Winning after being reduced to your last character while the opponent still had two or more.',
	combo: 'The highest single-combo hit count you’ve landed.',
	deficit: 'The largest character deficit you’ve overcome to win.'
};

export const PERIOD_LABEL: Record<LeaderboardPeriod, string> = {
	all: 'all-time',
	day: 'today',
	week: 'this week',
	month: 'this month'
};

/** The value shown in the numeric column for a given board. */
export function statValue(p: Player, tab: LeaderboardTab): number {
	return tab === 'rating' ? (p.rating ?? 1000) : (p.stat ?? 0);
}

/** True when the top-3 podium should render (not searching, at least 3 players). */
export function podiumOn(shown: Player[], searching: boolean): boolean {
	return !searching && shown.length >= 3;
}

/**
 * Flatten the board into rows + tier-cutline seams — mirrors renderLeaderboard() in index.html.
 * When the podium is showing, ranks 1–3 are lifted out and the body starts at #4. Ranked boards get
 * WoW-cutoff seams where the tier changes + an "unclaimed Galactus" line when nobody is 1500+.
 */
export function buildBoardItems(
	shown: Player[],
	tab: LeaderboardTab,
	searching: boolean
): BoardItem[] {
	const items: BoardItem[] = [];
	const podium = podiumOn(shown, searching);
	const start = podium ? 4 : 1;
	const rows = podium ? shown.slice(3) : shown;
	const seams = tab === 'rating' && !searching;

	if (seams && shown.length && (shown[0].rating ?? 1000) < 1500) {
		items.push({
			kind: 'cut',
			key: 'cut-galactus',
			label: '🪐 GALACTUS · 1500 — UNCLAIMED',
			color: '#ff7ae0'
		});
	}

	let prev: Player | null = start > 1 ? (shown[start - 2] ?? null) : null;
	rows.forEach((p, i) => {
		const pos = start + i;
		if (seams) {
			const cur = rankOf(p.rating, gamesOf(p));
			const pv = prev ? rankOf(prev.rating, gamesOf(prev)) : null;
			if (pv && cur.s !== pv.s && cur.n !== 'Civilian' && pv.n !== 'Civilian') {
				items.push({
					kind: 'cut',
					key: `cut-${pv.s}-${pos}`,
					label: `${pv.n.toUpperCase()} · ${TIER_FLOOR[pv.s] ?? ''}`,
					color: (RK_PLATE[pv.s] ?? RK_PLATE.civilian)[0]
				});
			}
		}
		items.push({ kind: 'row', key: p.steamid || `pos-${pos}`, player: p, pos });
		prev = p;
	});
	return items;
}
