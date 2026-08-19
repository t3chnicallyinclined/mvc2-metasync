<script lang="ts">
	import { base } from '$app/paths';
	import { timeAgo } from '$lib/format';
	import { teamAbbr } from '$lib/chars';
	import type { RecentMatch } from '$lib/stores/profile.svelte';

	let { match }: { match: RecentMatch } = $props();

	const won = $derived(!!match.won);
	const myTeam = $derived(teamAbbr(match.my_team));
	const oppTeam = $derived(teamAbbr(match.opp_team));
	const combo = $derived(Number(match.combo ?? 0));
	const elo = $derived(typeof match.elo === 'number' ? match.elo : 0);
	const when = $derived(timeAgo(match.ts));
	// confirmed/verified hint: ✓✓ both-agree+replay, ✓ confirmed, · unconfirmed.
	const seal = $derived(match.verified ? '✓✓' : match.confirmed ? '✓' : '');
	const oppHref = $derived(
		match.opp_id && String(match.opp_id).length === 17 ? `${base}/u/${match.opp_id}` : null
	);
</script>

<div class="mr" class:won class:lost={!won}>
	<span class="wl" aria-label={won ? 'Win' : 'Loss'}>{won ? 'W' : 'L'}</span>

	<div class="mid">
		<div class="line1">
			{#if oppHref}
				<a class="opp" href={oppHref}>{match.opp || 'Opponent'}</a>
			{:else}
				<span class="opp">{match.opp || 'Opponent'}</span>
			{/if}
			{#if seal}<span class="seal" title={match.verified ? 'Verified (both agree + replay)' : 'Confirmed'}>{seal}</span>{/if}
		</div>
		{#if myTeam || oppTeam}
			<div class="teams" title="{myTeam || '—'} vs {oppTeam || '—'}">
				<span class="tm">{myTeam || '—'}</span>
				<i>vs</i>
				<span class="tm dim">{oppTeam || '—'}</span>
			</div>
		{/if}
	</div>

	<div class="flair">
		{#if match.ocv}<span class="chip ocv" title="One-Character Victory">OCV</span>{/if}
		{#if match.perfect}<span class="chip perf" title="Perfect">PERF</span>{/if}
		{#if match.comeback}<span class="chip cb" title="Comeback">CB</span>{/if}
		{#if combo > 0}<span class="chip combo" title="Max combo this match">🎯 {combo}</span>{/if}
	</div>

	<div class="right">
		<b class="elo" class:up={elo >= 0} class:down={elo < 0}>{elo > 0 ? '+' : ''}{elo}</b>
		{#if when}<span class="ago">{when}</span>{/if}
	</div>
</div>

<style>
	.mr {
		display: grid;
		grid-template-columns: 26px minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 10px;
		padding: 8px 12px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.mr:last-child {
		border-bottom: none;
	}
	.wl {
		width: 22px;
		height: 22px;
		border-radius: 6px;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 12px;
		font-weight: 900;
		color: #0b0d12;
	}
	.won .wl {
		background: #4ade80;
	}
	.lost .wl {
		background: #f87171;
	}
	.mid {
		min-width: 0;
	}
	.line1 {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.opp {
		font-weight: 700;
		font-size: 13.5px;
		color: var(--ink);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	a.opp:hover {
		color: var(--gold);
	}
	.seal {
		flex: none;
		font-size: 10px;
		font-weight: 800;
		color: var(--good);
	}
	.teams {
		display: flex;
		align-items: baseline;
		gap: 5px;
		margin-top: 1px;
		font-size: 10.5px;
		font-weight: 700;
		letter-spacing: 0.03em;
		color: var(--dim);
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
		min-width: 0;
	}
	.teams i {
		font-style: normal;
		color: var(--faint);
		font-weight: 600;
	}
	.teams .tm {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.teams .tm.dim {
		color: var(--faint);
	}
	.flair {
		display: flex;
		align-items: center;
		gap: 4px;
		flex: none;
	}
	.chip {
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.04em;
		padding: 2px 5px;
		border-radius: 5px;
		white-space: nowrap;
		border: 1px solid var(--line);
		color: var(--dim);
	}
	.chip.ocv {
		color: #ff7ae0;
		border-color: color-mix(in srgb, #ff7ae0 40%, var(--line));
		background: color-mix(in srgb, #ff7ae0 12%, transparent);
	}
	.chip.perf {
		color: #9fd4ef;
		border-color: color-mix(in srgb, #9fd4ef 40%, var(--line));
		background: color-mix(in srgb, #9fd4ef 12%, transparent);
	}
	.chip.cb {
		color: #4ade80;
		border-color: color-mix(in srgb, #4ade80 40%, var(--line));
		background: color-mix(in srgb, #4ade80 12%, transparent);
	}
	.chip.combo {
		color: var(--gold);
		border-color: color-mix(in srgb, var(--gold) 34%, var(--line));
	}
	.right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 1px;
		flex: none;
	}
	.elo {
		font-size: 13px;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	.elo.up {
		color: #4ade80;
	}
	.elo.down {
		color: #f87171;
	}
	.ago {
		font-size: 10px;
		color: var(--faint);
		white-space: nowrap;
	}
	/* Phones: the flair chips are the first to go so the opponent name + result + ELO always fit. */
	@media (max-width: 480px) {
		.mr {
			grid-template-columns: 24px minmax(0, 1fr) auto;
			gap: 8px;
			padding: 8px 10px;
		}
		.flair {
			display: none;
		}
	}
</style>
