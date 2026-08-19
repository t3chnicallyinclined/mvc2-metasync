<script lang="ts">
	import { base } from '$app/paths';
	import Avatar from './Avatar.svelte';
	import { flagEmoji } from '$lib/format';
	import { auth } from '$lib/stores/auth.svelte';

	// Top-bar identity: a "Sign in through Steam" button when signed out, or the user's avatar+name
	// (→ their profile) with a sign-out control when signed in. Visible on desktop AND mobile.
</script>

{#if auth.authed}
	<div class="chip">
		<a class="who" href="{base}/u/{auth.steamid}" title="Your profile">
			<Avatar url={auth.me?.avatar} size={24} alt={auth.me?.name ?? 'You'} />
			<span class="nm">{#if auth.me?.cc}{flagEmoji(auth.me.cc)} {/if}{auth.me?.name || 'You'}</span>
		</a>
		<button class="out" onclick={() => auth.logout()} title="Sign out" aria-label="Sign out">⎋</button>
	</div>
{:else}
	<button class="steam" onclick={() => auth.login()}>
		<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
			<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" />
			<circle cx="15" cy="9" r="2.4" fill="currentColor" />
			<path d="M6 15l4.5 1.8" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
		</svg>
		<span class="lbl">Sign in</span>
	</button>
{/if}

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
	}
	.who {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		max-width: 168px;
		padding: 4px 8px 4px 4px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--panel);
		color: var(--ink);
		text-decoration: none;
		min-width: 0;
	}
	.who:hover {
		border-color: var(--gold-soft);
	}
	.nm {
		font-size: 12.5px;
		font-weight: 700;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.out {
		font: inherit;
		font-size: 14px;
		line-height: 1;
		color: var(--faint);
		background: transparent;
		border: 1px solid var(--line);
		border-radius: 999px;
		width: 28px;
		height: 28px;
		cursor: pointer;
		flex: none;
	}
	.out:hover {
		color: var(--bad, #ff6b6b);
		border-color: color-mix(in srgb, var(--bad, #ff6b6b) 45%, transparent);
	}
	.steam {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		font: inherit;
		font-size: 12.5px;
		font-weight: 800;
		color: #dfe9f5;
		background: linear-gradient(180deg, #2a475e, #1b2838);
		border: 1px solid color-mix(in srgb, #66c0f4 35%, transparent);
		border-radius: 999px;
		padding: 7px 13px;
		cursor: pointer;
		white-space: nowrap;
	}
	.steam:hover {
		border-color: #66c0f4;
		color: #fff;
	}
</style>
