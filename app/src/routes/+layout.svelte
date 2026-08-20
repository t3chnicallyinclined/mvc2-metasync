<script lang="ts">
	import { onMount } from 'svelte';
	import '../app.css';
	import RankSprite from '$lib/components/RankSprite.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import TabBar from '$lib/components/TabBar.svelte';
	import { pwa } from '$lib/stores/pwa.svelte';
	import { theme } from '$lib/stores/theme.svelte';

	let { children } = $props();

	// Boot-time: capture the install prompt + sync the theme store to what the inline script already applied.
	onMount(() => {
		pwa.init();
		theme.init();
	});
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
