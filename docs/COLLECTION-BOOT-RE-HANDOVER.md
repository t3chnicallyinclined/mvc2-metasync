# Booting the MvC2 Fighting Collection Build — RE Handover & Changelog

**Status: 2026-08-10.** Investigation phase complete; entering path (B) — reconstruct a bootable
image of the Collection's own MvC2 build. This doc is the cold-start handover: what we're doing,
everything we ruled out (so nobody re-treads it), the full asset inventory, and the roadmap.

Companion: `MVC2-STEAM-EXPERT.md` (the RE bible; §11 = extraction/boot summary). Memory:
`mvc-steam-naomi-revision` (§2026-08-10).

---

## 0. TL;DR

- **GOAL:** boot the Steam **"MARVEL vs CAPCOM Fighting Collection"** MvC2 build — a Capcom
  **Dreamcast-lineage recompile** whose fighter struct is **0x738** — inside an emulator we control
  (`maplecast-flycast`). Success unlocks: (1) **state-cloning** (snapshot any live moment → inject),
  (2) **native-0x738-layout training data**, (3) the user's original **savestate** idea.
- **Why the easy paths are gone (all ruled out, see §2):** stock flycast runs only `0x5A4` builds; no
  existing ROM matches `0x738`; and — live-proven — there is **no retail `0x5A4` core hiding inside
  the Collection**. The `0x738` record *is* the fighter struct.
- **REMAINING PATH (B):** the `0x738` **engine** (~2.4 MB) is delivered **only** inside the compressed
  **`0c000000` streams** — `entry250` turned out to be char DATA, not code (B2, 2026-08-10; see §8). So:
  crack the **inner Capcom codec** → decompress + reconstruct the engine image at guest **`0x8c010000`**
  (+ per-char code at `0x0CE30000`) → wrap in **IP.BIN + ISO9660 + GDI** → boot + stub host callbacks.
  **The codec is the SOLE gate. Multi-day, AMBER/RED, may dead-end.**
- **Fallback that already meets the training goal:** deterministic **input-replay** (validated
  2026-08-10 — a Magneto infinite reconstructed within a few HP, button counts 1:1). Arbitrary-moment
  cloning = replay the input log to any target frame. This stays available regardless of (B).

## 1. The "99%" thesis (why (B) is even plausible)

The Collection is **~99% the same game code as retail Dreamcast MvC2** — Capcom stitched rollback
netcode, save states, an enhanced training mode, and a menu wrapper onto the original DC build and
recompiled it. Evidence: the extracted payload's build banner is a live **Hitachi SH C/C++ 5.1**
command line targeting **`__DEV_TYPE_DC__`** (Dreamcast), with original source-module names intact
(`chrdef.c`, `hit_def.h`, `hit_equ.h`, `em_play.c`, `s_pl03.c`, `game.c`, `am_load.c`, `ef01.c`, …).
So we can **infer most of the structure from assets we already have** — the retail DC `1ST_READ.BIN`,
the `marvelous2` disassembly, and those module names. The recompile's diffs are small and localized
(the +404 bytes/fighter of `0x738` vs retail `0x5A4`). This is the leverage the whole effort rests on.

## 2. What we established — DO NOT re-investigate

1. **State-INJECT into stock flycast = NO-GO.** flycast boots only standard `0x5A4` MvC2 (marvelous2 /
   `mvc2.gdi` / `mvsc2.zip` all measure `0x5A4`); the Collection is `0x738`. Injecting `0x738` RAM into
   a `0x5A4` runtime is garbage.
2. **Extraction CRACKED (novel — nobody had done this).** `nativeDX11x64\arc\pc\game_50.arc` = Capcom
   "ARC" v7, single entry `bin\mvsc2`. Header: name[8..72], csize u32@0x4c, dsize(low-29b)@0x50, doff
   u32@0x54. For `game_50.arc.ORIGINAL` (clean): doff=0x8000, payload = raw zlib (0x789c) →
   `zlib.decompress` → **112.6 MB** = `IBIS`(hdr→0x40) → Sega `AFS\0` @0x40, **890 entries** (TOC @0x48:
   u32 off rel-0x40, u32 size; char sprite DAT = entry 209+char_id).
3. **Build identity = DC-target Capcom recompile** (`__DEV_TYPE_DC__`, tag `SHC211c`, SH C 5.1). The
   112.6 MB is ASSET+CODE data only — **no IP.BIN / ISO9660 / GDS / cart header** → not bootable as-is.
4. **No known ROM matches `0x738`.** All real DC dumps (US v1.000/v1.001, JP T-1215M, EU) are `0x5A4`;
   the DC "Matching Service" online-build hypothesis is dead (DC MvC2 was offline-only). `0x738` is
   unique to the Collection.
5. **LIVE-PROVEN: no retail `0x5A4` core exists.** In a live non-mirror match (team char_ids
   `[17,23,19,22,20,6]`), an exact-ordered 6-id fingerprint scan — **self-validated** (it re-found the
   real `0x738` array at its char_id column) — swept strides **0x300..0x1200** across the whole
   fighter region and found the team **only** in the `0x738` record. So `0x738` **is** the recompiled
   fighter struct, not just a render buffer; there is no `0x5A4` shortcut.
6. **Savestates:** no on-disk save states; the only save file (`userdata\…\2634890\remote\savedata.bin`,
   1.22 MB, encrypted) is settings/unlocks. The in-RAM **rollback ring** (≈6 byte-identical 32 MiB
   copies) is **raw allocator memory** — no `dc_serialize`/flycast magic — so it can't be parsed against
   upstream flycast. The exe is **string-stripped** (no `flycast/aica/naomi/gdrom` strings); flycast
   lineage is **inferred** from the guest `0x8C`/`0x0C` addressing (30k+ guest pointers), not proven.
   ⟹ SH4 register context must be pulled from the **live process** (Ghidra), not lifted from a file.

## 3. Asset inventory — what we HAVE to work with

| Asset | Location | Notes |
|---|---|---|
| Extracted program payload | `…\scratchpad\mvsc2_rom.bin` (112.6 MB) | IBIS→AFS 890 entries. **NOT** committed (BYOR). |
| **SH4 program image** | AFS **entry 250** (~1.18 MB, dataoff `0x29dc840`) | Partly **uncompressed**; carries the build banner @ `0x2b08847`. The boot target. |
| Inner-codec blocks | 170 `0c000000`-headed AFS records (idx 3..621, entropy 7.64) | **Capcom inner codec — the gating unknown.** |
| Retail DC reference exe | `maplecast-flycast\MVC2 Dev Files\1ST_READ.BIN` | The ~99% baseline to diff entry 250 against. |
| Retail DC GDI | `C:\Users\trist\Downloads\Dreamcast Games\Marvel vs. Capcom 2 v1.001 (2000)(Capcom)(US)[!]\…gdi` | Boot-wrapper reference (IP.BIN/ISO layout). |
| marvelous2 disassembly | maplecast/marvelous2 (DC map) | Semantic reference for the `0x5A4` layout + globals. |
| Collection host exe | `…\MARVEL vs. CAPCOM Fighting Collection\MarvelVsCapcomFightingCollection.exe` (8.8 MB, image base `0x140000000`; `kcode @ exe+0xac6f58`) | Contains the loader + inner codec + boot setup → Ghidra target. |
| Live memory snapshot | `…\scratchpad\snap_cur_A.npz` (menu-state, 75 regions) | Region map; guest addressing evidence. |
| Live fighter records | big flycast block, region base **~0x16b54000 (315 MB)**; `0x738` stride | NOT the 32 MiB guest-RAM copies — scan the big block. |
| `0x738` struct offsets | `src-tauri\src\sync.rs` | char_id +0x554, health +0xb44, DatPal +0x4c, input +0x4FC, pos_x +0x61c, combo +0x1ca. |
| Extraction/scan tools | `…\scratchpad\`: `fp2_scan.py` (exact-order finder), `witness_capture.py` (array anchor), `core5a4_scan.py` | Read-only. |

## 3a. RE data trove — SEARCH THESE to infer struct/pointer/routine/load info

We hold a large MvC2 RE corpus — mine it before reversing from scratch. All under `maplecast-flycast`:
- **Retail DC disassembly** (the ~99% baseline to diff entry250 against): `_oracle\_re\pl_mem.asm` (the
  retail **0x5A4 fighter-struct** code), `bank03.asm`, `bank12.asm`, `work.asm`.
- **Symbol table**: `tools\re_kb\ingest\data\marv_symbols.json` (retail function names→addresses — symbolize
  the entry250 diff).
- **RE knowledge base (SurQL)**: `tools\re_kb\` — `02_char_struct.surql`, `03_routines.surql`,
  `04_memory_data.surql`, `05_characters.surql`; per-char move/frame data `ingest\data\anotak_PL*.json`
  (+ `anotak_fields.json`); `disc_catalog.json`, `docs_findings.json`.
- **asmtrace** (real SH4 runtime): `tools\render-replica-poc\` — `realcore\trace_distinct_pcs.txt` (function
  entry map), `trace_entries.txt`, `trace_out.bin`, `sh4ctx_trace.h`, `trace_readset.c`. Confirms load address
  (guest `0x8C010000`), entrypoint, and which routines actually touch the fighter struct.
- **Oracle** (struct-field attribution / pointer anchoring): `_oracle\` — `mc_oracle.jsonl`,
  `oracle_attribute.py`, `oracle_anchor.py`, `oracle_layers.py`.
- **Inner-codec knowledge**: `mvc2-skin-studio\tools\gfx1_lzss.py` + `web\studio\rom-reader.mjs` (the skin
  pipeline already reads sprite DATs from this AFS — check before writing a new decoder).

## 4. Path (B) roadmap

### B1 — Crack the inner Capcom codec  *(GATING; do first)*
The `0c000000`-headed AFS records are compressed with a Capcom-internal codec (entropy 7.64, beyond
the outer zlib). Nothing downstream works until we can decompress them. Two attack angles, in parallel:
- **Static:** the codec's decompressor lives in the Collection **exe** — Ghidra it (anchor near the AFS
  loader; the `IBIS`/`AFS` handling calls it). Also check `mvc2-skin-studio`/`mvc-collection-sprite-editing`
  — the skin pipeline already reads *sprite* DATs, so parts of the chain may already be understood.
- **Dynamic:** the Collection decompresses these into guest RAM at load — capture before/after via RPM
  and diff to recover plaintext + infer the algorithm (LZ-family likely).

### B2 — Extract + understand entry 250 (the SH4 program)
Resolve entry 250's container header (`20 00 00 00 | sub-section offsets …`), extract the raw SH4
program, and **diff it against `1ST_READ.BIN`** (the ~99% baseline) to (a) confirm lineage, (b) locate
the recompile's changes, (c) map the source-module names to code regions.

### B3 — Entrypoint / load address + boot wrapper
DC programs load at guest **`0x8C010000`** and boot via **IP.BIN** (SEGA bootstrap) from an
**ISO9660** track. Determine entry 250's entrypoint/load address, then synthesize a fresh IP.BIN +
minimal ISO9660 → **GDI**, using the retail v1.001 GDI as the structural template.

### B4 — Boot + stub host callbacks
Boot the GDI in `maplecast-flycast` (or Demul). Core guest SH4 logic runs on emulated hardware, so the
game itself should boot; **stub any Collection host callbacks** (the DX11 renderer / rollback / mode
wrapper hooks) it expects. Iterate on the first crash/hang.

### B5 — Validate
Reaches a live match; the fighter struct reads back as `0x738`. If yes → we run the Collection's exact
build → state-cloning + native-layout data + savestate idea all unlock.

### Alt — Ghidra-port the loader (may subsume B1–B4)
Because the exe already does all of this, reversing its loader (game_50.arc → IBIS → AFS → inner codec →
guest memory → SH4 boot) hands us the codec, the load map, and the boot setup directly, which we then
replicate in `maplecast-flycast`. Highest-reliability, highest-effort route.

## 5. Risks / kill criteria
- **Inner codec unbreakable in reasonable time** → B1 stalls everything. *Kill criterion for (B).*
- **Entry 250 isn't the whole program** (streamed/paged) → boot needs more than one AFS entry.
- **Host-callback entanglement** too deep to stub → the recompile isn't standalone-bootable.
- If any of these hold: fall back to **input-replay** (already meets the training goal).

## 6. Expert assignments (multi-agent — "it's all the same game code")
- **naomi-re-expert** — B2/B3: entry 250 program structure, diff vs `1ST_READ.BIN`, entrypoint/load
  address, IP.BIN/GDI reconstruction, boot/stubbing strategy. (SH4/NAOMI/DC RE.)
- **mvc2steam-expert** (`.claude/agents/`) — B1: the Collection's ARC/IBIS/AFS + inner codec; reuse the
  skin pipeline's decode knowledge; the host exe's loader.
- **Ghidra-driven RE** (naomi-re-expert w/ GhidraMCP) — the Alt path: the exe loader + inner-codec
  decompressor + boot setup.
- **game-ai-ml-expert** — keeps the fallback (input-replay → training corpus) moving in parallel so
  progress isn't hostage to (B).

## 7. Changelog (this session)
- `docs/MVC2-STEAM-EXPERT.md` — **added §11** (ROM extraction + booting the Collection's own build).
- `docs/COLLECTION-BOOT-RE-HANDOVER.md` — **new** (this doc).
- Memory `mvc-steam-naomi-revision` — corrected "arcade build" → "DC recompile"; added the 2026-08-10
  extraction + live-scan findings.
- Scratchpad tools (not committed): `fp2_scan.py`, `core5a4_scan.py`, `fp_scan.py`, and the extracted
  `mvsc2_rom.bin` (BYOR — never commit).

## 8. UPDATE 2026-08-10 — entry250 is DATA, not the program; the `0c000000` codec is the SOLE gate (B2)

**B2 refuted the "entry250 = SH4 program" premise, decisively (grounded in bytes):**
- **entry250 is character-3 DATA** (sprite/table overlay compiled from `s_pl03.c`), NOT executable code:
  0 SH4 function prologues (`sts.l pr` = `22 4F`, `lds.l @r15+,pr` = `26 4F`) vs **2.572%** density in retail
  `1ST_READ.BIN`. A sweep of **all 890 AFS entries** found max 0.016% (noise) → **no uncompressed AFS entry
  contains the engine.**
- **The `20 00 00 00` container is fully decoded** (reusable): 16-byte header = 4× u32 section-start offsets,
  then sec0 (offset-table of u32 sub-records + blobs), sec1, sec2, and a systematic **64 KB sec3 trailer** =
  the SH C build banner/module stamp. Same family as the char DATs the skin pipeline reads (`rom.rs`).
- **99% lineage CONFIRMED:** entry210 carries a retail RCS module table dated **Dec 08–09 1999** (`game.c`,
  `em_play.c`, `hit_def.h`, `s_pl03.c`, `plXX_tbl.s`, `hit_dtXX.s`, …) — the retail DC module set + SH C 5.1.
- **`0x5A4→0x738` is a RELINK, not a constant.** `0x5A4` never appears as an immediate (it's a data-section
  stride); enlarging the fighter struct relocates the 6 struct bases + everything after → genuine recompile.
- **Load map (confirmed via runtime trace `trace_distinct_pcs.txt`):** engine @ guest **`0x8c010000`**
  (~8500 of 8962 distinct PCs), per-character code @ **`0x0CE30000`**. entry250-class assets load into
  `0x0c4xxxxx` datfile regions and **stream exactly as retail** once the engine boots.

**Roadmap correction:**
- **B2 is done / folded** — entry250 is not the program; its container work is reusable for asset streaming.
- **B1 (inner `0c000000` codec) is now the SINGLE blocker** — the engine + per-char code exist ONLY in those
  compressed streams. Codec correctness oracle: a correctly-decompressed **engine** record shows ~2.5%
  `22 4F`/`26 4F` prologue density (asset records ~0%).
- **B3 (revised):** decompress the `0c000000` memory-load records → reconstruct the `0x8c010000` engine image
  (+ `0x0CE30000` char code) → wrap IP.BIN + ISO9660 + GDI (retail v1.001 GDI = template) → boot → stub host
  callbacks. The eventual `0x5A4→0x738` diff (vs `_oracle\_re\pl_mem.asm` + `marv_symbols.json`) applies to the
  **decompressed engine**, and the deltas will be **relocated absolute addresses**, not opcode edits.
