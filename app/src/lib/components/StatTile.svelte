<script lang="ts">
	// A small ARENA stat tile: rail label + a big tabular number. Semantic accent optional.
	let {
		label,
		value,
		accent = 'var(--ink)',
		hint = ''
	}: { label: string; value: string | number; accent?: string; hint?: string } = $props();
</script>

<div class="tile" title={hint}>
	<span class="tl">{label}</span>
	<b class="tv" style="color:{accent}">{value}</b>
</div>

<style>
	.tile {
		min-width: 0; /* let the grid track shrink under the number on a phone */
		background: var(--panel-2);
		border: 1px solid var(--line);
		border-radius: 11px;
		padding: 9px 11px;
		display: flex;
		flex-direction: column;
		gap: 3px;
		overflow: hidden;
	}
	.tl {
		font-size: 9.5px;
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--faint);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.tv {
		font-size: 19px;
		font-weight: 900;
		line-height: 1.05;
		font-variant-numeric: tabular-nums;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
</style>
