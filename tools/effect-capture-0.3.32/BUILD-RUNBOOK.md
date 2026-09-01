# BUILD-RUNBOOK.md — reader 0.3.32 build → re-record → convert → render → verify

End-to-end so the effect layer re-records ONCE. Three actors: a **RetroReceipts-agent** build session (edits
+ cargo), **Tris** (records a match on the Steam game), the **render harness** (this worktree, already done).

---

## Step 0 — This-worktree render side (ALREADY DONE + VERIFIED — no action)
Applied + headless-verified in `mvc-live-skins-quarters`:
- `replay-kit/tape_to_gpujson.py decode_objs` — 32B detection + `[…,gfx2,blend,is_effect,drawn,zy,effect_key,depth]`
  (unit-tested: 20B→10 elems, 32B→16 elems, [10/11/12]=blend/is_effect/drawn).
- `web/tapecanvas/tape-adapter.mjs` — `detectObjRecBytes` (32B), `decodeObjsBytes` (12B tail), `fromJsonObject`
  ([10..15]), `applyFrame` (real effect_key/engZ + `is_effect→FX_CID`, additive gated `!isEffect`).
- **Regression confirmed:** the existing 20B `tape_59601369.json` renders IDENTICALLY (recBytes=20, drawn=33,
  additive=33, brightPx=59453). Old tapes unaffected.
No `sprite-client.mjs`/`sprite-gpu.mjs` change — `_emitEffectQuad`/`_resolveFxSprite`/`FX_CID` already consume
`effect_key`/`blend`/`engZ`.

---

## Step 1 — Agent build (RetroReceipts-agent, NON-isolated session)
1. Apply **`reader-EDITS.md`** 2a–2f verbatim (Cargo.toml + reader.rs). They are append-only find/replace blocks.
2. Build:
   ```
   cd RetroReceipts-agent
   cargo build --release -p agent
   ```
   ⚠ This is a Windows compile of the reader — verify it ACTUALLY built (don't trust a stale binary; a
   `cargo check` is NOT a build; a Windows compile builds no linux-cfg code).
3. Smoke-verify the record shape WITHOUT a match: the built binary's tape header must carry the new descriptor.
   After a fresh capture, check `objs_enc` contains **`32B`** and **`is_effect`**, and that the objs blob
   decodes at 32 B/record:
   ```
   python3 - <<'PY'
   import json,gzip,base64
   t=json.load(open('<fresh_tape.json>'))
   print('objs_enc 32B?', '32B' in t['objs_enc'] and 'is_effect' in t['objs_enc'])
   raw=gzip.decompress(base64.b64decode(t['objs']))
   # first frame: u32 frame + u16 count; each rec must be 32 B
   import struct; off=0; f=struct.unpack_from('<I',raw,0)[0]; c=struct.unpack_from('<H',raw,4)[0]
   print('frame',f,'count',c,'record-bytes', (len(raw)-6)//c if c else 'n/a', '(expect 32 for a 1-frame tape)')
   PY
   ```

---

## Step 2 — Tris re-records (Steam game)
Record ONE match that exercises the effect layer:
- **Supers:** Storm Lightning Storm, Magneto Magnetic Tempest (the reported failures), + any others.
- **Blackheart Inferno** (the pillar / demon swarm — the ownerless class).
- Land hits so hitsparks/beams fire.
⚠ Record CLEAN (no training modifiers — meter regen / infinite health change the sim outside the inputs).
The 0.3.32 agent writes the 32 B objs wire automatically; nothing extra to toggle.

---

## Step 3 — Convert (this worktree)
```
python replay-kit/tape_to_gpujson.py <new_tape.json.gz>   # -> web/tapecanvas/tape.json
# expect the log to print frames=…, objframes=… ; the objs arrays now have 16 elements/obj.
```
(Optional: `... web/tapecanvas/tape_<id>.json` to keep it named; point play_state at it with `?tape=`.)

---

## Step 4 — Deploy the per-char bakes (see bakes-RUNBOOK.md)
Do the PARTDUMP bakes for PL2A/PL2C/PL35 (+ other super-casters) → scp to
`/var/www/maplecast/test-atlas/chars/` → bump `?v=`. This gives pixel-perfect effect cells; the reader wire
(step 1-3) gives correct blend + ownerless attribution. Both are needed for the full effect layer.

---

## Step 5 — Render + verify (this worktree)
```
python -m http.server 8091 --directory C:/Users/trist/projects   # if not already serving
```
Open: `http://localhost:8091/mvc-live-skins-quarters/web/tapecanvas/play_state.html?frame=<super fi>&right=<name>`
- The `fxadd`/`fxown` URL knobs are NO LONGER needed — the 0.3.32 tape carries `blend` (real, per-object) and
  `is_effect`; the adapter uses them directly (`effectBlendByte` priority (1)/(2) beats the interim allowlist).
- Verify: supers render **bright/additive where the reader says additive, alpha where it says alpha** (kills
  the 10% dim-alpha inconsistency); the Inferno demon-swarm **attributes without the per-tape `fxBankMap`**
  (once the reader ships is_effect + a resolved effect_key/owner routing to the FX atlas).

## Acceptance gate (deterministic — the sign-off)
`maplecast-flycast/web/webgpu-test.html` DIFF v7, **tint view**: the effect regions go **yellow (match)** vs
the TA-mirror truth on the frozen super frames. Not "looks brighter" — the pixel-aligned tint diff is the gate.

---

## Fallback / no-regression guarantee
Every edit is append-only + record-size-gated. A 16/20 B tape (all existing tapes) detects its old size and
renders exactly as before (verified headless on `tape_59601369.json`: recBytes=20, unchanged). The 32 B path
only activates when `objs_enc` says `32B`/`is_effect`.

## Open flags for the build session (route to mvc2-sh4-re-expert — see reader-EDITS.md tail)
1. Re-confirm Steam **H+0x12C = DC node+0xE8** depth.
2. `blk+0x6CE8` value-test catches 3D-class only — sprite-class is_effect reads 0 (expected); their brightness
   rides on `blend` + the FX-atlas/effect_key binding (derivable offline from the tape's `calib` blob).
3. PALETTE base handle **H+0x1B8 vs H+0x1A8** — reconcile before any reader-side palette deref (bakes side).
