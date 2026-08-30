#!/usr/bin/env python3
# proof_full.py — HEADLESS pixel proof of the FULL tape render: 2D stage (when an asset is
# present) + bodies + sprite-class effects (with the garble-guard + hit-flash) + the FULL HUD
# (DM01 portraits, angled parallelogram life bars, roster names, TIME, super meters, combo).
#
# This is the PIL mirror of the WebGPU harness (gpu.html + renderer/): the SAME emitter
# geometry (proof_render.emit_body), the SAME garble-guard rule (sprite-client
# _isDegeneratePart), the SAME hit-flash (tape-adapter hitFx / sprite-client tint), and the
# SAME HUD math (hud-client.mjs). A correct output is direct evidence the JS path is right.
#
# usage: python proof_full.py [frameIdx] [out.png]

import sys, os, re, json, math
from PIL import Image, ImageDraw, ImageChops
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proof_render as P

HERE = P.HERE
CPSX, CPSY, HPMAX = P.CPSX, P.CPSY, P.HPMAX
METER_MAX = 144
P1_SLOTS, P2_SLOTS = [0, 2, 4], [1, 3, 5]

NAMES = {
    0x00:'RYU',0x01:'ZANGIEF',0x02:'GUILE',0x03:'MORRIGAN',0x04:'ANAKARIS',0x05:'STRIDER',
    0x06:'CYCLOPS',0x07:'WOLVERINE',0x08:'PSYLOCKE',0x09:'ICEMAN',0x0A:'ROGUE',
    0x0B:'CAPT.AMERICA',0x0C:'SPIDER-MAN',0x0D:'HULK',0x0E:'VENOM',0x0F:'DR.DOOM',
    0x10:'TRON',0x11:'JILL',0x12:'HAYATO',0x13:'RUBY HEART',0x14:'SONSON',0x15:'AMINGO',
    0x16:'MARROW',0x17:'CABLE',0x18:'ABYSS',0x19:'ABYSS',0x1A:'ABYSS',0x1B:'CHUN-LI',
    0x1C:'MEGA MAN',0x1D:'ROLL',0x1E:'AKUMA',0x1F:'B.B.HOOD',0x20:'FELICIA',0x21:'CHARLIE',
    0x22:'SAKURA',0x23:'DAN',0x24:'CAMMY',0x25:'DHALSIM',0x26:'M.BISON',0x27:'KEN',
    0x28:'GAMBIT',0x29:'JUGGERNAUT',0x2A:'STORM',0x2B:'SABRETOOTH',0x2C:'MAGNETO',
    0x2D:'SHUMA',0x2E:'WAR MACHINE',0x2F:'SILVER SAMURAI',0x30:'OMEGA RED',0x31:'SPIRAL',
    0x32:'COLOSSUS',0x33:'IRON MAN',0x34:'SENTINEL',0x35:'BLACKHEART',0x36:'THANOS',
    0x37:'JIN',0x38:'CAPT.COMMANDO',0x39:'WOLVERINE',0x3A:'SERVBOT',
}
# PIXEL-PERFECT HUD LAYOUT — mirror of renderer/hud-client.mjs (oracle-exact rects from
# gsta_stage.cpp P1BARS/P2BARS + HUDQ portrait/name quads). See that file for the citations.
TEAM_INNER = [(254,63,254),(0,254,0),(0,191,254)]      # C1 magenta / C2 green / C3 cyan
TEAM_HI    = [(255,156,255),(187,255,170),(174,235,255)]
BAR_OUTER  = (254,254,0); CHIP_RED = (254,0,0); FRAME_DARK = (26,29,36)
LB_P1 = [(46.6,269.5,46.0,57.7),(48.6,200.7,74.3,82.3),(48.6,200.7,94.3,102.3)]
LB_P2 = [(370.5,593.4,46.0,57.7),(439.3,591.4,74.3,82.3),(439.3,591.4,94.3,102.3)]
PORT_P1 = [(7,46,26,24),(21,74,18,17),(21,94,18,17)]
PORT_P2 = [(607,46,26,24),(601,74,18,17),(601,94,18,17)]
NAME_P1 = [(127,61,39,9),(111,84,29,7),(111,104,29,7)]
NAME_P2 = [(546,61,39,9),(555,84,29,7),(555,104,29,7)]
# legacy (bottom meter still uses a single point-color pair)
BAR_COLS = [((254,63,254),(255,156,255)), ((0,254,0),(187,255,170)), ((0,191,254),(174,235,255))]
CHIP = (138,20,20); WARM = (255,224,0)


def _hx(h): h=h.lstrip('#'); return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))


# ── portraits atlas (DM01) ──────────────────────────────────────────────────────
_PORT = None
def portraits():
    global _PORT
    if _PORT is not None: return _PORT
    _PORT = {}
    try:
        meta = json.load(open(os.path.join(HERE,'hud','portraits','portraits.json')))
        img = Image.open(os.path.join(HERE,'hud','portraits','portraits.png')).convert('RGBA')
        for k,r in meta.get('rects',{}).items():
            _PORT[int(k)] = img.crop((r['x'],r['y'],r['x']+r['w'],r['y']+r['h']))
    except Exception as e:
        print('  [warn] portraits atlas:', e)
    return _PORT


# ── garble-guard (mirror of sprite-client _isDegeneratePart) ─────────────────────
_DEGEN = {}
def is_degenerate(cid, part):
    key=(cid&0xff, part['x'], part['y'], part['w'], part['h'])
    if key in _DEGEN: return _DEGEN[key]
    w,h=part['w'],part['h']
    if w<2 or h<2 or w>48 or h>48: _DEGEN[key]=False; return False  # row-banded guard only (validated safe)
    img=P._cache[f'{cid&0xff:02X}'][2]
    c=img.crop((part['x'],part['y'],part['x']+w,part['y']+h)); px=c.load()
    solid=0; nonempty=0
    for y in range(h):
        first=None; uni=True; anyop=False
        for x in range(w):
            r,g,b,a=px[x,y]
            if a<8: continue
            anyop=True; rgb=(r<<16)|(g<<8)|b
            if first is None: first=rgb
            elif rgb!=first: uni=False
        if anyop:
            nonempty+=1
            if uni: solid+=1
    deg = nonempty>=3 and (solid/nonempty)>=0.85
    _DEGEN[key]=deg; return deg


# ── effect emit (own-origin, additive, garble-guarded) ───────────────────────────
def cid_for_slot(t,s): return t['p1_team'][s>>1] if s%2==0 else t['p2_team'][s>>1]

def emit_effect(o, slots, t, guard=True):
    sid,sx,sy,zx,face,cat,owner,layer = o[:8]
    if owner>=6: return [], None, 0
    cid=cid_for_slot(t,owner)
    ch=P.load_char(cid)
    if not ch: return [], cid, 0
    assemblies,parts,img,name=ch
    recs=assemblies.get(str(sid&0x7fff)) or assemblies.get(sid&0x7fff)
    if not recs: return [], cid, 0
    facing=slots[owner]['facing'] if slots[owner]['active'] else face
    objScale=zx/4096.0
    escl=(objScale/CPSX) if objScale>0.02 else 1.0     # eScl = objScale/asmScaleX (JS emitter)
    sl=dict(slot=owner,cid=cid,active=True,facing=facing,exx=sx,eyy=sy,sid=sid&0x7fff,xform=0,
            sclX=escl,sclY=escl,layer=layer,hp=144,red=144,costume=1)
    quads=P.emit_body(sl)
    guarded=0
    if guard:
        kept=[]
        for q in quads:
            px,py,pw,ph=q[2]
            part={'x':px,'y':py,'w':pw,'h':ph}
            if is_degenerate(cid, part): guarded+=1; continue
            kept.append(q)
        quads=kept
    return quads, cid, guarded


def paint_additive(base_rgba, quads):
    base=base_rgba.convert('RGB')
    for z,(dx,dy,dw,dh),(px,py,pw,ph),um,vf,cid in sorted(quads,key=lambda q:q[0]):
        if dw<.5 or dh<.5: continue
        img=P._cache[f'{cid&0xff:02X}'][2]
        sub=img.crop((px,py,px+pw,py+ph))
        if um: sub=sub.transpose(Image.FLIP_LEFT_RIGHT)
        if vf: sub=sub.transpose(Image.FLIP_TOP_BOTTOM)
        sub=sub.resize((max(1,round(dw)),max(1,round(dh))),Image.NEAREST)
        rgb=sub.convert('RGB'); a=sub.getchannel('A')
        pm=Image.composite(rgb, Image.new('RGB',rgb.size,(0,0,0)), a)
        layer=Image.new('RGB',base.size,(0,0,0)); layer.paste(pm,(round(dx),round(dy)))
        base=ImageChops.add(base,layer)
    return base.convert('RGBA')


# ── bodies with hit-flash ────────────────────────────────────────────────────────
def paint_bodies_flash(canvas, slots, hitstun, guard=True):
    quads=[]
    for sl in slots:
        if sl['active']:
            for q in P.emit_body(sl):
                px,py,pw,ph=q[2]
                if guard and is_degenerate(sl['cid'], {'x':px,'y':py,'w':pw,'h':ph}): continue
                quads.append(q+(hitstun[sl['slot']]>0,))
    quads.sort(key=lambda q:q[0])
    drawn=0
    for z,(dx,dy,dw,dh),(px,py,pw,ph),um,vf,cid,flash in quads:
        if dw<0.5 or dh<0.5: continue
        img=P._cache[f'{cid&0xff:02X}'][2]
        sub=img.crop((px,py,px+pw,py+ph))
        if um: sub=sub.transpose(Image.FLIP_LEFT_RIGHT)
        if vf: sub=sub.transpose(Image.FLIP_TOP_BOTTOM)
        sub=sub.resize((max(1,round(dw)),max(1,round(dh))),Image.NEAREST)
        if flash:                                   # victim hit-flash: additive near-white tint
            r,g,b,a=sub.split()
            boost=lambda ch,amt: ch.point(lambda v:min(255,int(v+amt)))
            sub=Image.merge('RGBA',(boost(r,128),boost(g,115),boost(b,115),a))
        canvas.alpha_composite(sub,(round(dx),round(dy)))
        drawn+=1
    return drawn


# ── FULL HUD (PIL port of hud-client.mjs renderState) ─────────────────────────────
def _quad(dr, ox, oy, l0, l1, h, skew, mirror, fill):
    d=-1 if mirror else 1
    pts=[(ox+d*l0,oy),(ox+d*l1,oy),(ox+d*(l1+skew),oy+h),(ox+d*(l0+skew),oy+h)]
    dr.polygon(pts, fill=fill)

# AXIS-ALIGNED (skew=0) opaque life-bar fill — mirror of hud-client.mjs _lifeBarAA. Rect
# [x0,x1]x[y0,y1] game space; p1side picks the outer (portrait-side) anchor. Draw order:
# dark backing -> bright-red chip (chipF) -> warm->team GOURAUD hp fill (hpF) -> sheen -> flash.
def _lerp(a,b,t): return tuple(int(a[i]+(b[i]-a[i])*t) for i in range(3))
def life_bar_aa(canvas, x0, x1, y0, y1, p1side, hpF, chipF, inner, hi, flash=0.0):
    dr=ImageDraw.Draw(canvas)
    w=x1-x0; outer=x0 if p1side else x1
    ix=lambda f:(outer+w*f) if p1side else (outer-w*f)
    def band(xa,xb,col):
        l,r=(xa,xb) if xa<=xb else (xb,xa)
        dr.rectangle([l,y0,r,y1],fill=col)
    dr.rectangle([x0,y0,x1,y1],fill=FRAME_DARK+(255,))                      # 1) dark channel
    if chipF>0: band(outer,ix(min(1,chipF)),CHIP_RED+(255,))               # 2) bright-red chip
    if hpF>0:
        f=min(1,hpF); xi=ix(f)
        lo,hix=(outer,xi) if outer<=xi else (xi,outer)
        span=max(1e-6,abs(xi-outer))
        for px in range(int(round(lo)),int(round(hix))):                    # 3) 2-stop gouraud
            t=(px-outer)/(xi-outer) if (xi-outer)!=0 else 0.0
            t=0.0 if t<0 else (1.0 if t>1 else t)
            dr.rectangle([px,y0,px+1,y1],fill=_lerp(BAR_OUTER,inner,t)+(255,))
        sh=max(1,int((y1-y0)*0.30))                                         # 4) top sheen
        for px in range(int(round(lo)),int(round(hix))):                    # opaque lightened band
            base=_lerp(BAR_OUTER,inner,max(0,min(1,(px-outer)/(xi-outer) if (xi-outer)!=0 else 0)))
            dr.rectangle([px,y0,px+1,y0+sh],fill=_lerp(base,hi,0.5)+(255,))
    if flash>0:                                                            # 5) hit-flash (white wash)
        a=int(min(1,flash)*0.8*255)
        ov=Image.new('RGBA',canvas.size,(0,0,0,0))
        ImageDraw.Draw(ov).rectangle([x0,y0,x1,y1],fill=(255,255,255,a))
        canvas.alpha_composite(ov)
    dr.rectangle([x0,y0,x1,y1],outline=(0,0,0,255),width=1)

def meter_bar(canvas, ox, oy, length, h, skew, mirror, fillF, col, glow=0.0):
    dr=ImageDraw.Draw(canvas)
    _quad(dr,ox,oy,0,length,h,skew,mirror,(21,24,30,255))
    f=max(0,min(1,fillF))
    if f>0:
        _quad(dr,ox,oy,0,length*f,h,skew,mirror,col+(255,))
        if glow>0: _quad(dr,ox,oy,0,length*f,h,skew,mirror,(255,255,255,int(0.35*glow*255)))
    d=-1 if mirror else 1
    dr.line([(ox,oy),(ox+d*length,oy),(ox+d*(length+skew),oy+h),(ox+d*skew,oy+h),(ox,oy)],
            fill=(0,0,0,220),width=1)

def digit_text(dr, s, x, y, size, anchor, col, font):
    dr.text((x,y), s, fill=col, font=font, anchor=anchor)

def draw_star(dr, cx, cy, r, col):
    pts=[]
    for k in range(5):
        a0=-math.pi/2+k*2*math.pi/5; a1=a0+math.pi/5
        pts+= [(cx+math.cos(a0)*r,cy+math.sin(a0)*r),(cx+math.cos(a1)*r*0.45,cy+math.sin(a1)*r*0.45)]
    dr.polygon(pts, fill=col)

# disp (optional) = {slot_index: {"hp":frac,"red":frac,"flash":0..1}} GLIDED displayed values
# from a HudAnim replay; when None the bars SNAP to the raw captured hp (single-frame proof).
# frameIdx drives the level glow + combo bounce; bounce = {0:frac,1:frac} per side.
def paint_full_hud(canvas, slots, hud, hitstun, disp=None, frameIdx=None, bounce=None):
    from PIL import ImageFont
    dr=ImageDraw.Draw(canvas)
    try: fbig=ImageFont.truetype('consolab.ttf',22)
    except Exception: fbig=ImageFont.load_default()
    try: fmid=ImageFont.truetype('consolab.ttf',13)
    except Exception: fmid=fbig
    try: fsm=ImageFont.truetype('consolab.ttf',9)
    except Exception: fsm=fbig
    PORT=portraits()
    # HUD FRAME BACKING (baked ornate border, from rip_hud_frame.py). Drawn first.
    try:
        fr=Image.open(os.path.join(HERE,'hud','hud_frame.png')).convert('RGBA')
        canvas.alpha_composite(fr,(0,0))
    except Exception: pass
    def point(side):
        for i,s in enumerate(side):
            if slots[s]['active']: return slots[s],i,s
        return slots[side[0]],0,side[0]
    p1,i1,ps1=point(P1_SLOTS); p2,i2,ps2=point(P2_SLOTS)
    # TEAM COLOR (gsta_stage.cpp: side color = ACTIVE POINT char's team-slot, all 3 bars).
    c1=(TEAM_INNER[i1],TEAM_HI[i1]); c2=(TEAM_INNER[i2],TEAM_HI[i2])
    # GLIDED displayed fractions when a HudAnim replay is supplied; else raw (snap).
    def dhp(sl,ps):
        if disp and ps in disp: return max(0,min(1,disp[ps]['hp']))
        return max(0,min(1,sl['hp']/HPMAX))
    def drd(sl,ps):
        if disp and ps in disp: return max(0,min(1,disp[ps]['red']))
        return max(0,min(1,sl['red']/HPMAX))
    def dfl(ps): return (disp[ps]['flash'] if (disp and ps in disp) else 0.0)
    # ALL 6 bars + 6 portraits + 6 names — active-first row order (point on row0).
    def draw_side(side_slots, bars, ports, names, p1side):
        inner,hi=(c1 if p1side else c2)
        order=[s for s in side_slots if slots[s]['active']]+[s for s in side_slots if not slots[s]['active']]
        for row in range(3):
            b=bars[row]; s=order[row]; sl=slots[s]; cid=sl['cid']&0xff
            hpF=dhp(sl,s); chipF=drd(sl,s)
            if chipF<hpF: chipF=hpF
            life_bar_aa(canvas,b[0],b[1],b[2],b[3],p1side,hpF,chipF,inner,hi,dfl(s))
            # portrait (26x24 point / 18x17 reserve; P1 H-flipped per HUDQ)
            px,py,pw,ph=ports[row]
            dr.rectangle([px,py,px+pw,py+ph],fill=(11,13,18,255))
            pim=PORT.get(cid)
            if pim:
                r=pim.resize((pw-2,ph-2),Image.NEAREST)
                if p1side: r=r.transpose(Image.FLIP_LEFT_RIGHT)
                canvas.paste(r,(px+1,py+1),r)
            else:
                dr.text((px+pw//2,py+max(1,(ph-12)//2)),(NAMES.get(cid,'?')[0]),fill=inner,font=fmid,anchor='ma')
            if sl['hp']<=0:
                ov=Image.new('RGBA',canvas.size,(0,0,0,0)); ImageDraw.Draw(ov).rectangle([px,py,px+pw,py+ph],fill=(0,0,0,128)); canvas.alpha_composite(ov)
            dr.rectangle([px,py,px+pw,py+ph],outline=inner+(255,),width=1)
            # roster name just below the bar (vector/truetype font, centered on the strip box)
            nx,ny,nw,nh=names[row]
            dr.text((nx,ny),NAMES.get(cid,'CHAR%02X'%cid),fill=(240,232,255),font=fsm,anchor='ma')
    draw_side(P1_SLOTS,LB_P1,PORT_P1,NAME_P1,True)
    draw_side(P2_SLOTS,LB_P2,PORT_P2,NAME_P2,False)
    # TIME center
    dr.rectangle([304,6,336,36],fill=(11,13,18),outline=(255,255,255))
    digit_text(dr,f"{max(0,min(99,hud['timer'])):02d}",320,9,22,'ma',(255,255,255),fbig)
    # super meters + level pips — DIRECT level/5 fill (no glide), free-running glow f(frameIdx)
    MTY,MTH,MTL,MTS,M1O,M2O=460,8,232,9,20,620
    import math as _m
    glow=(0.5+0.5*_m.sin((frameIdx or 0)*0.35))
    meter_bar(canvas,M1O,MTY,MTL,MTH,MTS,False,(hud['p1lvl'] or 0)/5.0,c1[0], glow if (hud['p1lvl'] or 0)>=1 else 0.0)
    meter_bar(canvas,M2O,MTY,MTL,MTH,MTS,True ,(hud['p2lvl'] or 0)/5.0,c2[0], glow if (hud['p2lvl'] or 0)>=1 else 0.0)
    def lvl(ox,mirror,n):
        n=max(0,min(8,n or 0))
        dr.text((ox+ (6 if mirror else -6), MTY-4), str(n), fill=(255,225,77), font=fmid, anchor=('la' if mirror else 'ra'))
        for i in range(n):
            px=ox-14-i*11 if mirror else ox+8+i*11
            dr.rectangle([px,MTY-7,px+8,MTY-3],fill=(255,210,77))
    lvl(M1O,False,hud['p1lvl']); lvl(M2O,True,hud['p2lvl'])
    # combo / damage panel — "N HITS" with HITS placed to the SIDE of the digit (measured
    # width), never on top of it (the old overlap nit). Pop bounce (scale+color) on increment.
    def combo(x,mirror,n,side):
        if (n or 0)<=1: return
        b=(bounce or {}).get(side,0.0)
        sz=22+int(b*6); col=(255,255,255) if b>0 else (255,210,77)
        f=ImageFont.truetype('consolab.ttf',sz) if fbig!=ImageFont.load_default() else fbig
        num=f"{n}"
        dr.text((x,50-(sz-22)),num,fill=col,font=f,anchor=('ra' if mirror else 'la'))
        nb=dr.textbbox((x,50-(sz-22)),num,font=f,anchor=('ra' if mirror else 'la'))
        numw=nb[2]-nb[0]; gap=5
        hx=(x-numw-gap) if mirror else (x+numw+gap)
        dr.text((hx,58),"HITS",fill=(255,233,160),font=fsm,anchor=('ra' if mirror else 'la'))
    combo(20,False,hud['p1combo'],0); combo(620,True,hud['p2combo'],1)


# ── stage backdrop (PIL mirror of renderer/stage-client.mjs render()) ────────────────
_STAGE=None
def load_stage(stage_id):
    global _STAGE
    if _STAGE is not None: return _STAGE
    _STAGE=False
    if stage_id is None or stage_id<0: return False
    hx=f'{stage_id & 0xFF:02X}'                       # STG_ID identity (panel/sh4-re)
    try:
        meta=json.load(open(os.path.join(HERE,'stages',f'STG{hx}.json')))
        img=Image.open(os.path.join(HERE,'stages',f'STG{hx}_bg.png')).convert('RGBA')
        meta['_img']=img
        _STAGE=meta
    except Exception as e:
        print('  [warn] stage backdrop:', e); _STAGE=False
    return _STAGE

def stage_canvas(t, row):
    # base canvas = sky bgColor fill + the wide strip scrolled by camX/camY (mirror stage-client)
    st=load_stage(t.get('stage_id'))
    if not st:
        return Image.new('RGBA',(640,480),(24,26,32,255))
    bg=tuple(st.get('bgColor',[30,34,44]))+(255,)
    canvas=Image.new('RGBA',(640,480),bg)
    Fi=t['_Fi']; camX=row[Fi['eyeX']]; camY=row[Fi['eyeY']]
    imgW=st['imgW']; imgH=st['imgH']; px=st.get('parallax',0.12)
    crx=st.get('camRefX',0); cry=st.get('camRefY',0)
    left=round((640-imgW)/2 - (camX-crx)*px)
    top =round((480-imgH)/2 + (camY-cry)*px)
    canvas.paste(st['_img'],(left,top))              # opaque strip; paste clips negative offsets
    return canvas


# ── main ──────────────────────────────────────────────────────────────────────────
def load_tape():
    t=json.load(open(os.path.join(HERE,'tape.json')))
    fields=[re.sub(r'\[.*','',f.strip()) for f in t['schema'].strip('[]').split(',')]
    t['_Fi']={n:i for i,n in enumerate(fields)}
    t['_byf']={fr:arr for fr,arr in t['objs']}
    return t

def main():
    t=load_tape(); Fi=t['_Fi']
    fi=int(sys.argv[1]) if len(sys.argv)>1 else 7729
    out=sys.argv[2] if len(sys.argv)>2 else os.path.join(HERE,f'proof_full_f{fi}.png')
    slots,hud=P.slot_state(t,fi)
    row=t['frames'][fi]; gframe=row[Fi['frame']]
    # hit-flash = hitstun RISING EDGE (fresh hit), matching tape-adapter.applyFrame.
    hs=row[Fi['hitstun']]
    phs=t['frames'][fi-1][Fi['hitstun']] if fi>0 else [0]*6
    hitstun=[ (1 if hs[s]>phs[s] else 0) for s in range(6) ]
    # STAGE backdrop (sky + scrolled airship strip) behind everything; falls back to flat fill
    canvas=stage_canvas(t,row)
    # bodies (hit-flash)
    nb=paint_bodies_flash(canvas,slots,hitstun)
    # effects (garble-guarded, additive)
    objs=t['_byf'].get(gframe,[])
    fxq=[]; drawn=0; guarded=0; skipped=0
    for o in objs:
        if not (1<=o[5]<=4): continue
        q,cid,g=emit_effect(o,slots,t,guard=True)
        guarded+=g
        if q: fxq+=q; drawn+=1
        else: skipped+=1
    canvas=paint_additive(canvas,fxq)
    # FULL HUD
    paint_full_hud(canvas,slots,hud,hitstun)
    canvas.convert('RGB').save(out)
    print(f'frame idx {fi} (game {gframe}) -> {out}')
    print(f'bodies:{nb} quads | effects:{drawn} nodes drawn, {skipped} empty, {guarded} garble-parts guarded')
    print(f'hitstun>0 slots:',[s for s in range(6) if hitstun[s]>0])
    print('HUD:',hud)

if __name__=='__main__':
    main()
