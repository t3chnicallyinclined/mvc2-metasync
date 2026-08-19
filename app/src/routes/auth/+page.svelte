<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';

	// Steam's OpenID return lands here (SKINSYNC_OPENID_SUCCESS = /app/auth) with #token&steamid in the
	// fragment. Capture it, then bounce to wherever the user started (or /ranks). A bare visit with no
	// token shows a sign-in prompt instead of a dead end.
	let failed = $state(false);

	onMount(() => {
		const ret = auth.captureFragment();
		if (ret) {
			void goto(`${base}${ret}`, { replaceState: true });
		} else {
			failed = true;
		}
	});
</script>

<svelte:head><title>Signing in · MetaSync</title></svelte:head>

<div class="wrap">
	{#if failed}
		<div class="card">
			<h1>Sign-in didn’t complete</h1>
			<p>The Steam sign-in was cancelled or the link expired.</p>
			<button class="steam" onclick={() => auth.login('/ranks')}>Sign in through Steam</button>
			<a class="back" href="{base}/ranks">Back to the ladder</a>
		</div>
	{:else}
		<div class="card">
			<span class="spin" aria-hidden="true"></span>
			<p class="muted">Signing you in…</p>
		</div>
	{/if}
</div>

<style>
	.wrap {
		display: grid;
		place-items: center;
		min-height: 60vh;
		padding: 24px;
	}
	.card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 14px;
		text-align: center;
		max-width: 360px;
	}
	h1 {
		font-size: 18px;
		font-weight: 900;
		font-style: italic;
	}
	p {
		margin: 0;
		color: var(--dim);
		font-size: 13px;
	}
	.muted {
		color: var(--faint);
	}
	.steam {
		font: inherit;
		font-weight: 800;
		font-size: 13px;
		color: #fff;
		background: linear-gradient(180deg, #2a3f5f, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 40%, transparent);
		border-radius: 9px;
		padding: 10px 16px;
		cursor: pointer;
	}
	.steam:hover {
		border-color: #66c0f4;
	}
	.back {
		color: var(--dim);
		font-size: 12px;
		text-decoration: none;
	}
	.back:hover {
		color: var(--gold);
	}
	.spin {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		border: 3px solid var(--line);
		border-top-color: var(--gold);
		animation: spin 0.8s linear infinite;
	}
	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.spin {
			animation-duration: 2s;
		}
	}
</style>
