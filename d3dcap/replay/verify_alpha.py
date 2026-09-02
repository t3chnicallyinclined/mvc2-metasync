#!/usr/bin/env python3
"""GATE 0 - hand-execute the captured frame's ALPHA channel in pure Python, no GPU, no WebGPU.

    python verify_alpha.py 4261

WHY ALPHA, AND WHY WITHOUT A GPU.
Every scene draw blends with srcA = ONE, dstA = ZERO (measured: 758 of 760 draws share one blend
state, the other two have blending disabled), so the render target's final alpha at a pixel is simply
the alpha of the LAST fragment that was not discarded there. That makes alpha a pure COVERAGE
question -- it needs no texture colour, no palette RGB, no fog and no blend arithmetic - and it is
settled by three inputs we already have: the vertex positions, the alpha test, and the draw order.

Both pixel-shader families end identically (confirmed from the ps_5_0 disassembly of
ps_00000000642DB9F8 and ps_00000000643D33F8):

    mul r0.w, r0.w, v1.w        a = texture_or_palette.a * colour0.a
    ge  r1.x, cb0[0].x, r0.w    fAlphaRef >= a ?
    discard_nz r1.x             ... then discard
    mov o0.w, r0.w

fAlphaRef is 0.0 for all 759 draws that bind cb0, so the test discards exactly the fragments whose
alpha is zero. The 'opaque' family is the same shader with IgnoreTexA, i.e. texture alpha forced to
1, so its alpha is colour0.a alone.

This separates the MODEL from the PLUMBING. If Python reproduces truth's alpha mask and the WebGPU
replay does not, the bug is in the replayer and the search space has halved. If Python misses the
same pixels, our model of the frame is wrong and the replayer is faithfully wrong.
"""
import glob
import hashlib
import json
import os
import struct
import sys
from collections import Counter

import numpy as np

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")
HERE = os.path.dirname(os.path.abspath(__file__))
CROP = (384, 32, 1280, 960)          # the viewport region inside the 2048x1024 scene RT

FMT_R8 = 61
D3D_TRIANGLELIST, D3D_TRIANGLESTRIP = 4, 5

# D3D11_COMPARISON_FUNC is 1-based: NEVER=1 LESS=2 EQUAL=3 LESS_EQUAL=4 GREATER=5 NOT_EQUAL=6
# GREATER_EQUAL=7 ALWAYS=8. Getting this off by one silently inverts every depth decision.
CMP = {
    1: lambda s, d: np.zeros_like(s, bool),
    2: lambda s, d: s < d,
    3: lambda s, d: s == d,
    4: lambda s, d: s <= d,
    5: lambda s, d: s > d,
    6: lambda s, d: s != d,
    7: lambda s, d: s >= d,
    8: lambda s, d: np.ones_like(s, bool),
}


def sha8(b):
    return hashlib.sha256(b).hexdigest()[:16]


def depth_state(d):
    """(comparison func, writes) from the captured depth-stencil state."""
    ds = d.get("depth") or d.get("ds")
    if not ds or not ds.get("en", 1):
        return None, False
    return ds.get("func", 4), bool(ds.get("write", 1))


def raster(P, alpha, depth, written_by, di, cls, aref, idxplane, palA, texA, t0,
           dfunc, dwrite, RTW, RTH, cull=None):
    """Half-space fill of one triangle, evaluating only the alpha channel."""
    (ax, ay, az, aa, au, av, _), (bx, by, bz, ba, bu, bv, _), (cx, cy, cz, ca, cu, cv, _) = P
    x0 = max(0, int(np.floor(min(ax, bx, cx))))
    x1 = min(RTW - 1, int(np.ceil(max(ax, bx, cx))))
    y0 = max(0, int(np.floor(min(ay, by, cy))))
    y1 = min(RTH - 1, int(np.ceil(max(ay, by, cy))))
    if x1 < x0 or y1 < y0:
        return 0
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return 0
    X, Y = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
    l0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
    l1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
    l2 = 1.0 - l0 - l1
    if cull is not None:
        # D3D and WebGPU both decide winding in framebuffer space with y pointing DOWN, so the sign
        # of the signed area is directly comparable. FrontCounterClockwise=TRUE (ccw:1) makes a
        # NEGATIVE signed area (counter-clockwise with y down) the front face.
        ccw, mode = cull
        front = (den < 0) if ccw else (den > 0)
        if os.environ.get("CULL") == "invert":
            front = not front
        if (mode == 2 and front) or (mode == 3 and not front):
            return 0
    inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
    if not inside.any():
        return 0

    z = l0 * az + l1 * bz + l2 * cz
    a = l0 * aa + l1 * ba + l2 * ca
    if cls in ("indexed", "texalpha"):
        u = l0 * au + l1 * bu + l2 * cu
        v = l0 * av + l1 * bv + l2 * cv
        if cls == "indexed":
            ix = np.clip((u * t0["w"]).astype(np.int32), 0, t0["w"] - 1)
            iy = np.clip((v * t0["h"]).astype(np.int32), 0, t0["h"] - 1)
            index = np.clip(idxplane[iy, ix].astype(np.int32), 0, 255)
            a = a * palA[index]
        else:
            th, tw = texA.shape
            ix = np.clip((u * tw).astype(np.int32), 0, tw - 1)
            iy = np.clip((v * th).astype(np.int32), 0, th - 1)
            a = a * texA[iy, ix]

    keep = inside & (a > aref)                       # ge fAlphaRef, a -> discard_nz
    if os.environ.get("DEPTHCLIP") == "1":
        # WebGPU (without the unclipped-depth feature) discards fragments whose NDC z leaves [0,1].
        # D3D11 with DepthClipEnable does the same, so this must be a no-op -- if it is NOT, our
        # replay is losing geometry that Steam keeps, and that is the whole coverage gap.
        keep = keep & (z >= 0.0) & (z <= 1.0)
    if dfunc is not None:
        keep = keep & CMP[dfunc](z, depth[y0:y1 + 1, x0:x1 + 1])
    if not keep.any():
        return 0
    alpha[y0:y1 + 1, x0:x1 + 1][keep] = a[keep]
    written_by[y0:y1 + 1, x0:x1 + 1][keep] = di
    if dwrite and dfunc is not None:
        depth[y0:y1 + 1, x0:x1 + 1][keep] = z[keep]
    return int(keep.sum())


def main(frame):
    rows = [json.loads(l) for l in open(os.path.join(CAP, f"frame_{frame}.ndjson"), encoding="utf-8")
            if l.strip()]
    all_draws = [r for r in rows if not str(r.get("kind", "")).startswith("Clear") and r.get("rt")]
    rtp = Counter(d["rt"]["p"] for d in all_draws).most_common(1)[0][0]
    draws = [d for d in all_draws if d["rt"]["p"] == rtp]
    rt = draws[0]["rt"]
    RTW, RTH = rt["w"], rt["h"]
    print(f"frame {frame}: {len(draws)} draws into the {RTW}x{RTH} scene RT ({rtp})")

    cleared = {c["rt"]["p"] for c in rows if str(c.get("kind", "")) == "ClearRTV"}
    if rtp not in cleared:
        print("  NOTE: this RT is never cleared in the frame, so Steam's own result starts from the")
        print("        previous frame's pixels. We start from zero; any pixel this frame's draws do")
        print("        not touch is therefore expected to differ.")

    smap = json.load(open(os.path.join(HERE, "shader-map.json")))
    bufs = {os.path.basename(f).split("_")[-1][:-4]: open(f, "rb").read()
            for f in glob.glob(os.path.join(CAP, f"buf_{frame}_*.bin"))}
    cbs = {os.path.basename(f).split("_")[-1][:-4].upper(): open(f, "rb").read()
           for f in glob.glob(os.path.join(CAP, f"cb_{frame}_*.bin"))}

    tex_cache, pal_cache = {}, {}

    def plane(t):
        """R8 tiles come back as raw index values; RGBA textures as an alpha plane in 0..1."""
        if t is None:
            return None
        if t["p"] in tex_cache:
            return tex_cache[t["p"]]
        hit = glob.glob(os.path.join(CAP, f"tex_*_{t['w']}x{t['h']}_f{t['fmt']}_{t['p']}.bin"))
        out = None
        if hit:
            raw = np.frombuffer(open(hit[0], "rb").read(), np.uint8)
            n = t["w"] * t["h"]
            if t["fmt"] == FMT_R8 and raw.size >= n:
                out = raw[:n].reshape(t["h"], t["w"]).astype(np.float32)
            elif raw.size >= n * 4:
                out = raw[: n * 4].reshape(t["h"], t["w"], 4)[:, :, 3].astype(np.float32) / 255.0
        tex_cache[t["p"]] = out
        return out

    def palette(t):
        if t is None:
            return None
        if t["p"] in pal_cache:
            return pal_cache[t["p"]]
        hit = glob.glob(os.path.join(CAP, f"tex_*_{t['w']}x{t['h']}_f{t['fmt']}_{t['p']}.bin"))
        out = None
        if hit:
            raw = np.frombuffer(open(hit[0], "rb").read(), np.uint8)
            if raw.size >= 256 * 4:
                out = raw[: 256 * 4].reshape(256, 4)[:, 3].astype(np.float32) / 255.0
        pal_cache[t["p"]] = out
        return out

    alpha = np.zeros((RTH, RTW), np.float32)
    depth = np.ones((RTH, RTW), np.float32)
    written_by = np.full((RTH, RTW), -1, np.int32)
    stats = Counter()
    per_draw_px, per_draw_cls = {}, {}

    for d in draws:
        vb = bufs.get(d.get("vb", ""))
        vs_p = os.path.join(CAP, f"vs_{d.get('vs', '')}.cso")
        ps_p = os.path.join(CAP, f"ps_{d.get('ps', '')}.cso")
        if vb is None or not os.path.exists(vs_p) or not os.path.exists(ps_p):
            stats["skip: no shader blob or VB"] += 1
            continue
        vsv = smap["vs"].get(sha8(open(vs_p, "rb").read()), {}).get("variant")
        cls = smap["ps"].get(sha8(open(ps_p, "rb").read()), {}).get("variant")
        if vsv is None or cls is None:
            stats["skip: unclassified shader"] += 1
            continue

        W = VP = None
        if vsv == "vs_world":
            h0, h1 = d["vscbHash"][0].upper(), d["vscbHash"][1].upper()
            if h0 not in cbs or h1 not in cbs:
                stats["skip: missing VS constant buffer"] += 1
                continue
            W = np.frombuffer(cbs[h0][:48], "<f4").reshape(3, 4).astype(np.float64)
            VP = np.frombuffer(cbs[h1][:64], "<f4").reshape(4, 4).astype(np.float64)

        aref = 0.0
        h = d["pscbHash"][0].upper()
        if h in cbs and len(cbs[h]) >= 4:
            aref = struct.unpack_from("<f", cbs[h], 0)[0]

        only = os.environ.get("ONLY")
        if only and cls != only:
            stats[f"filtered out: {cls}"] += 1
            continue

        tl = d.get("tex") or []
        t0 = tl[0] if tl else None
        t1 = tl[1] if len(tl) > 1 else None
        idxplane = plane(t0) if cls == "indexed" else None
        palA = palette(t1) if cls == "indexed" else None
        texA = plane(t0) if cls == "texalpha" else None
        if cls == "indexed" and (idxplane is None or palA is None):
            stats["skip: indexed draw with no dumped tile/palette"] += 1
            continue
        if cls == "texalpha" and texA is None:
            stats["skip: texalpha draw with no dumped texture"] += 1
            continue

        if d["kind"] == "DrawIndexed":
            ib = bufs.get(d.get("ib", ""))
            if ib is None:
                stats["skip: no index buffer"] += 1
                continue
            w = 2 if d["ifmt"] == 57 else 4
            o = d["ioff"] + d["start"] * w
            ind = [int.from_bytes(ib[o + i * w: o + (i + 1) * w], "little") + d["base"]
                   for i in range(d["count"])]
        else:
            ind = [d["start"] + i for i in range(d["count"])]

        if d["topo"] == D3D_TRIANGLESTRIP:
            tris = [((ind[i + 1], ind[i], ind[i + 2]) if i & 1 else (ind[i], ind[i + 1], ind[i + 2]))
                    for i in range(len(ind) - 2)]
        elif d["topo"] == D3D_TRIANGLELIST:
            tris = [(ind[i], ind[i + 1], ind[i + 2]) for i in range(0, len(ind) - 2, 3)]
        else:
            stats[f"skip: topology {d['topo']}"] += 1
            continue

        st, voff = d["stride"], d["voff"]
        VX, VY, VW, VH = d["vp"][:4]
        mnd, mxd = (d["vp"] + [0.0, 1.0])[4:6]

        def vertex(vi):
            o = voff + vi * st
            px, py, pz = struct.unpack_from("<3f", vb, o)
            c0a = vb[o + 24 + 3] / 255.0                  # TANGENT.w = colour0.a (format 28 = RGBA)
            u, v = struct.unpack_from("<2f", vb, o + 32)
            if vsv == "vs_world":
                p1 = np.array([px, py, pz, 1.0])
                wp = W @ p1                               # dp4 against cb0[0..2]
                clip = wp[0] * VP[0] + wp[1] * VP[1] + wp[2] * VP[2] + VP[3]
            else:
                clip = np.array([px, py, pz, 1.0])
            if clip[3] == 0:
                return None
            n = clip[:3] / clip[3]
            return (VX + (n[0] * .5 + .5) * VW, VY + (.5 - n[1] * .5) * VH,
                    mnd + n[2] * (mxd - mnd), c0a, u, v, clip[3])

        rs = d.get("raster") or {}
        cull = None
        if os.environ.get("CULL") in ("1", "invert") and rs.get("cull", 1) != 1:
            cull = (bool(rs.get("ccw", 0)), rs["cull"])
        dfunc, dwrite = depth_state(d)
        wrote = 0
        for ta, tb, tc in tris:
            P = [vertex(ta), vertex(tb), vertex(tc)]
            if any(p is None for p in P):
                continue
            wrote += raster(P, alpha, depth, written_by, d["i"], cls, aref, idxplane, palA, texA,
                            t0, dfunc, dwrite, RTW, RTH, cull)
        per_draw_px[d["i"]] = wrote
        per_draw_cls[d["i"]] = cls
        stats[f"drawn: {cls}"] += 1

    for k, v in sorted(stats.items()):
        print(f"  {v:4d}  {k}")

    compare(frame, alpha, written_by, per_draw_px, per_draw_cls)


def compare(frame, alpha, written_by, per_draw_px, per_draw_cls):
    bmp = open(os.path.join(CAP, f"scene_{frame}_2048x1024_f87.bmp"), "rb").read()
    off = struct.unpack_from("<I", bmp, 10)[0]
    W, H = struct.unpack_from("<i", bmp, 18)[0], struct.unpack_from("<i", bmp, 22)[0]
    img = np.frombuffer(bmp, np.uint8, W * abs(H) * 4, off).reshape(abs(H), W, 4)
    if H > 0:
        img = img[::-1]
    cx, cy, cw, ch = CROP
    truth = img[cy:cy + ch, cx:cx + cw, 3] > 0
    ours = alpha[cy:cy + ch, cx:cx + cw] > 0
    n = cw * ch
    miss = truth & ~ours
    spur = ours & ~truth
    print(f"\nALPHA MASK over the {cw}x{ch} crop ({n:,} px)")
    print(f"  truth covered : {truth.sum():,} ({100 * truth.mean():.3f}%)")
    print(f"  we covered    : {ours.sum():,} ({100 * ours.mean():.3f}%)")
    print(f"  MISSING       : {miss.sum():,} ({100 * miss.mean():.3f}%)")
    print(f"  spurious      : {spur.sum():,} ({100 * spur.mean():.3f}%)")
    if miss.any():
        ys, xs = np.nonzero(miss)
        print(f"  missing bbox  : x={xs.min()}..{xs.max()} y={ys.min()}..{ys.max()}")

    wb = written_by[cy:cy + ch, cx:cx + cw]
    top = Counter(wb[ours].tolist()).most_common(8)
    print("\n  final writer of our covered pixels (draw index -> px):")
    for di, c in top:
        print(f"    i={di:4d} {per_draw_cls.get(di, '?'):9s} {c:,}")
    empty = [i for i, v in per_draw_px.items() if v == 0]
    print(f"\n  draws that wrote ZERO pixels: {len(empty)} of {len(per_draw_px)}"
          f"{' -> ' + str(empty[:20]) if empty else ''}")
    print("\n  MEASUREMENT, NOT A MECHANISM. This shows our reading of the capture reproduces the")
    print("  alpha channel; it establishes nothing about MvC2 itself.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "4261")
