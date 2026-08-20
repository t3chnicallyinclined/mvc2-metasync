<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { wager } from '$lib/stores/wager.svelte';
	import QuarterUpForm from './QuarterUpForm.svelte';

	// 🪙 QUARTER MATCH — the marquee rail (WAGER-MATCH-SPEC Variant A): the single home for the viewer's
	// wager through its whole lifecycle — offer/pending → incoming → locked (pot + running FT + 🔴 IN GAME)
	// → settled (won/lost + Run it back) → refunded. Collapses to the quarter-up CTA when there's nothing
	// live. State is READ from wager.mine (patched by SSE + the poll) — this component never writes DOM ad hoc.
	const me = $derived(auth.steamid);
	const w = $derived(wager.mine);
	const st = $derived(w?.status ?? '');
	const done = $derived(st === 'settled' || st === 'refunded' || st === 'cancelled' || st === 'expired');
	// a finished wager auto-retires after 5 min so the rail returns to the quarter-up CTA.
	const stale = $derived(done && Date.now() - (w?.locked_ms || w?.created_ms || 0) > 5 * 60 * 1000);
	const showState = $derived(
		!!w && (st === 'open' || st === 'locked' || ((st === 'settled' || st === 'refunded') && !stale))
	);

	const iAmChallenger = $derived(!!w && w.challenger === me);
	const oppName = $derived(
		w ? (iAmChallenger ? w.acceptor_name || 'opponent' : w.challenger_name || 'opponent') : ''
	);
	const iWon = $derived(!!w && st === 'settled' && w.winner === me);
	const pot = $derived(w ? (w.pot ?? w.stake * 2) : 0);

	let acting = $state(false);
	let notice = $state<{ kind: 'ok' | 'err'; text: string } | null>(null);

	async function cancel() {
		if (acting || !w) return;
		acting = true;
		notice = null;
		const r = await wager.cancel(w.id);
		acting = false;
		if (!r.ok) notice = { kind: 'err', text: r.error ?? 'Could not cancel.' };
	}
	async function respond(accept: boolean) {
		if (acting || !w) return;
		acting = true;
		notice = null;
		const r = await wager.respond(w.id, accept);
		acting = false;
		if (!r.ok) notice = { kind: 'err', text: r.error ?? 'Could not respond.' };
	}
	async function runback() {
		if (acting || !w) return;
		acting = true;
		notice = null;
		const r = await wager.offer({ stake: w.stake, ft: w.ft ?? 2 });
		acting = false;
		if (!r.ok) notice = { kind: 'err', text: r.error ?? 'Could not re-offer.' };
	}
	async function copyLink() {
		if (!w) return;
		const link = `https://nobd.net/skinsync/mm?id=${w.id}`;
		try {
			await navigator.clipboard.writeText(link);
			notice = { kind: 'ok', text: 'Challenge link copied — share it anywhere.' };
		} catch {
			notice = { kind: 'ok', text: link };
		}
	}
</script>

<section
	class="qmatch"
	class:locked={showState && st === 'locked'}
	class:ingame={showState && st === 'locked' && w?.live}
	class:win={showState && iWon}
>
	<span class="lab">🪙 Quarter Match</span>

	{#if !auth.authed}
		<!-- signed out — the invitation + the sign-in door -->
		<div class="body">
			<span class="line dim">Put a quarter on a set — winner takes the pot.</span>
			<div class="acts">
				<button type="button" class="steam" onclick={() => auth.login('/match')}>
					<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
						<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
						<circle cx="15" cy="9" r="2.4" fill="currentColor" />
						<path d="M6 15l4.5 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
					</svg>
					<span>Sign in to challenge</span>
				</button>
			</div>
		</div>
	{:else if showState && w}
		{#if st === 'open' && iAmChallenger}
			<!-- my quarter is up, waiting for a taker -->
			<div class="body">
				<span class="line"
					>🪙 {w.stake} on the marquee · FT{w.ft ?? 2} for the pot — <span class="dim">waiting for a taker…</span></span
				>
				<div class="acts">
					<button type="button" class="ghost" disabled={acting} onclick={copyLink}>⧉ Copy link</button>
					<button type="button" class="ghost warn" disabled={acting} onclick={cancel}>Cancel</button>
				</div>
			</div>
		{:else if st === 'open' && w.opp === me}
			<!-- someone challenged ME directly — the one primary action of this moment -->
			<div class="body">
				<span class="line"
					><b>{w.challenger_name || 'A challenger'}</b> puts up 🪙 {w.stake} — match it and the machine holds
					🪙 {pot}.</span
				>
				<div class="acts">
					<button type="button" class="gold" disabled={acting} onclick={() => respond(true)}
						>Match 🪙 {w.stake}</button
					>
					<button type="button" class="ghost" disabled={acting} onclick={() => respond(false)}>Decline</button>
				</div>
			</div>
		{:else if st === 'locked'}
			<!-- both quarters staked; the machine holds the pot -->
			<div class="body">
				{#if w.live}
					<span class="line"
						><span class="livedot" aria-hidden="true"></span><b>IN GAME</b> — 🪙 {pot} on the line ·
						<b>{w.challenger_name || '?'}</b>
						<span class="score">{w.cw ?? 0}–{w.aw ?? 0}</span> <b>{w.acceptor_name || '?'}</b> · first to {w.ft ??
							2} takes it</span
					>
				{:else}
					<span class="line"
						>🪙 {pot} in the machine — <b>{w.challenger_name || '?'}</b>
						<span class="score">{w.cw ?? 0}–{w.aw ?? 0}</span> <b>{w.acceptor_name || '?'}</b> · next game
						decides it (FT{w.ft ?? 2}).</span
					>
				{/if}
			</div>
		{:else if st === 'settled'}
			<div class="body">
				{#if iWon}
					<span class="line big">🪙 +{pot} — purse claimed</span>
				{:else}
					<span class="line loss">purse lost — 🪙 {w.stake} to {oppName}</span>
				{/if}
				<div class="acts">
					<button type="button" class="ghost" disabled={acting} onclick={runback}>🪙 Run it back</button>
				</div>
			</div>
		{:else if st === 'refunded'}
			<div class="body">
				<span class="line dim">🪙 {w.stake} returned — no result recorded.</span>
			</div>
		{/if}
	{:else}
		<!-- nothing live → the quarter-up affordance (open marquee challenge) -->
		<div class="cta">
			<QuarterUpForm />
		</div>
	{/if}

	{#if notice}
		<div class="railnote {notice.kind}" role="status">{notice.text}</div>
	{/if}
</section>

<style>
	.qmatch {
		margin: 0 0 12px;
		padding: 12px 14px;
		border: 1px solid var(--line);
		border-radius: 14px;
		background: linear-gradient(120deg, var(--gold-soft), transparent 72%), var(--panel);
	}
	.qmatch.locked {
		border-left: 3px solid var(--gold);
	}
	.qmatch.ingame {
		border-left: 3px solid var(--live);
		background: linear-gradient(90deg, color-mix(in srgb, var(--live) 9%, transparent), var(--panel) 55%);
	}
	.qmatch.win {
		border-left: 3px solid var(--gold);
	}
	@media (prefers-reduced-motion: no-preference) {
		.qmatch.win {
			animation: winflash 0.9s ease-out 1;
		}
	}
	@keyframes winflash {
		0% {
			background: color-mix(in srgb, var(--gold) 24%, var(--panel));
		}
		100% {
			background: linear-gradient(120deg, var(--gold-soft), transparent 72%), var(--panel);
		}
	}
	.lab {
		display: block;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--faint);
		margin-bottom: 9px;
	}
	.body {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		flex-wrap: wrap;
	}
	.line {
		font-size: 13px;
		color: var(--ink);
		min-width: 0;
		line-height: 1.4;
	}
	.line.dim,
	.line .dim {
		color: var(--dim);
	}
	.line b {
		font-weight: 800;
	}
	.line.big {
		font-size: 15px;
		font-weight: 900;
		font-style: italic;
		color: var(--gold);
	}
	.line.loss {
		color: var(--dim);
	}
	.score {
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		color: var(--gold);
		padding: 0 2px;
	}
	.livedot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--live);
		margin-right: 6px;
		vertical-align: baseline;
	}
	@media (prefers-reduced-motion: no-preference) {
		.livedot {
			animation: pulse 1.6s ease-in-out infinite;
		}
	}
	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.35;
		}
	}
	.acts {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
		flex: none;
	}
	.cta {
		margin-top: 2px;
	}

	/* buttons */
	.gold,
	.ghost,
	.steam {
		font: inherit;
		font-size: 12.5px;
		font-weight: 800;
		border-radius: 9px;
		padding: 0 13px;
		min-height: 40px;
		cursor: pointer;
		white-space: nowrap;
	}
	.gold {
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border: 1px solid transparent;
		font-style: italic;
		font-weight: 900;
	}
	.gold:hover:not(:disabled) {
		filter: brightness(1.05);
	}
	.ghost {
		color: var(--dim);
		background: transparent;
		border: 1px solid var(--line);
	}
	.ghost:hover:not(:disabled) {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.ghost.warn:hover:not(:disabled) {
		color: var(--live);
		border-color: color-mix(in srgb, var(--live) 45%, var(--line));
	}
	.steam {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		color: #dfe9f5;
		background: linear-gradient(180deg, #2a475e, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 35%, transparent);
	}
	.steam:hover {
		border-color: #66c0f4;
		color: #fff;
	}
	.gold:disabled,
	.ghost:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.railnote {
		margin-top: 9px;
		font-size: 12px;
		font-weight: 700;
	}
	.railnote.ok {
		color: var(--good);
	}
	.railnote.err {
		color: var(--live);
	}
</style>
