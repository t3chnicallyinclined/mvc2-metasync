<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { TourneyStore } from '$lib/stores/tourney.svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import Avatar from '$lib/components/Avatar.svelte';
	import { flagEmoji, whenLabel } from '$lib/format';
	import { teamAbbr, CHAR_NAME } from '$lib/chars';
	import {
		statusMeta,
		formatLabel,
		ftLabel,
		entryCost,
		placeLabel,
		mdToSafeHtml,
		shortId,
		type BracketMatch,
		type Registration
	} from '$lib/tourney';

	const store = new TourneyStore();
	const id = $derived(page.params.id ?? '');

	// (Re)connect whenever the route param changes (first mount + client-side nav between tournaments).
	// `curId` is a plain local (not $state) so writing it never re-triggers this effect.
	let curId = '';
	$effect(() => {
		const i = id;
		if (i && i !== curId) {
			curId = i;
			store.connect(i);
		}
	});

	// Pause the live stream while backgrounded; refetch + reopen on return (CPU discipline).
	onMount(() => {
		const onVis = () => {
			if (document.hidden) store.disconnect();
			else store.connect(store.id);
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			store.disconnect();
		};
	});

	const doc = $derived(store.doc);
	const players = $derived(store.players);
	const cold = $derived(store.loading && !doc);

	const st = $derived(statusMeta(doc?.status));
	const place = $derived(placeLabel(doc));
	const ft = $derived(ftLabel(doc?.ft_winners, doc?.ft_losers, doc?.ft_grands));
	const cost = $derived(entryCost(doc?.entry_fee_cents, doc?.entry_coins));
	const stakeCoins = $derived(doc?.entry_coins ?? 0); // 🪙 QUARTERS stake to enter (0 = free)
	const when = $derived(whenLabel(doc?.starts_ms));
	const to = $derived(doc?.to_steamid ? players[doc.to_steamid] : undefined);

	// registrations — seeded first (asc), then by registration time.
	const regs = $derived(
		(doc?.registrations ?? []).slice().sort((a: Registration, b: Registration) => {
			const sa = a.seed ?? 0;
			const sb = b.seed ?? 0;
			if (sa && sb && sa !== sb) return sa - sb;
			if (sa && !sb) return -1;
			if (sb && !sa) return 1;
			return (a.registered_ms ?? 0) - (b.registered_ms ?? 0);
		})
	);
	const cap = $derived(doc?.cap ?? 0);

	// bracket — render defensively; every access guarded, unknown shapes degrade to a flat list.
	const br = $derived(doc?.bracket ?? null);
	const allMatches = $derived(Array.isArray(br?.matches) ? (br?.matches ?? []) : []);
	const champion = $derived(br?.champion ?? null);

	function group(type: string): { round: number; list: BracketMatch[] }[] {
		const inBr = allMatches.filter((m) => String(m?.bracket ?? '') === type);
		const rounds = new Map<number, BracketMatch[]>();
		for (const m of inBr) {
			const r = m.round ?? 0;
			const arr = rounds.get(r) ?? [];
			arr.push(m);
			rounds.set(r, arr);
		}
		return [...rounds.entries()]
			.sort((a, b) => a[0] - b[0])
			.map(([round, list]) => ({ round, list: list.slice().sort((a, b) => (a.id ?? 0) - (b.id ?? 0)) }));
	}

	const winners = $derived(group('winners'));
	const losers = $derived(group('losers'));
	const grands = $derived(group('grand'));
	// any match with an unrecognized bracket tag — shown as a flat fallback so nothing is dropped.
	const other = $derived(
		allMatches.filter((m) => !['winners', 'losers', 'grand'].includes(String(m?.bracket ?? '')))
	);

	function pname(sid?: string | null): string {
		if (!sid) return '';
		return players[sid]?.name || shortId(sid);
	}
	// visible states only (pending seats show their provenance instead of a chip).
	function stateChip(m: BracketMatch): { label: string; cls: string } | null {
		const s = String(m?.state ?? '').toLowerCase();
		if (s === 'live') return { label: 'LIVE', cls: 'live' };
		if (s === 'ready') return { label: 'READY', cls: 'ready' };
		if (s === 'done') return { label: m.score || 'DONE', cls: 'done' };
		if (s === 'bye') return { label: 'BYE', cls: 'muted' };
		return null;
	}

	const rulesHtml = $derived(mdToSafeHtml(doc?.rules_md));
	const title = $derived(doc?.name || 'Tournament');

	// ── signed-in actions (register / check-in / unregister) ────────────────────────────────────────
	// The acting steamid comes from the bearer TOKEN server-side; we only mirror the user's state here to
	// pick the right control. Windows: a 0 bound means "no bound" (mirrors tourney.rs register/checkin).
	const status = $derived((doc?.status ?? '').toLowerCase());
	function withinWindow(open?: number, close?: number): boolean {
		const now = Date.now();
		if (open && open > 0 && now < open) return false;
		if (close && close > 0 && now > close) return false;
		return true;
	}
	// registration is accepted while status is open|checkin AND inside the (optional) reg window.
	const regOpen = $derived(
		(status === 'open' || status === 'checkin') &&
			withinWindow(doc?.reg_open_ms, doc?.reg_close_ms)
	);
	// check-in is its own phase (status "checkin") within the (optional) check-in window.
	const checkinOpen = $derived(
		status === 'checkin' && withinWindow(doc?.checkin_open_ms, doc?.checkin_close_ms)
	);
	// the roster locks once the bracket is drawn (or the event is done/cancelled) — no self-drop after.
	const locked = $derived(status === 'running' || status === 'done' || status === 'cancelled');

	// the signed-in user's own registration row (active only — a dropped/DQ'd row counts as not-registered).
	const myReg = $derived(
		auth.authed && auth.steamid
			? (doc?.registrations ?? []).find((r) => r.steamid === auth.steamid)
			: undefined
	);
	const myDropped = $derived(myReg?.status === 'dropped' || myReg?.status === 'dq');
	const registered = $derived(!!myReg && !myDropped);
	const checkedIn = $derived(registered && (!!myReg?.checked_in || myReg?.status === 'checked_in'));

	// show the actions panel only when there's something to do/see for this viewer.
	const showActions = $derived(
		auth.authed ? registered || regOpen : regOpen || checkinOpen
	);

	// optional team picker — three char <select>s, '' = "any". Sorted by name for scannability.
	const charOptions = Object.entries(CHAR_NAME)
		.map(([id, name]) => ({ id: Number(id), name }))
		.sort((a, b) => a.name.localeCompare(b.name));
	let team = $state<[string, string, string]>(['', '', '']);

	let busy = $state(false);
	let notice = $state<{ kind: 'ok' | 'err'; text: string } | null>(null);

	async function doRegister() {
		if (busy) return;
		busy = true;
		notice = null;
		const picked = team.filter((v) => v !== '').map((v) => Number(v));
		const body: { id: string; team?: number[] } = { id };
		if (picked.length) body.team = picked;
		const res = await auth.post('/skinsync/tourney/register', body);
		busy = false;
		if (res.ok) {
			notice = { kind: 'ok', text: 'You’re registered!' };
			void store.load(id);
		} else {
			notice = { kind: 'err', text: res.error ?? 'Could not register.' };
		}
	}

	async function doCheckin() {
		if (busy) return;
		busy = true;
		notice = null;
		const res = await auth.post('/skinsync/tourney/checkin', { id });
		busy = false;
		if (res.ok) {
			notice = { kind: 'ok', text: 'Checked in — good luck!' };
			void store.load(id);
		} else {
			notice = { kind: 'err', text: res.error ?? 'Could not check in.' };
		}
	}

	async function doUnregister() {
		if (busy) return;
		busy = true;
		notice = null;
		const res = await auth.post('/skinsync/tourney/unregister', { id });
		busy = false;
		if (res.ok) {
			notice = { kind: 'ok', text: 'You’ve dropped from this event.' };
			team = ['', '', ''];
			void store.load(id);
		} else {
			notice = { kind: 'err', text: res.error ?? 'Could not unregister.' };
		}
	}
</script>

<svelte:head><title>{title} · MetaSync</title></svelte:head>

{#snippet seat(sid: string | null | undefined, from: string | undefined, bye: boolean | undefined, win: boolean)}
	<div class="seat" class:win>
		{#if sid}
			<a class="sname" href="{base}/u/{sid}">
				<Avatar url={players[sid]?.avatar} size={18} alt={pname(sid)} />
				<span class="st">{pname(sid)}</span>
			</a>
		{:else if bye}
			<span class="tbd">Bye</span>
		{:else}
			<span class="tbd">{from || 'TBD'}</span>
		{/if}
		{#if win}<span class="wtick" aria-hidden="true">✓</span>{/if}
	</div>
{/snippet}

{#snippet matchCard(m: BracketMatch)}
	{@const chip = stateChip(m)}
	<div class="mc" class:on={m.on_stream}>
		<div class="mc-hd">
			<span class="mid">#{(m.id ?? 0) + 1}</span>
			{#if chip}<span class="chip {chip.cls}">{chip.label}</span>{/if}
		</div>
		{@render seat(m.p1, m.p1_from, m.p1_bye, !!m.winner && m.winner === m.p1)}
		{@render seat(m.p2, m.p2_from, m.p2_bye, !!m.winner && m.winner === m.p2)}
	</div>
{/snippet}

{#snippet bracketCols(cols: { round: number; list: BracketMatch[] }[], label: string)}
	{#if cols.length}
		<div class="bwrap">
			<div class="brail">{label}</div>
			<div class="cols">
				{#each cols as col (col.round)}
					<div class="col">
						<div class="cround">Round {col.round}</div>
						{#each col.list as m (m.id)}
							{@render matchCard(m)}
						{/each}
					</div>
				{/each}
			</div>
		</div>
	{/if}
{/snippet}

{#if cold}
	<div class="empty">LOADING…</div>
{:else if store.notFound && !doc}
	<div class="empty">No tournament found for that link.</div>
{:else if !doc}
	<div class="empty">Couldn’t load this tournament — check your connection and try again.</div>
{:else}
	{#if store.gone}
		<div class="gone">This tournament was removed by the organizer.</div>
	{/if}

	<!-- Header -->
	<section class="hero" style="--acc:{st.cls === 'good' ? 'var(--good)' : st.cls === 'live' ? 'var(--live)' : 'var(--gold)'}">
		<div class="htop">
			<span class="pill {st.cls}">{st.label}</span>
			<span class="pill net" class:off={!doc.online}>{doc.online ? 'ONLINE' : 'OFFLINE'}</span>
		</div>
		<h1 class="hname">{doc.name || 'Untitled'}</h1>
		<div class="hmeta">
			<span class="fmt">{formatLabel(doc.format)}</span>
			{#if ft}<span class="sep">·</span><span class="ftl">{ft}</span>{/if}
		</div>
		<div class="hrow">
			{#if place || doc.online}
				<span class="hi"><span class="flag">{flagEmoji(doc.cc)}</span>{place || 'Online'}</span>
			{/if}
			{#if when}<span class="hi">🗓 {when}</span>{/if}
			<span class="hi cost" class:free={cost === 'Free'}>{cost}</span>
		</div>

		<div class="hbtm">
			<!-- Organizer -->
			{#if doc.to_steamid}
				<a class="to" href="{base}/u/{doc.to_steamid}" title="Organizer">
					<span class="rail">Organizer</span>
					<span class="tob">
						<Avatar url={to?.avatar} size={20} alt={to?.name ?? 'Organizer'} />
						<span class="ton">{to?.name || shortId(doc.to_steamid)}</span>
					</span>
				</a>
			{/if}
			<div class="links">
				{#if doc.stream_url}
					<a class="lnk stream" href={doc.stream_url} target="_blank" rel="noopener noreferrer">▶ Stream</a>
				{/if}
				{#if doc.discord_url}
					<a class="lnk" href={doc.discord_url} target="_blank" rel="noopener noreferrer">Discord</a>
				{/if}
			</div>
		</div>
	</section>

	<!-- Champion (once decided) -->
	{#if champion}
		<div class="champ">
			<span class="crown" aria-hidden="true">🏆</span>
			<span>Champion — <b>{pname(champion)}</b></span>
		</div>
	{/if}

	<!-- Sign-in / register / check-in actions -->
	{#if showActions}
		<div class="actions">
			{#if !auth.authed}
				<div class="signrow">
					<span class="prompt">Sign in with Steam to register for this event.</span>
					<button type="button" class="steam" onclick={() => auth.login()}>
						<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
							<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
							<circle cx="15" cy="9" r="2.4" fill="currentColor" />
							<path d="M6 15l4.5 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
						</svg>
						<span>Sign in with Steam</span>
					</button>
				</div>
			{:else if registered}
				<div class="status-line">
					{#if checkedIn}
						<span class="you good">✓ You’re checked in</span>
					{:else}
						<span class="you">You’re registered{regOpen ? '' : ' — check-in opens soon'}</span>
					{/if}
					{#if myReg?.team && myReg.team.length}
						<span class="you-team">{teamAbbr(myReg.team)}</span>
					{/if}
				</div>
				<div class="btnrow">
					{#if checkinOpen && !checkedIn}
						<button type="button" class="btn primary" disabled={busy} onclick={doCheckin}>
							{busy ? 'Checking in…' : 'Check in'}
						</button>
					{/if}
					{#if !locked}
						<button type="button" class="btn subtle" disabled={busy} onclick={doUnregister}>
							Unregister
						</button>
					{/if}
				</div>
			{:else if regOpen}
				<div class="reg">
					<div class="reg-hd">
						<span class="reg-title">Enter this tournament</span>
						<span class="reg-sub">Team is optional — leave as “Any” to decide later.</span>
					</div>
					{#if stakeCoins > 0}
						<div class="reg-stake">🪙 {stakeCoins} to enter — staked at register; the champion sweeps the pot.</div>
					{/if}
					<div class="picker">
						{#each [0, 1, 2] as slot (slot)}
							<label class="pk">
								<span class="pk-l">Char {slot + 1}</span>
								<select bind:value={team[slot]} disabled={busy} aria-label="Character {slot + 1}">
									<option value="">Any</option>
									{#each charOptions as c (c.id)}
										<option value={String(c.id)}>{c.name}</option>
									{/each}
								</select>
							</label>
						{/each}
					</div>
					<button type="button" class="btn primary wide" disabled={busy} onclick={doRegister}>
						{busy ? 'Registering…' : stakeCoins > 0 ? `Register · 🪙 ${stakeCoins}` : 'Register'}
					</button>
				</div>
			{/if}
			{#if notice}
				<div class="notice {notice.kind}" role="status">{notice.text}</div>
			{/if}
		</div>
	{/if}

	<!-- Registrations -->
	<div class="rail sec-hd">
		Players
		<span class="cnt">{regs.length}{cap ? ` / ${cap}` : ''}</span>
	</div>
	{#if regs.length}
		<div class="board plist">
			{#each regs as r (r.steamid)}
				{@const dropped = r.status === 'dropped' || r.status === 'dq'}
				<div class="pr" class:dropped>
					<span class="seed">{r.seed ? `#${r.seed}` : '–'}</span>
					<a class="pid" href="{base}/u/{r.steamid}">
						<Avatar url={players[r.steamid]?.avatar} size={26} alt={pname(r.steamid)} />
						<span class="pnm">
							{#if players[r.steamid]?.cc}<span class="pf">{flagEmoji(players[r.steamid]?.cc)}</span>{/if}
							{pname(r.steamid)}
						</span>
					</a>
					{#if r.team && r.team.length}<span class="team">{teamAbbr(r.team)}</span>{/if}
					{#if dropped}
						<span class="pill muted">{r.status === 'dq' ? 'DQ' : 'DROPPED'}</span>
					{:else if r.checked_in || r.status === 'checked_in'}
						<span class="pill good">CHECKED IN</span>
					{/if}
				</div>
			{/each}
		</div>
	{:else}
		<div class="empty">No players registered yet.</div>
	{/if}

	<!-- Bracket -->
	<div class="rail sec-hd">Bracket</div>
	{#if !br}
		<div class="empty">
			The bracket hasn’t started yet — {#if doc.status === 'open'}registration is open.{:else if doc.status === 'checkin'}check-in is open.{:else if doc.status === 'done'}this event is complete.{:else}it opens when the organizer starts the event.{/if}
		</div>
	{:else if allMatches.length === 0}
		<div class="empty">The bracket is set but has no matches to show yet.</div>
	{:else}
		<div class="bracket">
			{@render bracketCols(winners, 'Winners')}
			{@render bracketCols(losers, 'Losers')}
			{@render bracketCols(grands, 'Grand Finals')}
			{#if other.length}
				<div class="bwrap">
					<div class="brail">Matches</div>
					<div class="cols">
						<div class="col">
							{#each other as m (m.id)}
								{@render matchCard(m)}
							{/each}
						</div>
					</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Rules -->
	{#if rulesHtml}
		<details class="rules">
			<summary><span class="rail">Rules</span></summary>
			<!-- mdToSafeHtml escapes ALL doc text before emitting only its own whitelist tags (XSS-safe). -->
			<div class="rmd">{@html rulesHtml}</div>
		</details>
	{/if}
{/if}

<style>
	.gone {
		margin: 8px 0 12px;
		padding: 10px 14px;
		border: 1px solid color-mix(in srgb, var(--live) 40%, var(--line));
		background: color-mix(in srgb, var(--live) 10%, transparent);
		border-radius: 11px;
		font-size: 12.5px;
		font-weight: 700;
		color: var(--live);
	}

	/* ── header ── */
	.hero {
		margin: 10px 0 12px;
		padding: 15px 16px 14px;
		border: 1px solid var(--line);
		border-left: 4px solid var(--acc, var(--line));
		border-radius: 14px;
		background:
			linear-gradient(120deg, color-mix(in srgb, var(--acc, var(--line)) 13%, transparent), transparent 68%),
			linear-gradient(180deg, var(--panel-2), var(--panel));
		box-shadow: var(--shadow);
	}
	.htop {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
		margin-bottom: 8px;
	}
	.pill.net {
		color: var(--stream);
		background: color-mix(in srgb, var(--stream) 12%, transparent);
		border-color: color-mix(in srgb, var(--stream) 34%, var(--line));
	}
	.pill.net.off {
		color: var(--faint);
		background: transparent;
		border-color: var(--line);
	}
	.pill.muted {
		color: var(--faint);
	}
	.hname {
		font-size: clamp(20px, 6vw, 28px);
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.01em;
		line-height: 1.1;
		overflow-wrap: anywhere;
	}
	.hmeta {
		display: flex;
		align-items: center;
		gap: 7px;
		flex-wrap: wrap;
		margin-top: 5px;
		font-size: 12.5px;
		color: var(--dim);
	}
	.hmeta .fmt {
		font-weight: 800;
		color: var(--ink);
	}
	.hmeta .sep {
		color: var(--faint);
	}
	.hrow {
		display: flex;
		align-items: center;
		gap: 8px 14px;
		flex-wrap: wrap;
		margin-top: 9px;
	}
	.hi {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		font-size: 12px;
		color: var(--dim);
		min-width: 0;
	}
	.hi .flag {
		font-size: 14px;
	}
	.hi.cost {
		font-weight: 800;
		color: var(--gold);
	}
	.hi.cost.free {
		color: var(--good);
	}
	.hbtm {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 12px;
	}
	.to {
		display: flex;
		flex-direction: column;
		gap: 3px;
		text-decoration: none;
		color: inherit;
		min-width: 0;
	}
	.tob {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		min-width: 0;
	}
	.ton {
		font-weight: 800;
		font-size: 13px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.to:hover .ton {
		color: var(--gold);
	}
	.links {
		display: flex;
		gap: 7px;
		flex-wrap: wrap;
	}
	.lnk {
		display: inline-flex;
		align-items: center;
		padding: 6px 12px;
		border: 1px solid var(--line);
		border-radius: 9px;
		background: var(--panel-2);
		font-size: 12px;
		font-weight: 800;
		text-decoration: none;
		color: var(--ink);
	}
	.lnk.stream {
		color: var(--stream);
		border-color: color-mix(in srgb, var(--stream) 40%, var(--line));
		background: color-mix(in srgb, var(--stream) 10%, transparent);
	}
	.lnk:hover {
		border-color: var(--gold-soft);
	}

	.champ {
		display: flex;
		align-items: center;
		gap: 9px;
		margin: 0 0 12px;
		padding: 11px 14px;
		border: 1px solid color-mix(in srgb, var(--gold) 42%, var(--line));
		background: var(--gold-soft);
		border-radius: 11px;
		font-size: 13.5px;
		font-weight: 700;
	}
	.champ .crown {
		font-size: 16px;
	}

	/* ── actions (sign-in / register / check-in) ── */
	.actions {
		margin: 0 0 4px;
		padding: 14px;
		border: 1px solid color-mix(in srgb, var(--gold) 26%, var(--line));
		border-radius: 14px;
		background:
			linear-gradient(120deg, var(--gold-soft), transparent 70%),
			var(--panel);
	}
	.signrow {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
	}
	.prompt {
		font-size: 13px;
		font-weight: 700;
		color: var(--ink);
		min-width: 0;
	}
	.steam {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		font: inherit;
		font-size: 13.5px;
		font-weight: 800;
		color: #dfe9f5;
		background: linear-gradient(180deg, #2a475e, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 35%, transparent);
		border-radius: 10px;
		padding: 0 16px;
		min-height: 42px;
		cursor: pointer;
		white-space: nowrap;
		flex: none;
	}
	.steam:hover {
		border-color: #66c0f4;
		color: #fff;
	}

	.status-line {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		margin-bottom: 10px;
	}
	.you {
		font-size: 13.5px;
		font-weight: 800;
		color: var(--ink);
	}
	.you.good {
		color: var(--good);
	}
	.you-team {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.04em;
		color: var(--dim);
		font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
		padding: 3px 7px;
		border: 1px solid var(--line);
		border-radius: 6px;
	}
	.btnrow {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}
	.reg-hd {
		display: flex;
		flex-direction: column;
		gap: 2px;
		margin-bottom: 10px;
	}
	.reg-title {
		font-size: 14px;
		font-weight: 800;
		color: var(--ink);
	}
	.reg-sub {
		font-size: 11.5px;
		color: var(--dim);
	}
	.reg-stake {
		margin-bottom: 12px;
		padding: 8px 12px;
		border: 1px solid color-mix(in srgb, var(--gold) 30%, var(--line));
		border-radius: 9px;
		background: var(--gold-soft);
		font-size: 12.5px;
		font-weight: 700;
		color: var(--gold);
	}
	.picker {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 8px;
		margin-bottom: 12px;
	}
	.pk {
		display: flex;
		flex-direction: column;
		gap: 4px;
		min-width: 0;
	}
	.pk-l {
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.picker select {
		width: 100%;
		min-width: 0;
		/* ≥16px so iOS never zooms the viewport when the select is focused (HARD CONSTRAINT). */
		font-size: 16px;
		font-weight: 600;
		color: var(--ink);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 9px;
		padding: 9px 10px;
		min-height: 42px;
		appearance: none;
		-webkit-appearance: none;
		cursor: pointer;
	}
	.picker select:focus-visible {
		outline: 2px solid var(--gold);
		outline-offset: 1px;
	}

	.btn {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font: inherit;
		font-size: 13.5px;
		font-weight: 800;
		min-height: 42px;
		padding: 0 18px;
		border-radius: 10px;
		border: 1px solid var(--line);
		background: var(--panel-2);
		color: var(--ink);
		cursor: pointer;
	}
	.btn.wide {
		width: 100%;
	}
	.btn.primary {
		color: var(--gold-ink);
		background: var(--gold);
		border-color: var(--gold);
	}
	.btn.primary:hover:not(:disabled) {
		filter: brightness(1.05);
	}
	.btn.subtle {
		font-size: 12.5px;
		font-weight: 700;
		color: var(--dim);
		background: transparent;
		min-height: 40px;
		padding: 0 14px;
	}
	.btn.subtle:hover:not(:disabled) {
		color: var(--live);
		border-color: color-mix(in srgb, var(--live) 45%, var(--line));
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.notice {
		margin-top: 10px;
		font-size: 12.5px;
		font-weight: 700;
	}
	.notice.ok {
		color: var(--good);
	}
	.notice.err {
		color: var(--live);
	}

	/* ── section headers ── */
	.sec-hd {
		display: flex;
		align-items: baseline;
		gap: 8px;
		margin: 18px 2px 8px;
	}
	.sec-hd .cnt {
		font-size: 11px;
		font-weight: 800;
		letter-spacing: 0.02em;
		color: var(--gold);
	}

	/* ── registrations ── */
	.board {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
	}
	.plist {
		max-height: min(60vh, 640px);
		max-height: min(60dvh, 640px);
		overflow-y: auto;
		overscroll-behavior: contain;
	}
	.pr {
		display: flex;
		align-items: center;
		gap: 10px;
		padding: 9px 13px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.pr:last-child {
		border-bottom: none;
	}
	.pr.dropped {
		opacity: 0.5;
	}
	.seed {
		flex: none;
		width: 30px;
		font-size: 12px;
		font-weight: 800;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
	}
	.pid {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
		flex: 1 1 auto;
		text-decoration: none;
		color: inherit;
	}
	.pnm {
		font-weight: 700;
		font-size: 13.5px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.pnm .pf {
		margin-right: 3px;
	}
	.pid:hover .pnm {
		color: var(--gold);
	}
	.team {
		flex: none;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.04em;
		color: var(--dim);
		font-family: ui-monospace, 'Cascadia Mono', Consolas, monospace;
	}

	/* ── bracket ── */
	.bracket {
		display: flex;
		flex-direction: column;
		gap: 14px;
	}
	.bwrap {
		border: 1px solid var(--line);
		border-radius: 14px;
		background: var(--panel);
		overflow: hidden;
	}
	.brail {
		padding: 8px 14px;
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.14em;
		text-transform: uppercase;
		color: var(--faint);
		border-bottom: 1px solid var(--line);
		background: var(--panel-2);
	}
	.cols {
		display: flex;
		gap: 12px;
		padding: 12px;
		/* Wide bracket → scroll INSIDE this container so the page never scrolls sideways. */
		overflow-x: auto;
		overscroll-behavior-x: contain;
	}
	.col {
		display: flex;
		flex-direction: column;
		gap: 10px;
		flex: 0 0 auto;
		min-width: 172px;
	}
	.cround {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.mc {
		border: 1px solid var(--line);
		border-radius: 10px;
		background: var(--panel-2);
		padding: 7px 9px;
		display: flex;
		flex-direction: column;
		gap: 5px;
	}
	.mc.on {
		border-color: color-mix(in srgb, var(--stream) 45%, var(--line));
	}
	.mc-hd {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 6px;
	}
	.mid {
		font-size: 10px;
		font-weight: 800;
		color: var(--faint);
		font-variant-numeric: tabular-nums;
	}
	.chip {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.06em;
		padding: 1px 6px;
		border-radius: 5px;
		border: 1px solid var(--line);
		color: var(--dim);
	}
	.chip.live {
		color: var(--live);
		border-color: color-mix(in srgb, var(--live) 40%, var(--line));
		background: color-mix(in srgb, var(--live) 12%, transparent);
	}
	.chip.ready {
		color: var(--gold);
		border-color: color-mix(in srgb, var(--gold) 40%, var(--line));
	}
	.chip.done {
		color: var(--good);
		border-color: color-mix(in srgb, var(--good) 34%, var(--line));
		font-variant-numeric: tabular-nums;
	}
	.chip.muted {
		color: var(--faint);
	}
	.seat {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
	}
	.sname {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		text-decoration: none;
		color: inherit;
	}
	.seat .st {
		font-size: 12.5px;
		font-weight: 600;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.seat.win .st {
		font-weight: 800;
		color: var(--ink);
	}
	.sname:hover .st {
		color: var(--gold);
	}
	.tbd {
		font-size: 11.5px;
		font-style: italic;
		color: var(--faint);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.wtick {
		margin-left: auto;
		flex: none;
		font-size: 11px;
		font-weight: 900;
		color: var(--good);
	}

	/* ── rules ── */
	.rules {
		margin-top: 18px;
		border: 1px solid var(--line);
		border-radius: 12px;
		background: var(--panel);
		overflow: hidden;
	}
	.rules summary {
		cursor: pointer;
		padding: 12px 14px;
		list-style: none;
		user-select: none;
	}
	.rules summary::-webkit-details-marker {
		display: none;
	}
	.rules summary::after {
		content: '▸';
		float: right;
		color: var(--faint);
		transition: transform 0.15s;
	}
	.rules[open] summary::after {
		transform: rotate(90deg);
	}
	.rmd {
		padding: 2px 16px 16px;
		font-size: 13px;
		line-height: 1.55;
		color: var(--dim);
	}
	.rmd :global(h3),
	.rmd :global(h4),
	.rmd :global(h5),
	.rmd :global(h6) {
		color: var(--ink);
		font-size: 14px;
		font-weight: 800;
		margin: 12px 0 6px;
	}
	.rmd :global(h3:first-child) {
		margin-top: 4px;
	}
	.rmd :global(p) {
		margin: 5px 0;
	}
	.rmd :global(strong) {
		color: var(--ink);
	}
</style>
