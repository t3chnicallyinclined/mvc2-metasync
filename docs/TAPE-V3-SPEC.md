# TAPE v3 — a tape designed backwards from a pixel-exact renderer

> **Status: 2026-09-02, PROPOSAL.** Every requirement below is traced to a measurement, and the
> measurements are cited. Nothing here is a guess about what "might be useful later" — v2 already
> carries several fields nothing consumes, and this document deletes some of them.

---

## 0. The one design decision that matters

**Record the engine's draw ORDER, not the inputs to it.**

v2 records the six fighter slots as columns and the pool objects as a separate `objs` stream. The
engine does not see two lists — it sees **one ordered draw list** that fighters and pool objects are
both registered into. Splitting them throws the interleaving away, and no amount of post-hoc sorting
puts it back:

* on a layer tie the fighter registers FIRST, so a same-layer object lands on top of its own body —
  measured on tape `59601369`, **4,722 objects share their owner's layer exactly**, so the tie is the
  common case, not an edge;
* the real tie-break is `(s8) node+0x4D` (Steam; DC `+0x31`), which v2 does not record. Over a
  300-frame capture: `0 ×1778`, **`-8 ×1754`**, `8 ×294`, `2 ×144`, `1 ×110` — **43% of nodes carry
  the "draw behind" value.**

That is the cape drawing through the body, and it is not fixable downstream from v2's data.

**The fix is not to add the sort key. It is to stop reconstructing an order we can simply observe.**
The engine's own array is already sorted — `loc_8c0308c2` walks layers `0..15` ascending, then index
`0..count-1`, and registration (`loc_8c04515e`) has already applied the sort. The agent's
`harvest_objs` **already walks exactly that array**; it just splits the output. Emit it in order and
the renderer needs no sort at all, no layer-direction rule, and no registration model.

> Order is a *fact we can read*, not a *property we must derive*. Recording the derivation inputs and
> re-deriving on the client is how three separate ordering bugs got in.

---

## 1. Schema

One record per drawn node, per frame, **in draw order**.

```
frame:   u32   the engine frame clock (blk+0x3CC8). NOT a row counter.
nodes:   [ ... ]   ordered; index IS paint order, back to front
```

Per node — 20 bytes packed, or the named form below:

| field | width | source (Steam) | why it is here |
|---|---|---|---|
| `kind` | u8 | derived | 0 = fighter slot, 1 = pool object. Distinguishes the two atlas lookups. |
| `slot` | u8 | draw-list handle vs `blk+0x3DB8 + s*0x738` | which fighter; `0xFF` for an unowned object |
| `owner` | u8 | `node+0x28` (u64 → slot) | an object's atlas comes from its OWNER's character |
| `sid` | u16 | `node+0x188` | **the render key.** Ship RAW — bit 15 is a transform flag the consumer masks |
| `sx`,`sy` | i16 ×2 | `node+0x124`, `+0x128` (f32) | the origin. 640×480 space; native is `×3/5`, `×7/15` |
| `facing` | u8 | see §3 | selects `origin − dx` vs `origin + dx − w` |
| `pal` | u8 | see §2 | palette row. **v2's `costume` is not sufficient** |
| `cat` | u8 | `node+0x03` | 0 = fighter, 1..4 = the four pool lists. Gates the render path |
| `scale` | u16 | `node` zx (×4096) | 1.0 in every frame measured so far — see §4 |
| `gfx1` | u32 | `node+0x1A0` | the effect-page content key. §5 |

**Dropped from v2**, because nothing consumes them and they cost bytes every frame: `zx` as a
per-object column when it is constant (fold into §4's exception rule), `layer` and the standalone
`objs` stream (subsumed by ordering), and the `?` column that is `0` in all 17,958 rows.

**Kept but demoted to diagnostics**, written once per frame rather than per node: `eyeX`, `eyeY`,
`ground`, `timer`, `round_no`, meters, and the health/combo columns. Those drive the HUD and the
stage camera, not the sprite emitter.

---

## 2. ⚠ The palette field, and why `costume` is not enough

**CONFIRMED:** `costume c → palette row block 8·c`. Established from the palette data (rows in
`PLxx_lut.json` repeat at `+8` and never at `+4`: PL2A 25/40, PL17 30/40, PL2C 29/40, PL32 35/40),
and it independently predicts the captures — costume 1 → bank 8, which is exactly the bank the
captured PL2A / PL17 / PL2C palettes matched byte-for-byte. Tris confirmed the rendered result
(gold Storm, blue Magneto) is the costume actually selected.

**⚠ STILL A GAP: the sub-row within the block (0..7).** A captured PL32 body needs sub-row 2, and
every record in that assembly carries `FLAGS 0x0000`, so the record's `0x0070` field cannot be the
whole story. `docs/MVC2-RECONSTRUCTION-SPEC.md` names `node+0x12d`/`+0x12e` as the missing terms and
marks them "NO — GAP" on the wire.

⟹ **Record the resolved row, not the inputs.** `pal` should be the row the engine is actually using
(from the node's palette pointer), so the renderer never has to reproduce a rule we have not fully
derived. Same principle as §0: observe, don't re-derive. If the pointer proves awkward to resolve,
`8·costume + subrow` is the fallback and `subrow` is the field to hunt.

---

## 3. ⚠ `facing` is not one bit, and v2 conflates two of them

Three separate things exist and they are not the same:

* the **owner's** facing (`char+0x110`) — the field the body walker uses;
* the **object's own** flip (`node+0x130`), shipped in v2 inside `sid`'s bit 15;
* the record-level `flip`/`flipy` in the assembly table (`FLAGS & 0x4000 / 0x8000`).

v2's `objs` already XORs two of them at the consumer. **v3 should ship the object's own flip as its
own bit** and let the renderer combine, so a future correction does not require re-recording.

⚠ Which combination is correct is only measured indirectly: f2574's right-side body faces LEFT and
its quads are unmirrored, so the atlas is baked facing left. That is one observation, not a proof.

---

## 4. Scale — carry it, even though it is currently always 1

`zx` is `6826` in **all 17,958** object rows of tape `59601369` — exactly `5/3`, i.e. the same
640→384 factor the origins use, so the native scale is 1.0 and no scaling is exercised.

**Carry it anyway.** The DC walker has a scaled branch (`loc_8c034bea`, the `&0x8000` case) that this
tape never took, and supers and giant characters will take it. A field that is constant costs two
bytes and compresses to nothing; discovering we need it later costs a re-record of every tape.

---

## 5. `gfx1` and the effects gap — what v3 cannot fix alone

Super effects are **not** the character path. Measured on the triple-super capture: 90 additive draws,
all `vs_world` + `texalpha` sampling **256×256 RGBA pages**, blend `src=SRC_ALPHA dst=ONE`. They are a
different asset class from the palette-indexed bodies — RGBA, world-transformed.

The offline effects atlas is not a substitute: `test-atlas/effects/fx_atlas.json` holds **25 effects /
50 sprites** and labels its own key mapping `UNVERIFIED` off a base it calls DYNAMIC. The tape's
`gfx1` values (77 distinct, 2824..6962) are not in that range.

⟹ `gfx1` goes in the tape as the join key, but **the `gfx1` → page mapping has to be built
separately**, from captures that carry state (which now exist). Until that table exists, effects
render from whatever the fx atlas can resolve and the rest are missing. **That is a known hole, not a
tape bug** — do not let a missing effect be read as a broken emitter.

---

## 6. What this buys, and what it does not

**Pixel-exact is already demonstrated for bodies.** `emitter_gate.py` on `frame_5630`:

```
PL2A sel 83   coverage IoU 1.0000   index-exact 1.0000   missed 0, invented 0, wrong index 0
PL32 sel 13   coverage IoU 0.9997   index-exact 1.0000   missed 0, invented 2, wrong index 0
```

So the body path needs **no new data** — v3's ordering fixes composition, not fidelity.

Still open after v3, and none of it is solved by adding tape columns:

| gap | what it needs |
|---|---|
| effect pages | the `gfx1` → page table, from state-carrying captures |
| HUD state | list-`0x0B` nodes are not in any tape; the 256×128 font bank IS in every capture |
| palette sub-row | `node+0x12d`/`+0x12e`, or ship the resolved row (§2) |
| stage | rip once per `stage_id`; geometry proven static (455 world-space draws byte-identical across two DIFFERENT matches) |

---

## 7. Migration

v3 is a **superset in information and smaller on the wire** — one ordered list replaces six fighter
column-groups plus a parallel `objs` stream, and the dropped constant columns pay for `pal` and the
flip bit. Keep `schema` as the self-describing string v2 established so a reader can tell them apart,
and keep v2 readable: the fleet has tapes on disk and on rise3 that must not become unplayable.

**Do not migrate the fleet before the emitter consumes v3 end to end and `emitter_gate.py` passes on
a v3-driven frame.** The one thing worse than a tape that orders sprites wrongly is two tape formats
that both do.

---

## 8. ⭐⭐⭐ THE REGISTRATION CONTRACT, CONFIRMED FROM STEAM'S OWN CODE

> Tris: *"the steam ghidra expert should be the deciding factor on this, because that's how we are
> rendering it."* Correct, and it changed two things. Everything below is read from the Steam binary
> (`senior-re-generalist`, Ghidra disassembly rather than decompiler inference), not mapped from the
> DC. Where our capture could check a claim independently, the check is quoted.

### 8.1 The offsets

| field | DC | **Steam, CONFIRMED** | width / sign | where |
|---|---|---|---|---|
| category | `+0x03` | `+0x03` | u8, accept `<= 4` (`JA`) | `FUN_14061e560` @ `0x14061E5A5` |
| next ptr | `+0x08` | `+0x10` | u64 | list walk |
| **layer** | `+0x24` | **`+0x38`** | **s8** (`MOVSX`) | `0x14061E5AF` |
| **sort key** | `+0x31` | **`+0x4D`** | **s8** (`JLE`/`JG`) | `0x14061E61F` / `0x14061E66F` |
| visible | `+0x12C` | `+0x170` | u8 nonzero | `0x14061E590` |
| per-layer cap | `0x60` | `0x60` = 96 | s8 compare | `0x14061E5C3` |

Registration is `FUN_14061e560` (list walk) and `FUN_14061e780` (single node, fighters only); the
per-frame clear is `FUN_14061e690`; the walker is **`FUN_140620F10`**, and it iterates `L = 0..15`
ascending then `i = 0..count-1` ascending — `0x2F4D0 → 0x324D0` in steps of `0x300` is exactly 16.

**The sort key derivation held.** `(s8) node+0x4D`, ascending and stable, strict `>` to swap. The
statistical derivation (417 ordered-differing pairs, zero violations, signed-only) and the
instruction encoding agree on **both** the offset and the signedness, having never seen each other.

**⚠ The layer was wrong and is now corrected: `+0x38`, not `+0x24`.** Checked against our own
capture: `+0x38` equals the layer the node was walked from on **4,080 of 4,080** nodes; `+0x24`
disagrees **3,154** times. We only escaped the error because `blkstate.py` derives the layer
structurally — from which row of the array the handle came out of — rather than from the node.

**The DC→Steam deltas are a mechanism, not a table to memorise:** `0, +0x08, +0x14, +0x1C, +0x44`,
monotonically non-decreasing with offset — 32→64-bit pointer widening. That is exactly why `+0x44`
was the wrong delta for `+0x31`: `+0x44` only applies *past the last widened pointer*.

### 8.2 ⚠⚠ Two things that would have produced correct-looking, wrong output

**Registration order is fighters → list 3 → list 4 → list 1 → list 2.** Not 1,2,3,4. All four call
sites are byte-identical (`0x14060E523`, `0x14060EBA0`, `0x14060EE24`, `0x14060EF75`): clear the 16
counts, `FUN_140620190` registers the six fighters slot 0..5 ascending, then `MOV CL,3 / 4 / 1 / 2`
into `FUN_14061e560`.

Because the sort is **stable**, ties resolve to insertion order — and ties dominate: ~86% of nodes
sit on just two key values (`0 ×1778`, `-8 ×1754`). So **tie order IS draw order for most of the
frame.** Register in the wrong list order and every per-node field is byte-correct while the z-order
is wrong on the majority of nodes.

**⚠ And a monotonicity check cannot detect this.** My 2,943-pair analysis found the key, but a stable
sort's tie order is *invisible* to a non-decreasing test — the pairs it rests on are exactly the ones
where the key differs. The expert's verdict is **GO on the sort key, NO-GO on "draw order
reproduced"** until the tie order is in the path.

**Visibility is checked TWICE** — `node+0x170` gates registration (`0x14061E590`) *and* is re-checked
at draw time in the walker. A node can be registered and then hidden before the walk. Reproduce only
the first and you draw **phantoms**.

### 8.3 Why this vindicates §0 rather than complicating it

Every hazard in 8.2 is a hazard of **reconstructing** the order: wrong list order, invisible tie
order, a visibility flag that changes between the two checks. **v3 records the array as walked**, so
none of them can occur — tie order, list order and second-chance visibility all arrive as observed
fact.

It also settles the alternative for good: **the writer that SETS `+0x4D` is NOT LOCATED.** The key
can be *read* but not *predicted*. A design that derives order client-side would need that writer;
a design that records order does not.

> The Steam-side check confirmed the field we found, corrected a field we had wrong, and named a
> failure our own method structurally could not see. That last one is the reason to ask.

### 8.4 One correction to §1's source column

`blk` is `[0x142EDF560]`. `0x140AC6EF0` is the rollback **registration** copy — the base/size pair
written to `PTR_DAT_140acd3a0 + 0x1b0/0x1b8` at match init. Both point at the same buffer, which is
why reading through either works, but game code goes through `0x142EDF560`. The two-xref oddity that
first made `0x140AC6EF0` look authoritative is explained by this.

### 8.5 The falsification test, stated before the fix

Freeze one savestate. Dump the live `blk+0x2F4D0` row for a layer with `count >= 3` where at least
two nodes share `+0x4D`. Independently rebuild that row from the node lists using fighters→3→4→1→2.
**If the handle sequences differ, the registration-order claim is wrong.** Single variable, one
frozen frame, and the comparison is a byte-exact full-frame diff — not a sampled screenshot, because
z-order errors on ties are precisely what periodic capture aliases away.
