# reader-EDITS.md — RetroReceipts-agent 0.3.32 FULL EFFECT WIRE (verbatim find/replace)

Target repo: `RetroReceipts-agent` (a **non-isolated** session — this worktree can't build it).
All edits in `agent/src/reader.rs` unless noted. **Append-only** — older tapes (16/20 B objs) stay readable.
Apply as explicit find→replace (NOT a raw `git apply` patch — prior raw patches were corrupt).

Grows the objs record **20 B → 32 B**. The 12 appended bytes, in order:
`is_effect(1) blend(1) drawn(1) atimer(1) zy(u16) effect_key(u16) depth(f32)`.
Every field reads from the EXISTING `harvest_objs` `buf` (`CALIB_PREFIX_LEN`=0x1C0) — no extra per-node read;
`B` for the is_effect value-test is one read per FRAME (hoisted above the node loop).

Line numbers are orientation only (they drift) — match on the anchor text.

---

## 2a. Version bump — `agent/Cargo.toml` (line ~3)

FIND:
```
version = "0.3.31"  # 0.3.31 = TRAY MENU IS THE ONLY UI
```
REPLACE (keep the rest of the existing 0.3.31 comment tail after `PREVIOUS:`):
```
version = "0.3.32"  # 0.3.32 = FULL EFFECT WIRE (renderer lane). objs record 20B->32B, APPEND-ONLY: per-node is_effect (blk+0x6CE8 value-test) + blend (computeObjectBlend nibble) + drawn (H+0x170) + atimer (H+0x186) + scaleY zy (H+0x134 x4096) + effect_key (in-bank gfx low16) + depth (H+0x12C f32, DC node+0xE8, byte-exact z). Lets Path-A render bright additive supers/beams/the Inferno pillar; carries the discriminators to derive the ownerless-effect->atlas binding offline. Older tapes (16/20B) still decode. PREVIOUS:  # 0.3.31 = TRAY MENU IS THE ONLY UI
```
(Leave everything from `PREVIOUS:  # 0.3.31 = TRAY MENU IS THE ONLY UI` onward exactly as it already is.)

---

## 2b. New constants — in the H-offset const block, right after `H_GFX2` (line ~133)

FIND:
```rust
const H_GFX2:                usize = 0x1a4;     // Dat_GFX2 handle (DC +0x160, +0x44). the (GFX2,sel=sid) bank the
                                                //   sprite-class part-assembly path keys on; shipped alongside sid.
```
REPLACE:
```rust
const H_GFX2:                usize = 0x1a4;     // Dat_GFX2 handle (DC +0x160, +0x44). the (GFX2,sel=sid) bank the
                                                //   sprite-class part-assembly path keys on; shipped alongside sid.
// 0.3.32 FULL EFFECT WIRE — all read from the SAME 0x1C0 harvest_objs buffer (no extra per-node read).
const H_DEPTH:      usize = 0x12c;   // DC node+0xE8 (screen Z / 1-W numerator), +0x44 -> Steam 0x12C. f32.
                                     //   render-composite z-order (RENDER-ACCURACY-PROGRAM.md, sh4-re). Re-confirm at build.
const H_SCALE_Y:    usize = 0x134;   // per-object magnifier Y (f32), pairs with H_SCALE_X 0x130.
// is_effect value-test (fxprobe.py, CONFIRMED-live mechanism): B=*(u32)(blk+0x6CE8); a node is an
// effect iff some word in H+0x180..0x1BC masked &0x1FFFFFFF lands in [B, B+0x10000). Per the 0.3.29
// note this primarily catches 3D-class (cat 5-13) effects; sprite-class (cat 1-4, e.g. Inferno) usually
// read 0 (Steam handle is not a 0x0CED ptr) -- gfx1/effect_key still carry the discriminator.
const GFX_B_OFF:    usize = 0x6ce8;  // blk-rel: B = *(u32)(blk+this)             (fxprobe.py / spec §3)
const FX_BANK_WIN:  usize = 0x10000; // [B, B+win)                                 (fxprobe.py)
const H_FX_SCAN_LO: usize = 0x180;   // node gfx-key scan window start
const H_FX_SCAN_HI: usize = 0x1bc;   // last u32 wholly inside the 0x1C0 buffer (0x1bc+4=0x1c0)
```

---

## 2c. `ObjNode` struct — add fields (line ~1277)

FIND:
```rust
#[derive(Clone)]
struct ObjNode { sid: u16, sx: i16, sy: i16, zx: u16, face: u8, cat: u8, owner: u8, layer: u8,
                 // 0.3.29: the effect graphics-bank handles the renderer resolves the atlas from. Sprite-class
                 // (cat 1-4) render like a body via the (GFX2, sel=sid) part-assembly, so BOTH the bank handle
                 // and sid are needed — sid alone is ambiguous (effect sids overlap the body sid space).
                 gfx1: u32,   // Dat_GFX1 handle (H+0x1A0) — clusters by effect type
                 gfx2: u32 }  // Dat_GFX2 handle (H+0x1A4) — the part-assembly bank
```
REPLACE:
```rust
#[derive(Clone)]
struct ObjNode { sid: u16, sx: i16, sy: i16, zx: u16, face: u8, cat: u8, owner: u8, layer: u8,
                 // 0.3.29: the effect graphics-bank handles the renderer resolves the atlas from. Sprite-class
                 // (cat 1-4) render like a body via the (GFX2, sel=sid) part-assembly, so BOTH the bank handle
                 // and sid are needed — sid alone is ambiguous (effect sids overlap the body sid space).
                 gfx1: u32,   // Dat_GFX1 handle (H+0x1A0) — clusters by effect type
                 gfx2: u32,   // Dat_GFX2 handle (H+0x1A4) — the part-assembly bank
                 // 0.3.32 FULL EFFECT WIRE (append-only):
                 is_effect: u8,   // blk+0x6CE8 value-test (3D-class); feeds computeObjectBlend
                 blend: u8,       // sprite-gpu blend NIBBLE {0x00 opaque, 0x45 alpha, 0x11 additive}
                 drawn: u8,       // H+0x170 (draw gate) — 1 for every emitted node; honors future relax
                 atimer: u8,      // H+0x186 anim-cell countdown
                 zy: u16,         // scaleY x4096 (H+0x134)
                 effect_key: u16, // low-16 of the in-bank gfx word (else gfx1&0xffff)
                 depth: f32 }     // H+0x12C (DC node+0xE8) byte-exact z
```

---

## 2d. `harvest_objs` — read B once + compute/push new fields (line ~1699)

### hunk 1 — hoist B above the layer loop

FIND:
```rust
    let rd_u64 = |buf: &[u8], o: usize| -> u64 {
        u64::from_le_bytes([buf[o], buf[o+1], buf[o+2], buf[o+3], buf[o+4], buf[o+5], buf[o+6], buf[o+7]]) };
    for l in 0..N_LAYERS {
```
REPLACE:
```rust
    let rd_u64 = |buf: &[u8], o: usize| -> u64 {
        u64::from_le_bytes([buf[o], buf[o+1], buf[o+2], buf[o+3], buf[o+4], buf[o+5], buf[o+6], buf[o+7]]) };
    // 0.3.32: effect-bank base for the per-node is_effect value-test (fxprobe.py). One read per frame.
    let fx_b: u32 = read_at(h, blk + GFX_B_OFF, 4).filter(|b| b.len() >= 4).map(|b| le32(&b, 0)).unwrap_or(0);
    for l in 0..N_LAYERS {
```

### hunk 2 — compute + push (the `out.push` block)

FIND:
```rust
            // 0.3.29 owner (CONFIRMED live fxprobe): u64 @ H+0x28 == the owning fighter's H-base; 0xFF = ownerless global.
            let ow = rd_u64(&buf, H_OBJ_OWNER) as usize;
            let owner = fighters.iter().position(|&f| f == ow).map(|p| p as u8).unwrap_or(0xFF);
            out.push(ObjNode {
                sid,
                sx: lef32(&buf, H_SCREEN_X).round().clamp(-32768.0, 32767.0) as i16,
                sy: lef32(&buf, H_SCREEN_Y).round().clamp(-32768.0, 32767.0) as i16,
                zx: (lef32(&buf, H_SCALE_X).clamp(0.0, 15.999) * 4096.0) as u16,   // scale ×4096 (decode ÷4096, NOT ÷16)
                face: buf[H_FACING], cat: buf[H_CATEGORY], owner, layer: l as u8,
                gfx1: le32(&buf, H_GFX1),                                     // Dat_GFX1 handle (H+0x1A0)
                gfx2: le32(&buf, H_GFX2),                                     // Dat_GFX2 handle (H+0x1A4)
            });
```
REPLACE:
```rust
            // 0.3.29 owner (CONFIRMED live fxprobe): u64 @ H+0x28 == the owning fighter's H-base; 0xFF = ownerless global.
            let ow = rd_u64(&buf, H_OBJ_OWNER) as usize;
            let owner = fighters.iter().position(|&f| f == ow).map(|p| p as u8).unwrap_or(0xFF);
            // 0.3.32 is_effect + effect_key: scan H+0x180..0x1BC for a word landing in [B, B+0x10000).
            let mut is_effect: u8 = 0;
            let mut effect_key: u16 = (le32(&buf, H_GFX1) & 0xffff) as u16;   // fallback discriminator
            if fx_b != 0 {
                let mut o = H_FX_SCAN_LO;
                while o <= H_FX_SCAN_HI {
                    let w = le32(&buf, o) & 0x1FFF_FFFF;
                    if w >= fx_b && w < fx_b.wrapping_add(FX_BANK_WIN as u32) {
                        is_effect = 1;
                        effect_key = (w & 0xffff) as u16;   // DC-style dir key low-16 for _resolveFxSprite
                        break;
                    }
                    o += 4;
                }
            }
            // 0.3.32 per-object blend (port of maplecast computeObjectBlend) -> the sprite-gpu NIBBLE the
            // tape-adapter/sprite-gpu consume directly (0x11 additive / 0x45 alpha / 0x00 opaque).
            let list_type: u8 = if is_effect != 0 { 2 }
                else { match buf[H_CATEGORY] { 0x05|0x06|0x0B|0x0C|0x0D|0x01 => 0, _ => 1 } };
            let blend: u8 = match list_type { 2 => 0x11, 1 => 0x45, _ => 0x00 };
            out.push(ObjNode {
                sid,
                sx: lef32(&buf, H_SCREEN_X).round().clamp(-32768.0, 32767.0) as i16,
                sy: lef32(&buf, H_SCREEN_Y).round().clamp(-32768.0, 32767.0) as i16,
                zx: (lef32(&buf, H_SCALE_X).clamp(0.0, 15.999) * 4096.0) as u16,   // scale ×4096 (decode ÷4096, NOT ÷16)
                face: buf[H_FACING], cat: buf[H_CATEGORY], owner, layer: l as u8,
                gfx1: le32(&buf, H_GFX1),                                     // Dat_GFX1 handle (H+0x1A0)
                gfx2: le32(&buf, H_GFX2),                                     // Dat_GFX2 handle (H+0x1A4)
                // 0.3.32 FULL EFFECT WIRE:
                is_effect, blend, drawn: buf[H_DRAWN], atimer: buf[H_ANIM_TMR],
                zy: (lef32(&buf, H_SCALE_Y).clamp(0.0, 15.999) * 4096.0) as u16,
                effect_key,
                depth: lef32(&buf, H_DEPTH),
            });
```
(`H_DRAWN`=0x170 and `H_ANIM_TMR`=0x186 already exist; `le32`/`lef32` already exist.)

---

## 2e. Serialize — grow the record 20 B → 32 B (line ~2110)

FIND:
```rust
            for nd in nodes.iter().take(n) {
                b.extend_from_slice(&nd.sid.to_le_bytes());
                b.extend_from_slice(&nd.sx.to_le_bytes());
                b.extend_from_slice(&nd.sy.to_le_bytes());
                b.extend_from_slice(&nd.zx.to_le_bytes());
                b.push(nd.face); b.push(nd.cat); b.push(nd.owner); b.push(nd.layer);
                b.extend_from_slice(&nd.gfx1.to_le_bytes());   // 0.3.29: Dat_GFX1 handle (H+0x1A0)
                b.extend_from_slice(&nd.gfx2.to_le_bytes());   // 0.3.29: Dat_GFX2 handle (H+0x1A4)
            }
```
REPLACE:
```rust
            for nd in nodes.iter().take(n) {
                b.extend_from_slice(&nd.sid.to_le_bytes());
                b.extend_from_slice(&nd.sx.to_le_bytes());
                b.extend_from_slice(&nd.sy.to_le_bytes());
                b.extend_from_slice(&nd.zx.to_le_bytes());
                b.push(nd.face); b.push(nd.cat); b.push(nd.owner); b.push(nd.layer);
                b.extend_from_slice(&nd.gfx1.to_le_bytes());   // 0.3.29: Dat_GFX1 handle (H+0x1A0)
                b.extend_from_slice(&nd.gfx2.to_le_bytes());   // 0.3.29: Dat_GFX2 handle (H+0x1A4)
                // 0.3.32 FULL EFFECT WIRE (append-only, 12 B):
                b.push(nd.is_effect); b.push(nd.blend); b.push(nd.drawn); b.push(nd.atimer);
                b.extend_from_slice(&nd.zy.to_le_bytes());
                b.extend_from_slice(&nd.effect_key.to_le_bytes());
                b.extend_from_slice(&nd.depth.to_le_bytes());
            }
```

---

## 2f. `objs_enc` descriptor string (line ~2179)

FIND (one line):
```rust
        "objs_enc": "gzip+base64 of per-frame [u32 frame, u16 count, count x 20B {u16 sid, i16 sx, i16 sy, u16 zx(scale x4096; decode /4096), u8 face, u8 cat(render/blend class), u8 owner(slot|0xFF), u8 layer, u32 gfx1(H+0x1A0 Dat_GFX1 handle), u32 gfx2(H+0x1A4 Dat_GFX2 handle)}]",
```
REPLACE (one line):
```rust
        "objs_enc": "gzip+base64 of per-frame [u32 frame, u16 count, count x 32B {u16 sid, i16 sx, i16 sy, u16 zx(scaleX x4096; /4096), u8 face, u8 cat(render/blend class), u8 owner(slot|0xFF), u8 layer, u32 gfx1(H+0x1A0), u32 gfx2(H+0x1A4), u8 is_effect(blk+0x6CE8 value-test; 3D-class), u8 blend(sprite-gpu nibble 0x11 add/0x45 alpha/0x00 opaque, computeObjectBlend), u8 drawn(H+0x170!=0), u8 atimer(H+0x186), u16 zy(scaleY x4096, H+0x134), u16 effect_key(in-bank gfx low16 else gfx1&0xffff), f32 depth(H+0x12C=DC node+0xE8)}]",
```
The `32B` + `is_effect` tokens in this string are what the converter (`tape_to_gpujson.py`) and
the browser adapter (`detectObjRecBytes`) key the record-size detection on — do not drop them.

---

## Encoding note (why `blend` is the sprite-gpu NIBBLE, not list-type 0/1/2)

`tape-adapter.mjs effectBlendByte` passes `o.blend` straight through, and the draw builders test
`(blend & 0x0f) === 1` for additive. Shipping the **nibble** (`0x11/0x45/0x00`) means the JS blend
decode needs **zero** change (the doc's "no further render change" contract). 2d maps
computeObjectBlend's list-type -> nibble before shipping.

## What the render side already consumes (no further JS change needed)
- `tape_to_gpujson.py decode_objs`: detects 32 B, emits `[…,gfx2,blend,is_effect,drawn,zy,effect_key,depth]`. **DONE (this worktree).**
- `tape-adapter.mjs`: `detectObjRecBytes` (32 B), `decodeObjsBytes` (12 B tail), `fromJsonObject` ([10..15]), `applyFrame` (real effect_key/engZ + is_effect→FX_CID). **DONE (this worktree).**
- `sprite-client.mjs` `_emitEffectQuad`/`_resolveFxSprite`/`FX_CID`: already keyed on `effect_key`/`blend`/`engZ`. **No change.**

## ⚠ Route to mvc2-sh4-re-expert at build (flagged, not guessed)
1. Re-confirm Steam **H+0x12C = DC node+0xE8** depth (doc-cited; worth one live read).
2. The `blk+0x6CE8` value-test catches 3D-class only per the 0.3.29 note — for sprite-class effects
   is_effect reads 0; brightness for those rides on `blend`(computeObjectBlend) + the FX-atlas/effect_key
   binding derived offline from the `calib` blob. This is expected, not a bug.
3. Live PALETTE base handle: **H+0x1B8** (rr-sprite-render-pipeline) vs **H+0x1A8** (objs reader note = Dat_Pal)
   — reconcile before any reader-side palette deref (not needed for this wire; flagged for the bakes).
