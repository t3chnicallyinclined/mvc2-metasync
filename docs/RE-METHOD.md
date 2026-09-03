# RE METHOD — the one way we reverse-engineer Steam MvC2 (locked 2026-09-03)

Steam MvC2 is a **static recompilation** of the Dreamcast SH4 game. The reference binary is the
annotated `marvelous2` SH4 disassembly (`maplecast-flycast/_marv_re/build/bank*.asm`); the target
binary is the Steam x86-64 executable in Ghidra (`C:\Users\trist\ghidra_projects\mvc_dump.bin`,
HTTP bridge on localhost:8080). The original data files sit at their Dreamcast addresses inside a host
copy of DC RAM (`host = *(*(0x142ef0ab0)+8) + (X - 0x0C000000)`). The mutable state block `blk`
maps onto DC work RAM through the piecewise block map (`d3dcap/replay/re_map/blkmap.py`).

## The four sentences (say them at the start of every RE task, and say which step you are at)

1. **Port the SH4 annotations to the Steam binary by function matching.**
2. **Seed with unique constants, then propagate along the call graph.**
3. **Translate globals through the block map before comparing reference sets.**
4. **Tag confirmed versus inferred, and store the pairs as edges in the knowledge graph.**

## Vocabulary

- **Function fingerprinting** — constants, float literals, global references, strings, callees.
  Never instruction bytes or register choices; those do not survive recompilation.
- **Semantic anchor / unique-constant match** — one constant, one function on each side
  (812.357, 0xC10, 0x0D82D000, 0x0F4A …). Near-certain; these are the seeds.
- **Call-graph propagation** — callers and callees of a confirmed pair are compared next.
- **Global reference translation** — DC addresses → `blk` offsets through the block map, then compare
  the sets a function touches.
- **CONFIRMED** = both sides decompiled/read and agree. **INFERRED** = fingerprint or graph only.
  An inferred pair is a hypothesis with evidence attached, never a fact.
- **Program knowledge base** — the `re_kb` SurrealDB graph (http://127.0.0.1:8001, ns `re`, db `kb`):
  `steam_routine -recompiles-> routine`, `reads`/`writes` → `global`, `calls`, `finding -about->`,
  `-cites-> source`. Seeds live in `maplecast-flycast/tools/re_kb/NN_*.surql` and rebuild the graph.

## Rules

- **Query before deriving.** `SELECT` the graph and read `docs/STEAM-SH4-FUNCTION-MAP.md` /
  `docs/steam_sh4_map.csv` before any decompile, live probe, or new tape field.
- **Derive before capturing.** A capture is a GATE for a derived rule, never the source of the rule.
- **Every claim carries an address and evidence.** Say UNKNOWN rather than guess.
- **Every result goes into the graph** as a versioned seed (`tools/re_kb/NN_*.surql`, idempotent
  UPSERT/RELATE), applied with `PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py <seed>` from the
  maplecast-flycast root after the documented backup. A doc alone is not a result.
- **Gates are deterministic and numeric** (vertex sets, byte-exact pages, max-abs matrix error,
  pixel diff). "Looks right" is not a gate.
- Do not re-run `tools/re_kb/07_dedup_edges.surql` (it strips confidence/evidence from edges).
- BYOR: never commit ROM-derived bytes (rips, pages, tapes, blk dumps).

## What the method has already settled (do not re-derive)

| Topic | Where |
|---|---|
| 510 Steam↔SH4 pairs, 35 confirmed; 10,803 Steam nodes | `docs/STEAM-SH4-FUNCTION-MAP.md`, seed `30_steam_function_map.surql` |
| Stage deck = direct draw of POL model 0, identity W, world CB; props = list-5 nodes; TCW = 0xC10 + texIndex | `docs/STAGE-DRAW-GHIDRA.md` |
| World camera closed form, stage-independent; no CPU vertex transform on any path | `docs/WORLD-CAMERA-GHIDRA.md`, seed `24_world_camera.surql` |
| Sprite walker / submit read set (System B) | `docs/TAPE-V3-SPEC.md` §10 |

## Agents bound to this method

senior-re-generalist · mvc2-sh4-re-expert · naomi-re-expert · steam-d3d11-capture-expert ·
flycast-internals-expert · mvc2-sprite-render-expert (each carries an "RE METHOD" block pointing here).
