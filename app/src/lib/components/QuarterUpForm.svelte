<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { wallet } from '$lib/stores/wallet.svelte';
	import { wager } from '$lib/stores/wager.svelte';

	// 🪙 Quarter-up form — pick a stake + a first-to target, then put a quarter up. Reused for BOTH an
	// OPEN marquee challenge (no opp) and a directed "challenge this player" (opp set). Stakes mirror the
	// desktop's 🪙 1/2/4/8 denominations; FT the arcade 2/3/5. All writes ride wager.offer → auth.post.
	let {
		opp = '',
		oppName = ''
	}: { opp?: string; oppName?: string } = $props();

	const STAKES = [1, 2, 4, 8];
	const FTS = [2, 3, 5];
	let stake = $state(2);
	let ft = $state(2);
	let busy = $state(false);
	let notice = $state<{ kind: 'ok' | 'err'; text: string } | null>(null);

	const bal = $derived(wallet.balance);
	const tooRich = $derived(bal != null && stake > bal);

	async function submit() {
		if (busy || tooRich) return;
		busy = true;
		notice = null;
		const body: { stake: number; ft: number; opp?: string } = { stake, ft };
		if (opp) body.opp = opp;
		const res = await wager.offer(body);
		busy = false;
		if (res.ok) {
			notice = {
				kind: 'ok',
				text: opp
					? `Challenge sent to ${oppName || 'them'} — 🪙 ${stake} on the line.`
					: `🪙 ${stake} is on the marquee — waiting for a taker.`
			};
		} else {
			notice = { kind: 'err', text: res.error ?? 'Could not put your quarter up.' };
		}
	}
</script>

<div class="qform">
	<div class="pickers">
		<div class="pk">
			<span class="pk-l">Stake</span>
			<div class="opts" role="group" aria-label="Stake">
				{#each STAKES as v (v)}
					<button
						type="button"
						class="opt"
						class:on={stake === v}
						disabled={busy || (bal != null && v > bal)}
						aria-pressed={stake === v}
						onclick={() => (stake = v)}>🪙 {v}</button
					>
				{/each}
			</div>
		</div>
		<div class="pk">
			<span class="pk-l">First to</span>
			<div class="opts" role="group" aria-label="First to">
				{#each FTS as v (v)}
					<button
						type="button"
						class="opt"
						class:on={ft === v}
						disabled={busy}
						aria-pressed={ft === v}
						onclick={() => (ft = v)}>FT{v}</button
					>
				{/each}
			</div>
		</div>
	</div>

	<div class="foot">
		{#if bal != null}<span class="echo">you have 🪙 {bal}</span>{/if}
		<button type="button" class="put" disabled={busy || tooRich} onclick={submit}>
			{#if busy}
				Putting it up…
			{:else if opp}
				Challenge {oppName || 'player'} ▸
			{:else}
				Put it up ▸
			{/if}
		</button>
	</div>

	{#if tooRich && !busy}
		<div class="hint">Not enough quarters for that stake — pick a lower one.</div>
	{/if}
	{#if notice}
		<div class="notice {notice.kind}" role="status">{notice.text}</div>
	{/if}
</div>

<style>
	.qform {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.pickers {
		display: flex;
		flex-wrap: wrap;
		gap: 14px 22px;
	}
	.pk {
		display: flex;
		flex-direction: column;
		gap: 6px;
		min-width: 0;
	}
	.pk-l {
		font-size: 9.5px;
		font-weight: 800;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.opts {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}
	.opt {
		font: inherit;
		font-size: 13px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		color: var(--dim);
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 9px;
		padding: 0 12px;
		min-height: 40px;
		cursor: pointer;
		transform: skewX(-10deg);
		white-space: nowrap;
	}
	.opt > :global(*),
	.opt {
		transition: color 0.12s, border-color 0.12s, background 0.12s;
	}
	.opt.on {
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-color: transparent;
		font-style: italic;
	}
	.opt:disabled {
		opacity: 0.42;
		cursor: default;
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}
	.echo {
		font-size: 12px;
		font-weight: 700;
		color: var(--dim);
		font-variant-numeric: tabular-nums;
	}
	.put {
		margin-left: auto;
		font: inherit;
		font-size: 13.5px;
		font-weight: 900;
		font-style: italic;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border: 1px solid transparent;
		border-radius: 10px;
		padding: 0 18px;
		min-height: 42px;
		cursor: pointer;
		transform: skewX(-10deg);
		white-space: nowrap;
	}
	.put > :global(*) {
		display: inline-block;
		transform: skewX(10deg);
	}
	.put:hover:not(:disabled) {
		filter: brightness(1.05);
	}
	.put:disabled {
		opacity: 0.55;
		cursor: default;
	}
	.hint {
		font-size: 11.5px;
		color: var(--dim);
	}
	.notice {
		font-size: 12.5px;
		font-weight: 700;
	}
	.notice.ok {
		color: var(--good);
	}
	.notice.err {
		color: var(--live);
	}
</style>
