#!/usr/bin/env python3
"""Pack one captured Steam MvC2 frame into a single self-contained .pack for the replayer.

    python pack_replay.py <frame_number> [-o out.pack]

Why an offline packer instead of loading the capture directly in the browser:
  * fetching a 1252-line ndjson plus ~560 loose binaries and doing pointer-keyed dedupe in JS is slow
    and fragile;
  * TRIANGLESTRIP must be converted to a triangle list BEFORE any draw merging is possible -- see
    below, this is a correctness issue, not an optimisation;
  * runtime ID3D11* pointers are fine as keys WITHIN one captured frame and worthless across
    launches, so everything checked in must be keyed by CONTENT HASH instead;
  * coverage can be asserted once, here, instead of showing up later as a subtly wrong pixel diff.

⚠ THE STRIP TRAP (mvc2-sprite-render-expert, 2026-09-01). 1183 of 1245 draws are
D3D11_PRIMITIVE_TOPOLOGY_TRIANGLESTRIP. Adjacent character quads share an identical pipeline state
AND are contiguous in the vertex buffer, so a naive "merge adjacent draws with equal state" fuses two
strips into one and manufactures two bridging triangles between them. It fails silently and looks
plausible. Converting to triangle lists here makes merging safe, halves the pipeline space, and keeps
each draw a pure slice of the index buffer.
"""
import argparse
import glob
import hashlib
import json
import os
import struct
import sys
from collections import Counter, OrderedDict

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")

D3D_TRIANGLELIST = 4
D3D_TRIANGLESTRIP = 5


def sha8(b):
    return hashlib.sha256(b).hexdigest()[:16]


def strip_to_list(first, count):
    """Triangle-strip -> triangle-list indices, preserving winding.

    A strip of N vertices makes N-2 triangles; odd-numbered triangles have reversed winding, which a
    triangle list must express explicitly or every other face flips (and with per-draw culling, half
    the geometry disappears). Degenerate triangles (a repeated index) are dropped.
    """
    out = []
    for i in range(count - 2):
        a, b, c = first + i, first + i + 1, first + i + 2
        if i & 1:
            a, b = b, a
        # NOTE: no degenerate check here. a, b, c are always three DISTINCT consecutive indices, so
        # the obvious `if a == b or ...: continue` can never fire and is dead code — it was here and
        # did nothing. Real degenerate stitches would need equal VERTEX DATA, not equal indices, and
        # they rasterise to zero area anyway.
        out.extend((a, b, c))
    return out


def list_indices(first, count):
    return list(range(first, first + count - (count % 3)))


def load_draws(frame):
    path = os.path.join(CAP, "frame_%s.ndjson" % frame)
    if not os.path.exists(path):
        sys.exit("no capture: %s" % path)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    clears = [r for r in rows if r.get("kind", "").startswith("Clear")]
    draws = [r for r in rows if not r.get("kind", "").startswith("Clear")]
    foreign = [d for d in draws if d.get("retmod", "game") != "game"]
    draws = [d for d in draws if d.get("retmod", "game") == "game"]
    return draws, clears, foreign


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("-o", "--out")
    ap.add_argument("--allow-missing", action="store_true",
                    help="pack anyway when textures are missing (produces a KNOWN-INCOMPLETE pack)")
    a = ap.parse_args()

    draws, clears, foreign = load_draws(a.frame)
    print("frame %s: %d game draws, %d clears, %d foreign (overlay) draws dropped"
          % (a.frame, len(draws), len(clears), len(foreign)))

    # ── scene pass: the RT with the most draws; everything else is the post chain ────────────────
    rt_counts = Counter(d["rt"]["p"] for d in draws if d.get("rt"))
    if not rt_counts:
        sys.exit("no render targets recorded")
    scene_rt, scene_n = rt_counts.most_common(1)[0]
    scene = [d for d in draws if d.get("rt") and d["rt"]["p"] == scene_rt]
    post = [d for d in draws if not (d.get("rt") and d["rt"]["p"] == scene_rt)]
    rt0 = next(d["rt"] for d in scene)
    print("scene RT %s %dx%d fmt=%d -- %d draws (%d post-chain draws dropped)"
          % (scene_rt, rt0["w"], rt0["h"], rt0["fmt"], len(scene), len(post)))

    # ── vertex buffer ────────────────────────────────────────────────────────────────────────────
    vb_ptr = Counter(d["vb"] for d in scene if d.get("vb")).most_common(1)[0][0]
    vb_files = glob.glob(os.path.join(CAP, "buf_%s_vb_*%s*.bin" % (a.frame, vb_ptr)))
    if not vb_files:
        sys.exit("no vertex-buffer snapshot for %s (run collect.ps1 so a dump budget lands on this frame)"
                 % vb_ptr)
    vb = open(vb_files[0], "rb").read()
    print("vertex buffer %s: %d bytes" % (vb_ptr, len(vb)))

    # ── textures: dedupe by pointer, resolve to a dump, ASSERT COVERAGE ──────────────────────────
    # Frames of this capture that came BEFORE this one, newest first. A texture written once for the
    # whole burst lives under the frame number that first sampled it.
    earlier_frames = sorted(
        (int(os.path.basename(f)[6:-7]) for f in glob.glob(os.path.join(CAP, "frame_*.ndjson"))
         if os.path.getsize(f) and int(os.path.basename(f)[6:-7]) <= int(a.frame)),
        reverse=True)

    tex_index = OrderedDict()
    missing = Counter()
    for d in scene:
        for t in (d.get("tex") or []):
            if not t or "w" not in t:
                continue
            p = t["p"]
            if p in tex_index:
                continue
            # ⚠⚠ MATCH THIS FRAME'S DUMP, NOT `tex_*`. A capture run keeps every frame it sampled,
            # and a texture object that lives across frames has one dump per frame. The wildcard
            # matched all of them and this took hits[0] -- the alphabetically FIRST frame number, not
            # this one. Measured on frame 4360: 21 of 223 textures were being loaded from frames 2965
            # and 3893. On the earlier frame it caught the character tiles, whose contents change
            # every frame, and drew the characters as scattered shards of another animation frame
            # over a perfectly correct stage. It read like a shading bug for two rounds.
            # "pointer#generation" is the identity on captures from 2026-09-01 onward; older ones
            # have no "#" and no `_v` suffix, so both forms are accepted.
            # ⚠ NAME THE FILE, DO NOT GLOB FOR IT. With the frame number pinned the filename is fully
            # determined, and a burst leaves ~55,000 files in the capture directory -- one glob per
            # texture per frame is a full directory scan each time, which turned packing a 300-frame
            # sequence from seconds into hours.
            # A texture generation may legitimately have been written on an EARLIER frame of the same
            # burst: the version table lives for the whole session, so a texture is written once per
            # content generation, not once per frame that samples it.
            if "#" in p:
                ptr, ver = p.split("#", 1)
                name = "tex_%%s_%dx%d_f%d_%s_v%s.bin" % (t["w"], t["h"], t["fmt"], ptr, ver)
            else:
                name = "tex_%%s_%dx%d_f%d_%s.bin" % (t["w"], t["h"], t["fmt"], p)
            hits = [os.path.join(CAP, name % a.frame)] if os.path.exists(
                os.path.join(CAP, name % a.frame)) else []
            if not hits:
                hits = [x for x in (os.path.join(CAP, name % f) for f in earlier_frames)
                        if os.path.exists(x)][-1:]
            if not hits:
                missing[t["fmt"]] += 1
                continue
            tex_index[p] = {"w": t["w"], "h": t["h"], "fmt": t["fmt"], "file": hits[0]}
    bound = {t["p"] for d in scene for t in (d.get("tex") or []) if t and "w" in t}
    objs = {str(x).split("#", 1)[0] for x in bound}
    print("textures: %d/%d bound texture CONTENTS have pixel dumps (%d distinct objects, "
          "%d rewritten mid-frame)"
          % (len(tex_index), len(bound), len(objs), len(bound) - len(objs)))
    if missing:
        print("  MISSING by DXGI format: %s" % dict(missing))
        if 61 in missing:
            print("  ⚠ fmt 61 = R8_UNORM = the CHARACTER index tiles. Recapture with the current")
            print("    build: an older d3dcap only dumped 4-byte RGBA and skipped every one.")
        if not a.allow_missing:
            sys.exit("refusing to pack an incomplete frame (use --allow-missing to override)")

    # ── shaders + layouts: keyed by CONTENT HASH, never by runtime pointer ───────────────────────
    def blob_map(pattern, key):
        out = {}
        for d in scene:
            ptr = d.get(key)
            if not ptr or ptr in out:
                continue
            f = os.path.join(CAP, pattern % ptr)
            if os.path.exists(f):
                data = open(f, "rb").read()
                out[ptr] = sha8(data)
        return out

    vs_hash = blob_map("vs_%s.cso", "vs")
    ps_hash = blob_map("ps_%s.cso", "ps")
    il_hash, il_elements = {}, {}
    for d in scene:
        ptr = d.get("il")
        if not ptr or ptr in il_hash:
            continue
        f = os.path.join(CAP, "il_%s.json" % ptr)
        if os.path.exists(f):
            il_hash[ptr] = sha8(open(f, "rb").read())
            # The ELEMENTS have to travel with the pack, not just a hash of them: the replayer builds
            # its GPUVertexBufferLayout from these. Hardcoding one layout works only while every draw
            # shares it, and this frame already has a 28-byte position+normal layout that does not.
            il_elements[il_hash[ptr]] = json.load(open(f))["elements"]
    print("shaders: %d VS, %d PS, %d input layouts (content-hashed)"
          % (len(vs_hash), len(ps_hash), len(il_hash)))

    # Shader VARIANTS come from classify_shaders.py, which reads them out of the disassembly.
    # ⚠ Never infer the variant from what a draw binds. That heuristic ("something in slot 1 means
    # this is a character") selected 214 draws spanning five pixel shaders and three vertex shaders,
    # including the HUD bank and stage pages, and forced them all through the indexed path with a
    # pass-through vertex shader -- putting transformed geometry in the wrong place.
    smap_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shader-map.json")
    smap = json.load(open(smap_path)) if os.path.exists(smap_path) else {"vs": {}, "ps": {}}
    if not smap["ps"]:
        print("  ⚠ no shader-map.json — run: python classify_shaders.py %s" % a.frame)
    unmapped = Counter()

    # ── constant buffers: already content-hashed at capture time ─────────────────────────────────
    cb_files = {}
    for f in glob.glob(os.path.join(CAP, "cb_%s_*.bin" % a.frame)):
        cb_files[os.path.basename(f).rsplit("_", 1)[1][:-4].upper()] = f
    print("constant buffers: %d distinct payloads" % len(cb_files))

    # ── build the draw list ──────────────────────────────────────────────────────────────────────
    indices = []
    out_draws = []
    topo_hist = Counter()
    for d in scene:
        stride = d.get("stride") or 0
        if not stride:
            continue
        # ⚠⚠ THE VERTEX-OFFSET TRAP (measured 2026-09-01, cost a full round of false leads).
        # This used to be  first = (voff + start * stride) // stride,  folding the vertex buffer's
        # BYTE offset into a vertex INDEX. That is only valid when voff is a whole number of
        # vertices, and in frame 4261 it is not: voff takes the values 65536, 65648, 65808, 98304,
        # 131072 and 196608 against strides of 40 and 28, so 382 of 760 draws -- 50.3% -- were
        # misaligned by 8, 16, 24 or 32 bytes. Every one of them fetched POSITION out of the middle
        # of the previous vertex. It failed exactly the way a subtle bug does: half the geometry
        # still landed somewhere plausible, so the frame looked roughly right and the diff read as a
        # shading problem for two rounds.
        # The fix is to keep voff as a BYTE offset and hand it to setVertexBuffer, which takes one.
        if d["voff"] % 4:
            sys.exit("draw %d has vertex offset %d, which WebGPU cannot bind (must be a multiple "
                     "of 4)" % (d["i"], d["voff"]))
        first = d["start"]
        topo = d.get("topo")
        topo_hist[topo] += 1
        if topo == D3D_TRIANGLESTRIP:
            idx = strip_to_list(first, d["count"])
        elif topo == D3D_TRIANGLELIST:
            idx = list_indices(first, d["count"])
        else:
            continue                       # points/lines: not part of the sprite pass
        if not idx:
            continue
        out_draws.append({
            "i": d["i"], "firstIndex": len(indices), "indexCount": len(idx),
            # voff is a BYTE offset into the vertex buffer and stays one; indexCount/firstIndex index
            # the pack's own index buffer, and the index VALUES are relative to voff.
            "stride": stride, "voff": d["voff"],
            "vs": vs_hash.get(d.get("vs")), "ps": ps_hash.get(d.get("ps")),
            "il": il_hash.get(d.get("il")),
            "vsVariant": smap["vs"].get(vs_hash.get(d.get("vs")), {}).get("variant"),
            "psVariant": smap["ps"].get(ps_hash.get(d.get("ps")), {}).get("variant"),
            # A shader with no fog constant buffer must not have a fog term applied. Rather than
            # multiply the entry points by a fog flag, the replayer writes fogDensity = 0 for these,
            # which makes the shared fog tail a BIT-EXACT no-op (sqrt(0)=0 -> weight 1 -> +0*colour).
            "psFog": smap["ps"].get(ps_hash.get(d.get("ps")), {}).get("fog", True),
            "tex": [(t["p"] if t and "w" in t and t["p"] in tex_index else None)
                    for t in (d.get("tex") or [])][:2],
            "samp": (d.get("samp") or [])[:2],
            "blend": d.get("blend"), "bfactor": d.get("bfactor"), "smask": d.get("smask"),
            "depth": d.get("depth"), "raster": d.get("raster"),
            "vp": d.get("vp"), "scissor": d.get("scissor"),
            "vscbHash": (d.get("vscbHash") or [])[:4],
            "pscbHash": (d.get("pscbHash") or [])[:4],
        })
        indices.extend(idx)

    for d in out_draws:
        if not d.get("vsVariant") or not d.get("psVariant"):
            unmapped[(d.get("vsVariant"), d.get("psVariant"))] += 1
    if unmapped:
        print("  ⚠ %d draws have no shader variant: %s"
              % (sum(unmapped.values()), dict(unmapped)))
    print("variants: %s" % dict(Counter((d.get("vsVariant"), d.get("psVariant")) for d in out_draws)))

    voffs = Counter((d["voff"], d["stride"]) for d in out_draws)
    ragged = sum(n for (v, st), n in voffs.items() if v % st)
    print("vertex offsets: %d distinct, %d of %d draws start mid-vertex (%d%%) -- these are exactly "
          "the draws the old byte-offset-as-index packing destroyed"
          % (len(voffs), ragged, len(out_draws), round(100.0 * ragged / max(1, len(out_draws)))))

    print("topology in: %s -> all triangle lists out, %d indices, %d draws"
          % ({("STRIP" if k == 5 else "LIST" if k == 4 else k): v for k, v in topo_hist.items()},
             len(indices), len(out_draws)))

    # ── state-space report: this is what the pipeline cache will hold ────────────────────────────
    def tup(d, k, fields):
        v = d.get(k)
        return None if not v else tuple(v.get(f) for f in fields)
    print("state space: %d blend, %d depth, %d raster, %d sampler"
          % (len({json.dumps(d["blend"], sort_keys=True) for d in out_draws}),
             len({json.dumps(d["depth"], sort_keys=True) for d in out_draws}),
             len({json.dumps(d["raster"], sort_keys=True) for d in out_draws}),
             len({json.dumps(d["samp"], sort_keys=True) for d in out_draws})))

    # ⚠ WebGPU has NO border address mode. Fail loudly rather than silently substituting clamp.
    for d in out_draws:
        for s in (d.get("samp") or []):
            if s and s.get("u") == 4:
                sys.exit("draw %d uses D3D11_TEXTURE_ADDRESS_BORDER, which WebGPU cannot express"
                         % d["i"])

    # ── emit: one file = JSON manifest + concatenated payloads ───────────────────────────────────
    payloads = []
    def add(data):
        off = sum(len(p) for p in payloads)
        payloads.append(data)
        return {"off": off, "len": len(data)}

    # The ground-truth image is REFERENCED, not embedded: it is 8 MB and would double the pack, and
    # the diff tool wants it as a separate input anyway. This is the PRE-BLOOM scene RT -- diffing
    # against the backbuffer instead would only prove that the bloom chain exists.
    scene_hits = glob.glob(os.path.join(CAP, "scene_%s_*.bmp" % a.frame))
    if scene_hits:
        # Copy it beside the pack so the browser can fetch both from one directory. It is 8 MB and
        # ROM-derived, so *.bmp is gitignored here -- this is a working copy, not an artifact.
        import shutil
        dst = os.path.join(os.path.dirname(os.path.abspath(a.out or __file__)),
                           os.path.basename(scene_hits[0]))
        if os.path.abspath(scene_hits[0]) != os.path.abspath(dst):
            shutil.copyfile(scene_hits[0], dst)
        print("ground truth: %s (copied beside the pack)" % os.path.basename(scene_hits[0]))
    else:
        print("⚠ NO scene RT dump for this frame -- there is nothing to diff against")

    manifest = {
        "frame": a.frame,
        "sceneRTFile": os.path.basename(scene_hits[0]) if scene_hits else None,
        "viewport": next((d.get("vp") for d in out_draws if d.get("vp")), None),
        "sceneRT": {"w": rt0["w"], "h": rt0["h"], "fmt": rt0["fmt"]},
        "clears": clears,
        "vb": add(vb),
        "ib": add(struct.pack("<%dI" % len(indices), *indices)),
        "inputLayouts": il_elements,
        "textures": {},
        "constantBuffers": {},
        "draws": out_draws,
        "note": "indices are triangle lists; strips were converted at pack time",
    }
    for p, t in tex_index.items():
        manifest["textures"][p] = {"w": t["w"], "h": t["h"], "fmt": t["fmt"],
                                   **add(open(t["file"], "rb").read())}
    for h, f in cb_files.items():
        manifest["constantBuffers"][h] = add(open(f, "rb").read())

    out = a.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "frame_%s.pack" % a.frame)
    head = json.dumps(manifest).encode("utf-8")
    with open(out, "wb") as f:
        f.write(b"RRPK")
        f.write(struct.pack("<I", len(head)))
        f.write(head)
        for p in payloads:
            f.write(p)
    total = 8 + len(head) + sum(len(p) for p in payloads)
    print("\nwrote %s  (%.1f MB)" % (out, total / 1048576.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
