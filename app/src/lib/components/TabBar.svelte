<script lang="ts">
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { NAV } from '$lib/nav';

	// Mobile bottom tab bar — the primary nav on phones. Hidden on desktop (TopBar takes over).
	const path = $derived(page.url.pathname);
	function active(href: string): boolean {
		const full = base + href;
		if (href === '/ranks') return path === base + '/' || path.startsWith(full);
		return path.startsWith(full);
	}
</script>

<nav class="tabbar" aria-label="Primary">
	{#each NAV as t (t.id)}
		<a class="tab" class:on={active(t.href)} href="{base}{t.href}" aria-current={active(t.href) ? 'page' : undefined}>
			<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"
				><path
					d={t.d}
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
				/></svg
			>
			<span>{t.label}</span>
		</a>
	{/each}
</nav>

<style>
	.tabbar {
		display: none;
	}
	@media (max-width: 720px) {
		.tabbar {
			position: fixed;
			left: 0;
			right: 0;
			bottom: 0;
			z-index: 40;
			display: grid;
			grid-template-columns: repeat(5, 1fr);
			gap: 2px;
			padding: 6px 6px calc(6px + env(safe-area-inset-bottom));
			background: color-mix(in srgb, var(--panel) 92%, transparent);
			backdrop-filter: blur(10px);
			border-top: 1px solid var(--line);
		}
	}
	.tab {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 3px;
		padding: 6px 2px;
		text-decoration: none;
		color: var(--faint);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.02em;
		border-radius: 10px;
	}
	.tab span {
		white-space: nowrap;
	}
	.tab.on {
		color: var(--gold);
	}
	.tab.on svg {
		filter: drop-shadow(0 0 6px color-mix(in srgb, var(--gold) 50%, transparent));
	}
</style>
