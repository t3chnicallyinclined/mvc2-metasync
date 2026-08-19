<script lang="ts">
	import '../app.css';
	import RankSprite from '$lib/components/RankSprite.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import TabBar from '$lib/components/TabBar.svelte';

	let { children } = $props();
</script>

<!-- rank-badge sprite: injected once, referenced by every RankBadge via <use> -->
<RankSprite />

<div class="app">
	<div class="wrap">
		<TopBar />
		<main>
			{@render children()}
		</main>
	</div>
	<TabBar />
</div>

<style>
	main {
		margin-top: 6px;
	}
</style>
