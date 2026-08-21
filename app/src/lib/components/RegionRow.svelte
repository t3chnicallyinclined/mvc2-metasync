<script lang="ts">
	import { base } from '$app/paths';
	import Avatar from './Avatar.svelte';
	import { flagEmoji } from '$lib/format';
	import { tierOf, RK_TEXT } from '$lib/ranks';
	import type { Region } from '$lib/stores/regions.svelte';

	let {
		region,
		pos,
		onOpen
	}: { region: Region; pos: number; onOpen?: (r: Region) => void } = $props();

	const clickable = $derived(!!onOpen);
	const stop = (e: Event) => e.stopPropagation(); // the top-player link navigates without opening the drill-in
	function open() {
		onOpen?.(region);
	}
	function onKey(e: KeyboardEvent) {
		if (e.currentTarget !== e.target) return;
		if (e.key === 'Enter' || e.key === ' ') {
			e.preventDefault();
			open();
		}
	}
	const rootAttrs = $derived(
		clickable
			? { role: 'button', tabindex: 0, 'aria-label': `${region.name} — view players`, onclick: open, onkeydown: onKey }
			: {}
	);

	const wins = $derived(region.wins ?? 0);
	const losses = $derived(region.losses ?? 0);
	const players = $derived(region.players ?? 0);
	const avg = $derived(region.avg_rating ?? 0);
	const avgTint = $derived(RK_TEXT[tierOf(avg).n.toLowerCase()] ?? 'var(--ink)');
	const top = $derived(region.top ?? null);
	const topHref = $derived(
		top?.steamid && String(top.steamid).length === 17 ? `${base}/u/${top.steamid}` : null
	);
	const sub = $derived([region.region, region.country].filter(Boolean).join(' · '));
</script>

<div class="rg" class:clickable {...rootAttrs}>
	<div class="lead">
		<span class="place">{pos}</span>
		<span class="flag">{flagEmoji(region.cc)}</span>
		<div class="id">
			<b class="nm">{region.name}</b>
			{#if sub}<span class="sub">{sub}</span>{/if}
		</div>
	</div>

	<div class="stats">
		<span class="st"><b>{players}</b><i>{players === 1 ? 'player' : 'players'}</i></span>
		<span class="st"><b>{wins}<span class="dash">–</span>{losses}</b><i>W–L</i></span>
		<span class="st"><b style="color:{avgTint}">{avg}</b><i>avg</i></span>
	</div>

	{#if top}
		{#if topHref}
			<a class="top" href={topHref} title="{top.name} — {top.wins ?? 0} wins" onclick={stop}>
				<span class="crown" aria-hidden="true">👑</span>
				<Avatar url={top.avatar} size={22} alt={top.name} />
				<span class="tn">{top.name || 'Player'}</span>
				<span class="tw">{top.wins ?? 0}W</span>
			</a>
		{:else}
			<div class="top">
				<span class="crown" aria-hidden="true">👑</span>
				<Avatar url={top.avatar} size={22} alt={top.name} />
				<span class="tn">{top.name || 'Player'}</span>
				<span class="tw">{top.wins ?? 0}W</span>
			</div>
		{/if}
	{/if}
</div>

<style>
	.rg {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		padding: 11px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.rg:last-child {
		border-bottom: none;
	}
	.rg.clickable {
		cursor: pointer;
	}
	.rg.clickable:hover {
		background: color-mix(in srgb, var(--panel-2) 60%, transparent);
	}
	.rg.clickable:focus-visible {
		outline: none;
		box-shadow: inset 0 0 0 1.5px var(--gold-soft);
	}
	.lead {
		display: flex;
		align-items: center;
		gap: 9px;
		flex: 1 1 190px;
		min-width: 0;
	}
	.place {
		font-weight: 800;
		font-size: 13px;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
		flex: none;
		width: 20px;
		text-align: center;
	}
	.flag {
		flex: none;
		font-size: 16px;
	}
	.id {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 1px;
	}
	.nm {
		font-weight: 800;
		font-size: 14px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.sub {
		font-size: 10.5px;
		font-weight: 600;
		color: var(--dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.stats {
		display: flex;
		align-items: center;
		gap: 16px;
		flex: none;
	}
	.st {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		line-height: 1.1;
	}
	.st b {
		font-size: 13px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.st .dash {
		color: var(--faint);
		margin: 0 1px;
	}
	.st i {
		font-style: normal;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.top {
		display: flex;
		align-items: center;
		gap: 7px;
		flex: 1 1 170px;
		min-width: 0;
		justify-content: flex-end;
		color: inherit;
		text-decoration: none;
	}
	.crown {
		font-size: 11px;
		flex: none;
	}
	.tn {
		font-weight: 700;
		font-size: 12.5px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	a.top:hover .tn {
		color: var(--gold);
	}
	.tw {
		flex: none;
		font-size: 11px;
		font-weight: 800;
		color: var(--good);
		font-variant-numeric: tabular-nums;
	}
	/* Phones: the top player drops to its own full-width line, left-aligned under the stats. */
	@media (max-width: 560px) {
		.rg {
			gap: 8px 10px;
			padding: 10px 12px;
		}
		.lead {
			flex: 1 1 auto;
		}
		.stats {
			gap: 12px;
		}
		.top {
			flex: 1 1 100%;
			justify-content: flex-start;
			padding-left: 29px; /* align under the name (place + gap) */
		}
	}
</style>
