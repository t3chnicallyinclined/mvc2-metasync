<script lang="ts">
	import { base } from '$app/paths';
	import { flagEmoji, whenLabel } from '$lib/format';
	import {
		statusMeta,
		formatLabel,
		entryCost,
		placeLabel,
		type TournamentSummary
	} from '$lib/tourney';

	let { t }: { t: TournamentSummary } = $props();

	const st = $derived(statusMeta(t.status));
	const place = $derived(placeLabel(t));
	const when = $derived(whenLabel(t.starts_ms));
	const cost = $derived(entryCost(t.entry_fee_cents, t.entry_coins));
	const entrants = $derived(t.entrants ?? 0);
	const cap = $derived(t.cap ?? 0);
	const free = $derived(cost === 'Free');
</script>

<a class="card" href="{base}/tournament/{t.id}" aria-label={t.name}>
	<div class="top">
		<span class="pill {st.cls}">{st.label}</span>
		{#if t.online}<span class="pill net">ONLINE</span>{/if}
		{#if t.stream_url}<span class="stream" aria-hidden="true" title="Has a stream">▶</span>{/if}
	</div>

	<h3 class="nm">{t.name || 'Untitled'}</h3>

	<div class="meta">
		<span class="fmt">{formatLabel(t.format)}</span>
		<span class="sep" aria-hidden="true">·</span>
		<span class="ent">{entrants}{cap ? `/${cap}` : ''} {entrants === 1 ? 'entrant' : 'entrants'}</span>
	</div>

	<div class="foot">
		<span class="loc" title={place}>
			<span class="flag">{flagEmoji(t.cc)}</span>
			<span class="lt">{place || (t.online ? 'Online' : '—')}</span>
		</span>
		<span class="cost" class:free>{cost}</span>
	</div>

	{#if when}<div class="when">Starts {when}</div>{/if}
</a>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: 7px;
		min-width: 0;
		padding: 13px 15px 12px;
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
		border: 1px solid var(--line);
		border-radius: 14px;
		box-shadow: var(--shadow);
		text-decoration: none;
		color: inherit;
		transition: border-color 0.15s, transform 0.12s;
	}
	.card:hover {
		border-color: var(--gold-soft);
		transform: translateY(-1px);
	}
	.top {
		display: flex;
		align-items: center;
		gap: 6px;
		flex-wrap: wrap;
	}
	.pill.net {
		color: var(--stream);
		background: color-mix(in srgb, var(--stream) 12%, transparent);
		border-color: color-mix(in srgb, var(--stream) 34%, var(--line));
	}
	.pill.muted {
		color: var(--faint);
	}
	.stream {
		margin-left: auto;
		font-size: 11px;
		color: var(--stream);
		flex: none;
	}
	.nm {
		font-size: clamp(16px, 4.5vw, 18px);
		font-weight: 900;
		font-style: italic;
		letter-spacing: 0.01em;
		line-height: 1.15;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.meta {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--dim);
		min-width: 0;
	}
	.meta .fmt {
		font-weight: 700;
		color: var(--ink);
		white-space: nowrap;
	}
	.meta .sep {
		color: var(--faint);
	}
	.meta .ent {
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.foot {
		display: flex;
		align-items: center;
		gap: 10px;
		margin-top: 1px;
	}
	.loc {
		display: flex;
		align-items: center;
		gap: 6px;
		min-width: 0;
		flex: 1 1 auto;
		font-size: 11.5px;
		color: var(--dim);
	}
	.loc .flag {
		flex: none;
		font-size: 13px;
	}
	.loc .lt {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}
	.cost {
		flex: none;
		font-size: 11.5px;
		font-weight: 800;
		color: var(--gold);
		white-space: nowrap;
	}
	.cost.free {
		color: var(--good);
	}
	.when {
		font-size: 10.5px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--faint);
	}
</style>
