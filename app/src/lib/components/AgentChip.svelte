<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { agent } from '$lib/stores/agent.svelte';

	// ⬢ Desktop-agent chip — surfaces the running tray/Tauri agent's build so the user always sees what's
	// connected. Owns the agent-status lifecycle app-wide (mirrors WalletChip): load on sign-in, refresh when
	// the tab regains focus. Links to Settings, where the full "Desktop companion" card lives. Hidden when
	// signed-out or before an agent has reported a build.
	$effect(() => {
		// re-runs whenever the signed-in id changes (sign in / out) — keeps the status bound to the user.
		void agent.load(auth.steamid);
	});

	onMount(() => {
		const onVis = () => {
			if (!document.hidden) void agent.load(auth.steamid);
		};
		document.addEventListener('visibilitychange', onVis);
		return () => document.removeEventListener('visibilitychange', onVis);
	});

	const show = $derived(auth.authed && agent.reporting);
	const st = $derived(agent.status);
</script>

{#if show}
	<a class="agent" href="{base}/settings" title="Your desktop agent — tap for details">
		<span class="hex" aria-hidden="true">⬢</span>
		<span class="v"><span class="word">Agent </span>v{st?.ver}</span>
		{#if st?.client}<span class="c">· {st.client}</span>{/if}
	</a>
{/if}

<style>
	.agent {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 5px 10px;
		border: 1px solid color-mix(in srgb, var(--good) 30%, var(--line));
		border-radius: 999px;
		background: color-mix(in srgb, var(--good) 12%, transparent);
		color: var(--good);
		text-decoration: none;
		font-weight: 800;
		flex: none;
		min-height: 28px;
		white-space: nowrap;
	}
	.agent:hover {
		border-color: var(--good);
	}
	.hex {
		font-size: 11px;
		line-height: 1;
	}
	.v {
		font-size: 12.5px;
		font-variant-numeric: tabular-nums;
	}
	.c {
		font-size: 11.5px;
		font-weight: 700;
		opacity: 0.85;
		text-transform: capitalize;
	}
	/* keep the top bar from crowding on small phones — trim to just "⬢ v0.2.6" */
	@media (max-width: 520px) {
		.word,
		.c {
			display: none;
		}
	}
</style>
