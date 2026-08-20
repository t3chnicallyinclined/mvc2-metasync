<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { api } from '$lib/config';
	import StatTile from '$lib/components/StatTile.svelte';
	import { timeAgo } from '$lib/format';

	// ── Site-admin dashboard ─────────────────────────────────────────────────────────────────────────
	// Hidden operator view: surfaces the telemetry the server already exposes on GET /admin/stats and
	// GET /admin/versions. Admin-gated BOTH ways — the client only fetches when the signed-in user's OWN
	// /profile carried admin:true (auth.me.admin), and the server independently 403s a non-allowlisted
	// bearer. Never reachable from the public bottom nav; entered from Settings only. Types are declared
	// locally (types.ts is off-limits) and mirror the live payloads.

	// gate: admin flows from the owner-view /profile (auth.me), loaded with the bearer on boot.
	const isAdmin = $derived(auth.me?.admin === true);

	interface AdminStats {
		ok?: boolean;
		installs?: number;
		registrations?: number;
		active_tokens?: number;
		online_now?: number;
		online_players?: string[];
		total_matches?: number;
		total_players?: number;
		active_players_24h?: number;
		active_players_7d?: number;
		uptime_ms?: number;
	}
	interface FleetUser {
		steamid: string;
		name?: string;
		ver?: string;
		platform?: string;
		client?: string;
		last_seen?: number;
		source?: string; // "live" (heartbeat, reliable) | "last-match" (approximate fallback)
	}
	interface AdminVersions {
		ok?: boolean;
		active?: number;
		reliable_live?: number;
		approx_last_match?: number;
		by_version?: Record<string, number>;
		by_platform?: Record<string, number>;
		users?: FleetUser[];
	}

	let stats = $state<AdminStats | null>(null);
	let fleet = $state<AdminVersions | null>(null);
	let loading = $state(false);
	let forbidden = $state(false); // server said 403 despite the client gate → treat as not authorized
	let err = $state<string | null>(null);
	let showOnline = $state(false);

	// fleet filters — the "who's on old builds / nudge list" controls.
	let minVer = $state('');
	let staleDays = $state(30);

	async function loadStats(): Promise<void> {
		if (!auth.me?.admin) return; // never hit the admin endpoint for a non-admin
		try {
			const res = await fetch(api('/skinsync/admin/stats'), {
				headers: { accept: 'application/json', ...auth.headers() }
			});
			if (res.status === 403) {
				forbidden = true;
				return;
			}
			if (!res.ok) throw new Error(`stats ${res.status}`);
			stats = (await res.json()) as AdminStats;
			forbidden = false;
			err = null;
		} catch (e) {
			// keep-last-good: don't blank tiles that are already showing on a transient blip
			err = e instanceof Error ? e.message : 'error';
		}
	}

	async function loadFleet(): Promise<void> {
		if (!auth.me?.admin) return;
		try {
			const qs = new URLSearchParams();
			qs.set('stale_days', String(staleDays || 30));
			const mv = minVer.trim();
			if (mv) qs.set('min', mv);
			const res = await fetch(api(`/skinsync/admin/versions?${qs.toString()}`), {
				headers: { accept: 'application/json', ...auth.headers() }
			});
			if (res.status === 403) {
				forbidden = true;
				return;
			}
			if (!res.ok) throw new Error(`versions ${res.status}`);
			fleet = (await res.json()) as AdminVersions;
			forbidden = false;
			err = null;
		} catch (e) {
			err = e instanceof Error ? e.message : 'error'; // keep-last-good
		}
	}

	async function refresh(): Promise<void> {
		if (!isAdmin || loading) return;
		loading = true;
		err = null;
		await Promise.all([loadStats(), loadFleet()]);
		loading = false;
	}

	// Apply the fleet filters (min-version / stale-days) — refetches only the versions endpoint.
	async function applyFilter(): Promise<void> {
		if (!isAdmin || loading) return;
		loading = true;
		await loadFleet();
		loading = false;
	}

	// If the boot-time profile load missed (network blip), retry so the gate can resolve.
	onMount(() => {
		if (auth.authed && !auth.me) void auth.loadMe();
	});

	// Fetch once the admin flag resolves true (auth.me loads async after boot). Guard so it runs once.
	let started = false;
	$effect(() => {
		if (isAdmin && !started) {
			started = true;
			void refresh();
		}
	});

	function uptimeLabel(ms?: number): string {
		const t = Number(ms);
		if (!t || !isFinite(t) || t <= 0) return '—';
		const s = Math.floor(t / 1000);
		const d = Math.floor(s / 86400);
		const h = Math.floor((s % 86400) / 3600);
		const m = Math.floor((s % 3600) / 60);
		if (d > 0) return `${d}d ${h}h`;
		if (h > 0) return `${h}h ${m}m`;
		if (m > 0) return `${m}m`;
		return `${s}s`;
	}

	// version distribution, sorted high→low count; platforms likewise.
	const verRows = $derived(Object.entries(fleet?.by_version ?? {}).sort((a, b) => b[1] - a[1]));
	const verMax = $derived(verRows.reduce((mx, [, n]) => Math.max(mx, n), 0));
	const platRows = $derived(Object.entries(fleet?.by_platform ?? {}).sort((a, b) => b[1] - a[1]));
	const users = $derived(fleet?.users ?? []);
	const online = $derived(stats?.online_players ?? []);
</script>

<svelte:head><title>Admin · MetaSync</title></svelte:head>

<section class="mast">
	<div class="mrow">
		<h1 class="mtitle">ADMIN</h1>
		{#if isAdmin && !forbidden}
			<button class="refresh" onclick={refresh} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button>
		{/if}
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">Operator telemetry — live fleet, installs, and who’s on old builds.</p>
</section>

{#if !auth.authed}
	<div class="empty gate">
		<span>Sign in with Steam to access the admin dashboard.</span>
		<button class="btn steam" onclick={() => auth.login('/admin')}>Sign in through Steam</button>
	</div>
{:else if !auth.me}
	<div class="empty">Checking access…</div>
{:else if !isAdmin || forbidden}
	<div class="empty">Not authorized — this area is for site administrators.</div>
{:else}
	<!-- ── Overview ── -->
	<div class="rail sec-hd">Overview</div>
	<div class="tiles">
		<StatTile label="Online now" value={stats?.online_now ?? 0} accent="var(--good)" hint="Players heartbeating right now" />
		<StatTile label="Installs" value={stats?.installs ?? 0} accent="var(--gold)" />
		<StatTile label="Active · 24h" value={stats?.active_players_24h ?? 0} accent="var(--ink)" />
		<StatTile label="Active · 7d" value={stats?.active_players_7d ?? 0} accent="var(--ink)" />
		<StatTile label="Total matches" value={stats?.total_matches ?? 0} accent="var(--ink)" />
		<StatTile label="Total players" value={stats?.total_players ?? 0} accent="var(--ink)" />
		<StatTile label="Active tokens" value={stats?.active_tokens ?? 0} accent="var(--stream)" hint="Signed-in sessions with a live bearer" />
		<StatTile label="Uptime" value={uptimeLabel(stats?.uptime_ms)} accent="var(--dim)" hint="Server process uptime" />
	</div>

	{#if online.length}
		<button class="online-toggle" onclick={() => (showOnline = !showOnline)} aria-expanded={showOnline}>
			{showOnline ? '▾' : '▸'} Who’s online ({online.length})
		</button>
		{#if showOnline}
			<div class="online-list">
				{#each online as nm, i (i)}
					<span class="onchip">{nm}</span>
				{/each}
			</div>
		{/if}
	{/if}

	<!-- ── Fleet / versions ── -->
	<div class="rail sec-hd">Fleet</div>

	<!-- Trust line: which count is reliable (live heartbeat) vs the last-match fallback approximation. -->
	<div class="trust">
		<div class="tnum">
			<b>{fleet?.reliable_live ?? 0}</b>
			<span>reporting live</span>
		</div>
		<span class="tsep">/</span>
		<div class="tnum approx">
			<b>{fleet?.approx_last_match ?? 0}</b>
			<span>seen last match <i>(fallback)</i></span>
		</div>
		{#if fleet?.active != null}
			<span class="tactive">· {fleet.active} active total</span>
		{/if}
	</div>

	<!-- filters: min-version + stale-days → the "nudge the old builds" controls -->
	<div class="filters">
		<label class="fld">
			<span class="flab">Min version</span>
			<input class="fin" type="text" inputmode="decimal" placeholder="e.g. 0.3.0" bind:value={minVer} aria-label="Minimum version" />
		</label>
		<label class="fld">
			<span class="flab">Stale after (days)</span>
			<input class="fin sm" type="number" min="1" bind:value={staleDays} aria-label="Stale after days" />
		</label>
		<button class="btn ghost apply" onclick={applyFilter} disabled={loading}>{loading ? 'Applying…' : 'Apply'}</button>
	</div>

	<div class="fleetgrid">
		<!-- version distribution -->
		<div class="card dist">
			<div class="rail dhd">By version</div>
			{#if verRows.length}
				{#each verRows as [ver, n] (ver)}
					<div class="drow">
						<span class="dk">{ver || '—'}</span>
						<span class="dbar"><span class="dfill" style="width:{verMax ? Math.max(4, Math.round((n / verMax) * 100)) : 0}%"></span></span>
						<span class="dn">{n}</span>
					</div>
				{/each}
			{:else}
				<div class="dempty">No version data.</div>
			{/if}
		</div>

		<!-- platform distribution -->
		<div class="card dist">
			<div class="rail dhd">By platform</div>
			{#if platRows.length}
				<div class="plats">
					{#each platRows as [plat, n] (plat)}
						<span class="platchip">{plat || 'unknown'} <b>{n}</b></span>
					{/each}
				</div>
			{:else}
				<div class="dempty">No platform data.</div>
			{/if}
		</div>
	</div>

	<!-- user table — scrolls inside its own container, never the page -->
	<div class="rail sec-hd">Users ({users.length})</div>
	{#if users.length}
		<div class="tablewrap">
			<table class="utbl">
				<thead>
					<tr>
						<th class="c-name">Player</th>
						<th>Version</th>
						<th>Platform</th>
						<th>Client</th>
						<th>Source</th>
						<th class="c-seen">Last seen</th>
					</tr>
				</thead>
				<tbody>
					{#each users as u (u.steamid)}
						<tr>
							<td class="c-name"><a href="{base}/u/{u.steamid}" class="ulink">{u.name || u.steamid}</a></td>
							<td class="mono">{u.ver || '—'}</td>
							<td>{u.platform || '—'}</td>
							<td>{u.client || '—'}</td>
							<td>
								<span class="src" class:live={u.source === 'live'} class:approx={u.source !== 'live'}>
									{u.source === 'live' ? 'live' : 'last-match'}
								</span>
							</td>
							<td class="c-seen">{timeAgo(u.last_seen) || '—'}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="empty">No users match this filter.</div>
	{/if}

	{#if err && (stats || fleet)}
		<p class="foot">Live data — last refresh hit a snag ({err}). Showing the last good read.</p>
	{/if}
{/if}

<style>
	.mast {
		padding: 14px 4px 8px;
	}
	.mrow {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
	}
	.mtitle {
		font-size: clamp(20px, 5.5vw, 27px);
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.01em;
	}
	.refresh {
		font: inherit;
		font-size: 12px;
		font-weight: 800;
		color: var(--dim);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 7px 14px;
		cursor: pointer;
		white-space: nowrap;
		flex: none;
		min-height: 36px;
	}
	.refresh:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.refresh:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.seam {
		height: 3px;
		width: 120px;
		margin: 8px 0 9px;
		transform: skewX(-14deg);
		background: linear-gradient(90deg, var(--gold), transparent);
	}
	.mdesc {
		margin: 0;
		max-width: 720px;
		color: var(--dim);
		font-size: 12.5px;
		line-height: 1.5;
	}
	.sec-hd {
		display: block;
		margin: 18px 2px 8px;
	}

	.gate {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 12px;
		flex-wrap: wrap;
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
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.btn.ghost:disabled {
		opacity: 0.55;
		cursor: default;
	}

	/* ── overview tiles ── */
	.tiles {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 8px;
	}
	@media (max-width: 560px) {
		.tiles {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	.online-toggle {
		margin-top: 10px;
		font: inherit;
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		background: transparent;
		border: none;
		padding: 4px 2px;
		cursor: pointer;
		min-height: 32px;
	}
	.online-toggle:hover {
		color: var(--good);
	}
	.online-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 4px;
	}
	.onchip {
		font-size: 12px;
		font-weight: 700;
		color: var(--ink);
		background: color-mix(in srgb, var(--good) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--good) 34%, var(--line));
		border-radius: 999px;
		padding: 4px 10px;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	/* ── fleet trust line ── */
	.trust {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 8px 10px;
		padding: 11px 14px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--panel);
		font-size: 12.5px;
		color: var(--dim);
	}
	.tnum {
		display: inline-flex;
		align-items: baseline;
		gap: 6px;
		min-width: 0;
	}
	.tnum b {
		font-size: 20px;
		font-weight: 900;
		font-style: italic;
		color: var(--good);
		font-variant-numeric: tabular-nums;
	}
	.tnum.approx b {
		color: var(--dim);
		font-style: normal;
	}
	.tnum i {
		font-style: normal;
		color: var(--faint);
	}
	.tsep {
		color: var(--faint);
	}
	.tactive {
		color: var(--faint);
		font-size: 11.5px;
	}

	/* ── filters ── */
	.filters {
		display: flex;
		align-items: flex-end;
		flex-wrap: wrap;
		gap: 10px;
		margin: 12px 0;
	}
	.fld {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.flab {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.fin {
		font: inherit;
		/* 16px baseline on mobile (app.css) prevents iOS focus-zoom; keep it explicit here too. */
		font-size: 16px;
		color: var(--ink);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 9px;
		padding: 8px 12px;
		width: 160px;
		max-width: 60vw;
	}
	.fin.sm {
		width: 120px;
	}
	.fin::placeholder {
		color: var(--faint);
	}
	.apply {
		min-height: 40px;
	}

	/* ── distributions ── */
	.card {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		padding: 14px 16px;
	}
	.fleetgrid {
		display: grid;
		grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
		gap: 10px;
	}
	@media (max-width: 640px) {
		.fleetgrid {
			grid-template-columns: minmax(0, 1fr);
		}
	}
	.dhd {
		display: block;
		margin-bottom: 10px;
	}
	.drow {
		display: grid;
		grid-template-columns: minmax(56px, 88px) minmax(0, 1fr) auto;
		align-items: center;
		gap: 10px;
		padding: 4px 0;
	}
	.dk {
		font-size: 12px;
		font-weight: 700;
		color: var(--ink);
		font-variant-numeric: tabular-nums;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.dbar {
		display: block;
		height: 9px;
		border-radius: 999px;
		background: var(--panel-2);
		border: 1px solid var(--line-soft);
		overflow: hidden;
		min-width: 0;
	}
	.dfill {
		display: block;
		height: 100%;
		border-radius: 999px;
		background: linear-gradient(90deg, var(--gold), color-mix(in srgb, var(--gold) 55%, transparent));
	}
	.dn {
		font-size: 12px;
		font-weight: 800;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
		min-width: 20px;
		text-align: right;
	}
	.dempty {
		font-size: 12px;
		color: var(--faint);
	}
	.plats {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.platchip {
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 999px;
		padding: 5px 11px;
	}
	.platchip b {
		color: var(--ink);
		font-variant-numeric: tabular-nums;
		margin-left: 3px;
	}

	/* ── user table (scrolls inside its own container, never the page) ── */
	.tablewrap {
		overflow-x: auto;
		overscroll-behavior-x: contain;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--panel);
	}
	.utbl {
		width: 100%;
		border-collapse: collapse;
		font-size: 12.5px;
		min-width: 560px; /* below this it scrolls within .tablewrap rather than the page */
	}
	.utbl th,
	.utbl td {
		text-align: left;
		padding: 9px 12px;
		white-space: nowrap;
		border-bottom: 1px solid var(--line-soft);
	}
	.utbl thead th {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.utbl tbody tr:last-child td {
		border-bottom: none;
	}
	.utbl td {
		color: var(--dim);
	}
	.c-name {
		max-width: 180px;
	}
	.ulink {
		display: inline-block;
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		vertical-align: bottom;
		font-weight: 800;
		color: var(--ink);
		text-decoration: none;
	}
	.ulink:hover {
		color: var(--gold);
	}
	.c-seen {
		font-variant-numeric: tabular-nums;
	}
	.src {
		display: inline-block;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		padding: 2px 7px;
		border-radius: 6px;
		border: 1px solid var(--line);
		color: var(--faint);
	}
	.src.live {
		color: var(--good);
		background: color-mix(in srgb, var(--good) 12%, transparent);
		border-color: color-mix(in srgb, var(--good) 34%, var(--line));
	}
	.src.approx {
		color: var(--faint);
		background: transparent;
	}

	.foot {
		padding: 10px 4px 0;
		font-size: 11.5px;
		color: var(--faint);
	}
</style>
