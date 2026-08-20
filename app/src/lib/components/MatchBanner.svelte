<script lang="ts">
	import { timeAgo } from '$lib/format';
	import { teamAbbr } from '$lib/chars';
	import PlayerTag from './PlayerTag.svelte';

	// THE standardized match banner — ONE row, used by BOTH "Now Playing" (variant="live") and "Live
	// Results" (variant="result"). Shared vocabulary with MatchRow (tokens, chip colors, ELO rail, seal):
	//   [marker] · [playerA vs playerB — each badge+name+rating] · [teams] · | · [right cluster] · [end]
	// result → gold W winner marker, winner in --ink / loser dimmed, flair chips + rating swing, whole
	//          row opens the set modal (a decorative › hints it); loser/winner links stopPropagation.
	// live   → 🔴 LIVE marker, both players neutral, a (stubbed) Spectate button reserved for later.
	interface BannerPlayer {
		sid: string;
		name: string;
		rating?: number;
		team?: number[];
	}
	let {
		variant,
		left,
		right,
		ranked = false,
		mode = '',
		elo,
		ts,
		ocv = false,
		perfect = false,
		comeback = false,
		combo = 0,
		verified = false,
		sessionId,
		mine = false,
		onOpen
	}: {
		variant: 'result' | 'live';
		left: BannerPlayer;
		right: BannerPlayer;
		ranked?: boolean;
		mode?: string;
		elo?: number;
		ts?: number;
		ocv?: boolean;
		perfect?: boolean;
		comeback?: boolean;
		combo?: number;
		verified?: boolean;
		sessionId?: string;
		mine?: boolean;
		onOpen?: (id: string) => void;
	} = $props();

	// Row mode chip — mirrors MatchRow (only for non-ranked; ranked is the default, no chip).
	const MODE_TAG: Record<string, string> = { lobby: 'LOBBY', tourney: 'EVENT', money: 'MONEY' };
	const stop = (e: Event) => e.stopPropagation(); // profile links navigate without opening the modal

	const when = $derived(timeAgo(ts));
	const lTeam = $derived(teamAbbr(left.team));
	const rTeam = $derived(teamAbbr(right.team));
	const modeTag = $derived(mode && mode !== 'ranked' ? mode : '');
	const clickable = $derived(variant === 'result' && !!sessionId);

	function open() {
		if (sessionId && onOpen) onOpen(sessionId);
	}
	function onKey(e: KeyboardEvent) {
		if (e.currentTarget !== e.target) return; // ignore Enter/Space on an inner link
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			open();
		}
	}
	// Interactivity only when the row opens a set — spread so the a11y contract (role+tabindex+key)
	// is applied together or not at all (a plain live card stays non-interactive).
	const rootAttrs = $derived(
		clickable
			? { role: 'button', tabindex: 0, 'aria-label': 'View set details', onclick: open, onkeydown: onKey }
			: {}
	);
</script>

<div class="mb" class:mine class:clickable class:live={variant === 'live'} {...rootAttrs}>
	{#if variant === 'result'}
		<span class="wl" aria-label="Winner">W</span>
	{:else}
		<span class="livemark" aria-label="Live"><span class="ldot" aria-hidden="true"></span>LIVE</span>
	{/if}

	<span class="who">
		<PlayerTag
			sid={left.sid}
			name={left.name}
			rating={left.rating}
			emphasis={variant === 'result' ? 'win' : 'live'}
			onLinkClick={stop}
		/>
		<span class="vs">vs</span>
		<PlayerTag
			sid={right.sid}
			name={right.name}
			rating={right.rating}
			emphasis={variant === 'result' ? 'lose' : 'live'}
			onLinkClick={stop}
		/>
		{#if verified}<span class="seal" title="Verified (both agree + replay)">✓✓</span>{/if}
		{#if modeTag}<span class="mode m-{modeTag}" title="Game mode">{MODE_TAG[modeTag] ?? modeTag}</span>{/if}
	</span>

	{#if lTeam || rTeam}
		<!-- team matchup, inline + dimmed (teamAbbr); first to drop on narrow widths -->
		<span class="teams" title="{lTeam || '—'} vs {rTeam || '—'}">
			<span class="tm">{lTeam || '—'}</span><i>vs</i><span class="tm dim">{rTeam || '—'}</span>
		</span>
	{/if}

	<span class="spacer" aria-hidden="true"></span>

	{#if variant === 'result'}
		<span class="flair">
			{#if ocv}<span class="chip ocv" title="One-Character Victory">OCV</span>{/if}
			{#if perfect}<span class="chip perf" title="Perfect">PERF</span>{/if}
			{#if comeback}<span class="chip cb" title="Comeback">CB</span>{/if}
			{#if combo}<span class="chip combo" title="Max combo this set">🎯 {combo}</span>{/if}
		</span>
		<span class="right">
			{#if ranked && elo}<b class="elo up">+{elo}</b>{/if}
			{#if when}<span class="ago">{when}</span>{/if}
		</span>
		{#if sessionId}<span class="disc" aria-hidden="true">›</span>{/if}
	{:else}
		<!-- reserved: wired to a Steam join link later; stubbed/disabled for now -->
		<button class="spectate" disabled title="Spectate — coming soon" aria-label="Spectate (coming soon)">
			<span class="tri" aria-hidden="true">▶</span><span class="slbl">Spectate</span>
		</button>
	{/if}
</div>

<style>
	/* ── One-line match banner — MatchRow vocabulary, shared by live + result cards ──────────────── */
	.mb {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 12px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.mb:last-child {
		border-bottom: none;
	}
	.mb.clickable {
		cursor: pointer;
	}
	.mb.clickable:hover {
		background: color-mix(in srgb, var(--panel-2) 60%, transparent);
	}
	.mb:focus-visible {
		outline: none;
		box-shadow: inset 0 0 0 1.5px var(--gold-soft);
	}
	/* gold W badge — the winner marker (network-wide, not viewer-relative) */
	.wl {
		flex: none;
		width: 22px;
		height: 22px;
		border-radius: 6px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 12px;
		font-weight: 900;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
	}
	/* 🔴 LIVE marker on in-progress cards */
	.livemark {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		height: 22px;
		padding: 0 8px;
		border-radius: 6px;
		font-size: 9px;
		font-weight: 900;
		letter-spacing: 0.08em;
		color: var(--live);
		background: color-mix(in srgb, var(--live) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--live) 34%, var(--line));
	}
	.ldot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--live);
	}
	@media (prefers-reduced-motion: no-preference) {
		.ldot {
			animation: mbpulse 1.6s ease-in-out infinite;
		}
	}
	@keyframes mbpulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	/* the two players + separator + seal + mode — the primary cluster; shrinks/ellipsizes first */
	.who {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		flex: 0 1 auto;
	}
	.vs {
		flex: none;
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.seal {
		flex: none;
		font-size: 10px;
		font-weight: 800;
		color: var(--good);
	}
	.mode {
		flex: none;
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.05em;
		padding: 1px 5px;
		border-radius: 5px;
		border: 1px solid var(--line);
		color: var(--dim);
	}
	.mode.m-tourney {
		color: var(--stream);
		border-color: color-mix(in srgb, var(--stream) 40%, var(--line));
		background: color-mix(in srgb, var(--stream) 12%, transparent);
	}
	.mode.m-money {
		color: var(--good);
		border-color: color-mix(in srgb, var(--good) 40%, var(--line));
		background: color-mix(in srgb, var(--good) 12%, transparent);
	}
	/* inline team matchup (dimmed) — sits right after the names, drops first when tight */
	.teams {
		display: inline-flex;
		align-items: baseline;
		gap: 5px;
		flex: 0 1 auto;
		min-width: 0;
		font-size: 10.5px;
		font-weight: 700;
		letter-spacing: 0.03em;
		color: var(--dim);
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}
	.teams i {
		font-style: normal;
		color: var(--faint);
		font-weight: 600;
	}
	.teams .tm {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.teams .tm.dim {
		color: var(--faint);
	}
	/* flexible gap that pushes the right-hand cluster to the edge */
	.spacer {
		flex: 1 1 8px;
		min-width: 8px;
	}
	.flair {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		flex: none;
	}
	.chip {
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.04em;
		padding: 2px 5px;
		border-radius: 5px;
		white-space: nowrap;
		border: 1px solid var(--line);
		color: var(--dim);
	}
	.chip.ocv {
		color: #ff7ae0;
		border-color: color-mix(in srgb, #ff7ae0 40%, var(--line));
		background: color-mix(in srgb, #ff7ae0 12%, transparent);
	}
	.chip.perf {
		color: #9fd4ef;
		border-color: color-mix(in srgb, #9fd4ef 40%, var(--line));
		background: color-mix(in srgb, #9fd4ef 12%, transparent);
	}
	.chip.cb {
		color: #4ade80;
		border-color: color-mix(in srgb, #4ade80 40%, var(--line));
		background: color-mix(in srgb, #4ade80 12%, transparent);
	}
	.chip.combo {
		color: var(--gold);
		border-color: color-mix(in srgb, var(--gold) 34%, var(--line));
	}
	.right {
		display: inline-flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 1px;
		flex: none;
	}
	.elo {
		font-size: 13px;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	.elo.up {
		color: #4ade80;
	}
	.ago {
		font-size: 10px;
		color: var(--faint);
		white-space: nowrap;
	}
	/* disclosure chevron — the visible "opens a set" affordance (the row itself is the button) */
	.disc {
		flex: none;
		font-size: 16px;
		font-weight: 700;
		color: var(--faint);
		line-height: 1;
		transition: color 0.15s, transform 0.15s;
	}
	.mb.clickable:hover .disc {
		color: var(--gold);
		transform: translateX(2px);
	}
	/* Spectate — arena-styled, stubbed (disabled) until the Steam join link is wired */
	.spectate {
		flex: none;
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font: inherit;
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.02em;
		color: var(--dim);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 5px 12px;
		cursor: not-allowed;
		opacity: 0.72;
	}
	.spectate .tri {
		font-size: 8px;
		color: var(--live);
	}

	/* signed-in user's rows get a subtle gold rail (mirrors BoardRow.me) */
	.mb.mine {
		box-shadow: inset 0 0 0 1.5px var(--gold);
		background: linear-gradient(90deg, var(--gold-soft), transparent 55%);
	}

	/* Overflow priority (mirrors MatchRow): drop the inline teams first, then the flair chips, so the
	   players + rating/action always stay on one line. */
	@media (max-width: 640px) {
		.teams {
			display: none;
		}
	}
	@media (max-width: 480px) {
		.flair {
			display: none;
		}
		.mb {
			gap: 8px;
			padding: 8px 10px;
		}
	}
	@media (max-width: 400px) {
		.spectate .slbl {
			display: none;
		}
	}
</style>
