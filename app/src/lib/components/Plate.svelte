<script lang="ts">
	import type { Snippet } from 'svelte';

	// ARENA "Plate" primitive (DESIGN-SYSTEM.md): skewX(-6..-8deg), children counter-skewed, a 3–4px
	// accent edge, and a 120deg wash keyed off the accent vars --pa/--pb (skin colors, else tier colors).
	let {
		pa = 'var(--line)',
		pb = 'var(--line)',
		edge = 'left',
		skew = 6,
		children,
		class: klass = '',
		...rest
	}: {
		pa?: string;
		pb?: string;
		edge?: 'left' | 'top' | 'right';
		skew?: number;
		children: Snippet;
		class?: string;
		[k: string]: unknown;
	} = $props();
</script>

<div
	class="plate edge-{edge} {klass}"
	style="--pa:{pa}; --pb:{pb}; --skew:{-skew}deg; --unskew:{skew}deg;"
	{...rest}
>
	{@render children()}
</div>

<style>
	.plate {
		transform: skewX(var(--skew, -6deg));
		background:
			linear-gradient(
				120deg,
				color-mix(in srgb, var(--pa) 14%, transparent),
				transparent 70%
			),
			var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 12px;
		padding: 12px 16px;
		box-shadow: 0 6px 22px rgba(0, 0, 0, 0.32);
	}
	.plate > :global(*) {
		transform: skewX(var(--unskew, 6deg));
	}
	.edge-left {
		border-left: 4px solid var(--pa);
	}
	.edge-right {
		border-right: 4px solid var(--pa);
	}
	.edge-top {
		border-top: 3px solid var(--pa);
	}
</style>
