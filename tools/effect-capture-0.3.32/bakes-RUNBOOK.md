# bakes-RUNBOOK.md — per-character multi-tile PARTDUMP bakes (pixel-perfect effect cells)

Runs in a **non-isolated `maplecast-flycast` session** (headless build + ROM). This worktree can READ
`maplecast-flycast/tools/*` and the DATs but cannot build there.

## Why a live bake (measured, not assumed)
Every super's effect cells are **multi-tile / scratch-dependent** → offline `.arc→DAT` decode is a
CONFIRMED dead end (LZSS back-references the runtime shared scratch `0x0CE60000`, absent from the static
`GFX_DATA_00` file; `web/webgpu/pldat-codec.mjs` "DECOMPRESSION ARCHITECTURE"). Measured per-sid on the
real 59601369 tape (this worktree, `scratchpad/infernoprobe.py` variant):
- **Blackheart PL35** Inferno: sel 0x260 = 7/8 scratch; demon cells 0x3d(64×64)/0x3e(16×32)/0x3f(32×32) all scratch.
- **Storm PL2A** Lightning Storm: **18/18** super cells multi-tile (128×32, 64×64, 32×128…).
- **Magneto PL2C** Magnetic Tempest: **14/14** super cells multi-tile.
The deployed `PL{..}_parts.png` are OFFLINE-COMPLETE (their `_asm.json` `_note` says so) → approximate,
not pixel-faithful. The live bake replaces them with real pixels AND the correct live per-part palette.

## What the PARTDUMP captures (fixes cells + palette together)
`MAPLECAST_PARTDUMP=N` (`core/network/maplecast_gamestate.cpp partDump`) — READ-ONLY. Per in-match frame it
decodes the CURRENT pose's parts from the emulator's live decode buffer → `/dev/shm/PL%02X_gfx1_*.ppm`
(P6, **magenta = transparent**, the **live per-part palette already applied**) + a manifest/palette. This
is the ONLY correct pixel source (offline is dead). Because the palette is baked into the PPM, there is
**no per-part pal-row RE decision to make** (that RE is disputed — leave it to the live bake).

## Recipe (per super-casting character)
For a real demo match, drive supers so every char whose effects appear on the tape is captured. Point (P1)
= Storm 42 / Magneto 44 / Rogue 50; the opponent point = whatever the re-record uses; Blackheart 53 = Inferno.

```
# 1. CAPTURE — run headless with the ROM; play a match, throw EACH super repeatedly, varying the pose
#    so all demon/beam/spark cells get captured (PARTDUMP only sees the CURRENT frame's parts).
MAPLECAST_PARTDUMP=128 build-headless/flycast <rom>
#    Supers to throw during the capture window:
#      Storm   (PL2A): Lightning Storm   (QCF+PP) — the bolt/burst cells
#      Magneto (PL2C): Magnetic Tempest  (QCF+PP) — the energy-burst cells
#      Blackheart (PL35): Inferno         (QCF+PP) — sel 0x260 summon + the demon swarm (0x3d/0x3e/0x3f/0x30/0x31/0x28/0x2a)
#    (also throw any assists/supers of the other on-tape chars so their effect cells bake too.)

# 2. RIP — pair the disasm-confirmed geometry (GFX2 cumulative pen) with the REAL captured pixels.
#    Run once per character (PL2A, PL2C, PL35, + any other super-caster). Example PL35:
python3 tools/rip_gfx2_assembly.py \
  --gfx1 dasm_PLDAT/Output/PL35_DAT/PL35_DAT_GFX_DATA_00.BIN \
  --gfx2 dasm_PLDAT/Output/PL35_DAT/PL35_DAT_GFX_DATA_01.BIN \
  --pal  dasm_PLDAT/Output/PL35_DAT/PL35_DAT_PALETTE_DATA.BIN \
  --char PL35 --realparts /dev/shm --out web/test-atlas/chars
#    Repeat with --char PL2A / --gfx1..PL2A_DAT.. and --char PL2C / ..PL2C_DAT.. (Storm / Magneto).
#    Output per char: PL{HEX}_parts.png (REAL pixels), PL{HEX}_asm.json, PL{HEX}_parts.json.
```

## Deploy (ROM-derived → scp-only, NEVER committed)
```
scp web/test-atlas/chars/PL2A_parts.png web/test-atlas/chars/PL2A_asm.json web/test-atlas/chars/PL2A_parts.json \
    web/test-atlas/chars/PL2C_parts.* web/test-atlas/chars/PL35_parts.* \
    <host>:/var/www/maplecast/test-atlas/chars/
```
Then **bump `?v=`** on the atlas load so browsers drop the cached garbled atlas. The tapecanvas loader is
`sprite-client.mjs loadAsmChar` (fetches `<charBase>/PL{hex}_parts.png` + `_asm.json`); it already
cache-busts, but bump any pinned `?v=` in the harness/page.

## Pixel gate (the sign-off — not eyeballing)
Open the frozen super frame in `maplecast-flycast/web/webgpu-test.html` **DIFF v7, tint view**
(green = TA truth, red = ours, yellow = match). The effect region (Storm bolts / Magneto burst / Inferno
column) must go **yellow (match)**, not green/red-separated. Secondary visual check on the tape:
`play_state.html?frame=<super fi>&right=<name>` (Storm fi≈1451, Magneto fi≈2995, Inferno fi≈753 on tape 59601369).

## Scope note
- The bakes fix **cell fidelity** for OWNER-attributed effects (Storm/Magneto and most of Blackheart) —
  those already resolve to the caster atlas; the bake makes their pixels pixel-perfect.
- The bakes do NOT attribute the genuinely-**ownerless** global nodes (Blackheart's demon-swarm, global
  super-flashes) — that is the reader-wire's job (is_effect + resolved owner / effect_key, `reader-EDITS.md`).
- Blend correctness across banks is the reader `blend` byte's job (the gfx1-bank additive allowlist covers
  only ~90%). Bakes + reader wire together = the complete effect layer.
