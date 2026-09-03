#!/usr/bin/env python3
"""report.py -- render the function map into the deliverables:

    docs/steam_sh4_map.csv                      (steam_addr, sh4_pc, confidence, evidence, ...)
    docs/STEAM-SH4-FUNCTION-MAP.md              (method, coverage, anchors, render-relevant functions)
    <maplecast-flycast>/tools/re_kb/101_steam_function_map.surql   (idempotent KB seed)

    python report.py
"""
import os, json, csv, collections, datetime
from blkmap import dc_to_blk, blk_to_dc, dc_field_to_steam

HERE = os.path.dirname(os.path.abspath(__file__))
QUARTERS = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
DOCS = os.path.join(QUARTERS, "docs")
KB_DIR = r"C:\Users\trist\projects\maplecast-flycast\tools\re_kb"
SURQL = os.path.join(KB_DIR, "101_steam_function_map.surql")
GAME_LO, GAME_HI = 0x140600000, 0x1408e0000
TODAY = "2026-09-02"

RENDER_REGIONS = [(0x3CB8, 0x6D10, "globals/camera 0x3CB8..0x6D10"),
                  (0x2EDD8, 0x2EEE8, "node-pool lists 0x2EDD8..0x2EEE8"),
                  (0x2F4D0, 0x324F8, "draw list handles/counts 0x2F4D0..0x324F8")]
FIGHTER_LO, FIGHTER_HI, FIGHTER_STRIDE = 0x3DB8, 0x6908, 0x738

# roles for the seed pairs (plain English, copied to steam_routine.role when the SH4 row has none)
SEED_ROLES = {
    0x140620960: "per-frame render dispatcher (mode 0: sprite walk, deck, lists 5-8, HUD; mode 1: list 9)",
    0x140620f10: "sprite walker over the 16 draw lists (System B); inlines Render Main Sprite + effect path",
    0x140620740: "list matrix walker: composes each node's world matrix into node+0xA8",
    0x140620cd0: "list draw walker: draws each node with +0x170 gate and +0xA0 object",
    0x140620ea0: "HUD (list 0xB) then per-fighter 3D part nodes (list 0xC)",
    0x14061e170: "object-pool + render-state initialiser (256 x 0x280 nodes, 14 lists)",
    0x14061dbe0: "node alloc: free-list pop + constructor-table dispatch (kind 1 = append at tail)",
    0x14061df40: "node unlink + return to free list (clears +0x170 draw gate)",
    0x14060c370: "bank loader (25 cases; case 1 = stage POL/TEX at DC 0x0D82D000/0x0D85D000)",
    0x1406129f0: "sprite submit: body path (sprite id bit15 clear) -> TA/D3D quads",
    0x14061d7e0: "camera setup x1 (world units) from blk+0x6914..0x698C",
    0x14061d6a0: "camera setup x0.1 for lists 7/8/9",
    0x140847950: "NaomiLib matrix stack PUSH (optional load)",
    0x1408478c0: "NaomiLib matrix stack POP(n)",
    0x140619960: "render-mode getter (*(blk+0x6CE4))",
}


def esc(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


def hexlist(xs):
    return "[" + ", ".join("'0x%x'" % x for x in xs) + "]"


def main():
    steam = {f["addr"]: f for f in (json.loads(l) for l in open(os.path.join(HERE, "steam_funcs.jsonl"), encoding="utf-8"))}
    sh4 = {f["pc"]: f for f in (json.loads(l) for l in open(os.path.join(HERE, "sh4_funcs.jsonl"), encoding="utf-8"))}
    rows = json.load(open(os.path.join(HERE, "match_result.json"), encoding="utf-8"))
    # merge confirmations written into the live KB by OTHER lanes (same id scheme recompiles:FUN_x_loc_y);
    # a KB 'confirmed' row overrides the matcher's INFERRED tier and adds pairs the matcher did not have.
    ext_path = os.path.join(HERE, "cache", "kb_recompiles_external.json")
    n_ext = 0
    if os.path.exists(ext_path):
        ext = json.load(open(ext_path, encoding="utf-8"))[1]["result"]
        have = {(o["steam"], o["sh4"]): o for o in rows}
        for e in ext:
            sa = "0x" + e["in"].split("FUN_")[1]
            pc = "0x" + e["out"].split("loc_")[1]
            ev = "KB (%s): %s" % (e["method"], e["evidence"])
            if (sa, pc) in have:
                o = have[(sa, pc)]
                o["confidence"], o["method"], o["evidence"] = "confirmed", "kb-" + e["method"], ev + " | matcher: " + o["evidence"]
            else:
                a, p = int(sa, 16), int(pc, 16)
                rows.append({"steam": sa, "steam_name": steam[a]["name"] if a in steam else sa, "sh4": pc,
                             "sh4_label": "loc_%08x" % p, "bank": sh4[p]["bank"] if p in sh4 else "?", "confidence": "confirmed",
                             "method": "kb-" + e["method"], "evidence": ev, "score": 0, "runner_up": "",
                             "steam_ninsn": steam[a]["ninsn"] if a in steam else 0, "sh4_ninsn": sh4[p]["ninsn"] if p in sh4 else 0})
            n_ext += 1
        print("merged", n_ext, "external KB confirmations")
    kb_r = {r["id"]: r for r in json.load(open(os.path.join(HERE, "cache", "kb_routines.json"), encoding="utf-8"))[1]["result"]}
    kbg = json.load(open(os.path.join(HERE, "cache", "kb_globals_fields.json"), encoding="utf-8"))
    kb_globals = kbg[1]["result"]
    kb_edges = json.load(open(os.path.join(HERE, "cache", "kb_edges.json"), encoding="utf-8"))
    kb_reads = kb_edges[1]["result"]
    kb_writes = kb_edges[2]["result"]

    def role_of(pc):
        r = kb_r.get("routine:loc_%08x" % pc)
        return (r or {}).get("role") or ""

    def note_of(pc):
        r = kb_r.get("routine:loc_%08x" % pc)
        return (r or {}).get("note") or ""

    # ---------------- CSV
    os.makedirs(DOCS, exist_ok=True)
    order = {"confirmed": 0, "high": 1, "medium": 2, "low": 3}
    rows.sort(key=lambda o: (int(o["steam"], 16), order[o["confidence"]]))
    with open(os.path.join(DOCS, "steam_sh4_map.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["steam_addr", "sh4_pc", "confidence", "evidence", "method", "steam_name", "sh4_label", "bank",
                    "sh4_role", "score", "runner_up", "steam_ninsn", "sh4_ninsn"])
        for o in rows:
            w.writerow([o["steam"], o["sh4"], o["confidence"], o["evidence"], o["method"], o["steam_name"],
                        o["sh4_label"], o["bank"], role_of(int(o["sh4"], 16)), o["score"], o["runner_up"],
                        o["steam_ninsn"], o["sh4_ninsn"]])

    # ---------------- coverage
    by_steam = collections.defaultdict(list)
    for o in rows:
        by_steam[int(o["steam"], 16)].append(o)
    primary = {a: min(os_, key=lambda o: (0 if o["method"] in ("seed", "fingerprint", "fingerprint+callgraph") else 1, order[o["confidence"]]))
               for a, os_ in by_steam.items()}
    tiers = collections.Counter(o["confidence"] for o in rows)
    tiers_primary = collections.Counter(o["confidence"] for o in primary.values())
    methods = collections.Counter(o["method"] for o in rows)
    game = [a for a in steam if GAME_LO <= a < GAME_HI and steam[a]["ninsn"] <= 20000]
    game_matched = [a for a in game if a in primary]
    game_with_tokens = [a for a in game if steam[a]["imms"] or steam[a]["blk_offs"] or steam[a]["g_offs"] or steam[a]["floats"] or steam[a]["dcaddrs"]]
    sh4_matched = set(int(o["sh4"], 16) for o in rows)
    sh4_with_tokens = [p for p, f in sh4.items() if f["consts"] or f["blk_offs"] or f["dcaddrs"] or f["strings"]]

    # ---------------- render-relevant Steam functions
    def touches(f):
        offs = set(f["blk_offs"]) | set(f["g_offs"])
        hits = []
        for lo, hi, name in RENDER_REGIONS:
            if any(lo <= o < hi for o in offs):
                hits.append(name)
        fo = [o for o in offs if FIGHTER_LO <= o < FIGHTER_HI and ((o - FIGHTER_LO) % FIGHTER_STRIDE) >= 0x120]
        if fo:
            hits.append("fighter fields >=0x120 (%s)" % ",".join("0x%x" % o for o in sorted(fo)[:4]))
        return hits

    render_rows = []
    for a in sorted(game):
        h = touches(steam[a])
        if not h:
            continue
        offs = sorted((set(steam[a]["blk_offs"]) | set(steam[a]["g_offs"])))
        rr = [o for o in offs if any(lo <= o < hi for lo, hi, _ in RENDER_REGIONS) or (FIGHTER_LO <= o < FIGHTER_HI)]
        cps = by_steam.get(a, [])
        render_rows.append((a, h, rr, cps))

    # ---------------- markdown
    md = []
    md.append("# Steam MvC2 x86-64 <-> Dreamcast SH4 function correspondence map (%s)\n" % TODAY)
    md.append("Programmatic map between the unpacked Steam executable (`C:\\Users\\trist\\ghidra_projects\\mvc_dump.bin`, Ghidra "
              "project `dumpproj`, read through the GhidraMCP HTTP bridge on :8080) and the marvelous2 SH4 disassembly "
              "(`C:\\Users\\trist\\projects\\_marv_re\\build\\bank*.asm`, `loc_8c......` == PC). Machine-readable: "
              "`docs/steam_sh4_map.csv`. Scripts: `d3dcap/replay/re_map/` (`ghidra_export.py`, `sh4_export.py`, `blkmap.py`, "
              "`match.py`, `seeds.json`, `report.py`). KB seed: `maplecast-flycast/tools/re_kb/101_steam_function_map.surql`.\n")
    md.append("Every row is tagged **CONFIRMED** (both sides read by a human; `seeds.json`) or **INFERRED** (fingerprint / "
              "call-graph only; tiers high / medium / low). An INFERRED row is a hypothesis with its evidence and runner-up "
              "attached, not a fact.\n")
    md.append("## 1. Method\n")
    md.append("1. **Ghidra export** (`ghidra_export.py fetch|finger`): every one of the %d functions (`/list_functions`, "
              "`/disassemble_function`, `/get_function_by_address`, `/strings`) -> per-function fingerprint: immediates >= 0x100, "
              "f32/f64 constants (read from the dump at the rip-relative address), blk-relative displacements (register taint from "
              "`DAT_142edf560` = blk and `DAT_142edf580` = G = blk+0x3CB8, G offsets rebased to blk), DC-address-like immediates, "
              "string refs, struct displacements, callee list (in order).\n" % len(steam))
    md.append("2. **SH4 export** (`sh4_export.py`): %d routines from the bank asm (function starts = `;=====` separator labels + "
              "`bsr` targets + pool-held code pointers at clean boundaries); literal pools attributed by *reference* "
              "(`mov.l/mov.w/mova @(label,PC)`); `GameGlobalPointer`+offset and absolute 0x8C26xxxx accesses converted to Steam blk "
              "offsets through `blkmap.py`; struct displacements mapped through the fighter delta ladder.\n" % len(sh4))
    md.append("3. **Match** (`match.py`): rarity-weighted token overlap (exact constants first: e.g. 812.357 = 0x444b16de, "
              "0x0D82D000, 0xC10, table sizes), blk-offset set overlap, strings, weak struct-displacement overlap; then call-graph "
              "propagation (ordinal callee tokens, caller tokens, call-sequence sandwich alignment); mutual-best with margin and "
              "an evidence gate (a single shared constant or a single ordinal token cannot carry a pair). SH4 token sets are "
              "expanded with their small rarely-called callees because the recompile inlines them; an absorb pass then records "
              "those callees as `inlined` into the same Steam function. Two Ghidra mega-\"functions\" "
              "(`FUN_14006a3f0`, 186,634 insns; `caseD_0` at 0x1406415e0, 238,981 insns) are switch blobs and were excluded.\n")
    md.append("4. **Seeds**: %d CONFIRMED pairs read on both sides (section 3) drive the propagation.\n" % len([o for o in rows if o["method"] == "seed"]))
    md.append("## 2. Coverage\n")
    md.append("| what | count |\n|---|---|")
    md.append("| Steam functions total (Ghidra) | %d |" % len(steam))
    md.append("| Steam functions in the game range 0x140600000..0x1408E0000 (excluding the 2 mega blobs) | %d |" % len(game))
    md.append("| ... of which carry any exact-constant / blk / DC-address token | %d |" % len(game_with_tokens))
    md.append("| SH4 routines (marvelous2 banks) | %d |" % len(sh4))
    md.append("| ... of which carry any exact-constant / blk / DC-address / string token | %d |" % len(sh4_with_tokens))
    md.append("| **Steam functions with a primary SH4 counterpart** | **%d** (game range: %d) |" % (len(primary), len(game_matched)))
    md.append("| ... by tier (primary rows) | %s |" % ", ".join("%s %d" % (k, tiers_primary[k]) for k in ("confirmed", "high", "medium", "low")))
    md.append("| all map rows incl. `inlined` (one Steam function can hold several SH4 routines) | %d (%s) |" % (len(rows), ", ".join("%s %d" % (k, tiers[k]) for k in ("confirmed", "high", "medium", "low"))))
    md.append("| rows by method | %s |" % ", ".join("%s %d" % kv for kv in sorted(methods.items())))
    md.append("| SH4 routines placed (matched or inlined) | %d |" % len(sh4_matched))
    md.append("\nHonest reading: the map is dense around the render / object-pool / loader / NaomiLib core (where the anchors are) "
              "and sparse in character move code, whose SH4 side lives partly in the S_PLxx overlays (not in `bank*.asm`) and "
              "whose Steam side is largely swallowed by the `caseD_0` blob. Coverage there needs more seeds, not more heuristics.\n")

    md.append("## 3. CONFIRMED anchors (both sides read)\n")
    md.append("| Steam | SH4 | what | evidence |\n|---|---|---|---|")
    for o in rows:
        if o["method"] in ("seed", "seed-inlined") or o["method"].startswith("kb-"):
            md.append("| `%s` | `%s` (%s) | %s | %s |" % (o["steam_name"], o["sh4_label"], o["bank"],
                      SEED_ROLES.get(int(o["steam"], 16), "") if o["method"] == "seed" else ("inlined into " + o["steam_name"] if o["method"] == "seed-inlined" else "confirmed by another lane (KB)"),
                      o["evidence"].replace("|", "/")))
    md.append("\n### Block-map corrections found by this crawl (all from pairs above)\n")
    md.append("* **Pool-tail bookkeeping is pointer-scaled, not a flat delta.** DC `0x8C287A54` free_head(4) free_tail(4) heads[14](4) "
              "tails[14](4) counts[14](2) freecnt(2) freecnt2(2) <-> Steam `blk+0x2EDD8` with 8-byte pointers "
              "(`loc_8c044dce` <-> `FUN_14061e170`). The memory note's flat delta 0x8C258910 for `..0x2F4D0` only holds at the "
              "draw-list base; draw-list handles are also 4 -> 8 B (`0x8C287DE0 + L*0x180 + i*4` <-> `blk+0x2F4D0 + L*0x300 + i*8`).")
    md.append("* **The stage/camera struct (DC 0x8C26A518..0x8C26AA54) is piecewise:** camera block delta 0x8C263C10 "
              "(eye +0xC/10/14 -> blk+0x6914/18/1C, look-at +0x54.. -> 0x695C.., fov +0x6C -> 0x6974, near/far +0x80/84 -> 0x6988/8C; "
              "`loc_8c02e246`/`8c02e1a4` <-> `FUN_14061d6a0`/`FUN_14061d7e0`), deck colour + render mode delta 0x8C263C00 "
              "(0x8c26a8a8 -> 0x6CA8, 0x8c26a8e4 -> 0x6CE4), STG_ID delta 0x8C263C58 (0x8c26a95c -> 0x6D04), LayerZ delta "
              "0x8C263C6C (0x8c26a974 -> 0x6D08). `blkmap.py` returns None for the un-anchored parts of that range on purpose.")
    md.append("* `loc_8c0450c0` (468 DC call sites) is the node **unlink/free** (`FUN_14061df40`), `loc_8c044f12`+`8c044f26` the "
              "**alloc** (`FUN_14061dbe0`); `FUN_140612f70` is not a separate routine but the sprite-id-bit15-set path of "
              "`loc_8c034bea` that Ghidra split off `FUN_1406129f0` (reached by a conditional jump at 0x140612a02).\n")

    md.append("## 4. Render-relevant Steam functions and their SH4 counterparts\n")
    md.append("Steam functions (game range) that touch blk 0x3CB8..0x6D10 (globals/camera), 0x2EDD8..0x2EEE8 (node-pool lists), "
              "0x2F4D0..0x324F8 (draw list) or fighter-array fields >= 0x120 (absolute `blk+0x3DB8+i*0x738+off` references; "
              "functions that reach fighter fields only through a pointer register are not detectable this way and are not "
              "listed). %d functions; UNMATCHED means no SH4 counterpart was found by the matcher, not that none exists.\n" % len(render_rows))
    md.append("| Steam | touches | blk offsets (first 10) | SH4 counterpart(s) | tier |\n|---|---|---|---|---|")
    for a, h, rr, cps in render_rows:
        cp = "; ".join("`%s`%s" % (o["sh4_label"], "" if o["method"] in ("seed", "fingerprint", "fingerprint+callgraph") else " (inlined)") +
                       ((" - " + role_of(int(o["sh4"], 16))) if role_of(int(o["sh4"], 16)) else "") for o in cps) or "UNMATCHED"
        tier = "/".join(sorted(set(o["confidence"] for o in cps), key=lambda t: order[t])) if cps else "-"
        md.append("| `%s` | %s | %s | %s | %s |" % (steam[a]["name"], "; ".join(h), " ".join("0x%x" % o for o in rr[:10]), cp, tier))

    md.append("\n## 5. Falsification tests (how to break this map)\n")
    md.append("1. Any CONFIRMED pair: decompile the Steam side (`/decompile_function?address=`) and read the SH4 routine; the callee "
              "sequence and the blk/global set must correspond under `blkmap.py`. A mismatch in a seed invalidates every pair "
              "propagated from it (the CSV `evidence` column names the pair ids used).")
    md.append("2. INFERRED `high` rows: the `runner_up` column gives the second-best candidate and its score; if reading shows "
              "the runner-up is the true counterpart, lower `MARGIN` is not the fix -- add the pair to `seeds.json` and re-run.")
    md.append("3. The stage-struct deltas: sample `blk+0x6914..0x698C`, `0x6CA8`, `0x6CE4`, `0x6D04`, `0x6D08` live and compare with "
              "DC `0x8C26A524..`, `0x8C26A8A8`, `0x8C26A8E4`, `0x8C26A95C`, `0x8C26A974` in flycast on the same frame.")
    md.append("4. Re-run end to end: `python ghidra_export.py fetch` (resumable), `python ghidra_export.py finger`, "
              "`python sh4_export.py`, `python match.py`, `python report.py`; then, from the maplecast-flycast repo root, "
              "`PYTHONIOENCODING=utf-8 python tools/re_kb/apply_seed.py tools/re_kb/101_steam_function_map.surql` "
              "(one statement per request; `rekb.sh @file` fails on this 5 MB file with 'length limit exceeded' and applies NOTHING).")
    md.append("\n## 6. Precision spot-check of INFERRED rows (2026-09-02)\n")
    md.append("Six `high` rows drawn at random (`random.seed(7)`) and read on both sides before sign-off:\n")
    md.append("| Steam | SH4 | verdict | why |\n|---|---|---|---|")
    md.append("| `FUN_1406104b0` | `loc_8c02dc1c` | CORRECT | two stores: DC `@r5=0, @(4,r5)=r4` == Steam `blk+0x6CB4=0, blk+0x6CB8=param` (also corroborates the 0x8C263C00 delta) |")
    md.append("| `caseD_3` @0x140632b70 | `loc_8c03f3a8` | CORRECT | same `*(G+8)--`, `==0 -> *(G+5)++, *(G+8)=0x20` prologue |")
    md.append("| `caseD_4` @0x140765100 | `loc_8c069ba6` | CORRECT | same `*(node+0x18 -> +0x28)+0x1a0` test against the 0x1600/0x1601 family, same alloc call |")
    md.append("| `FUN_140609e30` | `loc_8c041e44` | CORRECT | same `G+0x43`, `G+0x14==0x40`, `G+0x2D` chain |")
    md.append("| `FUN_14060a270` | `loc_8c0357d8` | CORRECT | same `{i, 0x10, 0}` table fill after the default loader; Steam unrolled x8, stride 0x1C -> 0x38 |")
    md.append("| `FUN_140623350` | `loc_8c04d000` | DOUBTFUL | DC calls a routine first and tests a global byte >= 5 that the Steam side lacks; shared evidence is only the +-0.0833 constants and the 0xC00/0x800 masks. Treat as unverified. |")
    md.append("\nEstimated precision of the `high` tier from this sample: 5/6. `medium`/`low` were not sampled and should be assumed weaker.")
    md.append("\n## 7. Known gaps / UNKNOWN\n")
    md.append("* `FUN_14061d900` (Ghidra merged the four node constructors reached through `PTR_caseD_4_140a6e5c8` into one body) has "
              "no single SH4 counterpart; the DC constructor table is `loc_8c045020` (4 entries) -- not mapped.")
    md.append("* `FUN_140848ee0` (NaomiLib object record walk, role assigned by the WORLD-CAMERA lane) and `FUN_140846c30` (matrix slot "
              "store) carry no constants and were not reached by propagation with enough evidence; their SH4 counterparts are UNKNOWN here.")
    md.append("* The live KB also holds 12 `steam_routine` roles written by hand by the WORLD-CAMERA lane on functions this matcher "
              "left unmatched (fight camera x/y/zoom, matrix pre/post-multiply, queue flush, ...); the seed file coalesces "
              "(`role ?? 'UNMATCHED'`) so re-applying it cannot erase them.")
    md.append("* Functions inside the two Ghidra mega blobs are not in Ghidra's function list at all; re-analysis of the binary "
              "(splitting `caseD_0`) is required before this map can cover the character move code.")
    md.append("* The SH4 side does not include the S_PLxx character-program overlays (`_marv_re/char_prg`).")
    with open(os.path.join(DOCS, "STEAM-SH4-FUNCTION-MAP.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")

    # ---------------- SurQL seed
    q = []
    q.append("-- 23: Steam x86-64 <-> SH4 function correspondence map (programmatic crawl, %s)." % TODAY)
    q.append("-- Generated by mvc-live-skins-quarters/d3dcap/replay/re_map/report.py from match_result.json.")
    q.append("-- Idempotent: UPSERT for nodes, RELATE with explicit edge ids for edges (re-running updates in place).")
    q.append("-- APPLY WITH tools/re_kb/apply_seed.py (per statement). This file exceeds the server POST body limit: rekb.sh @file returns")
    q.append("-- 'length limit exceeded' and applies nothing (verified 2026-09-02).")
    q.append("-- Evidence classes: recompiles.confidence = confirmed (both sides read) | high | medium | low (fingerprint / call-graph only).")
    q.append("USE NS re DB kb;")
    q.append("DEFINE TABLE IF NOT EXISTS steam_routine SCHEMALESS COMMENT 'Steam x86-64 function (Ghidra); id=FUN_14xxxxxxx; fields: addr, role, note, blk_reads[], blk_writes[], consts[]';")
    q.append("DEFINE TABLE IF NOT EXISTS recompiles SCHEMALESS COMMENT 'steam_routine -> routine: this x86 function is the recompile of this SH4 routine; fields: confidence(confirmed/high/medium/low), method, evidence';")
    q.append("UPSERT source:ghidra_steam_crawl SET kind='ghidra', strength='code', ref='mvc_dump.bin via :8080 bridge', "
             "note='Programmatic crawl of every function of the unpacked Steam MvC2 executable (Ghidra project dumpproj, GhidraMCP HTTP bridge): "
             "per-function fingerprints (constants, blk offsets, DC addresses, strings, callees) matched against the marvelous2 SH4 banks. "
             "Scripts: mvc-live-skins-quarters/d3dcap/replay/re_map/. Map: docs/STEAM-SH4-FUNCTION-MAP.md + docs/steam_sh4_map.csv.';")
    q.append("UPSERT source:doc_stage_draw_ghidra SET kind='doc', strength='code', ref='mvc-live-skins-quarters/docs/STAGE-DRAW-GHIDRA.md', "
             "note='Ghidra read-set of the Steam stage draw path (2026-09-02): render dispatcher, node pool, stage loader, list walkers. Claims tagged CONFIRMED were decompiled and read.';")

    # steam_routine rows: all game-range functions + every matched function
    want = set(game) | set(primary)
    for a in sorted(want):
        f = steam[a]
        cps = by_steam.get(a, [])
        if cps:
            p = primary[a]
            pc = int(p["sh4"], 16)
            role = SEED_ROLES.get(a) or (role_of(pc) if p["confidence"] in ("confirmed", "high") else "")
            if not role:
                role = "matched (%s) to %s" % (p["confidence"], p["sh4_label"])
            note = "%s of SH4 %s (%s, %s). %s" % ("Recompile" if p["confidence"] == "confirmed" else "Probable recompile",
                                                   p["sh4_label"], p["confidence"], p["method"], p["evidence"])
            if len(cps) > 1:
                note += " Also holds inlined: " + ", ".join(o["sh4_label"] for o in cps if o is not p) + "."
            kbn = note_of(pc)
            if kbn and p["confidence"] in ("confirmed", "high"):
                note += " SH4 note: " + kbn[:300]
        else:
            role = "UNMATCHED"
            note = "No SH4 counterpart found by the crawl (fingerprint: %d imms, %d blk offsets, %d callees)." % (
                len(f["imms"]), len(f["blk_offs"]) + len(f["g_offs"]), len(set(f["callees"])))
        consts = sorted(set(v for v in f["imms"] if not (0x140000000 <= v < 0x1440e8000)) | set(f["dcaddrs"]))[:40]
        # unmatched rows must not clobber a role/note another lane wrote by hand: coalesce with the existing value
        role_expr = "'%s'" % esc(role) if cps else "role ?? '%s'" % esc(role)
        note_expr = "'%s'" % esc(note) if cps else "note ?? '%s'" % esc(note)
        q.append("UPSERT steam_routine:FUN_%x SET addr='0x%x', name='%s', role=%s, note=%s, ninsn=%d, size=%d, "
                 "blk_reads=%s, blk_writes=%s, consts=%s, floats=[%s], strings=[%s], callees=[%s], matched=%s;" % (
                     a, a, esc(f["name"]), role_expr, note_expr, f["ninsn"], f["size"],
                     hexlist(sorted(set(f["blk_reads"]))[:40]), hexlist(sorted(set(f["blk_writes"]))[:40]), hexlist(consts),
                     ", ".join("%r" % float("%.6g" % x) for x in f["floats"] if x == x and abs(x) != float("inf"))[:20] if False else ", ".join("%r" % float("%.6g" % x) for x in [y for y in f["floats"] if y == y and abs(y) != float("inf")][:20]),
                     ", ".join("'%s'" % esc(s) for s in f["strings"][:10]),
                     ", ".join("'FUN_%x'" % c for c in sorted(set(f["callees"]))[:40]),
                     "true" if cps else "false"))
        q.append("RELATE steam_routine:FUN_%x->cites->source:ghidra_steam_crawl;" % a if False else
                 "RELATE steam_routine:FUN_%x->cites:sr_FUN_%x_ghidra->source:ghidra_steam_crawl;" % (a, a))
    # recompiles edges
    for o in rows:
        a, pc = int(o["steam"], 16), int(o["sh4"], 16)
        method = o["method"]
        if method.startswith("kb-"):
            continue  # owned by the other lane's seed; never overwrite
        q.append("RELATE steam_routine:FUN_%x->recompiles:FUN_%x_loc_%08x->routine:loc_%08x SET confidence='%s', method='%s', evidence='%s', inlined=%s;" % (
            a, a, pc, pc, o["confidence"], method, esc(o["evidence"][:400]), "true" if method in ("inlined", "seed-inlined") else "false"))
    # calls among matched steam functions
    ncalls = 0
    for a in sorted(primary):
        for c in sorted(set(steam[a]["callees"])):
            if c in primary:
                q.append("RELATE steam_routine:FUN_%x->calls:FUN_%x_FUN_%x->steam_routine:FUN_%x;" % (a, a, c, c))
                ncalls += 1
    # globals: existing rows + new ones with known meaning
    new_globals = [
        ("blackout_gate", 0x8C2682D8, 0x3D50, "u8", "G+0x98: when non-zero the deck and lists 5/6 are skipped (super blackout). Read by the render dispatcher on both builds (loc_8c030858 mov.w 0x98; FUN_140620960 *(G+0x98)). Set per frame in FUN_14061f030 from DAT_142edf628+0x96 (STAGE-DRAW-GHIDRA)."),
        ("render_mode", 0x8C26A8E4, 0x6CE4, "i32", "render mode: 0 = match (sprite walk, deck, lists 5-8, HUD), 1 = list 9 only, else lists 7/8/9. Getter loc_8c0310f2 == FUN_140619960."),
        ("deck_colour_rgb", 0x8C26A8A8, 0x6CA8, "f32[3]", "stage deck (model 0) vertex colour r/g/b; DC loc_8c030cfc loads 0x8c26a8a4+4/8/C into fr4/5/6, Steam FUN_140849b00(blk+0x6CA8,0x6CAC,0x6CB0); also multiplies nodes with flag 0x800."),
        ("layerz_table", 0x8C26A974, 0x6D08, "f32[16]", "per-layer depth base table [15,17,19,21,23,25,27,29,10,11,12,13,30,31,32,33] indexed by node +0x24 layer byte; read by Render Main Sprite (loc_8c03093c) and the Steam sprite walker."),
        ("pool_free_head", 0x8C287A54, 0x2EDD8, "ptr", "object-pool free-list head (DC 4-byte, Steam 8-byte pointer)."),
        ("pool_free_tail", 0x8C287A58, 0x2EDE0, "ptr", "object-pool free-list tail."),
        ("pool_list_heads", 0x8C287A5C, 0x2EDE8, "ptr[14]", "System-A list heads, L=0..13 (DC stride 4, Steam stride 8). heads[12] = 0x8c287a8c / blk+0x2EE48 is walked for the per-fighter 3D part nodes."),
        ("pool_list_tails", 0x8C287A94, 0x2EE58, "ptr[14]", "System-A list tails."),
        ("pool_list_counts", 0x8C287ACC, 0x2EEC8, "u16[14]", "per-list node counts."),
        ("pool_free_counts", 0x8C287AE8, 0x2EEE4, "u16[2]", "free node counts (0xF6 and 0x100 at init); alloc refuses when either is 0."),
        ("camera_eye", 0x8C26A524, 0x6914, "f32[3]", "render camera eye x / y / zoom (zoom == 812.357 constant on Steam); stage struct +0xC/+0x10/+0x14."),
        ("camera_lookat", 0x8C26A56C, 0x695C, "f32[3]", "camera look-at x/y/z; stage struct +0x54/58/5C."),
        ("camera_fov", 0x8C26A584, 0x6974, "f32", "camera FOV in degrees; both builds compute (fov*32768/360+0.5)&0xffff for the perspective call."),
        ("camera_nearfar", 0x8C26A598, 0x6988, "f32[2]", "camera near / far; stage struct +0x80/+0x84."),
        ("list12_disable_flag", 0x8C268254, 0x3CCC, "u32", "G+0x14: == 0x40 disables list 12 (per-fighter 3D parts) and the per-stage prop init; default 0x20."),
    ]
    for gid, dc, so, ty, note in new_globals:
        q.append("UPSERT global:%s SET addr='0x%08X', steam_off='0x%X', type='%s', note='%s';" % (gid, dc, so, ty, esc(note)))
        q.append("RELATE global:%s->cites:g_%s_ghidra->source:ghidra_steam_crawl;" % (gid, gid))
    # existing globals: annotate the Steam offset where the block map gives one
    gmap = {}
    for g in kb_globals:
        try:
            dc = int(g["addr"], 16)
        except Exception:
            continue
        so = dc_to_blk(dc)
        if so is not None:
            gid = g["id"].split(":", 1)[1]
            gmap[so] = gid
            q.append("UPSERT global:%s SET steam_off='0x%X';" % (gid, so))
    for gid, dc, so, ty, note in new_globals:
        gmap[so] = gid
    # reads/writes edges from Steam functions to globals (by exact blk offset; arrays: match the base offset only)
    nrw = 0
    for a in sorted(want):
        f = steam[a]
        for kind, offs in (("reads", f["blk_reads"]), ("writes", f["blk_writes"])):
            for o in sorted(set(offs)):
                gid = gmap.get(o)
                if gid:
                    q.append("RELATE steam_routine:FUN_%x->%s:FUN_%x_%s->global:%s SET evidence='blk+0x%X';" % (a, kind, a, gid, gid, o))
                    nrw += 1
    # inherit DC routine -> field/global edges for confirmed/high primary pairs
    inh = 0
    for a, p in primary.items():
        if p["confidence"] not in ("confirmed", "high"):
            continue
        rid = "routine:loc_%08x" % int(p["sh4"], 16)
        for kind, edges in (("reads", kb_reads), ("writes", kb_writes)):
            for e in edges:
                if e["in"] == rid:
                    tgt = e["out"]
                    q.append("RELATE steam_routine:FUN_%x->%s:FUN_%x_%s->%s SET evidence='inherited from %s (%s)';" % (
                        a, kind, a, tgt.replace(":", "_"), tgt, rid, p["confidence"]))
                    inh += 1
    # findings
    findings = [
        ("steam_deck_drawn_by_direct_call", "The stage deck (STGxxPOL model 0) is not a System-A list node on Steam: FUN_140620960 draws it by a direct call FUN_140849c10(*(u64*)PTR_DAT_142edf588) after FUN_14061d7e0 camera, FUN_140847950(0) push, FUN_140847ca0 identity, FUN_140849b00 colour; pop FUN_1408478c0(1). The DC build does the identical sequence in loc_8c030cc0 (8c02e1a4, 8c120950(0), 8c121100, 8c030cfc, 8c1235e0(model0), 8c120900(1)).",
         ["steam_routine:FUN_140620960", "steam_routine:FUN_140849c10", "routine:loc_8c030cc0"]),
        ("steam_blackout_gate_g98", "Both builds skip the deck and lists 5/6 when *(G+0x98) != 0 (Steam blk+0x3D50; DC 0x8c2682d8 via mov.w 0x98 in loc_8c030858). The dispatcher also tests *(G+0x2E)==1 to tail-call a post-render routine (DC loc_8c031470).",
         ["steam_routine:FUN_140620960", "global:blackout_gate", "routine:loc_8c030858"]),
        ("steam_node_alloc_is_insertion", "FUN_14061dbe0(ctx, L, kind) pops the free list, zeroes 0x280 bytes, writes node+3=L and dispatches PTR_caseD_4_140a6e5c8[kind] (kind 1 = append at tail); DC loc_8c044f12/8c044f26 pop 0x8c287a54, node+3=list, ctor table loc_8c045020[kind]. FUN_14061df40 / loc_8c0450c0 unlink and push back on the free list and clear the draw gate (+0x170 / +0x12C).",
         ["steam_routine:FUN_14061dbe0", "steam_routine:FUN_14061df40", "routine:loc_8c044f12", "routine:loc_8c0450c0"]),
        ("steam_node_e8_is_parent_matrix", "In list-5 stage prop nodes +0xE8 points at the PARENT NODE'S +0xA8 matrix (not a model); FUN_140620740 loads it as the stack top before applying the node's own pos/rot/scale and stores the composed world matrix back into node+0xA8 (FUN_140846a00). DC counterpart loc_8c0301ce with the per-node body loc_8c0301f6.",
         ["steam_routine:FUN_140620740", "routine:loc_8c0301ce"]),
        ("steam_stage_model_table_static", "PTR_DAT_142edf588 -> DAT_142edf630 (352 x u64 host pointers, count at +0xB00, texture header list at +0xB08) is a static table filled by FUN_14060c370(1) -> FUN_14060d8f0 from the POL loaded at DC address 0x0D82D000 (host ram + 0x182D000); the stage data is outside blk. TCW = 0xC10 + texIndex is assigned per record by FUN_140844dc0 after FUN_1408458a0(0xC10).",
         ["steam_routine:FUN_14060c370", "steam_routine:FUN_14060d8f0", "steam_routine:FUN_140844dc0", "steam_routine:FUN_1408458a0"]),
        ("steam_list12_part_nodes", "FUN_140620ea0 draws list 0xB (HUD) then, unless *(G+0x14)==0x40, walks list 0xC nodes (+0x170 gate) into FUN_140653a70 (per-fighter 3D part draw; nodes from FUN_1406539a0 with +0xA0=0, +0xE8=0). DC: loc_8c030dcc -> loc_8c030d68 walks heads[12]=0x8c287a8c with the +0x12C gate into loc_8c0f215e.",
         ["steam_routine:FUN_140620ea0", "steam_routine:FUN_140653a70", "routine:loc_8c030dcc", "global:list12_disable_flag"]),
        ("steam_memory_layout_dc_ram_image", "FUN_140607b50: base = *PTR_DAT_140acd3a0; ctx = DAT_142ef0ab0 = base+0x8000000; ctx[1] = base+0x8400000 = the 32 MB DC work-RAM image, so DC address X maps to host ctx[1] + (X - 0x0C000000); ctx[2] = blk = base + ((rand&0x3F)+0xC0)<<20 (randomised per boot).",
         ["steam_routine:FUN_140607b50"]),
        ("steam_sprite_walker_inlines_render_bodies", "Steam FUN_140620f10 is the recompile of the DC slot-table walker loc_8c0308c2 with both per-object renderers inlined: loc_8c03093c (Render Main Sprite, category 0) and loc_8c030af8 (effect path). Same constant set on both sides (812.357, 480, 640, 1000, 0.1, 0.001), same draw gate (+0x12C -> +0x170), same list geometry (0x8c287de0 stride 0x180 -> blk+0x2F4D0 stride 0x300; counts 0x8c2895e0 -> blk+0x324D0).",
         ["steam_routine:FUN_140620f10", "routine:loc_8c0308c2", "routine:loc_8c03093c", "routine:loc_8c030af8"]),
        ("steam_pool_tail_pointer_scaled", "The object-pool bookkeeping after the 256-node pool is pointer-scaled between builds, not a flat delta: DC 0x8C287A54 {free_head, free_tail, heads[14], tails[14]} (4 B each) then counts[14] u16, freecnt u16, freecnt2 u16 <-> Steam blk+0x2EDD8 with 8 B pointers (heads blk+0x2EDE8, tails 0x2EE58, counts 0x2EEC8, free counts 0x2EEE4/6). Draw-list handles are likewise 4 -> 8 B (0x8C287DE0+L*0x180+i*4 <-> blk+0x2F4D0+L*0x300+i*8). Supersedes the flat delta 0x8C258910 in memory note mvc2-dc-steam-block-map for that range.",
         ["steam_routine:FUN_14061e170", "routine:loc_8c044dce", "global:pool_list_heads", "global:pool_free_head"]),
        ("steam_stage_struct_piecewise_deltas", "The DC stage/camera struct 0x8C26A518..0x8C26AA54 maps onto Steam blk piecewise: camera block delta 0x8C263C10 (eye +0xC -> blk+0x6914, look-at +0x54 -> 0x695C, fov +0x6C -> 0x6974, near/far +0x80/84 -> 0x6988/8C), deck colour and render mode delta 0x8C263C00 (0x8c26a8a8 -> 0x6CA8, 0x8c26a8e4 -> 0x6CE4), STG_ID delta 0x8C263C58 (0x8c26a95c -> 0x6D04), LayerZ table delta 0x8C263C6C (0x8c26a974 -> 0x6D08). Sub-ranges between those anchors are UNKNOWN; do not extrapolate.",
         ["steam_routine:FUN_14061d7e0", "steam_routine:FUN_14061d6a0", "routine:loc_8c02e246", "global:camera_eye", "global:stg_id", "global:layerz_table"]),
        ("steam_submit_split_by_ghidra", "Steam FUN_1406129f0 is loc_8c034bea (sprite submit) with the bit15-clear body path loc_8c0344d4 inlined; the bit15-set path (loc_8c0348c8) was split off by Ghidra as FUN_140612f70, reached only by a conditional jump from 0x140612a02. Same tests: sprite id == -1 -> 0; (id>>15)&1.",
         ["steam_routine:FUN_1406129f0", "steam_routine:FUN_140612f70", "routine:loc_8c034bea", "routine:loc_8c0344d4", "routine:loc_8c0348c8"]),
        ("steam_naomilib_matrix_stack", "NaomiLib matrix stack: DC struct {i16 count, i16 max, ptr@+8} at 0x8C2D68E8 with XMTRX saved/restored by fschg/frchg pairs (push loc_8c120950, pop(n) loc_8c120900, identity loc_8c121100); Steam keeps the stack pointer at ctx+0x1f81b0, free count at ctx+0x1f81bc and the current matrix at DAT_142ef0ab8 (FUN_140847950 push, FUN_1408478c0 pop, FUN_140847ca0 identity from the constant at 0x140ab20c0).",
         ["steam_routine:FUN_140847950", "steam_routine:FUN_1408478c0", "steam_routine:FUN_140847ca0", "routine:loc_8c120950", "routine:loc_8c120900"]),
    ]
    for slug, stmt, abouts in findings:
        q.append("UPSERT finding:%s SET statement='%s', status='confirmed', confidence='high', date='%s', "
                 "note='Read on both builds during the 2026-09-02 Steam<->SH4 function-map crawl; see docs/STEAM-SH4-FUNCTION-MAP.md and docs/STAGE-DRAW-GHIDRA.md.';" % (slug, esc(stmt), TODAY))
        for t in abouts:
            q.append("RELATE finding:%s->about:f_%s_%s->%s;" % (slug, slug, t.replace(":", "_"), t))
        q.append("RELATE finding:%s->cites:f_%s_ghidra->source:ghidra_steam_crawl;" % (slug, slug))
        q.append("RELATE finding:%s->cites:f_%s_stagedoc->source:doc_stage_draw_ghidra;" % (slug, slug))
    with open(SURQL, "w", encoding="utf-8") as f:
        f.write("\n".join(q) + "\n")
    print("csv rows", len(rows), "| md render rows", len(render_rows), "| surql statements", len(q),
          "| steam_routine rows", len(want), "| calls edges", ncalls, "| reads/writes edges", nrw, "| inherited", inh)
    print("primary tiers", dict(tiers_primary), "game matched", len(game_matched), "/", len(game))


if __name__ == "__main__":
    main()
