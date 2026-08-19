<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ProfileStore } from '$lib/stores/profile.svelte';
	import RankBadge from '$lib/components/RankBadge.svelte';
	import Avatar from '$lib/components/Avatar.svelte';
	import StatTile from '$lib/components/StatTile.svelte';
	import MatchRow from '$lib/components/MatchRow.svelte';
	import { rankOf, gamesOf, winrateOf, winrateColor, RK_PLATE } from '$lib/ranks';
	import { flagEmoji } from '$lib/format';

	const store = new ProfileStore();
	const sid = $derived(page.params.steamid ?? '');

	// Load whenever the route param changes (covers first mount + client-side nav between profiles).
	// `loadedSid` is a plain local (not $state) so writing it never re-triggers this effect.
	let loadedSid = '';
	$effect(() => {
		const s = sid;
		if (s && s !== loadedSid) {
			loadedSid = s;
			void store.load(s);
		}
	});

	// Live current-match banner via the shared "matches" channel; pause while backgrounded (CPU discipline).
	onMount(() => {
		store.connect();
		const onVis = () => {
			if (document.hidden) store.disconnect();
			else {
				store.connect();
				void store.load(store.steamid); // catch anything missed while hidden
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			store.disconnect();
		};
	});

	const p = $derived(store.data);
	const found = $derived(!!p && p.found);
	const gp = $derived(p ? gamesOf({ wins: p.wins, losses: p.losses }) : 0);
	const r = $derived(rankOf(p?.rating, gp));
	const acc = $derived(RK_PLATE[r.s] ?? RK_PLATE.civilian);
	const wr = $derived(p ? winrateOf({ wins: p.wins, losses: p.losses }) : 0);
	const loc = $derived([p?.city, p?.region].filter(Boolean).join(', ') || p?.country || '');
	const rating = $derived(p?.rating ?? 1000);
	const showPeak = $derived(!!p?.peak_rating && (p.peak_rating ?? 0) > rating);
	const cur = $derived(p?.current_match ?? null);
	const recent = $derived(p?.recent ?? []);
	const cold = $derived(store.loading && !p);
	const title = $derived(p?.name || 'Player');
</script>

<svelte:head><title>{title} · MetaSync</title></svelte:head>

{#if cold}
	<div class="empty">LOADING…</div>
{:else if !p}
	<div class="empty">Couldn’t load this profile — check your connection and try again.</div>
{:else if !found}
	<div class="empty">No player found for that ID.</div>
{:else}
	<!-- Hero: avatar · name+flag+location · rank plate -->
	<section class="hero" style="--pa:{acc[0]}; --pb:{acc[1]}">
		<div class="id">
			<Avatar url={p.avatar} size={64} alt={p.name} />
			<div class="who">
				<h1 class="nm">{#if p.cc}<span class="flag">{flagEmoji(p.cc)}</span> {/if}{p.name || 'Player'}</h1>
				{#if loc}<span class="loc">{loc}</span>{/if}
			</div>
		</div>
		<div class="rank">
			<RankBadge rating={rating} games={gp} size={34} />
			<div class="rcol">
				<b class="rk-{r.s} tier">{r.n}</b>
				<span class="elo">{rating}<i>ELO</i></span>
				{#if showPeak}<span class="peak" title="All-time peak rating">peak {p.peak_rating}</span>{/if}
			</div>
		</div>
	</section>

	{#if cur}
		<div class="live">
			<span class="dot" aria-hidden="true"></span>
			<span>🟢 In a match now — vs <b>{cur.opp_name || 'opponent'}</b></span>
		</div>
	{/if}

	<!-- Stat tiles -->
	<div class="tiles">
		<StatTile label="Wins" value={p.wins ?? 0} accent="#4ade80" />
		<StatTile label="Losses" value={p.losses ?? 0} accent="#f87171" />
		<StatTile label="Win %" value={`${wr}%`} accent={winrateColor(wr)} hint="{p.wins ?? 0}W · {p.losses ?? 0}L over {gp} games" />
		<StatTile label="OCVs" value={p.ocvs ?? 0} accent="#ff7ae0" hint="One-character victories" />
		<StatTile label="Comebacks" value={p.comebacks ?? 0} accent="#4ade80" />
		<StatTile label="Perfects" value={p.perfects ?? 0} accent="#9fd4ef" />
		<StatTile label="Best Streak" value={p.best_streak ?? 0} accent="#ffb35c" />
		<StatTile label="Best Combo" value={p.best_combo ?? 0} accent="var(--gold)" />
		<StatTile label="Meters" value={p.meters ?? 0} />
		<StatTile label="Verified Wins" value={p.verified_wins ?? 0} accent="var(--good)" hint="Wins confirmed by both players / replay" />
	</div>

	<!-- Recent matches -->
	<div class="rail sec-hd">Recent matches</div>
	{#if recent.length}
		<div class="matches">
			{#each recent.slice(0, 20) as m, i (m.mid ?? m.match_key ?? i)}
				<MatchRow match={m} />
			{/each}
		</div>
	{:else}
		<div class="empty">No matches logged yet.</div>
	{/if}
{/if}

<style>
	.hero {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
		flex-wrap: wrap;
		margin: 10px 0 12px;
		padding: 14px 16px;
		border: 1px solid var(--line);
		border-left: 4px solid var(--pa, var(--line));
		border-radius: 14px;
		background:
			linear-gradient(120deg, color-mix(in srgb, var(--pa, var(--line)) 14%, transparent), transparent 68%),
			linear-gradient(180deg, var(--panel-2), var(--panel));
		box-shadow: var(--shadow);
	}
	.id {
		display: flex;
		align-items: center;
		gap: 13px;
		min-width: 0;
		flex: 1 1 auto;
	}
	.who {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.nm {
		font-size: clamp(19px, 5vw, 25px);
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.01em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.nm .flag {
		font-style: normal;
	}
	.loc {
		font-size: 12px;
		color: var(--dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.rank {
		display: flex;
		align-items: center;
		gap: 10px;
		flex: none;
	}
	.rcol {
		display: flex;
		flex-direction: column;
		line-height: 1.15;
	}
	.tier {
		font-size: 15px;
		font-weight: 900;
	}
	.elo {
		font-size: 15px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}
	.elo i {
		font-style: normal;
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.1em;
		color: var(--faint);
		margin-left: 4px;
	}
	.peak {
		font-size: 10px;
		font-weight: 700;
		color: var(--faint);
	}

	.live {
		display: flex;
		align-items: center;
		gap: 9px;
		margin: 0 0 12px;
		padding: 10px 14px;
		border: 1px solid color-mix(in srgb, var(--good) 40%, var(--line));
		background: color-mix(in srgb, var(--good) 10%, transparent);
		border-radius: 11px;
		font-size: 13px;
		font-weight: 600;
	}
	.live .dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--good);
		flex: none;
		box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 60%, transparent);
	}
	@media (prefers-reduced-motion: no-preference) {
		.live .dot {
			animation: pulse 1.8s ease-out infinite;
		}
	}
	@keyframes pulse {
		0% {
			box-shadow: 0 0 0 0 color-mix(in srgb, var(--good) 55%, transparent);
		}
		100% {
			box-shadow: 0 0 0 7px transparent;
		}
	}

	.tiles {
		display: grid;
		/* explicit reflow with minmax(0,1fr) tracks — they shrink under the number on a phone
		   (bare 1fr = minmax(auto,1fr) would NOT, and the tile's overflow:hidden clips instead). */
		grid-template-columns: repeat(5, minmax(0, 1fr));
		gap: 8px;
		margin-bottom: 4px;
	}
	@media (max-width: 720px) {
		.tiles {
			grid-template-columns: repeat(4, minmax(0, 1fr));
		}
	}
	@media (max-width: 480px) {
		.tiles {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
	}

	.sec-hd {
		display: block;
		margin: 18px 2px 8px;
	}
	.matches {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
	}
</style>
