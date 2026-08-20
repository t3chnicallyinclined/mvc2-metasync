<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { matchfeed, type FeedMode } from '$lib/stores/matchfeed.svelte';
	import { wager } from '$lib/stores/wager.svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { timeAgo } from '$lib/format';
	import { charName } from '$lib/chars';
	import Avatar from '$lib/components/Avatar.svelte';
	import WagerRail from '$lib/components/WagerRail.svelte';
	import Marquee from '$lib/components/Marquee.svelte';

	// Live match center + 🪙 quarter-match surfaces — all push off the app-wide `matches` SSE channel (a
	// mode-scoped seed fetch backs Live Results; a seed fetch for the wager rail/marquee). onMount opens the
	// streams and pauses them while the tab is hidden (CPU discipline — mirrors /ranks).
	onMount(() => {
		matchfeed.connect();
		wager.connect(auth.steamid);
		void wager.loadOpen();
		if (auth.steamid) void wager.loadMine(auth.steamid);
		const onVis = () => {
			if (document.hidden) {
				matchfeed.disconnect();
				wager.disconnect();
			} else {
				matchfeed.connect();
				wager.connect(auth.steamid);
				void wager.loadOpen();
				if (auth.steamid) void wager.loadMine(auth.steamid);
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			matchfeed.disconnect();
			wager.disconnect();
		};
	});

	// keep the rail bound to the signed-in user (covers a sign-in/out while this tab is open).
	$effect(() => {
		const sid = auth.steamid;
		if (sid) void wager.loadMine(sid);
		else wager.mine = null;
	});

	const nowPlaying = $derived(matchfeed.nowPlaying);
	const results = $derived(matchfeed.results);
	const mode = $derived(matchfeed.mode);
	const me = $derived(auth.steamid);

	// ── Live Results mode filter (mirrors the /ranks scope tab-list) — Ranked is the default. ──
	const MODES: { id: FeedMode; label: string; icon: string }[] = [
		{ id: 'ranked', label: 'Ranked', icon: '⚔' },
		{ id: 'lobby', label: 'Lobby', icon: '🎮' },
		{ id: 'tourney', label: 'Tournament', icon: '🏆' }
	];
	const MODE_LABEL: Record<FeedMode, string> = { ranked: 'ranked', lobby: 'lobby', tourney: 'tournament' };

	function selectMode(m: FeedMode) {
		if (m === matchfeed.mode) return;
		matchfeed.setMode(m);
		page = 0; // a fresh mode starts on page 1
	}

	// ── Pagination — 5 per page, up to 20 rows (4 pages). A live delta prepends to page 1 (store cap 20). ──
	const PER_PAGE = 5;
	let page = $state(0);
	const pageCount = $derived(Math.max(1, Math.ceil(results.length / PER_PAGE)));
	// Keep the page in range as the list shrinks (mode switch / cap eviction).
	$effect(() => {
		if (page > pageCount - 1) page = pageCount - 1;
	});
	const pageResults = $derived(results.slice(page * PER_PAGE, page * PER_PAGE + PER_PAGE));

	const isRanked = (m?: string) => m === 'ranked';
	const is17 = (sid: string) => /^\d{17}$/.test(sid);
	// A missing/short display name falls back to a shortened steamid rather than a raw 17-digit wall.
	const nameFor = (sid: string, names: Record<string, string>) =>
		(names && names[sid]) || (sid ? `…${sid.slice(-5)}` : 'Player');
	const involvesMe = (a: string, b: string) => !!me && (a === me || b === me);

	// Mode chip label per result origin; ranked additionally shows the rating swing (see the row markup).
	const MODE_CHIP: Record<string, string> = {
		ranked: '⚔ Ranked',
		lobby: '🎮 Lobby',
		tourney: '🏆 Tournament',
		money: '🪙 Wager'
	};
	const modeChip = (m?: string) => (m ? (MODE_CHIP[m] ?? null) : null);

	const coldLoad = $derived(matchfeed.loading && results.length === 0);
</script>

<svelte:head><title>Match · MetaSync</title></svelte:head>

<!-- Masthead: title + ghost watermark + accent seam + description (matches /ranks · /regions) -->
<section class="mast" style="--acc:var(--live)">
	<div class="ghost" aria-hidden="true">LIVE</div>
	<div class="mrow">
		<h1 class="mtitle">MATCH</h1>
		<span class="pill live"><span class="dot" aria-hidden="true"></span>LIVE</span>
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">The live match center — games in progress and results as they land, pushed the moment they happen. Leave it open and watch the scene play out.</p>
</section>

<!-- 🪙 Quarter Match: your wager rail + the open-challenge marquee (live off the same `matches` channel) -->
<WagerRail />
<Marquee />

<!-- 🟢 Now Playing -->
<section class="sec">
	<h2 class="shead"><span class="ic on"><span class="dot" aria-hidden="true"></span></span> Now Playing {#if nowPlaying.length}<span class="cnt">{nowPlaying.length}</span>{/if}</h2>
	{#if nowPlaying.length === 0}
		<div class="empty">No games in progress right now.</div>
	{:else}
		<div class="panel">
			{#each nowPlaying as p (p.key)}
				{@const na = nameFor(p.a, p.names)}
				{@const nb = nameFor(p.b, p.names)}
				<div class="np" class:me={involvesMe(p.a, p.b)}>
					{#if involvesMe(p.a, p.b)}<span class="you-tag">YOU</span>{/if}
					<span class="side">
						<Avatar size={22} alt={na} />
						{#if is17(p.a)}
							<a class="pn" href="{base}/u/{p.a}" title={na}>{na}</a>
						{:else}
							<span class="pn" title={na}>{na}</span>
						{/if}
					</span>
					<span class="vs">vs</span>
					<span class="side r">
						{#if is17(p.b)}
							<a class="pn" href="{base}/u/{p.b}" title={nb}>{nb}</a>
						{:else}
							<span class="pn" title={nb}>{nb}</span>
						{/if}
						<Avatar size={22} alt={nb} />
					</span>
				</div>
			{/each}
		</div>
	{/if}
</section>

<!-- 🔴 Live Results — mode-scoped, paginated arena cards -->
<section class="sec">
	<div class="sechd">
		<h2 class="shead"><span class="ic res" aria-hidden="true"></span> Live Results {#if results.length}<span class="cnt">{results.length}</span>{/if}</h2>
		<!-- Mode filter — same tab-list pattern as /ranks scope. Selecting refetches that mode's feed. -->
		<div class="scopes" role="tablist" aria-label="Results mode">
			{#each MODES as m (m.id)}
				<button
					class="scope"
					class:on={m.id === mode}
					role="tab"
					aria-selected={m.id === mode}
					title={m.label}
					onclick={() => selectMode(m.id)}
					><span class="sic" aria-hidden="true">{m.icon}</span><span class="slbl">{m.label}</span></button
				>
			{/each}
		</div>
	</div>

	{#if coldLoad}
		<div class="empty">LOADING…</div>
	{:else if results.length === 0}
		<div class="empty">No {MODE_LABEL[mode]} results yet — they appear here the moment a set finishes.</div>
	{:else}
		<div class="panel">
			{#each pageResults as r (r.key)}
				{@const ranked = isRanked(r.mode)}
				{@const chip = modeChip(r.mode)}
				<article class="rr" class:me={involvesMe(r.winner, r.loser)} class:nonranked={!!r.mode && !ranked}>
					<!-- top meta: mode chip · (YOU) — verified · time -->
					<div class="rr-meta">
						<span class="mleft">
							{#if involvesMe(r.winner, r.loser)}<span class="you-tag inline">YOU</span>{/if}
							{#if chip}<span class="chip" class:rk={ranked}>{chip}</span>{/if}
						</span>
						<span class="mright">
							{#if r.verified}<span class="seal" title="Verified — both players agree + replay">✓✓</span>{/if}
							{#if timeAgo(r.ts)}<span class="ago">{timeAgo(r.ts)}</span>{/if}
						</span>
					</div>

					<!-- winner side (reads as winner: gold rail + W chip + team) -->
					<div class="p win">
						<div class="pline">
							<span class="wtag" aria-hidden="true">W</span>
							{#if is17(r.winner)}
								<a class="name" href="{base}/u/{r.winner}" title={r.winner_name}>{r.winner_name}</a>
							{:else}
								<span class="name" title={r.winner_name}>{r.winner_name}</span>
							{/if}
							{#if ranked && r.elo}<span class="delta up" title="Rating gained">+{r.elo}</span>{/if}
						</div>
						{#if r.winner_team?.length}
							<div class="team">
								{#each r.winner_team as id, i (i)}{#if i > 0}<span class="sep" aria-hidden="true">/</span>{/if}<span class="ch">{charName(id)}</span>{/each}
							</div>
						{/if}
					</div>

					<div class="seam-def"><span>def.</span></div>

					<!-- loser side (quieter) -->
					<div class="p lose">
						<div class="pline">
							{#if is17(r.loser)}
								<a class="name" href="{base}/u/{r.loser}" title={r.loser_name}>{r.loser_name}</a>
							{:else}
								<span class="name" title={r.loser_name}>{r.loser_name}</span>
							{/if}
							{#if ranked && r.elo}<span class="delta down" title="Rating lost">−{r.elo}</span>{/if}
						</div>
						{#if r.loser_team?.length}
							<div class="team">
								{#each r.loser_team as id, i (i)}{#if i > 0}<span class="sep" aria-hidden="true">/</span>{/if}<span class="ch">{charName(id)}</span>{/each}
							</div>
						{/if}
					</div>

					<!-- highlight badges -->
					{#if r.ocv || r.perfect || r.comeback || r.combo}
						<div class="tags">
							{#if r.ocv}<span class="badge ocv" title="One-character victory — swept all three with a single character">OCV</span>{/if}
							{#if r.perfect}<span class="badge perfect" title="Flawless — won a game without taking damage">PERFECT</span>{/if}
							{#if r.comeback}<span class="badge comeback" title="Comeback — won from the last character down">COMEBACK</span>{/if}
							{#if r.combo}<span class="badge combo" title="Biggest combo of the set">{r.combo}-HIT</span>{/if}
						</div>
					{/if}
				</article>
			{/each}
		</div>

		{#if pageCount > 1}
			<nav class="pager" aria-label="Live Results pages">
				<button class="pg" disabled={page === 0} onclick={() => (page = Math.max(0, page - 1))}>‹ Prev</button>
				<div class="dots">
					{#each Array(pageCount) as _, i (i)}
						<button class="dot" class:on={i === page} onclick={() => (page = i)} aria-label="Page {i + 1}" aria-current={i === page}></button>
					{/each}
				</div>
				<button class="pg" disabled={page >= pageCount - 1} onclick={() => (page = Math.min(pageCount - 1, page + 1))}>Next ›</button>
			</nav>
		{/if}
	{/if}
</section>

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

	/* pulsing live dot inside the pill (motion-safe only) */
	.pill .dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--live);
		flex: none;
	}
	@media (prefers-reduced-motion: no-preference) {
		.pill .dot {
			animation: pulse 1.6s ease-in-out infinite;
		}
	}
	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}

	.sec {
		margin-top: 16px;
	}
	/* Section header: title on the left, the mode tab-list on the right (wraps under it on phones). */
	.sechd {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		flex-wrap: wrap;
		margin-bottom: 8px;
	}
	.shead {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0 0 8px;
		font-size: 13px;
		font-weight: 800;
		letter-spacing: 0.02em;
		color: var(--ink);
	}
	.sechd .shead {
		margin: 0;
	}
	.shead .ic {
		width: 16px;
		height: 16px;
		border-radius: 50%;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		flex: none;
	}
	.shead .ic.on {
		background: color-mix(in srgb, var(--good) 20%, transparent);
	}
	.shead .ic.on .dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--good);
	}
	@media (prefers-reduced-motion: no-preference) {
		.shead .ic.on .dot {
			animation: pulse 1.6s ease-in-out infinite;
		}
	}
	.shead .ic.res {
		width: 8px;
		height: 8px;
		background: var(--live);
	}
	.cnt {
		font-size: 11px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		color: var(--faint);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 1px 7px;
	}

	/* Mode tab-list — a rounded segmented control, cloned from the /ranks scope switch. */
	.scopes {
		display: inline-flex;
		align-items: center;
		flex: none;
		gap: 2px;
		padding: 2px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--panel);
	}
	.scope {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		border: 0;
		background: transparent;
		color: var(--dim);
		border-radius: 999px;
		padding: 6px 12px;
		font-size: 12px;
		font-weight: 700;
		cursor: pointer;
		white-space: nowrap;
		transition: color 0.15s, background 0.15s;
	}
	.scope:hover {
		color: var(--ink);
	}
	.scope.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		color: var(--gold-ink);
		font-style: italic;
	}
	.sic {
		font-size: 12.5px;
		line-height: 1;
	}

	.panel {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
	}

	/* Now-playing row: [side A] vs [side B] — both tracks minmax(0,…) so long names ellipsize
	   instead of overflowing the phone viewport. */
	.np {
		position: relative;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 10px;
		padding: 11px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.np:last-child {
		border-bottom: none;
	}
	.side {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}
	.side.r {
		justify-content: flex-end;
	}
	.pn {
		font-weight: 700;
		font-size: 13.5px;
		color: var(--ink);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	a.pn:hover {
		color: var(--gold);
	}
	.vs {
		flex: none;
		font-size: 10.5px;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--faint);
	}

	/* ── Result card ─────────────────────────────────────────────────────────────────────────── */
	.rr {
		position: relative;
		padding: 12px 14px 13px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.rr:last-child {
		border-bottom: none;
	}
	.rr-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 8px;
		margin-bottom: 8px;
	}
	.mleft,
	.mright {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}

	/* a player line: [W] name  +delta */
	.p {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding-left: 10px;
		border-left: 2px solid transparent;
	}
	.p.win {
		border-left-color: var(--good);
	}
	.pline {
		display: flex;
		align-items: baseline;
		gap: 8px;
		min-width: 0;
	}
	.wtag {
		flex: none;
		align-self: center;
		font-size: 9.5px;
		font-weight: 900;
		line-height: 1;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-radius: 4px;
		padding: 3px 5px;
	}
	.p .name {
		font-weight: 800;
		font-size: 14.5px;
		color: var(--good);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.p.lose .name {
		font-weight: 600;
		font-size: 13px;
		color: var(--dim);
	}
	a.name:hover {
		text-decoration: underline;
	}
	/* char-team matchup line (via charName) */
	.team {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 5px;
		font-size: 11.5px;
		font-weight: 700;
		letter-spacing: 0.01em;
		color: var(--ink);
	}
	.p.lose .team {
		color: var(--dim);
		font-weight: 600;
	}
	.team .sep {
		color: var(--faint);
		font-weight: 400;
	}

	/* skewed "def." seam between the two sides */
	.seam-def {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 7px 0;
		padding-left: 10px;
	}
	.seam-def span {
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.seam-def::after {
		content: '';
		flex: 1;
		height: 1px;
		background: linear-gradient(90deg, var(--line), transparent);
	}

	/* rating swing — +gain (winner) green, −loss (loser) red */
	.delta {
		flex: none;
		font-size: 11.5px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.delta.up {
		color: var(--good);
	}
	.delta.down {
		color: var(--live);
	}

	/* mode chip — neutral by default; ranked gets a faint green wash to match its rating swing */
	.chip {
		flex: none;
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.02em;
		white-space: nowrap;
		color: var(--faint);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 2px 8px;
	}
	.chip.rk {
		color: var(--good);
		border-color: color-mix(in srgb, var(--good) 32%, var(--line));
		background: color-mix(in srgb, var(--good) 12%, transparent);
	}
	.seal {
		font-size: 11px;
		font-weight: 800;
		color: var(--good);
	}
	.ago {
		font-size: 10.5px;
		color: var(--faint);
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
	}

	/* highlight badges — each keyed to a token so it stays theme-aware */
	.tags {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
		padding-left: 10px;
	}
	.badge {
		font-size: 9.5px;
		font-weight: 900;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		border-radius: 6px;
		padding: 3px 7px;
		border: 1px solid transparent;
		font-variant-numeric: tabular-nums;
	}
	.badge.ocv {
		color: var(--live);
		background: color-mix(in srgb, var(--live) 13%, transparent);
		border-color: color-mix(in srgb, var(--live) 34%, var(--line));
	}
	.badge.perfect {
		color: var(--p2);
		background: var(--p2-soft);
		border-color: var(--p2-line);
	}
	.badge.comeback {
		color: var(--stream);
		background: color-mix(in srgb, var(--stream) 14%, transparent);
		border-color: color-mix(in srgb, var(--stream) 40%, var(--line));
	}
	.badge.combo {
		color: var(--gold);
		background: var(--gold-soft);
		border-color: color-mix(in srgb, var(--gold) 40%, var(--line));
	}
	/* non-ranked results sit a touch quieter so ranked (with its rating swing) reads first */
	.rr.nonranked {
		opacity: 0.9;
	}

	/* signed-in user's rows get a subtle gold rail + a YOU tag */
	.np.me,
	.rr.me {
		box-shadow: inset 0 0 0 1.5px var(--gold);
		background: linear-gradient(90deg, var(--gold-soft), transparent 55%);
	}
	.you-tag {
		position: absolute;
		top: 3px;
		right: 8px;
		font-size: 8.5px;
		font-weight: 900;
		letter-spacing: 0.12em;
		color: var(--gold);
	}
	.you-tag.inline {
		position: static;
		font-size: 9px;
	}

	/* pager — arena-styled prev/next + page dots */
	.pager {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 14px;
		margin-top: 12px;
	}
	.pg {
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 6px 14px;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.pg:hover:not(:disabled) {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.pg:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.dots {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	.dot {
		width: 8px;
		height: 8px;
		padding: 0;
		border: 0;
		border-radius: 50%;
		background: var(--line);
		cursor: pointer;
		transition: background 0.15s, transform 0.15s;
	}
	.dot:hover {
		background: var(--faint);
	}
	.dot.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		transform: scale(1.25);
	}

	@media (max-width: 560px) {
		.scopes {
			width: 100%;
			justify-content: space-between;
		}
		.scope {
			padding: 6px 10px;
		}
	}
</style>
