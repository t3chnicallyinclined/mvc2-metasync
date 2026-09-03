# Texture banks: how the Steam build numbers texture slots, and where the pixels are on disk (2026-09-02)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, base 0x140000000, Ghidra project `dumpproj`, GhidraMCP bridge :8080
`decompile_function?address=` / `xrefs_to?address=`). SH4 side: marvelous2 `build/bank*.asm`. `blk` = `DAT_142edf560`,
`G` = `DAT_142edf580` = `blk+0x3CB8`, `ctx` = `DAT_142ef0ab0` (NaomiLib host context), `ctx[0]` = archive image,
`ctx[1]` = host base of the 32 MB DC work-RAM image (DC `X` -> `ctx[1] + (X - 0x0C000000)`).
Tags: **CONFIRMED** = decompiled/disassembled and read; **INFERRED** = derived, not read. Seed: `maplecast-flycast/tools/re_kb/31_texture_banks.surql`.
Ripper + gate: `d3dcap/replay/rip_texbank.py`. Gold: `d3dcap/replay/tcw_pages/index.json` (captured D3D pages, sha256 over RGBA8).

## 0. Answer

* **Slot rule (CONFIRMED both builds):** `FUN_1408458a0(base)` stores `base` at `ctx+0x1e0098` (SH4 `loc_8C11B800`:
  `mov.l r4,@0x8C2DEE54`). `FUN_140844dc0(model, texHdrs)` then assigns every model record `TCW = base + texIndex` and
  fills slot `ctx+0x1e00a0 + TCW*0x18` from the 16-byte TEX record `{u16 w, u16 h, u8 fmt, u8 type, u16 -, u32 loc, u32 -}`
  with pixels at `ctx[1] + (loc & 0x1ffffff)`. The stage rule (`0xC10 + texIndex`) is one instance; the effects bank is
  `0xC50 + texIndex`, the HUD bank `0xC90 + texIndex`.
* **On disk (CONFIRMED):** `...\nativeDX11x64\arc\pc\game_50.arc` -> ARC v7, one zlib entry `bin\mvsc2` -> IBIS header +
  Sega **AFS at +0x40** (890 entries) = `ctx[0]`. Effects = AFS **799** (POL) + **800** (TEX); HUD = **835/836**;
  common = **837/838**; stage = `801+2*id` / `802+2*id`. Byte ranges in section 3.
* **Host decode (CONFIRMED, gated byte-exact):** `FUN_14004ba50` -- 565/1555 expand as `c*255/31` (integer), 4444 as
  `c*0x11`, twiddle with **y in bit 0**, VQ = 256x4-u16 codebook + block-twiddled indices. `rip_stage.py`'s decode is
  **falsified** on the same pages (section 5).
* **Gate:** every captured page that can come from a bank file matches byte-exact (effects 9/9 distinct pages, HUD 2/2,
  stage-0B 1/1). The other captured pages are either mis-keyed by the capture tool (7, proven) or the runtime-patched
  portrait slots `0xC9A..0xCA5` (29), plus one 1x1 non-texture. The missing pages `0xC51/0xC5A/0xC5C/0xC5D/0xC5E/0xC5F/0xC62`
  and the rest of the effects bank (`0xC50..0xC68`) plus HUD `0xC90..0xC98` are now in the library with `obj='arc'`.

## 1. The slot mechanism (CONFIRMED)

| Steam | body | SH4 |
|---|---|---|
| `FUN_1408458a0(base)` | `*(u32*)(ctx+0x1e0098) = base` | `loc_8C11B800`: `mov.l r4,@0x8C2DEE54; rts` |
| `FUN_1408457e0()` | free all 0xFFF slots (`FUN_140843580(i)`), base = 0 | -- |
| `FUN_140844dc0(model, texHdrs)` | walk records from `model+0x18` while `PCW<0` (`next = rec + rec[0x13] + 0x50`); `ti = rec[8]`; if `ti >= 0`: `TCW = ti + base`; `rec[3] = TCW`; if slot free: `used=1, fmtType=u16@hdr+4, flag=(type in 5..7)?0:-1, w, h`, `FUN_140048460(TCW, w, h, 0, fmtType, *(ctx+0x1e0088) + (loc & 0x1ffffff))` | `loc_8C122FD0` (loops `loc_8C122D00` per record; inner routine not read -- pair is **high**, not confirmed) |
| `FUN_1408435d0(slot, rec)` | same fill for one explicit slot from a 16-byte record | -- |
| `FUN_140845fe0(list, flags)` | `slot = base + i` for each record while `w > 0` | -- |
| `FUN_140846080(list, _, idx)` | register `list[idx]` at `base + idx` | -- |
| `FUN_140845830(slot, pixels)` | **re-upload** an existing slot (`FUN_140048910`) | -- |
| `FUN_14060d080(base, &table, POL)` | registrar; `FUN_14060d8f0` (host model table: `table[i] = host(modelTable[i])`, count `+0xB00`, texHdrs `+0xB08`); loop `FUN_140844dc0` | `loc_8c032320(base, &table, POL)`: `loc_8c11b800(base)`, `*table = POL`, loop `loc_8c122fd0(POL[0][i], *(POL+8))` |
| `FUN_14060d770(POL, TEX)` | `delta = *POL - POL - 0x10`; `*POL`, `*(POL+8)`, every model-table entry `-= delta`; every TEX record `loc -= firstLoc - TEX` | `loc_8c0322d4` -- identical (read) |
| `FUN_14060dcf0(i, dc)` | `memcpy(ctx[1] + dc - 0x0C000000, ctx[0] + u32@ctx[0]+8+i*8, u32@ctx[0]+0xC+i*8)` | `loc_8c027366` (seed 30) |
| `FUN_140844a10` | also `*(ctx+0x1e0088) = *(ctx+0x1e0090) = ctx[1]` | -- |

Slot table entry (`ctx+0x1e00a0 + TCW*0x18`): `+0 u16 used, +2 u16 fmt|type<<8, +4 u16 flag, +6 u16 w, +8 u16 h, +0x10 host texture`
(`FUN_140048460` keeps the D3D object at `DAT_140acd3a8 + 0xd0500 + TCW*8`; fmt 9/10 pick a second DXGI format from
`0x140a4f768`; type 0xB marks the slot as the special render target `DAT_140acd3a8+0xdbd04`).

## 2. Every base the registrar is called with (CONFIRMED: 43 call sites, all decompiled)

| base | caller | what is registered | file / DC |
|---|---|---|---|
| 0xC10 | `FUN_14060d470` (case 1, 0x17) | stage POL/TEX (STAGE-DRAW-GHIDRA) | AFS `801+2*id` -> 0x0D82D000, `802+2*id` -> 0x0D85D000 |
| **0xC50** | `FUN_14060c370` case 2 (also 0x18) -> `FUN_14060d080(0xc50, &PTR_DAT_142edf590, 0xd000000)` | **effects bank**, 241 models, 25 textures | AFS **799/800** -> 0x0D000000 / 0x0D026000 (boot, `FUN_14060c070`); SH4 case `loc_8c032c76`: `loc_8c0322d4(0x0CED0000, 0x0CDA4000)` then `loc_8c032320(0x0C50, 0x8C26A908, 0x0CED0000)` |
| **0xC90** | `FUN_14060d560` (case 4) | **HUD / common-model bank**, 130 models, 25 records (9 static) | AFS **835/836** -> 0x0D082000 / 0x0D099000; SH4 `loc_8c032696`, table `0x8C26A90C` |
| 0x810 | case 5 (`PTR_DAT_142edf5a0`), 6 (`5a8`, 0x0D25C000), 9 (`5c0`/`5d0`, 0x0D7CC000), 10 (`5c8`, 0x0D2BB000), 0xB/0x19 (`5d0`, 0x0D3A2000), 0xC (`5d8`, 0x0D4CE000), 0xD (`5e0`, 0x0D6CC000) | select / vs / result banks | case 5: AFS 837/838 -> 0x0D0C6000 / 0x0D0E5000; others per `FUN_14060c070` (seed note) |
| 0x850 | case 0xF (`5f0`, 0x0D7A9000), 0x10 (`5f8`, 0x0CE80000), 0x11 (RAM list at 0x0CC00000), 0x12..0x15 (`608..620`, 0x0CE80000) | ending / credits banks | AFS 0x357/0x358, 0x35E..0x369 |
| 0x860 | case 0x11 (`DAT_142edf600`, 0x0CE80000) | | AFS 0x360/0x361 |
| 0x910 | case 5 (`DAT_140a6aad0`), case 9 (`DAT_140a6ab30`) | exe-resident 16-B record lists (256x256 fmt0 @0x0CE60000, 128x128 fmt1 @0x0CC60000, 64x64 fmt2 @0x0CCF0000, two 128x128 @0x00200000/0x00208000 + `G+0x94`) | RAM scratch, decompressed by `FUN_140611e90` |
| 0x914 | case 5 (`DAT_140a6aaf0[0]`) | one 128x128 fmt1 @0x0CC60000 | |
| 0xD10 | case 8 (`5b8`, 0x0D2B1000), 0xE (`5e8`, 0x0D720000) | | AFS 0x349/0x34A, 0x355/0x356 (0x359/0x35A when `G+0x29`) |
| 0xD50 | case 0xE (`DAT_140a6ab98`) | 128x128 fmt2 @0x0CC80000 | |
| 0xD | case 0x11 (RAM list at 0x0CE60000) | | AFS 0x93 -> 0x0CE60000 |
| 2 | `FUN_14060af70` / `FUN_14060b230` (boot / bank reset) | list at DC 0x0CE1D000 | |
| 0 | boot, and before every direct re-upload (`FUN_140845830` callers: 0x810/0x81C/0x811/0x81D/0x817+/0x910/0x914/0xC99/0xCA6+) | | |
| `0x390 + slot*0x100` | `FUN_140612180(_, slot)` | **per-fighter sprite pages** (System B) | fighter data |
| `*(blk+0x32be8)` | `FUN_1406127c0` | list at DC 0x0CE60C00 | |

`FUN_140611e90(src, dst)` is the NinjaLib **word-LZSS** (u16 stream; bitmask word per 16 chunks, 0x8000 first; set bit:
hi-5 count / low-11 distance, count 0 = next word is the count and the whole word is the distance; distance 0 = zero run;
0/0 = end) -- same algorithm as `rip_stage.lzss_decompress_tex`.

## 3. Archive -> DC map (CONFIRMED)

`game_50.arc`: `ARC\0`, u16 ver 7, u16 count 1; toc@8: name `bin\mvsc2`, `csize @+68`, `dsize @+72`, `doff @+76` (0x8000).
Inflate -> 112,635,968 B: `IBIS` header, **`AFS\0` at +0x40**, u32 count 890, entries `{u32 off, u32 size}` at +8 (offsets
relative to the AFS start). `FUN_14060dcf0(i, dc)` copies entry `i` to `ctx[1] + dc - 0x0C000000`. Entries 799/800/835-838
are byte-identical across `game_50.arc`, `.bak`, `.ORIGINAL` (the skin tool rewrites only character DATs).

| bank | POL entry (AFS off, size) | TEX entry (AFS off, size) | Steam DC | records |
|---|---|---|---|---|
| effects 0xC50 | 799 (0x3EBB000, 0x25ED0) header ptr 0x0CED0010 (= SH4 address), 241 models, texHdrs 0x3D8..0x578 | 800 (0x3EE1000, 0x5B800) | 0x0D000000 / 0x0D026000 | 25: 0xC50..0xC68, **all type 3 (VQ)**, 128x128 or 256x256, fmt 0/1/2; loc = 0x0CC00000 + offset |
| HUD 0xC90 | 835 (0x5B91800, 0x164E8), 130 models | 836 (0x5BA8000, **0x1E000**) | 0x0D082000 / 0x0D099000 | 25: 0xC90 128x128 fmt1, 0xC91 128x128 fmt2, 0xC92..0xC98 64x64, **0xC99..0xCA8 point past the file** (section 6) |
| common 0x810 | 837 (0x5BC6000, 0x1E5A8), 181 models | 838 (0x5BE4800, 0x16E000) | 0x0D0C6000 / 0x0D0E5000 | 14: 0x810..0x81D (256x256 x3, 64x64 x3, 128, 256 x4, 512x512, 2 VQ) |
| stage 0xC10 | `801+2*id` | `802+2*id` | 0x0D82D000 / 0x0D85D000 | e.g. STG0B: 10 (0xC10..0xC19) |

`rip_texbank.py --bank arc|hud|common|stage --stage XX` prints the record table with AFS offsets.

## 4. Host decode (CONFIRMED, `FUN_14004ba50` <- `FUN_14004d290` <- `FUN_140048460`)

* type (`fmtType >> 8`): **1** twiddled 16bpp -> `FUN_140051f70(src, dst, stride, n)` recursion **TL, BL, TR, BR**
  (BL = `dst + stride*q`, TR = `dst + q`) => twiddled index has **y in bit 0, x in bit 1**; non-square = `min(w,h)` squares
  along the long axis; type 2 (mipmapped) skips 0x2aac/0xaaac/0x2aaac. **3** VQ -> `FUN_140052050`: codebook = first 0x800 B
  (256 x 4 u16), indices at +0x800, `FUN_140052280` recurses over 2x2 blocks in the same order, leaf
  `FUN_140051f70(codebook + idx*8, dst, stride, 2)` => each entry is 4 texels in twiddle order; type 4 skips
  0xd56/0x1556/0x5556. **5..7** 4-bit palettized (nibble expand, `FUN_140051e90`). Size caps: 0x200000 texels (VQ), 0x10000 (4-bit).
* fmt (`fmtType & 0xFF`), scalar tails read: **0** ARGB1555 -> `R=((v>>10)&31)*255/31, G=((v>>5)&31)*255/31, B=(v&31)*255/31,
  A = (i16)v>>15 & 0xFF` (line 2413); **1** RGB565 -> `R=(v>>11)*255/31, G=((v>>5)&63)*255/63, B=(v&31)*255/31, A=0xFF`
  (line 753); **2** ARGB4444 -> `R=(hi&15)*0x11, G=(lo>>4)*0x11, B=(lo&15)*0x11, A=(hi>>4)*0x11` (case 2); **5** 555 with A=0xFF.
  Integer division (SIMD magic 0x84210843 = 1/31, 0x82082083 = 1/63). Output bytes **R,G,B,A** = DXGI R8G8B8A8_UNORM = the
  capture's fmt 28.

## 5. Gate (deterministic, no capture needed)

`python d3dcap/replay/rip_texbank.py --bank arc --gate` (and `--bank hud`, `--bank stage --stage 0B`): sha256[:16] over the
RGBA8 bytes, the `tcw_build.py` convention. Result over the 45 captured entries (index.json before `--add`):

| class | n | entries |
|---|---|---|
| byte-exact under their key | 8 | 0xC5B, 0xC61_d3f807, 0xC63, 0xC64, 0xC66, 0xC67, 0xC90_b23a27, 0xC91 |
| byte-exact under ANOTHER TCW (capture mis-keyed) | 7 | lib 0xC50 = 0xC51, 0xC60 = 0xC5C, 0xC61(64x64) = stage 0xC10, 0xC61_b23a27 = HUD 0xC90, 0xC61_cc2a09 = 0xC5A, 0xC90 = 0xC5A, 04000000 = 0xC90 |
| runtime-patched portrait slots | 29 | every 0xC9A..0xCA5 entry (section 6) |
| unmatched | 1 | 04000000_ad9513 (1x1) -- not a bank texture |

So **16 of the 16 pages that can come from a bank file match byte-exact; 0 contradict the rule.** The mis-keying is a
property of the capture join, not of the rule: `tcw_build.py:66` keys a draw by `records[0].tcw` of the node object whose
CBWorld matched, so an object with several textures files its later pages under its first record's TCW (CONFIRMED by
reading the script; 7/7 mis-keyed pages are explained by a page of the SAME banks). `--add --fix-miskeyed` moved those
entries to `<key>_<sha6>` (field `miskeyed_true_tcw`) and put the ripped page under the key; the library is now 73 entries
with `obj='arc'` for 0xC50..0xC68 and 0xC90..0xC98.

**Falsification arm:** `--decode ripstage` (the `rip_stage.py` decode) scores **0/11** effects and **0/2** HUD on the same
records. Hybrid runs: host twiddle + rip_stage colours = 3 hits (ARGB4444 only, where `c*0x11` agrees); rip_stage twiddle
+ host colours = 0. So `rip_stage.py` is wrong on **both** axes: its x-LSB morton transposes every page, and its 1555
(`c*8`) / 565 (bit-replicate) expansions are not the host's `c*255/31`. Every `STGxx_tNN.png` it produced inherits this;
the stage rule consumers should decode through `rip_texbank.decode_host` (`--bank stage`).

## 6. Runtime-patched HUD slots (CONFIRMED writers, INFERRED derivation)

HUD records 9..24 (0xC99..0xCA8) have `loc` offsets >= 0x1E000 in a 0x1E000-byte TEX: no static pixels. Writers:
* `FUN_14060d560` (every match load): for each of the 6 fighter slots `s` (stride 0x738): `FUN_140611e90(data + data[0]`
  (or `data[3]` when `G+0x29`), DC 0x0CE60000)` where `data = *(blk + 0x3FB0 + s*0x738)`; then copy 0x800 B (one 32x32
  RGB565 page) from `ctx[1] + (DAT_140a6aac4[*(slot+0x440d)] + 0x1CC0) * 0x800` (= DC 0x0CE60000 + k*0x800) into
  `texHdr[10 + DAT_140a6aac8[s]].loc`, and 0x800 B from DC 0x0CE61000 into `texHdr[16 + DAT_140a6aac8[s]].loc`.
  `DAT_140a6aac8 = {0,3,1,4,2,5}`, `DAT_140a6aac4 = {1,0,3,0}` => **0xC9A/0xC9B/0xC9C = P1 C1/C2/C3 portraits,
  0xC9D/0xC9E/0xC9F = P2**, 0xCA0..0xCA5 the second (dim/alt) set. This is why the capture holds up to four different pages
  per key and why sha pairs repeat across keys (mirror teams).
* `FUN_1406162e0(fighter)`: decompress `*(fighter+0x1f8) + [4]` to 0x0CE60000, re-upload slot 0xC99 (base 0).
* `FUN_140616330(fighter)`: decompress `+[8]`, re-upload slot `(*(fighter+0x230) >> 1) + 0xCA6`.
INFERRED: all of it is derivable offline from AFS entry `209 + cid` (the character DAT) -- a roster-dependent second rule;
the test is `cid -> page sha` against the captured 0xC9A..0xCA5 pages. Not implemented here.

## 7. Corrections to earlier records

* seed 30 (crawl) pairs falsified by this read-set, demoted in seed 31: `FUN_1408458a0 -> loc_8c0324d0` (that routine is the
  case-9 body), `FUN_14060d770 -> loc_8c129668` (memcpy), `FUN_140844dc0 -> loc_8c032526` (case-10 body),
  `FUN_14060d080 -> loc_8c0321dc` (a small load+rebase routine, Steam counterpart UNKNOWN).
* STAGE-DRAW-GHIDRA.md section 2 called `PTR_DAT_142edf598` "the 0x0D082000 bank, used by list-12 part nodes" -- it is the
  HUD/common-model bank (base 0xC90, HUD list-11 nodes draw its pages); list-12 part draws index the same table.

## 8. Open

1. Case 0x18 rebases the effects TEX to 0x0CDA0000 -- who copies pixels there and whether it runs in a match: UNKNOWN
   (the gate matched file 800 at its boot placement, so it did not matter for any captured frame).
2. SH4 side of the slot table (Steam `ctx+0x1e00a0`): not located.
3. `loc_8c0321dc`'s Steam counterpart: UNKNOWN.
4. Character-DAT derivation of 0xC99..0xCA8: INFERRED, not gated.
5. Origin of the 1x1 page `04000000_ad9513`: UNKNOWN.

## 9. Address index

`FUN_1408458a0` registrar (SH4 `loc_8C11B800`, global 0x8C2DEE54 / `ctx+0x1e0098`) · `FUN_140844dc0` slot assign
(`loc_8C122FD0`) · `FUN_1408435d0` / `FUN_140845fe0` / `FUN_140846080` record-list registration · `FUN_140845830` re-upload ·
`FUN_1408457e0` reset · `FUN_14060d080` bank register (`loc_8c032320`) · `FUN_14060d770` relocation (`loc_8c0322d4`) ·
`FUN_14060d8f0` host model table · `FUN_14060dcf0` AFS copy (`loc_8c027366`) · `FUN_14060c070` boot loader ·
`FUN_14060c370` bank loader (`loc_8c032be0`; inlines `loc_8c0324d0`, `loc_8c032526`) · `FUN_14060d560` HUD bank
(`loc_8c032696`) · `FUN_140611e90` word-LZSS · `FUN_140844a10` sets `ctx+0x1e0088` · `FUN_140048460` / `FUN_14004d290` /
`FUN_14004ba50` host texture create / upload / decode · `FUN_140051f70` detwiddle · `FUN_140052050` / `FUN_140052280` VQ ·
`FUN_140800640` memcpy (`loc_8C129668`) · tables `PTR_DAT_142edf590` (0xC50, SH4 0x8C26A908), `PTR_DAT_142edf598` (0xC90,
SH4 0x8C26A90C), `DAT_140a6aac4/aac8` (portrait slot map), `DAT_140a6aad0/aaf0/ab30/ab98` (exe-resident record lists).
