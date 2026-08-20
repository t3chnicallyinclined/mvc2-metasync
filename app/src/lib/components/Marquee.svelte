<script lang="ts">
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { wager } from '$lib/stores/wager.svelte';
	import Avatar from './Avatar.svelte';

	// THE MARQUEE — the open-challenge feed (WAGER-MATCH-SPEC): every quarter that's up for anyone to
	// attempt. Reads wager.open (public, live off the `matches` channel). Signed-in → ⚔ Attempt matches the
	// stake into escrow; signed-out → the sign-in door. Your own quarter shows Cancel instead.
	const me = $derived(auth.steamid);
	const rows = $derived(wager.open.slice(0, 12));

	const is17 = (sid: string) => /^\d{17}$/.test(sid);
	const nameFor = (w: { challenger: string; challenger_name?: string }) =>
		w.challenger_name || (w.challenger ? `…${w.challenger.slice(-5)}` : 'Player');

	let acting = $state('');
	let notice = $state<{ kind: 'ok' | 'err'; text: string } | null>(null);

	async function attempt(id: string) {
		if (!auth.authed) {
			auth.login('/match');
			return;
		}
		if (acting) return;
		acting = id;
		notice = null;
		const r = await wager.respond(id, true);
		acting = '';
		if (r.ok) notice = { kind: 'ok', text: '🪙 Matched — the machine holds the pot.' };
		else notice = { kind: 'err', text: r.error ?? 'Could not match that quarter.' };
	}
	async function cancel(id: string) {
		if (acting) return;
		acting = id;
		notice = null;
		const r = await wager.cancel(id);
		acting = '';
		if (!r.ok) notice = { kind: 'err', text: r.error ?? 'Could not cancel.' };
	}
</script>

<section class="sec">
	<h2 class="shead">
		<span class="ic" aria-hidden="true">🪙</span> Open Challenges
		{#if rows.length}<span class="cnt">{rows.length}</span>{/if}
	</h2>

	{#if rows.length === 0}
		<div class="empty">
			{#if auth.authed}
				No open challenges right now. Put a quarter up on the rail above and wait for a taker.
			{:else}
				No open challenges right now. Sign in to challenge someone for quarters.
			{/if}
		</div>
	{:else}
		<div class="panel">
			{#each rows as w (w.id)}
				{@const nm = nameFor(w)}
				{@const mine = w.challenger === me}
				<div class="mq" class:me={mine}>
					<span class="who">
						<Avatar size={24} alt={nm} />
						{#if is17(w.challenger)}
							<a class="nm" href="{base}/u/{w.challenger}" title={nm}>{nm}</a>
						{:else}
							<span class="nm" title={nm}>{nm}</span>
						{/if}
					</span>
					<span class="stake" title="pot 🪙 {w.pot ?? w.stake * 2}">
						🪙 {w.stake}<i>·</i>FT{w.ft ?? 2}<i>·</i><span class="pot">pot 🪙 {w.pot ?? w.stake * 2}</span>
					</span>
					{#if mine}
						<button type="button" class="btn ghost" disabled={acting === w.id} onclick={() => cancel(w.id)}
							>Cancel</button
						>
					{:else}
						<button type="button" class="btn attempt" disabled={acting === w.id} onclick={() => attempt(w.id)}
							>⚔ {acting === w.id ? '…' : 'Attempt'}</button
						>
					{/if}
				</div>
			{/each}
		</div>
	{/if}

	{#if notice}
		<div class="note {notice.kind}" role="status">{notice.text}</div>
	{/if}
</section>

<style>
	.sec {
		margin-top: 16px;
	}
	.shead {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0 0 8px;
		font-size: 13px;
		font-weight: 800;
		letter-spacing: 0.02em;
		color: var(--ink);
	}
	.shead .ic {
		font-size: 14px;
		line-height: 1;
	}
	.cnt {
		font-size: 11px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		color: var(--gold);
		background: var(--gold-soft);
		border: 1px solid color-mix(in srgb, var(--gold) 30%, var(--line));
		border-radius: 999px;
		padding: 1px 7px;
	}
	.panel {
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 14px;
		overflow: hidden;
	}
	/* [avatar+name] [stake meta] [action] — name track shrinks + ellipsizes, action stays put */
	.mq {
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto auto;
		align-items: center;
		gap: 10px;
		padding: 10px 14px;
		border-bottom: 1px solid color-mix(in srgb, var(--line) 55%, transparent);
	}
	.mq:last-child {
		border-bottom: none;
	}
	.mq.me {
		background: linear-gradient(90deg, var(--gold-soft), transparent 55%);
	}
	.who {
		display: flex;
		align-items: center;
		gap: 8px;
		min-width: 0;
	}
	.nm {
		font-weight: 700;
		font-size: 13.5px;
		color: var(--ink);
		text-decoration: none;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	a.nm:hover {
		color: var(--gold);
	}
	.stake {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		flex: none;
		font-size: 12px;
		font-weight: 800;
		color: var(--gold);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.stake i {
		font-style: normal;
		color: var(--faint);
		font-weight: 700;
	}
	.stake .pot {
		color: var(--dim);
		font-weight: 700;
	}
	/* on the tightest phones drop the pot echo (the stake + FT carry the meaning) */
	@media (max-width: 380px) {
		.stake .pot,
		.stake i:last-of-type {
			display: none;
		}
	}
	.btn {
		font: inherit;
		font-size: 12px;
		font-weight: 800;
		border-radius: 9px;
		padding: 0 12px;
		min-height: 40px;
		cursor: pointer;
		white-space: nowrap;
		flex: none;
	}
	.btn.attempt {
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border: 1px solid transparent;
		font-style: italic;
		font-weight: 900;
	}
	.btn.attempt:hover:not(:disabled) {
		filter: brightness(1.05);
	}
	.btn.ghost {
		color: var(--dim);
		background: transparent;
		border: 1px solid var(--line);
	}
	.btn.ghost:hover:not(:disabled) {
		color: var(--live);
		border-color: color-mix(in srgb, var(--live) 45%, var(--line));
	}
	.btn:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.note {
		margin-top: 8px;
		font-size: 12px;
		font-weight: 700;
	}
	.note.ok {
		color: var(--good);
	}
	.note.err {
		color: var(--live);
	}
</style>
