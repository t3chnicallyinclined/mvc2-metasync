<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { base } from '$app/paths';
	import { api } from '$lib/config';
	import { charName } from '$lib/chars';
	import { flagEmoji, timeAgo } from '$lib/format';
	import Avatar from './Avatar.svelte';

	// The SET modal — a game-by-game view of one match session. Opened with a session_id from a result OR
	// a Now Playing card. Fetches GET /skinsync/session?id=<id> and renders the two players + running set
	// score (counted across games) + a Game 1..N list in the SAME arena language as the result cards.
	// When `live` (the set belongs to an in-progress match), it SILENTLY re-polls the endpoint every few
	// seconds so new games appear as they finish — the 🔴 LIVE badge is on and driven. Types are local.
	let {
		sessionId,
		onClose,
		live = false // on when the open set belongs to a Now Playing pair → silent live polling below.
	}: { sessionId: string; onClose: () => void; live?: boolean } = $props();

	const LIVE_POLL_MS = 5000; // silent refresh cadence while a live set is open

	interface SessionGame {
		winner: string;
		loser: string;
		wname?: string;
		lname?: string;
		wteam?: number[];
		lteam?: number[];
		combo?: number;
		ocv?: boolean;
		perfect?: boolean;
		comeback?: boolean;
		ts?: number;
		match_index?: number;
	}
	interface SessionPlayer {
		steamid?: string;
		name?: string;
		avatar?: string;
		cc?: string;
	}
	interface SessionResp {
		ok?: boolean;
		session_id?: string;
		count?: number;
		games?: unknown[];
		players?: SessionPlayer[];
	}

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<SessionResp | null>(null);
	let reqId = 0;

	const is17 = (sid: string) => /^\d{17}$/.test(sid);
	const short = (sid: string) => (sid ? `…${sid.slice(-5)}` : 'Player');

	/** Coerce a raw team field into a clean char-id array (or undefined). */
	function team(x: unknown): number[] | undefined {
		if (!Array.isArray(x)) return undefined;
		const ids = x.map(Number).filter((n) => Number.isFinite(n));
		return ids.length ? ids : undefined;
	}
	/** Normalize one raw game row (server orders by match_index; we sort defensively too). */
	function toGame(x: unknown): SessionGame | null {
		const g = x as Record<string, unknown>;
		const winner = String(g?.winner ?? '');
		const loser = String(g?.loser ?? '');
		if (!winner || !loser) return null;
		const comboN = Number(g?.combo);
		return {
			winner,
			loser,
			wname: g?.wname ? String(g.wname) : undefined,
			lname: g?.lname ? String(g.lname) : undefined,
			wteam: team(g?.wteam),
			lteam: team(g?.lteam),
			combo: Number.isFinite(comboN) && comboN > 1 ? Math.round(comboN) : undefined,
			ocv: g?.ocv === true,
			perfect: g?.perfect === true,
			comeback: g?.comeback === true,
			ts: Number(g?.ts) || undefined,
			match_index: Number.isFinite(Number(g?.match_index)) ? Number(g.match_index) : undefined
		};
	}

	const games = $derived.by<SessionGame[]>(() => {
		const raw = Array.isArray(data?.games) ? data!.games : [];
		const list = raw.map(toGame).filter((g): g is SessionGame => g != null);
		return list
			.map((g, i) => ({ g, i }))
			.sort((a, b) => (a.g.match_index ?? a.i) - (b.g.match_index ?? b.i))
			.map((x) => x.g);
	});

	// The two set participants — anchored to game 1 (winner = A, loser = B) so A/B stay stable as sides
	// alternate across games.
	const pa = $derived(games[0]?.winner ?? '');
	const pb = $derived(games[0]?.loser ?? '');
	const aWins = $derived(games.filter((g) => g.winner === pa).length);
	const bWins = $derived(games.filter((g) => g.winner === pb).length);

	const byId = $derived.by(() => {
		const m = new Map<string, SessionPlayer>();
		for (const p of data?.players ?? []) if (p?.steamid) m.set(String(p.steamid), p);
		return m;
	});
	function nameOf(sid: string): string {
		const p = byId.get(sid);
		if (p?.name) return p.name;
		for (const g of games) {
			if (g.winner === sid && g.wname) return g.wname;
			if (g.loser === sid && g.lname) return g.lname;
		}
		return short(sid);
	}
	const avatarOf = (sid: string) => byId.get(sid)?.avatar;
	const ccOf = (sid: string) => byId.get(sid)?.cc;

	const inProgress = $derived(!!data && games.length <= 1);

	// Fetch the set. `silent` (a live re-poll) keeps the current view on screen — no spinner, no data
	// clear, and a transient failure keeps last-good rather than flashing an error over live content.
	async function fetchSession(silent: boolean): Promise<void> {
		const id = sessionId;
		if (!id) return;
		const myReq = ++reqId;
		if (!silent) {
			loading = true;
			error = null;
			data = null;
		}
		try {
			const res = await fetch(api(`/skinsync/session?id=${encodeURIComponent(id)}`), {
				headers: { accept: 'application/json' }
			});
			if (!res.ok) throw new Error(`session ${res.status}`);
			const j = (await res.json()) as SessionResp;
			if (myReq !== reqId) return;
			if (!j || j.ok === false) throw new Error('That set could not be found.');
			data = j;
			error = null;
		} catch (e: unknown) {
			if (myReq !== reqId) return;
			if (!silent) error = e instanceof Error ? e.message : 'error'; // silent poll: keep last-good
		} finally {
			if (myReq === reqId && !silent) loading = false;
		}
	}

	// ── full fetch on open (and whenever the id changes) ──
	$effect(() => {
		void sessionId; // track the id so a change re-fetches
		void fetchSession(false);
	});

	// ── live: silently re-poll while the set is in progress; cleaned up when it closes or live turns off ──
	$effect(() => {
		if (!live) return;
		const iv = setInterval(() => void fetchSession(true), LIVE_POLL_MS);
		return () => clearInterval(iv);
	});

	// ── focus management + body scroll lock (mount → move focus in, cleanup → restore) ──
	let dlg = $state<HTMLDivElement | null>(null);
	let closeBtn = $state<HTMLButtonElement | null>(null);
	onMount(() => {
		const prev = document.activeElement as HTMLElement | null;
		const prevOverflow = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		void tick().then(() => closeBtn?.focus());
		return () => {
			document.body.style.overflow = prevOverflow;
			prev?.focus?.();
		};
	});

	function focusables(): HTMLElement[] {
		if (!dlg) return [];
		return Array.from(
			dlg.querySelectorAll<HTMLElement>(
				'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
			)
		).filter((el) => el.offsetParent !== null);
	}
	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			onClose();
			return;
		}
		if (e.key !== 'Tab') return;
		const f = focusables();
		if (!f.length) return;
		const first = f[0];
		const last = f[f.length - 1];
		const act = document.activeElement as HTMLElement | null;
		if (e.shiftKey && act === first) {
			e.preventDefault();
			last.focus();
		} else if (!e.shiftKey && act === last) {
			e.preventDefault();
			first.focus();
		}
	}
</script>

<!-- backdrop closes only on a click landing on the overlay itself (not on the dialog within) -->
<div
	class="ovl"
	role="presentation"
	onclick={(e) => {
		if (e.target === e.currentTarget) onClose();
	}}
	onkeydown={onKeydown}
>
	<div
		class="dlg"
		bind:this={dlg}
		role="dialog"
		aria-modal="true"
		aria-label="Set details"
		tabindex="-1"
	>
		<header class="dhd">
			<div class="dhd-l">
				<span class="rail">Set</span>
				{#if live}
					<!-- in-progress set: the body silently re-polls so new games land as they finish -->
					<span class="pill live"><span class="dot" aria-hidden="true"></span>LIVE</span>
				{/if}
			</div>
			<button class="x" bind:this={closeBtn} onclick={onClose} aria-label="Close">✕</button>
		</header>

		{#if loading}
			<div class="dbody"><div class="empty">LOADING…</div></div>
		{:else if error}
			<div class="dbody"><div class="empty">{error}</div></div>
		{:else if data}
			<!-- scoreboard: player A [score] – [score] player B -->
			<div class="score">
				<div class="pl" class:lead={aWins > bWins}>
					<Avatar url={avatarOf(pa)} size={30} alt={nameOf(pa)} />
					<span class="who">
						{#if is17(pa)}<a class="pnm" href="{base}/u/{pa}">{#if ccOf(pa)}{flagEmoji(ccOf(pa))} {/if}{nameOf(pa)}</a>
						{:else}<span class="pnm">{nameOf(pa)}</span>{/if}
					</span>
					<b class="sc">{aWins}</b>
				</div>
				<span class="dash" aria-hidden="true">–</span>
				<div class="pl r" class:lead={bWins > aWins}>
					<b class="sc">{bWins}</b>
					<span class="who">
						{#if is17(pb)}<a class="pnm" href="{base}/u/{pb}">{nameOf(pb)}{#if ccOf(pb)} {flagEmoji(ccOf(pb))}{/if}</a>
						{:else}<span class="pnm">{nameOf(pb)}</span>{/if}
					</span>
					<Avatar url={avatarOf(pb)} size={30} alt={nameOf(pb)} />
				</div>
			</div>

			{#if games.length === 0}
				<div class="dbody"><div class="empty">No games recorded for this set yet.</div></div>
			{:else}
				<ol class="games">
					{#each games as g, i (i)}
						<li class="game">
							<span class="gno">Game {i + 1}</span>
							<div class="gmain">
								<div class="gside win">
									<span class="wtag" aria-hidden="true">W</span>
									<span class="gname">{g.wname || nameOf(g.winner)}</span>
									{#if g.wteam?.length}
										<span class="gteam">{#each g.wteam as id, k (k)}{#if k > 0}<span class="sep" aria-hidden="true">/</span>{/if}<span class="ch">{charName(id)}</span>{/each}</span>
									{/if}
								</div>
								<div class="gside lose">
									<span class="gdef" aria-hidden="true">def.</span>
									<span class="gname">{g.lname || nameOf(g.loser)}</span>
									{#if g.lteam?.length}
										<span class="gteam">{#each g.lteam as id, k (k)}{#if k > 0}<span class="sep" aria-hidden="true">/</span>{/if}<span class="ch">{charName(id)}</span>{/each}</span>
									{/if}
								</div>
								{#if g.ocv || g.perfect || g.comeback || g.combo}
									<div class="gtags">
										{#if g.ocv}<span class="chip ocv" title="One-Character Victory">OCV</span>{/if}
										{#if g.perfect}<span class="chip perf" title="Perfect">PERF</span>{/if}
										{#if g.comeback}<span class="chip cb" title="Comeback">CB</span>{/if}
										{#if g.combo}<span class="chip combo" title="Biggest combo">🎯 {g.combo}</span>{/if}
									</div>
								{/if}
							</div>
							{#if timeAgo(g.ts)}<span class="gago">{timeAgo(g.ts)}</span>{/if}
						</li>
					{/each}
				</ol>
				{#if inProgress}
					<p class="note">Set in progress — more games appear here as they finish.</p>
				{/if}
			{/if}
		{/if}
	</div>
</div>

<style>
	.ovl {
		position: fixed;
		inset: 0;
		z-index: 100; /* above the fixed TabBar (z-40) */
		display: flex;
		align-items: center;
		justify-content: center;
		padding: max(16px, env(safe-area-inset-top)) 14px calc(16px + env(safe-area-inset-bottom));
		background: color-mix(in srgb, #05070c 72%, transparent);
		backdrop-filter: blur(3px);
	}
	.dlg {
		position: relative;
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
	}
	.rail {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.pill.live {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		padding: 3px 8px;
		border-radius: 6px;
		color: var(--live);
		background: color-mix(in srgb, var(--live) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--live) 34%, var(--line));
	}
	.pill.live .dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--live);
	}
	@media (prefers-reduced-motion: no-preference) {
		.pill.live .dot {
			animation: mpulse 1.6s ease-in-out infinite;
		}
	}
	@keyframes mpulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.35; }
	}
	.x {
		flex: none;
		width: 30px;
		height: 30px;
		border-radius: 8px;
		border: 1px solid var(--line);
		background: var(--panel-2);
		color: var(--dim);
		font-size: 13px;
		cursor: pointer;
		transition: color 0.15s, border-color 0.15s;
	}
	.x:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.dbody {
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

	/* scoreboard — the two plates + the running set score */
	.score {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: 10px;
		padding: 16px 16px 14px;
		background: linear-gradient(180deg, var(--panel-2), transparent);
		border-bottom: 1px solid var(--line-soft);
	}
	.pl {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
	}
	.pl.r {
		flex-direction: row-reverse;
	}
	.who {
		min-width: 0;
		overflow: hidden;
	}
	.pnm {
		font-weight: 800;
		font-size: 14px;
		color: var(--ink);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		display: block;
	}
	a.pnm:hover {
		color: var(--gold);
	}
	.sc {
		flex: none;
		font-size: 26px;
		font-weight: 900;
		font-style: italic;
		font-variant-numeric: tabular-nums;
		color: var(--faint);
		line-height: 1;
	}
	.pl.lead .sc {
		color: var(--gold);
	}
	.pl.lead .pnm {
		color: var(--ink);
	}
	.dash {
		flex: none;
		font-size: 15px;
		font-weight: 800;
		color: var(--faint);
	}

	/* game list — same visual language as the result cards */
	.games {
		list-style: none;
		margin: 0;
		padding: 4px 0;
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.game {
		position: relative;
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 10px;
		align-items: start;
		padding: 11px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.game:last-child {
		border-bottom: none;
	}
	.gno {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--faint);
		padding-top: 2px;
		white-space: nowrap;
	}
	.gmain {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 4px;
	}
	.gside {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 6px;
		min-width: 0;
	}
	.wtag {
		align-self: center;
		font-size: 8.5px;
		font-weight: 900;
		line-height: 1;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-radius: 3px;
		padding: 2px 4px;
	}
	.gdef {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.gside.win .gname {
		font-weight: 800;
		font-size: 13px;
		color: var(--good);
	}
	.gside.lose .gname {
		font-weight: 600;
		font-size: 12.5px;
		color: var(--dim);
	}
	.gname {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}
	.gteam {
		font-size: 11px;
		font-weight: 700;
		color: var(--dim);
	}
	.gside.lose .gteam {
		color: var(--faint);
		font-weight: 600;
	}
	.gteam .sep {
		color: var(--faint);
		font-weight: 400;
		margin: 0 3px;
	}
	.gtags {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 5px;
		margin-top: 2px;
	}
	.chip {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.04em;
		border-radius: 5px;
		padding: 2px 6px;
		border: 1px solid var(--line);
		color: var(--dim);
		white-space: nowrap;
		font-variant-numeric: tabular-nums;
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
	.gago {
		position: absolute;
		top: 11px;
		right: 14px;
		font-size: 10px;
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}
	.note {
		margin: 0;
		padding: 10px 14px 14px;
		font-size: 11.5px;
		color: var(--faint);
		text-align: center;
	}
</style>
