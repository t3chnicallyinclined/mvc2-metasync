<script lang="ts">
	// Small round Steam avatar. Empty url → a neutral placeholder (no broken-image).
	let {
		url,
		size = 20,
		alt = ''
	}: { url?: string; size?: number; alt?: string } = $props();
</script>

{#if url}
	<img
		class="av"
		src={url}
		width={size}
		height={size}
		{alt}
		loading="lazy"
		referrerpolicy="no-referrer"
		style="width:{size}px;height:{size}px"
	/>
{:else}
	<span class="av ph" style="width:{size}px;height:{size}px" aria-hidden="true"></span>
{/if}

<style>
	.av {
		border-radius: 50%;
		object-fit: cover;
		flex: none;
		background: var(--panel-2);
		display: inline-block;
	}
	.ph {
		background: radial-gradient(circle at 50% 35%, var(--line), var(--panel-2));
	}
</style>
