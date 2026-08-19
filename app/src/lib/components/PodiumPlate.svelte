<script lang="ts">
	import { base } from '$app/paths';
	import RankBadge from './RankBadge.svelte';
	import Avatar from './Avatar.svelte';
	import { rankOf, gamesOf, winrateOf, RK_PLATE } from '$lib/ranks';
	import { statValue, MAST } from '$lib/boards';
	import { flagEmoji } from '$lib/format';
	import type { Player, LeaderboardTab } from '$lib/types';

	let {
		player,
		place,
		tab
	}: { player: Player; place: 1 | 2 | 3; tab: LeaderboardTab } = $props();

	const r = $derived(rankOf(player.rating, gamesOf(player)));
	const acc = $derived(RK_PLATE[r.s] ?? RK_PLATE.civilian);
	const crown = $derived(place === 1);
</script>

<div
	class="pod c{place}"
	class:crown
	style="--pa:{acc[0]}; --pb:{acc[1]}; --lb-acc:{MAST[tab][2]}"
>
	<span class="mark mono">{crown ? '👑' : '#' + place}</span>
	{#if player.steamid}
		<a class="av-link" href="{base}/u/{player.steamid}" aria-label={player.name || 'Player'}>
			<Avatar url={player.avatar} size={crown ? 58 : 46} alt={player.name} />
		</a>
		<a class="pnm plink" href="{base}/u/{player.steamid}">{#if player.cc}{flagEmoji(player.cc)} {/if}{player.name || 'Player'}</a>
	{:else}
		<Avatar url={player.avatar} size={crown ? 58 : 46} alt={player.name} />
		<b class="pnm">{#if player.cc}{flagEmoji(player.cc)} {/if}{player.name || 'Player'}</b>
	{/if}
	<span class="ptier bd-tier">
		<RankBadge rating={player.rating} games={gamesOf(player)} size={crown ? 20 : 16} />
		<span class="rk-{r.s}">{r.n}</span>
	</span>
	<b class="prt">{statValue(player, tab)}</b>
	<span class="pwl">{player.wins ?? 0}W · {player.losses ?? 0}L · {winrateOf(player)}%</span>
</div>

<style>
	.pod {
		transform: skewX(-6deg);
		background:
			linear-gradient(120deg, color-mix(in srgb, var(--pa, var(--line)) 14%, transparent), transparent 70%),
			linear-gradient(180deg, var(--panel-2), var(--panel));
		border: 1px solid var(--line);
		border-left: 4px solid var(--pa, var(--line));
		border-radius: 13px;
		padding: 14px 12px 12px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 5px;
		cursor: default;
		min-width: 0;
		overflow: hidden;
	}
	.pwl,
	.ptier {
		max-width: 100%;
	}
	.pod > :global(*) {
		transform: skewX(6deg);
	}
	.pod.crown {
		border-color: color-mix(in srgb, var(--gold) 55%, var(--line));
		border-left-color: var(--pa, var(--gold));
		box-shadow: 0 0 24px rgba(232, 185, 60, 0.08);
		padding-top: 18px;
	}
	.mark {
		font-weight: 800;
		font-size: 12px;
	}
	.crown .mark {
		font-size: 16px;
	}
	.pnm {
		font-size: 14px;
		font-weight: 800;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.av-link {
		display: inline-flex;
		line-height: 0;
		text-decoration: none;
	}
	a.pnm {
		text-decoration: none;
		color: inherit;
	}
	a.pnm:hover {
		color: var(--gold);
	}
	.ptier {
		display: flex;
		align-items: center;
		gap: 6px;
		font-weight: 800;
		font-size: 12.5px;
	}
	.prt {
		font-size: 22px;
		font-weight: 900;
		font-family: ui-monospace, Consolas, monospace;
		font-variant-numeric: tabular-nums;
	}
	.crown .prt {
		font-size: 27px;
		color: var(--gold);
	}
	.pwl {
		font-size: 11.5px;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
	}
	/* On phones the skewX lean pushes the rightmost plate past the viewport (body is
	   overflow-x:hidden → it gets clipped). Straighten the plates and tighten padding so
	   all three fit exactly. */
	@media (max-width: 560px) {
		.pod {
			transform: none;
			padding: 12px 8px 10px;
			gap: 4px;
		}
		.pod.crown {
			padding-top: 14px;
		}
		.pod > :global(*) {
			transform: none;
		}
		.pnm {
			font-size: 13px;
		}
		.prt {
			font-size: 20px;
		}
		.crown .prt {
			font-size: 24px;
		}
	}
</style>
