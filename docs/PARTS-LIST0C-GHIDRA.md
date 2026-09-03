# List 0xC "part" nodes = the COMBO COUNTER (Ghidra read-set + gate, 2026-09-03)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, base 0x140000000, Ghidra `dumpproj`, GhidraMCP bridge :8080).
SH4 side: marvelous2 `_marv_re/build/bank0f.asm`. `blk` = `DAT_142edf560`, `G` = `DAT_142edf580` = `blk+0x3CB8`,
`ctx` = `DAT_142ef0ab0`. Tags: **CONFIRMED** = decompiled/disassembled and read (both sides where a pair is
claimed) or reproduced by the gate; **INFERRED** = derived, not read; **UNKNOWN** = not located.
Tools: `d3dcap/replay/rip_parts.py` (bank models + static lists -> `tcw_pages/parts/`, gitignored),
`d3dcap/replay/parts_gate.py` (the gate), `blkstate.pnodes()` (list-12 walker on a captured block).
Seed: `maplecast-flycast/tools/re_kb/107_list0c_parts.surql`.

RE METHOD steps used: (1) `loc_8c030dcc` -> `FUN_140620ea0` was already CONFIRMED (seed 30); its callee
`jsr 8c0f215e` / `FUN_140653a70` is the new pair, matched by structure and the unique float -6.0
(`0xC0C00000` in both pools); (2) seeds propagated to the callee set (translate/scale/store/draw/header-patch);
(3) the DC node offsets translate to Steam through the per-field deltas listed in section 6; (4) every pair is
tagged and stored in seed 37, and the rule is gated bit-for-bit on five captured frames (section 7).

## 0. Answer

* **List 0xC is not hit sparks.** The two nodes `FUN_1406539a0(slot)` allocates (one per point-character
  slot 0/1) are the **COMBO HIT COUNTER** ("`%3d` HITS" and, when a combo ends, the rating word plus an
  8-digit hex points line). `FUN_140652cc0` sprintf's the i16 at `node+0x172` with `"%3d"` into
  `node+0x228..0x22A` (char - '0'; a space becomes -16 = blank) and points `node+0x110` at the static part
  list `DAT_140a7a2f0`. Two other allocators put text on the same list: `FUN_14073dfb0` (round/intro text,
  lists `PTR_LAB_140a987f0[state]`) and `FUN_1407ec920` (results-screen time lines, lists `DAT_140aac980[k]`).
  Hit sparks are System-B sprite objects (the tape's `objs`/`nodes`), not list-0xC nodes; whatever drops
  them on real-match tapes is a different owner and is NOT diagnosed here (section 9).
* **Node -> model rule (CONFIRMED, `FUN_140653a70`):** the node carries no object and no matrix input; its
  render inputs are `+0x110` (part list, exe-static), `+0x118` (second-line list), `+0x50` (position),
  `+0x80` (second-line x), `+0x228..0x237` (16 x i8 digit/model indices), `+0x170` (drawn). Each 8-B list
  entry `{i8 count, i8 flags, i8 scaleIdx, i8 modelIdx, f32 xoff}` selects **model
  `PTR_DAT_142edf598[modelIdx]`** (the HUD/common bank, TCW base 0xC90, AFS 835/836) when `flags < 0`, else
  **model `node[0x228 + k]`** (k-th non-fixed entry; negative = nothing drawn, the x advance still applies).
  Before the draw `FUN_14060d8d0(model, count-1)` overwrites the model's record headers (PCW/ISP/TSP/TCW) with
  `DAT_142eed370[count-1]` = the first-record header of HUD models 0..3, i.e. **texture page 0xC92 + count - 1**.
* **Transform (CONFIRMED; no CPU vertex transform):** `W = T(node+0x50)`, then per entry
  `W = T(xoff,0,0) x W` and, if `scaleIdx`, `W = S(SCALE[scaleIdx & 7]) x W` (row-vector, pre-multiplied,
  cumulative across entries -- later x advances are scaled by earlier scales); pass 2 restarts from
  `T(node+0x50)` with `T(node+0x80, -6, 0)` and walks `+0x118`. The draw is `FUN_1408499e0` (kind 0/2):
  D3D receives **P = `FUN_14061d5b0` (angle 0x4000, far 12000), V = I, CBWorld = W**, colour (1,1,1),
  alpha 1.0, and the model vertices verbatim except that `FUN_1408482a0` clears bit 0 of the x word and of the
  v word. The "z = -71 view-space" identity-CBWorld draws in the earlier note are list-0xB HUD objects (339 on
  frame 4445), not parts.
* **Why the tape has none of it:** `harvest_anodes` requires `+0xA0 != 0 || +0xE8 != 0`; both are 0 on every
  list-12 node (CONFIRMED in all three allocators). Section 5 gives the harvest delta (a separate 44-B
  `pnodes` record).
* **Gate (section 7):** frames 4445 / 4447 / 4474 / 7441 / 26380 -- derived CBWorld bit-exact **24/24**, model
  group positions **82/82**, uvs **82/82**, texture pages byte-exact **82/82**, unexplained z=-40 HUD-camera
  draws **0**.

## 1. Lifetime and owner (CONFIRMED)

| routine | what | where |
|---|---|---|
| `FUN_140653970` | `if G+0x14 != 0x40: FUN_1406539a0(0); FUN_1406539a0(1)` | callers `FUN_140620670`, `FUN_140626c20`, `FUN_1406277b0`, `FUN_140627390`, `FUN_14073d490` (match / mode inits; not traced further) |
| `FUN_1406539a0(slot)` | `FUN_14061dbe0(0, 0xC, 1)` (append to list 12); `+0x170 = 1`; `+0x18 = LAB_140653940`; `+0xA0 = 0`; `+0xF0 = 0`; `+0x50..58 = DAT_140a7a280[slot]` = (-40, 5, -40) / (40, 5, -40); `+2 = slot`; `+0x6C..74 = (1.5, 1.5, 1)` (unused by the draw); `+0x28 = blk+0x3DB8+slot*0x738` (fighter); `+1 = fighter+1`; `+0x228..0x237 = 0` | one node per point slot |
| `LAB_140653940` (node callback, undefined in Ghidra; capstone) | `+0x100 = *(blk + 0x32500 + slot*0x18)` (per-slot record), then `jmp switchdata[node+4]` -- the state machine: `caseD_c/e/f/10/11` (0x140652e40.., 0x140652f40..), `FUN_1406535f0`, `FUN_140652b30/b80/bf0` | runs from `FUN_14061e520(0xC)` (list callback pass) |
| `switchD_140653969::caseD_e` (combo running) | eases `+0x50.x` toward `+0x8C` (`fVar2 = (0x8C - 0x50) * DAT_14092792c`, clamped by `DAT_14097eb40` / `_DAT_14097f1ac`); `+0x172 = *(i16*)(blk + 0x3254E + slot*2)` (the engine's per-slot combo count) unless < 2; `FUN_140652cc0` (format); after 0x1E frames with `blk+0x324e0 == 5`: `+0x110 = +0x118 = 0`, state `+0x34 = 5` | the "N HITS" display |
| `caseD_10` (combo ended) | `+0x180 = rating index` from the count (`<3 -> hide; 3 -> 0xD; 4,5 -> 4; 6,7 -> 5; 8,9 -> 6; 10..29 -> 7; 30..49 -> 8; 50..99 -> 0xE; >=100 -> 9`; alternative 0xA/0xB when `+0x174 & 1` and fighter `+0x33c & 1`), `+0x34 = 3`, digits = `"%8x"` of `*(u32*)(blk + 0x3256C + fighterSlot*4)` (points), then `FUN_140652c50` | rating word + points line |
| `FUN_140652c50` | `+0x110 = DAT_140a7a3b0[+0x180 & 0xF]`; if `DAT_140a7a470[idx]`: `+0x118 = DAT_140a7a330` when `G+0x8B == 0 && fighter+0x6B1 == 0` else 0 | 16 rating lists (models 10..34 = letters), points list |
| `caseD_10` tail (0x1406533a9) | `+0x80 = DAT_140a7a430[idx] - 24.0` (second-line x) | |
| `FUN_14073dfb0(kind)` | list 12, `+0x170 = 0`, callback `LAB_14073dfa0`, `+0x3A = 7`, `+0x34 = kind & 0xF`; its `caseD_0`: `+0x170 = 1`, `+0x54 = -6.25`, `+0x58 = 0`, `+0x50 = DAT_140a98870[state] * -0.5`, `+0x110 = PTR_LAB_140a987f0[state]`, `+0x118 = 0` | round / intro text (models 1, 2, 10..46), 8 lists |
| `FUN_1407ec920(mode)` / `FUN_1407ecc50` / `FUN_1407ec6b0` | list 12 nodes at `+0x54 = -10/0/5/10`, `+0x58 = -40`; digits `"%1x"` + `"%02d"` / `"%08x"` of `+0x270/+0x278` (h:mm:ss from `blk+0x324f8`); `caseD_0`: `+0x110 = DAT_140aac980[state]` | results-screen time lines (7 lists) |

All list-12 writers of `+0x110`/`+0x118` (byte scan of the disassembly cache): `FUN_140652c50`, `FUN_140652cc0`,
`caseD_c/e/f/10/11` of `switchD_140653969`, `FUN_1406535f0`, `switchD_14073dfab::caseD_0`, `FUN_1407ec6b0`'s
`caseD_0` (0x1407ec7d2). Every non-zero value is one of the roots in `rip_parts.py --lists` (5 roots, 32 distinct lists).

## 2. The draw, `FUN_140653a70(node)` (CONFIRMED, decompiled + disassembled)

```
if node+0x170 == 0 or node+0x110 == 0: return
push; identity; FUN_140847c40(node+0x50) [cur = T(pos) x cur]; FUN_140846a00(node+0xA8) [store]; pop
FUN_14061d5b0()                       ; HUD camera: slot3 = P(0x4000, 4/3, near 1.0, far 12000), slot2 = I, mode 1
push
for pass in 0..1:
    FUN_140846c30(node+0xA8)          ; slot1 = T(pos)
    if pass == 1:
        list = node+0x118 ; if 0: break
        FUN_140847bf0(node+0x80, -6.0 [DAT_14097f1b0], 0)      ; cur = T(x2, -6, 0) x cur
    k = &node+0x228
    for entry = list; entry.count >= 0; entry += 8:
        FUN_140847bf0(entry.xoff, 0, 0)                          ; cur = T(xoff,0,0) x cur
        if entry.scaleIdx:
            FUN_140847b90(PTR_DAT_140a7a2b0[scaleIdx & 7])       ; cur = S(sx,sy,sz) x cur
            FUN_140036560(FUN_140620720(scale))                  ; max(sx,sy,sz) -> EMPTY on Steam (DC 8c122710)
        FUN_140849b00(1.0, 1.0, 1.0)                             ; vertex colour multipliers = 1
        ctx+0x1f855c = 1                                         ; records are copied into the frame arena
        if entry.flags < 0: model = PTR_DAT_142edf598[entry.modelIdx]
        else:              idx = *k++ ; if idx < 0: continue ; model = PTR_DAT_142edf598[idx]
        if entry.count > 0: FUN_14060d8d0(model, entry.count - 1)   ; header patch, section 3
        FUN_1408499e0(model)                                     ; FUN_140848ee0(model, 0, 1.0, ctx+0x1f8518 ? 2 : 0)
pop
```

Matrix helpers (CONFIRMED by decompile; all build a 4x4 from the identity `DAT_140ab20c0` and call
`FUN_140846ee0` = pre-multiply): `FUN_140847bf0(x,y,z)` = translate, `FUN_140847c40(ptr)` = translate by
`ptr[0..2]`, `FUN_140847b90(ptr)` = scale by `ptr[0..2]`. `FUN_140620720(ptr)` = max of three floats.
Scale table `PTR_DAT_140a7a2b0`: `[0,1,6,7] -> (1.5, 1.5, 1)`, `2 -> (0.66, 0.66, 1)`, `3 -> (0.5, 1, 1)`,
`4 -> (1, 0.5, 1)`, `5 -> (2.5, 2.5, 1)`.

What D3D receives (CONFIRMED, `FUN_1408436a0` kinds 0/1/6/7 and `FUN_1408482a0`): `entry+0x08 = slot3 = P`,
`entry+0x48 = IDENTITY = V`, `entry+0x88 = slot1 = cur = W`; the flush binds P,V as the 128-B command 4 and W as
command 7 (the 48-B CBWorld = rows 0..2 of W transposed, `blkstate.cbworld`). The vertex copy is verbatim except
**`*puVar14 &= 0xfffffffe` (x) and `puVar14[7] &= 0xfffffffe` (v)** -- bit 0 of the x word is the NaomiLib
direct-vertex flag (`(*puVar17 & 1) == 0` selects the reference-vertex path). Every one of the 95 vertices of
frame 4445's part draws differs from the file by exactly that bit (x and v: 95/95 at -1 ulp; y, z, u: 95/95
equal), and none differ once the mask is applied. This mask is a property of the kind-0..3 consumer, so it
applies to every world/HUD object the tape reproduces, not only to parts (a 1-ulp effect; invisible in pixels,
decisive for a bit-exact gate). TSP-RENDER-STATE-GHIDRA.md section 3 ("copied verbatim") is corrected by this.

`ctx+0x1f855c = 1` makes `FUN_140848ee0` copy each record (`rec[0x13] + 0x50` bytes) into the frame arena
`ctx+0x100030 + ctx+0x1e0080` (`FUN_140800640` = memcpy) and submit the copy, then clears the flag. Needed
because the header patch (section 3) rewrites the SHARED model in place between draws.

## 3. The texture-page patch (CONFIRMED)

`FUN_14060d8d0(model, k)` = `FUN_140619760(model, DAT_142eed370 + k*0x10)`: for every record of the model
(`rec = model+0x18; while *rec != 0: rec = rec + rec[0x13] + 0x50`) copy the 16-B table entry over the record's
first four words (PCW, ISP, TSP, TCW). The table is built once per HUD-bank load in `FUN_14060c370` case 4:
`for i in 0..3: FUN_140619720(PTR_DAT_142edf598[i], DAT_142eed370 + i*0x10)` (the inverse copy: the first record
header of HUD model i). HUD models 0..3 have texIndex 2..5, so `DAT_142eed370[k].TCW = 0xC92 + k` (the four
64x64 RGB565 pages of the bank), PCW 0x8000002C, ISP 0x83000000, TSP 0x2009A45B (dump values; CONFIRMED equal to
the ripped headers). Hence `count = 2 -> 0xC93` (digits), `4 -> 0xC95` (HIT/S letters), `3 -> 0xC94` (rating
words), `1 -> 0xC92`. Models 4.. carry texIndex 2 (0xC92) in the file; the patch is what selects their page.

## 4. The HUD/common bank models (CONFIRMED by rip + gate)

`rip_parts.py`: AFS 835 (POL, 91,368 B) -> 130 models (`u32@0` model-table DC ptr 0x0CE80010, count 130,
texHdrs 0x0CE80218; file offset = DC - 0x0CE80000). Models 0..49 have one record each (0..3: 84/30/72/135
triangle vertices; 4..46: glyphs, x in [-1.5, 1.5], y in [0, 5], z ~ 0; 47/48/49: 3-D pieces on pages
0xC98/0xC96/0xC97); 50.. are empty. Decoded with `tape_to_seq.nl_groups` (Steam's own strip expansion).
Glyph identities used by the combo counter: digits = models 0..9 (`node+0x228` values 0..9 index them
directly), `DAT_140a7a2f0` = `[(2,0,S1,-,2.5) (2,1,-,-,3.5) (2,2,-,-,3.5)]` three digit slots then
`(4,ff,S2,17,2.81) (4,ff,-,18,2.68) (4,ff,-,29,2.38)` = the word after the number (models 17, 18, 29 on page
0xC95). The 8-digit points line `DAT_140a7a330` = 8 digit slots (scale 3 = (0.5,1,1)), three fixed model-0
entries, then models 36/37/38 (scale 4). The ripped JSON keeps the FILE vertex bytes; the gate applies the
bit-0 mask of section 2.

## 5. Minimum per-node tape data and the harvest delta

Everything the draw reads that is not exe-static or bank-static:

| field | bytes | why |
|---|---|---|
| `node+0x170` drawn | 1 | gate |
| `node+0x02` slot | 1 | identifies P1/P2 node (diagnostic; `+0x50` already carries the side) |
| `node+0x34` state | 1 | diagnostic (which display) |
| `node+0x110` list | 4 as RVA (`ptr - exe_base`, 0 = none) | selects the static list; exe is ASLR-relocated, the low 16 bits are stable if no base is at hand |
| `node+0x118` list2 | 4 as RVA | second line |
| `node+0x50/54/58` pos | 12 | the ONLY per-frame matrix input (x eases every frame in caseD_e) |
| `node+0x80` x2 | 4 | second-line x |
| `node+0x228..0x237` digits | 16 x i8 | model indices for the non-fixed entries |

44 B per node, at most a handful of nodes per frame (2 in a match; up to ~6 on the results screen). NOT needed:
`+0xA8` (recomputed from `+0x50`; and in a post-walk block it holds the PREVIOUS draw's `+0x50` -- frame 4445:
`+0xA8.x = -40.180` while the draw used `+0x50.x = -40.135307`, CONFIRMED by the CBWorld match), `+0x6C` (not
read by the draw), `+0x94` colour (fixed 1,1,1), `+0x90` alpha (fixed 1.0), `+0x172` (already formatted into
`+0x228`), `+0xF0` (0).

**Separate `pnodes` record, not an anodes append.** The 100-B anodes record is keyed on an interned object
(`obj`) or a model pointer (`model`) plus a 64-B matrix; a list-12 node has neither, its matrix is stale, and
the consumer would have to special-case list 12 anyway. Appending would also leave list 12 behind the 96-node
cap that HUD-heavy frames exhaust (77 HUD nodes seen). A separate 44-B fixed record walked from head 12 alone
cannot be starved and carries exactly the inputs of `FUN_140653a70`.

Patch for `RetroReceipts-agent/agent/src/reader.rs` (not applied here -- the agent lane owns the file; offsets
are the CONFIRMED ones above; `exe_base` is the value `find_opponent_lobby` / `read_set_score` already use):

```diff
@@ const ANODES_CAP_PER_FRAME: usize = 96;
+// LIST 0xC (combo counter / rating / round text): no object, no model -- docs/PARTS-LIST0C-GHIDRA.md.
+// The draw FUN_140653a70 reads ONLY these; +0xA8 is stale (previous draw) and is not carried.
+const P_LIST1: usize = 0x110; const P_LIST2: usize = 0x118; const P_X2: usize = 0x80;
+const P_DIGITS: usize = 0x228; const P_SLOT: usize = 0x02; const P_STATE: usize = 0x34;
+const PNODES_STRIDE: usize = 44; const PNODES_CAP_PER_FRAME: usize = 8;
+#[derive(Clone)]
+struct PNode { slot: u8, drawn: u8, state: u8, list1: u32, list2: u32, pos: [f32; 3], x2: f32, digits: [i8; 16] }
+
+unsafe fn harvest_pnodes(h: &mem::Proc, blk: usize, exe_base: usize, out: &mut Vec<PNode>) {
+    let mut p = match read_at(h, blk + ALIST_HEADS + 12 * 8, 8) { Some(b) if b.len() >= 8 => le64(&b, 0) as usize, _ => return };
+    let mut n = 0;
+    while p != 0 && n < 64 && out.len() < PNODES_CAP_PER_FRAME {
+        let nd = match read_at(h, p, 0x240) { Some(b) if b.len() >= 0x240 => b, _ => break };
+        let l1 = le64(&nd, P_LIST1) as usize; let l2 = le64(&nd, P_LIST2) as usize;
+        if nd[A_DRAWN] != 0 && l1 != 0 {
+            let rva = |q: usize| if q == 0 { 0 } else { q.wrapping_sub(exe_base) as u32 };
+            let mut digits = [0i8; 16];
+            for i in 0..16 { digits[i] = nd[P_DIGITS + i] as i8; }
+            out.push(PNode { slot: nd[P_SLOT], drawn: nd[A_DRAWN], state: nd[P_STATE], list1: rva(l1), list2: rva(l2),
+                             pos: [lef32(&nd, 0x50), lef32(&nd, 0x54), lef32(&nd, 0x58)], x2: lef32(&nd, P_X2), digits });
+        }
+        n += 1;
+        p = le64(&nd, A_NEXT) as usize;
+    }
+}
@@ struct GsCapture {
     anodes: std::collections::BTreeMap<u32, Vec<ANode>>,
+    pnodes: std::collections::BTreeMap<u32, Vec<PNode>>,   // list 0xC, 44 B each (docs/PARTS-LIST0C-GHIDRA.md)
@@ (the per-frame harvest call, next to `harvest_anodes(h, blk, &mut araw)`)
-                            if let Some(blk) = base.checked_sub(BLK_BACK) { unsafe { harvest_anodes(h, blk, &mut araw); } }
+                            let mut praw: Vec<PNode> = Vec::new();
+                            if let Some(blk) = base.checked_sub(BLK_BACK) { unsafe { harvest_anodes(h, blk, &mut araw); harvest_pnodes(h, blk, exe_base, &mut praw); } }
@@ (where `c.anodes.insert(frame, list)` is done)
+                                    if !praw.is_empty() && (c.pnodes.len() < GS_CAP || c.pnodes.contains_key(&frame)) { c.pnodes.insert(frame, praw); }
@@ (snapshot serialisation, next to "anodes")
+        // per-frame [u32 frame, u16 count, count x 44 B {u8 slot(node+2), u8 drawn(+0x170), u8 state(+0x34), u8 pad,
+        //   u32 list1(+0x110 - exe_base, 0 = none), u32 list2(+0x118 - exe_base), f32[3] pos(+0x50), f32 x2(+0x80), i8[16] digits(+0x228)}]
+        "pnodes": pnodes_b64, "pnodes_frames": gs.pnodes.len(), "pnodes_stride": PNODES_STRIDE,
+        "pnodes_enc": "TAPE v6 -- gzip+base64 of per-frame [u32 frame, u16 count, count x 44 B] list-0xC nodes; render rule docs/PARTS-LIST0C-GHIDRA.md s2 (static lists from rip_parts.py --lists, models from rip_parts.py)",
```

`pnodes_b64` is built like `anodes_b64` (`b64_encode(&gzip_bytes(&raw))`, raw = per frame `u32 frame, u16 count`
then the 44-B records with `pos`/`x2` as `to_le_bytes()` f32 and `list1/list2` as `to_le_bytes()` u32).

Sampling-phase caveat (for the harness owner, not resolved here): the reader samples at the clock edge; the
combo state machine (`caseD_e`) rewrites `+0x50.x` and `+0x228` in the callback pass before the render. In the
captured post-walk blocks `+0x50` is the value the same frame's draw used (CONFIRMED by the gate); whether the
agent's edge sample lands before or after the callback pass is a live measurement: compare a tape's `pnodes.pos.x`
sequence against the eased series `x += (0x8C - x) * DAT_14092792c` -- a one-frame offset shows as a constant lag.

## 6. SH4 side (CONFIRMED pairs; `bank0f.asm`)

| Steam | SH4 | evidence |
|---|---|---|
| `FUN_140653a70` | `loc_8C0F215E` | same skeleton: gate `+0x12C` (DC) / `+0x170`, list `+0xD4` / `+0x110`, `8c120950(0)` push, `8c121100` identity, `8c1210E0(r12+0x34)` translate by `+0x34` / `+0x50`, `8c11FA80(r12+0x88)` store to `+0x88` / `+0xA8`, `8c120900(1)` pop, `8c02E334` HUD camera (= `FUN_14061d5b0`, seed 24), two passes with `+0xD8` / `+0x118` and `8c1210B0(+0x64 (DC) / +0x80, fr13 = -6.0 [0xC0C00000 at 8C0F2244], 0)`, per entry `8c1210B0(entry+4, 0, 0)`, scale via `8c120FF0(0x8C1605F0[idx&7])` + `8c0301B4` (max3) + `8c122710`, colour `8c123780(1,1,1)`, digit pointer `r13 = r12 + 0x19C` / `+0x228`, model table `0x8C26A90C` / `PTR_DAT_142edf598`, `8c032FAe(model, count-1)` / `FUN_14060d8d0`, `8c1235B0(model)` / `FUN_1408499e0` |
| `FUN_140652cc0` | `loc_8c0f2104` | `8c129740` sprintf (= `FUN_14003a4c0`, seed 30) of `*(i16*)(node+0x12E)` / `+0x172`; three chars minus 0x30 (negative -> 0xFF) into `+0x19C` / `+0x228`; `+0xD4 = 0x8c160610` / `+0x110 = 0x140a7a2f0`; `+0xD8 = 0` / `+0x118 = 0` |
| `FUN_140847bf0` / `FUN_140847c40` / `FUN_140847b90` | `loc_8c1210B0` / `loc_8c1210E0` / `loc_8c120FF0` | translate(x,y,z) / translate(ptr) / scale(ptr) (call slots) |
| `FUN_140846a00` / `FUN_140846c30` | `loc_8c11FA80` / `loc_8c1201E0` | store XMTRX to / load XMTRX from a node matrix |
| `FUN_140849b00` | `loc_8c123780` | vertex colour multipliers |
| `FUN_14060d8d0` / `FUN_1408499e0` / `FUN_140620720` | `loc_8c032FAe` / `loc_8c1235B0` / `loc_8c0301B4` | header patch / draw / max3 (call slots) |
| `FUN_140036560` | `loc_8c122710` | DC does something with max(scale); Steam body is `ret` (TSP-RENDER-STATE-GHIDRA.md s1) |

DC -> Steam node-field deltas seen here: `+0x12C -> +0x170` (+0x44), `+0x12E -> +0x172` (+0x44), `+0xD4 -> +0x110`
(+0x3C), `+0xD8 -> +0x118` (+0x40), `+0x34 -> +0x50` (+0x1C), `+0x64 -> +0x80` (+0x1C), `+0x88 -> +0xA8` (+0x20),
`+0x19C -> +0x228` (+0x8C). Static tables: DC `0x8C1605F0` (scale ptrs, 4-B) -> `0x140a7a2b0` (8-B);
`0x8c160610` -> `0x140a7a2f0`; `0x8c160648` (second list, written by the routine before `loc_8c0f2104`) ->
`0x140a7a330`; DC model table `0x8C26A90C` -> `PTR_DAT_142edf598 = 0x142ee0c50`.

## 7. Gate (deterministic, bit-for-bit) -- `parts_gate.py`

Inputs: the frame's captured block (`blkstate.load_frame`, `pnodes()`), the exe-static lists/scale table read
from the dump at run time, the ripped HUD POL/TEX from `game_50.arc`, and the frame's `.pack`. Derivation = the
pseudo-code of section 2 in float32 with `FUN_140846ee0`'s pre-multiply. Match = captured HUD-camera draw
(scene CB with V = I) whose 48-B CBWorld equals the derived W bit-for-bit; then the draw's unique vertex
positions / uvs (VB stride 40: pos @0, uv @32) vs the model group's set with the bit-0 mask; then the bound
texture page vs the bank page named by the patched TCW (`rip_texbank.decode_host`).

| frame | count / digits | derived draws | CBWorld exact | groups | pos exact | uv exact | page exact | unexplained z=-40 draws |
|---|---|---|---|---|---|---|---|---|
| 4445 | 9 `[-16,-16,9]` | 4 | 4/4 | 16 | 16/16 | 16/16 | 16/16 | 0 |
| 4447 | 12 `[-16,1,2]` | 5 | 5/5 | 14 | 14/14 | 14/14 | 14/14 | 0 |
| 4474 | 28 `[-16,2,8]` | 5 | 5/5 | 22 | 22/22 | 22/22 | 22/22 | 0 |
| 7441 | 12, `+0x80 = -12.25` | 5 | 5/5 | 14 | 14/14 | 14/14 | 14/14 | 0 |
| 26380 | 22 `[-16,2,2]` | 5 | 5/5 | 16 | 16/16 | 16/16 | 16/16 | 0 |

Frame 4445 in numbers: node `+0x50 = (-40.135307, 5, -40)`; the "9" (model 9, page 0xC93) draws 174..181 with
`W = diag(1.5,1.5,1), T = (-27.135307, 5, -40)`; models 17/18/29 (page 0xC95) at `T.x = -22.920307 /
-20.267107 / -17.910908` with `diag(0.99, 0.99, 1)` (0.66 x 1.5). The list-2 pass and the rating lists were not
exercised by any captured frame (every capture has `+0x118 = 0`; state 3 never captured) -- INFERRED from the
same code path, not gated. Before the bit-0 mask the position/uv counts were 0/16 (95/95 vertices at exactly
-1 ulp on x and v): that is how section 2's mask was found, and it is the falsification the mask survived.

## 8. Falsification tests (what would disprove this)

1. A frame whose list-12 node has `+0x110 != 0` and `+0x170 != 0` but whose pack has no HUD-camera draw with
   the derived CBWorld -> the transform or the list pointer is wrong. (5/5 frames pass.)
2. A captured part vertex differing from the ripped model by anything other than bit 0 of x / v -> the models
   are not AFS 835 or the consumer does more than the mask. (0 of 95 on 4445; 82/82 groups on 5 frames.)
3. A captured part page whose bytes differ from `0xC92 + count - 1` -> the header-patch rule is wrong (82/82).
4. `harvest_anodes` yielding any list-12 node with `+0xA0 != 0 || +0xE8 != 0` -> the "dropped by construction"
   claim fails; every allocator read writes both to 0.
5. Live: a tape `pnodes.pos.x` series that is a one-frame lag of the eased series -> the sampling phase is
   before the callback pass (section 5 caveat); fix on the reader side, not the rule.

## 9. Open / not this document

* **Missing hit sparks on real-match tapes are NOT explained by list 0xC.** Hit sparks are System-B sprite
  objects (cat 1..4 in `blk+0x2F4D0`, the tape's `objs`/`nodes`); bisect that symptom separately (objs cap,
  effect-page decode, `is_effect` classing) -- UNKNOWN here.
* The rating-word / points pass (`+0x118`, `T(+0x80, -6, 0)`) and the round-text / results-time nodes are
  INFERRED from the same walker; no capture exercised them.
* Which init path calls `FUN_140653970` in a match (five callers) -- not traced.
* `blk+0x3254E + slot*2` (per-slot combo count) and `blk+0x3256C + slot*4` (points) are read here for the first
  time; their writers (the hit/damage code) are not traced.

## 10. Address index

Steam: `FUN_140653a70` part draw · `FUN_1406539a0` alloc (slot) · `FUN_140653970` alloc both · `LAB_140653940`
callback dispatcher · `switchD_140653969::caseD_c/e/f/10/11` states · `FUN_140652cc0` "%3d" formatter ·
`FUN_140652c50` rating/points lists · `FUN_1406535f0` · `FUN_14073dfb0` / `switchD_14073dfab::caseD_0` round text ·
`FUN_1407ec920` / `FUN_1407ecc50` / `FUN_1407ec6b0` results time · `FUN_14060d8d0` -> `FUN_140619760` header
patch · `FUN_140619720` header copy (table build, `FUN_14060c370` case 4) · `FUN_140847bf0/c40/b90` translate /
translate-ptr / scale · `FUN_140846ee0` pre-multiply · `FUN_140846a00/c30` store/load · `FUN_140849b00` colour ·
`FUN_1408499e0` -> `FUN_140848ee0` -> `FUN_1408436a0` -> `FUN_1408482a0` (bit-0 mask) · `FUN_140800640` memcpy ·
`FUN_14061d5b0` HUD camera · tables `DAT_140a7a280` (slot positions) · `PTR_DAT_140a7a2b0` (scales) ·
`DAT_140a7a2f0` (hits list) · `DAT_140a7a330` (points list) · `DAT_140a7a3b0[16]` (rating lists) ·
`DAT_140a7a430[16]` (rating x2) · `DAT_140a7a470[16]` (points-line enable) · `PTR_LAB_140a987f0[16]` +
`DAT_140a98870[16]` (round text) · `DAT_140aac980[7]` + `DAT_140aac9b8` (results time) · `DAT_142eed370`
(header-patch table) · `PTR_DAT_142edf598 = 0x142ee0c50` (HUD bank model table) · `DAT_14097f1b0 = -6.0` ·
`DAT_14097e87c = "%3d"`, `DAT_14097e850 = "%8x"`, `DAT_14097e844 = "%08x"`, `DAT_1409803b0 = "%1x"`,
`DAT_1409803b4 = "%02d"` · state `blk+0x3254E` (combo count per slot), `blk+0x3256C` (points), `blk+0x324E0`,
`blk+0x32500 + slot*0x18`, `blk+0x324F8`.
SH4: `loc_8C0F215E`, `loc_8c0f2104`, `loc_8c1210B0`, `loc_8c1210E0`, `loc_8c120FF0`, `loc_8c11FA80`,
`loc_8c1201E0`, `loc_8c123780`, `loc_8c032FAe`, `loc_8c1235B0`, `loc_8c0301B4`, `loc_8c122710`, `loc_8c02E334`,
tables `0x8C1605F0`, `0x8c160610`, `0x8c160648`, `0x8C26A90C`.
