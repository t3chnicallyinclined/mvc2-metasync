<script lang="ts">
	import { onMount } from 'svelte';
	import { regions } from '$lib/stores/regions.svelte';
	import RegionRow from '$lib/components/RegionRow.svelte';

	onMount(() => {
		void regions.load();
	});

	const list = $derived(regions.regions);
	const cold = $derived(regions.loading && list.length === 0);
</script>

<svelte:head><title>Regions · MetaSync</title></svelte:head>

<!-- Masthead: title + ghost watermark + accent seam + description (matches /ranks) -->
<section class="mast" style="--acc:#34d39a">
	<div class="ghost" aria-hidden="true">REPRESENT</div>
	<div class="mrow">
		<h1 class="mtitle">REGIONS</h1>
		{#if regions.error && list.length}
			<span class="pill live" title={regions.error}>RECONNECTING…</span>
		{:else}
			<span class="pill good">LIVE</span>
		{/if}
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">Where the fighters rep — city ladders ranked by total wins. Play {regions.minGames} games to put your city on the map.</p>
</section>

{#if cold}
	<div class="empty">LOADING…</div>
{:else if list.length === 0}
	<div class="empty">No regions on the board yet — win some matches to put your city up.</div>
{:else}
	<div class="board">
		<div class="bd-head">
			<span>Region</span>
			<span class="r">Record</span>
			<span class="r col-top">Top player</span>
		</div>
		<div class="bd-body">
			{#each list as rg, i (rg.name + '|' + (rg.region ?? '') + '|' + (rg.cc ?? ''))}
				<RegionRow region={rg} pos={i + 1} />
			{/each}
		</div>
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

	.board {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
		margin-top: 10px;
	}
	.bd-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
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
	.bd-head .r {
		text-align: right;
	}
	.bd-head .col-top {
		flex: 0 0 170px;
	}
	.bd-body {
		max-height: min(74vh, 900px);
		max-height: min(74dvh, 900px);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	@media (max-width: 560px) {
		.bd-head .col-top {
			display: none;
		}
	}
</style>
