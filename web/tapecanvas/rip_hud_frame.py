#!/usr/bin/env python3
# ============================================================================
# DEPRECATED (2026-08-29) — SUPERSEDED BY rip_hud_quads.py. DO NOT USE.
#
# This flat-PNG "frame layer" bake is FUNDAMENTALLY WRONG and cannot be fixed by a
# palette tweak. CONFIRMED by decoding the capture:
#   • The metallic FRAME and the life-bar FILL are FUSED in the same quads — e.g. the
#     fmt=5 pieces [64][65][66][90][91] carry the silver/gold texture AND the bar's
#     gouraud vertex color on different corners. The `allwhite` filter below DROPS them
#     (they aren't pure-white), which is why the frame baked near-black (~2468 lit px).
#   • The frame quads INTERLEAVE with the bars in the engine's draw order (painter's ==
#     z-order): you cannot composite a single "behind" or "in-front" frame layer.
#   • The fmt=5 palette (palSel 16/24, ctrl=2 4444) was NOT wrong — it decodes to the
#     gold/purple/silver metal correctly; the bug was the flat-layer MODEL, not the decode.
# The faithful path is to render ALL 104 HUD quads IN ORDER, texture × per-vertex gouraud
# (PVR modulate) — exactly what maplecast gstaBuildHudTA -> pvr2 does. That is now baked by
# rip_hud_quads.py (hud/hud_quads.json + hud/hud_tex.png) and rendered by the software
# rasterizer in renderer/hud-client.mjs (gate: gate_hud_diff.mjs reproduces hud_0123.png).
# Kept only for reference/history.
# ============================================================================
# rip_hud_frame.py — VENDORED offline extractor for the MVC2 HUD FRAME ART (the ornate
# slanted life-bar border + caps). Bakes the STATIC (match-independent) frame quads from a
# captured VRAM + palette prefix into ONE RGBA overlay PNG that renderer/hud-client.mjs blits
# behind the fills/portraits/names. NO maplecast runtime dep — this reads the read-only capture
# files once and writes vendored assets into web/tapecanvas/hud/.
#
# GROUND TRUTH (read-only, in the maplecast-flycast repo):
#   tools/render-replica-poc/_hud_cap_def/hudq_tail.bin   — 104 real HUD quads (x/y/u/v/col/tcw…)
#   tools/render-replica-poc/_hud_cap_def/vram_prefix.bin — 8MB VRAM (frame textures live here)
#   tools/render-replica-poc/_hud_cap_def/pvr_prefix.bin  — PVR regs + palette RAM (regs+0x1000)
#
# DECODE is a VERBATIM port of the proven flycast WebGPU decoder
# (maplecast web/webgpu/texture-manager.mjs: twiddle tw()/twop, u1555/u565/u4444, _pal4/_pal8,
# updatePalette). fmt from tcw bits27-29 (5=PAL4, 6=PAL8, 0/1/2=1555/565/4444); WxH from tsp
# (8<<((tsp>>3)&7) x 8<<(tsp&7)); palSel = tcw bits21-26; VRAM byte addr = (tcw&0x1FFFFF)<<3.
#
# STATIC-FRAME FILTER: a quad is frame art iff ALL 4 vertex colors are the plain white swatch
# modulate (RGB == 0xFEFEFE) AND its texAddr is NOT a portrait/name texture. That drops the
# team-gouraud / red-chip bar fills (which carry team/warm/red vertex colors) and the per-char
# portrait/name textures — leaving only the match-independent border/cap art.
#
# usage: python3 rip_hud_frame.py [cap_dir] [out_dir]
#   cap_dir default = ../../../maplecast-flycast/tools/render-replica-poc/_hud_cap_def
#   out_dir default = ./hud
import os, sys, struct
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_CAP = os.path.normpath(os.path.join(
    HERE, "..", "..", "..", "maplecast-flycast", "tools", "render-replica-poc", "_hud_cap_def"))
CAP = sys.argv[1] if len(sys.argv) > 1 else DEF_CAP
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "hud")

# HUD band we bake (game 640x480 space). The captured frame art spans y ~44..112.
BAND_W, BAND_H = 640, 128

# Portrait + name texAddrs (per-char, EXCLUDE from the static frame). From HUDQ quads
# [3][9][15][21][27][33] (portraits) and [35..40] (names).
PORTRAIT_ADDRS = {0x4ef000, 0x4ef800, 0x4f0000, 0x4f2000, 0x4f2800, 0x4f3000}
NAME_ADDRS     = {0x4f0800, 0x4f1000, 0x4f1800, 0x4f3800, 0x4f4000, 0x4f4800}

# ── twiddle (BYTE-IDENTICAL to texture-manager.mjs tw/twop; flycast texconv twiddle_slow) ──
_DTW = [[None] * 11, [None] * 11]
def _tw(x, y, xs, ys):
    r = 0; s = 0; xs >>= 1; ys >>= 1
    while xs or ys:
        if ys: r |= (y & 1) << s; ys >>= 1; y >>= 1; s += 1
        if xs: r |= (x & 1) << s; xs >>= 1; x >>= 1; s += 1
    return r
for _s in range(11):
    a = [0] * 1024; b = [0] * 1024; _ys = 1 << _s
    for i in range(1024):
        a[i] = _tw(i, 0, 1024, _ys); b[i] = _tw(0, i, _ys, 1024)
    _DTW[0][_s] = a; _DTW[1][_s] = b
def twop(x, y, bx, by): return _DTW[0][by][x] + _DTW[1][bx][y]
def bsr(v):
    r = 0
    while (1 << r) < v: r += 1
    return r

# ── channel expansion + 16bpp unpack (verbatim: e5/e6/e4, u1555/u565/u4444) ──
def e5(v): return (v << 3) | (v >> 2)
def e6(v): return (v << 2) | (v >> 4)
def e4(v): return (v << 4) | v
def u1555(c): return (e5((c >> 10) & 31), e5((c >> 5) & 31), e5(c & 31), 255 if (c >> 15) else 0)
def u565(c):  return (e5((c >> 11) & 31), e6((c >> 5) & 63), e5(c & 31), 255)
def u4444(c): return (e4((c >> 8) & 15), e4((c >> 4) & 15), e4(c & 15), e4((c >> 12) & 15))


def load_palette(pvr):
    """Port of texture-manager.mjs updatePalette: ctrl @ regs+0x108 (&3); 1024 u32 @ regs+0x1000."""
    if len(pvr) < 0x1000 + 4096:
        return None
    ctrl = struct.unpack_from("<I", pvr, 0x108)[0] & 3
    unp = [u1555, u565, u4444, u4444][ctrl]
    pal = []
    for i in range(1024):
        raw = struct.unpack_from("<I", pvr, 0x1000 + i * 4)[0]
        if ctrl == 3:
            pal.append(((raw >> 16) & 0xFF, (raw >> 8) & 0xFF, raw & 0xFF, (raw >> 24) & 0xFF))
        else:
            pal.append(unp(raw & 0xFFFF))
    return pal, ctrl


def decode_tex(vram, pal, tcw, tsp):
    """Decode one HUD texture -> (W, H, [RGBA...]). Mirrors _decode/_pal4/_pal8 + direct path."""
    addr = (tcw & 0x1FFFFF) << 3
    fmt = (tcw >> 27) & 7
    scan = (tcw >> 26) & 1
    palSel = (tcw >> 21) & 0x3F
    w = 8 << ((tsp >> 3) & 7); h = 8 << (tsp & 7)
    bx, by = bsr(w), bsr(h)
    out = [(0, 0, 0, 0)] * (w * h)
    if fmt == 5:                                   # PAL4
        if not pal: return w, h, out
        pb = palSel << 4
        for y in range(h):
            for x in range(w):
                ti = twop(x, y, bx, by); bo = addr + (ti >> 1)
                if bo >= len(vram): continue
                ni = ((vram[bo] >> 4) & 0xF) if (ti & 1) else (vram[bo] & 0xF)
                out[y * w + x] = pal[pb + ni]
    elif fmt == 6:                                 # PAL8
        if not pal: return w, h, out
        pb = (palSel >> 4) << 8
        for y in range(h):
            for x in range(w):
                ti = twop(x, y, bx, by); bo = addr + ti
                if bo >= len(vram): continue
                out[y * w + x] = pal[pb + vram[bo]]
    else:                                          # direct 16bpp (0/1/2)
        unp = {0: u1555, 1: u565, 2: u4444}.get(fmt)
        if not unp: return w, h, out
        for y in range(h):
            for x in range(w):
                idx = (y * w + x) if scan == 1 else twop(x, y, bx, by)
                so = addr + idx * 2
                if so + 1 >= len(vram): continue
                out[y * w + x] = unp(vram[so] | (vram[so + 1] << 8))
    return w, h, out


def parse_quads(buf):
    """Parse hudq_tail.bin (magic 'HUDQ', u32 n, then n * 96-byte quads)."""
    if struct.unpack_from("<I", buf, 0)[0] != 0x48554451:
        raise SystemExit("bad HUDQ magic")
    n = struct.unpack_from("<I", buf, 4)[0]; p = 8; qs = []
    for _ in range(n):
        x = list(struct.unpack_from("<4f", buf, p + 0))
        y = list(struct.unpack_from("<4f", buf, p + 16))
        u = list(struct.unpack_from("<4f", buf, p + 32))
        v = list(struct.unpack_from("<4f", buf, p + 48))
        col = list(struct.unpack_from("<4I", buf, p + 64))
        pcw, isp, tsp, tcw = struct.unpack_from("<4I", buf, p + 80)
        qs.append(dict(x=x, y=y, u=u, v=v, col=col, pcw=pcw, isp=isp, tsp=tsp, tcw=tcw))
        p += 96
    return qs


def raster_quad(canvas, q, tex, tw, th):
    """Affine textured-quad blit into the RGBA `canvas` (list of [r,g,b,a], BAND_W wide).
    Verts are sorted into convex ring order around the centroid, then fan-triangulated; each
    pixel gets barycentric-interpolated UV, nearest-sampled from the decoded texture, over-blended."""
    import math
    pts = list(zip(q["x"], q["y"], q["u"], q["v"]))
    cx = sum(p[0] for p in pts) / 4.0; cy = sum(p[1] for p in pts) / 4.0
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))   # convex ring order

    def tri(a, b, c):
        minx = max(0, int(math.floor(min(a[0], b[0], c[0]))))
        maxx = min(BAND_W - 1, int(math.ceil(max(a[0], b[0], c[0]))))
        miny = max(0, int(math.floor(min(a[1], b[1], c[1]))))
        maxy = min(BAND_H - 1, int(math.ceil(max(a[1], b[1], c[1]))))
        d = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(d) < 1e-9: return
        for py in range(miny, maxy + 1):
            sy = py + 0.5
            for px in range(minx, maxx + 1):
                sx = px + 0.5
                l1 = ((b[1] - c[1]) * (sx - c[0]) + (c[0] - b[0]) * (sy - c[1])) / d
                l2 = ((c[1] - a[1]) * (sx - c[0]) + (a[0] - c[0]) * (sy - c[1])) / d
                l3 = 1.0 - l1 - l2
                if l1 < -0.001 or l2 < -0.001 or l3 < -0.001: continue
                uu = l1 * a[2] + l2 * b[2] + l3 * c[2]
                vv = l1 * a[3] + l2 * b[3] + l3 * c[3]
                tx = min(tw - 1, max(0, int(uu * tw)))
                ty = min(th - 1, max(0, int(vv * th)))
                pr, pg, pb, al = tex[ty * tw + tx]
                if al == 0: continue
                di = py * BAND_W + px; dst = canvas[di]; sa = al / 255.0
                canvas[di] = [int(pr * sa + dst[0] * (1 - sa)), int(pg * sa + dst[1] * (1 - sa)),
                              int(pb * sa + dst[2] * (1 - sa)), max(dst[3], al)]
    tri(pts[0], pts[1], pts[2])
    tri(pts[0], pts[2], pts[3])


def main():
    tail = open(os.path.join(CAP, "hudq_tail.bin"), "rb").read()
    vram = open(os.path.join(CAP, "vram_prefix.bin"), "rb").read()
    pvr = open(os.path.join(CAP, "pvr_prefix.bin"), "rb").read()
    quads = parse_quads(tail)
    palret = load_palette(pvr)
    pal = palret[0] if palret else None
    print(f"loaded {len(quads)} quads, vram {len(vram)}B, pal ctrl={palret[1] if palret else '?'}")

    canvas = [[0, 0, 0, 0] for _ in range(BAND_W * BAND_H)]
    texcache = {}
    kept = 0; skipped_dyn = 0; skipped_pn = 0
    for i, q in enumerate(quads):
        allwhite = all((c & 0xFFFFFF) == 0xFEFEFE for c in q["col"])
        addr = (q["tcw"] & 0x1FFFFF) << 3
        if not allwhite:
            skipped_dyn += 1; continue                     # team/warm/red -> dynamic bar/chip
        if addr in PORTRAIT_ADDRS or addr in NAME_ADDRS:
            skipped_pn += 1; continue                      # per-char portrait/name
        key = (q["tcw"], q["tsp"])
        if key not in texcache:
            texcache[key] = decode_tex(vram, pal, q["tcw"], q["tsp"])
        tw, th, tex = texcache[key]
        raster_quad(canvas, q, tex, tw, th)
        kept += 1

    os.makedirs(OUT, exist_ok=True)
    img = Image.new("RGBA", (BAND_W, BAND_H))
    img.putdata([tuple(p) for p in canvas])
    png = os.path.join(OUT, "hud_frame.png")
    img.save(png)
    import json
    meta = {"x": 0, "y": 0, "w": BAND_W, "h": BAND_H,
            "source": "maplecast _hud_cap_def (hudq_tail.bin + vram/pvr prefix)",
            "note": "static (match-independent) HUD frame art: white-swatch quads minus "
                    "portrait/name textures. Decoded via texture-manager.mjs port."}
    with open(os.path.join(OUT, "hud_frame.json"), "w") as f:
        json.dump(meta, f, indent=1)
    lit = sum(1 for p in canvas if p[3] > 0)
    print(f"kept {kept} frame quads (dropped {skipped_dyn} dynamic + {skipped_pn} portrait/name)")
    print(f"wrote {png} ({BAND_W}x{BAND_H}), {lit} lit px -> {os.path.join(OUT,'hud_frame.json')}")


if __name__ == "__main__":
    main()
