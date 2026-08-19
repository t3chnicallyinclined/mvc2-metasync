<script lang="ts">
	let { title, blurb }: { title: string; blurb: string } = $props();
</script>

<svelte:head><title>{title} · MetaSync</title></svelte:head>

<section class="cs">
	<span class="rail">{title}</span>
	<h1>Coming soon</h1>
	<p>{blurb}</p>
	<span class="pill gold">PHASE 2+</span>
</section>

<style>
	.cs {
		border: 1px dashed var(--line);
		border-radius: 14px;
		padding: 40px 22px;
		text-align: center;
		margin-top: 16px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 10px;
	}
	.cs h1 {
		font-size: 22px;
		font-weight: 900;
		font-style: italic;
	}
	.cs p {
		margin: 0;
		max-width: 420px;
		color: var(--dim);
		font-size: 13px;
		line-height: 1.5;
	}
</style>
