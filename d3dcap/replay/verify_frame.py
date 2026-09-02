#!/usr/bin/env python3
"""GATE 0 (colour) - hand-execute a captured frame's FULL colour on the CPU, from the .pack.

    python verify_frame.py 4261 [--png ours.png]

This is the sibling of verify_alpha.py and it exists for the same reason: to separate OUR MODEL of
the frame from the WebGPU PLUMBING that renders it. It reads the same .pack the browser reads, runs
the same fragment maths the WGSL runs, and composites with the same captured blend states -- but on
the CPU, in NumPy, with no GPU anywhere.

  Python matches truth, browser does not  =>  the bug is in the replayer. Halve the search space.
  Neither matches                         =>  our model is wrong and the replayer is faithfully wrong.

That is exactly how the vertex-offset bug was found: verify_alpha.py reproduced Steam's coverage
byte-for-byte while the browser was missing 25% of it, which proved the fault had to be in the pack.

WHAT IS MODELLED, AND WHY EACH PIECE IS THERE
  * perspective-correct interpolation. DXBC's `dcl_input_ps linear` means perspective-correct (the
    non-perspective variant is spelled `linear_noperspective`). Screen-space-affine interpolation is
    visibly wrong on the stage, where w varies across a triangle.
  * point and bilinear sampling, chosen per draw from the captured D3D11_SAMPLER_DESC. Character
    draws are POINT on BOTH slots -- linear-filtering an index tile blends palette INDICES into
    arbitrary colours.
  * the alpha test `ge fAlphaRef, a -> discard_nz`, from the pixel-shader disassembly.
  * the depth test and depth writes, from the captured depth-stencil state.
  * per-draw blending, from the captured blend state.

WHAT IS DELIBERATELY NOT MODELLED
  * the scene RT's incoming contents. Steam never clears this target, so it starts each frame from
    the previous frame's pixels; we start from black. Harmless while the frame's own draws cover
    100% of the crop with alpha 1 (measured), and reported if that ever stops being true.
  * multisampling. `ms:1` appears in the raster state but the scene RT is single-sampled.

A MATCH HERE IS A MEASUREMENT, NOT A MECHANISM. It shows our reading of the capture reproduces the
pixels. It establishes nothing about MvC2 itself.
"""
import argparse
import json
import os
import struct
import sys
from collections import Counter

import numpy as np

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")
HERE = os.path.dirname(os.path.abspath(__file__))
CROP = (384, 32, 1280, 960)

# D3D11_COMPARISON_FUNC, 1-based.
CMP = {
    1: lambda s, d: np.zeros_like(s, bool), 2: lambda s, d: s < d,
    3: lambda s, d: s == d, 4: lambda s, d: s <= d,
    5: lambda s, d: s > d, 6: lambda s, d: s != d,
    7: lambda s, d: s >= d, 8: lambda s, d: np.ones_like(s, bool),
}

# D3D11_BLEND. Only the values this capture uses are mapped; anything else must fail loudly.
def blend_factor(code, srcC, srcA, dstC, dstA):
    if code == 1:                                   # ZERO
        return 0.0
    if code == 2:                                   # ONE
        return 1.0
    if code == 5:                                   # SRC_ALPHA
        return srcA
    if code == 6:                                   # INV_SRC_ALPHA
        return 1.0 - srcA
    if code == 7:                                   # DEST_ALPHA
        return dstA
    if code == 8:                                   # INV_DEST_ALPHA
        return 1.0 - dstA
    if code == 3:                                   # SRC_COLOR
        return srcC
    if code == 4:                                   # INV_SRC_COLOR
        return 1.0 - srcC
    if code == 9:                                   # DEST_COLOR
        return dstC
    if code == 10:                                  # INV_DEST_COLOR
        return 1.0 - dstC
    raise SystemExit(f"unmapped D3D11_BLEND {code}")


def load_pack(path):
    b = open(path, "rb").read()
    assert b[:4] == b"RRPK", "not a .pack"
    n = struct.unpack_from("<I", b, 4)[0]
    head = json.loads(b[8:8 + n].decode("utf-8"))
    base = 8 + n
    return head, (lambda r: b[base + r["off"]: base + r["off"] + r["len"]])


def decode_texture(rec, payload):
    """-> (h, w, 4) float32 in 0..1. Index tiles come back with the RAW index in .r * 255."""
    w, h, fmt = rec["w"], rec["h"], rec["fmt"]
    raw = np.frombuffer(payload, np.uint8)
    if fmt == 28:                                   # R8G8B8A8_UNORM
        return raw[: w * h * 4].reshape(h, w, 4).astype(np.float32) / 255.0
    if fmt == 61:                                   # R8_UNORM: a palette index, normalised to 0..1
        out = np.zeros((h, w, 4), np.float32)
        out[:, :, 0] = raw[: w * h].reshape(h, w).astype(np.float32) / 255.0
        out[:, :, 3] = 1.0
        return out
    raise SystemExit(f"unmapped texture format {fmt}")


def wrap(i, n, mode):
    if mode == 1:                                   # WRAP
        return np.mod(i, n)
    return np.clip(i, 0, n - 1)                     # CLAMP (mirror never appears in the scene)


def sample(tex, u, v, samp):
    """textureSample(), matching the captured D3D11_SAMPLER_DESC."""
    h, w = tex.shape[:2]
    filt = (samp or {}).get("filter", 0)
    au = (samp or {}).get("u", 3)
    av = (samp or {}).get("v", 3)
    if not (filt & 0x04):                           # magnification POINT
        ix = wrap(np.floor(u * w).astype(np.int64), w, au)
        iy = wrap(np.floor(v * h).astype(np.int64), h, av)
        return tex[iy, ix]
    x = u * w - 0.5
    y = v * h - 0.5
    x0 = np.floor(x); y0 = np.floor(y)
    fx = (x - x0)[..., None]; fy = (y - y0)[..., None]
    x0i = wrap(x0.astype(np.int64), w, au); x1i = wrap(x0.astype(np.int64) + 1, w, au)
    y0i = wrap(y0.astype(np.int64), h, av); y1i = wrap(y0.astype(np.int64) + 1, h, av)
    return ((tex[y0i, x0i] * (1 - fx) + tex[y0i, x1i] * fx) * (1 - fy)
            + (tex[y1i, x0i] * (1 - fx) + tex[y1i, x1i] * fx) * fy)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame")
    ap.add_argument("--png", default=None, help="write our composited result here for eyeballing")
    ap.add_argument("--only", default=None, choices=["opaque", "texalpha", "indexed", "character"],
                    help="render one class only -- for LOOKING; the diff it prints is not valid")
    a = ap.parse_args()

    head, slice_ = load_pack(os.path.join(HERE, f"frame_{a.frame}.pack"))
    RTW, RTH = head["sceneRT"]["w"], head["sceneRT"]["h"]
    draws = head["draws"]
    print(f"frame {a.frame}: {len(draws)} draws, {len(head['textures'])} textures, "
          f"{RTW}x{RTH} scene RT")

    vb = slice_(head["vb"])
    ib = np.frombuffer(slice_(head["ib"]), "<u4")
    cbs = {k.upper(): slice_(v) for k, v in head["constantBuffers"].items()}
    texcache = {}

    def texture(ptr):
        if ptr not in texcache:
            rec = head["textures"][ptr]
            texcache[ptr] = decode_texture(rec, slice_(rec))
        return texcache[ptr]

    color = np.zeros((RTH, RTW, 4), np.float64)
    depth = np.ones((RTH, RTW), np.float64)
    # Who painted each pixel LAST. With the composite matching to 0.01% of the browser, the useful
    # question is no longer "how wrong is the frame" but "which draw owns the wrong pixels" -- and
    # under blending the last writer is the one to interrogate first.
    owner = np.full((RTH, RTW), -1, np.int32)
    stats = Counter()

    for d in draws:
        cls = d.get("psVariant")
        vsv = d.get("vsVariant")
        if not cls or not vsv:
            stats["skipped: unclassified shader"] += 1
            continue
        if a.only and not (cls == a.only or (a.only == "character" and cls == "indexed")):
            stats["filtered out"] += 1
            continue
        if d["stride"] < 40:
            # the 28-byte POSITION+NORMAL layout carries no colours and no UVs; the replayer skips
            # these for the same reason -- rendering them would mean inventing both.
            stats["skipped: layout cannot feed the shader"] += 1
            continue

        # ── uniforms ─────────────────────────────────────────────────────────────────────────────
        def cb(hash_, off, count, default=None):
            src = cbs.get(str(hash_ or "").upper())
            if src is None or len(src) < off + count * 4:
                return None if default is None else np.array(default, np.float64)
            return np.frombuffer(src, "<f4", count, off).astype(np.float64)

        W = VP = None
        if vsv == "vs_world":
            W = cb(d["vscbHash"][0], 0, 12)
            VP = cb(d["vscbHash"][1], 0, 16)
            if W is None or VP is None:
                stats["skipped: missing world/view-projection"] += 1
                continue
            W = W.reshape(3, 4); VP = VP.reshape(4, 4)
        cameraPos = cb(d["vscbHash"][1] if vsv == "vs_world" else None, 64, 3, [0, 0, 0])
        fogColor = cb(d["pscbHash"][2], 0, 4, [0, 0, 0, 0])
        fogSR = cb(d["pscbHash"][2], 24, 2, [0, 0])
        if d.get("psFog") is False:
            fogColor = fogColor.copy(); fogColor[3] = 0.0
        aref = float(cb(d["pscbHash"][0], 0, 1, [0.0])[0])

        # ── vertices ─────────────────────────────────────────────────────────────────────────────
        idx = ib[d["firstIndex"]: d["firstIndex"] + d["indexCount"]]
        st, voff = d["stride"], d["voff"]
        VX, VY, VW, VH = d["vp"][:4]
        mnd, mxd = (list(d["vp"]) + [0.0, 1.0])[4:6]

        cache = {}

        def vertex(vi):
            if vi in cache:
                return cache[vi]
            o = voff + int(vi) * st
            px, py, pz = struct.unpack_from("<3f", vb, o)
            c0 = np.frombuffer(vb, np.uint8, 4, o + 24).astype(np.float64) / 255.0
            c1 = np.frombuffer(vb, np.uint8, 4, o + 28).astype(np.float64) / 255.0
            u, v = struct.unpack_from("<2f", vb, o + 32)
            if vsv == "vs_world":
                p1 = np.array([px, py, pz, 1.0])
                wp = W @ p1
                clip = wp[0] * VP[0] + wp[1] * VP[1] + wp[2] * VP[2] + VP[3]
            else:
                wp = np.array([px, py, pz])
                clip = np.array([px, py, pz, 1.0])
            if clip[3] == 0:
                return None
            n = clip[:3] / clip[3]
            out = (VX + (n[0] * .5 + .5) * VW, VY + (.5 - n[1] * .5) * VH,
                   mnd + n[2] * (mxd - mnd), 1.0 / clip[3], c0, c1,
                   np.array([u, v], np.float64), wp)
            cache[vi] = out
            return out

        dstate = d.get("depth") or {}
        dfunc = CMP[dstate["func"]] if dstate.get("en", 1) else None
        dwrite = bool(dstate.get("write", 1)) and dfunc is not None
        blend = d.get("blend") or {}
        t0 = texture(d["tex"][0]) if d["tex"] and d["tex"][0] else None
        t1 = texture(d["tex"][1]) if len(d["tex"]) > 1 and d["tex"][1] else None
        s0 = (d.get("samp") or [None])[0]
        s1 = (d.get("samp") or [None, None])[1] if len(d.get("samp") or []) > 1 else None

        for k in range(0, len(idx) - 2, 3):
            P = [vertex(idx[k]), vertex(idx[k + 1]), vertex(idx[k + 2])]
            if any(p is None for p in P):
                continue
            shade(P, color, depth, cls, aref, t0, t1, s0, s1, blend, dfunc, dwrite,
                  cameraPos, fogColor, fogSR, RTW, RTH, owner, d["i"])
        stats[f"drawn: {vsv}+{cls}"] += 1

    for k, v in sorted(stats.items()):
        print(f"  {v:4d}  {k}")
    compare(a.frame, color, head, a.png, a.only, owner)


def shade(P, color, depth, cls, aref, t0, t1, s0, s1, blend, dfunc, dwrite,
          cameraPos, fogColor, fogSR, RTW, RTH, owner=None, di=-1):
    (ax, ay, az, aiw, ac0, ac1, auv, awp) = P[0]
    (bx, by, bz, biw, bc0, bc1, buv, bwp) = P[1]
    (cx, cy, cz, ciw, cc0, cc1, cuv, cwp) = P[2]
    x0 = max(0, int(np.floor(min(ax, bx, cx)))); x1 = min(RTW - 1, int(np.ceil(max(ax, bx, cx))))
    y0 = max(0, int(np.floor(min(ay, by, cy)))); y1 = min(RTH - 1, int(np.ceil(max(ay, by, cy))))
    if x1 < x0 or y1 < y0:
        return
    den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(den) < 1e-12:
        return
    X, Y = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
    l0 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / den
    l1 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / den
    l2 = 1.0 - l0 - l1
    inside = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
    if not inside.any():
        return

    z = l0 * az + l1 * bz + l2 * cz              # depth interpolates linearly in screen space
    if dfunc is not None:
        inside = inside & dfunc(z, depth[y0:y1 + 1, x0:x1 + 1])
        if not inside.any():
            return

    # perspective-correct varyings: DXBC `dcl_input_ps linear` is the perspective-correct mode
    iw = l0 * aiw + l1 * biw + l2 * ciw
    w = 1.0 / np.where(iw == 0, 1e-30, iw)
    m0 = (l0 * aiw) * w; m1 = (l1 * biw) * w; m2 = (l2 * ciw) * w

    def lerp(va, vb, vc):
        return m0[..., None] * va + m1[..., None] * vb + m2[..., None] * vc

    c0 = lerp(ac0, bc0, cc0)
    c1 = lerp(ac1, bc1, cc1)
    uv = lerp(auv, buv, cuv)
    u, v = uv[..., 0], uv[..., 1]

    if cls == "indexed":
        index = sample(t0, u, v, s0)[..., 0]                    # R8 index, normalised to 0..1
        texel = sample(t1, index, np.zeros_like(index), s1)
    elif cls in ("texalpha", "opaque"):
        texel = sample(t0, u, v, s0) if t0 is not None else np.ones(u.shape + (4,))
    else:
        return

    src_a = (c0[..., 3] if cls == "opaque" else texel[..., 3] * c0[..., 3])
    keep = inside & (src_a > aref)                              # ge fAlphaRef, a -> discard_nz
    if not keep.any():
        return
    rgb = texel[..., :3] * c0[..., :3] + c1[..., :3]

    if fogColor[3] != 0.0:
        wp = lerp(np.asarray(P[0][7], np.float64), np.asarray(P[1][7], np.float64),
                  np.asarray(P[2][7], np.float64))
        dist = np.linalg.norm(wp - cameraPos, axis=-1)
        f = np.sqrt(np.clip((dist - fogSR[0]) * fogSR[1], 0.0, 1.0) * fogColor[3])[..., None]
        rgb = rgb * (1.0 - f) + fogColor[:3] * f

    dst = color[y0:y1 + 1, x0:x1 + 1]
    if blend.get("en"):
        sf = blend_factor(blend["src"], rgb, src_a[..., None], dst[..., :3], dst[..., 3:4])
        df = blend_factor(blend["dst"], rgb, src_a[..., None], dst[..., :3], dst[..., 3:4])
        sfa = blend_factor(blend["srcA"], src_a, src_a, dst[..., 3], dst[..., 3])
        dfa = blend_factor(blend["dstA"], src_a, src_a, dst[..., 3], dst[..., 3])
        out_rgb = rgb * sf + dst[..., :3] * df
        out_a = src_a * sfa + dst[..., 3] * dfa
    else:
        out_rgb, out_a = rgb, src_a

    k3 = keep[..., None]
    dst[..., :3] = np.where(k3, np.clip(out_rgb, 0.0, 1.0), dst[..., :3])
    dst[..., 3] = np.where(keep, np.clip(out_a, 0.0, 1.0), dst[..., 3])
    if owner is not None:
        osub = owner[y0:y1 + 1, x0:x1 + 1]
        owner[y0:y1 + 1, x0:x1 + 1] = np.where(keep, di, osub)
    if dwrite:
        dsub = depth[y0:y1 + 1, x0:x1 + 1]
        depth[y0:y1 + 1, x0:x1 + 1] = np.where(keep, z, dsub)


def compare(frame, color, head, png, only, owner=None):
    name = head.get("sceneRTFile") or f"scene_{frame}_2048x1024_f87.bmp"
    bmp = open(os.path.join(HERE, name), "rb").read()
    off = struct.unpack_from("<I", bmp, 10)[0]
    W, H = struct.unpack_from("<i", bmp, 18)[0], struct.unpack_from("<i", bmp, 22)[0]
    img = np.frombuffer(bmp, np.uint8, W * abs(H) * 4, off).reshape(abs(H), W, 4)
    if H > 0:
        img = img[::-1]
    cx, cy, cw, ch = CROP
    truth = img[cy:cy + ch, cx:cx + cw].astype(np.int32)         # BGRA
    ours8 = np.clip(np.rint(color * 255.0), 0, 255).astype(np.int32)[cy:cy + ch, cx:cx + cw]
    ours_bgra = ours8[:, :, [2, 1, 0, 3]]

    both = (ours8[:, :, 3] > 0) & (truth[:, :, 3] > 0)
    n = cw * ch
    print(f"\nCOVERAGE  we {int((ours8[:,:,3]>0).sum()):,}  truth {int((truth[:,:,3]>0).sum()):,}  "
          f"MISSING {int(((truth[:,:,3]>0) & (ours8[:,:,3]==0)).sum()):,}  of {n:,}")
    if not both.any():
        print("  nothing in common to compare")
        return
    delta = np.abs(ours_bgra - truth)[both]
    differing = int((delta.max(axis=1) > 1).sum())
    print(f"COLOUR  over the {int(both.sum()):,} px both cover")
    print(f"  max |delta| : B={delta[:,0].max()} G={delta[:,1].max()} R={delta[:,2].max()} "
          f"A={delta[:,3].max()}")
    print(f"  mean |delta|: B={delta[:,0].mean():.3f} G={delta[:,1].mean():.3f} "
          f"R={delta[:,2].mean():.3f} A={delta[:,3].mean():.3f}")
    print(f"  differing   : {differing:,} px ({100.0*differing/both.sum():.3f}%) at >1 LSB")

    if owner is not None:
        by_i = {d["i"]: d for d in head["draws"]}
        own = owner[cy:cy + ch, cx:cx + cw]
        wrong = both & (np.abs(ours_bgra - truth).max(axis=2) > 1)
        tally = Counter(own[wrong].tolist())
        print()
        print("  WHO OWNS THE WRONG PIXELS (last writer, most first)")
        for di, cnt in tally.most_common(12):
            d = by_i.get(di, {})
            held = int((own == di).sum())
            print(f"    i={di:4d} {str(d.get('vsVariant')):8s}+{str(d.get('psVariant')):9s} "
                  f"wrong {cnt:7,} of {held:7,} it owns "
                  f"({100.0 * cnt / max(1, held):5.1f}%)  tex={d.get('tex')}")
        cls_tally = Counter(str(by_i.get(i, {}).get("psVariant")) for i in own[wrong].tolist())
        print("  by class:", dict(cls_tally))

        # Per-class scoreboard. A draw is judged only on the pixels where IT is the last writer --
        # the only pixels a composited truth can say anything about for that draw.
        for want in ("indexed", "texalpha", "opaque"):
            ids = [d["i"] for d in head["draws"] if d.get("psVariant") == want]
            held = Counter(own[np.isin(own, ids)].tolist())
            bad = Counter(own[wrong & np.isin(own, ids)].tolist())
            exact = sum(1 for i in ids if held.get(i, 0) and not bad.get(i, 0))
            silent = sum(1 for i in ids if not held.get(i, 0))
            print(f"  {want}: {len(ids)} draws -- {exact} pixel-exact, "
                  f"{len(ids) - exact - silent} wrong somewhere, {silent} never the last writer")
            worst = sorted(((bad.get(i, 0) / max(1, held.get(i, 1)), i) for i in ids
                            if held.get(i, 0)), reverse=True)[:6]
            for frac, i in worst:
                if frac:
                    print(f"      i={i:4d} {frac*100:5.1f}% of its {held[i]:6,} px wrong")

    import os as _os
    focus = _os.environ.get("FOCUS")
    if focus and owner is not None:
        fi = int(focus)
        m = (own == fi)
        dd = np.abs(ours_bgra - truth)[m]
        print()
        print(f"  FOCUS draw {fi}: {int(m.sum()):,} px it owns")
        print(f"    delta percentiles B: {np.percentile(dd[:,0], [50,90,99,100]).round(1)}")
        print(f"    delta percentiles G: {np.percentile(dd[:,1], [50,90,99,100]).round(1)}")
        print(f"    delta percentiles R: {np.percentile(dd[:,2], [50,90,99,100]).round(1)}")
        ys, xs = np.nonzero(m)
        print(f"    bbox x={xs.min()}..{xs.max()} y={ys.min()}..{ys.max()}")
        o = ours8[m][:, :3].mean(axis=0); t = truth[m][:, [2,1,0]].mean(axis=0)
        print(f"    mean ours RGB {o.round(1)}   mean truth RGB {t.round(1)}")

    if png:
        try:
            from PIL import Image
        except ImportError:
            sys.exit("--png needs Pillow (pip install pillow)")
        Image.fromarray(ours8.astype(np.uint8), "RGBA").save(png)
        print(f"  wrote {png}")
    if only:
        print("\n  SUBSET RENDER -- the numbers above are NOT a valid comparison. Alpha blending is")
        print("  not decomposable, so a subset over a black clear cannot equal the composite.")
    print("\n  MEASUREMENT, NOT A MECHANISM. Reproducing the pixels shows our reading of the capture")
    print("  is right; it establishes nothing about MvC2.")


if __name__ == "__main__":
    main()
