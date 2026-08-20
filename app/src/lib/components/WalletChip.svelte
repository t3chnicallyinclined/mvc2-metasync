<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { wallet } from '$lib/stores/wallet.svelte';

	// 🪙 balance chip — the single global home of the quarters balance (DESIGN §5). It lives in the top bar
	// and OWNS the wallet lifecycle app-wide: load on sign-in, refresh live off the `matches` channel, and
	// pause while the tab is hidden (CPU discipline — mirrors the other live surfaces). Links to Settings,
	// where the full ledger lives. Hidden when signed-out or before the first balance lands.
	$effect(() => {
		// re-runs whenever the signed-in id changes (sign in / out) — keeps the balance bound to the user.
		void wallet.load(auth.steamid);
	});

	onMount(() => {
		wallet.connect();
		const onVis = () => {
			if (document.hidden) wallet.disconnect();
			else {
				wallet.connect();
				void wallet.load(auth.steamid);
			}
		};
		document.addEventListener('visibilitychange', onVis);
		return () => {
			document.removeEventListener('visibilitychange', onVis);
			wallet.disconnect();
		};
	});

	const show = $derived(auth.authed && wallet.balance != null);
</script>

{#if show}
	<a class="coin" href="{base}/settings" title="Your quarters — tap for your wallet">
		<span class="ic" aria-hidden="true">🪙</span>
		<span class="n">{wallet.balance}</span>
	</a>
{/if}

<style>
	.coin {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 5px 10px;
		border: 1px solid color-mix(in srgb, var(--gold) 30%, var(--line));
		border-radius: 999px;
		background: var(--gold-soft);
		color: var(--gold);
		text-decoration: none;
		font-weight: 800;
		flex: none;
		min-height: 28px;
	}
	.coin:hover {
		border-color: var(--gold);
	}
	.ic {
		font-size: 12px;
		line-height: 1;
	}
	.n {
		font-size: 12.5px;
		font-variant-numeric: tabular-nums;
	}
</style>
