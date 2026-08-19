<script lang="ts">
	import { onMount } from 'svelte';
	import { leaderboard } from '$lib/stores/leaderboard.svelte';
	import { TABS, PERIODS, MAST, STAT_DESC, PERIOD_LABEL, podiumOn, buildBoardItems } from '$lib/boards';
	import Board from '$lib/components/Board.svelte';
	import PodiumPlate from '$lib/components/PodiumPlate.svelte';
	import type { LeaderboardTab, LeaderboardPeriod } from '$lib/types';

	// ── live wiring: initial fetch + subscribe to the "leaderboard" SSE channel; pause on hide ──
	onMount(() => {
		void leaderboard.load(true);
		leaderboard.connect();
		const onVis = () => {
			if (document.hidden) {
				leaderboard.disconnect(); // stop the stream while backgrounded (CPU discipline)
			} else {
				leaderboard.connect();
				void leaderboard.load(); // catch anything missed while hidden
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			leaderboard.disconnect();
		};
	});

	let q = $state('');

	const tab = $derived(leaderboard.tab);
	const players = $derived(leaderboard.players);
	const searching = $derived(q.trim().length > 0);
	const shown = $derived(
		searching
			? players.filter((p) => (p.name ?? '').toLowerCase().includes(q.trim().toLowerCase()))
			: players
	);
	const mast = $derived(MAST[tab]);
	const showPodium = $derived(podiumOn(shown, searching));
	const items = $derived(buildBoardItems(shown, tab, searching));

	const coldLoad = $derived(leaderboard.loading && players.length === 0);
</script>

<svelte:head><title>Ranks · MetaSync</title></svelte:head>

<!-- Masthead: title + ghost watermark + accent seam + description -->
<section class="mast" style="--acc:{mast[2]}">
	<div class="ghost" aria-hidden="true">{mast[1]}</div>
	<div class="mrow">
		<h1 class="mtitle">{mast[0]}</h1>
		{#if leaderboard.error && players.length}
			<span class="pill live" title={leaderboard.error}>RECONNECTING…</span>
		{:else}
			<span class="pill good">LIVE</span>
		{/if}
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">{STAT_DESC[tab]}</p>
</section>

<!-- Controls: board tabs · period · search -->
<div class="controls">
	<div class="cuts" role="tablist" aria-label="Leaderboard">
		{#each TABS as t (t.id)}
			<button
				class="cut"
				class:on={t.id === tab}
				role="tab"
				aria-selected={t.id === tab}
				onclick={() => leaderboard.setTab(t.id as LeaderboardTab)}>{t.label}</button
			>
		{/each}
	</div>
	{#if !leaderboard.periodLocked}
		<div class="periods">
			{#each PERIODS as p (p.id)}
				<button
					class="per"
					class:on={p.id === leaderboard.period}
					onclick={() => leaderboard.setPeriod(p.id as LeaderboardPeriod)}>{p.label}</button
				>
			{/each}
		</div>
	{/if}
	<input class="search" type="search" placeholder="Search player…" bind:value={q} aria-label="Search player" />
</div>

{#if coldLoad}
	<div class="empty">LOADING…</div>
{:else if shown.length === 0}
	<div class="empty">
		{#if searching}
			No players match “{q}”.
		{:else}
			No rankings {leaderboard.period === 'all' ? 'yet' : `for ${PERIOD_LABEL[leaderboard.period]}`} — win a match to get on the board.
		{/if}
	</div>
{:else}
	{#if showPodium}
		<div class="podium">
			<PodiumPlate player={shown[1]} place={2} {tab} />
			<PodiumPlate player={shown[0]} place={1} {tab} />
			<PodiumPlate player={shown[2]} place={3} {tab} />
		</div>
	{/if}

	<Board {items} {tab} flashIds={leaderboard.flashIds} mySteam={null} />

	<!-- pinned YOU row — auth arrives in Phase 2 -->
	<div class="you empty">
		Sign in with Steam (coming in Phase 2) to pin your own rank here.
	</div>

	{#if tab === 'rating'}
		<p class="foot">Play 5 games to get ranked — Civilians don’t appear on this board.</p>
	{/if}
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
		gap: 8px;
		flex-wrap: wrap;
		margin: 4px 0 12px;
	}
	.cuts {
		display: flex;
		gap: 4px;
		flex-wrap: wrap;
	}
	.cut {
		transform: skewX(-12deg);
		padding: 6px 12px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: transparent;
		color: var(--dim);
		font-size: 11.5px;
		font-weight: 700;
		cursor: pointer;
		transition: color 0.15s, background 0.15s, border-color 0.15s;
	}
	.cut > :global(*) {
		display: inline-block;
		transform: skewX(12deg);
	}
	.cut:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.cut.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-color: transparent;
		color: var(--gold-ink);
		font-style: italic;
	}
	.periods {
		display: flex;
		gap: 3px;
		margin-left: 2px;
	}
	.per {
		padding: 6px 10px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: transparent;
		color: var(--dim);
		font-size: 11px;
		font-weight: 700;
		cursor: pointer;
	}
	.per.on {
		color: var(--ink);
		background: var(--panel);
		border-color: var(--gold-soft);
	}
	.search {
		margin-left: auto;
		flex: 0 1 190px;
		min-width: 120px;
		font: inherit;
		font-size: 12.5px;
		color: var(--ink);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 9px;
		padding: 7px 12px;
	}
	.search::placeholder {
		color: var(--faint);
	}

	.podium {
		display: grid;
		/* minmax(0,…) — NOT bare 1fr — so the tracks can shrink below the plates' nowrap
		   content (names/stats) on a phone; the plate's own overflow:hidden clips instead
		   of the row overflowing the viewport. */
		grid-template-columns: minmax(0, 1fr) minmax(0, 1.22fr) minmax(0, 1fr);
		gap: 12px;
		align-items: end;
		margin-bottom: 12px;
	}
	.you {
		margin-top: 8px;
		padding: 14px 16px;
		font-size: 12px;
	}
	.foot {
		padding: 8px 4px 0;
		font-size: 11.5px;
		color: var(--faint);
	}
	@media (max-width: 560px) {
		.podium {
			gap: 7px;
		}
		.search {
			flex-basis: 100%;
			margin-left: 0;
			order: 3;
		}
	}
</style>
