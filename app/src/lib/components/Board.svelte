<script lang="ts">
	import { createVirtualizer } from '@tanstack/svelte-virtual';
	import BoardRow from './BoardRow.svelte';
	import { STAT_LABEL } from '$lib/boards';
	import type { BoardItem, LeaderboardTab } from '$lib/types';

	// The ARENA "Board" — a dense columnar list. Rows + tier cutlines are virtualized with
	// @tanstack/svelte-virtual so only on-screen rows exist in the DOM (event-driven, ~0 idle CPU).
	// Heights are deterministic (row 44px, cut 26px) → exact estimateSize, no dynamic measurement.
	let {
		items,
		tab,
		flashIds,
		mySteam = null,
		scoped = false
	}: {
		items: BoardItem[];
		tab: LeaderboardTab;
		flashIds: Set<string>;
		mySteam?: string | null;
		// Lobby/Tournament scope: rows carry no rating/rank → drop the Tier column entirely.
		scoped?: boolean;
	} = $props();

	const ROW = 44;
	const CUT = 26;

	let scrollEl = $state<HTMLDivElement | null>(null);

	// $derived.by reads `scrollEl` and `items.length` so it rebinds when the scroller mounts and when
	// the row count changes. On scroll the store emits the SAME instance → reference stays stable.
	const virtualizer = $derived.by(() => {
		const el = scrollEl;
		const count = items.length;
		return createVirtualizer<HTMLDivElement, HTMLDivElement>({
			count,
			getScrollElement: () => el,
			estimateSize: (i) => (items[i]?.kind === 'cut' ? CUT : ROW),
			overscan: 12,
			getItemKey: (i) => items[i]?.key ?? i
		});
	});
</script>

<div class="board" class:scoped>
	<div class="bd-head">
		<span class="c">#</span>
		<span>Player</span>
		{#if !scoped}<span class="col-tier">Tier</span>{/if}
		<span class="r">{tab === 'rating' ? 'Rating' : STAT_LABEL[tab]}</span>
		<span class="r col-wl">W – L</span>
		<span class="r col-wr">Win %</span>
	</div>
	<div class="bd-scroll" bind:this={scrollEl}>
		<div class="bd-canvas" style="height:{$virtualizer.getTotalSize()}px">
			{#each $virtualizer.getVirtualItems() as v (v.key)}
				{@const item = items[v.index]}
				<div class="bd-abs" style="transform:translateY({v.start}px); height:{v.size}px">
					{#if item.kind === 'cut'}
						<div class="bd-cut" style="color:{item.color}"><i></i><span>{item.label}</span><i></i></div>
					{:else}
						<BoardRow
							player={item.player}
							pos={item.pos}
							{tab}
							{scoped}
							me={mySteam != null && item.player.steamid === mySteam}
							flash={flashIds.has(item.player.steamid)}
						/>
					{/if}
				</div>
			{/each}
		</div>
	</div>
</div>

<style>
	.board {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
		/* desktop: rank · name · tier · stat · W–L · win% (defined here so a media query can override) */
		--bd-cols: 40px minmax(0, 1fr) 138px 92px 84px 60px;
	}
	/* Scoped (Lobby/Tournament): no Tier column — rank · name · stat · W–L · win%. Rows omit the
	   tier cell too (BoardRow) so the grid stays aligned. */
	.board.scoped {
		--bd-cols: 40px minmax(0, 1fr) 92px 84px 60px;
	}
	.bd-head {
		display: grid;
		grid-template-columns: var(--bd-cols);
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
		position: sticky;
		top: 0;
		z-index: 2;
		background: var(--panel);
	}
	.bd-head .c {
		text-align: center;
	}
	.bd-head .r {
		text-align: right;
	}
	.bd-scroll {
		max-height: min(72vh, 880px);
		max-height: min(72dvh, 880px);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.bd-canvas {
		position: relative;
		width: 100%;
	}
	.bd-abs {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
	}
	.bd-cut {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 3px 12px;
		height: 26px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		white-space: nowrap;
	}
	.bd-cut i {
		flex: 1;
		height: 1px;
		background: currentColor;
		opacity: 0.3;
	}
	/* Phones can't hold six columns — the tier cutline bands already label each tier, so
	   collapse to rank · name · stat. Rows hide the same cells (BoardRow) to stay aligned. */
	@media (max-width: 640px) {
		/* Both selectors listed so `.board.scoped` (higher specificity) can't keep its desktop
		   track count on phones. */
		.board,
		.board.scoped {
			--bd-cols: 28px minmax(0, 1fr) auto;
		}
		.bd-head {
			gap: 8px;
			padding: 0 12px;
		}
		.bd-head .col-tier,
		.bd-head .col-wl,
		.bd-head .col-wr {
			display: none;
		}
	}
</style>
