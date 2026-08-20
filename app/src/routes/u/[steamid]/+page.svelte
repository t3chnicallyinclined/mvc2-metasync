<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { page } from '$app/state';
	import { ProfileStore } from '$lib/stores/profile.svelte';
	import { PlayerStatsStore } from '$lib/stores/playerstats.svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import RankBadge from '$lib/components/RankBadge.svelte';
	import Avatar from '$lib/components/Avatar.svelte';
	import StatTile from '$lib/components/StatTile.svelte';
	import MatchRow from '$lib/components/MatchRow.svelte';
	import QuarterUpForm from '$lib/components/QuarterUpForm.svelte';
	import { rankOf, gamesOf, winrateOf, winrateColor, RK_PLATE } from '$lib/ranks';
	import { flagEmoji } from '$lib/format';

	const store = new ProfileStore();
	const stats = new PlayerStatsStore();
	const sid = $derived(page.params.steamid ?? '');

	// Load whenever the route param changes (covers first mount + client-side nav between profiles).
	// `loadedSid` is a plain local (not $state) so writing it never re-triggers this effect.
	let loadedSid = '';
	$effect(() => {
		const s = sid;
		if (s && s !== loadedSid) {
			loadedSid = s;
			void store.load(s);
			void stats.load(s);
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

	// Per-mode records (game-modes policy). Shown only when the player has games in that mode; lobby is
	// owner-or-public (null when hidden). Ranked lives in the main tiles above.
	const tRec = $derived(p?.tourney ?? null);
	const mRec = $derived(p?.money ?? null);
	const lRec = $derived(p?.lobby ?? null);
	const tGames = $derived((tRec?.wins ?? 0) + (tRec?.losses ?? 0));
	const mGames = $derived((mRec?.wins ?? 0) + (mRec?.losses ?? 0));
	const lGames = $derived(lRec ? (lRec.wins ?? 0) + (lRec.losses ?? 0) : 0);
	const hasModeRecs = $derived(tGames > 0 || mGames > 0 || lGames > 0);

	// ── owner controls (own profile only) ──────────────────────────────────────────────────────────
	// Only the signed-in owner of THIS profile sees the lobby-visibility toggle. lRec is non-null for the
	// owner (the profile fetch carries their bearer), so `public` reflects the true current state.
	const isOwner = $derived(auth.authed && auth.steamid === sid);
	const lobbyPublic = $derived(!!lRec?.public);
	let ownerBusy = $state(false);
	let ownerMsg = $state<string | null>(null);

	// ── 🪙 quarter-up: challenge THIS player (signed-in, not your own profile, a real 17-digit id) ──
	const canChallenge = $derived(
		auth.authed && !!auth.steamid && auth.steamid !== sid && found && /^\d{17}$/.test(sid)
	);
	let showChallenge = $state(false);

	async function toggleLobby() {
		if (ownerBusy) return;
		ownerBusy = true;
		ownerMsg = null;
		const res = await auth.post('/skinsync/lobby_visibility', { public: !lobbyPublic });
		ownerBusy = false;
		if (res.ok) await store.load(sid); // refetch so the toggle + lobby record reflect the new state
		else ownerMsg = res.error ?? 'Could not update visibility.';
	}

	// ── rivalries + form (any profile, read-only) ──────────────────────────────────────────────────
	const sd = $derived(stats.data);
	const statsFound = $derived(!!sd && sd.found);
	const nemesis = $derived(statsFound ? (sd?.nemesis ?? null) : null);
	const victim = $derived(statsFound ? (sd?.victim ?? null) : null);
	// server sends form NEWEST-first; reverse so the strip reads oldest → newest (latest on the right).
	const form = $derived(statsFound && Array.isArray(sd?.form) ? [...(sd?.form ?? [])].reverse() : []);
	const hasRivalries = $derived(!!nemesis || !!victim || form.length > 0);
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

	{#if canChallenge}
		<div class="challenge">
			{#if !showChallenge}
				<button type="button" class="ch-open" onclick={() => (showChallenge = true)}>
					🪙 Challenge {p.name || 'this player'} for quarters ▸
				</button>
			{:else}
				<div class="ch-hd">
					<span class="ch-title">🪙 Challenge {p.name || 'this player'}</span>
					<button type="button" class="ch-x" aria-label="Close" onclick={() => (showChallenge = false)}>×</button>
				</div>
				<QuarterUpForm opp={sid} oppName={p.name || 'them'} />
			{/if}
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

	<!-- Per-mode records (only what the player has played; ranked is the tiles above) -->
	{#if hasModeRecs}
		<div class="moderecs">
			{#if tGames}<span class="mrec ev">🏆 Tournament <b>{tRec?.wins ?? 0}–{tRec?.losses ?? 0}</b></span>{/if}
			{#if mGames}<span class="mrec mon">🪙 Money <b>{mRec?.wins ?? 0}–{mRec?.losses ?? 0}</b></span>{/if}
			{#if lGames}<span class="mrec lob">🎮 Lobby <b>{lRec?.wins ?? 0}–{lRec?.losses ?? 0}</b></span>{/if}
		</div>
	{/if}

	<!-- Owner controls (own profile only) -->
	{#if isOwner}
		<div class="owner">
			<div class="octl">
				<div class="olabel">
					<span class="otitle">Show my casual lobby record publicly</span>
					<span class="ohint">When off, only you can see your lobby W–L.</span>
				</div>
				<button
					type="button"
					class="toggle"
					class:on={lobbyPublic}
					role="switch"
					aria-checked={lobbyPublic}
					aria-label="Show my casual lobby record publicly"
					disabled={ownerBusy}
					onclick={toggleLobby}
				>
					<span class="knob" aria-hidden="true"></span>
				</button>
			</div>
			{#if ownerMsg}<div class="omsg">{ownerMsg}</div>{/if}
		</div>
	{/if}

	<!-- Rivalries + recent form -->
	{#if hasRivalries}
		<div class="rail sec-hd">Head-to-head</div>
		<div class="rivals">
			{#if nemesis}
				<a class="rival nem" href="{base}/u/{nemesis.opp_id}">
					<div class="rhd">
						<span class="rlabel">Most losses against</span>
						<span class="rtag">ranked · toughest matchup</span>
					</div>
					<div class="rbody">
						<Avatar url={nemesis.avatar} size={38} alt={nemesis.name ?? 'Opponent'} />
						<div class="rwho">
							<span class="rname"
								>{#if nemesis.cc}<span class="rf">{flagEmoji(nemesis.cc)}</span> {/if}{nemesis.name ||
									'Opponent'}</span
							>
							<span class="rrec">{nemesis.wins}<i>W</i> · {nemesis.losses}<i>L</i></span>
						</div>
					</div>
				</a>
			{/if}
			{#if victim}
				<a class="rival vic" href="{base}/u/{victim.opp_id}">
					<div class="rhd">
						<span class="rlabel">Most wins against</span>
						<span class="rtag">ranked · best matchup</span>
					</div>
					<div class="rbody">
						<Avatar url={victim.avatar} size={38} alt={victim.name ?? 'Opponent'} />
						<div class="rwho">
							<span class="rname"
								>{#if victim.cc}<span class="rf">{flagEmoji(victim.cc)}</span> {/if}{victim.name ||
									'Opponent'}</span
							>
							<span class="rrec">{victim.wins}<i>W</i> · {victim.losses}<i>L</i></span>
						</div>
					</div>
				</a>
			{/if}
		</div>
		{#if form.length}
			<div class="form" aria-label="Recent form, oldest to newest">
				<span class="frail">Form</span>
				<div class="pips">
					{#each form as w, i (i)}
						<span class="pip" class:win={w === 1} class:loss={w !== 1} title={w === 1 ? 'Win' : 'Loss'}
						></span>
					{/each}
				</div>
			</div>
		{/if}
	{/if}

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

	/* ── 🪙 challenge this player ── */
	.challenge {
		margin: 0 0 12px;
		padding: 12px 14px;
		border: 1px solid color-mix(in srgb, var(--gold) 26%, var(--line));
		border-radius: 12px;
		background: linear-gradient(120deg, var(--gold-soft), transparent 72%), var(--panel);
	}
	.ch-open {
		font: inherit;
		font-size: 13px;
		font-weight: 800;
		color: var(--gold);
		background: transparent;
		border: none;
		padding: 0;
		cursor: pointer;
		text-align: left;
		min-height: 24px;
	}
	.ch-open:hover {
		filter: brightness(1.1);
	}
	.ch-hd {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		margin-bottom: 10px;
	}
	.ch-title {
		font-size: 13.5px;
		font-weight: 800;
		color: var(--ink);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.ch-x {
		font: inherit;
		font-size: 18px;
		line-height: 1;
		color: var(--faint);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 8px;
		width: 32px;
		height: 32px;
		flex: none;
		cursor: pointer;
	}
	.ch-x:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
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

	.moderecs {
		display: flex;
		flex-wrap: wrap;
		gap: 8px;
		margin: 12px 0 2px;
	}
	.mrec {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		padding: 6px 11px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--panel);
	}
	.mrec b {
		font-variant-numeric: tabular-nums;
		color: var(--ink);
	}
	.mrec.ev {
		border-color: color-mix(in srgb, var(--stream) 35%, var(--line));
	}
	.mrec.mon {
		border-color: color-mix(in srgb, var(--good) 35%, var(--line));
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

	/* ── owner controls ── */
	.owner {
		margin: 14px 0 2px;
		padding: 12px 14px;
		border: 1px solid color-mix(in srgb, var(--gold) 26%, var(--line));
		border-radius: 12px;
		background: var(--gold-soft);
	}
	.octl {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.olabel {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.otitle {
		font-size: 13px;
		font-weight: 800;
		color: var(--ink);
	}
	.ohint {
		font-size: 11px;
		color: var(--dim);
	}
	.toggle {
		flex: none;
		position: relative;
		width: 52px;
		height: 30px;
		min-height: 40px; /* touch target — the visible track stays 30px, the hit area is taller */
		padding: 0;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--panel-2);
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s;
	}
	.toggle .knob {
		position: absolute;
		top: 50%;
		left: 4px;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--faint);
		transform: translate(0, -50%);
		transition: transform 0.15s, background 0.15s;
	}
	.toggle.on {
		background: color-mix(in srgb, var(--good) 40%, transparent);
		border-color: color-mix(in srgb, var(--good) 55%, var(--line));
	}
	.toggle.on .knob {
		background: var(--good);
		transform: translate(22px, -50%);
	}
	.toggle:disabled {
		opacity: 0.55;
		cursor: default;
	}
	@media (prefers-reduced-motion: reduce) {
		.toggle,
		.toggle .knob {
			transition: none;
		}
	}
	.omsg {
		margin-top: 8px;
		font-size: 12px;
		font-weight: 600;
		color: var(--live);
	}

	/* ── rivalries ── */
	.rivals {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 8px;
	}
	@media (max-width: 480px) {
		.rivals {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.rival {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 11px 13px;
		border: 1px solid var(--line);
		border-left: 3px solid var(--line);
		border-radius: 12px;
		background: var(--panel);
		text-decoration: none;
		color: inherit;
		min-width: 0;
	}
	.rival.nem {
		border-left-color: var(--live);
	}
	.rival.vic {
		border-left-color: var(--good);
	}
	.rival:hover {
		border-color: var(--gold-soft);
	}
	.rhd {
		display: flex;
		align-items: baseline;
		gap: 8px;
		min-width: 0;
	}
	.rlabel {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		flex: none;
	}
	.nem .rlabel {
		color: var(--live);
	}
	.vic .rlabel {
		color: var(--good);
	}
	.rtag {
		font-size: 11px;
		color: var(--dim);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.rbody {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	.rwho {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}
	.rname {
		font-size: 13.5px;
		font-weight: 800;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.rname .rf {
		font-weight: 400;
	}
	.rival:hover .rname {
		color: var(--gold);
	}
	.rrec {
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
	}
	.rrec i {
		font-style: normal;
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.06em;
		color: var(--faint);
		margin-left: 1px;
	}

	/* ── recent form strip ── */
	.form {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 8px;
		padding: 9px 13px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--panel);
		overflow-x: auto;
		overscroll-behavior-x: contain;
	}
	.frail {
		flex: none;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.pips {
		display: flex;
		gap: 5px;
		min-width: 0;
	}
	.pip {
		width: 16px;
		height: 16px;
		border-radius: 4px;
		flex: none;
		background: var(--line);
	}
	.pip.win {
		background: #4ade80;
	}
	.pip.loss {
		background: #f87171;
	}
</style>
