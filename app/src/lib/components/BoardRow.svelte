<script lang="ts">
	import { base } from '$app/paths';
	import RankBadge from './RankBadge.svelte';
	import Avatar from './Avatar.svelte';
	import { rankOf, gamesOf, winrateOf, winrateColor } from '$lib/ranks';
	import { statValue } from '$lib/boards';
	import { flagEmoji } from '$lib/format';
	import type { Player, LeaderboardTab } from '$lib/types';

	let {
		player,
		pos,
		tab,
		me = false,
		flash = false,
		scoped = false
	}: {
		player: Player;
		pos: number | null;
		tab: LeaderboardTab;
		me?: boolean;
		flash?: boolean;
		// Lobby/Tournament scope: no rating/rank on the row → the tier cell is omitted.
		scoped?: boolean;
	} = $props();

	const r = $derived(rankOf(player.rating, gamesOf(player)));
	const w = $derived(winrateOf(player));
	const val = $derived(statValue(player, tab));
	// verified-wins badge on the Wins board — confirmed by both-agree / replay
	const cw = $derived(player.confirmed_wins == null ? null : Number(player.confirmed_wins));
	const showVerified = $derived(tab === 'wins' && cw != null && cw < val);
</script>

<div class="bd-row" class:me class:flash>
	<div class="bd-rank">{pos == null ? '—' : pos}</div>
	<div class="bd-name">
		{#if player.steamid}
			<a class="lnk" href="{base}/u/{player.steamid}">
				<Avatar url={player.avatar} size={20} alt={player.name} />
				{#if player.cc}<span class="flag">{flagEmoji(player.cc)}</span>{/if}
				<span class="nm">{player.name || 'Player'}</span>
			</a>
		{:else}
			<Avatar url={player.avatar} size={20} alt={player.name} />
			{#if player.cc}<span class="flag">{flagEmoji(player.cc)}</span>{/if}
			<span class="nm">{player.name || 'Player'}</span>
		{/if}
		{#if me}<span class="me-tag">YOU</span>{/if}
	</div>
	{#if !scoped}
		<div class="bd-tier">
			<RankBadge rating={player.rating} games={gamesOf(player)} size={16} />
			<span class="rk-{r.s}">{r.n}</span>
		</div>
	{/if}
	<div class="bd-num">
		{val}{#if showVerified}<span class="verified" title="{cw} of {val} wins verified">✓{cw}</span>{/if}
	</div>
	<div class="bd-num dim col-wl">{player.wins ?? 0} – {player.losses ?? 0}</div>
	<div class="bd-num col-wr" style="color:{winrateColor(w)}">{w}%</div>
</div>

<style>
	.bd-row {
		display: grid;
		grid-template-columns: var(--bd-cols);
		align-items: center;
		gap: 10px;
		padding: 0 14px;
		height: 44px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
		content-visibility: auto;
		contain-intrinsic-size: auto 44px;
	}
	.bd-row.me {
		box-shadow: 0 0 0 1.5px var(--gold) inset;
		background: linear-gradient(90deg, var(--gold-soft), transparent 45%);
	}
	.bd-rank {
		font-weight: 800;
		font-size: 13.5px;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
		text-align: center;
	}
	.bd-name {
		font-weight: 700;
		font-size: 13.5px;
		display: flex;
		align-items: center;
		gap: 7px;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
	}
	.bd-name .lnk {
		display: flex;
		align-items: center;
		gap: 7px;
		min-width: 0;
		overflow: hidden;
		color: inherit;
		text-decoration: none;
	}
	.bd-name .lnk:hover .nm {
		color: var(--gold);
	}
	.bd-name .nm {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.flag {
		flex: none;
	}
	.me-tag {
		font-size: 10px;
		color: var(--gold);
		font-weight: 800;
		margin-left: 6px;
		letter-spacing: 0.06em;
	}
	.bd-tier {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 800;
		font-size: 12.5px;
	}
	.bd-num {
		font-variant-numeric: tabular-nums;
		text-align: right;
		font-size: 13px;
		font-weight: 700;
	}
	.bd-num.dim {
		color: var(--dim);
		font-size: 12px;
		font-weight: 500;
	}
	.verified {
		margin-left: 5px;
		font-size: 10px;
		font-weight: 800;
		color: var(--good);
	}
	/* one-shot flash on a row whose value changed live — ≤900ms, motion-safe only */
	.flash {
		animation: rowflash 0.85s ease-out 1;
	}
	@keyframes rowflash {
		0% {
			background: color-mix(in srgb, var(--gold) 26%, transparent);
		}
		100% {
			background: transparent;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.flash {
			animation: none;
		}
	}
	/* Match Board's mobile collapse: drop tier · W–L · win% so rank · name · stat stay aligned. */
	@media (max-width: 640px) {
		.bd-row {
			gap: 8px;
			padding: 0 12px;
		}
		.bd-tier,
		.col-wl,
		.col-wr {
			display: none;
		}
	}
</style>
