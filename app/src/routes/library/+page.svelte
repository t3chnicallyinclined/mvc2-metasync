<script lang="ts">
	import { onMount } from 'svelte';
	import { tierlist } from '$lib/stores/tierlist.svelte';
	import { teamAbbr } from '$lib/chars';
	import { winrateColor } from '$lib/ranks';

	// The MvC2 team tier list — every recorded 3-character composition ranked by win rate. One fetch,
	// keep-last-good (RegionsStore pattern). Static list → no live channel; a min-games gate is the one
	// piece of interactivity (low-games teams have noisy 100% rates, so gate them client-side).
	onMount(() => {
		void tierlist.load();
	});

	const MIN_PRESETS = [5, 20, 50, 100];
	let minGames = $state(20);

	const all = $derived(tierlist.teams);
	const cold = $derived(tierlist.loading && all.length === 0);
	// already winrate-desc from the store; just gate by games.
	const shown = $derived(all.filter((t) => (t.games ?? 0) >= minGames));
	const filteredOut = $derived(all.length - shown.length);
	// Never render more than 100 rows (dataset is ~74 today; the cap is a safety rail + a note if hit).
	const capped = $derived(shown.slice(0, 100));
	const overflow = $derived(shown.length - capped.length);

	const parseTeam = (s: string): number[] =>
		s.split(',').map((x) => Number(x)).filter((n) => Number.isFinite(n));
</script>

<svelte:head><title>Tier List · MetaSync</title></svelte:head>

<!-- Masthead: title + ghost watermark + accent seam + description (matches /ranks · /regions) -->
<section class="mast" style="--acc:#b98cff">
	<div class="ghost" aria-hidden="true">META</div>
	<div class="mrow">
		<h1 class="mtitle">TIER LIST</h1>
		{#if tierlist.error && all.length}
			<span class="pill live" title={tierlist.error}>RECONNECTING…</span>
		{:else}
			<span class="pill gold">TEAMS</span>
		{/if}
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">Which teams actually win — every 3-character composition ranked by win rate across all recorded matches. Low-game teams are gated below so a one-and-done 100% doesn’t top the list.</p>
</section>

<!-- min-games gate -->
<div class="controls">
	<span class="rail">Min games</span>
	<div class="chips" role="group" aria-label="Minimum games">
		{#each MIN_PRESETS as n (n)}
			<button class="chip" class:on={n === minGames} onclick={() => (minGames = n)}>{n}+</button>
		{/each}
	</div>
	{#if all.length}
		<span class="note">
			{shown.length} team{shown.length === 1 ? '' : 's'}
			{#if filteredOut > 0}· {filteredOut} below {minGames}{/if}
		</span>
	{/if}
</div>

{#if cold}
	<div class="empty">LOADING…</div>
{:else if all.length === 0}
	<div class="empty">
		{#if tierlist.error}Couldn’t load the tier list — {tierlist.error}.{:else}No team data yet — play some matches to build the board.{/if}
	</div>
{:else if shown.length === 0}
	<div class="empty">No teams with {minGames}+ games yet — lower the minimum to see more.</div>
{:else}
	<div class="board">
		<div class="bd-head">
			<span class="c">#</span>
			<span>Team</span>
			<span class="col-bar">Win rate</span>
			<span class="r">Win %</span>
			<span class="r col-wg">W – G</span>
		</div>
		<div class="bd-body">
			{#each capped as t, i (t.team)}
				{@const wr = Math.round((t.winrate ?? 0) * 10) / 10}
				{@const col = winrateColor(t.winrate ?? 0)}
				<div class="tl-row">
					<div class="rank">{i + 1}</div>
					<div class="team" title={teamAbbr(parseTeam(t.team)) || t.team}>{teamAbbr(parseTeam(t.team)) || t.team}</div>
					<div class="bar" aria-hidden="true">
						<span class="track"><span class="fill" style="width:{Math.max(2, Math.min(100, t.winrate ?? 0))}%;background:{col}"></span></span>
					</div>
					<div class="pct" style="color:{col}">{wr}%</div>
					<div class="wg col-wg">{t.wins ?? 0} <span class="sl">/</span> {t.games ?? 0}</div>
				</div>
			{/each}
		</div>
		{#if overflow > 0}
			<p class="foot">Showing the top 100 — {overflow} more below the cut.</p>
		{/if}
	</div>
{/if}

<style>
	.mast {
		position: relative;
		overflow: hidden;
		padding: 14px 4px 10px;
		margin-bottom: 4px;
	}
	.ghost {
		position: absolute;
		right: 0;
		top: -6px;
		font-size: clamp(46px, 12vw, 96px);
		font-style: italic;
		font-weight: 900;
		letter-spacing: -0.03em;
		color: var(--ink);
		opacity: 0.045;
		pointer-events: none;
		user-select: none;
		white-space: nowrap;
	}
	.mrow {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.mtitle {
		font-size: clamp(20px, 5.5vw, 27px);
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.01em;
	}
	.seam {
		height: 3px;
		width: 120px;
		margin: 8px 0 9px;
		transform: skewX(-14deg);
		background: linear-gradient(90deg, var(--acc), transparent);
	}
	.mdesc {
		margin: 0;
		max-width: 720px;
		color: var(--dim);
		font-size: 12.5px;
		line-height: 1.5;
	}

	.controls {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-wrap: wrap;
		margin: 4px 0 12px;
	}
	.chips {
		display: flex;
		gap: 4px;
	}
	.chip {
		padding: 6px 11px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: transparent;
		color: var(--dim);
		font-size: 11.5px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		cursor: pointer;
		transition: color 0.15s, background 0.15s, border-color 0.15s;
	}
	.chip:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.chip.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-color: transparent;
		color: var(--gold-ink);
		font-style: italic;
	}
	.note {
		font-size: 11.5px;
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}

	.board {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
		margin-top: 4px;
		/* rank · team · bar · win% · W–G — minmax(0,…) on the flex tracks so nothing overflows a phone */
		--tl-cols: 34px minmax(0, 1fr) minmax(56px, 150px) 50px 66px;
	}
	.bd-head {
		display: grid;
		grid-template-columns: var(--tl-cols);
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		height: 32px;
		border-bottom: 1px solid var(--line);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.bd-head .c {
		text-align: center;
	}
	.bd-head .r {
		text-align: right;
	}
	.bd-body {
		max-height: min(74vh, 900px);
		max-height: min(74dvh, 900px);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.tl-row {
		display: grid;
		grid-template-columns: var(--tl-cols);
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		height: 42px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
		content-visibility: auto;
		contain-intrinsic-size: auto 42px;
	}
	.tl-row:last-child {
		border-bottom: none;
	}
	.rank {
		font-weight: 800;
		font-size: 13.5px;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
		text-align: center;
	}
	.team {
		font-weight: 700;
		font-size: 13px;
		letter-spacing: 0.02em;
		color: var(--ink);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.bar {
		min-width: 0;
	}
	.track {
		display: block;
		width: 100%;
		height: 8px;
		border-radius: 999px;
		background: var(--panel-2);
		overflow: hidden;
	}
	.fill {
		display: block;
		height: 100%;
		border-radius: 999px;
	}
	.pct {
		font-weight: 800;
		font-size: 13px;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
	.wg {
		font-size: 12px;
		font-weight: 600;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
		text-align: right;
	}
	.wg .sl {
		color: var(--faint);
	}
	.foot {
		padding: 8px 14px;
		font-size: 11.5px;
		color: var(--faint);
	}
	/* Phones: drop the raw W–G column; the bar + win% carry the story. */
	@media (max-width: 480px) {
		.board {
			--tl-cols: 28px minmax(0, 1fr) minmax(44px, 1fr) 46px;
		}
		.bd-head {
			gap: 8px;
			padding: 0 12px;
		}
		.tl-row {
			gap: 8px;
			padding: 0 12px;
		}
		.col-wg {
			display: none;
		}
	}
</style>
