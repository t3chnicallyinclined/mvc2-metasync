<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { matchfeed } from '$lib/stores/matchfeed.svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { timeAgo } from '$lib/format';
	import Avatar from '$lib/components/Avatar.svelte';

	// Live match center — push-only off the app-wide `matches` SSE channel (no snapshot fetch). onMount
	// opens the stream and pauses it while the tab is hidden (CPU discipline — mirrors /ranks).
	onMount(() => {
		matchfeed.connect();
		const onVis = () => {
			if (document.hidden) matchfeed.disconnect();
			else matchfeed.connect();
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			matchfeed.disconnect();
		};
	});

	const nowPlaying = $derived(matchfeed.nowPlaying);
	const results = $derived(matchfeed.results);
	const me = $derived(auth.steamid);

	const is17 = (sid: string) => /^\d{17}$/.test(sid);
	// A missing/short display name falls back to a shortened steamid rather than a raw 17-digit wall.
	const nameFor = (sid: string, names: Record<string, string>) =>
		(names && names[sid]) || (sid ? `…${sid.slice(-5)}` : 'Player');
	const involvesMe = (a: string, b: string) => !!me && (a === me || b === me);
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

<!-- 🔴 Live Results -->
<section class="sec">
	<h2 class="shead"><span class="ic res" aria-hidden="true"></span> Live Results {#if results.length}<span class="cnt">{results.length}</span>{/if}</h2>
	{#if results.length === 0}
		<div class="empty">Results appear here as matches finish.</div>
	{:else}
		<div class="panel">
			{#each results as r (r.key)}
				<div class="rr" class:me={involvesMe(r.winner, r.loser)}>
					{#if involvesMe(r.winner, r.loser)}<span class="you-tag">YOU</span>{/if}
					<div class="rmain">
						{#if is17(r.winner)}
							<a class="win" href="{base}/u/{r.winner}" title={r.winner_name}>{r.winner_name}</a>
						{:else}
							<span class="win" title={r.winner_name}>{r.winner_name}</span>
						{/if}
						<span class="def">def.</span>
						{#if is17(r.loser)}
							<a class="lose" href="{base}/u/{r.loser}" title={r.loser_name}>{r.loser_name}</a>
						{:else}
							<span class="lose" title={r.loser_name}>{r.loser_name}</span>
						{/if}
					</div>
					<div class="rmeta">
						{#if r.verified}<span class="seal" title="Verified — both players agree + replay">✓✓</span>{/if}
						{#if timeAgo(r.ts)}<span class="ago">{timeAgo(r.ts)}</span>{/if}
					</div>
				</div>
			{/each}
		</div>
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
	.np:last-child,
	.rr:last-child {
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

	/* Result row: [winner def. loser] … [seal · ago] */
	.rr {
		position: relative;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
		padding: 10px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.rmain {
		display: flex;
		align-items: baseline;
		gap: 7px;
		min-width: 0;
	}
	.win {
		font-weight: 800;
		font-size: 13.5px;
		color: var(--good);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
		flex: 0 1 auto;
	}
	a.win:hover {
		text-decoration: underline;
	}
	.def {
		flex: none;
		font-size: 10.5px;
		font-weight: 700;
		color: var(--faint);
	}
	.lose {
		font-weight: 600;
		font-size: 13px;
		color: var(--dim);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
		flex: 0 1 auto;
	}
	a.lose:hover {
		color: var(--ink);
	}
	.rmeta {
		display: flex;
		align-items: center;
		gap: 8px;
		flex: none;
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

	/* signed-in user's rows get a subtle gold rail + a YOU tag pinned top-right */
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
</style>
