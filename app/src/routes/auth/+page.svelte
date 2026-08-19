<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';

	// The Steam OpenID token is captured inline in app.html (survives a stale service worker), so by
	// the time this route mounts the session is already stored. This is just a friendly landing that
	// bounces home; captureFragment() is a belt-and-suspenders fallback if the inline script didn't run.
	onMount(() => {
		if (!auth.authed) auth.captureFragment();
		void goto(`${base}/ranks`, { replaceState: true });
	});
</script>

<svelte:head><title>Signing in · MetaSync</title></svelte:head>

<div class="wrap">
	<span class="spin" aria-hidden="true"></span>
	<p>Signing you in…</p>
</div>

<style>
	.wrap {
		display: grid;
		place-items: center;
		gap: 14px;
		min-height: 60vh;
		padding: 24px;
	}
	p {
		margin: 0;
		color: var(--faint);
		font-size: 13px;
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
