// Tournament shapes + pure display helpers. Types are declared locally (types.ts is off-limits) and
// MIRROR the live skinsync tournament payloads (GET /skinsync/tourney/list · /tourney/get and the
// per-tournament SSE stream). The server model (metasync-srv/skinsync/src/tourney.rs) is the source of
// truth for every field name here — kept in sync with it.

// ── browse-card summary (GET /skinsync/tourney/list → tournaments[]) ────────────────────────────────
export interface TournamentSummary {
	id: string;
	name: string;
	format?: string; // "double" | "single" | …
	status?: string; // draft | open | checkin | running | done | cancelled
	online?: boolean;
	cc?: string;
	city?: string;
	country?: string;
	region?: string;
	cap?: number; // 0 = no explicit cap
	entrants?: number; // active registration count
	entry_coins?: number; // 🪙 QUARTERS stake per entrant (0 = free)
	entry_fee_cents?: number; // real-money fee (0 = free)
	starts_ms?: number;
	reg_open_ms?: number;
	reg_close_ms?: number;
	banner_url?: string;
	stream_url?: string;
	to_steamid?: string;
}

// ── full document (GET /skinsync/tourney/get?id= → tournament, and the SSE snapshot's `tournament`) ──
export interface Registration {
	steamid: string;
	seed?: number; // 1-based; 0 = not yet seeded
	seed_source?: string; // "elo" | "manual" | "random"
	team?: number[]; // declared 3-char comp (char ids)
	checked_in?: boolean;
	checkin_ms?: number;
	status?: string; // registered | waitlisted | checked_in | dropped | dq
	registered_ms?: number;
}

/** One node of a generated double-elimination bracket. Every field is optional — render defensively. */
export interface BracketMatch {
	id: number;
	bracket?: string; // "winners" | "losers" | "grand"
	round?: number;
	p1?: string | null; // a SteamID once known
	p2?: string | null;
	p1_from?: string; // provenance label while TBD: "Winner of #3" / "Seed 5"
	p2_from?: string;
	p1_bye?: boolean;
	p2_bye?: boolean;
	winner?: string | null;
	loser?: string | null;
	score?: string;
	best_of?: number;
	state?: string; // pending | ready | live | done | bye | void
	host?: string;
	lobby_id?: string;
	on_stream?: boolean;
}

export interface Bracket {
	size?: number;
	matches?: BracketMatch[];
	wb_final?: number;
	lb_final?: number | null;
	gf?: number | null;
	gf_reset?: number | null;
	champion?: string | null;
}

export interface TournamentDoc {
	id: string;
	name?: string;
	game?: string; // "mvc2"
	format?: string;
	status?: string;
	online?: boolean;
	host_mode?: string;
	hosts?: unknown[];
	co_tos?: string[];
	to_steamid?: string;
	cc?: string;
	city?: string;
	country?: string;
	region?: string;
	banner_url?: string;
	discord_url?: string;
	stream_url?: string;
	cap?: number;
	entrants?: number;
	entry_coins?: number;
	entry_fee_cents?: number;
	ft_winners?: number;
	ft_losers?: number;
	ft_grands?: number;
	reg_open_ms?: number;
	reg_close_ms?: number;
	checkin_open_ms?: number;
	checkin_close_ms?: number;
	created_ms?: number;
	starts_ms?: number;
	rules_md?: string;
	registrations?: Registration[];
	bracket?: Bracket | null;
}

// ── display helpers (pure) ──────────────────────────────────────────────────────────────────────────

export type PillCls = 'good' | 'gold' | 'live' | 'muted';

/** Status → a pill label + variant. open=green, checkin/running=gold/live, done/cancelled=muted. */
export function statusMeta(status?: string): { label: string; cls: PillCls } {
	switch ((status ?? '').toLowerCase()) {
		case 'open':
			return { label: 'OPEN', cls: 'good' };
		case 'checkin':
			return { label: 'CHECK-IN', cls: 'gold' };
		case 'running':
			return { label: 'LIVE', cls: 'live' };
		case 'done':
			return { label: 'COMPLETE', cls: 'muted' };
		case 'cancelled':
			return { label: 'CANCELLED', cls: 'muted' };
		case 'draft':
			return { label: 'DRAFT', cls: 'muted' };
		default:
			return { label: (status ?? '').toUpperCase() || 'UPCOMING', cls: 'muted' };
	}
}

/** Sort bucket for a status — running first, then check-in, open, then finished/cancelled. */
export function statusRank(status?: string): number {
	switch ((status ?? '').toLowerCase()) {
		case 'running':
			return 0;
		case 'checkin':
			return 1;
		case 'open':
			return 2;
		case 'draft':
			return 3;
		case 'done':
			return 4;
		case 'cancelled':
			return 5;
		default:
			return 3;
	}
}

/** "double" → "Double Elim", "single" → "Single Elim", else a titled fallback. */
export function formatLabel(fmt?: string): string {
	switch ((fmt ?? '').toLowerCase()) {
		case 'double':
			return 'Double Elim';
		case 'single':
			return 'Single Elim';
		case 'round_robin':
		case 'roundrobin':
			return 'Round Robin';
		default:
			return fmt ? fmt.replace(/[_-]+/g, ' ') : 'Bracket';
	}
}

/** Entry cost: "Free" when both are 0; else 🪙 coins and/or a $ fee. */
export function entryCost(feeCents?: number, coins?: number): string {
	const c = coins ?? 0;
	const f = feeCents ?? 0;
	if (!c && !f) return 'Free';
	const parts: string[] = [];
	if (c) parts.push(`🪙 ${c}`);
	if (f) parts.push(`$${(f / 100).toFixed(2)}`);
	return parts.join(' + ');
}

/** "FT2 winners · FT2 losers · FT3 grands" from the per-phase first-to targets (omits any that are 0). */
export function ftLabel(w?: number, l?: number, g?: number): string {
	const parts: string[] = [];
	if (w) parts.push(`FT${w} winners`);
	if (l) parts.push(`FT${l} losers`);
	if (g) parts.push(`FT${g} grands`);
	return parts.join(' · ');
}

/** A place/region string: "City · Region · Country" (whichever are present), else "". */
export function placeLabel(
	t: { city?: string; region?: string; country?: string } | null | undefined
): string {
	if (!t) return '';
	return [t.city, t.region, t.country].map((s) => (s ?? '').trim()).filter(Boolean).join(' · ');
}

/** A short human-readable stand-in for an unresolved 17-digit SteamID (last 4). */
export function shortId(sid?: string | null): string {
	const s = String(sid ?? '');
	if (!s) return 'Player';
	return s.length >= 4 ? `Player ${s.slice(-4)}` : s;
}

/**
 * Minimal, XSS-SAFE markdown → HTML for `rules_md`. We NEVER inject the raw document: every line is
 * HTML-escaped FIRST, then only a whitelist of tags we generate ourselves is applied —
 *   `#`…`######` headings → <h3>…<h6>, `**bold**` → <strong>, one line per paragraph.
 * Because escaping happens before any tag insertion, an embedded `<script>` becomes inert text; the
 * only `<`/`>` in the output are the tags this function emits. Safe to pass to Svelte's {@html}.
 */
export function mdToSafeHtml(src?: string): string {
	const esc = (s: string): string =>
		s
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;')
			.replace(/"/g, '&quot;');
	// bold runs on ALREADY-escaped text (asterisks aren't escaped, so this is safe + predictable).
	const inline = (s: string): string => esc(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
	const out: string[] = [];
	for (const raw of String(src ?? '').replace(/\r\n/g, '\n').split('\n')) {
		const line = raw.trim();
		if (!line) continue;
		const h = /^(#{1,6})\s+(.*)$/.exec(line);
		if (h) {
			const lvl = Math.min(6, h[1].length + 2); // # → h3
			out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`);
		} else {
			out.push(`<p>${inline(line)}</p>`);
		}
	}
	return out.join('\n');
}
