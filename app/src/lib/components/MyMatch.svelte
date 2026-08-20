<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { matchfeed } from '$lib/stores/matchfeed.svelte';
	import { api } from '$lib/config';
	import type { Profile } from '$lib/stores/profile.svelte';
	import { rankOf } from '$lib/ranks';
	import { charName } from '$lib/chars';
	import { flagEmoji } from '$lib/format';
	import RankBadge from './RankBadge.svelte';
	import Avatar from './Avatar.svelte';

	// THE live "versus" scoreboard — the signed-in user's CURRENT match, ported from the Tauri app's
	// #link plate scoreboard + #matchupStrip. Renders NOTHING unless you're signed in AND in a live match
	// (so it never leaves an empty shell). YOU always sit left (orange), the OPPONENT right (blue), a giant
	// gold VS between, the live set score on top, and a matchup-intel strip (win% · H2H · best team · kryptonite)
	// below. Presence + live score come from the network `nowPlaying` feed (SSE); teams from your profile's
	// current_match; the intel from /skinsync/matchup. Identical field names + copy to the desktop app.

	interface Matchup {
		win_chance?: number;
		my_elo?: number;
		opp_elo?: number;
		h2h?: { wins: number; losses: number };
		best_team_vs_them?: { team: string; wins: number } | null;
		their_kryptonite?: { team: string; losses: number } | null;
	}

	const me = $derived(auth.steamid);
	// The live now-playing row that includes me (network feed → live wins/ratings/join_link). Undefined = idle.
	const mine = $derived(me ? matchfeed.nowPlaying.find((p) => p.a === me || p.b === me) : undefined);
	const oppId = $derived(mine ? (mine.a === me ? mine.b : mine.a) : '');

	let myProfile = $state<Profile | null>(null);
	let oppProfile = $state<Profile | null>(null);
	let mu = $state<Matchup | null>(null);
	let fetchedFor = $state(''); // the oppId the three fetches above are currently resolved for
	let reqId = 0;

	// When the opponent changes (match start / new opponent), pull the details: my teams (from my profile's
	// current_match), the opponent's profile (avatar/flag/rating), and the matchup intel. Cached by oppId.
	$effect(() => {
		const opp = oppId;
		const my = me;
		if (!opp || !my) {
			myProfile = null;
			oppProfile = null;
			mu = null;
			fetchedFor = '';
			return;
		}
		if (opp === fetchedFor) return; // already resolved for this opponent
		const rq = ++reqId;
		Promise.all([
			fetch(api(`/skinsync/profile?steamid=${encodeURIComponent(my)}`), {
				headers: { accept: 'application/json' }
			})
				.then((r) => (r.ok ? (r.json() as Promise<Profile>) : null))
				.catch(() => null),
			fetch(api(`/skinsync/profile?steamid=${encodeURIComponent(opp)}`), {
				headers: { accept: 'application/json' }
			})
				.then((r) => (r.ok ? (r.json() as Promise<Profile>) : null))
				.catch(() => null),
			fetch(api(`/skinsync/matchup?me=${encodeURIComponent(my)}&opp=${encodeURIComponent(opp)}`), {
				headers: { accept: 'application/json' }
			})
				.then((r) => (r.ok ? (r.json() as Promise<Matchup>) : null))
				.catch(() => null)
		]).then(([mp, op, m]) => {
			if (rq !== reqId) return; // superseded by a newer opponent
			myProfile = mp;
			oppProfile = op;
			mu = m && !(m as { error?: unknown }).error ? m : null;
			fetchedFor = opp;
		});
	});

	// ── derived display values ──
	const cur = $derived(myProfile?.current_match ?? null);
	const games = (p: Profile | null) => (p ? (p.wins ?? 0) + (p.losses ?? 0) : 0);

	// names — prefer the live feed's name map, then profiles, then a shortened id.
	const shortId = (sid: string) => (sid ? `…${sid.slice(-5)}` : 'Player');
	const myName = $derived(auth.me?.name || myProfile?.name || (me ? shortId(me) : 'You'));
	const oppName = $derived(mine?.names?.[oppId] || oppProfile?.name || shortId(oppId));

	// ratings — the live feed carries per-sid ratings; fall back to the profile.
	const myRating = $derived(mine?.ratings?.[me ?? ''] ?? auth.me?.rating ?? myProfile?.rating ?? 1000);
	const oppRating = $derived(mine?.ratings?.[oppId] ?? oppProfile?.rating ?? 1000);
	const myGames = $derived(games(myProfile) || games(auth.me as Profile | null));
	const oppGames = $derived(games(oppProfile));

	const myTier = $derived(rankOf(myRating, myGames || null));
	const oppTier = $derived(rankOf(oppRating, oppGames || null));

	// live set score (from the feed's per-sid wins map).
	const myWins = $derived(mine?.wins?.[me ?? ''] ?? 0);
	const oppWins = $derived(mine?.wins?.[oppId] ?? 0);
	const hasScore = $derived(myWins > 0 || oppWins > 0);

	// current teams (this game) — char-id lists from my profile's current_match.
	const myTeam = $derived(cur?.my_chars ?? []);
	const oppTeam = $derived(cur?.opp_chars ?? []);
	const teamLine = (ids: number[]) => ids.map((id) => charName(id)).join(' / ');

	// matchup intel
	const winPct = $derived(mu ? Math.max(0, Math.min(100, Math.round((mu.win_chance ?? 0) * 100))) : null);
	const h2hW = $derived(mu?.h2h?.wins ?? 0);
	const h2hL = $derived(mu?.h2h?.losses ?? 0);
	// a team_key is a delimited char-id string → readable names.
	const teamKeyNames = (s: string) =>
		String(s || '')
			.split(/[^0-9]+/)
			.filter(Boolean)
			.map((n) => charName(Number(n)))
			.join(' / ');

	const flag = (cc?: string) => (cc ? flagEmoji(cc) : '');
</script>

{#if me && mine}
	<section class="mm" aria-label="Your current match">
		<div class="ghostvs" aria-hidden="true">VS</div>

		<!-- YOU (left, orange) -->
		<div class="plate p1">
			<Avatar url={myProfile?.avatar ?? (auth.me?.avatar as string | undefined)} size={52} alt={myName} />
			<div class="who">
				<div class="sidetag">You</div>
				<div class="nm">{#if flag(myProfile?.cc ?? auth.me?.cc)}<span class="fl">{flag(myProfile?.cc ?? auth.me?.cc)}</span> {/if}{myName}</div>
				<div class="rk">
					<RankBadge rating={myRating} games={myGames || null} size={15} />
					<span class="rk-t rk-{myTier.s}">{myTier.n}</span>
					<span class="elo">· {myRating}</span>
				</div>
				{#if myTeam.length}<div class="team">{teamLine(myTeam)}</div>{/if}
			</div>
		</div>

		<!-- center: score + VS + live pill -->
		<div class="center">
			{#if hasScore}
				<div class="score" title="Set score (live)">set <b>{myWins}</b><span class="d">–</span><b class="them">{oppWins}</b></div>
			{/if}
			<div class="vs-hero">VS</div>
			<span class="livepill"><span class="dot" aria-hidden="true"></span>IN MATCH</span>
		</div>

		<!-- OPPONENT (right, blue) -->
		<div class="plate p2">
			<div class="who">
				<div class="sidetag">Opponent</div>
				<div class="nm">{oppName}{#if flag(oppProfile?.cc)} <span class="fl">{flag(oppProfile?.cc)}</span>{/if}</div>
				<div class="rk">
					<RankBadge rating={oppRating} games={oppGames || null} size={15} />
					<span class="rk-t rk-{oppTier.s}">{oppTier.n}</span>
					<span class="elo">· {oppRating}</span>
				</div>
				{#if oppTeam.length}<div class="team">{teamLine(oppTeam)}</div>{/if}
				{#if h2hW || h2hL}
					<div class="rec"><span class="lbl">YOU</span> <b class="w">{h2hW}</b><span class="d">–</span><b class="l">{h2hL}</b> <span class="lbl">THEM</span></div>
				{:else if mu}
					<div class="rec first">first meeting</div>
				{/if}
			</div>
			<Avatar url={oppProfile?.avatar} size={52} alt={oppName} />
		</div>
	</section>

	<!-- matchup intel strip -->
	{#if mu}
		<div class="mu">
			<div class="mu-main">
				<div class="mu-win"><div class="mu-pct">{winPct}%</div><div class="mu-lbl">your win chance</div></div>
				<div class="mu-bar"><div class="mu-fill" style="width:{winPct}%"></div></div>
				<div class="mu-h2h">{#if h2hW || h2hL}head-to-head <b>{h2hW}–{h2hL}</b>{:else}first meeting{/if}</div>
			</div>
			<div class="mu-teams">
				<div class="mu-team">
					<div class="mu-tl">🏆 your best team vs them</div>
					<div class="mu-tv">{#if mu.best_team_vs_them}{teamKeyNames(mu.best_team_vs_them.team)} <small>{mu.best_team_vs_them.wins}W</small>{:else}<small>no wins vs them yet</small>{/if}</div>
				</div>
				<div class="mu-team">
					<div class="mu-tl">☠️ they lose most to</div>
					<div class="mu-tv">{#if mu.their_kryptonite}{teamKeyNames(mu.their_kryptonite.team)} <small>{mu.their_kryptonite.losses}L</small>{:else}<small>not enough data</small>{/if}</div>
				</div>
			</div>
		</div>
	{/if}
{/if}

<style>
	/* ── versus scoreboard (ported from the Tauri #link plates) ─────────────────────────────────── */
	.mm {
		position: relative;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 12px;
		padding: 16px;
		margin-bottom: 10px;
		overflow: hidden;
	}
	.ghostvs {
		position: absolute;
		left: 50%;
		top: 50%;
		transform: translate(-50%, -52%) skewX(-8deg);
		font-size: clamp(90px, 22vw, 150px);
		font-style: italic;
		font-weight: 900;
		letter-spacing: -0.04em;
		color: var(--ink);
		opacity: 0.035;
		pointer-events: none;
		user-select: none;
	}
	/* skewed parallelogram plates; contents un-skewed */
	.plate {
		position: relative;
		z-index: 1;
		display: flex;
		align-items: center;
		gap: 11px;
		min-width: 0;
		transform: skewX(-8deg);
		border: 1px solid var(--line);
		border-radius: 12px;
		padding: 11px 20px 11px 15px;
		background:
			linear-gradient(120deg, var(--p1-soft), transparent 60%), var(--panel-2);
		box-shadow: 0 6px 22px rgba(0, 0, 0, 0.28);
	}
	.plate > :global(*) {
		transform: skewX(8deg);
	}
	.plate.p1 {
		border-left: 4px solid var(--p1);
	}
	.plate.p2 {
		justify-content: flex-end;
		text-align: right;
		border-right: 4px solid var(--p2);
		padding: 11px 15px 11px 20px;
		background: linear-gradient(240deg, var(--p2-soft), transparent 60%), var(--panel-2);
	}
	.plate.p2 .who {
		order: 1;
	}
	.who {
		min-width: 0;
	}
	.sidetag {
		font-size: 10px;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--faint);
		font-weight: 700;
	}
	.nm {
		font-weight: 800;
		font-size: 17px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rk {
		display: flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		margin-top: 3px;
	}
	.plate.p2 .rk {
		justify-content: flex-end;
	}
	.rk-t {
		font-weight: 800;
	}
	.elo {
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}
	.team {
		font-size: 11px;
		font-weight: 700;
		color: var(--dim);
		margin-top: 3px;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.rec {
		font-size: 11.5px;
		margin-top: 3px;
		color: var(--faint);
	}
	.rec .lbl {
		opacity: 0.6;
		letter-spacing: 0.02em;
	}
	.rec .w {
		color: #3ddc84;
		font-size: 1.12em;
	}
	.rec .l {
		color: #ff6b6b;
		font-size: 1.12em;
	}
	.rec .d {
		opacity: 0.4;
		margin: 0 3px;
	}
	.rec.first {
		font-style: italic;
	}
	/* tier text colors (Marvel ladder) */
	.rk-iron { color: #a7adb8; }
	.rk-bronze { color: #d59a5f; }
	.rk-silver { color: #cdd7e4; }
	.rk-gold { color: #f2c74a; }
	.rk-vibranium { color: #b98cff; }
	.rk-adamantium { color: #9fd4ef; }
	.rk-herald { color: #ffb35c; }
	.rk-infinity { color: #ffe9b0; }
	.rk-galactus { color: #ff7ae0; }
	.rk-civilian { color: var(--dim); }

	/* center column */
	.center {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
	}
	.score {
		display: flex;
		align-items: baseline;
		gap: 5px;
		font-size: 10.5px;
		color: var(--dim);
	}
	.score b {
		font-size: 22px;
		font-weight: 900;
		font-style: italic;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
	}
	.score b.them {
		color: var(--ink);
	}
	.score .d {
		opacity: 0.55;
	}
	.vs-hero {
		font-size: clamp(38px, 9vw, 56px);
		line-height: 0.9;
		font-style: italic;
		font-weight: 900;
		letter-spacing: -0.03em;
		background: linear-gradient(175deg, #fff3c0 20%, var(--gold) 45%, #a3670a 80%);
		-webkit-background-clip: text;
		background-clip: text;
		color: transparent;
		filter: drop-shadow(0 4px 14px rgba(232, 185, 60, 0.3));
		user-select: none;
	}
	.livepill {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.07em;
		text-transform: uppercase;
		padding: 4px 10px;
		border-radius: 999px;
		color: var(--good);
		border: 1px solid color-mix(in srgb, var(--good) 45%, var(--line));
		background: color-mix(in srgb, var(--good) 12%, var(--panel));
		white-space: nowrap;
	}
	.livepill .dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--good);
		box-shadow: 0 0 8px var(--good);
	}
	@media (prefers-reduced-motion: no-preference) {
		.livepill .dot {
			animation: mmpulse 1.1s ease-in-out infinite;
		}
	}
	@keyframes mmpulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.4; }
	}

	/* ── matchup intel strip ─────────────────────────────────────────────────────────────────────── */
	.mu {
		display: flex;
		align-items: center;
		gap: 14px;
		flex-wrap: wrap;
		padding: 8px 14px;
		margin-bottom: 10px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--panel);
	}
	.mu-main {
		display: flex;
		align-items: center;
		gap: 12px;
		flex: 1;
		min-width: 240px;
	}
	.mu-win {
		text-align: center;
		flex: none;
	}
	.mu-pct {
		font-size: 18px;
		font-weight: 900;
		line-height: 1;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
	}
	.mu-lbl {
		font-size: 9.5px;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--dim);
		margin-top: 3px;
	}
	.mu-bar {
		flex: 1 1 auto;
		height: 8px;
		max-width: 180px;
		border-radius: 99px;
		background: var(--p2-soft);
		overflow: hidden;
		min-width: 70px;
	}
	.mu-fill {
		height: 100%;
		border-radius: 99px;
		background: linear-gradient(90deg, var(--p2), var(--gold));
		transition: width 0.45s ease;
	}
	.mu-h2h {
		font-size: 12px;
		color: var(--dim);
		white-space: nowrap;
	}
	.mu-h2h b {
		color: var(--ink);
		font-weight: 800;
	}
	.mu-teams {
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
	}
	.mu-team {
		min-width: 128px;
	}
	.mu-tl {
		font-size: 10px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--dim);
		margin-bottom: 3px;
	}
	.mu-tv {
		font-size: 11.5px;
		font-weight: 700;
		color: var(--ink);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 260px;
	}
	.mu-tv small {
		color: var(--dim);
		font-weight: 600;
	}

	/* phones: stack the plates, shrink the hero */
	@media (max-width: 560px) {
		.mm {
			gap: 8px;
			padding: 12px 10px;
		}
		.nm {
			font-size: 15px;
		}
		.plate {
			padding: 9px 12px;
			gap: 8px;
		}
	}
</style>
