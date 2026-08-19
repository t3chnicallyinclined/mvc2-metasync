<script lang="ts">
	import { onMount } from 'svelte';
	import { leaderboard } from '$lib/stores/leaderboard.svelte';
	import { TABS, PERIODS, MAST, STAT_DESC, PERIOD_LABEL, podiumOn, buildBoardItems } from '$lib/boards';
	import Board from '$lib/components/Board.svelte';
	import PodiumPlate from '$lib/components/PodiumPlate.svelte';
	import RankBadge from '$lib/components/RankBadge.svelte';
	import Avatar from '$lib/components/Avatar.svelte';
	import { rankOf } from '$lib/ranks';
	import { flagEmoji } from '$lib/format';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
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

	// The signed-in user's position on the CURRENT board (‑1 if not among the loaded rows).
	const myPos = $derived(auth.steamid ? players.findIndex((p) => p.steamid === auth.steamid) : -1);
	const myGames = $derived((auth.me?.wins ?? 0) + (auth.me?.losses ?? 0));
	const myTier = $derived(auth.me ? rankOf(auth.me.rating ?? 0, myGames) : null);
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

	<Board {items} {tab} flashIds={leaderboard.flashIds} mySteam={auth.steamid} />

	<!-- pinned YOU row -->
	{#if auth.authed}
		<a class="you-card" href="{base}/u/{auth.steamid}">
			<span class="you-tag">YOU</span>
			<Avatar url={auth.me?.avatar} size={30} alt={auth.me?.name ?? 'You'} />
			<span class="you-name">{#if auth.me?.cc}{flagEmoji(auth.me.cc)} {/if}{auth.me?.name || 'You'}</span>
			{#if myTier}
				<span class="you-tier bd-tier">
					<RankBadge rating={auth.me?.rating ?? 0} games={myGames} size={16} />
					<span class="rk-{myTier.s}">{myTier.n}</span>
				</span>
			{/if}
			<span class="you-rt">{auth.me?.rating ?? '—'}</span>
			<span class="you-pos">{myPos >= 0 ? '#' + (myPos + 1) : 'unranked'}</span>
		</a>
	{:else}
		<div class="you-signin">
			<span>Sign in with Steam to pin your own rank on the board.</span>
			<button class="steam" onclick={() => auth.login()}>Sign in through Steam</button>
		</div>
	{/if}

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
		/* 16px: below it iOS/iPadOS Safari auto-zooms the page when the field is focused. */
		font-size: 16px;
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
	.you-card {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 8px;
		padding: 10px 14px;
		border: 1.5px solid var(--gold);
		border-radius: 12px;
		background: linear-gradient(90deg, var(--gold-soft), transparent 55%), var(--panel);
		text-decoration: none;
		color: var(--ink);
	}
	.you-card:hover {
		border-color: var(--gold);
		background: linear-gradient(90deg, var(--gold-soft), transparent 45%), var(--panel-2);
	}
	.you-tag {
		font-size: 10px;
		font-weight: 900;
		letter-spacing: 0.1em;
		color: var(--gold);
		flex: none;
	}
	.you-name {
		font-weight: 800;
		font-size: 13.5px;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		flex: 1;
	}
	.you-tier {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 800;
		font-size: 12.5px;
		flex: none;
	}
	.you-rt {
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		flex: none;
	}
	.you-pos {
		font-weight: 900;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
		flex: none;
		min-width: 34px;
		text-align: right;
	}
	.you-signin {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 8px;
		padding: 12px 16px;
		border: 1px dashed var(--line);
		border-radius: 12px;
		font-size: 12.5px;
		color: var(--dim);
	}
	.you-signin .steam {
		font: inherit;
		font-weight: 800;
		font-size: 12.5px;
		color: #dfe9f5;
		background: linear-gradient(180deg, #2a475e, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 35%, transparent);
		border-radius: 999px;
		padding: 8px 14px;
		cursor: pointer;
		white-space: nowrap;
	}
	.you-signin .steam:hover {
		border-color: #66c0f4;
		color: #fff;
	}
	@media (max-width: 460px) {
		.you-tier {
			display: none;
		}
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
