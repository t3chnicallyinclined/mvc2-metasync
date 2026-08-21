<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/config';
	import { flagEmoji } from '$lib/format';
	import { rankOf } from '$lib/ranks';
	import Avatar from './Avatar.svelte';
	import RankBadge from './RankBadge.svelte';
	import type { Region } from '$lib/stores/regions.svelte';

	// Region drill-in: the players who rep a city + their stats. Opened from a RegionRow. Fetches the standard
	// leaderboard filtered to this region (?country=<cc>&city=<name>) — same rows as /ranks, so the rank badge
	// is client-derived from rating exactly like everywhere else.
	let { region, onClose }: { region: Region; onClose: () => void } = $props();

	interface PlayerRow {
		steamid: string;
		name?: string;
		rating?: number;
		wins?: number;
		losses?: number;
		cc?: string;
		avatar?: string;
	}

	let loading = $state(false);
	let error = $state<string | null>(null);
	let players = $state<PlayerRow[]>([]);

	const is17 = (s: string) => /^\d{17}$/.test(s);
	const sub = $derived([region.region, region.country].filter(Boolean).join(' · '));

	onMount(() => {
		const prev = document.activeElement as HTMLElement | null;
		const prevOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		void tick().then(() => closeBtn?.focus());
		void load();
		return () => {
			document.body.style.overflow = prevOverflow;
			prev?.focus?.();
		};
	});

	async function load() {
		loading = true;
		error = null;
		const qs = new URLSearchParams({ tab: 'wins', limit: '50' });
		if (region.cc) qs.set('country', region.cc);
		if (region.name) qs.set('city', region.name);
		try {
			const res = await fetch(api(`/skinsync/leaderboard?${qs}`), { headers: { accept: 'application/json' } });
			if (!res.ok) throw new Error(`region ${res.status}`);
			const j = (await res.json()) as { players?: PlayerRow[] };
			players = Array.isArray(j.players) ? j.players : [];
		} catch (e) {
			error = e instanceof Error ? e.message : 'error';
		} finally {
			loading = false;
		}
	}

	const games = (p: PlayerRow) => (p.wins ?? 0) + (p.losses ?? 0);

	let dlg = $state<HTMLDivElement | null>(null);
	let closeBtn = $state<HTMLButtonElement | null>(null);
	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onClose();
		}
	}
</script>

<div
	class="ovl"
	role="presentation"
	onclick={(e) => {
		if (e.target === e.currentTarget) onClose();
	}}
	onkeydown={onKeydown}
>
	<div class="dlg" bind:this={dlg} role="dialog" aria-modal="true" aria-label="{region.name} players" tabindex="-1">
		<header class="dhd">
			<div class="dhd-l">
				<span class="flag">{flagEmoji(region.cc)}</span>
				<div class="ttl">
					<b>{region.name}</b>
					{#if sub}<span class="sub">{sub}</span>{/if}
				</div>
			</div>
			<button class="x" bind:this={closeBtn} onclick={onClose} aria-label="Close">✕</button>
		</header>

		<div class="summary">
			<span class="s"><b>{region.players ?? players.length}</b><i>players</i></span>
			<span class="s"><b>{region.wins ?? 0}<span class="d">–</span>{region.losses ?? 0}</b><i>W–L</i></span>
			<span class="s"><b>{region.avg_rating ?? 0}</b><i>avg elo</i></span>
		</div>

		{#if loading}
			<div class="body"><div class="empty">LOADING…</div></div>
		{:else if error}
			<div class="body"><div class="empty">{error}</div></div>
		{:else if players.length === 0}
			<div class="body"><div class="empty">No ranked players from {region.name} yet.</div></div>
		{:else}
			<ol class="list">
				{#each players as p, i (p.steamid || i)}
					{@const g = games(p)}
					{@const tier = rankOf(p.rating ?? 0, g || null)}
					<li class="row">
						<span class="pos">{i + 1}</span>
						<Avatar url={p.avatar} size={30} alt={p.name ?? 'Player'} />
						<span class="who">
							{#if is17(p.steamid)}
								<a class="pn" href="{base}/u/{p.steamid}">{#if p.cc}{flagEmoji(p.cc)} {/if}{p.name || 'Player'}</a>
							{:else}
								<span class="pn">{p.name || 'Player'}</span>
							{/if}
						</span>
						<span class="rk">
							<RankBadge rating={p.rating ?? 0} games={g || null} size={15} />
							<span class="rk-t rk-{tier.s}">{tier.n}</span>
						</span>
						<span class="rt">{p.rating ?? '—'}</span>
						<span class="wl"><b class="w">{p.wins ?? 0}</b><span class="d">–</span><b class="l">{p.losses ?? 0}</b></span>
					</li>
				{/each}
			</ol>
		{/if}
	</div>
</div>

<style>
	.ovl {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: max(16px, env(safe-area-inset-top)) 14px calc(16px + env(safe-area-inset-bottom));
		background: color-mix(in srgb, #05070c 72%, transparent);
		backdrop-filter: blur(3px);
	}
	.dlg {
		width: 100%;
		max-width: 520px;
		max-height: min(86vh, 860px);
		max-height: min(86dvh, 860px);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 16px;
		box-shadow: var(--shadow);
	}
	.dhd {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.dhd-l {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	.flag {
		font-size: 22px;
		flex: none;
	}
	.ttl {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}
	.ttl b {
		font-size: 16px;
		font-weight: 900;
		font-style: italic;
	}
	.ttl .sub {
		font-size: 11px;
		color: var(--dim);
	}
	.x {
		flex: none;
		width: 30px;
		height: 30px;
		border-radius: 8px;
		border: 1px solid var(--line);
		background: var(--panel-2);
		color: var(--dim);
		cursor: pointer;
	}
	.x:hover {
		color: var(--ink);
	}
	.summary {
		display: flex;
		gap: 22px;
		padding: 12px 16px;
		border-bottom: 1px solid var(--line-soft);
		background: linear-gradient(180deg, var(--panel-2), transparent);
	}
	.s {
		display: flex;
		flex-direction: column;
		line-height: 1.15;
	}
	.s b {
		font-size: 15px;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}
	.s .d {
		color: var(--faint);
		margin: 0 1px;
	}
	.s i {
		font-style: normal;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.body {
		padding: 22px 16px;
	}
	.empty {
		border: 1px dashed var(--line);
		border-radius: 12px;
		padding: 24px 16px;
		text-align: center;
		color: var(--dim);
		font-size: 12.5px;
	}
	.list {
		list-style: none;
		margin: 0;
		padding: 2px 0;
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.row {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 8px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.row:last-child {
		border-bottom: none;
	}
	.pos {
		flex: none;
		width: 20px;
		text-align: center;
		font-size: 12px;
		font-weight: 800;
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}
	.who {
		flex: 1 1 auto;
		min-width: 0;
	}
	.pn {
		font-weight: 700;
		font-size: 13.5px;
		color: var(--ink);
		text-decoration: none;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		display: block;
	}
	a.pn:hover {
		color: var(--gold);
	}
	.rk {
		display: flex;
		align-items: center;
		gap: 5px;
		flex: none;
	}
	.rk-t {
		font-size: 11.5px;
		font-weight: 800;
	}
	.rt {
		flex: none;
		width: 44px;
		text-align: right;
		font-size: 12.5px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		color: var(--dim);
	}
	.wl {
		flex: none;
		width: 58px;
		text-align: right;
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.wl .w {
		color: var(--good);
		font-weight: 800;
	}
	.wl .l {
		color: var(--loss);
		font-weight: 700;
	}
	.wl .d {
		color: var(--faint);
		margin: 0 2px;
	}
	/* tier colours (Marvel ladder) */
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

	@media (max-width: 480px) {
		.rk-t {
			display: none;
		}
		.rt {
			width: 40px;
		}
	}
</style>
