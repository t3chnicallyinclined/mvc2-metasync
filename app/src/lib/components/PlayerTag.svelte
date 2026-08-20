<script lang="ts">
	import { base } from '$app/paths';
	import RankBadge from './RankBadge.svelte';

	// One player on a match banner: [rank badge] name (→ profile) [rating]. The rank tier is CLIENT-
	// derived from the rating via RankBadge (games omitted → the rating-based "placed" tier, same path
	// /ranks + the profile use) — the server's rank string is intentionally ignored (different scheme).
	// The rating badge + number render only when a rating is present (ranked play); lobby/tourney omit
	// them but keep the name, so the row layout stays identical across modes.
	let {
		sid,
		name,
		rating,
		emphasis = 'neutral',
		onLinkClick
	}: {
		sid: string;
		name: string;
		rating?: number;
		emphasis?: 'win' | 'lose' | 'live' | 'neutral';
		onLinkClick?: (e: Event) => void;
	} = $props();

	const is17 = $derived(/^\d{17}$/.test(sid));
</script>

<span class="pt {emphasis}">
	{#if rating != null}<RankBadge {rating} size={16} />{/if}
	{#if is17}
		<a class="pn" href="{base}/u/{sid}" onclick={onLinkClick} title={name}>{name}</a>
	{:else}
		<span class="pn" title={name}>{name}</span>
	{/if}
	{#if rating != null}<span class="rt">{rating}</span>{/if}
</span>

<style>
	.pt {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		min-width: 0;
		flex: 0 1 auto;
	}
	.pn {
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
		font-size: 13.5px;
	}
	.pt.win .pn {
		font-weight: 800;
		color: var(--ink);
	}
	.pt.lose .pn {
		font-weight: 600;
		font-size: 13px;
		color: var(--dim);
	}
	.pt.live .pn,
	.pt.neutral .pn {
		font-weight: 700;
		color: var(--ink);
	}
	a.pn:hover {
		color: var(--gold);
	}
	.pt.lose a.pn:hover {
		color: var(--ink);
	}
	.rt {
		flex: none;
		font-size: 11px;
		font-weight: 700;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
	}
	.pt.lose .rt {
		color: var(--faint);
		font-weight: 600;
	}
</style>
