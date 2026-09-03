# The world camera, closed form (Ghidra read-set, 2026-09-02)

Binary: `mvc_dump.bin` (unpacked Steam MvC2, base 0x140000000, Ghidra project `dumpproj`, GhidraMCP bridge
:8080 `decompile_function?address=` / `xrefs_to?address=`). SH4 side: marvelous2 `build/bank*.asm`.
`blk` = `DAT_142edf560`; `ctx` = `DAT_142ef0ab0` (NaomiLib host context); `cur` = `DAT_142ef0ab8` (pointer to the
CURRENT 4x4 of the matrix stack). All matrices are 16 x f32 row-major in the **row-vector** convention
(`p' = p * M`, translation in row 3). Tags: **CONFIRMED** = function decompiled and read (both sides where a
pair is claimed); **INFERRED** = derived from a fit or a fingerprint only. Gate data: `d3dcap/replay/capgate/state`
(1436 captured frames, all stage 0x0B) and `d3dcap/replay/camera_block.json` (the fitted 432-B scene CB).

## 0. Answer

* The camera the deck and lists 5/6 use is `V = LookAt(eye=blk+0x6914.., target=blk+0x695C.., roll=blk+0x698C)`
  and `P = Persp(angle=(blk+0x6974 * 65536/360 + 0.5) & 0xFFFF, aspect 4/3, near = ctx+0x1f82b0 = 1.0,
  far = 1400000, y-offset = blk+0x6988)`; the world matrix `W` is the identity for the deck and the node's `+0xA8`
  for list nodes. The 432-B D3D scene CB is a pure function of `(P, V)`; `W` travels separately as CBWorld.
  Closed forms in section 2, gate in section 4: **max abs error vs `camera_block.json` = 0.0121 (rows 25/26,
  (V.P)^-1 translation, magnitude ~400, rel 3e-5); rows 0-3 / 15-18 (the ones the vertex shader uses) reproduce
  to float32 rounding (<= 2.4e-4 abs on values ~1.3e3).** Same for the x0.1 variant: 2.7e-4 abs.
* `blk+0x6988` is **not** a near plane and `blk+0x698C` is **not** a far plane: 0x6988 is the projection
  **y-offset** (`P[2][1] = -offset = +0.41`, CONFIRMED `FUN_140848200` -> `FUN_140847f20`) and 0x698C is a
  **u16 roll angle** for the look-at (CONFIRMED `FUN_140846c80` param_3). The earlier "near/far" naming in
  STAGE-DRAW-GHIDRA.md section 4 and `global:camera_nearfar` is wrong; corrected in the seed.
* The fov->angle constant is **65536/360** (`_DAT_1408fefd0` = 0x47800000 = 65536.0f, read from the dump), not
  32768/360 as written in the re_kb note for `FUN_14061d6a0`; the hex in that note was right, the decimal wrong.
* **Nothing per stage.** No stage initialiser (`PTR_PTR_140a6ec20[stage]`) writes any camera field. The writers of
  0x6914..0x691C / 0x695C..0x6964 / 0x6974 / 0x6988 / 0x698C are enumerated in section 5 (fingerprint scan of all
  29678 functions for blk writes, then decompiled). In the FIGHT camera state the look-at is
  `(eye.x, eye.y, 0)`, zoom is the constant `320/tan(0x0F4A) = 812.357`, fov 43, offset -0.41, roll 0 -- verified on
  all 1436 captured frames (0 violations, section 5.1). So a tape carrying `stage_id + blk+0x6914/18/1C` is
  sufficient **while `blk+0x6908 == 0`**; when `blk+0x6908 == 1` (scripted round-intro/outro camera, section 5) the
  look-at and roll are free and the tape must carry the 9 floats + u16 (or the script state bytes).
* Consequence for the "garbled deck on stage 15/2" symptom: the camera is NOT stage dependent, so either the
  garbled frames were captured in camera state 1 (tilt = look-at.y != eye.y, e.g. script 4 = eye (0,95,812) ->
  target (0,190,0)), or the owner is the renderer's model-0 path, not the camera. Section 7 gives the bisection.

## 1. The NaomiLib matrix stack on Steam (CONFIRMED)

`FUN_140846a40(stackBuf, depth)` (init) lays out `ctx+0x1f80a4` = current mode, `+0x1f80a8` = previous mode,
four 64-B matrix slots **mode 0 @ `ctx+0x1f80ac`, 1 @ `+0x1f80ec`, 2 @ `+0x1f812c`, 3 @ `+0x1f816c`**, two scratch
matrices `+0x1f81c0` and `+0x1f8200`, the push/pop storage pointer `+0x1f81b0` with depth counters `+0x1f81b8/bc`,
projection offsets `+0x1f8240/+0x1f8244` = 0, and `cur = &slot[0]`. Identity source = `DAT_140ab20c0`
(verified 1,0,0,0 / 0,1,0,0 / 0,0,1,0 / 0,0,0,1 in the dump).

| Steam | SH4 (bank12/11) | pair | what it does |
|---|---|---|---|
| `FUN_140846e90(m)` | `loc_8C1204F0` | CONFIRMED (identical position/args in both camera routines; SH4 saves XMTRX to the old slot, sets the mode byte `0x8C2D68E4`, reloads XMTRX from the new slot via `8C1201E0`->`8C120220`) | `if m<4: prev=cur mode; mode=m; cur=&slot[m]` -- Steam keeps a pointer, no XMTRX |
| `FUN_140847ca0()` | `loc_8C121100` | CONFIRMED (both write the identity pattern) | `*cur = I` |
| `FUN_140846ee0(M)` | (ftrv-based `8C120540` family) | high | `*cur = M x *cur` (pre-multiply: `out[i][j] = sum_k M[i][k] cur[k][j]`) |
| `FUN_1408473d0(M)` | -- | -- | `*cur = *cur x M` (post-multiply) |
| `FUN_140846880(v,out)` | -- | -- | `out = [v 1] x *cur` (row vector) |
| `FUN_140847950(p)` | -- | -- | push `*cur`; if `p` load `*cur = *p` |
| `FUN_1408478c0(n)` | -- | -- | pop n |
| `FUN_140846c30(p)` / `FUN_140846a00(p)` | -- | -- | `slot[mode] = *p` / `*p = *cur` |
| `FUN_140848200(ox,oy)` | `loc_8C121710` | CONFIRMED (SH4 stores `fabs` of both to `0x8C16BD80/84`, consumed and zeroed by `8C1219B0`; Steam stores signed to `ctx+0x1f8240/44`; the sign is re-applied in the matrix so the result is the same) | projection x/y offset |
| `FUN_140847f20(angle,aspect,near,far)` | `loc_8C1219B0` | CONFIRMED pair (fingerprint high + same 4 args + same call slot); SH4 body builds its 4x4 at `0x8C2D6B58` with the sin/atan/cos helpers `8C11EB20/8C11E170/8C11E2E0` and multiplies into XMTRX via `8C120540`/`8C122780`; its closed form was NOT reduced -- INFERRED equal to Steam's | perspective, section 2.1 |
| `FUN_140846c80(eye,target,roll)` | `loc_8C11FF90` | CONFIRMED pair (fingerprint high, same args: r4 eye, r5 target, r6 u16 roll; SH4 computes target-eye, normalises, translates by -eye via `8C1210C0`); closed form read on Steam | look-at, section 2.2 |
| `FUN_14061d7e0()` | `loc_8c02e1a4` | CONFIRMED (seed) | world camera, section 2.3 |
| `FUN_14061d6a0()` | `loc_8c02e246` | CONFIRMED (seed) | same at x0.1, far 12000 |
| `FUN_14061d5b0()` | `loc_8c02e334` | high (crawl) | fixed 90-degree projection + identity view (HUD / list 0xC) |

`FUN_140847dd0` is a second perspective builder without the 240/320 correction (unused by the camera path).

## 2. Closed forms (CONFIRMED from `FUN_140847f20`, `FUN_140846c80`, `FUN_14061d7e0`; constants read from the dump)

### 2.1 Perspective `FUN_140847f20(angle u16, aspect, near, far)`

```
t     = tan( angle * 2*pi/65536 * 0.5 )          ; FUN_140817230 = tanf; DAT_1408e2a68 = 6.2831855, DAT_14092a584 = 1/65536, DAT_1408e2a44 = 0.5
h     = atan( t * 240/320 )                       ; DAT_14097da6c = 240, DAT_14097d594 = 320, FUN_1408d577c = atanf
cot   = cos(h) / sin(h)                           ; FUN_140811cd0 = cosf, FUN_1408121d0 = sinf (argument 2*h*0.5)
ox,oy = ctx+0x1f8240, ctx+0x1f8244                ; from FUN_140848200
P = [ cot/aspect   0      0                  0 ]
    [ 0            cot    0                  0 ]
    [ -ox          -oy    -(far+near)/(far-near)   -1 ]      ; DAT_1408e34a4 = -1.0, sign flips via DAT_1408e2ac0 = 0x80000000
    [ 0            0      -2*far*near/(far-near)    0 ]
*cur = P x *cur ;  ctx+0x1f8518 = 0
```

So `blk+0x6974 = 43.0` is the **horizontal** fov: angle = 7828, t = tan(21.5 deg) = 0.39392, h = atan(0.29544),
cot = 3.38482 = `P[1][1]`, `P[0][0] = 3.38482/1.33333 = 2.53862`. With near = 1.0, far = 1400000:
`P[2][2] = -1.0000014`, `P[3][2] = -2.0000014`; with far = 12000: `-1.000167 / -2.000167`. `oy = -0.41` gives
`P[2][1] = +0.41`. All match `camera_block.json` rows 15-18 to <= 4.7e-7.

Inputs of the three call sites (all CONFIRMED):

| caller | angle | aspect | near | far | offsets | view |
|---|---|---|---|---|---|---|
| `FUN_14061d7e0` (deck, lists 5/6) | `(blk+0x6974 * 65536/360 + 0.5) & 0xFFFF` | `DAT_14095e268` = 1.3333334 | `ctx+0x1f82b0` | `DAT_140a6e518` = 1400000.0 | `(0, blk+0x6988)` | LookAt(eye, target, roll) |
| `FUN_14061d6a0` (lists 7/8/9) | same | same | same | `_DAT_14097d5ec` = 12000.0 | same | LookAt(eye*0.1, target*0.1, roll) |
| `FUN_14061d5b0` (HUD list 0xB, list 0xC parts) | 0x4000 (90 deg) | same | same | 12000.0 | (0, 0) | identity |

`ctx+0x1f82b0` is written to **1.0** at the top of the render dispatcher `FUN_140620960` every frame (line 1 of its
body); the 0.1 written by `FUN_14061c6e0` / `FUN_14060b960` never survives to a draw. Hence near = 1.0 for all three.

### 2.2 Look-at `FUN_140846c80(eye, target, roll u16)`

```
d = normalize(eye - target)                       ; computed as -(target - eye), FUN_140848220 = normalise
r = normalize(cross(up=(0,1,0), d))               ; FUN_140847d70(a,b) = a x b
u = cross(d, r)
L = [ r.x  u.x  d.x  0 ]
    [ r.y  u.y  d.y  0 ]
    [ r.z  u.z  d.z  0 ]
    [ -eye.r  -eye.u  -eye.d  1 ]                 ; FUN_140847ce0 = dot, sign via 0x80000000
if roll != 0:  *cur = Rz(roll) x *cur             ; Rz from the 65536-entry sin (DAT_142ef0ac0) / cos (DAT_142f30ac0) tables built in FUN_140844a10
*cur = L x *cur
```

For the fight camera (target = (eye.x, eye.y, 0), roll 0): `d = (0,0,1)`, `r = (1,0,0)`, `u = (0,1,0)`,
`V = I` with row 3 = `(-eye.x, -eye.y, -eye.z, 1)` == `camera_block.json` rows 7-10.

### 2.3 Composition in `FUN_14061d7e0` (CONFIRMED, decompiled)

```
FUN_140846e90(3); FUN_140847ca0();                          slot3 = I
FUN_140848200(0, blk+0x6988);                               offsets (0, -0.41)
FUN_140847f20(angle(blk+0x6974), 4/3, ctx+0x1f82b0, 1.4e6); slot3 = P
FUN_140846e90(2); FUN_140847ca0();                          slot2 = I
FUN_140846c80(blk+0x6914.., blk+0x695C.., blk+0x698C);      slot2 = L x Rz(roll)   (Rz first, then L pre-multiplied)
FUN_140846e90(1);                                           leave mode 1 (world) current for the caller
```

The caller then sets the world: `FUN_140847ca0()` (identity, deck) or `FUN_140846c30(node+0xA8)` (list nodes).
The three matrices are never multiplied together on the CPU for a draw; `FUN_140847d10` composes
`V x P x Screen(DAT_140ab2080 = [320 0 0 0; 0 -240 0 0; 0 0 1 0; 320 240 0 1])` into `ctx+0x1f8200` only for
point projection helpers (`FUN_1408480a0`, `FUN_140848120`, `FUN_140843320` = the sort key).

## 3. The queue entry and what D3D receives (CONFIRMED)

`FUN_1408436a0(kind, &entry, 0x130)` copies for **kind 2..5** (deck via `FUN_140849c10`, list nodes via
`FUN_140849c10/be0/c30/ac0`): `entry+0x08 = slot3 (P)`, `entry+0x48 = slot2 (V)`, `entry+0x88 = slot1 (W)`.
For **kind 0,1,6,7** (`FUN_1408499e0` after `FUN_14061d5b0`, i.e. HUD/list-0xC): `entry+0x48 = IDENTITY`,
`entry+0x88 = slot1`. The sort key is `FUN_140843320(rec+0x10..)` = record centre through `V x P x Screen`.

The flush `FUN_140842e30` issues per entry `FUN_1400483c0(4, entry+8, 0x80)` (**P and V, 128 B**) and
`FUN_1400483c0(7, entry+0x88, 0x40)` (**W, 64 B**), then kind 0..3 -> `FUN_1408482a0`, 4/5 -> `FUN_140848ce0`,
6/7 -> `FUN_140849030`. `FUN_1408482a0` copies each vertex's position/normal/uv **verbatim** into a 0x28-B VB
(`FUN_140048370(..., stride 0x28, ...)`); `FUN_140846960` (rotate normal by `*cur`) feeds only the per-vertex
lighting colour. **No position is transformed on the CPU on any of these paths.** So:

* the D3D 432-B scene CB is built by the host renderer from the 128-B (P, V) pair only; CBWorld (48 B) from W;
* coordinator Q1: `FUN_140848ee0` submits raw model vertices, kind 2, and pairs them with the (P, V) of
  `FUN_14061d7e0` -> the "world" CB (a);
* Q2: at the deck walk the current mode is 1, `W = I`, `V = L(eye,target,roll)`, `P` as 2.1; there is no
  XMTRX composite on Steam;
* Q4: lists 5/6 go through the same consumer with `W = node+0xA8` -> raw world vertices + CB (a). CONFIRMED;
* the "projection-only" CB (b) `[1,0,0,0],[0,1.3333,0,0],[0,0,-1.000167,-1],[0,0,-2.000167,0]` is exactly
  `P(0x4000, 4/3, 1, 12000)` of `FUN_14061d5b0` with `V = I`: `cot(atan(tan 45 * 0.75)) = 1.3333`, x = 1.0.
  Those 25 draws are list-0xB/0xC nodes (`FUN_140620ea0` -> `FUN_14061d5b0`; `FUN_140653a70` -> `FUN_14061d5b0`)
  whose vertices are authored in view space (z = -71) and whose CBWorld is the node's own matrix (identity when
  `+0x50..58 = 0` and no rotation) -- they are NOT CPU-transformed (INFERRED which list; decided by the TCW page).
* Q3 numeric check on a list-0xC part was NOT done: the part models live in the `0x0D082000` bank
  (`PTR_DAT_142edf598`), which is not among the rips available offline. Procedure: take the node's `+0xA8`
  (= translate(+0x50) x rotations x scale as built in `FUN_140653a70`), multiply a model vertex by it, and it
  must equal the captured (x, y, -71) vertex byte-exact; the scene CB is `P(0x4000)` with `V = I`.

### 3.1 The scene-CB layout (rows of 4 f32; rows 0-3,7-26 CONFIRMED by reproduction; 4-6 INFERRED)

| rows | content | reproduced |
|---|---|---|
| 0-3 | `V x P` | yes (<= 2.4e-4 abs at value ~1.3e3) |
| 4 | `(V^-1 row3 .xyz = eye,  2*far/(far+near))` | yes (1.9e-9; w = 1.9999986 for far 1.4e6, 1.99983 for 12000) |
| 5 | `(-(V^-1 row2 .xyz) = camera forward, 100.0)` | matches on the fight camera ((0,0,-1),100); the forward part is INFERRED for tilted cameras |
| 6 | `(c, 1/c, 0, 0)`, c = 20.41504 (far 1.4e6) / 13.55109 (far 12000) -- c ~ log2(far) to 1e-4 rel; use the two constants | INFERRED (the host-side builder for command 4 was not located; `FUN_14004ba50` is a texture uploader) |
| 7-10 | `V` | exact |
| 11-14 | `V^-1` | exact |
| 15-18 | `P` | <= 4.7e-7 |
| 19-22 | `P^-1` | <= 1.1e-7 |
| 23-26 | `(V x P)^-1` | <= 7e-3 abs at value ~400 (3e-5 rel) |

Formula the renderer must implement: `scene_CB = f(P(fov, oy, 1.0, far_path), V(eye, target, roll))` as above,
`CBWorld = W` (identity for the deck, `node+0xA8` for nodes), far_path = 1400000 for the deck/lists 5-6 and 12000
for lists 7-9 (with eye/target x0.1) and for HUD/list 0xC (with V = I, angle 0x4000).

## 4. Gate: reproduce `camera_block.json` from the state dump

Script (inline in this session; the formulas are the ones above, numpy float64):

* input frames: every 25th of the 1436 captured state frames (`blkstate.load_frame`), eye = `blk+0x6914..`,
  target = `blk+0x695C..` (== (eye.x, eye.y, 0) on all of them), fov 43.0, oy -0.41, roll 0, near 1.0;
* `list6` (far 1400000): **max abs err 0.0121**, max rel err (normalised by max(|fit|,1)) **4.2e-5**; the only rows
  above 1e-4 abs are 3 (2.4e-4), 25 and 26 (7e-3, the (V.P)^-1 translation, values ~250..406);
* `list7` (eye x0.1, far 12000): **max abs err 2.7e-4**, max rel **5.2e-6**.

The fitted file was built by linear regression on floats; those residuals are its rounding, not a model error.
Falsification of section 2 would have been any row off by more than float32 rounding -- none is.

## 5. Who writes the camera block (CONFIRMED by decompile; writer list from the fingerprint scan of all functions)

| writer | SH4 | when | writes |
|---|---|---|---|
| `FUN_14061c6e0` | `loc_8c02e014` **CONFIRMED** (pool at 8c02e014.. holds the unique set 0x0F4A, 0x422c0000=43.0, 0xbed1eb85=-0.41, 0x42be0000=95, 0x43a00000=320) | match start (`caseD_5` 0x14060ed9b, `FUN_14060efd0`, menu inits) | state bytes 0x6908/0x690f/0x6910/0x6911/0x6912 = 0; eye = (0, 95, **320/tan(0x0F4A) = 812.357** via `FUN_140845170` = tanf(u16)); 0x6978 = 95; 0x6980 = 0; fov 0x6974 = 43.0; target (0, 95, 0); **0x6988 = -0.41**; 0x69b4.. = same; bounds 0x69a0 = -1280, 0x69a4 = 1280, 0x69a8 = 1238.4, 0x69ac = -46.6; ctx+0x1f82b0 = 0.1 |
| `FUN_14061caf0` | (caseD_0 of `FUN_14061ca70`) | first fight frame | identical to `FUN_14061c6e0` then `0x690f++` |
| `FUN_14061ca70` | `loc_8c02e3c8` (low, crawl) | every frame (callers `FUN_14060efd0`, `FUN_140614cc0`, `FUN_140615930` ...) | the camera STATE MACHINE on `blk+0x6908`: 0 = fight camera (`FUN_14061caf0` once, then `FUN_14061ce90`); 1 = scripted (0x690f: 0 = load key 0 of script `blk+0x6910`, 1 = run `FUN_14061c0a0`, 2 = hold); 2..5 = round transitions |
| `FUN_14061ce90` | -- | every fight frame | **first** copies 0x6914..1C -> 0x6920..28 and 0x695C..64 -> 0x6968..70, then 0x69bc = 812.357; x-follow via `FUN_14061a0c0` (P1) / `FUN_14061a370` (P2): target x = fighter `+0x50` clamped by `FUN_14061c660` (bounds 0x69a0/0x69a4), eye.x = target.x smoothed `+= (goal - prev)/N`; y/zoom via `FUN_140619dd0` (both) / `FUN_14061a1a0` / `FUN_14061a450`: `0x6980 = max_i(y_i(+0x54) + byte(+0x180)*2.142857 [0 if state +1 in 0x18..0x1A]) - 350` if > 0; `0x69b8 = clamp(0x6980 + 95, 95, 900)`; eye.y = target.y smoothed by 0.25 (0.5 when `+1 == 0x1A`) toward 0x69b8; eye.z toward 0x69bc (812.357); target.z toward 0x69c8 (0). Tail: window 0x6990 = eye.x-320, 0x6994 = eye.x+320, 0x69b0 = eye.y+98.4, 0x6998/0x699c = 0x69b0 +/- 240 |
| `FUN_14061c0a0` + `FUN_14061ae80` + `FUN_14061b8e0` | -- | scripted state | keyframes from `PTR_DAT_140a6e460[script]` (6 f32: eye, target) / `PTR_DAT_140a6e488[script]` (orbit deg: eye-orbit xyz, target-orbit xy, roll) / `PTR_DAT_140a6e438[script]` (count + per-key frame counts); linear interpolation of eye and target; `FUN_14061ae80` orbits eye about target, `FUN_14061b8e0` orbits target about eye and **writes the roll `0x698C = (deg*65536/360+0.5)&0xFFFF`** |
| `FUN_140615020`, `FUN_1406285f0`, `FUN_140629890`, `FUN_14062bc80` | -- | menu / ending / demo screens | `FUN_14061c6e0` then their own eye/target and script index (0x6910 = 3 / 4 / 1) |
| `FUN_140607da0` | -- | debug (`PTR_DAT_140acd3a0+0x828`) | eye.x / target.x = +/-960 |

Scripts (dump, `0x140a6e438/460/488`): 0 = 39 keys x5 frames (world-space fly-in ~ (9,15,86)), 1 = 7 keys
((0,1080,0.1) -> (0,484,170) top-down), 2 = 1 key ((0,190,90) -> (0,190,0)), 3 = 26 keys x6 (0.1-scale orbit with
roll -3.8..), 4 = 1 key x60: **eye (0, 95, 812.357) -> target (0, 190, 0)** -- a tilted camera. Whether a
particular stage/round runs a script and which is set by the game flow that assigns `blk+0x6908/0x6910`
(not traced further; the captured training frames never left state 0).

### 5.1 Data check over the capture (all 1436 frames, stage 0x0B)

`target == (eye.x, eye.y, 0)`: 0 violations. `eye.z == 812.3571`: 0. `fov == 43`: 0. `0x6988 == -0.41`: 0.
`0x698C == 0`: 0. `(0x6908, 0x690f) == (0, 1)`: 0. `0x6920/24 != 0x6914/18`: 988 frames, always equal to the
PREVIOUS captured frame's eye (1-frame lag, section 6).

## 6. Sprite-walker camera vs world camera (task 4)

`blk+0x6920/24/28` (and `0x6968/6C/70`) are the **previous frame's** `0x6914/18/1C` (and target): the copy is the
first statement of `FUN_14061ce90`, before the update (CONFIRMED; the 988-frame lag in 5.1 is the measurement).
Readers: `FUN_140620f10` (sprite walker) reads only `0x6928` (zoom, constant 812.357); `FUN_140620740` (list walker)
reads `0x6920/24/28` for billboard flag bits 7/8; the sprite screen placement uses the window fields
`0x6990/0x6994/0x69b0/0x6998/0x699c` which are derived from the CURRENT `0x6914/0x6918` in the same call. So the
tape columns eyeX/eyeY/zoom = `0x6914/0x6918/0x691C` (as `states_to_tape.py:157` reads them) are the right offsets
for both the sprites and the deck; `0x6920..` is derivable as "last frame's eye" if billboard nodes need it.

## 7. Bisection for the stage-15 / stage-2 deck garble (go/no-go)

The camera is not the owner unless the state says so. Run, on a garbled frame, in this order:

1. **Camera state.** Read `blk+0x6908, 0x690f, 0x6910, 0x6911` and the 9 floats + u16. Expected in a fight:
   `(0,1,*,*)`, target == (eye.x, eye.y, 0), zoom 812.357, fov 43, 0x6988 = -0.41, 0x698C = 0. If so the CB the
   renderer must use is exactly section 2 with those numbers -- the fit is general, and the camera is ruled out.
   If `0x6908 == 1`, the frame is under a script: carry the 9 floats + roll (36 + 2 B) and re-render.
2. **Consumer parity.** With the same identity W and the section-2 CB, draw a list-5 node of the same stage (exact
   on training) and model 0 side by side. List-5 exact + model 0 wrong => the model-0 geometry path (rip model
   order, record walk, scale) owns it, not the camera or the CB.
3. **Model identity.** Live: `p = *(u64*)0x142edf630`; walk records (`next = rec + rec[0x13] + 0x50` while
   `(int)PCW < 0`), count vertices and compare with the rip's `STG%02X` model 0. On STG0B the rip's model 0 is 2
   meshes / 2424 vertices, x +/-2500, y -182..1363, z -2895..816, yet the frame-4445 capture has only 6
   identity-CBWorld draws (giant quads x +/-6244, z -65000..500) that match NO model of the STG0B rip (no rip model
   exceeds +/-5000). So on training either the live table entry 0 is not the rip's model 0, or its records were
   culled/empty. This is OPEN and it is the same question as the stage-15 garble; step 3 settles it.

Falsification of the leading hypothesis ("the fit is not the general camera"): a fight-state frame (step 1 passes)
whose scene CB differs from section 2 by more than float32 rounding. None of 1436 training frames does; a
real-stage state dump is required to close it there.

## 8. Address index

Steam: `FUN_140846a40` stack init - `FUN_140846e90` mode - `FUN_140847ca0` identity - `FUN_140846ee0` pre-mul -
`FUN_1408473d0` post-mul - `FUN_140846880` xform point - `FUN_140847950/1408478c0` push/pop - `FUN_140846c30/a00`
load/store - `FUN_140848200` offsets - `FUN_140847f20` perspective - `FUN_140846c80` look-at - `FUN_140848220`
normalise - `FUN_140847d70` cross - `FUN_140847ce0` dot - `FUN_1408444d0/140845150` cos/sin tables -
`FUN_140845170` tan(u16) - `FUN_140844a10` renderer constants - `FUN_14061d7e0/d6a0/d5b0` camera setups -
`FUN_1408436a0` queue append - `FUN_140842e30` flush - `FUN_1408482a0` kind 0-3 consumer - `FUN_1400483c0` D3D
command (4 = P+V, 7 = W) - `FUN_14061c6e0/caf0` camera init - `FUN_14061ca70` state machine - `FUN_14061ce90`
fight camera - `FUN_14061a0c0/a370` x-follow - `FUN_140619dd0/a1a0/a450` y+zoom - `FUN_14061c660` clamp -
`FUN_14061c0a0/ae80/b8e0` scripted camera - tables `PTR_DAT_140a6e438/460/488`.
SH4: `loc_8c02e1a4`, `loc_8c02e246`, `loc_8c02e334`, `loc_8c02e014`, `loc_8C1204F0`, `loc_8C121100`,
`loc_8C121710`, `loc_8C1219B0`, `loc_8C11FF90`, `loc_8C1210B0/C0`, `loc_8C120540`, `loc_8C11FA80`.
