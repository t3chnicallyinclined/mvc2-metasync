<script lang="ts">
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { auth } from '$lib/stores/auth.svelte';
	import { api } from '$lib/config';
	import { CHAR_NAME, charAbbr } from '$lib/chars';
	import { STOCK_PALETTES } from '$lib/stockPalettes';

	// THE web skin picker (Phase 3). Pick a character → edit its 16-colour palette → Save. The palette is
	// stored server-side as your loadout ({char → colors}); the tray agent polls it and paints your fighters
	// live in-game (MvC2 sprites are palette-indexed, so the palette IS the recolor). Reset reverts to stock.
	// Minimal by design: the agent only ever needs the char id + the 16 colours — everything else stays here.

	const roster = Object.keys(STOCK_PALETTES)
		.map(Number)
		.filter((id) => CHAR_NAME[id])
		.sort((a, b) => (CHAR_NAME[a] || '').localeCompare(CHAR_NAME[b] || ''));

	let loadout = $state<Record<number, string[]>>({}); // cid → 16 hex (your saved custom picks)
	let selected = $state<number | null>(null);
	let edit = $state<string[]>([]); // the 16 hex currently being edited
	let saving = $state(false);
	let loaded = $state(false);

	const toHex = (n: number) => '#' + (n & 0xffffff).toString(16).padStart(6, '0');
	const toInt = (h: string) => parseInt(h.replace('#', ''), 16) & 0xffffff;

	async function loadLoadout() {
		if (!auth.authed) {
			loaded = true;
			return;
		}
		try {
			const res = await fetch(api('/skinsync/loadout'), {
				headers: { accept: 'application/json', ...auth.headers() }
			});
			if (res.ok) {
				const j = (await res.json()) as { skins?: { cid: number; colors: number[] }[] };
				const map: Record<number, string[]> = {};
				for (const s of j.skins ?? []) {
					if (Array.isArray(s.colors) && s.colors.length >= 16)
						map[s.cid] = s.colors.slice(0, 16).map(toHex);
				}
				loadout = map;
			}
		} catch {
			// keep-last-good
		}
		loaded = true;
	}
	onMount(loadLoadout);

	function pick(cid: number) {
		selected = cid;
		edit = (loadout[cid] ?? STOCK_PALETTES[cid] ?? []).slice();
	}
	function close() {
		selected = null;
	}
	const isCustom = (cid: number) => cid in loadout;
	const curName = $derived(selected != null ? CHAR_NAME[selected] || `#${selected}` : '');

	// a sprite that 404s → abbreviation fallback (same pattern as the versus card).
	let spriteFailed = $state<Set<number>>(new Set());
	function onSpriteError(id: number) {
		if (!spriteFailed.has(id)) spriteFailed = new Set(spriteFailed).add(id);
	}

	async function save() {
		if (selected == null || !auth.authed) return;
		saving = true;
		const cid = selected;
		try {
			const res = await fetch(api('/skinsync/loadout'), {
				method: 'POST',
				headers: { 'content-type': 'application/json', ...auth.headers() },
				body: JSON.stringify({ cid, colors: edit.map(toInt) })
			});
			if (res.ok) loadout = { ...loadout, [cid]: edit.slice() };
		} catch {
			// swallow — the swatch state stays as edited; user can retry
		}
		saving = false;
	}
	async function resetStock() {
		if (selected == null || !auth.authed) return;
		saving = true;
		const cid = selected;
		try {
			const res = await fetch(api(`/skinsync/loadout?cid=${cid}`), {
				method: 'DELETE',
				headers: { ...auth.headers() }
			});
			if (res.ok) {
				const { [cid]: _drop, ...rest } = loadout;
				loadout = rest;
				edit = (STOCK_PALETTES[cid] ?? []).slice();
			}
		} catch {
			// keep-last-good
		}
		saving = false;
	}
	function revertEdits() {
		if (selected == null) return;
		edit = (loadout[selected] ?? STOCK_PALETTES[selected] ?? []).slice();
	}
</script>

<svelte:head><title>Skins · MetaSync</title></svelte:head>

<section class="mast" style="--acc:#8b6dff">
	<div class="ghost" aria-hidden="true">SKINS</div>
	<div class="mrow">
		<h1 class="mtitle">SKINS</h1>
		<span class="pill">LOADOUT</span>
	</div>
	<div class="seam" aria-hidden="true"></div>
	<p class="mdesc">Pick a character and set its 16-colour palette — it saves to your loadout and the agent paints it live in your matches. Reset any character back to stock anytime.</p>
</section>

{#if !auth.authed}
	<div class="signin">
		<p>Sign in with Steam to build your skin loadout — it follows your SteamID, and your running agent applies it in-game.</p>
		<button class="steam" onclick={() => auth.login()}>Sign in through Steam</button>
	</div>
{:else}
	<div class="grid">
		{#each roster as cid (cid)}
			<button class="cc" class:on={selected === cid} class:custom={isCustom(cid)} onclick={() => pick(cid)} title={CHAR_NAME[cid]}>
				<div class="face">
					{#if spriteFailed.has(cid)}
						<span class="abbr">{charAbbr(cid)}</span>
					{:else}
						<img src="{base}/chars/{cid}.webp" alt={CHAR_NAME[cid]} loading="lazy" onerror={() => onSpriteError(cid)} />
					{/if}
					{#if isCustom(cid)}<span class="dot" title="Custom skin set" aria-hidden="true"></span>{/if}
				</div>
				<div class="nm">{CHAR_NAME[cid]}</div>
			</button>
		{/each}
	</div>
{/if}

{#if selected != null}
	<!-- editor overlay -->
	<div class="ovl" role="presentation" onclick={(e) => { if (e.target === e.currentTarget) close(); }}>
		<div class="ed" role="dialog" aria-modal="true" aria-label="{curName} palette">
			<header class="edh">
				<div class="edt">
					<span class="rail">Palette</span>
					<b>{curName}</b>
					{#if isCustom(selected)}<span class="tag">custom</span>{:else}<span class="tag stock">stock</span>{/if}
				</div>
				<button class="x" onclick={close} aria-label="Close">✕</button>
			</header>

			<div class="preview" aria-hidden="true">
				<img src="{base}/chars/{selected}.webp" alt="" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')} />
				<div class="strip">
					{#each edit as c, i (i)}<span class="chip" style="background:{c}"></span>{/each}
				</div>
			</div>

			<div class="swatches">
				{#each edit as _c, i (i)}
					<label class="sw" title="Colour {i + 1}">
						<input type="color" bind:value={edit[i]} />
						<span class="idx">{i + 1}</span>
					</label>
				{/each}
			</div>

			<footer class="edf">
				<button class="btn ghost" onclick={revertEdits} disabled={saving}>Undo edits</button>
				<button class="btn ghost" onclick={resetStock} disabled={saving}>Reset to stock</button>
				<button class="btn save" onclick={save} disabled={saving}>{saving ? 'Saving…' : 'Save skin'}</button>
			</footer>
			<p class="note">Applies in your next match — your agent picks it up within a few seconds.</p>
		</div>
	</div>
{/if}

<style>
	.mast {
		position: relative;
		overflow: hidden;
		padding: 14px 4px 10px;
		margin-bottom: 6px;
	}
	.ghost {
		position: absolute;
		right: 0;
		top: -6px;
		font-size: clamp(46px, 12vw, 96px);
		font-style: italic;
		font-weight: 900;
		letter-spacing: -0.03em;
		color: var(--ink);
		opacity: 0.045;
		pointer-events: none;
		user-select: none;
	}
	.mrow {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.mtitle {
		font-size: clamp(20px, 5.5vw, 27px);
		font-weight: 900;
		font-style: italic;
	}
	.pill {
		font-size: 10px;
		font-weight: 800;
		letter-spacing: 0.08em;
		padding: 3px 8px;
		border-radius: 6px;
		color: var(--stream);
		background: color-mix(in srgb, var(--stream) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--stream) 34%, var(--line));
	}
	.seam {
		height: 3px;
		width: 120px;
		margin: 8px 0 9px;
		transform: skewX(-14deg);
		background: linear-gradient(90deg, var(--acc), transparent);
	}
	.mdesc {
		margin: 0;
		max-width: 720px;
		color: var(--dim);
		font-size: 12.5px;
		line-height: 1.5;
	}

	.signin {
		border: 1px dashed var(--line);
		border-radius: 14px;
		padding: 26px 18px;
		text-align: center;
		color: var(--dim);
		display: flex;
		flex-direction: column;
		gap: 14px;
		align-items: center;
	}
	.steam {
		font: inherit;
		font-weight: 800;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border: none;
		border-radius: 10px;
		padding: 10px 18px;
		cursor: pointer;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(84px, 1fr));
		gap: 8px;
	}
	.cc {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
		padding: 8px 4px 6px;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 12px;
		cursor: pointer;
		font: inherit;
		transition: border-color 0.15s, transform 0.1s;
	}
	.cc:hover {
		border-color: var(--gold-soft);
		transform: translateY(-1px);
	}
	.cc.on {
		border-color: var(--stream);
		box-shadow: 0 0 0 1px var(--stream);
	}
	.cc.custom {
		border-color: color-mix(in srgb, var(--gold) 45%, var(--line));
	}
	.face {
		position: relative;
		width: 62px;
		height: 72px;
		border-radius: 9px;
		overflow: hidden;
		display: grid;
		place-items: center;
		background: linear-gradient(180deg, var(--panel-2), var(--panel));
	}
	.face img {
		width: 100%;
		height: 100%;
		object-fit: contain;
		image-rendering: pixelated;
	}
	.abbr {
		font-size: 15px;
		font-weight: 900;
		color: var(--dim);
	}
	.dot {
		position: absolute;
		top: 3px;
		right: 3px;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--gold);
		box-shadow: 0 0 6px var(--gold);
	}
	.nm {
		font-size: 10.5px;
		font-weight: 700;
		color: var(--dim);
		max-width: 100%;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	/* editor overlay */
	.ovl {
		position: fixed;
		inset: 0;
		z-index: 100;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: max(16px, env(safe-area-inset-top)) 14px calc(16px + env(safe-area-inset-bottom));
		background: color-mix(in srgb, #05070c 72%, transparent);
		backdrop-filter: blur(3px);
	}
	.ed {
		width: 100%;
		max-width: 460px;
		max-height: min(88vh, 880px);
		max-height: min(88dvh, 880px);
		display: flex;
		flex-direction: column;
		overflow: hidden;
		background: var(--panel);
		border: 1px solid var(--line);
		border-radius: 16px;
		box-shadow: var(--shadow);
	}
	.edh {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 10px;
		padding: 12px 14px;
		border-bottom: 1px solid var(--line);
	}
	.edt {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 0;
	}
	.edt b {
		font-size: 15px;
		font-weight: 800;
	}
	.rail {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.16em;
		text-transform: uppercase;
		color: var(--faint);
	}
	.tag {
		font-size: 9px;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
		padding: 2px 6px;
		border-radius: 5px;
		color: var(--gold);
		border: 1px solid color-mix(in srgb, var(--gold) 40%, var(--line));
	}
	.tag.stock {
		color: var(--faint);
		border-color: var(--line);
	}
	.x {
		flex: none;
		width: 30px;
		height: 30px;
		border-radius: 8px;
		border: 1px solid var(--line);
		background: var(--panel-2);
		color: var(--dim);
		cursor: pointer;
	}
	.x:hover {
		color: var(--ink);
	}
	.preview {
		display: flex;
		align-items: center;
		gap: 14px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--line-soft);
		background: linear-gradient(180deg, var(--panel-2), transparent);
	}
	.preview img {
		width: 66px;
		height: 82px;
		object-fit: contain;
		image-rendering: pixelated;
		flex: none;
	}
	.strip {
		display: grid;
		grid-template-columns: repeat(8, 1fr);
		gap: 3px;
		flex: 1;
	}
	.strip .chip {
		height: 16px;
		border-radius: 3px;
		border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
	}
	.swatches {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 8px;
		padding: 14px 16px;
		overflow-y: auto;
	}
	.sw {
		position: relative;
		display: block;
		height: 46px;
		border-radius: 8px;
		overflow: hidden;
		border: 1px solid var(--line);
		cursor: pointer;
	}
	.sw input {
		position: absolute;
		inset: -4px;
		width: calc(100% + 8px);
		height: calc(100% + 8px);
		border: none;
		padding: 0;
		background: none;
		cursor: pointer;
	}
	.sw .idx {
		position: absolute;
		bottom: 2px;
		right: 4px;
		font-size: 9px;
		font-weight: 800;
		color: #fff;
		text-shadow: 0 0 3px rgba(0, 0, 0, 0.9);
		pointer-events: none;
	}
	.edf {
		display: flex;
		gap: 8px;
		padding: 12px 16px 4px;
		flex-wrap: wrap;
	}
	.btn {
		font: inherit;
		font-size: 12.5px;
		font-weight: 800;
		border-radius: 9px;
		padding: 9px 14px;
		cursor: pointer;
		border: 1px solid var(--line);
	}
	.btn.ghost {
		background: var(--panel-2);
		color: var(--dim);
	}
	.btn.ghost:hover {
		color: var(--ink);
	}
	.btn.save {
		margin-left: auto;
		color: var(--gold-ink);
		background: linear-gradient(180deg, #ffe084, #c98f0e);
		border: none;
	}
	.btn:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.note {
		margin: 0;
		padding: 8px 16px 14px;
		font-size: 11px;
		color: var(--faint);
		text-align: center;
	}
</style>
