# Steam MvC2 x86-64 <-> Dreamcast SH4 function correspondence map (2026-09-02)

Programmatic map between the unpacked Steam executable (`C:\Users\trist\ghidra_projects\mvc_dump.bin`, Ghidra project `dumpproj`, read through the GhidraMCP HTTP bridge on :8080) and the marvelous2 SH4 disassembly (`C:\Users\trist\projects\_marv_re\build\bank*.asm`, `loc_8c......` == PC). Machine-readable: `docs/steam_sh4_map.csv`. Scripts: `d3dcap/replay/re_map/` (`ghidra_export.py`, `sh4_export.py`, `blkmap.py`, `match.py`, `seeds.json`, `report.py`). KB seed: `maplecast-flycast/tools/re_kb/30_steam_function_map.surql`.

Every row is tagged **CONFIRMED** (both sides read by a human; `seeds.json`) or **INFERRED** (fingerprint / call-graph only; tiers high / medium / low). An INFERRED row is a hypothesis with its evidence and runner-up attached, not a fact.

## 1. Method

1. **Ghidra export** (`ghidra_export.py fetch|finger`): every one of the 29678 functions (`/list_functions`, `/disassemble_function`, `/get_function_by_address`, `/strings`) -> per-function fingerprint: immediates >= 0x100, f32/f64 constants (read from the dump at the rip-relative address), blk-relative displacements (register taint from `DAT_142edf560` = blk and `DAT_142edf580` = G = blk+0x3CB8, G offsets rebased to blk), DC-address-like immediates, string refs, struct displacements, callee list (in order).

2. **SH4 export** (`sh4_export.py`): 9607 routines from the bank asm (function starts = `;=====` separator labels + `bsr` targets + pool-held code pointers at clean boundaries); literal pools attributed by *reference* (`mov.l/mov.w/mova @(label,PC)`); `GameGlobalPointer`+offset and absolute 0x8C26xxxx accesses converted to Steam blk offsets through `blkmap.py`; struct displacements mapped through the fighter delta ladder.

3. **Match** (`match.py`): rarity-weighted token overlap (exact constants first: e.g. 812.357 = 0x444b16de, 0x0D82D000, 0xC10, table sizes), blk-offset set overlap, strings, weak struct-displacement overlap; then call-graph propagation (ordinal callee tokens, caller tokens, call-sequence sandwich alignment); mutual-best with margin and an evidence gate (a single shared constant or a single ordinal token cannot carry a pair). SH4 token sets are expanded with their small rarely-called callees because the recompile inlines them; an absorb pass then records those callees as `inlined` into the same Steam function. Two Ghidra mega-"functions" (`FUN_14006a3f0`, 186,634 insns; `caseD_0` at 0x1406415e0, 238,981 insns) are switch blobs and were excluded.

4. **Seeds**: 15 CONFIRMED pairs read on both sides (section 3) drive the propagation.

## 2. Coverage

| what | count |
|---|---|
| Steam functions total (Ghidra) | 29678 |
| Steam functions in the game range 0x140600000..0x1408E0000 (excluding the 2 mega blobs) | 10794 |
| ... of which carry any exact-constant / blk / DC-address token | 9236 |
| SH4 routines (marvelous2 banks) | 9607 |
| ... of which carry any exact-constant / blk / DC-address / string token | 1676 |
| **Steam functions with a primary SH4 counterpart** | **453** (game range: 444) |
| ... by tier (primary rows) | confirmed 21, high 204, medium 131, low 97 |
| all map rows incl. `inlined` (one Steam function can hold several SH4 routines) | 510 (confirmed 35, high 204, medium 140, low 131) |
| rows by method | fingerprint 106, fingerprint+callgraph 326, inlined 43, kb-seed+constants 1, kb-seed+decompile 5, seed 15, seed-inlined 14 |
| SH4 routines placed (matched or inlined) | 510 |

Honest reading: the map is dense around the render / object-pool / loader / NaomiLib core (where the anchors are) and sparse in character move code, whose SH4 side lives partly in the S_PLxx overlays (not in `bank*.asm`) and whose Steam side is largely swallowed by the `caseD_0` blob. Coverage there needs more seeds, not more heuristics.

## 3. CONFIRMED anchors (both sides read)

| Steam | SH4 | what | evidence |
|---|---|---|---|
| `FUN_14060c370` | `loc_8c032be0` (bank03) | bank loader (25 cases; case 1 = stage POL/TEX at DC 0x0D82D000/0x0D85D000) | CONFIRMED both read: bank loader. DC: switch on (r4-1) < 0x19 (25 cases, braf table at 8c032c3c), DC file addresses 0x0c420000 0x0c810000 0x0cc00000 0x0cd00000 0x0ce80000 ... in the pool; Steam FUN_14060c370: same case range (1..0x19), same DC addresses as immediates (0xc420000, 0xc810000, 0xcc00000, 0xcd00000, 0xce80000, 0xd82d000, 0xd85d000) passed to FUN_14060dcf0. |
| `FUN_1406129f0` | `loc_8c034bea` (bank03) | sprite submit: body path (sprite id bit15 clear) -> TA/D3D quads | CONFIRMED both read: sprite submit. DC 8c034bea: +0x144 sprite id == 0xFF(-1) -> return 0; tst 0x8000 -> 8c0344d4 (body) else 8c0348c8. Steam FUN_1406129f0: *(+0x188)==0xffffffff -> 0; (id>>15)&1==0 -> body path inline (0x7fff mask, 0x4000 flip, +0x124/0x128 screen, +0x130/0x134 scale, +0x154 facing, +0x178/0x17A) else conditional jump to FUN_140612f70. |
| `FUN_1406129f0` | `loc_8c0344d4` (bank03) | inlined into FUN_1406129f0 | per-frame BODY render (bit15 clear path), inlined as the main body of FUN_1406129f0 |
| `FUN_140619960` | `loc_8c0310f2` (bank03) | render-mode getter (*(blk+0x6CE4)) | CONFIRMED both read: render-mode getter. DC returns *(0x8c26a8e4) (0 if zero); Steam returns *(blk+0x6CE4). Establishes DC 0x8c26a8e4 <-> blk+0x6CE4 (delta 0x8C263C00). |
| `FUN_14061c6e0` | `loc_8c02e014` (bank02) | confirmed by another lane (KB) | KB (seed+constants): unique constant set {0x0F4A, 0x422c0000 (43.0), 0xbed1eb85 (-0.41), 0x42be0000 (95), 0x43a00000 (320)} in the pool at 8c02e014..; Steam FUN_14061c6e0 writes the same to blk+0x6914..0x6988 (WORLD-CAMERA-GHIDRA.md s5) / matcher: b:6978(11.0) b:6912(11.0) b:6974(10.8) b:6988(10.5) sw:35#2#0(9.9) k:31#10(9.9) k:30#8(9.9) b:6911(9.8) |
| `FUN_14061d6a0` | `loc_8c02e246` (bank02) | camera setup x0.1 for lists 7/8/9 | CONFIRMED both read: camera x0.1 (lists 7/8/9). DC: eye +0xC/10/14, look-at +0x54/58/5C scaled by 0x3dcccccd (0.1), fov +0x6C: fov*32768(0x47800000)/360(0x43b40000)+0.5 & 0xffff, near/far +0x80/+0x84; Steam FUN_14061d6a0 same sequence on blk+0x6914.. with the same constants. |
| `FUN_14061d7e0` | `loc_8c02e1a4` (bank02) | camera setup x1 (world units) from blk+0x6914..0x698C | CONFIRMED both read: camera x1 (deck, lists 5/6). DC loc_8c02e1a4: eye 0x8c26a518+0xC/10/14 and look-at +0x54/58/5C copied unscaled to the stack, then 8c1204f0(3), 8c121100, 8c121710(0, +0x80), 8c1219b0(fov: +0x6C*32768/360+0.5 & 0xffff), 8c1204f0(2), 8c121100, 8c11ff90(eye, lookat, +0x84), 8c1204f0(1). Steam FUN_14061d7e0: blk+0x6914/18/1C, 0x695C/60/64, FUN_140846e90(3), FUN_140847ca0, FUN_140848200(0, blk+0x6988), FUN_140847f20(fov from blk+0x6974 same formula), FUN_140846e90(2), FUN_140847ca0, FUN_140846c80(.., blk+0x698C), FUN_140846e90(1). Camera block delta 0x8C263C10. |
| `FUN_14061dbe0` | `loc_8c044f12` (bank04) | node alloc: free-list pop + constructor-table dispatch (kind 1 = append at tail) | CONFIRMED both read: node alloc = free-list pop + constructor-table dispatch. DC: 8c044f12 tests free count 0x8c287ae8>0 then 8c044f26: pop head (0x8c287a54, next=+0x8), dec both free counts, inc per-list count (table 0x8c045018), memset-like jsr, node+3=list, ctor table 0x8c045020[kind]. Steam FUN_14061dbe0: *(blk+0x2EEE4)>0 && *(0x2EEE6)!=0, pop blk+0x2EDD8, dec counts, inc blk+0x2EEC8[L], memset(node,0,0x280), node+3=L, PTR_caseD_4_140a6e5c8[kind]. |
| `FUN_14061dbe0` | `loc_8c044f26` (bank04) | inlined into FUN_14061dbe0 | alloc body (free-list pop + ctor dispatch) |
| `FUN_14061df40` | `loc_8c0450c0` (bank04) | node unlink + return to free list (clears +0x170 draw gate) | CONFIRMED both read: node unlink + return to free list. DC: clears byte +0x12C (mov.w pool 0x012c), fixes prev/next (+0x8/+0xC) or heads/tails tables, dec per-list count, push on free list; 468 DC call sites. Steam FUN_14061df40: +0x170=0, prev/next +0x8/+0x10, blk+0x2EDE8/0x2EE58 tables, dec blk+0x2EEC8[L], free tail blk+0x2EDE0, inc blk+0x2EEE4/6. |
| `FUN_14061e170` | `loc_8c044d8c` (bank04) | object-pool + render-state initialiser (256 x 0x280 nodes, 14 lists) | CONFIRMED both read: pool + render-state init. DC: bsr 8c044dce (pool init) then 5 memsets (r6 = 0x0C, w, w, 0x18, 0x10) and two byte clears. Steam FUN_14061e170: pool init inline (256 x 0x280 from blk+0x6DD8, free head/tail blk+0x2EDD8/E0, 14 heads/tails/counts, 0xF6/0x100), then zero blk+0x6CC4/0x6CCC, memset(blk+0x6908,0x180), memset(blk+0x6A88,0x22C), zero 0x6CE4/0x6CEC, DAT_142edf543=0, DAT_142edf546=0. |
| `FUN_14061e170` | `loc_8c044dce` (bank04) | inlined into FUN_14061e170 | object-pool initializer: base 0x8c26aa54 stride 0x1D0 x256 (consts 0x1d000/0x1ce30), free head/tail 0x8c287a54/58, heads 0x8c287a5c, tails 0x8c287a94, counts 0x8c287acc, free counts 0x8c287ae8=0xF6 /aea=0x100 -- pointer-scaled onto blk+0x2EDD8.. |
| `FUN_140620740` | `loc_8c0301ce` (bank03) | list matrix walker: composes each node's world matrix into node+0xA8 | CONFIRMED both read: list matrix walker. DC: heads table 0x8c287a5c[L] (== blk+0x2EDE8+L*8), per node bsr 8c0301f6, next = +0xC (== Steam +0x10). Steam FUN_140620740(L): same loop with the per-node matrix compose inlined. |
| `FUN_140620740` | `loc_8c0301f6` (bank03) | inlined into FUN_140620740 | per-node matrix compose (push, parent matrix, translate/billboard/rotate/scale, store +0xA8, pop) |
| `FUN_140620960` | `loc_8c030858` (bank03) | per-frame render dispatcher (mode 0: sprite walk, deck, lists 5-8, HUD; mode 1: list 9) | CONFIRMED both read: per-frame render dispatcher. DC: jsr 8c0310f2 (mode) -> mode1: 8c030d56 / mode0: 8c0308c2 walker, test G+0x98 blackout (mov.w 0x98), 8c030cc0 deck+list5, 8c030d12, 8c030d24, 8c030d36, 8c030dcc HUD; then G+0x2E==1 -> jmp 8c031470. Steam FUN_140620960: FUN_140619960 mode, FUN_140620f10, *(G+0x98)==0, blk+0x6D04!=8, camera/push/identity/colour/model0/pop, lists 5,6,7,8, FUN_140620ea0; g_offs 0x3CE6 (=G+0x2E). |
| `FUN_140620960` | `loc_8c030cc0` (bank03) | inlined into FUN_140620960 | deck draw block: STG_ID!=8 -> 8c02e1a4 camera, 8c120950(0) push, 8c121100 identity, 8c030cfc colour, 8c1235e0(model0), 8c120900(1) pop; then bsr list-5 trio == the inline block at 0x140620a4c.. in FUN_140620960 |
| `FUN_140620960` | `loc_8c030cfc` (bank03) | inlined into FUN_140620960 | loads deck vertex colour fr4/5/6 from 0x8c26a8a4+4/8/C -> Steam FUN_140849b00(blk+0x6CA8,0x6CAC,0x6CB0) |
| `FUN_140620960` | `loc_8c030d12` (bank03) | inlined into FUN_140620960 | list 5 trio: 8c02e1a4 camera + 8c0301ce(5) + 8c030410(5) == FUN_14061d7e0; FUN_140620740(5); FUN_140620cd0(5) |
| `FUN_140620960` | `loc_8c030d24` (bank03) | inlined into FUN_140620960 | list 6 trio (camera x1) |
| `FUN_140620960` | `loc_8c030d36` (bank03) | inlined into FUN_140620960 | lists 7 and 8 with 8c02e246 camera x0.1 == FUN_14061d6a0 path |
| `FUN_140620960` | `loc_8c030d56` (bank03) | inlined into FUN_140620960 | mode-1 path: 8c02e246 camera x0.1 + list 9 |
| `FUN_140620cd0` | `loc_8c030410` (bank03) | list draw walker: draws each node with +0x170 gate and +0xA0 object | CONFIRMED both read: list draw walker. DC: per node test +woff(0x12c) gate and +woff(obj) then optional +0x28 callback (8c0305ce) and 8c030452 draw; Steam FUN_140620cd0: +0x170 && +0xA0, optional +0x40 callback, draw body inlined. |
| `FUN_140620cd0` | `loc_8c030452` (bank03) | inlined into FUN_140620cd0 | per-node draw body (push, load +0xA8 matrix, scale, colour select, draw kind, pop) |
| `FUN_140620cd0` | `loc_8c0305ce` (bank03) | inlined into FUN_140620cd0 | call node +0x28 callback (== Steam node +0x40 callback) |
| `FUN_140620ea0` | `loc_8c030dcc` (bank03) | HUD (list 0xB) then per-fighter 3D part nodes (list 0xC) | CONFIRMED both read: HUD (list 0xB) then list 0xC. DC: 8c02e334 camera + 8c0301ce(0xB) + 8c030410(0xB); *(G+0x14)==0x40 skip else 8c030d68 walks heads[12]=0x8c287a8c (== blk+0x2EE48) nodes with +0x12C gate and jsr 8c0f215e. Steam: FUN_14061d5b0, FUN_140620740(0xB), FUN_140620cd0(0xB), *(G+0x14)!=0x40 -> walk blk+0x2EE48 with +0x170 -> FUN_140653a70. |
| `FUN_140620f10` | `loc_8c0308c2` (bank03) | sprite walker over the 16 draw lists (System B); inlines Render Main Sprite + effect path | CONFIRMED both read: sprite walker over the 16 draw lists. DC: handles 0x8c287de0 stride 0x180 (mov.w 0x0180), counts 0x8c2895e0, node+3 category==0 -> 8c03093c else 8c030af8. Steam: blk+0x2F4D0 stride 0x300, counts blk+0x324D0, node+3, +0x170 gate, both render bodies inlined (812.357 / 480 / 640 / 1000 / 0.1 / 0.001 constants present on both sides). |
| `FUN_140620f10` | `loc_8c03093c` (bank03) | inlined into FUN_140620f10 | Render Main Sprite: +0x12C draw gate == Steam +0x170; camera constant 812.357 (0x444b16de) at bank03.asm:1513 == blk+0x691C |
| `FUN_140620f10` | `loc_8c030af8` (bank03) | inlined into FUN_140620f10 | effect-path renderer (category!=0), same constant set, stride 0x5A4 == Steam 0x738 |
| `FUN_140846c80` | `loc_8c11ff90` (bank11) | confirmed by another lane (KB) | KB (seed+decompile): same args (eye, target, u16 roll) and call slot; SH4 computes target-eye, normalises, translates by -eye via 8C1210C0 (WORLD-CAMERA-GHIDRA.md s1/2.2) / matcher: sw:11#0#4(9.9) sw:10#0#4(9.9) k:11#4(9.9) k:10#4(9.9) kl:11#-1(7.9) kl:10#-1(7.9) ko:11(4.1) ko:10(4.1) |
| `FUN_140846e90` | `loc_8c1204f0` (bank12) | confirmed by another lane (KB) | KB (seed+decompile): same call slot/args in loc_8c02e1a4 vs FUN_14061d7e0; SH4 saves XMTRX to slot, sets mode byte 0x8C2D68E4, reloads via 8C1201E0; Steam moves DAT_142ef0ab8 to ctx+0x1f80ac+m*0x40 (WORLD-CAMERA-GHIDRA.md s1) / matcher: sw:11#0#0(9.9) sw:10#0#0(9.9) k:11#0(9.9) k:10#0(9.9) kl:11#-5(7.9) kl:10#-5(7.9) ko:11(4.1) ko:10(4.1) |
| `FUN_1408478c0` | `loc_8c120900` (bank12) | NaomiLib matrix stack POP(n) | CONFIRMED both read: NaomiLib matrix POP(n). DC: n=max(n,1), count-=n clamped, ptr-=n*0x40, reload XMTRX. Steam FUN_1408478c0: loop n: ptr-=0x40, copy to current, free-count++. |
| `FUN_140847950` | `loc_8c120950` (bank12) | NaomiLib matrix stack PUSH (optional load) | CONFIRMED both read: NaomiLib matrix PUSH. DC: stack {i16 count,i16 max,ptr@+8} at 0x8C2D68E8, saves XMTRX (fschg/frchg 8 pairs) to ptr, ptr+=0x40, count++, optional load from r4. Steam FUN_140847950: ptr ctx+0x1f81b0, free-count ctx+0x1f81bc--, copies DAT_142ef0ab8 (current 4x4), optional load from param. |
| `FUN_140847ca0` | `loc_8c121100` (bank12) | confirmed by another lane (KB) | KB (seed+decompile): both write the identity (WORLD-CAMERA-GHIDRA.md s1) / matcher: sw:11#0#1(9.9) sw:10#0#1(9.9) k:11#1(9.9) k:10#1(9.9) kl:11#-4(7.9) kl:10#-4(7.9) ko:11(4.1) ko:10(4.1) |
| `FUN_140847f20` | `loc_8c1219b0` (bank12) | confirmed by another lane (KB) | KB (seed+decompile): same 4 args (angle u16, aspect, near, far) and call slot; Steam closed form read; SH4 body uses sin/atan/cos helpers 8C11EB20/8C11E170/8C11E2E0 and ftrv loader 8C120540 (not reduced) (WORLD-CAMERA-GHIDRA.md s1/2.1) / matcher: sw:11#0#3(9.9) sw:10#0#3(9.9) k:11#3(9.9) k:10#3(9.9) kl:11#-2(7.9) kl:10#-2(7.9) ko:11(4.1) ko:10(4.1) |
| `FUN_140848200` | `loc_8c121710` (bank12) | confirmed by another lane (KB) | KB (seed+decompile): SH4 stores fabs(fr4),fabs(fr5) to 0x8C16BD80/84 (consumed by 8C1219B0); Steam stores to ctx+0x1f8240/44 (consumed by FUN_140847f20); same call slot (WORLD-CAMERA-GHIDRA.md s1) / matcher: sw:11#0#2(9.9) sw:10#0#2(9.9) k:11#2(9.9) k:10#2(9.9) kl:11#-3(7.9) kl:10#-3(7.9) ko:11(4.1) ko:10(4.1) |

### Block-map corrections found by this crawl (all from pairs above)

* **Pool-tail bookkeeping is pointer-scaled, not a flat delta.** DC `0x8C287A54` free_head(4) free_tail(4) heads[14](4) tails[14](4) counts[14](2) freecnt(2) freecnt2(2) <-> Steam `blk+0x2EDD8` with 8-byte pointers (`loc_8c044dce` <-> `FUN_14061e170`). The memory note's flat delta 0x8C258910 for `..0x2F4D0` only holds at the draw-list base; draw-list handles are also 4 -> 8 B (`0x8C287DE0 + L*0x180 + i*4` <-> `blk+0x2F4D0 + L*0x300 + i*8`).
* **The stage/camera struct (DC 0x8C26A518..0x8C26AA54) is piecewise:** camera block delta 0x8C263C10 (eye +0xC/10/14 -> blk+0x6914/18/1C, look-at +0x54.. -> 0x695C.., fov +0x6C -> 0x6974, near/far +0x80/84 -> 0x6988/8C; `loc_8c02e246`/`8c02e1a4` <-> `FUN_14061d6a0`/`FUN_14061d7e0`), deck colour + render mode delta 0x8C263C00 (0x8c26a8a8 -> 0x6CA8, 0x8c26a8e4 -> 0x6CE4), STG_ID delta 0x8C263C58 (0x8c26a95c -> 0x6D04), LayerZ delta 0x8C263C6C (0x8c26a974 -> 0x6D08). `blkmap.py` returns None for the un-anchored parts of that range on purpose.
* `loc_8c0450c0` (468 DC call sites) is the node **unlink/free** (`FUN_14061df40`), `loc_8c044f12`+`8c044f26` the **alloc** (`FUN_14061dbe0`); `FUN_140612f70` is not a separate routine but the sprite-id-bit15-set path of `loc_8c034bea` that Ghidra split off `FUN_1406129f0` (reached by a conditional jump at 0x140612a02).

## 4. Render-relevant Steam functions and their SH4 counterparts

Steam functions (game range) that touch blk 0x3CB8..0x6D10 (globals/camera), 0x2EDD8..0x2EEE8 (node-pool lists), 0x2F4D0..0x324F8 (draw list) or fighter-array fields >= 0x120 (absolute `blk+0x3DB8+i*0x738+off` references; functions that reach fighter fields only through a pointer register are not detectable this way and are not listed). 898 functions; UNMATCHED means no SH4 counterpart was found by the matcher, not that none exists.

| Steam | touches | blk offsets (first 10) | SH4 counterpart(s) | tier |
|---|---|---|---|---|
| `FUN_140607da0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4310,0x4318,0x4330,0x4400) | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cd0 0x3cd3 0x3ce0 0x3ce1 0x3ce8 0x3cec | UNMATCHED | - |
| `FUN_140607e90` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4310,0x4318,0x4330,0x4400) | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cd0 0x3d39 0x3d44 0x4310 0x4318 0x4330 | UNMATCHED | - |
| `FUN_140608690` | globals/camera 0x3CB8..0x6D10 | 0x3cd3 0x3ce0 0x3ce1 0x3ce8 0x3cec 0x3cf0 0x3cf4 0x3cfe 0x3d01 0x3d05 | UNMATCHED | - |
| `FUN_140608bf0` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 0x3db8 0x44f0 0x4c28 0x5360 0x5a98 0x61d0 | UNMATCHED | - |
| `FUN_140608d40` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 | UNMATCHED | - |
| `FUN_140608f30` | globals/camera 0x3CB8..0x6D10 | 0x3cfb | `loc_8c041c08` | medium |
| `FUN_1406090a0` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb 0x3cfd | `loc_8c0420b8` | medium |
| `FUN_140609250` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | UNMATCHED | - |
| `FUN_1406092b0` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb 0x3cfd | `loc_8c04218c` | medium |
| `FUN_140609510` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | UNMATCHED | - |
| `FUN_140609570` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | `loc_8c04257c` | medium |
| `FUN_1406095f0` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | `loc_8c04223a` | medium |
| `FUN_140609990` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb 0x3cfd | `loc_8c041f5c` | medium |
| `FUN_140609c60` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | `loc_8c04255a` | medium |
| `FUN_140609df0` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | `loc_8c041dde` | high |
| `FUN_140609e30` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3ce5 0x3cfb | `loc_8c041e44` | high |
| `FUN_140609f10` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3cfb | `loc_8c042538` | medium |
| `FUN_14060a1f0` | globals/camera 0x3CB8..0x6D10 | 0x3cd2 0x3cd4 0x3cd8 | `loc_8c03589a`; `loc_8c0358be` (inlined) | high/low |
| `FUN_14060af70` | globals/camera 0x3CB8..0x6D10 | 0x3ccc 0x3ce1 0x3ce3 0x3ce7 0x3ce8 0x3cec 0x3cf8 0x3cfa 0x3d11 0x6d04 | UNMATCHED | - |
| `FUN_14060b3d0` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba | UNMATCHED | - |
| `FUN_14060b400` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba | UNMATCHED | - |
| `FUN_14060b440` | globals/camera 0x3CB8..0x6D10 | 0x3cd3 0x3ce2 0x3cfa 0x3cfb 0x3cfc 0x3cfd 0x3cfe 0x3cff 0x3d00 0x3d01 | UNMATCHED | - |
| `FUN_14060b7d0` | globals/camera 0x3CB8..0x6D10 | 0x3cc8 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc4 0x3ce1 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x41a8,0x4478,0x44b0) | 0x3cb9 0x3cba 0x3ccc 0x3ce2 0x3cfc 0x3d02 0x3d04 0x3d05 0x41a8 0x4478 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc4 0x3ce1 | UNMATCHED | - |
| `FUN_14060c070` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | UNMATCHED | - |
| `FUN_14060c370` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x3fb0,0x4478) | 0x3ce1 0x3d14 0x3d3c 0x3d47 0x3d4c 0x3d53 0x3d65 0x3fb0 0x4478 0x6d04 | `loc_8c032be0`; `loc_8c032364` (inlined) | confirmed/low |
| `FUN_14060d470` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | `loc_8c0322d4` - DM00 compactor | high |
| `FUN_14060d560` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | `loc_8c032696` | high |
| `FUN_14060df00` | globals/camera 0x3CB8..0x6D10 | 0x3d3c | UNMATCHED | - |
| `FUN_14060e170` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4330,0x4334,0x440d,0x4468) | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3ccc 0x3cd0 | `loc_8c03de54`; `loc_8c03e594` (inlined); `loc_8c031bba` (inlined); `loc_8c0370a4` (inlined); `loc_8c038dd4` (inlined); `loc_8c03e97c` (inlined); `loc_8c046abc` (inlined); `loc_8c04ebb8` (inlined) | high/medium/low |
| `FUN_14060e190` | globals/camera 0x3CB8..0x6D10 | 0x3ce4 0x3d39 0x6d04 | UNMATCHED | - |
| `FUN_14060e250` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd0 0x3ce4 0x3ce6 0x3d04 0x3d39 | UNMATCHED | - |
| `FUN_14060e3f0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4330,0x4334,0x4a68,0x4a6c) | 0x3cba 0x3cc0 0x3ce6 0x3d38 0x3d48 0x4330 0x4334 0x4a68 0x4a6c 0x51a0 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478,0x4489,0x52e8,0x6158) | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd0 0x3cd1 0x3ce2 0x3d04 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cd1 0x3d3f 0x3d48 0x3d50 0x3dbc 0x44f4 0x4c2c 0x5364 0x5a9c | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3ccc 0x3cd1 0x3d48 0x3db8 0x6d04 | `loc_8c03dcba` | medium |
| `caseD_7` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x44a4,0x4bdc) | 0x3d04 0x3d3c 0x3d44 0x3d46 0x3d48 0x44a4 0x4bdc 0x324e0 | UNMATCHED | - |
| `FUN_14060efd0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cd1 0x3d48 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3d50 0x6909 0x690a | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3ce6 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4468,0x4469,0x4478) | 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd1 0x3d01 0x3d39 0x3d3c 0x3d3e | `loc_8c03d9a0` | medium |
| `FUN_14060fa00` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `FUN_14060fb90` | globals/camera 0x3CB8..0x6D10 | 0x3d04 | `loc_8c0331d8` | high |
| `FUN_1406101b0` | globals/camera 0x3CB8..0x6D10 | 0x6ca8 0x6cac 0x6cb0 0x6cb4 0x6cb8 0x6cb9 0x6cba 0x6cbc 0x6cbd 0x6cbe | UNMATCHED | - |
| `FUN_140610480` | globals/camera 0x3CB8..0x6D10 | 0x6cb4 0x6cb8 0x6cbc | `loc_8c02dc32` | high |
| `FUN_1406104b0` | globals/camera 0x3CB8..0x6D10 | 0x6cb4 0x6cb8 | `loc_8c02dc1c` | high |
| `FUN_1406104d0` | globals/camera 0x3CB8..0x6D10 | 0x6c9c 0x6ca4 0x6ca8 0x6cac 0x6cb0 | `loc_8c030f24` | high |
| `FUN_140610530` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6ca8 0x6cac 0x6cb0 0x324e6 | `loc_8c030f54` | high |
| `FUN_1406105a0` | globals/camera 0x3CB8..0x6D10 | 0x6ca8 0x6cac 0x6cb0 | `loc_8c030f44` | high |
| `FUN_1406105d0` | globals/camera 0x3CB8..0x6D10 | 0x6cd0 0x6cd4 0x6cd8 0x6cdc 0x6ce0 | `loc_8c0355b2` | high |
| `FUN_140610630` | globals/camera 0x3CB8..0x6D10 | 0x6cd0 0x6cd8 0x6ce0 | `loc_8c0355a8` | high |
| `FUN_140610650` | globals/camera 0x3CB8..0x6D10 | 0x6cd0 0x6cd4 0x6cd8 0x6cdb 0x6cdc 0x6ce0 | `loc_8c0355c2` | medium |
| `FUN_140610730` | globals/camera 0x3CB8..0x6D10 | 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 0x6a98 0x6ca8 0x6cac 0x6cb0 | `loc_8c030e3a` | high |
| `FUN_140610840` | globals/camera 0x3CB8..0x6D10 | 0x6a88 | UNMATCHED | - |
| `FUN_140610870` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4400,0x440c,0x4468,0x4b38) | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cc2 0x3cc4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cc0 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc0 | UNMATCHED | - |
| `FUN_140610c80` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3ccc 0x3cd2 0x3d06 0x3d45 | `loc_8c035b2e` | medium |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cc0 0x6908 0x690f 0x6910 | `loc_8c03619c`; `loc_8c036142` (inlined) | high/medium |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc0 | UNMATCHED | - |
| `FUN_140611040` | globals/camera 0x3CB8..0x6D10 | 0x3cba | UNMATCHED | - |
| `FUN_140611100` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4400,0x440c,0x4468,0x4b38) | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cc2 0x3cc4 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cc0 0x3cc2 0x6a88 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc0 0x3cc2 0x6a94 | `loc_8c035db0`; `loc_8c0360fa` (inlined) | high/low |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x6a88 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 | UNMATCHED | - |
| `FUN_1406119b0` | globals/camera 0x3CB8..0x6D10 | 0x3cba | UNMATCHED | - |
| `FUN_140611a20` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cc2 0x3cc4 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cc2 0x3cc4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cd0 0x3cd1 0x3ce4 0x3ce6 0x3d06 0x3d07 0x3d30 0x3d3b 0x3d3d | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cba | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3d08 0x3d39 0x3d3c 0x3d3d | UNMATCHED | - |
| `FUN_140613390` | globals/camera 0x3CB8..0x6D10 | 0x3cdc 0x6d08 0x6d0c | `loc_8c0338ec` | high |
| `FUN_1406146d0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | `loc_8c035162` | high |
| `FUN_140614b70` | globals/camera 0x3CB8..0x6D10 | 0x3d44 0x3d46 | UNMATCHED | - |
| `FUN_140614bf0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_140614c30` | globals/camera 0x3CB8..0x6D10 | 0x3cc8 0x3cd1 0x3d04 0x3d43 0x3d65 | `loc_8c040a84` | high |
| `FUN_140614cc0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4489,0x448a) | 0x3cbc 0x3cbd 0x3cc0 0x3cc2 0x3cc4 0x3cc6 0x3cd0 0x3cd1 0x3ce2 0x3d3c | `loc_8c040b20` | high |
| `FUN_140614fa0` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3d3c | UNMATCHED | - |
| `FUN_140615020` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4489,0x448a) | 0x3cbc 0x3cbd 0x3cc0 0x3cc2 0x3cc4 0x3cc6 0x3ccc 0x3ce2 0x3d53 0x4489 | `loc_8c040788` | high |
| `FUN_140615760` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x446b,0x4478,0x4480,0x4484) | 0x3cbb 0x3ce4 0x3d43 0x3d47 0x3d53 0x3d65 0x3db8 0x446b 0x4478 0x4480 | `loc_8c040d86` | medium |
| `FUN_140615930` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3cc0 0x3cc2 0x3cc4 0x3cc6 | `loc_8c040eec` | medium |
| `FUN_140615a40` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3ce4 | UNMATCHED | - |
| `FUN_140615cf0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4478,0x527d,0x52e8) | 0x3d04 0x3d40 0x3d53 0x440d 0x4478 0x527d 0x52e8 0x60ed 0x6158 | UNMATCHED | - |
| `FUN_140616050` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4478,0x527d,0x52e8) | 0x3d40 0x440d 0x4478 0x527d 0x52e8 0x60ed 0x6158 | UNMATCHED | - |
| `FUN_1406163e0` | globals/camera 0x3CB8..0x6D10 | 0x3d4c 0x3d65 0x6d04 | `loc_8c03a004` | medium |
| `FUN_140616610` | globals/camera 0x3CB8..0x6D10 | 0x3d4c | UNMATCHED | - |
| `FUN_140616730` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x3ce1 0x3d4c 0x4478 | UNMATCHED | - |
| `FUN_140616960` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x3d4c 0x4478 | UNMATCHED | - |
| `FUN_1406169f0` | globals/camera 0x3CB8..0x6D10 | 0x3d4c 0x3d65 | `loc_8c039c64` | high |
| `FUN_140617ca0` | globals/camera 0x3CB8..0x6D10 | 0x3d4c | `loc_8c039a74` | high |
| `FUN_140618460` | globals/camera 0x3CB8..0x6D10 | 0x3d4c | `loc_8c0273f4` | high |
| `FUN_140618ab0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x448c,0x448d,0x448e,0x448f) | 0x3cbb 0x3d04 0x448c 0x448d 0x448e 0x448f | `loc_8c031504` | high |
| `FUN_140619370` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | `loc_8c031470` | medium |
| `FUN_140619830` | globals/camera 0x3CB8..0x6D10 | 0x3d14 | `loc_8c03221a` | low |
| `FUN_140619840` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4434,0x4444,0x4b6c,0x4b7c) | 0x4434 0x4444 0x4b6c 0x4b7c 0x52a4 0x52b4 0x59dc 0x59ec 0x6114 0x6124 | UNMATCHED | - |
| `FUN_140619910` | globals/camera 0x3CB8..0x6D10 | 0x3ce0 0x6ce8 0x6cec 0x6cf0 | UNMATCHED | - |
| `FUN_140619970` | globals/camera 0x3CB8..0x6D10 | 0x6ce4 0x6ce8 0x6cec | UNMATCHED | - |
| `FUN_140619a80` | globals/camera 0x3CB8..0x6D10 | 0x6ce8 0x6cec 0x6cf0 | `loc_8c031008` | medium |
| `FUN_140619ac0` | globals/camera 0x3CB8..0x6D10 | 0x6ce8 0x6cec 0x6cf0 | `loc_8c031018` | medium |
| `FUN_140619b00` | globals/camera 0x3CB8..0x6D10 | 0x3ce0 0x6ce8 0x6cec 0x6cf0 | `loc_8c030fae` | high |
| `FUN_140619b50` | globals/camera 0x3CB8..0x6D10 | 0x6ce8 0x6cec 0x6cf0 | UNMATCHED | - |
| `FUN_140619b80` | globals/camera 0x3CB8..0x6D10 | 0x6ce8 0x6cec 0x6cf0 | UNMATCHED | - |
| `FUN_140619dd0` | globals/camera 0x3CB8..0x6D10 | 0x6918 0x691c 0x6960 0x6964 0x6980 0x69b8 0x69bc 0x69c4 0x69c8 0x6a08 | UNMATCHED | - |
| `FUN_140619fe0` | globals/camera 0x3CB8..0x6D10 | 0x69b4 0x69c0 0x69fc 0x69fd | UNMATCHED | - |
| `FUN_14061a0c0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x695c 0x69b4 0x69c0 0x6a08 0x6a18 0x6a24 | UNMATCHED | - |
| `FUN_14061a1a0` | globals/camera 0x3CB8..0x6D10 | 0x6918 0x691c 0x6960 0x6964 0x6980 0x69b8 0x69bc 0x69c4 0x69c8 0x6a08 | UNMATCHED | - |
| `FUN_14061a370` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x695c 0x69b4 0x69c0 0x6a10 0x6a18 0x6a24 | UNMATCHED | - |
| `FUN_14061a450` | globals/camera 0x3CB8..0x6D10 | 0x6918 0x691c 0x6960 0x6964 0x6980 0x69b8 0x69bc 0x69c4 0x69c8 0x6a10 | UNMATCHED | - |
| `FUN_14061ac50` | globals/camera 0x3CB8..0x6D10 | 0x6909 0x690a 0x6a08 0x6a10 | `loc_8c02fd26` | high |
| `FUN_14061acc0` | globals/camera 0x3CB8..0x6D10 | 0x6909 0x6a08 0x6a10 | UNMATCHED | - |
| `FUN_14061ad10` | globals/camera 0x3CB8..0x6D10 | 0x690a 0x6a08 0x6a10 | UNMATCHED | - |
| `FUN_14061ad60` | globals/camera 0x3CB8..0x6D10 | 0x6909 0x690a 0x6a01 0x6a08 0x6a10 | `loc_8c02fec4` | high |
| `FUN_14061ae80` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x6918 0x691c 0x695c 0x6960 0x6964 0x69cc 0x69d0 0x69d4 0x69fe | UNMATCHED | - |
| `FUN_14061b8e0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x6918 0x691c 0x695c 0x6960 0x6964 0x698c 0x69d8 0x69dc 0x69e0 | UNMATCHED | - |
| `FUN_14061c0a0` | globals/camera 0x3CB8..0x6D10 | 0x690f 0x6910 0x6911 0x6914 0x6918 0x691c 0x695c 0x6960 0x6964 0x69b4 | UNMATCHED | - |
| `FUN_14061c660` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `FUN_14061c6e0` | globals/camera 0x3CB8..0x6D10 | 0x6908 0x690f 0x6910 0x6911 0x6912 0x6914 0x6918 0x691c 0x695c 0x6960 | `loc_8c02e014` (inlined) | confirmed |
| `FUN_14061ca70` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6908 0x6909 0x690a 0x690c 0x690d 0x690e 0x690f 0x6910 0x6911 0x6912 | `loc_8c02e3c8`; `loc_8c02e4ac` (inlined); `loc_8c02fa88` (inlined); `loc_8c02fde0` (inlined); `loc_8c0300ba` (inlined) | low |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690f | UNMATCHED | - |
| `FUN_14061caf0` | globals/camera 0x3CB8..0x6D10 | 0x6908 0x690f 0x6910 0x6911 0x6912 0x6914 0x6918 0x691c 0x695c 0x6960 | UNMATCHED | - |
| `FUN_14061ce90` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6909 0x690a 0x690c 0x690d 0x690e 0x6914 0x6918 0x691c 0x6920 0x6928 | UNMATCHED | - |
| `FUN_14061d540` | globals/camera 0x3CB8..0x6D10 | 0x690f 0x6910 0x6911 0x69fc 0x69fd 0x69fe 0x69ff | UNMATCHED | - |
| `FUN_14061d620` | globals/camera 0x3CB8..0x6D10 | 0x695c | `loc_8c02e378` | high |
| `FUN_14061d6a0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x6918 0x691c 0x695c 0x6960 0x6964 0x6974 0x6988 0x698c | `loc_8c02e246` | confirmed |
| `FUN_14061d7e0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x6918 0x691c 0x695c 0x6960 0x6964 0x6974 0x6988 0x698c | `loc_8c02e1a4` | confirmed |
| `FUN_14061d900` | globals/camera 0x3CB8..0x6D10; node-pool lists 0x2EDD8..0x2EEE8; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cc6 0x3cd1 0x3d3c | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cc0 0x3cc6 0x3d46 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cc0 0x3cc6 0x3d46 0x324e6 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd1 0x3d3c 0x3d45 0x3d46 | UNMATCHED | - |
| `FUN_14061dbe0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2edd8 0x2ede0 0x2eec8 0x2eee4 0x2eee6 | `loc_8c044f12` - TA poly-record ALLOCATOR (called by every HUD sub-builder, r5=list 0x0B r6=1); `loc_8c044f26` (inlined) | confirmed |
| `FUN_14061de60` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2edd8 0x2ede0 0x2eec8 0x2eee4 0x2eee6 | `loc_8c10589a` | medium |
| `FUN_14061df40` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2edd8 0x2ede0 0x2ede8 0x2ee58 0x2eec8 0x2eee4 0x2eee6 | `loc_8c0450c0` | confirmed |
| `FUN_14061e030` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2edd8 0x2ede0 0x2ede8 0x2ee58 0x2eec8 0x2eee4 0x2eee6 | `loc_8c044e56` | high |
| `FUN_14061e170` | globals/camera 0x3CB8..0x6D10; node-pool lists 0x2EDD8..0x2EEE8 | 0x6cc4 0x6ccc 0x6ce4 0x6cec 0x2edd8 0x2ede0 0x2ede8 0x2edf0 0x2edf8 0x2ee00 | `loc_8c044d8c`; `loc_8c044dce` (inlined) - object-pool initializer | confirmed |
| `FUN_14061e560` | draw list handles/counts 0x2F4D0..0x324F8 | 0x2f4d0 0x324d0 | UNMATCHED | - |
| `FUN_14061e690` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324d0 0x324d1 0x324d2 0x324d3 0x324d4 0x324d5 0x324d6 0x324d7 0x324d8 0x324d9 | UNMATCHED | - |
| `FUN_14061e780` | draw list handles/counts 0x2F4D0..0x324F8 | 0x2f4d0 0x324d0 | UNMATCHED | - |
| `FUN_14061e880` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4452) | 0x4452 | `loc_8c047594` | medium |
| `FUN_14061e8f0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4452,0x4b8a) | 0x3ce1 0x3d43 0x4452 0x4b8a | UNMATCHED | - |
| `FUN_14061e9d0` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 0x3ce6 0x3d39 0x3d3c 0x3d43 0x3db8 0x44f0 | `loc_8c0473b0` | medium |
| `FUN_14061eb00` | globals/camera 0x3CB8..0x6D10 | 0x3ce6 0x3d3b | UNMATCHED | - |
| `FUN_14061f030` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4078,0x4228,0x47b0,0x4960) | 0x3cd4 0x3d50 0x3d62 0x3db8 0x4078 0x4228 0x44f0 0x47b0 0x4960 0x4c28 | `loc_8c043cdc`; `loc_8c044c4a` (inlined); `loc_8c043e30` (inlined); `loc_8c043fb8` (inlined); `loc_8c044944` (inlined); `loc_8c044ccc` (inlined) | high/medium/low |
| `FUN_14061f9e0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `FUN_140620070` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | `loc_8c04419c` | low |
| `FUN_140620190` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x3f28) | 0x3db8 0x3f28 | UNMATCHED | - |
| `FUN_140620200` | globals/camera 0x3CB8..0x6D10 | 0x6a88 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 0x6ca8 0x6cac 0x6cb0 0x6cc4 | `loc_8c045ce0`; `loc_8c108426` (inlined) | high/low |
| `FUN_140620420` | globals/camera 0x3CB8..0x6D10 | 0x3d48 0x6a8c 0x6a94 0x6cc5 0x6d04 | UNMATCHED | - |
| `FUN_140620740` | globals/camera 0x3CB8..0x6D10; node-pool lists 0x2EDD8..0x2EEE8 | 0x6920 0x6924 0x6928 0x2ede8 | `loc_8c0301ce`; `loc_8c0301f6` (inlined) | confirmed |
| `FUN_140620960` | globals/camera 0x3CB8..0x6D10 | 0x3ce6 0x3d50 0x6ca8 0x6cac 0x6cb0 0x6d04 | `loc_8c030858`; `loc_8c030cc0` (inlined); `loc_8c030cfc` (inlined); `loc_8c030d12` (inlined); `loc_8c030d24` (inlined); `loc_8c030d36` (inlined); `loc_8c030d56` (inlined) | confirmed |
| `FUN_140620ad0` | globals/camera 0x3CB8..0x6D10 | 0x3d46 | UNMATCHED | - |
| `FUN_140620b40` | globals/camera 0x3CB8..0x6D10 | 0x3d46 | UNMATCHED | - |
| `FUN_140620c70` | globals/camera 0x3CB8..0x6D10 | 0x6cd8 | `loc_8c030df0` | low |
| `FUN_140620cd0` | globals/camera 0x3CB8..0x6D10; node-pool lists 0x2EDD8..0x2EEE8 | 0x6ca8 0x6cac 0x6cb0 0x2ede8 | `loc_8c030410`; `loc_8c030452` (inlined); `loc_8c0305ce` (inlined); `loc_8c030550` (inlined) | confirmed/medium |
| `FUN_140620ea0` | globals/camera 0x3CB8..0x6D10 | 0x3ccc | `loc_8c030dcc` | confirmed |
| `FUN_140620f10` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x3f78) | 0x3cdc 0x3f78 0x6928 0x6d08 0x324d0 | `loc_8c0308c2` - Render_sprites (slot-table walker); `loc_8c03093c` (inlined) - Render Main Sprite (PER-FRAME, per-object); `loc_8c030af8` (inlined) | confirmed |
| `FUN_140621430` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 0x324e1 | `loc_8c045790` | high |
| `FUN_1406215c0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 0x324e1 | `loc_8c05b642` | high |
| `FUN_140621690` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3db8 0x324e0 | UNMATCHED | - |
| `FUN_140621c90` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x3fe2,0x3fe3,0x3ff8,0x4000) | 0x3fe2 0x3fe3 0x3ff8 0x4000 | UNMATCHED | - |
| `FUN_140622190` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_140622370` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_140622500` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_140622530` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_1406226b0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140622720` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c0505b8` | low |
| `FUN_140622e10` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x44f0 0x5360 0x61d0 0x324e6 | `loc_8c04f628` | high |
| `FUN_140622f60` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_140623100` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x3f28,0x3f29,0x4049,0x404b) | 0x3db8 0x3db9 0x3dba 0x3e08 0x3f28 0x3f29 0x4049 0x404b 0x4082 0x4321 | `loc_8c04ecee` | high |
| `FUN_1406233b0` | globals/camera 0x3CB8..0x6D10 | 0x3d10 | `loc_8c04eafc` | high |
| `FUN_140624440` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69a0 | `loc_8c0502a4` | high |
| `FUN_1406246e0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69a8 | UNMATCHED | - |
| `FUN_1406247f0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69a8 | UNMATCHED | - |
| `FUN_140624910` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x3ee8,0x3eec,0x3f04,0x3f29) | 0x3dba 0x3e04 0x3e08 0x3e0c 0x3e10 0x3ee8 0x3eec 0x3f04 0x3f29 0x3f2a | UNMATCHED | - |
| `FUN_140624be0` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `FUN_140624cc0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | `loc_8c04fd92` | high |
| `FUN_140624d90` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4469,0x447b,0x4ba1,0x4bb3) | 0x4469 0x447b 0x4ba1 0x4bb3 | UNMATCHED | - |
| `FUN_140624f40` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_140625110` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_140625680` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690b 0x690c 0x690d 0x690e 0x324e6 | UNMATCHED | - |
| `FUN_140625ed0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_b` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d50 0x324e6 | UNMATCHED | - |
| `FUN_1406265f0` | globals/camera 0x3CB8..0x6D10 | 0x3d50 | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d50 0x324e6 | UNMATCHED | - |
| `FUN_140626bb0` | globals/camera 0x3CB8..0x6D10 | 0x3d40 | `loc_8c0469c8` | medium |
| `FUN_140626c20` | globals/camera 0x3CB8..0x6D10 | 0x3d3c 0x3d50 | `loc_8c04669c`; `loc_8c046756` (inlined) | medium/low |
| `FUN_140626db0` | globals/camera 0x3CB8..0x6D10 | 0x3cd1 0x3d50 0x3d63 0x6cc8 | `loc_8c045ffe` | high |
| `FUN_140626eb0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4330) | 0x3cfe 0x3d05 0x3d63 0x4330 | `loc_8c046912` | high |
| `FUN_140626fe0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4330,0x4a68,0x51a0,0x58d8) | 0x3cfe 0x3d05 0x3d10 0x3d43 0x4330 0x4a68 0x51a0 0x58d8 0x6010 0x6748 | UNMATCHED | - |
| `FUN_140627230` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4240,0x4242,0x4420,0x4978) | 0x3d63 0x4240 0x4242 0x4420 0x4978 0x497a 0x4b58 | `loc_8c04611c` | medium |
| `FUN_140627390` | globals/camera 0x3CB8..0x6D10 | 0x3d63 | `loc_8c0467ce` | high |
| `FUN_1406274f0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4321,0x448b,0x4a59,0x4bc3) | 0x3cfe 0x3d05 0x3db8 0x4321 0x448b 0x44f0 0x4a59 0x4bc3 0x4c28 0x5191 | UNMATCHED | - |
| `FUN_1406276d0` | globals/camera 0x3CB8..0x6D10 | 0x3d10 0x3d40 | `loc_8c046c74` | low |
| `FUN_1406277b0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4060,0x4069,0x4226,0x4254) | 0x3cd1 0x3d04 0x3d40 0x3d43 0x3d50 0x3d5c 0x3d63 0x4060 0x4069 0x4226 | `loc_8c0463aa`; `loc_8c047278` (inlined) | high/low |
| `FUN_140627c50` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4418,0x441c,0x44a4) | 0x3ce1 0x3d04 0x3d10 0x3d3c 0x3d43 0x3d6a 0x3db9 0x4418 0x441c 0x44a4 | `loc_8c046ddc` | high |
| `FUN_140628020` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4321,0x448b,0x4a59,0x4bc3) | 0x3db8 0x4321 0x448b 0x44f0 0x4a59 0x4bc3 0x4c28 0x5191 0x52fb 0x5360 | UNMATCHED | - |
| `FUN_1406281a0` | globals/camera 0x3CB8..0x6D10 | 0x3d6a | `loc_8c047218` | high |
| `FUN_140628320` | globals/camera 0x3CB8..0x6D10 | 0x3d5e 0x3d66 | `loc_8c045fd0` | high |
| `FUN_1406283a0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `FUN_140628570` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cf9 0x3d44 0x3d46 | `loc_8c0409e0`; `loc_8c0306de` (inlined); `loc_8c040d60` (inlined); `loc_8c041588` (inlined) | high/low |
| `FUN_1406285f0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478,0x4bb0,0x52e8,0x5a20) | 0x3cbc 0x3cc0 0x3cc6 0x3cd1 0x3d3c 0x4478 0x4bb0 0x52e8 0x5a20 0x6158 | `loc_8c0402a4` | medium |
| `FUN_1406288b0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 0x3cc6 0x3d3c 0x6914 0x691c 0x6920 0x6928 0x695c 0x6964 | UNMATCHED | - |
| `FUN_1406289c0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 0x3cc6 0x6a93 0x6a94 | `loc_8c040564` | high |
| `FUN_140628ac0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4420,0x448b,0x4b58,0x4bc3) | 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd1 0x3d3c 0x4420 0x448b 0x4b58 | UNMATCHED | - |
| `FUN_140628c70` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4438,0x4b70) | 0x3d3c 0x3d44 0x3d45 0x3d46 0x4438 0x4b70 | UNMATCHED | - |
| `FUN_140628d60` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4434,0x4438,0x4b6c,0x4b70) | 0x3cbb 0x4434 0x4438 0x4b6c 0x4b70 | UNMATCHED | - |
| `FUN_140628df0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4490,0x4494,0x4498,0x449c) | 0x3ce8 0x3cec 0x3cf0 0x3cf4 0x4490 0x4494 0x4498 0x449c 0x4bc8 0x4bcc | UNMATCHED | - |
| `FUN_1406291d0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 0x3cd1 | UNMATCHED | - |
| `FUN_1406292b0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 | UNMATCHED | - |
| `FUN_140629490` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 0x3d04 | UNMATCHED | - |
| `FUN_1406295e0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3d39 | UNMATCHED | - |
| `FUN_140629690` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 | UNMATCHED | - |
| `FUN_140629700` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_1406297f0` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3d44 0x3d45 0x3d46 0x3d52 | UNMATCHED | - |
| `FUN_140629890` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cd1 0x3d3c 0x3d44 0x3d45 0x3d46 0x3d52 | UNMATCHED | - |
| `FUN_140629ab0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x3cbc 0x3d3c 0x4478 | UNMATCHED | - |
| `FUN_140629dc0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4478) | 0x3db9 0x440d 0x4478 | UNMATCHED | - |
| `FUN_14062a1d0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4478,0x448b) | 0x3d3c 0x3d3d 0x3d44 0x3dbc 0x440d 0x4478 0x448b | UNMATCHED | - |
| `FUN_14062a720` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | UNMATCHED | - |
| `FUN_14062a810` | globals/camera 0x3CB8..0x6D10 | 0x3d41 | UNMATCHED | - |
| `FUN_14062aa00` | globals/camera 0x3CB8..0x6D10 | 0x3d3c 0x3db8 0x3db9 0x4c29 | UNMATCHED | - |
| `FUN_14062b130` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x4478 | UNMATCHED | - |
| `FUN_14062b200` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x3ce8 0x3cec 0x3cf0 0x3cf4 0x4478 | UNMATCHED | - |
| `FUN_14062b3c0` | globals/camera 0x3CB8..0x6D10 | 0x3d09 0x6d04 | UNMATCHED | - |
| `FUN_14062b6c0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4038,0x4039,0x403c,0x403d) | 0x3dbc 0x3dbd 0x3dbe 0x3dbf 0x4038 0x4039 0x403c 0x403d 0x44f4 0x44f5 | UNMATCHED | - |
| `FUN_14062b7b0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478,0x4479) | 0x3d3c 0x3d3d 0x4478 0x4479 | UNMATCHED | - |
| `FUN_14062baf0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_14062bc80` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x447b,0x4bb3) | 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc0 0x3cd1 0x3d04 0x3d3c 0x3d44 | `loc_8c03a420`; `loc_8c03bbe2` (inlined); `loc_8c03c06a` (inlined); `loc_8c0305d8` (inlined); `loc_8c03ba4a` (inlined); `loc_8c03bce8` (inlined) | medium/low |
| `FUN_14062c440` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_14062c480` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3d3c 0x3d3d 0x3d45 0x3d46 0x3dbc 0x3dbd 0x3dbe 0x3dbf | UNMATCHED | - |
| `FUN_14062c640` | globals/camera 0x3CB8..0x6D10 | 0x3d3c 0x3d44 0x3d45 0x3d46 | UNMATCHED | - |
| `FUN_14062c710` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_14062c780` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 | UNMATCHED | - |
| `FUN_14062c7f0` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3cc0 | UNMATCHED | - |
| `FUN_14062c830` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3d39 | UNMATCHED | - |
| `FUN_14062c950` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 | UNMATCHED | - |
| `FUN_14062ca10` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `FUN_14062cb20` | globals/camera 0x3CB8..0x6D10 | 0x3d3d 0x3d44 | UNMATCHED | - |
| `FUN_14062cc50` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 | UNMATCHED | - |
| `FUN_14062cc90` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cc0 0x3cd1 0x690f 0x691c | UNMATCHED | - |
| `FUN_14062cd50` | globals/camera 0x3CB8..0x6D10 | 0x6d00 | `loc_8c031f24` | high |
| `FUN_14062cd70` | globals/camera 0x3CB8..0x6D10 | 0x6cf4 0x6cfc | `loc_8c031f10` | high |
| `FUN_14062cda0` | globals/camera 0x3CB8..0x6D10 | 0x6cf4 0x6cfc 0x6d00 | `loc_8c031ef8` | high |
| `FUN_14062d040` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 | UNMATCHED | - |
| `FUN_14062d490` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 | UNMATCHED | - |
| `FUN_14062e090` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cd0 0x3cd1 0x3ce2 0x3ce4 0x3cfc 0x3d04 0x3d3c 0x3d3d 0x3d40 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 0x3cd1 0x3d3d 0x3d40 0x3d42 0x3d44 0x3d45 0x3d46 0x3d67 0x3d6a | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cd1 0x3ce4 0x3d45 0x3d5c 0x3d6a | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x3d04 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 0x3d6a | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cd0 0x3cd1 0x3d02 0x3d3d 0x3d40 0x3d44 0x3d45 0x3d46 0x3d67 | UNMATCHED | - |
| `FUN_14062f450` | globals/camera 0x3CB8..0x6D10 | 0x3ce4 | UNMATCHED | - |
| `FUN_14062fba0` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | UNMATCHED | - |
| `FUN_14062fdc0` | globals/camera 0x3CB8..0x6D10 | 0x3cb9 0x3cba 0x3cc2 0x3cf8 | UNMATCHED | - |
| `FUN_14062ffe0` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 0x3ce8 0x3cec | UNMATCHED | - |
| `FUN_1406302a0` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 0x3cf8 | UNMATCHED | - |
| `FUN_140630700` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cc2 0x6a88 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 | UNMATCHED | - |
| `FUN_140630830` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 0x3cf8 0x6a88 | UNMATCHED | - |
| `FUN_1406318f0` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 | UNMATCHED | - |
| `FUN_140631e10` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3cbf | UNMATCHED | - |
| `FUN_140631e60` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cd1 | UNMATCHED | - |
| `FUN_140631eb0` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3cc4 0x3cc6 0x3cd1 0x3ce2 0x3cfc | UNMATCHED | - |
| `FUN_1406320b0` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cbf 0x3cc2 0x3cd1 | UNMATCHED | - |
| `FUN_140632160` | globals/camera 0x3CB8..0x6D10 | 0x3cbb | UNMATCHED | - |
| `FUN_1406321a0` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb | UNMATCHED | - |
| `FUN_140632370` | globals/camera 0x3CB8..0x6D10 | 0x3cbb 0x3cc0 0x3cc6 0x3cd0 0x3ce2 0x6a8c 0x6a91 0x6a92 0x6a93 0x6a94 | `loc_8c03ee92` | low |
| `FUN_140632510` | globals/camera 0x3CB8..0x6D10 | 0x3cbc | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 0x3cc6 0x3d3c | `loc_8c03f2b6` | low |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 0x3cc6 0x3d3c | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 0x3cc4 0x3cc6 0x3d3c | `loc_8c03f3a8`; `loc_8c03f880` (inlined); `loc_8c03fad0` (inlined) | high/medium |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 | `loc_8c03f790` | high |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cbc 0x3cbd 0x3cc0 0x3d3c | UNMATCHED | - |
| `FUN_1406331f0` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cc0 | UNMATCHED | - |
| `FUN_140633250` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3cbb 0x3cbc 0x3cbd 0x3cbe 0x3cc0 0x3cc2 0x3cc4 0x3cc6 | `loc_8c03f7c6` | low |
| `FUN_140633300` | globals/camera 0x3CB8..0x6D10 | 0x3cbd 0x3cbe 0x3cc0 0x3cc2 0x3cc4 0x3cc6 0x3cd1 0x6a88 0x6a8c 0x6a91 | `loc_8c03f0fa` | high |
| `FUN_140633dc0` | globals/camera 0x3CB8..0x6D10 | 0x3d47 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cc2 | UNMATCHED | - |
| `FUN_140634920` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4420,0x4422,0x4424,0x4426) | 0x4420 0x4422 0x4424 0x4426 0x4430 0x4b58 0x4b5a 0x4b5c 0x4b5e 0x4b68 | UNMATCHED | - |
| `FUN_140635450` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_140635a20` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140635ad0` | globals/camera 0x3CB8..0x6D10 | 0x3d64 | `loc_8c0530d8` | high |
| `FUN_140635f20` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e3 | UNMATCHED | - |
| `FUN_1406362c0` | globals/camera 0x3CB8..0x6D10 | 0x3dbd | UNMATCHED | - |
| `FUN_140636450` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c0532a8` | medium |
| `FUN_1406364f0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e4 | `loc_8c0518a0` | high |
| `FUN_1406368d0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e4 | UNMATCHED | - |
| `FUN_140636af0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e4 | UNMATCHED | - |
| `FUN_140636ff0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c051bca` | high |
| `FUN_1406370b0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | UNMATCHED | - |
| `FUN_1406371c0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c05176e` | medium |
| `FUN_140637390` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | `loc_8c052dac` | medium |
| `caseD_d` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c051648` | high |
| `FUN_1406377b0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | UNMATCHED | - |
| `FUN_140637a10` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 0x324e5 | UNMATCHED | - |
| `FUN_140637c70` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c051868` | high |
| `FUN_140637f00` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c052008` | medium |
| `caseD_6` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e5 | `loc_8c0520c0` | low |
| `FUN_140639200` | globals/camera 0x3CB8..0x6D10 | 0x3d5e | `loc_8c059914` | high |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3d48 | `loc_8c059d3a` | low |
| `FUN_1406394b0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d10 0x324e7 0x324e8 0x324f0 | `loc_8c059426` | high |
| `FUN_140639d00` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d0e 0x3d5e 0x324e0 | `loc_8c057718` | high |
| `FUN_14063a4a0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c055edc` | medium |
| `FUN_14063afd0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d5e 0x3db8 0x324e0 | `loc_8c056454` | medium |
| `FUN_14063b3e0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4120,0x4330,0x4334,0x4336) | 0x3d0b 0x3d0f 0x3db8 0x4120 0x4330 0x4334 0x4336 0x44f0 0x4858 0x4a68 | `loc_8c059582` | high |
| `FUN_14063b5c0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4120,0x4858,0x4f90,0x56c8) | 0x3db8 0x4120 0x44f0 0x4858 0x4c28 0x4f90 0x5360 0x56c8 0x5a98 0x5e00 | `loc_8c0599b8` | high |
| `FUN_14063b6c0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d0f 0x324e0 | `loc_8c059718` | high |
| `FUN_14063b920` | globals/camera 0x3CB8..0x6D10 | 0x3d0c 0x3d5e | `loc_8c059610` | medium |
| `FUN_14063bd70` | globals/camera 0x3CB8..0x6D10 | 0x3d0a | `loc_8c056e14` | low |
| `FUN_14063cbc0` | globals/camera 0x3CB8..0x6D10 | 0x3d5e | `loc_8c05929c` | low |
| `FUN_14063cd30` | globals/camera 0x3CB8..0x6D10 | 0x3cd3 | `loc_8c031b48` | medium |
| `FUN_14063cf60` | globals/camera 0x3CB8..0x6D10 | 0x3d5e | `loc_8c0591c8` | high |
| `FUN_14063d770` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x4418 0x4b50 0x324e2 | `loc_8c0522e0` | high |
| `FUN_14063d930` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x4418 0x4b50 0x324e2 | `loc_8c05a0b8` | medium |
| `FUN_14063dce0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x4418 0x4b50 0x324e2 | `loc_8c05a46c` | high |
| `FUN_14063dd40` | globals/camera 0x3CB8..0x6D10 | 0x3d43 | `loc_8c05a2cc` | high |
| `FUN_14063df80` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x4418 0x4b50 | `loc_8c05a6c8` | medium |
| `FUN_14063dfe0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x4418 0x4b50 | `loc_8c05a706` | high |
| `FUN_14063e080` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4418,0x4b50) | 0x3d3c 0x3db8 0x4418 0x44f0 0x4b50 | `loc_8c05aac4` | medium |
| `FUN_14063e4a0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690d 0x690e 0x6920 0x324e0 0x324e6 | UNMATCHED | - |
| `caseD_12` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6920 0x324e0 | UNMATCHED | - |
| `caseD_17` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x6920 | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1f` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_24` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_26` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_30` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | `loc_8c04c02c` | low |
| `caseD_33` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_3d` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_5` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c0476b8` | medium |
| `caseD_8` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c04a596` | low |
| `caseD_1` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d6b 0x324e1 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c047c40` | medium |
| `caseD_1` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `FUN_140643a00` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | UNMATCHED | - |
| `FUN_140643ac0` | globals/camera 0x3CB8..0x6D10 | 0x3d48 | UNMATCHED | - |
| `FUN_140643cd0` | globals/camera 0x3CB8..0x6D10 | 0x3d48 | UNMATCHED | - |
| `FUN_140644030` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_14` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_6` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_1f` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x69a0 0x69a4 0x324e0 | UNMATCHED | - |
| `caseD_10` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140647ad0` | globals/camera 0x3CB8..0x6D10 | 0x69a4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x69a4 | UNMATCHED | - |
| `FUN_14064a4a0` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | UNMATCHED | - |
| `FUN_14064bd70` | globals/camera 0x3CB8..0x6D10 | 0x6d04 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14064ead0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x691c | UNMATCHED | - |
| `FUN_14064eb30` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_14064f3a0` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_14064f710` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_14064f9f0` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_14064fce0` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_1406501b0` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_140650430` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_140650950` | globals/camera 0x3CB8..0x6D10 | 0x6cc8 | UNMATCHED | - |
| `FUN_140651460` | globals/camera 0x3CB8..0x6D10 | 0x3cba 0x3ccc 0x3cd0 0x3ce0 0x3ce8 0x3d08 0x3d10 0x3d24 0x3d2c 0x3d48 | UNMATCHED | - |
| `FUN_140651610` | globals/camera 0x3CB8..0x6D10 | 0x3cbf 0x3ccc 0x3cd0 0x3ce0 0x3cea 0x3d08 0x3d10 0x3d58 0x3da8 0x3e28 | UNMATCHED | - |
| `FUN_1406516e0` | globals/camera 0x3CB8..0x6D10 | 0x3cbf 0x3ccc 0x3cd0 0x3ce0 0x3cea 0x3d08 0x3d10 0x3d58 0x3da8 0x3e28 | UNMATCHED | - |
| `FUN_140652200` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4321,0x4330,0x440d) | 0x4321 0x4330 0x440d | UNMATCHED | - |
| `FUN_1406529d0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4321) | 0x3dba 0x4321 | UNMATCHED | - |
| `FUN_140652b30` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140652b80` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd0 0x324e0 | UNMATCHED | - |
| `FUN_140652bf0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140652c50` | globals/camera 0x3CB8..0x6D10 | 0x3d43 | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cba 0x3cd0 0x324e0 0x324e2 | UNMATCHED | - |
| `caseD_c` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_e` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_f` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd0 0x3ce1 0x324e0 | UNMATCHED | - |
| `FUN_1406535f0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_140653970` | globals/camera 0x3CB8..0x6D10 | 0x3ccc | UNMATCHED | - |
| `FUN_1406539a0` | globals/camera 0x3CB8..0x6D10 | 0x3db9 | UNMATCHED | - |
| `FUN_140653ee0` | globals/camera 0x3CB8..0x6D10 | 0x3d05 | UNMATCHED | - |
| `FUN_140653f20` | globals/camera 0x3CB8..0x6D10 | 0x3d05 | UNMATCHED | - |
| `FUN_140653fd0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4324) | 0x4324 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6990 0x6994 0x69a0 0x69a4 0x324e0 | UNMATCHED | - |
| `caseD_23` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2b` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6998 0x69a0 0x69a4 | `loc_8c06e49a` | low |
| `caseD_27` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_24` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_25` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_29` | globals/camera 0x3CB8..0x6D10 | 0x6990 | UNMATCHED | - |
| `FUN_140659700` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6990 0x6994 0x324e6 | UNMATCHED | - |
| `caseD_20` | globals/camera 0x3CB8..0x6D10 | 0x6990 | UNMATCHED | - |
| `caseD_34` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_42` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `FUN_14065bcd0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_3a` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3ccc 0x324e6 | UNMATCHED | - |
| `caseD_14` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_15` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `FUN_140660be0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6918 0x324e0 | UNMATCHED | - |
| `FUN_140660e30` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x6918 0x324e0 | UNMATCHED | - |
| `FUN_140661240` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 0x3d08 0x3d10 0x3d24 0x3d28 0x3d2c 0x3d45 0x3d4c 0x3d50 0x3d54 | UNMATCHED | - |
| `FUN_140662250` | globals/camera 0x3CB8..0x6D10 | 0x3ccc | UNMATCHED | - |
| `FUN_140662410` | globals/camera 0x3CB8..0x6D10 | 0x3db8 | UNMATCHED | - |
| `FUN_140666bb0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_b` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14066a2f0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | `loc_8c06414c` | low |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_14066ecc0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | `loc_8c063aa2` | medium |
| `caseD_2` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_140677110` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x3d38 0x690d 0x690e 0x6990 0x6994 0x6998 0x699c 0x324e0 | UNMATCHED | - |
| `FUN_140677150` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 0x699c | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1d` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_1f` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3d38 0x324e0 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3d38 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_16` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1d` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14067ae50` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cfd 0x6914 0x324e0 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x3cfd | UNMATCHED | - |
| `caseD_38` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_3b` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_28` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x3d40 | UNMATCHED | - |
| `caseD_2d` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_20` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_24` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_3` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_1406895e0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6cec | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14068fd10` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_20` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406923b0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x3d40 0x690d 0x690e | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x3d40 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3d43 0x3d5d | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x6990 0x6994 0x6998 0x699c 0x324e0 0x324e3 | UNMATCHED | - |
| `caseD_7` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e3 | UNMATCHED | - |
| `FUN_14069a050` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `FUN_14069a090` | globals/camera 0x3CB8..0x6D10 | 0x6998 0x699c | UNMATCHED | - |
| `caseD_9` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_20` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 0x6994 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2c` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_32` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_35` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_26` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_1a` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6994 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x6994 | UNMATCHED | - |
| `caseD_e` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_14` | globals/camera 0x3CB8..0x6D10 | 0x3dbd | UNMATCHED | - |
| `caseD_c` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_d` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_30` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1b` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_9` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_20` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1a` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406b0220` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x690d 0x690e 0x6990 0x6994 0x6cec 0x324e0 | UNMATCHED | - |
| `caseD_27` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6cec | UNMATCHED | - |
| `caseD_28` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406b24e0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x324e0 | UNMATCHED | - |
| `caseD_2d` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6ce4 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x6994 | UNMATCHED | - |
| `FUN_1406badf0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `FUN_1406bb910` | globals/camera 0x3CB8..0x6D10 | 0x6990 | UNMATCHED | - |
| `caseD_28` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_27` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2c` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406bcb40` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_21` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1b` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406bd1b0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406bd390` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1406bd490` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406bd750` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_14` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e | UNMATCHED | - |
| `caseD_24` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_e` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_31` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_3` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_1406caf10` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e3 0x324e5 | UNMATCHED | - |
| `FUN_1406cb0b0` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_1` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `caseD_2c` | globals/camera 0x3CB8..0x6D10 | 0x3d48 0x6914 | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_1406cc3d0` | globals/camera 0x3CB8..0x6D10 | 0x3d48 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_12` | globals/camera 0x3CB8..0x6D10 | 0x3cfd | UNMATCHED | - |
| `FUN_1406d2da0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x324e0 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x324e0 | UNMATCHED | - |
| `caseD_a` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_1406d7980` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_9` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_36` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_37` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_0` | node-pool lists 0x2EDD8..0x2EEE8; draw list handles/counts 0x2F4D0..0x324F8 | 0x2eee4 0x324e0 | UNMATCHED | - |
| `caseD_3` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_7` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1406eb8e0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x6990 | UNMATCHED | - |
| `caseD_1d` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_1e` | globals/camera 0x3CB8..0x6D10 | 0x6cec | UNMATCHED | - |
| `caseD_17` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406f2f10` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_1406f32b0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_14` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1406f4d00` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `FUN_1406f76f0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `FUN_1406f7770` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `FUN_1406f77f0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `FUN_1406f7870` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_1406fcfe0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_b` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_3` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_1c` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_140705d80` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_140706ba0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_140707780` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_18` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_140709e60` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_16` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14070e740` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10; node-pool lists 0x2EDD8..0x2EEE8 | 0x3db8 0x6990 0x69a8 0x2eee4 | UNMATCHED | - |
| `caseD_2e` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x69a8 | UNMATCHED | - |
| `caseD_1f` | globals/camera 0x3CB8..0x6D10 | 0x3db8 | UNMATCHED | - |
| `caseD_19` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_15` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_d` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_140723640` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_1407239c0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_6` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_39` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_36` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_37` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_3c` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_14072cd80` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_14072ce20` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x690d 0x690e | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_4c` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_54` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_56` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_51` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_53` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_52` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6998 | UNMATCHED | - |
| `caseD_50` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_5a` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x69a0 0x69a4 | UNMATCHED | - |
| `FUN_140730fc0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_c` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_11` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_23` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_4` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14073beb0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `FUN_14073d8b0` | globals/camera 0x3CB8..0x6D10 | 0x3d43 0x6914 0x69b0 | `loc_8c105860` | medium |
| `FUN_14073da50` | globals/camera 0x3CB8..0x6D10 | 0x6918 0x691c 0x69b0 | `loc_8c10597c` | medium |
| `FUN_14073daf0` | globals/camera 0x3CB8..0x6D10 | 0x3d43 0x6914 | UNMATCHED | - |
| `FUN_14073dd30` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3d43 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x3d43 | UNMATCHED | - |
| `FUN_14073dfb0` | globals/camera 0x3CB8..0x6D10 | 0x3d43 | `loc_8c0f2ee4` | high |
| `FUN_14073e330` | globals/camera 0x3CB8..0x6D10 | 0x3cbb | UNMATCHED | - |
| `FUN_14073e360` | globals/camera 0x3CB8..0x6D10 | 0x3cc8 | `loc_8c0f8208` | medium |
| `FUN_14073e540` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4478) | 0x4478 | `loc_8c0f8376` | medium |
| `FUN_14073edf0` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4479) | 0x4479 | UNMATCHED | - |
| `FUN_14073ee90` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x440d,0x4478) | 0x3d39 0x3db9 0x440d 0x4478 | UNMATCHED | - |
| `FUN_14073f200` | globals/camera 0x3CB8..0x6D10; fighter fields >=0x120 (0x4454,0x4b8c) | 0x3d04 0x3d63 0x4454 0x4b8c 0x6d04 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x3cbf | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cbb | UNMATCHED | - |
| `FUN_140741910` | globals/camera 0x3CB8..0x6D10 | 0x3d3c 0x3d3d | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 0x3ce0 0x3cec 0x3d08 0x3d10 0x3d18 0x3d39 0x3d48 0x3d58 0x3da0 | UNMATCHED | - |
| `FUN_140742270` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 | UNMATCHED | - |
| `FUN_140742360` | globals/camera 0x3CB8..0x6D10 | 0x3cbf | `loc_8c01a90e` | low |
| `FUN_1407425b0` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cc4 | UNMATCHED | - |
| `FUN_140743530` | globals/camera 0x3CB8..0x6D10 | 0x3cba | UNMATCHED | - |
| `FUN_1407437a0` | globals/camera 0x3CB8..0x6D10 | 0x3cba | UNMATCHED | - |
| `FUN_140748480` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `FUN_140748540` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `FUN_1407489f0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3ce6 0x324e0 0x324e1 0x324e5 | `loc_8c05b440` | high |
| `FUN_140749bb0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | `loc_8c04dd94` | low |
| `caseD_1` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x690d 0x690e 0x6914 0x324e0 | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_37` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14074b7a0` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `FUN_14074b850` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `FUN_14074c200` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c054400` | high |
| `FUN_14074c4c0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_14074c710` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_14074c870` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | `loc_8c054bb8` | medium |
| `FUN_14074cd70` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `FUN_14074cda0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e1 | UNMATCHED | - |
| `FUN_14074d2b0` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_14074fab0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | `loc_8c107f1c` | medium |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_11` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `FUN_140752c60` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_a` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `FUN_140755c10` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3ccc 0x324e6 | UNMATCHED | - |
| `FUN_1407566b0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_140756750` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_14075a760` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_14075a830` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_4` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_7` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_21` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6998 | UNMATCHED | - |
| `caseD_1b` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_26` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x6994 | `loc_8c064cb8`; `loc_8c064a0a` (inlined) | low |
| `caseD_36` | globals/camera 0x3CB8..0x6D10 | 0x6994 | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | `loc_8c0671f6` | medium |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_140764b40` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | `loc_8c069ba6` | high |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_140765f60` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | `loc_8c06a2d6` | medium |
| `FUN_140766230` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | `loc_8c06a4f0` | medium |
| `FUN_140766440` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | `loc_8c06a6fa` | medium |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_b` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `FUN_140769ff0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_14076ac40` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_b` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_14076dff0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_14076ec00` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_14076fda0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `FUN_140773a70` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_1407741b0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_140775990` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_140775df0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_16` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_19` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1b` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1f` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_21` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_25` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_27` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x6914 | `loc_8c075d8a` | high |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_1d` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6914 | `loc_8c077fde` | low |
| `caseD_18` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | `loc_8c0790ee` | low |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_21` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_22` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_23` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_24` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_25` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_26` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_65` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_42` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_43` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_40` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_41` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_5a` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | `loc_8c07d22a` | high |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | `loc_8c07a76e` | high |
| `caseD_14` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | `loc_8c07af18` | high |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_12` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_4` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_6` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_1e` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x69a8 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x69a0 0x69a4 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x6990 0x6994 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_21` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 0x69b0 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_2` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_c` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_3d` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_18` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_2b` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_12` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_39` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_30` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1e` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_34` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 0x6990 0x6994 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_d` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_18` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_23` | globals/camera 0x3CB8..0x6D10 | 0x6918 | UNMATCHED | - |
| `caseD_18` | globals/camera 0x3CB8..0x6D10 | 0x6918 | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_4` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_15` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `caseD_11` | globals/camera 0x3CB8..0x6D10 | 0x6914 | UNMATCHED | - |
| `FUN_1407bb7a0` | globals/camera 0x3CB8..0x6D10 | 0x3ce6 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6998 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_9` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1407c1d30` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_22` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1407c33f0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_3` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_4` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `caseD_5` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 | UNMATCHED | - |
| `FUN_1407c4270` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_2` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_9` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1407ca820` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_a` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e | UNMATCHED | - |
| `caseD_0` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_9` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_3` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `FUN_1407d7920` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x6998 0x699c | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_2a` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_2` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e0 0x324e3 0x324e6 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 0x6994 0x6998 0x699c | UNMATCHED | - |
| `caseD_e` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_11` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_f` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_10` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x699c | UNMATCHED | - |
| `caseD_16` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6998 | UNMATCHED | - |
| `caseD_1c` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x699c | UNMATCHED | - |
| `caseD_28` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x6998 | UNMATCHED | - |
| `caseD_2` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 | UNMATCHED | - |
| `caseD_6` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 0x699c | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x690d 0x690e 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 | UNMATCHED | - |
| `caseD_1` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_7` | globals/camera 0x3CB8..0x6D10 | 0x6998 | UNMATCHED | - |
| `FUN_1407e66f0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_1` | draw list handles/counts 0x2F4D0..0x324F8 | 0x324e6 | UNMATCHED | - |
| `FUN_1407e9160` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_1b` | globals/camera 0x3CB8..0x6D10; draw list handles/counts 0x2F4D0..0x324F8 | 0x3cd4 0x324e0 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x6990 0x6994 | UNMATCHED | - |
| `caseD_4` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cd0 | UNMATCHED | - |
| `FUN_1407ed2c0` | globals/camera 0x3CB8..0x6D10 | 0x3d39 | UNMATCHED | - |
| `FUN_1407ed640` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | UNMATCHED | - |
| `FUN_1407ed850` | globals/camera 0x3CB8..0x6D10 | 0x3ce1 | UNMATCHED | - |
| `FUN_1407f54d0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_1407f6fa0` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `FUN_1407fa000` | node-pool lists 0x2EDD8..0x2EEE8 | 0x2eee4 | UNMATCHED | - |
| `caseD_0` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_5` | globals/camera 0x3CB8..0x6D10 | 0x3cd4 | UNMATCHED | - |
| `caseD_8` | globals/camera 0x3CB8..0x6D10 | 0x3d41 | UNMATCHED | - |

## 5. Falsification tests (how to break this map)

1. Any CONFIRMED pair: decompile the Steam side (`/decompile_function?address=`) and read the SH4 routine; the callee sequence and the blk/global set must correspond under `blkmap.py`. A mismatch in a seed invalidates every pair propagated from it (the CSV `evidence` column names the pair ids used).
2. INFERRED `high` rows: the `runner_up` column gives the second-best candidate and its score; if reading shows the runner-up is the true counterpart, lower `MARGIN` is not the fix -- add the pair to `seeds.json` and re-run.
3. The stage-struct deltas: sample `blk+0x6914..0x698C`, `0x6CA8`, `0x6CE4`, `0x6D04`, `0x6D08` live and compare with DC `0x8C26A524..`, `0x8C26A8A8`, `0x8C26A8E4`, `0x8C26A95C`, `0x8C26A974` in flycast on the same frame.
4. Re-run end to end: `python ghidra_export.py fetch` (resumable), `python ghidra_export.py finger`, `python sh4_export.py`, `python match.py`, `python report.py`; then, from the maplecast-flycast repo root, `PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py tools/re_kb/30_steam_function_map.surql` (one statement per request; `rekb.sh @file` fails on this 5 MB file with 'length limit exceeded' and applies NOTHING).

## 6. Precision spot-check of INFERRED rows (2026-09-02)

Six `high` rows drawn at random (`random.seed(7)`) and read on both sides before sign-off:

| Steam | SH4 | verdict | why |
|---|---|---|---|
| `FUN_1406104b0` | `loc_8c02dc1c` | CORRECT | two stores: DC `@r5=0, @(4,r5)=r4` == Steam `blk+0x6CB4=0, blk+0x6CB8=param` (also corroborates the 0x8C263C00 delta) |
| `caseD_3` @0x140632b70 | `loc_8c03f3a8` | CORRECT | same `*(G+8)--`, `==0 -> *(G+5)++, *(G+8)=0x20` prologue |
| `caseD_4` @0x140765100 | `loc_8c069ba6` | CORRECT | same `*(node+0x18 -> +0x28)+0x1a0` test against the 0x1600/0x1601 family, same alloc call |
| `FUN_140609e30` | `loc_8c041e44` | CORRECT | same `G+0x43`, `G+0x14==0x40`, `G+0x2D` chain |
| `FUN_14060a270` | `loc_8c0357d8` | CORRECT | same `{i, 0x10, 0}` table fill after the default loader; Steam unrolled x8, stride 0x1C -> 0x38 |
| `FUN_140623350` | `loc_8c04d000` | DOUBTFUL | DC calls a routine first and tests a global byte >= 5 that the Steam side lacks; shared evidence is only the +-0.0833 constants and the 0xC00/0x800 masks. Treat as unverified. |

Estimated precision of the `high` tier from this sample: 5/6. `medium`/`low` were not sampled and should be assumed weaker.

## 7. Known gaps / UNKNOWN

* `FUN_14061d900` (Ghidra merged the four node constructors reached through `PTR_caseD_4_140a6e5c8` into one body) has no single SH4 counterpart; the DC constructor table is `loc_8c045020` (4 entries) -- not mapped.
* `FUN_140848ee0` (NaomiLib object record walk, role assigned by the WORLD-CAMERA lane) and `FUN_140846c30` (matrix slot store) carry no constants and were not reached by propagation with enough evidence; their SH4 counterparts are UNKNOWN here.
* The live KB also holds 12 `steam_routine` roles written by hand by the WORLD-CAMERA lane on functions this matcher left unmatched (fight camera x/y/zoom, matrix pre/post-multiply, queue flush, ...); the seed file coalesces (`role ?? 'UNMATCHED'`) so re-applying it cannot erase them.
* Functions inside the two Ghidra mega blobs are not in Ghidra's function list at all; re-analysis of the binary (splitting `caseD_0`) is required before this map can cover the character move code.
* The SH4 side does not include the S_PLxx character-program overlays (`_marv_re/char_prg`).
