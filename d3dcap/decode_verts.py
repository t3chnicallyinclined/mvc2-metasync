#!/usr/bin/env python3
"""Decode captured vertices using the AUTHORITATIVE input layout.

    python decode_verts.py <frame_number>        # reads %TEMP%\\rrcap

Pairs a frame's draw inventory (frame_N.ndjson) with the buffer snapshot (buf_N_vb_<ptr>.bin) and
the input-layout descriptions recorded at CreateInputLayout time (il_<ptr>.json).

Why the layout comes from il_*.json and not from staring at the bytes: 1.0f and 0x3F800000 are the
same four bytes, and a UNORM colour channel and a normalised UV occupy the same range. The
D3D11_INPUT_ELEMENT_DESC array passed to CreateInputLayout is what the hardware actually used.

Two validity gates run before anything is decoded (steam-d3d11-capture-expert, 2026-09-01):
  1. DISJOINTNESS - every draw's byte range [voff+start*stride, +count*stride) must be unique. The
     game appends into one shared dynamic VB; overlapping ranges would mean it discarded mid-frame
     and the end-of-frame snapshot holds only the last batch, making earlier vertices garbage that
     still decodes to plausible-looking floats.
  2. COVERAGE - every il/vs/ps pointer referenced by a draw must have been captured at creation
     time. Anything created before injection is unrecoverable, so an incomplete frame fails loudly
     instead of replaying a hole.
"""
import glob
import json
import os
import struct
import sys
from collections import Counter, defaultdict

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")

# DXGI_FORMAT -> (byte size, struct code, count, normalized)
FMT = {
    2:  (16, "f", 4, False),   # R32G32B32A32_FLOAT
    6:  (12, "f", 3, False),   # R32G32B32_FLOAT
    16: (8,  "f", 2, False),   # R32G32_FLOAT
    41: (4,  "f", 1, False),   # R32_FLOAT
    10: (8,  "e", 4, False),   # R16G16B16A16_FLOAT
    34: (4,  "e", 2, False),   # R16G16_FLOAT
    28: (4,  "B", 4, True),    # R8G8B8A8_UNORM
    87: (4,  "B", 4, True),    # B8G8R8A8_UNORM
    31: (4,  "B", 4, True),    # R8G8B8A8_UINT-ish
    24: (4,  "I", 1, False),   # R10G10B10A2_UNORM (raw)
}
FMT_NAME = {2: "float4", 6: "float3", 16: "float2", 41: "float", 10: "half4", 34: "half2",
            28: "unorm4(RGBA8)", 87: "unorm4(BGRA8)", 24: "R10G10B10A2"}


def load_layouts():
    out = {}
    for f in glob.glob(os.path.join(CAP, "il_*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
            out[d["il"].lower()] = d["elements"]
        except Exception:
            pass
    return out


def norm_ptr(p):
    return ("0x" + p.lstrip("0x").lstrip("0").upper()).lower() if p else p


def gate_disjoint(draws, vb):
    """Every draw on this VB must own a unique byte range."""
    rng = []
    for d in draws:
        if d.get("vb") != vb or not d.get("stride"):
            continue
        a = d["voff"] + d["start"] * d["stride"]
        b = a + d["count"] * d["stride"]
        rng.append((a, b, d["i"]))
    rng.sort()
    # An EXACT duplicate range is legitimate: the same geometry drawn twice (e.g. a two-pass sprite).
    # A PARTIAL overlap is the dangerous case -- it means the buffer was discarded and rewritten
    # mid-frame, so an earlier draw's vertices have been replaced by a later draw's.
    overlaps = 0
    dupes = 0
    back = []
    for i in range(1, len(rng)):
        a0, a1, _ = rng[i - 1]
        b0, b1, _ = rng[i]
        if (b0, b1) == (a0, a1):
            dupes += 1
        elif b0 < a1:
            overlaps += 1
    prev_end = 0
    for a, b, i in rng:
        if a < prev_end and a > 65536:   # the low arena (<64KiB) is the post-pass, not a rewind
            back.append(i)
        prev_end = max(prev_end, b)
    span = (rng[-1][1] - rng[0][0]) if rng else 0
    used = sum(b - a for a, b, _ in rng)
    return overlaps, dupes, back, span, used, len(rng)


def decode(frame, score_only=False):
    inv = os.path.join(CAP, "frame_%s.ndjson" % frame)
    if not os.path.exists(inv):
        print("no inventory:", inv)
        return 1
    draws = [json.loads(l) for l in open(inv, encoding="utf-8") if l.strip()]
    layouts = load_layouts()

    game = [d for d in draws if d.get("retmod", "game") == "game"]
    foreign = len(draws) - len(game)
    if not score_only:
        print("=" * 78)
        print("FRAME %s -- %d draws (%d game, %d foreign/overlay)" % (frame, len(draws), len(game), foreign))
        print("=" * 78)

    # ── gate 0: is this actually an IN-MATCH frame? ──────────────────────────────────────────────
    # Character select renders into the SAME 2048x1024 offscreen RT with a similar draw count as
    # gameplay, so draw count alone cannot tell them apart. Distinct bound textures can: a match binds
    # a separate sprite page per character and effect, while char-select re-binds one atlas.
    # Measured on real captures: menus 9-30, character select 22-24, in-match 96-298.
    tex_ids = {t["p"] for d in game for t in (d.get("tex") or []) if t and "w" in t}
    if score_only:
        # Ranking hook for collect.ps1: richer frame = more distinct sprite pages = more of the
        # scene (assists, effects, supers) actually exercised. 0 means "not an in-match frame".
        print(len(tex_ids) if len(tex_ids) >= 50 else 0)
        return 0
    if len(tex_ids) < 50:
        print("\n[GATE 0: IN-MATCH] %d distinct textures -- this is a MENU or CHARACTER SELECT frame,"
              % len(tex_ids))
        print("    not a match (in-match frames bind 96-298). Keep playing; capture continues.")
        return 5
    print("\n[GATE 0: IN-MATCH] %d distinct textures -- this is a real in-match frame." % len(tex_ids))

    # ── coverage gate ────────────────────────────────────────────────────────────────────────────
    print("\n[COVERAGE] creation-time captures for everything the frame references")
    for kind, key, pat in (("input layout", "il", "il_%s.json"), ("vertex shader", "vs", "vs_%s.cso"),
                           ("pixel shader", "ps", "ps_%s.cso")):
        refs = {d[key] for d in game if d.get(key) and d[key] != "0000000000000000"}
        have = set()
        for r in refs:
            cand = os.path.join(CAP, pat % r)
            if os.path.exists(cand) or (key == "il" and r.lower() in layouts):
                have.add(r)
        miss = refs - have
        flag = "OK" if not miss else "INCOMPLETE"
        print("    %-14s referenced=%-3d captured=%-3d  %s" % (kind, len(refs), len(have), flag))
        if miss:
            print("        missing: %s" % ", ".join(sorted(miss)[:6]))
            print("        (created before injection - inject earlier, or re-enter the title)")

    # ── pick the dominant vertex buffer + layout ─────────────────────────────────────────────────
    vbs = Counter(d["vb"] for d in game if d.get("vb"))
    if not vbs:
        print("\nno vertex buffers referenced")
        return 1
    vb, vbn = vbs.most_common(1)[0]
    ils = Counter(d["il"] for d in game if d.get("vb") == vb)
    il, iln = ils.most_common(1)[0]
    print("\n[BUFFER] dominant VB %s used by %d draws; dominant layout %s (%d draws)" % (vb, vbn, il, iln))

    ov, dup, back, span, used, n = gate_disjoint(game, vb)
    print("\n[GATE 1: DISJOINTNESS] %d ranges | partial-overlaps=%d | exact-dupes=%d | "
          "backward-jumps=%d | span=%d used=%d (%.0f%%)"
          % (n, ov, dup, len(back), span, used, (100.0 * used / span) if span else 0))
    if dup and not ov:
        print("    (%d exact-duplicate ranges = the same geometry drawn twice; harmless)" % dup)
    if ov:
        print("    *** FAILED: ranges overlap -> the buffer was discarded mid-frame.")
        print("    *** Earlier draws' vertices are OVERWRITTEN. Do not trust decoded values.")
        return 2
    print("    PASSED: the game appends; the end-of-frame snapshot is valid for every draw.")

    elems = layouts.get(il.lower())
    if not elems:
        print("\n[LAYOUT] no il_%s.json captured -- cannot decode authoritatively." % il)
        print("    Refusing to guess the layout from value ranges.")
        return 3

    stride = next((d["stride"] for d in game if d.get("il") == il and d.get("stride")), 0)
    print("\n[LAYOUT] %s  stride=%d bytes" % (il, stride))
    total = 0
    for e in elems:
        sz = FMT.get(e["format"], (0,))[0]
        total += sz
        print("    +%-3d %-10s%-2d %-16s slot=%d  (%d bytes)" %
              (e["offset"], e["semantic"], e["index"],
               FMT_NAME.get(e["format"], "fmt%d" % e["format"]), e["slot"], sz))
    print("    -> %d bytes described, stride %d%s" %
          (total, stride, "" if total == stride else "   (padding or unmapped tail)"))

    # ── decode actual vertices ───────────────────────────────────────────────────────────────────
    blobs = glob.glob(os.path.join(CAP, "buf_%s_vb_*.bin" % frame))
    blob = next((b for b in blobs if vb.lower() in os.path.basename(b).lower()), None)
    if not blob:
        print("\n[VERTICES] no snapshot buf_%s_vb_%s.bin -- run a capture with buffer dumping on." % (frame, vb))
        return 4
    data = open(blob, "rb").read()
    print("\n[VERTICES] %s (%d bytes)" % (os.path.basename(blob), len(data)))

    quads = [d for d in game if d.get("il") == il and d.get("count") == 4 and d.get("topo") == 5]
    print("    %d four-vertex TRIANGLESTRIP draws with this layout; decoding the first 3:\n" % len(quads))
    for d in quads[:3]:
        base = d["voff"] + d["start"] * stride
        tex = next((t for t in (d.get("tex") or []) if t and "w" in t), None)
        print("  draw #%d  ret=%s  tex=%s" %
              (d["i"], d.get("ret"), ("%dx%d fmt=%d" % (tex["w"], tex["h"], tex["fmt"])) if tex else "none"))
        for v in range(4):
            off = base + v * stride
            if off + stride > len(data):
                print("      vertex %d: past end of snapshot" % v)
                continue
            parts = []
            for e in elems:
                sz, code, cnt, is_norm = FMT.get(e["format"], (0, None, 0, False))
                if not sz:
                    continue
                raw = data[off + e["offset"]: off + e["offset"] + sz]
                if len(raw) < sz:
                    continue
                vals = struct.unpack("<" + code * cnt, raw)
                if is_norm:
                    txt = "(" + ",".join("%.3f" % (x / 255.0) for x in vals) + ")"
                else:
                    txt = "(" + ",".join("%.4g" % x for x in vals) + ")"
                parts.append("%s%d=%s" % (e["semantic"], e["index"], txt))
            print("      v%d: %s" % (v, "  ".join(parts)))
        print("")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not args:
        print(__doc__)
        sys.exit(2)
    sys.exit(decode(args[0], score_only=("--score" in sys.argv)))
