#!/usr/bin/env python3
"""Summarize one d3dcap frame inventory into the Path-B fork answer.

Usage:  python summarize.py "%TEMP%\\rrcap\\frame_123.ndjson"

Reads the NDJSON the injected DLL wrote and prints the numbers that decide whether Steam's frame is
re-renderable on WebGPU (bounded textured-quad draws) or record-only (post-heavy composite).
"""
import json
import sys
from collections import Counter, OrderedDict

# DXGI_FORMAT values we actually expect to see; anything else prints raw.
FMT = {0: "UNKNOWN", 2: "R32G32B32A32_FLOAT", 10: "R16G16B16A16_FLOAT", 24: "R10G10B10A2_UNORM",
       28: "R8G8B8A8_UNORM", 29: "R8G8B8A8_UNORM_SRGB", 87: "B8G8R8A8_UNORM", 88: "B8G8R8X8_UNORM",
       61: "R8_UNORM", 71: "BC1_UNORM", 74: "BC2_UNORM", 77: "BC3_UNORM", 80: "BC4_UNORM",
       98: "BC7_UNORM", 40: "D32_FLOAT", 45: "D24_UNORM_S8_UINT", 41: "R32_FLOAT", 57: "R8G8_UNORM"}
TOPO = {0: "UNDEFINED", 1: "POINTLIST", 2: "LINELIST", 3: "LINESTRIP",
        4: "TRIANGLELIST", 5: "TRIANGLESTRIP"}
BLEND = {1: "ZERO", 2: "ONE", 3: "SRC_COLOR", 4: "INV_SRC_COLOR", 5: "SRC_ALPHA", 6: "INV_SRC_ALPHA",
         7: "DEST_ALPHA", 8: "INV_DEST_ALPHA", 9: "DEST_COLOR", 10: "INV_DEST_COLOR",
         11: "SRC_ALPHA_SAT", 14: "BLEND_FACTOR", 15: "INV_BLEND_FACTOR"}
BLENDOP = {1: "ADD", 2: "SUBTRACT", 3: "REV_SUBTRACT", 4: "MIN", 5: "MAX"}


def fmt(v):
    return FMT.get(v, "fmt%d" % v)


def blend_str(b):
    if not b:
        return "none"
    if not b.get("en"):
        return "OPAQUE (blend disabled)"
    return "%s %s %s %s (alpha: %s %s %s)" % (
        BLENDOP.get(b["op"], b["op"]), BLEND.get(b["src"], b["src"]), "x", BLEND.get(b["dst"], b["dst"]),
        BLENDOP.get(b["opA"], b["opA"]), BLEND.get(b["srcA"], b["srcA"]), BLEND.get(b["dstA"], b["dstA"]))


def main(path, brief=False):
    draws = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                draws.append(json.loads(line))
    if not draws:
        print("no draws in %s" % path)
        return 1

    # The stream now interleaves ClearRTV / ClearDSV events with draws so a replay can reproduce the
    # exact order. They carry no pipeline state, so every per-draw section below must exclude them.
    events = draws
    clears = [d for d in draws if d.get("kind", "").startswith("Clear")]
    draws = [d for d in draws if not d.get("kind", "").startswith("Clear")]
    if not draws:
        print("frame contains only %d clear events, no draws" % len(clears))
        return 1

    if brief:
        tex = {t["p"] for d in draws for t in (d.get("tex") or []) if t and "w" in t}
        rts = {(d["rt"] or {}).get("p") for d in draws if d.get("rt")}
        blends = {blend_str(d.get("blend")) for d in draws}
        quads = sum(1 for d in draws if d["count"] == 6)
        sites = len({d.get("ret", "0x0") for d in draws})
        print("    frame %-7s %5d draws | %3d textures | %2d blend | %2d RTs | %d call sites"
              % (draws[0]["f"], len(draws), len(tex), len(blends), len(rts), sites))
        return 0

    print("=" * 78)
    print("FRAME %s  --  %d draw calls  (+%d clears)" % (draws[0]["f"], len(draws), len(clears)))
    print("=" * 78)

    if clears:
        print("\n[0] CLEARS  (in submission order; an uncleared RT keeps last frame's contents)")
        for c in clears:
            if c["kind"] == "ClearRTV":
                rt = c.get("rt") or {}
                print("    #%-5d ClearRTV  %sx%s fmt=%s  color=%s"
                      % (c["i"], rt.get("w"), rt.get("h"), rt.get("fmt"), c.get("color")))
            else:
                print("    #%-5d ClearDSV  depth=%s stencil=%s flags=%s"
                      % (c["i"], c.get("depth"), c.get("stencil"), c.get("flags")))

    # ── 1. tractability: how many draws, of what kind, at what size ──────────────────────────────
    print("\n[1] DRAW KINDS")
    for k, n in Counter(d["kind"] for d in draws).most_common():
        print("    %-24s %d" % (k, n))
    print("\n    topology:", ", ".join("%s x%d" % (TOPO.get(t, t), n)
                                       for t, n in Counter(d["topo"] for d in draws).most_common()))
    quads = sum(1 for d in draws if d["count"] == 6)
    print("    draws with exactly 6 indices (= one quad): %d / %d" % (quads, len(draws)))
    print("    index/vertex counts:", ", ".join("%d x%d" % (c, n) for c, n in
                                                Counter(d["count"] for d in draws).most_common(12)))

    # ── 2. pipeline clusters: distinct (vs, ps, inputlayout) ─────────────────────────────────────
    print("\n[2] PIPELINE CLUSTERS  (distinct vertex-shader / pixel-shader / input-layout)")
    for (vs, ps, il), n in Counter((d["vs"], d["ps"], d["il"]) for d in draws).most_common():
        print("    vs=%s ps=%s il=%s  -> %d draws" % (vs, ps, il, n))

    # ── 3. blend states: settles the additive heuristic ──────────────────────────────────────────
    print("\n[3] BLEND STATES  (ground truth for the additive-blend heuristic)")
    bl = Counter()
    for d in draws:
        bl[blend_str(d.get("blend"))] += 1
    for s, n in bl.most_common():
        print("    %-52s %d draws" % (s, n))

    # ── 4. depth ─────────────────────────────────────────────────────────────────────────────────
    print("\n[4] DEPTH STATES")
    for s, n in Counter(json.dumps(d.get("depth"), sort_keys=True) for d in draws).most_common():
        print("    %-52s %d draws" % (s, n))

    # ── 5. textures: atlas identity + whether skins survive ──────────────────────────────────────
    print("\n[5] TEXTURES BOUND TO PS SLOT 0..3")
    tex = OrderedDict()
    for d in draws:
        for slot, t in enumerate(d.get("tex") or []):
            if not t or "w" not in t:
                continue
            key = t["p"]
            e = tex.setdefault(key, {"w": t["w"], "h": t["h"], "fmt": t["fmt"], "mips": t["mips"],
                                     "slots": set(), "n": 0})
            e["slots"].add(slot)
            e["n"] += 1
    objs = {str(k).split("#", 1)[0] for k in tex}
    print("    %d distinct textures (%d objects, %d content generations)"
          % (len(tex), len(objs), len(tex)))
    if len(tex) > len(objs):
        print("    -> %d textures were REWRITTEN mid-frame; each generation is captured separately"
              % (len(tex) - len(objs)))
    for p, e in sorted(tex.items(), key=lambda kv: -kv[1]["n"])[:30]:
        print("    %s  %5dx%-5d %-20s mips=%d slots=%s  used by %d draws"
              % (p, e["w"], e["h"], fmt(e["fmt"]), e["mips"], sorted(e["slots"]), e["n"]))

    # ── 6. render targets: the pass structure / post chain ───────────────────────────────────────
    print("\n[6] RENDER-TARGET PASSES  (in submission order; each switch = a pass boundary)")
    last = None
    order = []
    for d in draws:
        rt = d.get("rt")
        key = None if not rt else (rt.get("p"), rt.get("w"), rt.get("h"), rt.get("fmt"))
        if key != last:
            order.append([key, 0])
            last = key
        order[-1][1] += 1
    for key, n in order:
        if key is None:
            print("    (no RT)                                        %d draws" % n)
        else:
            print("    %s %5dx%-5d %-20s  %d draws" % (key[0], key[1], key[2], fmt(key[3]), n))
    print("\n    -> %d pass boundaries, %d distinct render targets"
          % (len(order), len({k[0] for k, _ in order if k})))

    # ── 7. viewports ─────────────────────────────────────────────────────────────────────────────
    print("\n[7] VIEWPORTS")
    for v, n in Counter(tuple(d["vp"]) for d in draws if "vp" in d).most_common(8):
        print("    x=%g y=%g w=%g h=%g  %d draws" % (v[0], v[1], v[2], v[3], n))

    # ── 8. call sites: which game code issued these draws ────────────────────────────────────────
    # `ret` is the return address rebased to the dump image base, so it pastes straight into Ghidra.
    # The RE named 0x1402B72F0 / 0x1402B7645 as the Draw sites inside FUN_1402B6F30 (the D3D11
    # command executor). This confirms or refutes that from live data rather than by interpretation.
    print("\n[8] DRAW CALL SITES  (return address, rebased to image base 0x140000000)")
    KNOWN = {
        0x1402B717F: "FUN_1402B6F30 DrawIndexed site #1 (RE)",
        0x1402B7261: "FUN_1402B6F30 DrawIndexed site #2 (RE)",
        0x1402B72F0: "FUN_1402B6F30 Draw site #1 (RE)",
        0x1402B7645: "FUN_1402B6F30 Draw site #2 (RE)",
        0x1402B738B: "FUN_1402B6F30 DrawInstanced (RE)",
        0x1402B7431: "FUN_1402B6F30 DrawIndexedInstanced (RE)",
    }
    sites = Counter((d.get("ret", "0x0"), d["kind"]) for d in draws)
    for (ret, kind), n in sites.most_common(20):
        try:
            note = KNOWN.get(int(ret, 16), "")
        except ValueError:
            note = ""
        print("    %-14s %-22s x%-6d %s" % (ret, kind, n, note))
    print("    -> %d distinct call sites" % len({r for r, _ in sites}))

    # ── verdict prompt ───────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 78)
    print("FORK RUBRIC (RENDER-PIPELINE-HANDOVER.md A.5)")
    print("  re-renderable if: draw count bounded, mostly quads, standard blend, per-part textures")
    print("  record-only if:   post/bloom dominates, textures arrive pre-composited")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(args[0], brief="--brief" in sys.argv))
