<script lang="ts">
	import { page } from '$app/state';
	import { base } from '$app/paths';
	import { NAV } from '$lib/nav';

	// The single global arena bar (DESIGN-SYSTEM.md hard-rule #1): brand cab + cut-tabs + gold seam.
	// Desktop only — mobile uses the bottom TabBar.
	const path = $derived(page.url.pathname);
	function active(href: string): boolean {
		const full = base + href;
		if (href === '/ranks') return path === base + '/' || path.startsWith(full);
		return path.startsWith(full);
	}
</script>

<header class="bar">
	<a class="brand" href="{base}/ranks">
		<span class="cab">M</span>
		<span class="wordmark">Meta<span class="g">Sync</span></span>
	</a>
	<span class="seam" aria-hidden="true"></span>
	<nav class="tabs">
		{#each NAV as t (t.id)}
			<a class="cut" class:on={active(t.href)} class:soon={!t.live} href="{base}{t.href}">
				<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"
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
	<span class="brandtag">MvC2 · METASYNC</span>
</header>

<style>
	.bar {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 10px 4px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		text-decoration: none;
		color: var(--ink);
	}
	.cab {
		width: 32px;
		height: 32px;
		border-radius: 9px;
		display: grid;
		place-items: center;
		background: linear-gradient(160deg, var(--gold), color-mix(in srgb, var(--gold) 55%, #ff5c2c));
		color: var(--gold-ink);
		font-weight: 900;
		font-size: 17px;
	}
	.wordmark {
		font-size: 15.5px;
		font-weight: 800;
		letter-spacing: 0.02em;
	}
	.wordmark .g {
		color: var(--gold);
	}
	.seam {
		width: 2px;
		height: 26px;
		transform: skewX(-14deg);
		background: linear-gradient(180deg, transparent, color-mix(in srgb, var(--gold) 60%, var(--line)), transparent);
	}
	.tabs {
		display: flex;
		gap: 4px;
		align-items: center;
	}
	.cut {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		transform: skewX(-12deg);
		padding: 7px 13px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: transparent;
		color: var(--dim);
		font-size: 12.5px;
		font-weight: 700;
		text-decoration: none;
		transition: color 0.15s, border-color 0.15s, background 0.15s;
	}
	.cut > :global(*) {
		transform: skewX(12deg);
	}
	.cut:hover {
		color: var(--ink);
		border-color: var(--gold-soft);
	}
	.cut.on {
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border-color: transparent;
		color: var(--gold-ink);
		font-style: italic;
	}
	.cut.soon {
		opacity: 0.72;
	}
	.brandtag {
		margin-left: auto;
		font-size: 10px;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--faint);
		font-weight: 700;
	}
	@media (max-width: 720px) {
		/* the bottom TabBar carries navigation on mobile */
		.bar {
			gap: 10px;
		}
		.seam,
		.tabs,
		.brandtag {
			display: none;
		}
	}
</style>
