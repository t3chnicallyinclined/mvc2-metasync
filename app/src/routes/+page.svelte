<script lang="ts">
	import { goto } from '$app/navigation';
	import { base } from '$app/paths';

	// Home → the live board (Ranks is the only functional tab in Phase 1).
	$effect(() => {
		void goto(`${base}/ranks`, { replaceState: true });
	});
</script>

<div class="empty">Loading the arena…</div>
