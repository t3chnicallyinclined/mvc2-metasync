#!/usr/bin/env python3
# rip_hud_quads.py — VENDORED offline bake of the MVC2 HUD for the REAL pvr2 renderer path
# (renderer/hud-pvr2.mjs -> pvr2-renderer.mjs). Emits, into web/tapecanvas/hud/:
#   hud_quads.json — the 104 HUD quads in DRAW ORDER with their RAW pvr words
#                    {x[4],y[4],u[4],v[4],col[4],pcw,isp,tsp,tcw} + {cls,side,row,sub} for the
#                    client's live bar-reshape/team-recolor. Fed straight to buildHudTA -> pvr2.
#   hud_vram.bin   — the STATIC HUD VRAM slab [0x400000,0x500000) (frame/bars/names/portraits).
#   hud_pal.bin    — the palette RAM (pvr_regs prefix).
#   hud_vram.json  — {base,len,vramSize,palLen} so the client splats the slab into a sparse 8 MiB
#                    vram array before pvr2 samples it.
#
# The 104 quads (hudq_inventory.txt / hudq_tail.bin) are the engine's REAL HUD primitives; the
# metallic FRAME and life-bar FILL are FUSED per-quad and z-INTERLEAVE, so there is NO separable
# "frame layer" — the faithful HUD is these quads rendered IN ORDER through pvr2 (the exact TA
# rasterizer that produced the oracle _hud_cap_def/hud_0123.png). A prior software re-raster was a
# wheel-reinvention and is deleted; the byte-exact gate is `node gate_hud_pvr2.mjs`.
#
# The hud_vram.bin / hud_pal.bin (and the portraits) are ROM-derived -> gitignore / scp-only.
#
# usage: python3 rip_hud_quads.py [cap_dir] [out_dir]
import os, sys, struct, json, math
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DEF_CAP = os.path.normpath(os.path.join(
    HERE, "..", "..", "..", "maplecast-flycast", "tools", "render-replica-poc", "_hud_cap_def"))
args = [a for a in sys.argv[1:] if not a.startswith("--")]
CAP = args[0] if len(args) > 0 else DEF_CAP
OUT = args[1] if len(args) > 1 else os.path.join(HERE, "hud")
SELFCHECK = "--selfcheck" in sys.argv

BAND_W, BAND_H = 640, 128

# per-char portrait/name texAddrs — the client OVERRIDES these quads to sample a per-char atlas.
PORTRAIT_ADDRS = {0x4ef000, 0x4ef800, 0x4f0000, 0x4f2000, 0x4f2800, 0x4f3000}
NAME_ADDRS     = {0x4f0800, 0x4f1000, 0x4f1800, 0x4f3800, 0x4f4000, 0x4f4800}
BAR_ADDR       = 0x400000    # tcw&0x1FFFFF==0x80000 — the white swatch modulated by bar gouraud

# ── twiddle (byte-identical to texture-manager.mjs) ──
_DTW = [[None]*11, [None]*11]
def _tw(x, y, xs, ys):
    r=0; s=0; xs>>=1; ys>>=1
    while xs or ys:
        if ys: r|=(y&1)<<s; ys>>=1; y>>=1; s+=1
        if xs: r|=(x&1)<<s; xs>>=1; x>>=1; s+=1
    return r
for _s in range(11):
    a=[0]*1024; b=[0]*1024; _ys=1<<_s
    for i in range(1024): a[i]=_tw(i,0,1024,_ys); b[i]=_tw(0,i,_ys,1024)
    _DTW[0][_s]=a; _DTW[1][_s]=b
def twop(x,y,bx,by): return _DTW[0][by][x]+_DTW[1][bx][y]
def bsr(v):
    r=0
    while (1<<r)<v: r+=1
    return r
def e5(v): return (v<<3)|(v>>2)
def e6(v): return (v<<2)|(v>>4)
def e4(v): return (v<<4)|v
def u1555(c): return (e5((c>>10)&31), e5((c>>5)&31), e5(c&31), 255 if (c>>15) else 0)
def u565(c):  return (e5((c>>11)&31), e6((c>>5)&63), e5(c&31), 255)
def u4444(c): return (e4((c>>8)&15), e4((c>>4)&15), e4(c&15), e4((c>>12)&15))

def load_palette(pvr):
    if len(pvr) < 0x1000+4096: return None, None
    ctrl = struct.unpack_from("<I", pvr, 0x108)[0] & 3
    unp = [u1555,u565,u4444,u4444][ctrl]
    pal=[]
    for i in range(1024):
        raw=struct.unpack_from("<I", pvr, 0x1000+i*4)[0]
        if ctrl==3: pal.append(((raw>>16)&0xFF,(raw>>8)&0xFF,raw&0xFF,(raw>>24)&0xFF))
        else: pal.append(unp(raw&0xFFFF))
    return pal, ctrl

def decode_tex(vram, pal, tcw, tsp):
    addr=(tcw&0x1FFFFF)<<3
    fmt=(tcw>>27)&7
    scan=(tcw>>26)&1
    palSel=(tcw>>21)&0x3F
    w=8<<((tsp>>3)&7); h=8<<(tsp&7)
    bx,by=bsr(w),bsr(h)
    out=[(0,0,0,0)]*(w*h)
    if fmt==5:
        if not pal: return w,h,out
        pb=palSel<<4
        for y in range(h):
            for x in range(w):
                ti=twop(x,y,bx,by); bo=addr+(ti>>1)
                if bo>=len(vram): continue
                ni=((vram[bo]>>4)&0xF) if (ti&1) else (vram[bo]&0xF)
                out[y*w+x]=pal[pb+ni]
    elif fmt==6:
        if not pal: return w,h,out
        pb=(palSel>>4)<<8
        for y in range(h):
            for x in range(w):
                ti=twop(x,y,bx,by); bo=addr+ti
                if bo>=len(vram): continue
                out[y*w+x]=pal[pb+vram[bo]]
    else:
        unp={0:u1555,1:u565,2:u4444}.get(fmt)
        if not unp: return w,h,out
        for y in range(h):
            for x in range(w):
                idx=(y*w+x) if scan==1 else twop(x,y,bx,by)
                so=addr+idx*2
                if so+1>=len(vram): continue
                out[y*w+x]=unp(vram[so]|(vram[so+1]<<8))
    return w,h,out

def parse_quads(buf):
    if struct.unpack_from("<I",buf,0)[0]!=0x48554451: raise SystemExit("bad HUDQ magic")
    n=struct.unpack_from("<I",buf,4)[0]; p=8; qs=[]
    for _ in range(n):
        x=list(struct.unpack_from("<4f",buf,p+0)); y=list(struct.unpack_from("<4f",buf,p+16))
        u=list(struct.unpack_from("<4f",buf,p+32)); v=list(struct.unpack_from("<4f",buf,p+48))
        col=list(struct.unpack_from("<4I",buf,p+64))
        pcw,isp,tsp,tcw=struct.unpack_from("<4I",buf,p+80)
        qs.append(dict(x=x,y=y,u=u,v=v,col=col,pcw=pcw,isp=isp,tsp=tsp,tcw=tcw)); p+=96
    return qs

def classify(q):
    tcw=q["tcw"]; addr=(tcw&0x1FFFFF)<<3
    xs=q["x"]; ys=q["y"]; cx=sum(xs)/4.0; cy=sum(ys)/4.0
    side = 0 if cx<320 else 1
    row  = 0 if cy<70 else (1 if cy<95 else 2)
    if addr in PORTRAIT_ADDRS: return "portrait", side, row, None
    if addr in NAME_ADDRS:     return "name", side, row, None
    if addr == BAR_ADDR:
        allred = all(((c>>16)&0xFF)>0x80 and ((c>>8)&0xFF)<0x40 and (c&0xFF)<0x40 for c in q["col"])
        return "bar", side, row, ("chip" if allred else "fill")
    return "frame", side, row, None

def main():
    tail=open(os.path.join(CAP,"hudq_tail.bin"),"rb").read()
    vram=open(os.path.join(CAP,"vram_prefix.bin"),"rb").read()
    pvr =open(os.path.join(CAP,"pvr_prefix.bin"),"rb").read()
    quads=parse_quads(tail)
    pal,ctrl=load_palette(pvr)
    print(f"loaded {len(quads)} quads, vram {len(vram)}B, pal ctrl={ctrl}")

    os.makedirs(OUT,exist_ok=True)
    out_quads=[]
    for i,q in enumerate(quads):
        cls,side,row,sub=classify(q)
        tsp=q["tsp"]
        # PVR2 render semantics (CONFIRMED web/webgpu/pvr2-renderer.mjs + texture-manager.mjs):
        #   filter  fm = (tsp>>13)&3   (0 = point/nearest; else bilinear)
        #   blend   sb = (tsp>>29)&7  src factor, db = (tsp>>26)&7  dst factor
        #           SBM=[zero,one,dst,1-dst,srcA,1-srcA,dstA,1-dstA]; DBM likewise (src-based)
        out_quads.append({
            "x":[round(v,3) for v in q["x"]], "y":[round(v,3) for v in q["y"]],
            "u":[round(v,5) for v in q["u"]], "v":[round(v,5) for v in q["v"]],
            "col":[f"{c:08x}" for c in q["col"]],
            "tk":f'{q["tcw"]:08x}_{q["tsp"]:08x}', "fmt":(q["tcw"]>>27)&7,
            "cls":cls, "side":side, "row":row, "sub":sub,
            # RAW PVR words — the tape HUD renders through the REAL pvr2 rasterizer (renderer/
            # hud-pvr2.mjs), which needs pcw/isp/tsp/tcw verbatim. The client reshapes bar x + recolors
            # col by live HP/team, then feeds these straight to buildHudTA -> pvr2 (byte-exact vs oracle).
            "pcw":f'{q["pcw"]:08x}', "isp":f'{q["isp"]:08x}',
            "tsp":f'{q["tsp"]:08x}', "tcw":f'{q["tcw"]:08x}',
        })
    meta={"screenW":640,"screenH":480,"nquads":len(out_quads),
          "source":"maplecast _hud_cap_def hudq_tail.bin+vram/pvr prefix (engine draw order; pvr2 path)",
          "quads":out_quads}
    json.dump(meta, open(os.path.join(OUT,"hud_quads.json"),"w"))
    print(f"wrote hud_quads.json ({len(out_quads)} quads, raw pvr words for the pvr2 path)")

    # ── STATIC HUD VRAM + palette for the REAL pvr2 path (renderer/hud-pvr2.mjs). The tape carries
    # no HUD VRAM, so the client renders the HUD quads against this baked, match-independent VRAM
    # region (frame/bars/names/portraits from the capture). ROM-derived -> gitignore/scp-only.
    # The HUD textures live in [0x400000, 0x500000); we ship just that 1 MiB slab + its base so the
    # client can splat it into a sparse 8 MiB vram array before pvr2 samples it. ──
    VBASE, VEND = 0x400000, 0x500000
    with open(os.path.join(OUT,"hud_vram.bin"),"wb") as f: f.write(vram[VBASE:VEND])
    with open(os.path.join(OUT,"hud_pal.bin"),"wb") as f: f.write(pvr)
    json.dump({"base":VBASE,"len":VEND-VBASE,"vramSize":len(vram),"palLen":len(pvr)},
              open(os.path.join(OUT,"hud_vram.json"),"w"))
    print(f"wrote hud_vram.bin ({(VEND-VBASE)//1024} KiB @0x{VBASE:06x}), hud_pal.bin ({len(pvr)} B)")
    print("VERIFY: node gate_hud_pvr2.mjs  (real pvr2 vs oracle hud_0123.png — expect 0.00/px)")

if __name__=="__main__":
    main()
