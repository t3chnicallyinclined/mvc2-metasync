#!/usr/bin/env python3
# bake_stage_backdrop.py — FIRST-PASS 2D stage backdrop bake for the tape render.
#
# Reads a LOCAL POL/TEX stage rip (maplecast rip_stage.py output: STGxx.json + STGxx_tNN.png)
# and rasterizes its placed meshes through a fixed fight camera into ONE flat backdrop strip:
#   stages/STG<xx>_bg.png   the flattened deck + sky snapshot (RENDER_W x 480)
#   stages/STG<xx>.json     { stage_id, file, name, imgW, imgH, groundImgY, parallax,
#                             bgColor, fidelity }  (consumed by renderer/stage-client.mjs)
#
# FIDELITY (honest): this is a STATIC camera snapshot of the POL-rip geometry, not a
# per-frame camera-matched 3D render. There is NO true multi-layer parallax (deck vs sky
# move together, scaled by one `parallax` factor). Only STG0B has a full engine-TA world
# bake; every other stage — including STG00 here — is deck+props via the POL rip, which is
# exactly this path. "Better than black", real stage pixels, honestly first-pass.
#
# Projection is a VERBATIM port of maplecast web/webgpu/stage-client.mjs _viewProj/_project
# (the DEFAULT_CAM no-matrix preview path); rasterizer mirrors tools/render_stage_before.py.
#
# usage:
#   python bake_stage_backdrop.py <stage_id> [--rip <dir>] [--out <dir>]
#          [--eye X Y Z] [--target X Y Z] [--fov DEG] [--w PX]
import sys, os, json, argparse
import numpy as np
from PIL import Image

SCREEN_H = 480

STAGE_NAMES = {
    0x00:'Airship Stage (Day, Flying)',0x01:'Desert Stage (Orange Sky)',0x02:'Factory Stage',
    0x03:'Carnival Stage (Summer/Spring)',0x04:'Swamp Stage',0x05:'Cave Stage (Water)',
    0x06:'Clocktower Stage (Clear Sky)',0x07:'River on Ice Stage',0x08:'Abyss Stage',
    0x09:'Airship Stage (Night, Floating)',0x0A:'Desert Stage (Blue Sky)',0x0B:'Training Stage',
    0x0C:'Carnival Stage (Winter/Fall)',0x0D:'Swamp (Asian)',0x0E:'Cave Stage (Lava)',
    0x0F:'Clocktower Stage (Snowy)',0x10:'River on Raft Stage',
}
# STG_ID is a clean 0-based identity index into the STGxx disc files (CONFIRMED panel/sh4-re:
# global 0x8c26A95C; Steam blk+0x6D3C maps to it exactly). Valid 0x00..0x10. No remap table.
def resolve_file(sid): return sid & 0xFF


def view_proj(eye, target, fov_deg, aspect):
    # VERBATIM maplecast _viewProj (up = world +Y = (0,1,0))
    f = np.array(target, float) - np.array(eye, float)
    f /= (np.linalg.norm(f) or 1.0)
    s = np.array([f[2], 0.0, -f[0]])           # forward x up
    s /= (np.linalg.norm(s) or 1.0)            # right
    u = np.array([s[1]*f[2]-s[2]*f[1], s[2]*f[0]-s[0]*f[2], s[0]*f[1]-s[1]*f[0]])  # s x f
    tan_half = np.tan(np.radians(fov_deg)/2) or 1.0
    return dict(right=s, up=u, fwd=f, eye=np.array(eye, float), tanHalf=tan_half, aspect=aspect)


def project(vp, p, W):
    # VERBATIM maplecast _project (returns screenX, screenY, depth=1/w)
    d = np.array(p, float) - vp['eye']
    vx = d @ vp['right']; vy = d @ vp['up']; vzf = d @ vp['fwd']
    w = max(vzf, 1e-3)
    ndcX = vx / (w * vp['tanHalf'] * vp['aspect'])
    ndcY = vy / (w * vp['tanHalf'])
    sx = (ndcX*0.5 + 0.5) * W
    sy = (1 - (ndcY*0.5 + 0.5)) * SCREEN_H
    return sx, sy, 1.0 / w


def project_ortho(op, p, W):
    # ORTHOGRAPHIC elevation looking along -Z: screenX=worldX, screenY=-worldY, depth=Z
    # (larger Z = nearer, so the far -Z skybox draws behind). No perspective wrap — a clean
    # flat 2D backdrop, the honest first-pass shape for a scrolled strip.
    sx = (p[0] - op['cx']) * op['scale'] + W/2
    sy = SCREEN_H/2 - (p[1] - op['cy']) * op['scale']
    return sx, sy, p[2]           # depth = Z (bigger = nearer)


def raster_tri(fb, ab, zb, tex, sv, W):
    if max(v[2] for v in sv) <= 0: return
    xs=[v[0] for v in sv]; ys=[v[1] for v in sv]
    minx=max(0,int(min(xs))); maxx=min(W-1,int(max(xs)))
    miny=max(0,int(min(ys))); maxy=min(SCREEN_H-1,int(max(ys)))
    if minx>maxx or miny>maxy: return
    x0,y0=sv[0][0],sv[0][1]; x1,y1=sv[1][0],sv[1][1]; x2,y2=sv[2][0],sv[2][1]
    den=(y1-y2)*(x0-x2)+(x2-x1)*(y0-y2)
    if abs(den)<1e-9: return
    th,tw=(tex.shape[0],tex.shape[1]) if tex is not None else (0,0)
    for py in range(miny,maxy+1):
        for px in range(minx,maxx+1):
            l0=((y1-y2)*(px+.5-x2)+(x2-x1)*(py+.5-y2))/den
            l1=((y2-y0)*(px+.5-x2)+(x0-x2)*(py+.5-y2))/den
            l2=1-l0-l1
            if l0<-.001 or l1<-.001 or l2<-.001: continue
            z=l0*sv[0][2]+l1*sv[1][2]+l2*sv[2][2]
            if z<=zb[py,px]: continue
            col=l0*sv[0][4]+l1*sv[1][4]+l2*sv[2][4]      # per-vertex color (modulation)
            if tex is not None and th:
                u=(l0*sv[0][3][0]+l1*sv[1][3][0]+l2*sv[2][3][0])%1.0
                v=(l0*sv[0][3][1]+l1*sv[1][3][1]+l2*sv[2][3][1])%1.0
                t=tex[int(v*(th-1)),int(u*(tw-1))]
                if t[3]<24: continue                     # skip near-transparent texels (ARGB4444)
                rgb=t[:3].astype(np.float32)*(col[:3]/255.0)
                a=t[3]
            else:
                rgb=col[:3]; a=255
            fb[py,px]=np.clip(rgb,0,255); ab[py,px]=a; zb[py,px]=z


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('stage_id', type=lambda x:int(x,0))
    ap.add_argument('--rip', default='C:/Users/trist/projects/maplecast-flycast/web/test-atlas/stages')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),'stages'))
    ap.add_argument('--eye', type=float, nargs=3, default=[0.0,-1400.0,7200.0])
    ap.add_argument('--target', type=float, nargs=3, default=[0.0,-100.0,0.0])
    ap.add_argument('--fov', type=float, default=42.0)
    ap.add_argument('--w', type=int, default=960)          # RENDER_W (>640 = horizontal pan margin)
    ap.add_argument('--groundImgY', type=float, default=None)  # override deck screen-row in bake
    ap.add_argument('--parallax', type=float, default=0.12)
    ap.add_argument('--tag', default='')                   # filename suffix for camera sweeps
    ap.add_argument('--ortho', action='store_true')        # orthographic -Z elevation
    ap.add_argument('--scale', type=float, default=0.06)   # ortho: world-units -> px
    ap.add_argument('--center', type=float, nargs=2, default=[0.0, 1200.0])  # ortho world (X,Y) at frame center
    ap.add_argument('--camRefX', type=float, default=0.0)  # tape camX the snapshot is framed at
    ap.add_argument('--camRefY', type=float, default=0.0)  # tape camY the snapshot is framed at
    args=ap.parse_args()

    sid=args.stage_id; fidx=resolve_file(sid)
    hx=f'{fidx:02X}'; W=args.w
    J=json.load(open(os.path.join(args.rip,f'STG{hx}.json')))
    tex={}
    for t in J['textures']:
        p=os.path.join(args.rip,t['file'])
        if os.path.exists(p):
            tex[t['index']]=np.asarray(Image.open(p).convert('RGBA')).astype(np.float32)
    vp=view_proj(args.eye,args.target,args.fov,W/SCREEN_H)
    op=dict(cx=args.center[0],cy=args.center[1],scale=args.scale)
    proj=(lambda p: project_ortho(op,p,W)) if args.ortho else (lambda p: project(vp,p,W))

    fb=np.zeros((SCREEN_H,W,3),np.float32)
    ab=np.zeros((SCREEN_H,W),np.float32)
    zb=np.full((SCREEN_H,W),-1e9,np.float32)
    ndrawn=0
    for m in J['meshes']:
        if not m.get('placed',True): continue
        t=tex.get(m['texIndex']) if m['texIndex']<len(J['textures']) else None
        for tri in m['tris']:
            sv=[]
            for v in tri:
                sx,sy,sz=proj(v['pos'])
                col=np.array(v.get('col',[255,255,255,255]),np.float32)
                sv.append((sx,sy,sz,v['uv'],col))
            raster_tri(fb,ab,zb,t,sv,W); ndrawn+=1

    rgb=np.clip(fb,0,255).astype(np.uint8)
    alpha=np.clip(ab,0,255).astype(np.uint8)
    # sky/bg fill color = median of the drawn top-quarter (behind everything)
    top=rgb[:SCREEN_H//4][alpha[:SCREEN_H//4]>0]
    bg=[int(x) for x in (np.median(top,0) if len(top) else [40,60,90])]
    # composite drawn pixels over the bg so the strip has no transparent holes
    out=np.empty((SCREEN_H,W,3),np.uint8); out[:]=bg
    mask=alpha>0; out[mask]=rgb[mask]
    cov=int(mask.sum())

    os.makedirs(args.out,exist_ok=True)
    tag=args.tag
    Image.fromarray(out).save(os.path.join(args.out,f'STG{hx}_bg{tag}.png'))
    # deck screen-row: median screen-Y of the deck meshes (largest tri-count, |Z|<1200 near origin)
    if args.groundImgY is not None:
        gimg=args.groundImgY
    else:
        # deck platform = the tex8 X/Z ~ +/-1056 flat mesh at Y~0 (the walkable floor)
        deck=sorted([m for m in J['meshes'] if m.get('placed',True)],key=lambda m:-len(m['tris']))[:2]
        dys=[]
        for m in deck:
            for tri in m['tris']:
                for v in tri:
                    _,sy,_=proj(v['pos']); dys.append(sy)
        gimg=float(np.median(dys)) if dys else SCREEN_H*0.78
    meta=dict(stage_id=sid,file=f'STG{hx}',name=STAGE_NAMES.get(fidx,'?'),
              imgW=W,imgH=SCREEN_H,groundImgY=round(gimg,1),parallax=args.parallax,
              bgColor=bg,camRefX=args.camRefX,camRefY=args.camRefY,
              cam=dict(eye=args.eye,target=args.target,fov=args.fov,ortho=args.ortho),
              fidelity='first-pass: POL-rip deck+props projected through a fixed fight camera '
                       'to a static wide snapshot; NOT per-frame camera-matched; single-layer '
                       'parallax (deck+sky scroll together). STG0B has a fuller engine-TA bake.')
    if not tag:
        json.dump(meta,open(os.path.join(args.out,f'STG{hx}.json'),'w'),indent=1)
    print(f'STG{hx} "{meta["name"]}"  {W}x{SCREEN_H}  tris={ndrawn}  coverage={100*cov/(W*SCREEN_H):.1f}%  '
          f'bg={bg}  groundImgY={meta["groundImgY"]}')


if __name__=='__main__':
    main()
