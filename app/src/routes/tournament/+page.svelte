<script lang="ts">
	import { onMount } from 'svelte';
	import { tournaments } from '$lib/stores/tournaments.svelte';
	import TournamentCard from '$lib/components/TournamentCard.svelte';

	// ── live wiring: initial fetch + subscribe to the "tourney_index" SSE channel; pause on hide ──
	onMount(() => {
		void tournaments.load();
		tournaments.connect();
		const onVis = () => {
			if (document.hidden) {
				tournaments.disconnect(); // stop the stream while backgrounded (CPU discipline)
			} else {
				tournaments.connect();
				void tournaments.load(); // catch anything missed while hidden
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			tournaments.disconnect();
		};
	});

	const list = $derived(tournaments.list);
	const cold = $derived(tournaments.loading && list.length === 0);
</script>

<svelte:head><title>Tournaments · MetaSync</title></svelte:head>

<!-- Masthead: title + ghost watermark + accent seam + description (matches /ranks · /regions) -->
<section class="mast" style="--acc:#8b6dff">
	<div class="ghost" aria-hidden="true">BRACKETS</div>
	<div class="mrow">
		<h1 class="mtitle">TOURNAMENTS</h1>
		{#if tournaments.error && list.length}
			<span class="pill live" title={tournaments.error}>RECONNECTING…</span>
		{:else}
			<span class="pill good">LIVE</span>
		{/if}
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">
		Brackets that run themselves — browse open events and follow the action live from your phone.
	</p>
</section>

{#if cold}
	<div class="empty">LOADING…</div>
{:else if list.length === 0}
	<div class="empty">No tournaments yet — check back when an organizer opens one up.</div>
{:else}
	<div class="grid">
		{#each list as t (t.id)}
			<TournamentCard {t} />
		{/each}
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
		font-size: clamp(42px, 12vw, 96px);
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

	.grid {
		display: grid;
		/* minmax(min(100%, 280px), 1fr): a single column below ~280px (never overflows the phone),
		   auto-filling wider tracks on tablet/desktop. */
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr));
		gap: 12px;
		margin-top: 10px;
	}
</style>
