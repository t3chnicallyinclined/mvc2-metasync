# Steam Collection graphics options — the mechanism, from the shell code (2026-09-03)

**RE METHOD (locked, restated):** (1) Port the SH4 annotations to the Steam binary by function matching.
(2) Seed with unique constants, then propagate along the call graph. (3) Translate globals through the
block map before comparing reference sets. (4) Tag CONFIRMED versus INFERRED, and store the pairs as edges
in the knowledge graph. The graphics options are **Collection shell code (Capcom MT Framework)** with no SH4
counterpart, so step 2 dominates here: the seeds were the option strings (`uUiOptionDisp`, `config.ini`,
`common\rtt_hd`, `%s\game_bg%02d`) and the message IDs in `FUN_140097c40`, propagated along the call graph
to the screen object. Steps 1 and 3 do not apply (nothing below touches `blk`). Step 4: every claim below is
tagged; the pairs to seed into `re_kb` are listed in §9.

Sources: Ghidra `dumpproj` on `C:\Users\trist\ghidra_projects\mvc_dump.bin` through the :8080 bridge (all
`FUN_`/`DAT_` addresses are that image, base `0x140000000`); the existing Path B captures in
`%TEMP%\rrcap` (frame 11943 = `cap_sent-rocket` step, 2026-09-02) and `d3dcap/replay/frame_4360.pack`;
the game files under `nativeDX11x64\`; `fxc /dumpbin` on the shim's `ps_*.cso`/`vs_*.cso` dumps. Scratch
artefacts (disassemblies, extracted arcs, GMD dump) are in the session scratchpad, not the repo.

---

## 0. The answer in one paragraph

The Collection has **six per-title display options**, saved in the encrypted `savedata.bin`, plus the
MT-Framework window/display settings in `config.ini`. Only **three** of them change pixels inside the game
picture: **Internal Resolution** (MvC2-only, 1x–4x), **Display Filter** (None + 8 shader filters) and
**Display Size** (5 placements). **Wallpaper** and the volumes touch nothing inside the picture. The
mechanism, CONFIRMED from the decompile and matched against the captured D3D11 state:

```
native      = 640 x 480                          (title table +0x1d8..0x1e4, dump-confirmed for MvC2)
k           = Internal Resolution option (0..3), clamped by window height (FUN_140073820)
src         = 640*(k+1) x 480*(k+1)              (FUN_140073820: +0x98/+0x9c)
sceneRT     = 2048x1024 | 3072x1536 | 4096x2048  by window height <1440 | <1920 | else (FUN_140073cc0)
viewport    = src, CENTERED in sceneRT            (FUN_140070940 "drawJack": (RT-src)/2)
picture     = one quad: NDC rect from Display Size (FUN_140073ac0), UV = src/RT,
              sampler SSPoint, PS = filter table[Display Filter] (FUN_14006f5e0 "draw", DAT_140a502f0)
then          MT post chain -> GUI wallpaper -> ImagePlane composite -> gamma -> backbuffer
```

Every capture taken so far was at **Internal Resolution = 2x, Display Filter = None, Display Size =
Full (4:3), Wallpaper != None**, in a 1280x768 window (§5). The game's own vertex data, constant buffers,
samplers, blend/depth state and textures **do not change with any of these options** — only the viewport
rect, the RT size and the shell's copy pass do. That is why the tape/receipt is resolution-independent and
why our player can apply the options after the fact.

---

## 1. Where the settings live (CONFIRMED)

| store | what | evidence |
|---|---|---|
| `<install>\config.ini` | MT Framework `[GRAPHICS]`/`[DISPLAY]`/`[CPU]`/`[JOYPAD]`/`[Window]` — window resolution, screen mode, borderless type, vsync, AA, texture detail, SMAA quality | file read 2026-09-03 (`Resolution=1024x768`, `ScreenMode=WINDOW`, `BorderlessWindowType=KEEPEASPECT`, `SMAA Quality=HIGH`, `AntiAlias=NONE`); path string `0x140a5ca38` built at `0x140029c0a` from `"%s\%s"` + `"config.ini"` (`0x140901528`); keys registered in `FUN_1402b22d0` (`s_Resolution_1408df088`, `s_Aspect_1408df094`, `s_AntiAlias_14095d860`, …) via `FUN_14026cc40`; command-line overrides `-Resolution/-RefreshRate/-ScreenMode` parsed in `FUN_140046790` |
| `Steam\userdata\39399619\2634890\remote\savedata.bin` (1,221,552 B) | the per-title options below (and everything else the game saves) | `FUN_1400751c0` opens `s_savedata_bin_1408e3950`; the file has no plaintext (repeating 16-byte pattern in the header) — **encrypted/scrambled, layout UNKNOWN**; the live values are read from the app object `DAT_140acd3a8 + 0xd04b0` (below) |
| in memory | per-title option record: `*(app+0xd04b0 + 8)` + `title * 0x9AC` (20 slots) | getters `FUN_14003f680` (+0x1D8), `FUN_14003fcd0` (+0x1DC), `FUN_14003fd10` (+0x1E0), `FUN_14003fcf0` (+0x1E4), `FUN_14003f6a0` (+0x1E8), `FUN_14003fd30` (+0x1EC), `FUN_14003f7e0` (+0xB44); setter `FUN_140040be0` (+0xB44) |

Title index: MvC2 = **5** (`FUN_140097c40` adds the Internal Resolution item only `if (title == 5)`; the sound
list order `xmc, msh, xvs, mvs, mvc1, mvc2, pnh` in `base.arc` gives 0..6; `DAT_140a4f758[5] = 2`,
`DAT_140a4f760[5] = 1` are the per-title Display Filter / Display Size "Default" values handed to the option
list via `FUN_14004a560`/`FUN_14004a580`).

⚠ `config.ini` says `Resolution=1024x768`, but the captured swapchain/backbuffer is **1280x768**
(`frame_11943.ndjson` draws 665–685 `rt.w=1280,h=768`; `shot_*.bmp`). The MT display code
(`FUN_1402b9930`, aspect literals 1.3333/1.6/1.7778, `ResizeBuffers` strings) resizes the borderless window;
which rule produced 1280x768 was **not traced** — UNKNOWN, and irrelevant to the picture mechanism because
everything below is driven by the live client size `renderer+0xd8-0xd0` x `renderer+0xdc-0xd4`
(`DAT_142ebd8f0` = the renderer the shim already probes).

## 2. The option list (CONFIRMED: `FUN_140097c40` = `uUiOptionDisp` vtable[5], message text from `msg.arc`)

`uUiOptionDisp` (DTI `0x140bd4790`, name `0x1408e9d58`, instance 0x420 B created by `FUN_140097310`,
vtable `0x1408e9db0`). `FUN_140097c40` fills item arrays at `this+0x338` (kind), `+0x358` (label msg),
`+0x378` (description msg), `+0x398` (current value), `+0x3b8` (value count), `+0x3d8` (default),
`+0x3f8` (original). Text = `msg.arc → ui\0_system\00_font\menu_eng` (GMD v0x10302, 2683 strings, section
index = message id):

| item | label (msg) | values (msg) | record field | default | consumer |
|---|---|---|---|---|---|
| 0 | **Wallpaper** (0x205) | None / Pop Art / Paint / Showdown (0x206–0x209) | +0x1D8, 4 values | 1 | `uUiGameBg` ctor `FUN_140081bc0` → `this+0x67`; change → `FUN_140081d20` → `FUN_14007b350(this,2,DAT_140a59928[v])` (GUI state 0xF4241/42/43 for Pop Art/Paint/Showdown, 0xF4248 for None). Art = `game_bgNN.arc` (index from table `0x140a31008`, loader at `0x140036e47` → `"%s\game_bg%02d"`) |
| 1 | **Display Filter** (0x20a) | None (0x20b) / "Type" (0x20c) + 1..8 (INFERRED: 9 values, one "Type" label) | +0x1DC, 9 values | "Default"-button value `DAT_140a4f758[5]` = 2 (other titles 4); the capture ran at 0 | screen object `+0xB0` → shader table `DAT_140a502f0[v]` (§4.3) and the integer pre-scale rule (§4.4) |
| 2 | **Display Size** (0x20d) | Full / Full (4:3) / Original Select / Original (4:3) / Wide (0x20e–0x212) | +0x1E0, 5 values | `DAT_140a4f760[5]` = 1 = Full (4:3) (other titles 0) | screen object `+0xB4` → `FUN_140073ac0` (§4.5) |
| 3 | Screen Rotation (0x213) | Off / On | +0x1E4, 2 values | — | only if title flag `PTR_DAT_140acd3a0[0x4c] & 4`; MvC2's flag word is 0 (dump) → **not offered for MvC2** |
| 4 | **Internal Resolution** (0xa73, "Change the internal resolution of the game screen." 0xa74) | 4 values (label format UNKNOWN; semantics = multiplier v+1, §4.1) | +0xB44, 4 values | 0 (= 1x) | screen object `+0xBC` → `FUN_140073820` (§4.1); **MvC2 only** |
| 5 | Music Volume (0x216) | 0..10 | +0x1E8, 11 values | 10 | `FUN_140037370`: `title+0x2cc = v*12+7` |
| 6 | Sound Effects Volume (0x217) | 0..10 | +0x1EC, 11 values | 10 | `FUN_140037370`: `title+0x2d0 = v*12+7` |
| 7 | Default (0xa4) | — | — | — | reset |

The PC page (`uUiOptionPC`, `0x1408ea828`) carries the `config.ini` items ("Resolution" 0xd6, "Change the
resolution." 0xdb) — window settings, not picture settings.

Not present anywhere: a texture-filter / smoothing toggle, a scanline toggle separate from Display Filter, an
integer-scale toggle separate from Display Size, a bloom toggle. (Bloom/SMAA are MT post passes gated by
`config.ini`, §4.7.)

## 3. The screen object (CONFIRMED)

Created at title start in `FUN_140038430` right after loading `common\rtt_hd` (`base.arc` entry 0, 16 B,
magic `RTX\0` — an RT descriptor; its bit layout is UNKNOWN and it is **not** where the size comes from):
`FUN_14006f4a0(0xE8,0x10)` → `FUN_14006f370` (ctor, vtable `0x1408e3530`), `FUN_140073c80(this, rtt)`.

| field | meaning | set by |
|---|---|---|
| `+0x7c/+0x80` | window client w/h | `FUN_140073820` from `renderer+0xd8-0xd0`, `+0xdc-0xd4` |
| `+0x84/+0x88` | scene RT w/h | `FUN_140073cc0` (vtable[5]) |
| `+0x8c/+0x90` | native w/h = `(title+0x1dc - title+0x1d8 + 1)`, `(title+0x1e4 - title+0x1e0 + 1)` | `FUN_140073820`; dump: `[0, 639, 0, 479]` → **640x480** |
| `+0x98/+0x9c` | source (rendered) w/h = native × (k+1) | `FUN_140073820` |
| `+0xa0/+0xa4` | aspect numerator/denominator (4:3 or 10:7 or 16:9) | `FUN_140073ac0` |
| `+0xb0` | Display Filter | `FUN_140073820` ← `FUN_14003fcd0` |
| `+0xb4` | Display Size | ← `FUN_14003fd10` |
| `+0xb8` | Screen Rotation | ← `FUN_14003fcf0` |
| `+0xbc` | Internal Resolution k | ← `FUN_14003f7e0`, clamped |
| `+0xc0` | integer pre-scale divisor for filters 3..7 | `FUN_140073820` (§4.4) |
| `+0xc4/+0xc8` | margins (0 in the capture) | — |
| `+0xcc/+0xd0` | destination (picture) w/h in window pixels | `FUN_140073ac0` |
| `+0x48/+0x50` (2), `+0x58/+0x60` (2), `+0x68/+0x70` (2) | scene colour RT ×2 (parity `+0x78`), half-height RT ×2, depth ×2 | `FUN_140073cc0` |

`FUN_140073820` (vtable[8], per frame) re-reads window size + the four options and calls `FUN_140073ac0`
when anything changed, then computes `+0x98/+0x9c` and `+0xc0`.

## 4. Per option: what changes in the D3D11 pipeline

### 4.1 Internal Resolution (CONFIRMED)

`FUN_140073820`:
```
cap   = window_h < 1440 ? 2 : window_h < 1920 ? 3 : 4        // max multiplier allowed by the window
if (cap <= k) FUN_140040be0(..., cap-1)                       // option silently clamped and WRITTEN BACK
k = FUN_14003f7e0(...)                                        // re-read
src_w = native_w * (k+1);  src_h = native_h * (k+1)           // +0x98 / +0x9c
```
So in a 768-tall window only 1x and 2x are selectable; 3x needs ≥1440, 4x needs ≥1920 window height.

Scene RT (`FUN_140073cc0`, keyed on the same window height so the largest allowed `src` always fits):
`2048x1024` (<1440), `3072x1536` (<1920), `4096x2048`; MT colour format code 0x27 ↔ the captured
`DXGI_FORMAT 87 = B8G8R8A8_UNORM` (INFERRED: same object, enum mapping not read); a second RT of half
height; a depth RT (code 0xF/5, flag 0x80 ↔ the captured `dsv`, INFERRED likewise).
`title+0x1a8 != 0` selects a 512x256 CPU-fed path (not MvC2; `+0x1a8 = 0` in the dump).

Viewport (`FUN_140070940`, the "drawJack" pass — the pass in which the recompiled game's polygon lists are
drawn, MT technique `TJackShader`):
```
x0 = (rt_w - src_w) / 2;  y0 = (rt_h - src_h) / 2;  x1 = x0 + src_w;  y1 = y0 + src_h
FUN_1403420b0(ctx, colourRT[parity], depthRT[parity])          // OMSetRenderTargets
FUN_140343cc0(ctx, ..., &rect)                                 // viewport/scissor rect
```
= `(384, 32, 1280, 960)` in `2048x1024` at k=1 — exactly the captured `vp` on all 662 scene draws of frame
11943 and on every earlier pack (`frame_4360.pack` head `viewport: [384,32,1280,960,0,1]`,
`sceneRT: 2048x1024 fmt 87`).

What does NOT change (CONFIRMED by construction, INFERRED for k≠1 since only k=1 was captured):
* sprite vertex positions are **NDC** (`vs_flat` pass-through, `classify_shaders.py`; NDC-per-texel exactly
  `2/384`, `2/224` — `rr-pathb-steam-capture` M6), so scaling is purely the viewport transform;
* the scene camera CB (`04E19F4C`, 432 B: projection `[1,0,0,0; 0,1.3333,…]`, view, world) has **no
  viewport-size term** — it is the 4:3 projection whatever k is;
* samplers are the game's own TSP state (`TSP-RENDER-STATE-GHIDRA.md` §2.2: point/linear + clamp/wrap
  from the TSP word), not an option: in frame 11943, 506 scene draws sample `filter 21`
  (`D3D11_FILTER_MIN_MAG_MIP_LINEAR`, stage pages), 111 `filter 0` on both t0/t1 (character index tile +
  palette), all `mips:1`, `maxaniso 0`, `bias 0`;
* blend/depth/raster state, textures, index/vertex buffers: untouched.

⚠ Pixel-visible consequences of k that are NOT a viewport change: (a) the stage's linear-filtered pages are
magnified by (k+1) with the same bilinear kernel, so texel interpolation happens at a finer grid — a 1x and
a 2x scene RT are not related by nearest downsampling; (b) point-sampled character tiles and the depth test
are exact at any k. This is why a 3x gate must diff against a 3x capture, not a resampled 2x one (§7).

### 4.2 The picture pass — "draw" (`FUN_14006f5e0`, vtable[11]) (CONFIRMED against draws 664–666)

```
ClearRTV(pictureRT 1280x768, [0,0,0,0])                                  // draw 664
quad A: NDC x = ±(1 - 2*((win_w - win_h*1.42857)*0.5)/win_w), y = ±1     // draw 665: vs 069138, ps 643EB9F8
        (colour-only; 1.42857 = DAT_1408e35dc = 10/7; = ±0.85714 at 1280x768; black)
quad B: NDC x = ±dst_w/win_w, y = ±dst_h/win_h                            // draw 666: ±0.8, ±1.0
        UV   = [ (rt_w-src_w)/2/rt_w , (rt_h-src_h/c0)/2/rt_h ] .. +src   // 0.1875..0.8125, 0.03125..0.96875
        VS  = pass-through (cache blob @11588 = vs_0432C5F8)
        PS  = filter table[Display Filter]  (§4.3); sampler s0 = SSPoint (filter 0, clamp)
        blend off, write mask 15, no depth
CBAppShader (cb0, 48 B, written by the same function):
        fAppTexSize   = (rt_w, rt_h)            // (2048,1024)
        fAppVideoSize = (src_w, src_h/c0)       // (1280, 960) at filter None
        fAppOutSize   = (dst_w, dst_h)          // (1024, 768)
        fAppAspect    = (1, dst_h/dst_w)
        iAppVertical, iAppKind, iAppFramecount  // per-title flags + frame counter
```
So at the captured setting the 1280x960 viewport is **point-downsampled 0.8x** into a 1024x768 4:3 box
centred in the 1280x768 picture RT; the strip between ±0.8 and ±0.857 is black; outside ±0.857 alpha stays 0
so the wallpaper shows through later.

### 4.3 Display Filter (CONFIRMED table, INFERRED per-type identity)

`DAT_140a502f0[9]` = `{shaderId, variant}`; MT shader id = `(~crc32(name) & 0xFFFFF) << 12 | index`
(verified on all 12 ids seen in this pass):

| value | id | MT technique (from `AppShaderPackage.mfx` string table) |
|---|---|---|
| 0 None | `11cccb57 / 0` | `TAppFilter` variant 0 = `PS_AppFilterCopy` — the captured 5-instruction copy `ps_6458C1F8` (cache blob @3f550) |
| 1 Type 1 | `11cccb57 / 1` | `TAppFilter` variant 1 = `PS_AppFilterArcade` (mfx locals: `af_curve_distance, sharp, af_filter_lanczos, curve_x`) |
| 2 Type 2 | `c5f3bb58` | `TAppFilterB` (`dm_Mask, mask_line, odd`) |
| 3 Type 3 | `b6fadb59` | `TAppFilterC` (`dilate, ce_filter_lanczos, scan_bright, scan_beam, mask_weight`) |
| 4 Type 4 | `ffa0eb5a` | `TAppFilterD` (`scanlineWeights, dotMaskWeights, ilfac, mod_factor`) |
| 5 Type 5 | `8ca98b5b` | `TAppFilterE` (`color_matrix0/1, lum0/1, min_sample/max_sample`) |
| 6 Type 6 | `19b22b5c` | `TAppFilterF` (`CrtsFetch/CrtsTone/CrtsMask/CrtsFilter`, `clf_FromSrgb/ToSrgb`) |
| 7 Type 7 | `6abb4b5d` | `TAppFilterG` (`maskFade, whichmask, scanLineWeight/B`) |
| 8 Type 8 | `9b625b5e` | `TAppFilterH` (`pC4, pC8`) |

Other ids in the pass: `a583bb16` = `TSystem` (the "drawHalf" pre-scale copy), `4866ab56` = `TScalingFilter`
(`FScalingFilter{2x,3x,4x}BRZ / HQ2x/3x/4x / Super2xSaI / SuperEagle` — the branch taken when filter ≥ 9,
unreachable from the 9-value option), `7fa75002`/`abee5001` = `IASystemClear`/`IASystemCopy` layouts.

**The bytecode is already on disk.** The DX11 shader cache `nativeDX11x64\sa\DX11_64\root.arc` → entry
`sc\DX11_64\root` (zlib, 338,484 B) holds 137 DXBC blobs, and the shim dumped every one of them at device
creation as `%TEMP%\rrcap\ps_*.cso` (byte-identical, sha256-matched). The eight `CBAppShader` pixel shaders:

| cache offset | shim dump | ps_5_0 lines | samples | cb0 regs read | fingerprint |
|---|---|---|---|---|---|
| @21420 | `ps_00000000620E5278` | 113 | 8 | [0] | lanczos taps + gamma (exp/log), literals 0.14/0.4167/0.8 |
| @23eac | `ps_00000000621C2E38` | 38 | 1 | [0] | one sample + mask, literals 4.0/0.2664/2.05 |
| @331f4 | `ps_00000000621E5978` | 91 | 8 | — | sincos, 1/6 taps |
| @36f50 | `ps_00000000621E4FF8` | 185 | 8 | [0,1,2] | reads `iAppFramecount` (interlace) — matches `ilfac` (D) |
| @3a5bc | `ps_0000000062343A78` | 188 | 8 | [0] | colour matrix 0.052/0.947 |
| @426e8 | `ps_000000006245EEB8` | 100 | 8 | [0] | sincos + sqrt |
| @49778 | `ps_0000000062489E38` | 175 | 12 | [0] | branches, 1/8 & 1/4 weights, `whichmask`-like |
| @4ce64 | `ps_000000006248A478` | 110 | 8 | [0] | Rec.709 luma 0.2126/0.7152/0.0722 |

The cache is hash-ordered, not technique-ordered, so **which blob is Type N is INFERRED** from the mfx local
names (only D ↔ @36f50 via `iAppFramecount` is strong). The decisive check is one frame captured with the
filter set: draw 666's `ps` hash names it (§7). ⚠ `ps_*.cso` files are game data — BYOR, never commit.

### 4.4 Integer pre-scale for filters 3..7 — "drawHalf" (`FUN_1400704c0`) (CONFIRMED)

`FUN_140073820`:
```
c0 = 1
if (src_h > 447 && 3 <= filter <= 7)
    for (h = src_h; window_h < h*4 && h > 447; h /= 2) c0 *= 2
```
At 1x/768-tall: 480 → 240, c0 = 2. At 2x: 960 → 480 → 240, c0 = 4. `FUN_1400704c0` then copies the centred
`src` rect of the scene RT into the half-height RT (`+0x58`) at `src_h / c0` lines (technique `TSystem`,
`FUN_1402b3e20` rect blit), and the filter samples that (`fAppVideoSize.y = src_h/c0`). I.e. for any window
under 1920 px tall **the CRT filters see a 240-line picture** for MvC2 whatever the internal resolution
(at 4x in a 2160-tall window: 1920 → 480 lines) — the k multiplier survives only horizontally.

### 4.5 Display Size (`FUN_140073ac0`) (CONFIRMED)

```
(a0,a4) = Display Size in {1,3} ? (4,3) : (10,7)          // 16:9 only for a title-kind-2 non-384-wide game
Full / Full(4:3)             : dst_h = win_h;                       dst_w = a0*dst_h/a4 & ~1
Original Select / Original(4:3): dst_h = native_h; if win_h < dst_h: dst_h/=2; dst_h = (win_h/dst_h)*dst_h;  dst_w = a0*dst_h/a4 & ~1
Wide                         : dst = window
```
(the `else` branch fits width instead; it needs the title's flag bit 2 AND rotation on — not MvC2).
Then `+0xcc = dst_w + 2*margin`, `+0xd0 = dst_h + 2*margin`. Captured: `Full (4:3)` → 1024x768 → NDC ±0.8.
"Full"/"Original Select" use **10:7** (1.4286), the same ratio as the black quad A.

### 4.6 Wallpaper (CONFIRMED path, art content per value UNKNOWN)

GUI draws 677–682 of frame 11943 (VS `1B1D78`/`32BCB8` with `CBGUIMatrix/CBGUIGlobal/CBViewProjection`,
PS `068E38` colour / `4E0D38` textured, `CBGUIGlobal = (2/1920, -2/1080, -1, 1)` → GUI space 1920x1080):
677 full-screen black; 678 1540x1080 vertex-gradient (`97,18,37` → `0,0,78`) at translation `+189`;
679/680 two 1540x300 strips (40x300 BC7) at y −600 (off-screen); 681/682 the art (1540x1080 / 1548x1080
BC7 `fmt 98`) at x+189 → GUI x 189..1729 of 1920 ≙ window x 126..1153, i.e. the art quad **coincides with
the 4:3 picture box** (window x 128..1152) and is drawn UNDER it. Then 683 (`ImagePlane`, VS `0687F8`,
PS `65BEF8`, `SSFilter` linear/border, blend SRC_ALPHA/INV_SRC_ALPHA, write mask 7) composites the picture
RT over it at 1:1 (`CBImagePlane` colour `[1,1,1,1]`, UV transform identity). Because the picture RT is
opaque over ±0.857 and alpha-0 outside, at `Full (4:3)` the art is fully covered and the pillars are the
black of draw 677; the art can only show for Display Size values that leave the box partly uncovered
(INFERRED — not observed). Which of Pop Art / Paint / Showdown the capture had is not recoverable from the
draws — UNKNOWN. Art files: `game_bg01..14.arc`
(index table `0x140a31008` = `[1..14]` over `[flag][title]`), plus `%s\game_%d%d` and `%s\game_%ds` (MvC2:
`game_5s.arc`) for the title's own frame art.

### 4.7 The rest of the post chain (CONFIRMED as captured; role INFERRED)

| draw | RT | PS | notes |
|---|---|---|---|
| 672 | 640x384 (+dsv) | `3ECCB8` `CBSystemDepthCopy`, samples the 1280x768 depth (fmt 44) | depth copy for the MT filters |
| 673 | 1280x768 `6488FB60` | `58C538` `CBHDRFactor` ×0.5 ×2 (`B2455988 = [0.5,2,1,1]`), blend SRC_ALPHA/INV, `SSSystemCopy` (21) | HDR re-encode round trip = identity at these factors |
| 674 | 640x384 | `58B8B8` `SSLinear` (21), luminance normalise | bloom downsample |
| 675 | 320x192 | `630078` 4-tap box, `SSPoint` | bloom downsample |
| 676 | 1280x768 `648919A0` (+dsv) | `4E1378` `mul_sat ×2`, `SSPoint` | back to LDR |
| 685 | 1280x768 `6488EDA0` | `65CE78` `CBSystemGamma` `[1,0,0,0]` → `exp(log(c)*1)` | gamma = identity at the captured setting |

`config.ini` `AntiAlias=NONE`, `SMAA Quality=HIGH`, `HDR=DEFAULT` gate these MT passes; at the captured
values they are numerically identity on the picture (0.5×2, gamma 1). No fog, no SMAA pass observed.

## 5. The setting every existing capture was taken at (CONFIRMED from the captures)

| quantity | value | where |
|---|---|---|
| window / backbuffer | 1280x768 (5:3) | draws 665–685 `rt`, `shot_*.bmp`, `FUN_1402b22d0` default 1280x720 resized |
| scene RT | 2048x1024 B8G8R8A8 (87) + depth | 662 scene draws, `frame_4360.pack` head |
| viewport | (384, 32, 1280, 960) | same |
| Internal Resolution | **2x** (k = 1) — the max allowed at 768 px | 1280x960 = 640x480 × 2; `FUN_140073820` clamp |
| Display Filter | **None** | draw 666 PS = `PS_AppFilterCopy` (5 instr, no cbuffer), sampler `SSPoint` |
| Display Size | **Full (4:3)** | draw 666 NDC ±0.8 → 1024x768 |
| Wallpaper | not None (which: UNKNOWN) | draws 681/682 sample 1540x1080 BC7 art |
| Screen Rotation | not offered | title flag word 0 |
| game samplers | 21 = MIN_MAG_MIP_LINEAR (stage pages), 0 = point (index tile + palette), wrap/clamp per TSP | frame 11943 histogram; identical in `frame_4360.pack` (524×21, 234×0/0) |

The same numbers hold for `frame_4360.pack`, `frame_5630.pack` and the `cap_*.seq` bursts (same head).

## 6. What our WebGPU player must do per option

Ground rule (Tris): only the game's own assets and the game's own arithmetic. Every step below is a literal
port of a captured pass, never an approximation.

### 6.1 Where the 640x480 / 2x assumption sits today

| place | assumption | file:line |
|---|---|---|
| `.seq` path | none — the blit crop is computed from `head.viewport` over `replayer.width/height`, which come from the pack head `sceneRT` | `d3dcap/replay/player.mjs:113-135`, `replay.mjs:102-104`, `state.mjs:239-243` |
| tape path | frozen template `[384,32,1280,960]` / `2048x1024` from `frame_2574.pack` | `RetroReceipts-agent/rr-render/src/seq.rs:16-39` (`FROZEN_TEMPLATE_2574`), `feed.rs:71`, `tape-player.mjs:74,126,131` |
| sprite NDC | `SX,SY = 192,112`, `TAPE_X,Y = 3/5, 7/15` — native 384x224 ↔ 640x480; resolution-free (NDC) | `rr-render/src/sprites.rs:5` |
| page canvas | `<canvas width=1280 height=960>` | `d3dcap/replay/player.html:48` (CSS 1280px, 4:3 at `:17`) |
| video capture | canvas pinned to 640x480 CSS | `d3dcap/replay/capture_video.mjs:40-42` |
| readback gate | `replayer.readback()` = whole scene RT, unpadded rows | `replay.mjs:280-298`; `verify_frame.py`/`gate_l3.mjs` compare the RT |

Nothing in `replay.mjs`/`resources.mjs`/`sprite.wgsl` hard-codes 640, 480, 1280 or 960: the replayer
allocates the RT from `head.sceneRT` and sets the viewport from each draw's `vp`.

### 6.2 Internal Resolution k (1x–4x)

* **Replayer:** allocate the scene RT with the Steam rule (`2048x1024` for k≤1, `3072x1536` for k=2,
  `4096x2048` for k=3 — the window-height rule maps 1:1 onto the clamp), and rewrite every scene draw's
  `vp` to `((RT.w-640(k+1))/2, (RT.h-480(k+1))/2, 640(k+1), 480(k+1))`. Draw records, CBs, samplers,
  textures unchanged. For the tape path this is one field in the template (`seq.rs` `viewport`/`scene_rt`
  become a function of k); for `.seq` playback it is a per-draw `vp` override in `replay.mjs:267`.
* **Depth:** the depth attachment follows the RT size (`replay.mjs:226-229` already sizes it from
  `this.width/height`).
* **Gate:** scene-RT pixel diff (`verify_frame.py`, coverage + colour separately) against a Path B capture
  taken at that k — only a capture at k proves the bilinear magnification of the stage pages (§4.1 ⚠).
  Until one exists, the k≠1 path is INFERRED-correct by construction and must be labelled so in the UI.

### 6.3 Display Size + the picture pass (all sizes)

Port §4.2 literally as a second WebGPU pass: picture RT = the output canvas size; quad A (black, 10:7) and
quad B with the NDC rect from `FUN_140073ac0` and UV = centred `src` rect over the RT; sampler
`nearest/clamp` (= `SSPoint`); PS = `PS_AppFilterCopy` (`rgb = tex.rgb; a = 1`). This replaces the current
blit (`player.mjs:71-96` `BLIT_WGSL`), which is already the k=1 / Full(4:3) special case of it minus quad A.
Gate: the 1280x768 picture RT `649F3860` of a capture (add it to the shim's RT snapshot list — currently
only the scene RT is written; `dllmain.cpp:1504`) vs our pass output, byte-exact expected (point copy).

### 6.4 Display Filter (Types 1–8)

* **Shaders:** port the eight `CBAppShader` pixel shaders from their DXBC (`%TEMP%\rrcap\ps_*.cso` /
  `root.arc`) to WGSL exactly as `sprite.wgsl` ported the game shaders; bind `CBAppShader` with the values
  §4.2 lists (`fAppTexSize`, `fAppVideoSize`, `fAppOutSize`, `fAppAspect`, `iAppVertical/Kind/Framecount`
  — the last is the frame counter, needed for the interlace-style filter D).
* **Pre-scale:** for Types 3–7 implement the `c0` rule of §4.4 and the half-height copy (`TSystem` =
  plain point copy, rect blit `FUN_1402b3e20`).
* **Gate:** per Type, one captured frame with that filter set: draw 666's `ps` hash names the shader
  (closes the INFERRED row of §4.3), its `pscbHash` CB dump gives the exact `CBAppShader` bytes, and the
  picture RT gives the pixels. Byte-exact is expected for Types 1,2,5,6,8 (no time term); Type 4 depends on
  `iAppFramecount` — compare with the captured CB's counter.

### 6.5 Wallpaper

Draws 677–683 are ordinary GUI draws already in the capture; the art is in `game_bgNN.arc` (BC7, 1540x1080
— our `resources.mjs` would need `bc7-rgba-unorm` or a CPU decode). This is outside the game picture and
is the lowest-value item; if offered at all it must use those files, never a substitute. Gate: the
backbuffer `shot_*.bmp` vs our composite — but only after the picture RT gate passes, because the composite
also contains the identity post passes of §4.7.

### 6.6 Post passes / gamma / bloom / SMAA

At the captured `config.ini` they are identity on the picture (§4.7); the player should not implement them
until a capture at a non-default `config.ini` shows a non-identity pass (`HDR`, `SMAA Quality`,
`AntiAlias`). Not an in-game option; keep it out of the option list.

### 6.7 What the player must NOT expose as "Steam options"

Texture filter (point/linear), anisotropy, mip bias, fog, modifier volumes, per-strip sort — none exists in
the Collection (the samplers are the game's TSP state, §4.1). Exposing them would change the picture away
from Steam's.

## 7. Optional verification recipe (not a gate the plan waits on)

One guided session per setting, game restarted between (the option is read into the screen object each
frame by `FUN_140073820`, so a live change also works, but the clamp needs a tall enough window):

1. For 3x/4x first set the window: edit `config.ini` `[DISPLAY] Resolution=2560x1440` (3x) or `3840x2160`
   (4x) — the clamp is on the **client height** (`FUN_140073820`), so a 1280x768 window can never show them.
2. In the game: Options → Display & Sound Settings → set **Internal Resolution** / **Display Filter** /
   **Display Size** to the value under test, one change per session.
3. `▶ READY:`
   ```
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\session-guided.ps1 -Seconds 1 -Steps "opt-res3x=any neutral footage, both fighters on screen"
   ```
   then press ENTER when in training mode; the step packs `d3dcap\replay\cap_opt-res3x.seq`.
4. Fields to diff against frame 11943 (`%TEMP%\rrcap\frame_<f>.ndjson`): scene draws' `rt.{w,h,fmt}`
   and `vp` (expect `3072x1536`, `(576, 48, 1920, 1440)` at 3x); draw 666's `ps` (`ps_<ptr>.cso` sha256 →
   §4.3 table), `samp[0]`, `pscbHash` → `cb_<f>_<hash>.bin` = `CBAppShader`; draw 666's vertex quad (`vb`
   at `voff`, stride 16: `pos.xy, uv.xy`) → Display Size rect; the scene draws' `samp`/`vscbHash`/
   `pscbHash` (expect unchanged); the `scene_<f>_WxH_f87.bmp` for the k gate; and — new — the picture RT
   (add `649F3860`-class 1280x768 RTs to `captureSceneRT`'s candidate list so the filter output is captured).

## 8. flycast / `king.html` options versus this title

`maplecast-flycast/web/js/diagnostics.mjs:150-205` (bound in `settings.mjs`): **Resolution**
480/720/960/1440/1080p(4x) — the same idea as Internal Resolution but flycast's is the PVR framebuffer
height, Steam's is 640x480×k with the window clamp; **Aniso**, **Tex Filter** (Default/Nearest/Linear),
**Transparency layers**, **Fog**, **Modifier Volumes**, **Per-Strip Sort** — PVR-renderer knobs with no
Steam counterpart (Steam has no PVR; samplers come from TSP words, translucency from a real depth buffer
per `TRANSLUCENT-SORT-GHIDRA.md`, no fog, no modvols) — meaningless for this title and must not be shown as
Steam options; **CRT Scanlines / Bloom Glow / Sharpen / Smooth / Vignette / CRT Curve / Bright / Contrast /
Sat** — CSS filters on the canvas (`settings.mjs:29-40`), not the game's shaders: they are exactly the
"approximated" kind Tris rejected; Steam's equivalents are the eight `TAppFilter*` shaders of §4.3.

## 9. re_kb seed (pairs to store; all `steam_routine`, no SH4 twin)

CONFIRMED: `FUN_140097c40` = uUiOptionDisp.buildList; `FUN_14006f370`/`FUN_14006f200` = screen ctor;
`FUN_140073820` = screen.update (option read + clamp + src size + c0); `FUN_140073ac0` = screen.layout
(Display Size → dst rect); `FUN_140073cc0` = screen.createRTs (window-height → RT size);
`FUN_14006f5e0` = screen.draw (picture pass, CBAppShader, filter table `DAT_140a502f0`);
`FUN_1400704c0` = screen.drawHalf (pre-scale); `FUN_140070940` = screen.drawJack (scene pass: RT bind +
centred viewport); `FUN_1402b3e20` = renderer.rectBlit; getters `FUN_14003f680/fcd0/fd10/fcf0/f6a0/fd30/f7e0`,
setter `FUN_140040be0`; `FUN_1402b22d0` = renderer ctor + config.ini registration; `FUN_140046790` =
command-line display overrides; `FUN_140038430` = title init (rtt_hd + screen object); `uUiGameBg` ctor
`FUN_140081bc0`/`FUN_140081b00`, update `FUN_140081d20`, loader `0x140036e00` (no Ghidra function);
message ids 0x204–0x21e, 0xa73/0xa74 in `menu_eng`.
INFERRED: Type N ↔ cache blob (§4.3 table); "Type" label numbering; wallpaper art ↔ value.
UNKNOWN: `savedata.bin` layout/cipher; `RTX` descriptor bits; why the window is 1280x768.
