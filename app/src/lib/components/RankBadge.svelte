<script lang="ts">
	import { rankOf, RANK_MIN_GAMES } from '$lib/ranks';

	// One rank badge. Derives the tier from rating+games (client-derived — never a server string).
	// Pass `games` as null when placement info is unknown (derive straight from rating).
	let {
		rating,
		games = null,
		size = 16
	}: { rating: number | null | undefined; games?: number | null; size?: number } = $props();

	const r = $derived(rankOf(rating, games));
	const rt = $derived(typeof rating === 'number' && isFinite(rating) ? rating : 1000);
	const tip = $derived(
		r.n === 'Civilian'
			? `Civilian — play ${RANK_MIN_GAMES} games to get ranked`
			: `${r.n} · ${rt} ELO`
	);
</script>

<span class="rkw" title={tip}>
	<svg class="rkb" width={size} height={size} aria-hidden="true"><use href="#rk-{r.s}" /></svg>
</span>

<style>
	.rkw {
		display: inline-flex;
		line-height: 0;
	}
	.rkb {
		display: block;
	}
</style>
