<script lang="ts">
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { pwa } from '$lib/stores/pwa.svelte';
	import { theme, type ThemeChoice } from '$lib/stores/theme.svelte';
	import { APP_VERSION } from '$lib/config';
	import Avatar from '$lib/components/Avatar.svelte';
	import RankBadge from '$lib/components/RankBadge.svelte';
	import { rankOf, gamesOf } from '$lib/ranks';
	import { flagEmoji } from '$lib/format';

	const me = $derived(auth.me);
	const gp = $derived(me ? gamesOf({ wins: me.wins, losses: me.losses }) : 0);
	const r = $derived(me ? rankOf(me.rating ?? 0, gp) : null);

	const THEMES: { id: ThemeChoice; label: string }[] = [
		{ id: 'dark', label: 'Dark' },
		{ id: 'light', label: 'Light' },
		{ id: 'auto', label: 'Auto' }
	];
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
