# effect-capture-0.3.32 — turnkey staged package (the effect-layer fix)

Re-record ONCE. This package makes the tape carry everything Path-A needs to render every effect
faithfully: per-object **blend**, **is_effect**, **effect_key**/**depth**, plus the per-character
multi-tile **PARTDUMP bakes** for pixel-perfect effect cells.

## Why (grounded, this worktree)
- Super effects (Storm Lightning Storm, Magneto Magnetic Tempest, Blackheart Inferno) are almost all
  **owner-attributed** and DO draw, but: (a) the gfx1-bank additive allowlist covers only **~90%** →
  1,667 nodes render dim alpha (banks 0x19/0x16/0x0d/0x0b); (b) a minority are **ownerless globals**
  (Blackheart's demon-swarm, 9 gfx1 values that NEVER appear owner-attributed → unlearnable from the 20 B
  tape); (c) all super cells are **multi-tile / scratch-dependent** → offline decode is a CONFIRMED dead end.
- (a)+(b) need the reader **wire** (blend + is_effect + effect_key). (c) needs the **PARTDUMP bakes**.

## Read in this order
1. **`reader-EDITS.md`** — verbatim find/replace for `RetroReceipts-agent` (Cargo.toml 0.3.31→0.3.32,
   H-consts, `ObjNode`, `harvest_objs`, serialize 20→32 B, `objs_enc`). Non-isolated agent session.
2. **`BUILD-RUNBOOK.md`** — build the agent → re-record → convert → render → the pixel gate. Ties it together.
3. **`bakes-RUNBOOK.md`** — the per-char PARTDUMP bakes (PL2A/PL2C/PL35 + other super-casters) for
   pixel-perfect cells. Non-isolated maplecast session.

## Already done in THIS worktree (no action; verified headless, old tapes unaffected)
- `replay-kit/tape_to_gpujson.py` `decode_objs` — 32 B detection + extended emit (unit-tested).
- `web/tapecanvas/tape-adapter.mjs` — `detectObjRecBytes`/`decodeObjsBytes`/`fromJsonObject`/`applyFrame`
  consume the 0.3.32 fields; 20 B fallback verified byte-identical (`tape_59601369.json` recBytes=20,
  drawn=33, additive=33, brightPx=59453).
- No `sprite-client.mjs`/`sprite-gpu.mjs` change — `_emitEffectQuad`/`_resolveFxSprite`/`FX_CID` already
  key on `effect_key`/`blend`/`engZ`.

The render side is a no-op for existing tapes and lights up automatically the moment a 0.3.32 tape arrives.
