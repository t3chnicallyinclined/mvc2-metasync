# HUD portrait / name-plate pages (TCW 0xC9A..0xCA5) — CLOSED 2026-09-04

Method: `docs/RE-METHOD.md`. Step 1–3 (port the SH4 annotations by function matching; seed with unique
constants; translate globals through the block map), then a numeric gate. This file closes
`RENDER-STATUS-2026-09-03.md` open tweak **#4 "Portraits — TCW 0xC99..0xCA8 patched at runtime from
character DATs (INFERRED); capture-derived for now"** and `TEXTURE-BANKS-GHIDRA.md` §8.4
("Character-DAT derivation of 0xC99..0xCA8: INFERRED, not gated").

## 0. The bug it fixes

Tape `76561197999665347_76561198047120675_76561198047120675_59616461` (agent 0.3.50, stage 10,
`p1_team [42,44,50]` = Storm/Magneto/Colossus, `p2_team [42,44,8]` = Storm/Magneto/Psylocke) rendered
with **Sentinel's portrait and name plate** in the in-picture HUD. Sentinel (cid 52) is in neither team.

Mechanism (CONFIRMED, code + pixels, no game state needed):

* The tape carries **no `pages`** (only synthetic tapes do). Every world texture therefore resolves by
  TCW key through `rr-render/src/world.rs emit_world` -> `ws.tape_pages` -> `assets.lib_pages`, the
  **capture-derived** library `d3dcap/replay/tcw_pages/index.json` (`pack.rs world_assets`;
  `tape_to_seq.py` main's `tape_pages` / `wt.pages` lookup).
* Twelve of those keys — `0xC9A..0xCA5` — are **not bank pixels at all**. HUD TEX records 9..24 have
  `loc >= 0x1E000` in a 0x1E000-byte file (`TEXTURE-BANKS-GHIDRA.md` §6): the engine rewrites them at
  every match load from the SIX FIGHTERS' OWN character DATs. The library's copies are whatever roster
  the D3D capture happened to contain.
* Measured: the library's bare keys decode to **`0xC9A` = SENTINEL, `0xC9B` = STORM, `0xC9C` = MAGNETO,
  `0xC9D` = STORM, `0xC9E` = SENTINEL, `0xC9F` = MAGNETO** and name plates `0xCA0..0xCA5` =
  SENTINEL/STORM/MAGNETO/STORM/SENTINEL/MAGNETO. So **every tape rendered that capture's roster**, which
  is exactly the reported symptom, and why the picture "does not swap when players tag": the twelve slots
  are all resident every frame and the tape selects among them correctly (verified below) — only the
  pixels were frozen to a foreign roster.
* Verified on the tape: list-11 binds `0xC9A..0xC9F` + `0xCA0..0xCA5` on 3,688–8,294 of 8,302 frames each,
  and slot pages drop out and return exactly when a character dies / the round restarts (e.g. `0xC9B` and
  `0xCA1` vanish together at clock 2487 and return at 4906). **The tape's selection was never wrong.**

Not an index/base-arithmetic error, and not the DOM overlay: `overlay.meta` and `p1_team`/`p2_team` are
correct end to end.

## 1. The writers (CONFIRMED — both sides read)

`FUN_14060d560` (Steam) == `loc_8c032696` (SH4 bank03), the HUD bank loader, decompiled in full:

```
FUN_14060d8f0(PTR_DAT_142edf598, 0xd082000)                    // HUD POL/TEX rebase (AFS 835/836)
for s in 0..6:                                                  // uVar11 += 0x738 while < 0x2b50
    lVar8 = DAT_142edf560 + s*0x738                             // DAT_142edf560 = blk
    data  = *(u32**)(lVar8 + 0x3fb0)                            // = fighter+0x1F8, the char HUD file
    j     = 0                                                   // (G+0x29 != 0 -> 3 for a few cids)
    FUN_140611e90(data + data[j], dcram + 0xE60000)             // 16-bit LZSS -> 0x0CE60000
    k = DAT_140a6aac8[s]                                        // {0,3,1,4,2,5}
    memcpy(texHdr[10+k].loc, dcram + (DAT_140a6aac4[*(u8*)(lVar8+0x440d)] + 0x1CC0)*0x800, 0x800)
    memcpy(texHdr[16+k].loc, dcram + 0xE61000,                                             0x800)
FUN_1408458a0(0xc90); for each model: FUN_140844dc0(model, texHdrs)   // publish TCW = 0xC90 + record
```

* `texHdr` = `*(PTR_DAT_142edf598 + 0xb08)`, 16-byte records, `loc` at +8, so the decompiled expressions
  `lVar2 + 0xa8 + k*0x10` and `lVar2 + 0x108 + k*0x10` are **records 10+k and 16+k** (0xa8 = 10*0x10+8).
* TCW = 0xC90 + record => **portrait = 0xC9A + k, name plate = 0xCA0 + k**.
* Records 10..21 read out of AFS 835: `32x32, fmt 1 (RGB565), type 1 (twiddled)` — read, not assumed.
* `DAT_140a6aac8 = {0,3,1,4,2,5}` and `DAT_140a6aac4 = {1,0,3,0}` — **read out of `mvc_dump.bin`**
  (file offset = addr − 0x140000000), not quoted from an earlier doc.
* Slot order is EVEN = P1 / ODD = P2, team position = s/2. CONFIRMED three ways: the select routine at
  `0x14062a460` computes its slot as `imul rax, (side[+0x6b0] & 1) + pos[+0x32]*2, 0x738`;
  `legacy/src-tauri/src/sync.rs` `p1_team_cid = [cid(0), cid(2), cid(4)]`; `rr-render/src/web.rs`
  skin routing. Also `0x14060f85a: lea rdx,[rax + 0x3db8]` re-confirms the fighter-slot base
  `blk + 0x3DB8 + i*0x738` (`rr-steam-object-base-fix`).

=> **P1 team i -> portrait 0xC9A+i, name 0xCA0+i; P2 team i -> portrait 0xC9D+i, name 0xCA3+i.**

Two more slots of the SAME file (CONFIRMED, decompiled, ripped, **not yet bound** — see §5):
* `FUN_1406162e0(fighter)`: `FUN_140611e90(file + file[1], 0x0CE60000)`, `FUN_140845830(0xc99, ...)`
  -> TCW **0xC99**, 256x256 fmt 1 type 3 (VQ) = the character's large "win/super" artwork.
* `FUN_140616330(fighter)`: `FUN_140611e90(file + file[2], ...)`,
  `FUN_140845830((*(u8*)(fighter+0x230)>>1) + 0xca6, ...)` -> TCW **0xCA6..0xCA8**, 128x128 fmt 1 type 3.

## 2. The source file (CONFIRMED)

`fighter+0x1F8` is loaded at the VS screen by `FUN_14060c370` case 6 (SH4 `loc_8c032cbe`):
`FUN_14060dcf0(DAT_140a6d190[cid], base+0x148000)`. `DAT_140a6d190` is a **u16** table read from the exe:
`[cid] = 3 + cid` for every cid, with **cids 25/26 collapsed onto entry 27**; 59 entries then zeros.
(`RECEIPT-RUNNER-DCRAM.md` already gated all eleven per-character files 66/66 byte-exact against the live
DC-RAM image, so the file identity is not in doubt.)

Layout of AFS entry `3+cid`: `u32 off[3]` then three LZSS blobs.
`off[0]` -> four 0x800-B 32x32 RGB565 twiddled pages, `off[1]` -> the 0xC99 VQ page, `off[2]` -> the 0xCA6 VQ page.

`FUN_140611e90` is a **16-bit LZSS**, ported verbatim into `rip_portraits.lzss16`:
a control word supplies 16 flags MSB-first; flag 0 = literal word; flag 1 = a match word `w` with
`count = w>>11`, `offset = w & 0x7FF`, and when `count == 0` the NEXT word is the count and `w` itself is
the offset; `offset == 0` means write `count` zero words, and `offset == 0 && count == 0` ends the stream.
Offsets and counts are in 16-bit WORDS into the output. (Gate: the three blobs decompress to exactly
0x2000 / 0x4800 / 0x1800 bytes = the sizes the three record shapes need, on every character.)

## 3. Which of the four pages is the portrait: `*(fighter+0x655)` = the ASSIST TYPE

`DAT_140a6aac4[*(u8*)(fighter+0x655)]` picks the page, table `{1,0,3,0}`. Pages 0/1/3 are the same face on
a green / red / blue field (200–280 of 1024 texels differ between them — a whole colour variant, not just a
border); page 2 is the NAME PLATE and is fixed.

`+0x655` is written at CHARACTER SELECT by the routine at `0x14062a460`:
`mov byte [rsi+0x440d], r8b` with `r8d = rand() % 3` on the random-select path (`call 0x14060f990`, the
`0xaaaaaaab` reciprocal), and `(prev ± 1 + 3) % 3` on the A1 (`0x2000`) / A2 (`0x1000`) button paths tested
at `[base + slot*2 + 0x33a68]` — i.e. **alpha / beta / gamma**. It is carried between slots on a rematch by
the routine at `0x14060f450` alongside cid (`+0x6C0`), costume (`+0x6C1`) and `+0x6F0`.

The agent already ships it: `RetroReceipts-agent/agent/src/harvest.rs` `OFF_ASSIST = 0x4E9` off the
pre-fix base, and `0x4E9 + 0x16C = 0x655` — the **same byte**. So the tape's `assist[slot]` IS
`*(fighter+0x655)`, and the whole rule is resolvable from the tape with **zero free parameters**:

```
slot s:  cid = (s even ? p1_team : p2_team)[s/2]     a = assist[s]     k = {0,3,1,4,2,5}[s]
portrait  TCW 0xC9A + k  <-  character-DAT page {1,0,3,0}[a]
name      TCW 0xCA0 + k  <-  character-DAT page 2
```

## 4. Gate

`python d3dcap/replay/rip_portraits.py --gate`:
**29/29** — every 0xC9A..0xCA5 entry in the capture-derived library (up to four content variants per key,
from several capture sessions) is reproduced **byte-exact** by decompressing AFS `3+cid` and taking the page
the rule names, for cids 42/44/50/52/23/53. 0 contradictions. That is the first numeric gate on the
character-DAT derivation and it also validates the LZSS port, the AFS index table and the page layout.

Emitter gates after the fix:
* `rr-render/tools/gate_l1.sh` (MODE=full): **5/5 PASS**, draws exact 24574, 17969, 21061, 24481, 2588 —
  Rust and the Python oracle agree byte-for-byte with the new rule on both sides.
* `gate_l3.mjs` on the affected tape (stage 10, rows 200..229): **30/30 frames byte-exact**, browser wasm
  tape path vs the Python `.seq`.
* `gate_seek.mjs` on the same clip, both the `.seq` path and the wasm `tape` path: **3/3 frames byte-equal**
  to the sequential render, and the two paths produce the SAME three scene hashes
  (`e8b99e5add99` / `39f90cdbb017` / `4a017f4d6911`) — a third, pixel-level confirmation that Rust and the
  Python oracle agree. NOTE: `gate_seek.mjs`'s header usage is stale — the URL needs **`&auto=1`** or the
  player never sets `window.__rr.ready` and the gate times out at 300 s (pre-existing, unrelated).
* Emitted textures on the affected tape now read STORM / MAGNETO / COLOSSUS (0xC9A/B/C) and
  STORM / MAGNETO / PSYLOCKE (0xC9D/E/F) with matching name plates. No Sentinel.
* Falsification arm: pristine `git HEAD` `emit_seq` vs the patched Python oracle on the same 6 frames =
  **150 `tex[0]` mismatches**; patched Rust vs patched Python = **0**.

### Deliberate re-baseline (scene hashes change, and should)
Every previously rendered tape had 6–12 of the twelve HUD pages wrong. For the four L1 gate tapes:

| tape | roster | HUD pages changed |
|---|---|---|
| 59613662 (stage 13) | P1 52,44,8 / P2 42,44,50 | 8 of 12 (slot 0 Sentinel was accidentally right — the library came from a capture whose slot 0 was Sentinel) |
| 59613506 (stage 11) | P1 42,44,50 / P2 42,44,8 | 10 of 12 |
| 59614009 (stage 13) | P1 42,44,50 / P2 42,44,8 | 10 of 12 |
| 59612784 (stage 0)  | P1 42,44,50 / P2 52,42,56 | 12 of 12 |

Any stored scene-RT hash for a frame that draws list 11 is invalidated on purpose. The L1/L3 gates compare
Rust against Python (both carrying the rule), so they stay green.

## 5. Open

1. **TCW 0xC99 and 0xCA6..0xCA8 are still unbound.** The pages are now rippable per cid
   (`rip_portraits.py --big`), but the slot is GLOBAL and re-uploaded on a character switch by
   `FUN_1406162e0` / `FUN_140616330`, so "whose art is in it this frame" is stateful across both sides.
   0xC99 appears on 476 of 8,302 frames of the reference tape; today the emitter logs `no page for 00000C99`
   and drops the draw (missing, never wrong). Deriving the owner from `drawn[6]` is INFERRED, not gated.
2. The `G+0x29 != 0` branch of `FUN_14060d560` uses sub-blob **3** for cids {16,28,30,31,33,38,58}
   (bitmasks `0xd0010000` / `0x4000042`). Not reproduced; the `off[3]` word is not a valid offset in the
   entries checked, so the branch is probably a different (non-battle) mode. UNKNOWN.
3. Tapes older than agent 0.3.28 carry no `assist`; the rule then defaults to `a = 0` -> page 1 (alpha).
   Name plates are unaffected.
4. **Unrelated, pre-existing, reported not fixed:** on stage 0x0A, 30 deck draws per 6 frames
   (`world_00000C10`) differ Rust-vs-Python in the vertex BLUE byte by exactly −64. Present at
   `git HEAD` before this change and absent from all four L1 gate tapes. Owner: the deck-emission lane.

## 6. Address index

| symbol | meaning |
|---|---|
| `FUN_14060d560` | HUD bank load + the twelve portrait/name uploads (== `loc_8c032696`) |
| `FUN_140611e90` | 16-bit LZSS decompressor |
| `FUN_1406162e0` / `FUN_140616330` | 0xC99 / 0xCA6+ re-upload on a character switch |
| `FUN_14060dcf0` | AFS entry -> DC address loader |
| `FUN_14060c370` case 6 | loads `fighter+0x1F8` (== SH4 `loc_8c032cbe`) |
| `0x14062a460` | character-select routine that writes `+0x655` (assist type) |
| `0x14060f450` | rematch/slot shuffle: copies `+0x6C0` cid, `+0x655`, `+0x6C1` costume, `+0x6F0` |
| `DAT_140a6aac4` | `{1,0,3,0}` assist type -> DAT page |
| `DAT_140a6aac8` | `{0,3,1,4,2,5}` fighter slot -> HUD record offset |
| `DAT_140a6d190` | u16 `[cid] = 3 + cid` (25/26 -> 27), the character HUD/portrait AFS entry |
| `DAT_142edf560` | `blk`; fighter slot base `blk + 0x3DB8 + s*0x738` |
| `PTR_DAT_142edf598` | HUD/common model bank; `+0xb08` = the texture-header array |
