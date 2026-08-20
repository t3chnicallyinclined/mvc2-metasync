<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { wallet } from '$lib/stores/wallet.svelte';
	import { pwa } from '$lib/stores/pwa.svelte';
	import { theme, type ThemeChoice } from '$lib/stores/theme.svelte';
	import { APP_VERSION, api } from '$lib/config';
	import Avatar from '$lib/components/Avatar.svelte';
	import RankBadge from '$lib/components/RankBadge.svelte';
	import { rankOf, gamesOf } from '$lib/ranks';
	import { flagEmoji, timeAgo } from '$lib/format';

	const me = $derived(auth.me);
	const gp = $derived(me ? gamesOf({ wins: me.wins, losses: me.losses }) : 0);
	const r = $derived(me ? rankOf(me.rating ?? 0, gp) : null);

	const THEMES: { id: ThemeChoice; label: string }[] = [
		{ id: 'dark', label: 'Dark' },
		{ id: 'light', label: 'Light' },
		{ id: 'auto', label: 'Auto' }
	];

	// ── Season Zero (light touch): policy v1 makes registering a functional no-op, so this is flavor,
	// not a CTA. Status from GET /season/status; join via the shared authed POST. ──
	interface SeasonStatus {
		registered?: boolean;
		since?: number;
		registered_count?: number;
		season?: string;
	}
	let season = $state<SeasonStatus | null>(null);
	let seasonBusy = $state(false);
	let seasonMsg = $state('');

	async function loadSeason(): Promise<void> {
		if (!auth.steamid) return;
		try {
			const res = await fetch(api(`/skinsync/season/status?steamid=${encodeURIComponent(auth.steamid)}`), {
				headers: { accept: 'application/json', ...auth.headers() }
			});
			if (res.ok) season = (await res.json()) as SeasonStatus;
		} catch {
			/* keep last-good; the line just stays quiet on a blip */
		}
	}

	async function joinSeason(): Promise<void> {
		seasonBusy = true;
		seasonMsg = '';
		const r = await auth.post('/skinsync/season/register', {});
		seasonBusy = false;
		if (r.ok) {
			seasonMsg = 'You’re in. See you on the ladder.';
			await loadSeason();
		} else {
			seasonMsg = r.error ?? 'Could not join right now.';
		}
	}

	// 🪙 wallet: the balance is loaded app-wide by WalletChip; make sure it's fresh when this page opens.
	onMount(() => {
		if (auth.steamid) {
			void wallet.load(auth.steamid);
			void loadSeason();
		}
	});
	const bal = $derived(wallet.balance);
	const recent = $derived(wallet.recent.slice(0, 6));
	// Human labels for the ledger flow codes (1 genesis … 9 match-refund).
	const LEDGER_LABEL: Record<string, string> = {
		genesis: 'Starting quarters',
		entry: 'Tournament entry',
		refund: 'Tournament refund',
		payout: 'Tournament payout',
		grant: 'Grant',
		'match-stake': 'Match stake',
		'match-settle': 'Match won',
		'match-fee': 'House fee',
		'match-refund': 'Match refund'
	};
	const ledgerLabel = (kind?: string) => LEDGER_LABEL[kind ?? ''] ?? (kind || 'Adjustment');
</script>

<svelte:head><title>Settings · MetaSync</title></svelte:head>

<section class="mast">
	<h1 class="mtitle">SETTINGS</h1>
	<div class="seam" aria-hidden="true"></div>
</section>

<!-- Account -->
<div class="rail sec-hd">Account</div>
<div class="card">
	{#if auth.authed}
		<div class="acct">
			<a class="who" href="{base}/u/{auth.steamid}">
				<Avatar url={me?.avatar} size={44} alt={me?.name ?? 'You'} />
				<div class="whotext">
					<b class="nm">{#if me?.cc}{flagEmoji(me.cc)} {/if}{me?.name || 'You'}</b>
					{#if r}<span class="sub"><RankBadge rating={me?.rating ?? 0} games={gp} size={14} /> <span class="rk-{r.s}">{r.n}</span> · {me?.rating ?? '—'}</span>{/if}
				</div>
			</a>
			<button class="btn ghost" onclick={() => auth.logout()}>Sign out</button>
		</div>
	{:else}
		<div class="signed-out">
			<span>Sign in with Steam to pin your rank, join tournaments, and manage your profile.</span>
			<button class="btn steam" onclick={() => auth.login('/settings')}>Sign in through Steam</button>
		</div>
	{/if}
</div>

<!-- Wallet (🪙 quarters) — signed-in only -->
{#if auth.authed}
	<div class="rail sec-hd">Wallet</div>
	<div class="card">
		<div class="wallet-hd">
			<div class="wl">
				<span class="wlab">Quarters</span>
				<span class="wsub">Play money — everyone starts with 🪙 {wallet.genesis}. No purchase, no cash-out.</span>
			</div>
			<span class="wbal">🪙 {bal ?? '—'}</span>
		</div>
		{#if recent.length}
			<ul class="ledger">
				{#each recent as tx, i (tx.ts ?? i)}
					{@const d = tx.delta ?? 0}
					<li class="lrow">
						<span class="lk">{ledgerLabel(tx.kind)}</span>
						{#if tx.ts}<span class="lt">{timeAgo(tx.ts)}</span>{/if}
						<span class="ld" class:pos={d > 0} class:neg={d < 0}>{d > 0 ? '+' : d < 0 ? '−' : ''}🪙 {Math.abs(d || tx.amount || 0)}</span>
					</li>
				{/each}
			</ul>
		{:else}
			<div class="wempty">No quarter activity yet — put one up on the Match tab.</div>
		{/if}
	</div>

	<!-- Season Zero — deliberately subtle (policy v1: joining is just a flag, no reset, no side ladder) -->
	<div class="rail sec-hd">Season</div>
	<div class="card">
		<div class="row">
			<div class="rowlabel">
				<b>Season Zero <span class="soon">preseason</span></b>
				<span class="sub">
					{#if season?.registered}
						You’re in for Season Zero{#if season.registered_count}, with {season.registered_count} other{season.registered_count === 1 ? '' : 's'}{/if}. Nothing to do yet — your rank carries on as normal.
					{:else}
						A soft prologue while the season format is finalized. Joining is just a flag for now — no reset, no separate ladder.
					{/if}
				</span>
			</div>
			{#if season?.registered}
				<span class="pill good">JOINED</span>
			{:else}
				<button class="btn ghost" onclick={joinSeason} disabled={seasonBusy}>{seasonBusy ? 'Joining…' : 'Join Season Zero'}</button>
			{/if}
		</div>
		{#if seasonMsg}<div class="season-msg">{seasonMsg}</div>{/if}
	</div>
{/if}

<!-- Appearance -->
<div class="rail sec-hd">Appearance</div>
<div class="card">
	<div class="row">
		<div class="rowlabel"><b>Theme</b><span class="sub">Auto follows your device.</span></div>
		<div class="seg" role="group" aria-label="Theme">
			{#each THEMES as t (t.id)}
				<button class="segbtn" class:on={theme.choice === t.id} onclick={() => theme.set(t.id)} aria-pressed={theme.choice === t.id}>{t.label}</button>
			{/each}
		</div>
	</div>
</div>

<!-- Install -->
<div class="rail sec-hd">Install</div>
<div class="card">
	{#if pwa.standalone}
		<div class="row"><div class="rowlabel"><b>Installed</b><span class="sub">You’re running the app from your home screen. ✓</span></div></div>
	{:else if pwa.canInstall}
		<div class="row">
			<div class="rowlabel"><b>Add to your device</b><span class="sub">Full-screen, offline-ready, one tap from your home screen.</span></div>
			<button class="btn steam" onclick={() => pwa.promptInstall()}>Install</button>
		</div>
	{:else if pwa.isIOS}
		<div class="row"><div class="rowlabel"><b>Add to Home Screen</b><span class="sub">In Safari, tap the <b>Share</b> button, then <b>Add to Home Screen</b>.</span></div></div>
	{:else}
		<div class="row"><div class="rowlabel"><b>Install</b><span class="sub">Use your browser’s “Install app” / “Add to Home Screen” option.</span></div></div>
	{/if}
</div>

<!-- Desktop agent (placeholder for the tray agent) -->
<div class="rail sec-hd">Desktop companion</div>
<div class="card">
	<div class="row">
		<div class="rowlabel">
			<b>Skin agent <span class="soon">soon</span></b>
			<span class="sub">A tiny background app for your gaming PC — auto-reports your matches and applies your skins live. Coming in a future update.</span>
		</div>
		<span class="dot off" title="Not connected" aria-label="Not connected"></span>
	</div>
</div>

<!-- About -->
<div class="rail sec-hd">About</div>
<div class="card about">
	<span>MvC MetaSync — live ranks, tournaments &amp; stats for Marvel vs Capcom 2.</span>
	<span class="ver">v{APP_VERSION}</span>
</div>

<style>
	.mast {
		padding: 14px 4px 8px;
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
		margin-top: 8px;
		transform: skewX(-14deg);
		background: linear-gradient(90deg, var(--gold), transparent);
	}
	.sec-hd {
		display: block;
		margin: 18px 2px 8px;
	}
	.card {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		padding: 14px 16px;
	}
	.acct {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
	}
	.who {
		display: flex;
		align-items: center;
		gap: 12px;
		text-decoration: none;
		color: var(--ink);
		min-width: 0;
	}
	.whotext {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}
	.nm {
		font-size: 15px;
		font-weight: 800;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.sub {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		color: var(--dim);
		flex-wrap: wrap;
	}
	.signed-out {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		font-size: 13px;
		color: var(--dim);
	}

	/* ── wallet ── */
	.wallet-hd {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.wl {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}
	.wlab {
		font-size: 14px;
		font-weight: 800;
		color: var(--ink);
	}
	.wsub {
		font-size: 11.5px;
		color: var(--dim);
	}
	.wbal {
		flex: none;
		font-size: 20px;
		font-weight: 900;
		font-style: italic;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
	}
	.ledger {
		list-style: none;
		margin: 12px 0 0;
		padding: 10px 0 0;
		border-top: 1px solid color-mix(in srgb, var(--line) 60%, transparent);
	}
	.lrow {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 10px;
		padding: 6px 0;
		font-size: 12.5px;
	}
	.lk {
		font-weight: 700;
		color: var(--ink);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.lt {
		font-size: 11px;
		color: var(--faint);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.ld {
		font-weight: 800;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.ld.pos {
		color: var(--good);
	}
	.ld.neg {
		color: var(--live);
	}
	.wempty {
		margin-top: 10px;
		font-size: 12px;
		color: var(--dim);
	}
	.season-msg {
		margin-top: 10px;
		font-size: 12px;
		color: var(--dim);
	}
	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 14px;
	}
	.rowlabel {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}
	.rowlabel b {
		font-size: 14px;
	}
	.btn {
		font: inherit;
		font-weight: 800;
		font-size: 13px;
		border-radius: 10px;
		padding: 9px 15px;
		cursor: pointer;
		white-space: nowrap;
		flex: none;
		min-height: 40px;
	}
	.btn.steam {
		color: #dfe9f5;
		background: linear-gradient(180deg, #2a475e, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 35%, transparent);
	}
	.btn.steam:hover {
		border-color: #66c0f4;
		color: #fff;
	}
	.btn.ghost {
		color: var(--dim);
		background: transparent;
		border: 1px solid var(--line);
	}
	.btn.ghost:hover {
		color: var(--live);
		border-color: color-mix(in srgb, var(--live) 45%, transparent);
	}
	.seg {
		display: inline-flex;
		border: 1px solid var(--line);
		border-radius: 10px;
		overflow: hidden;
		flex: none;
	}
	.segbtn {
		font: inherit;
		font-size: 12.5px;
		font-weight: 700;
		color: var(--dim);
		background: transparent;
		border: none;
		padding: 9px 14px;
		cursor: pointer;
		min-height: 40px;
	}
	.segbtn + .segbtn {
		border-left: 1px solid var(--line);
	}
	.segbtn.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		color: var(--gold-ink);
	}
	.soon {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--gold);
		background: var(--gold-soft);
		border: 1px solid color-mix(in srgb, var(--gold) 34%, var(--line));
		border-radius: 5px;
		padding: 1px 5px;
		margin-left: 4px;
		vertical-align: middle;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		flex: none;
	}
	.dot.off {
		background: var(--faint);
	}
	.about {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		font-size: 12.5px;
		color: var(--dim);
	}
	.ver {
		font-variant-numeric: tabular-nums;
		color: var(--faint);
		font-weight: 700;
		flex: none;
	}
	@media (max-width: 460px) {
		.row {
			flex-wrap: wrap;
		}
	}
</style>
