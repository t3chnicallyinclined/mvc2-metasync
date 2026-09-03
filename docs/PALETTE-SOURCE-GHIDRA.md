# Palette source: where the LUT a character draw binds comes from (Steam MvC2, Ghidra, 2026-09-03)

RE METHOD (`docs/RE-METHOD.md`), steps 1-4 all applied: SH4 anchors `loc_8c035000` / `loc_8c035162` / `loc_8c034bea`
(marvelous2 bank03) ported to the Steam binary by function matching, propagated along the call graph to the NaomiLib
palette upload and the D3D LUT refresh, globals translated through the block map (`0x8c2659dc` staging -> `blk+0x1040`),
every pair tagged and stored in seed `maplecast-flycast/tools/re_kb/38_palette_source.surql`.
Binary: `mvc_dump.bin` (GhidraMCP bridge :8080, `decompile_function?address=`, `xrefs_to?address=`). `blk` = `DAT_142edf560`,
`G` = `DAT_142edf580`, `ctx` = `DAT_142ef0ab0` (NaomiLib host context), `dev` = `*(DAT_140acd3a8)` (the D3D device wrapper).
Tags: **CONFIRMED** = both sides read / reproduced by a gate; **INFERRED** = derived, not read; **UNKNOWN** = not located.
Gate tool: `d3dcap/replay/palette_gate.py`. No ROM-derived bytes in this document.

## 0. Answer

* **`FUN_1406129f0` (= `loc_8c034bea`, the sprite submit) does NOT carry a palette.** Every quad it emits goes through
  `FUN_140845e20(&quad)` with only a **texture-table index** (`*(blk+0x32bec) + node+0x120 + tile` on the tiled path,
  `node+0x230 * 0x100 + 0x390 + alloc` on the scale-walker path). `FUN_140845e20` reads the slot-table entry
  `ctx+0x1e00a0 + idx*0x18` and packs its `+4` word = the **palette bank** as `(bank+1)<<16 | idx` into the polygon
  word before `FUN_1408436a0(0xc, ...)`. **CONFIRMED.**
* **The bank was fixed at sheet registration**: `FUN_140612180` (= `loc_8c033d78`, CONFIRMED) computes per unique part
  `palid = ((node+0x172)*16 + rec.flags) >> 4 & 0x3F` when `node+0x171 != 0` (else `rec.flags >> 4`), i.e.
  **bank = slot base + record sub-row**; `FUN_140845fe0` stores it at slot-table `+4`. Slot base `node+0x172` =
  `DAT_140a6d188[node+0x230]` = `{0x10,0x18,0x20,0x28,0x30,0x38}` (bytes read from the dump; = DC `loc_8c1355d4`).
* **The colours the bank holds come from the STAGING LINES** `blk+0x1040 + bank*0x38` (128 lines; `+0` u32 bank idx,
  `+4` u32 count = 16, `+8` u32 flag `1` raw pending / `2` dim pending / `0` uploaded, `+0x18` 16 x u16 ARGB4444).
  DC: `0x8c2659dc + bank*0x30` (`+8` flag, `+0x10` colours). **CONFIRMED both builds.**
  * filled by `FUN_1406146d0` (= `loc_8c035162`, CONFIRMED both read): mode 0 (rest) sets `+0x172` from the slot table,
    **row 0 = `FUN_140614130(node)`** (= `loc_8c035000`, CONFIRMED) = `DatPal + (node+0x39)*0x100` with per-character
    extras (char 1 / 0x14 with `+0x2b2`, 0x22 with `+0xf0`, 0x37 with `+0x374` -> the `+0x600` extras block),
    **rows 1..7 = `DatPal + (node+0x39)*0x100 + 0x20*k`**; modes 1, 3..7 copy `node+0x4c` (+1/+2) rows from the extras
    block (flash palettes, frame parity `G+0x1C`); mode 2 / 10 set flag 2 (dim) / 1 on all eight lines; 8 / 9 fill
    white / 0xff00.
  * uploaded by `FUN_140613390` (per-frame render begin, called from `FUN_14060a1f0` <- `FUN_140608a00`; also at init):
    for each flagged line, copy raw (flag 1) or **dimmed `(c>>1)&0x777 | c&0xF000`** (flag 2) into `blk+0x2C40+i*0x20`,
    then `FUN_140845670(bank<<4, colours, 16)` -> `FUN_140048940` -> `FUN_14004d350`: expands each u16 into a u32 at
    **host PALETTE_RAM `dev+0xd8d04 + entry*4`** (1024 entries; Steam's PVR `0xA05F9000`); flag cleared.
  * turned into textures by `FUN_140048970` (sole caller: the frame flush `FUN_140843eb0`, before it executes the queued
    draws): flips `dev+0xd8d00`, memcmp's each 16-entry bank against the per-flip copy at `dev+0xd9d04 + flip*0x1000`,
    Maps the changed bank into **its own D3D texture `dev+0xd8500 + (bank + flip*0x40)*8`** (64 B; 1 KB for banks
    `== 0 mod 16`). The draw binds that texture as `t1`: the captured 256x1 `fmt 28` (R8G8B8A8) page, **each channel =
    nibble*17** (measured on the pages; the SIMD expander in `FUN_14004d350` was not decoded by hand).
* **`DatPal` (`cl+0x4C` = `node+0x1B8` = DC `char+0x164`) is the character's palette BLOCK in its DAT bank**: six
  costume blocks of 0x100 B (8 rows x 32 B) at +0, extras from +0x600. It is a load-time *source*, not the rendered
  palette. **The v3/v4 tape `pal` = 32 B at `DatPal+0` = costume 0, row 0**, whatever the fighter wears.
* **Mirror-colour selector = `node+0x39`** (DC `char+0x25`, copied from `char+0x52D` at fighter init, bank04
  `loc_8c04f0ec`): each same-character object carries its own variant and stages into its own bank range from its own
  DatPal (distinct DAT bank per slot). The character-select rule that assigns `+0x52D` (forced alternate colour vs the
  player's pick) was **not traced on Steam: UNKNOWN** - the tape does not need it once it ships the resolved rows.
* Reader caveat: `OFF_COLOR = cl+0x6` is `node+0x172` = the **bank base** (0x10/0x18/...), not the variant; it differs
  per slot and so masqueraded as a per-side colour discriminator.

## 1. Gates (deterministic, numeric)

### 1.1 capgate: captured LUT pages vs the frame's own staging lines

`python d3dcap/replay/palette_gate.py 4445 4505 5168 7279`. For every draw binding a 256x1 `t1`, its first 64 B must
equal SOME staging line converted with the rule above; the matched bank is then checked against the owner slot.

| frame | indexed draws | LUT == staged line | banks bound (owner slot / row) | note |
|---|---|---|---|---|
| 4445 | 240 | **240/240** | 0x20 (s2 r0) 41, 0x23 (s2 r3) 150, 0x28 (s3 r0) 44, 0x29 (s3 r1) 5 | 4 distinct LUTs = 4 banks |
| 4505 | 144 | **120/144** | 0x13+0x2b (r3, identical content) 12, 0x20 53, 0x28 55 | 24 misses = one texture (`748E0CE0`) still holding the **4445-era** bank 0x23 content; the 4505 line 0x23 differs and no flag is pending |
| 5168 | - | not gateable | - | state dump only, no `.pack` in capgate |
| 7279 | 134 | **134/134** | 0x20 87, 0x28 47 | |
| total | 518 | **494/518** | | |

The captured team is itself a same-character mirror: slots 0/3 PL34 (var 1/0), 1/2 PL2A (var 0/1), 4/5 PL2C (var 1/0),
and the two drawn fighters (slots 2 and 3) bind different bank ranges with different contents - the mirror case is
inside the gate.

The 4505 residual is the **LUT lag** (INFERRED mechanism, CONFIRMED effect): the flush refreshes the textures of the
*new* flip while the executing draws bind the other set, so a line rewritten mid-frame reaches the pixels one frame
(possibly two) later. Falsifier: consecutive-frame packs with a palette change between them (capgate has none;
its bursts are 9- or 3-frame steps).

### 1.2 TTD same-moment dump: staging rows vs the DatPal rows

`python d3dcap/replay/palette_gate.py --ttd d3dcap/ttd/runs/20260903-000941/pre` (blk.bin + dcram.bin dumped within
0.33 s; a different match, used for the structural rule only):

* staged row k == `dcram[DatPal + (node+0x39)*0x100 + k*0x20]` on **46/48** rows (6 fighters x 8). The two misses are
  PL2A rows 1-2 = the engine-authored lightning sub-palette rewrite already in the graph
  (`finding:gsta_storm_no_body_divergence`) -> the staging rows, not DatPal, are the truth.
* for **5/5** fighters with variant != 0, `DatPal+0` (what the tape ships) != the rendered row 0.

### 1.3 What the emulation harness would add

`emu_gate.py` cannot run this path on the capgate dumps: `FUN_1406146d0` reads DatPal in the DC-RAM host image (no
capture holds it) and `FUN_140048970` writes into `dev` (heap, not `blk`, not `ctx`). The TTD run does hold `dcram.bin`
and `blk.bin`, so `FUN_1406146d0(node, 0)` could be emulated there against its own staging lines; 1.2 already gates
that rule directly on the same bytes, so it was not run.

## 2. Layer assignment for the mirror symptom

| layer | test | result |
|---|---|---|
| wire / reader | does the shipped `pal` equal the rendered row 0? | NO for every non-default costume (1.2: 5/5). **Owner of the symptom.** |
| transpiled geometry / consumer | given the right rows, does the consumer pick the right row per part? | `row_of(sid, ri)` = `rec.flags >> 4` = the registration sub-row (`FUN_140612180`) - consistent; the LUT-locate fallback in `tape_to_seq` only worked when `pal` happened to be a real row |
| texture decode | - | not involved (index tiles are palette-independent; Path B M6) |
| flycast / D3D render | LUT == staging line | 494/518, residual = lag, not colour |

Falsification of "it is a mirror-only bug": a non-mirror match with one fighter on a non-default colour will render
that fighter in costume 0 with the v3/v4 tape (1.2 shows 5 such fighters, only 3 of them in mirrored pairs).

## 3. Steam <-> SH4 pairs added (seed 38)

| Steam | SH4 | what | tag |
|---|---|---|---|
| `FUN_1406146d0` | `loc_8c035162` | per-char palette staging, mode dispatch 0..0xA | CONFIRMED |
| `FUN_140614130` | `loc_8c035000` | row-0 source select (variant x 0x100 + extras) | CONFIRMED |
| `FUN_140612180` | `loc_8c033d78` | sheet registration incl. `palid = base + (flags>>4)` | CONFIRMED (palette part; was high) |
| `FUN_1406144f0` | `loc_8c03544c` | staging line copier | INFERRED (high) |
| `FUN_140613390` (palette loop) | bank1a `loc_8c1A8092` (VBlank PALETTE_RAM write) | upload | INFERRED |
| `FUN_140845e20` / `FUN_140845fe0` / `FUN_14004d350` / `FUN_140048970` | NaomiLib / host layer | read, no SH4 pair sought | CONFIRMED read |

Fields: DC `char+0x25` palid = Steam `node+0x39`; DC `char+0x164` Dat_Pal = Steam `node+0x1B8`; DC `char+0x12E` =
Steam `node+0x172` (bank base, seed 98). Globals: `blk+0x1040` staging lines, `DAT_140a6d188`, `dev+0xd8d04/0xd8500/
0xd8d00/0xd9d04`, `ctx+0x1e00a4`.

## 4. The tape delta (TAPE v5 `palrows`)

**What the tape must carry per slot per frame: the eight staging lines' colours (and flags).** They are engine-resolved
(variant, extras, runtime rewrites, pending dims), inside `blk`, at a fixed offset, no pointer chase:

```
blk + 0x1040 + (0x10 + 8*slot + row) * 0x38      row 0..7, slot 0..5
   = blk + 0x13C0 + slot*0x1C0 + row*0x38          one read of 0x540 B covers all six slots
      +0x08  u32 flag   (1 raw pending, 2 dim pending, 0 uploaded)
      +0x18  16 x u16 ARGB4444
```

Per-part row on the consumer = `rec.flags >> 4` (the atlas `row_of`), exactly the bank the slot table carries.
Interned through the existing `pals` table: 48 x u16 index + 48 x u8 flag = 148 B/frame before gzip (rows rarely change,
so it compresses to a few bytes per frame).

### 4.1 reader.rs (agent lane - diff block, NOT applied)

```diff
--- a/agent/src/reader.rs
+++ b/agent/src/reader.rs
@@ const H_DATPAL: usize = 0x1b8;
+// ── TAPE v5 (2026-09-03) PALETTE STAGING ROWS — docs/PALETTE-SOURCE-GHIDRA.md ──
+// ⭐ The palette a draw binds is NOT the fighter's DatPal: it is the bank the sheet registration
+// gave the part (slot base 0x10+8*slot + rec.flags>>4), whose colours the engine STAGES at
+// blk+0x1040+bank*0x38 (FUN_1406146d0 = loc_8c035162) and uploads per frame (FUN_140613390).
+// `pal` (read_pal(H+0x1B8)) is DatPal+0 = costume 0 row 0 — wrong for every non-default colour
+// (TTD gate 5/5) and the reason a same-character mirror renders both fighters alike.
+const PAL_STAGE_OFF:    usize = 0x13C0;  // blk + 0x1040 + 0x10*0x38: slot 0 row 0
+const PAL_STAGE_STRIDE: usize = 0x38;    // one line
+const PAL_STAGE_FLAG:   usize = 0x08;    // u32: 1 raw pending / 2 dim pending / 0 uploaded
+const PAL_STAGE_COLS:   usize = 0x18;    // 16 x u16 ARGB4444
+const PAL_STAGE_LEN:    usize = 6 * 8 * PAL_STAGE_STRIDE;   // 0x540: all six slots in one read
@@ struct GameState { ... objs: Vec<(u32, Vec<ObjNode>)>, ... }
+    /// TAPE v5: per captured frame, the 48 (slot*8+row) engine-resolved palette rows + flags.
+    palrows: Vec<(u32, [[u8; 32]; 48], [u8; 48])>,
@@ fn read_objs(...) — once per frame, right after the draw-list read (same blk, same instant):
+        if let Some(pb) = read_at(h, blk + PAL_STAGE_OFF, PAL_STAGE_LEN).filter(|b| b.len() >= PAL_STAGE_LEN) {
+            let mut rows = [[0u8; 32]; 48];
+            let mut flags = [0u8; 48];
+            for i in 0..48 {
+                let o = i * PAL_STAGE_STRIDE;
+                rows[i].copy_from_slice(&pb[o + PAL_STAGE_COLS..o + PAL_STAGE_COLS + 32]);
+                flags[i] = pb[o + PAL_STAGE_FLAG] & 3;
+            }
+            gs.palrows.push((frame, rows, flags));
+        }
@@ serialise (next to `nodes_raw` / `pal_tab` — reuse the SAME interning so `pals` stays one table):
+    // TAPE v5 `palrows`: [u32 frame][48 x u16 pal index (slot*8+row)][48 x u8 flag] = 148 B/frame
+    let palrows_raw: Vec<u8> = {
+        let mut b = Vec::new();
+        for (f, rows, flags) in &gs.palrows {
+            b.extend_from_slice(&f.to_le_bytes());
+            for r in rows.iter() {
+                let pi = match pal_tab.iter().position(|p| p == r) {
+                    Some(i) => i as u16,
+                    None if pal_tab.len() < 0xFFFE => { pal_tab.push(*r); (pal_tab.len() - 1) as u16 }
+                    None => 0xFFFF,
+                };
+                b.extend_from_slice(&pi.to_le_bytes());
+            }
+            b.extend_from_slice(flags);
+        }
+        b
+    };
+    let palrows_b64 = b64_encode(&gzip_bytes(&palrows_raw));
@@ JSON:
+        "palrows": palrows_b64, "palrows_frames": gs.palrows.len(), "palrows_stride": 148, "palrows_ver": 1,
+        "palrows_enc": "TAPE v5 -- gzip+base64 of per-frame [u32 frame][48 x u16 index into `pals` (slot*8+row: the engine-resolved 16-colour rows staged at blk+0x13C0+slot*0x1C0+row*0x38+0x18, FUN_1406146d0)][48 x u8 flag (blk line +8: 1 raw pending, 2 dim pending, 0 uploaded)]. Per-part row = rec.flags>>4. Supersedes `pal` (DatPal+0 = costume 0 row 0).",
```

Note `pals_raw` must be built AFTER `palrows_raw` (both push into `pal_tab`). Ordering of the reads: the staging
lines are read in the same pass as the draw list so rows and nodes describe one instant; the LUT lag (section 1.1)
is then a consumer choice (`--pal-lag`), not a wire ambiguity.

### 4.2 tape_to_seq.py (applied, palette code only)

* decodes `palrows` when present (`v3palrows[frame] = (48 x index, 48 x flag)`), old tapes untouched;
* each item carries `pslot` (fighter slot or object owner) and `pframe`;
* the sprite pass uses `v3pals[palrows[frame][pslot*8 + row_of(sid, ri)]]` when the key exists, else the v3/v4
  path (`pal` + LUT locate) unchanged;
* `--pal-lag N` (default 0) reads the rows of frame-N for the lag in 1.1 once it is gated.

## 5. Open / not proven

* Exact LUT lag (1 vs 2 frames) - UNKNOWN; needs consecutive-frame packs with a palette change (falsifier stated).
* The `+0x52D` writer (character-select colour assignment / forced-alternate rule) on Steam - UNKNOWN.
* The dim flag (2) is consumed at upload and then cleared, so a walk-time dump cannot see whether the live LUT is
  currently dimmed; the agent's read catches it only if it samples between the game logic and the render begin. The
  authoritative live source would be `dev+0xd8d04` (host PALETTE_RAM, 4 KB, pointer chase through `DAT_140acd3a8`) -
  not in any capture, not needed for the mirror fix.
* `FUN_14004d350`'s expansion was fixed by measurement (nibble*17, RGBA) not by reading the SIMD; a 1555/565 path exists
  for other `PAL_RAM_CTRL` modes and was not exercised.
