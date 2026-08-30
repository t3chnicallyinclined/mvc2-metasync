#!/usr/bin/env python3
"""fxprobe.py — READ-ONLY live probe that CONFIRMS the three broken effect-object offsets.

Phase-2 empirically proved the 0.3.28 `objs` capture has THREE wrong node offsets (whole-tape scan,
docs/OWNED-RENDER-BUILD-SPEC.md §3 lines 206-213):
    (1) gfx / Dat_GFX1 effect key  — currently H+0x1A8, 0/23742 objs land in the effect bank.
    (2) owner (node -> fighter slot) — currently H_OWNER_A=0x9c / H_OWNER_B=0xc4, every obj = 255.
    (3) per-object scale            — currently H_SCALE_X=0x130, a CONSTANT 426.625 garbage.

This probe finds all three from LIVE Steam memory in one session so reader.rs harvest_objs (0.3.29)
can be fixed with CONFIRMED offsets instead of guesses.

MECHANISM (nothing reinvented):
  * process attach + read = mvcmem.Mem  — opens PROCESS_VM_READ only, so it CANNOT write. Safe to run
    while a match is live. (savestate.Game has a write handle; we deliberately do NOT use it.)
  * blk resolution + draw-list walk = the exact path in verify.py `cmd_pool` (CONFIRMED live):
        blk        = *(u64)(EXE + 0xAC6EF0)
        count[L]   =  u8  @ blk + 0x324D0 + L                       (16 layers)
        handle[L,i]=  u64 @ blk + 0x2F4D0 + L*0x300 + i*8   for i < count[L]
    fighters (blk+0x3DB8+i*0x738) are skipped; everything else is an object-pool node.
  * value-test recipe (docs/OWNED-RENDER-BUILD-SPEC.md §3, CONFIRMED):
        B     = *(u32)(blk + 0x6CE8)          effect/model dir base   (~0x0CED0000)
        DBASE = *(u32)(B   + 0x08)
        a node's gfx key is the H+0x180..0x1C0 word whose (word & 0x1FFFFFFF) in [B, B+0x10000)
        dirIdx = ((key & 0x1FFFFFFF) - DBASE) / 0x10

It SAMPLES ~10s (default) so the user can throw a fireball / do a super while it runs, capturing the
first N drawn effect nodes it sees. Then it AUTO-IDENTIFIES and prints:
    FOUND: gfx=H+0xNN  owner=H+0xNN  scale=H+0xNN
plus a ready-to-paste reader.rs harvest_objs patch.

usage:  python fxprobe.py [seconds] [max_nodes]
        (defaults: 10s, 40 nodes)
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mvcmem import EXE, Mem

# ── constants (all CONFIRMED live; sources cited) ────────────────────────────────────────────────
BLK_PTR       = EXE + 0xAC6EF0          # savestate.py BLK_PTR  (CONFIRMED)
MODE_OFF      = 0x3CB8                   # byte[2]: 1=char-select 2=in-battle  (verify.py MODE_OFF)
FC_OFF        = 0x3CC8                   # sim frame counter                    (savestate.py FC_OFF)
H0            = 0x3DB8                   # fighter slot 0 (draw-list handle base) (reader.rs BLK_H0_OFF)
STRIDE        = 0x738                    # fighter stride                        (reader.rs STRIDE)
CL_BACK       = 0x16C                    # cl (logical) base = H + 0x16C         (reader.rs OBJ_BACK)
DRAW_LIST     = 0x2F4D0                  # blk-rel: layer handle arrays          (reader.rs DRAWLIST_OFF)
DRAW_COUNTS   = 0x324D0                  # blk-rel: u8 count per layer           (reader.rs DRAWLIST_COUNTS)
DRAW_LAYER    = 0x300                    # per-layer stride                      (reader.rs DRAWLIST_LAYER)
N_LAYERS      = 16
MAX_PER_LAYER = 0x60                     # engine cap                            (reader.rs DRAWLIST_MAX_PER_LAYER)

H_CATEGORY    = 0x03                     # node category (effect = 1..4)         (reader.rs H_CATEGORY)
H_DRAWN       = 0x170                    # draw gate, non-zero = rendered        (reader.rs H_DRAWN)
H_SPRITE_ID   = 0x188                    # render key u16 (mask 0x7FFF)          (reader.rs H_SPRITE_ID)
H_SCREEN_X    = 0x124                    # engine screen X f32                   (reader.rs H_SCREEN_X)
H_SCREEN_Y    = 0x128                    # engine screen Y f32                   (reader.rs H_SCREEN_Y)
H_OWNER_A     = 0x9c                     # current (WRONG) owner cand A          (reader.rs H_OWNER_A)
H_OWNER_B     = 0xc4                     # current (WRONG) owner cand B          (reader.rs H_OWNER_B)
H_GFX1_CUR    = 0x1a8                    # current (WRONG) gfx offset            (reader.rs H_GFX1_PTR)
H_SCALE_CUR   = 0x130                    # current (WRONG) scale offset          (reader.rs H_SCALE_X)

GFX_B_OFF     = 0x6CE8                   # blk-rel: B = *(u32)(blk+this)         (spec §3 value-test)
DBASE_OFF     = 0x08                     # DBASE = *(u32)(B+this)                (spec §3 value-test)
BANK_LO, BANK_HI = 0x0CED0000, 0x0CEE0000  # empirical effect bank (spec §3, whole-tape scan)
BANK_WIN      = 0x10000                  # [B, B+0x10000)                        (spec §3)

NODE_SZ       = 0x200                    # read window per node (covers 0..0x1FF)
GFX_SCAN      = range(0x140, NODE_SZ - 4 + 1, 4)   # widened scan around H+0x190..0x1C0 cluster
GFX_DUMP      = range(0x180, 0x1C0 + 1, 4)         # the detailed dump window the task asked for
OWNER_SCAN    = range(0x00, NODE_SZ - 8 + 1, 4)    # every 4-aligned u64 in the node
SCALE_SCAN    = range(0x40, 0x140, 4)              # plausible float region (world..screen..magnifier)


# ── little-endian field readers over a captured buffer ───────────────────────────────────────────
def u16b(b, o):  return struct.unpack_from("<H", b, o)[0] if o + 2 <= len(b) else None
def u32b(b, o):  return struct.unpack_from("<I", b, o)[0] if o + 4 <= len(b) else None
def u64b(b, o):  return struct.unpack_from("<Q", b, o)[0] if o + 8 <= len(b) else None
def f32b(b, o):  return struct.unpack_from("<f", b, o)[0] if o + 4 <= len(b) else None


def masked28(v):
    return None if v is None else (v & 0x1FFFFFFF)


def in_bank(v, B):
    """low-28 of v lands in the effect bank. Prefer live-resolved [B,B+win); fall back to empirical."""
    m = masked28(v)
    if m is None:
        return False
    if B is not None:
        return B <= m < B + BANK_WIN
    return BANK_LO <= m < BANK_HI


def collect(m, secs, cap):
    """Poll the draw list for ~secs, return distinct DRAWN non-fighter nodes (buffer + meta)."""
    blk = m.u64(BLK_PTR)
    if not blk:
        return None, None, []
    fighters = {blk + H0 + i * STRIDE for i in range(6)}
    seen = {}          # handle -> node dict (first drawn sighting kept)
    t0 = time.time()
    polls = 0
    while time.time() - t0 < secs and len(seen) < cap:
        counts = m.read(blk + DRAW_COUNTS, N_LAYERS)
        table = m.read(blk + DRAW_LIST, N_LAYERS * DRAW_LAYER)
        if not counts or not table:
            continue
        polls += 1
        for L in range(N_LAYERS):
            n = min(counts[L], MAX_PER_LAYER)
            for i in range(n):
                h = struct.unpack_from("<Q", table, L * DRAW_LAYER + i * 8)[0]
                if not h or h <= 0x10000 or h in fighters or h in seen:
                    continue
                buf = m.read(h, NODE_SZ)
                if not buf or len(buf) < NODE_SZ:
                    continue
                if buf[H_DRAWN] == 0:
                    continue                         # not rendered this frame
                sid = u16b(buf, H_SPRITE_ID) & 0x7FFF
                if sid == 0:
                    continue                         # inactive node
                seen[h] = dict(handle=h, off=h - blk, layer=L, cat=buf[H_CATEGORY],
                               sid=sid, buf=buf)
        time.sleep(0.004)
    return blk, fighters, list(seen.values())


def dump_nodes(nodes, blk, fighters, B):
    """Per-node evidence dump (first 8), exactly the fields the task listed."""
    print(f"\n{'='*94}\nPER-NODE EVIDENCE  (first {min(8,len(nodes))} of {len(nodes)} drawn nodes)\n{'='*94}")
    fbase_h  = {blk + H0 + i * STRIDE: i for i in range(6)}                 # H-base -> slot
    fbase_cl = {blk + H0 + CL_BACK + i * STRIDE: i for i in range(6)}       # cl-base -> slot
    for nd in nodes[:8]:
        b = nd["buf"]
        sx = f32b(b, H_SCREEN_X); sy = f32b(b, H_SCREEN_Y)
        print(f"\n-- node 0x{nd['handle']:x}  (blk+0x{nd['off']:x})  layer={nd['layer']:2d}  "
              f"cat={nd['cat']}  sid={nd['sid']}  screen=({sx:.1f},{sy:.1f})")
        # (a) the H+0x180..0x1C0 gfx cluster: u32 + as-pointer low28 + in-bank flag
        print("   gfx cluster H+0x180..0x1C0  [off : u32          low28      in-bank?]")
        for o in GFX_DUMP:
            v = u32b(b, o)
            tag = "  <<< IN EFFECT BANK" if in_bank(v, B) else ""
            print(f"      H+0x{o:03x} : 0x{v:08x}   0x{masked28(v):08x}{tag}")
        # (b) current owner candidates + wider scan for any u64 == a fighter base
        oa, ob = u64b(b, H_OWNER_A), u64b(b, H_OWNER_B)
        print(f"   owner cand H+0x9c=0x{oa:x}  H+0xc4=0x{ob:x}  "
              f"(match slot? {fbase_h.get(oa, fbase_cl.get(oa, '-'))}/"
              f"{fbase_h.get(ob, fbase_cl.get(ob, '-'))})")
        hits = []
        for o in OWNER_SCAN:
            v = u64b(b, o)
            if v in fbase_h:
                hits.append(f"H+0x{o:x}->slot{fbase_h[v]}(H-base)")
            elif v in fbase_cl:
                hits.append(f"H+0x{o:x}->slot{fbase_cl[v]}(cl-base)")
        print(f"   wider owner scan (u64==fighter base): {hits if hits else 'NONE'}")
        # (c) candidate scale floats near the node
        cand = []
        for o in (0x50, 0x54, 0x124, 0x128, 0x130, 0x134, 0xec, 0xf0, 0x11c, 0x120):
            fv = f32b(b, o)
            if fv is not None and 0.001 < abs(fv) < 4096.0:
                cand.append(f"H+0x{o:x}={fv:.4f}")
        print(f"   scale candidates: {cand}")


def analyse_gfx(nodes, B, DBASE):
    """Winner = the H+0x180..0x1C0 offset whose word lands in the effect bank across the MOST nodes."""
    tally = {}          # off -> hit count
    for nd in nodes:
        b = nd["buf"]
        for o in GFX_SCAN:
            if in_bank(u32b(b, o), B):
                tally[o] = tally.get(o, 0) + 1
    print(f"\n{'='*94}\n(1) GFX / Dat_GFX1 effect-key offset  — value-test over {len(nodes)} nodes\n{'='*94}")
    if not tally:
        print("   NO offset produced an in-bank word on any node.")
        print("   => either no true effect node was captured (retry: do a super/projectile during the")
        print("      window), or B is mis-resolved. Check the B/DBASE line above.")
        return None
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    for o, c in ranked[:8]:
        star = " <<< WINNER" if (o, c) == ranked[0] else ""
        print(f"   H+0x{o:03x}: in-bank on {c}/{len(nodes)} nodes{star}")
    best, best_hits = ranked[0]
    if best == H_GFX1_CUR:
        print(f"   NOTE: winner equals the CURRENT H+0x1A8 — width/mask may be the bug, not the offset.")
    else:
        print(f"   CONFIRMED: real gfx offset is H+0x{best:03x}  (current H+0x1A8 was wrong).")
    # dirIdx per node at the winning offset
    print("   dirIdx per node (spec: (key&0x1FFFFFFF - DBASE)/0x10):")
    for nd in nodes:
        key = u32b(nd["buf"], best)
        if not in_bank(key, B):
            continue
        km = masked28(key)
        di_dbase = (km - DBASE) // 0x10 if DBASE is not None else None
        di_b = (km - B) // 0x10 if B is not None else None
        print(f"      sid={nd['sid']:5d} key=0x{km:08x}  dirIdx(DBASE)={di_dbase}  dirIdx(B)={di_b}")
    return best


def analyse_owner(nodes, blk):
    """Winner = the u64 offset that equals a fighter base on the MOST nodes (H-base or cl-base)."""
    fbase_h  = {blk + H0 + i * STRIDE: i for i in range(6)}
    fbase_cl = {blk + H0 + CL_BACK + i * STRIDE: i for i in range(6)}
    tally = {}          # (off, kind) -> hit count
    for nd in nodes:
        b = nd["buf"]
        for o in OWNER_SCAN:
            v = u64b(b, o)
            if v in fbase_h:
                tally[(o, "H")] = tally.get((o, "H"), 0) + 1
            elif v in fbase_cl:
                tally[(o, "cl")] = tally.get((o, "cl"), 0) + 1
    print(f"\n{'='*94}\n(2) OWNER offset (node -> fighter slot)  — u64-scan over {len(nodes)} nodes\n{'='*94}")
    if not tally:
        print("   NO node field equalled any fighter base. Effects may all be ownerless globals in this")
        print("   sample (hit-sparks/super-flash). Retry with a PROJECTILE or an ASSIST on screen — those")
        print("   carry an owner. (owner=255 stays correct for genuinely ownerless nodes.)")
        return None, None
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0][0]))
    for (o, kind), c in ranked[:8]:
        star = " <<< WINNER" if ((o, kind), c) == ranked[0] else ""
        print(f"   H+0x{o:03x} (== fighter {kind}-base): matched on {c}/{len(nodes)} nodes{star}")
    (best_off, best_kind), _ = ranked[0]
    print(f"   CONFIRMED: owner is u64 @ H+0x{best_off:03x}, pointing at each fighter's "
          f"{'H-base (blk+0x3DB8+i*0x738)' if best_kind=='H' else 'cl-base (H+0x16C)'}.")
    return best_off, best_kind


def analyse_scale(nodes):
    """Winner = a float offset that VARIES across nodes and sits in a plausible scale range."""
    print(f"\n{'='*94}\n(3) SCALE offset  — per-node float variance over {len(nodes)} nodes\n{'='*94}")
    rows = []
    for o in SCALE_SCAN:
        vals = [f32b(nd["buf"], o) for nd in nodes]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        finite = [v for v in vals if abs(v) < 1e9 and v == v]        # drop NaN/inf
        if len(finite) < len(vals) or not finite:
            continue
        rng = hi - lo
        in_scale = sum(1 for v in finite if 0.02 <= abs(v) <= 16.0)
        rows.append((o, lo, hi, rng, in_scale, len(finite)))
    # rank: prefer offsets whose values are IN scale-range on most nodes AND vary
    def score(r):
        o, lo, hi, rng, in_scale, n = r
        return (in_scale / n if n else 0, 1 if rng > 1e-4 else 0, -o)
    rows.sort(key=score, reverse=True)
    print(f"   {'off':<8}{'min':>12}{'max':>12}{'range':>12}  in-scale/n   note")
    for o, lo, hi, rng, in_scale, n in rows[:14]:
        note = ""
        if o == H_SCALE_CUR:
            note = "  <- current (garbage) scale offset"
        if 0.02 <= abs(lo) <= 16.0 and rng > 1e-4:
            note += "  <<< plausible per-object scale"
        print(f"   H+0x{o:03x}{lo:>12.4f}{hi:>12.4f}{rng:>12.4f}   {in_scale}/{n}{note}")
    best = None
    for o, lo, hi, rng, in_scale, n in rows:
        if o == H_SCALE_CUR:
            continue
        if n and in_scale / n >= 0.75 and rng > 1e-4:
            best = o
            break
    if best is not None:
        print(f"   INFERRED: best per-object scale = H+0x{best:03x} "
              f"(in-range and varies; cross-check the paired +4 float for scale-Y).")
    else:
        print("   INFERRED: no float both varied AND stayed in [0.02,16] — the effect scale may be")
        print("   constant per effect-type (still valid), or supers weren't captured. Pick from the")
        print("   table the offset whose value matches the on-screen effect size; H_SCREEN scale")
        print("   semantics say a fighter's magnifier rests ~1.667(X)/2.143(Y).")
    return best


def emit_patch(gfx_off, owner_off, owner_kind, scale_off):
    print(f"\n{'='*94}\nreader.rs harvest_objs PATCH  (0.3.29 — paste over the current constants + body)\n{'='*94}")
    print("// ── constants (agentcheck/src/reader.rs) ──")
    if gfx_off is not None:
        print(f"const H_GFX1_PTR: usize = 0x{gfx_off:x};   // was 0x1a8 (value-test WRONG). "
              f"CONFIRMED live fxprobe.py: word lands in effect bank [B,B+0x10000).")
    if owner_off is not None:
        base_expr = "blk + BLK_H0_OFF + i*STRIDE" if owner_kind == "H" else "blk + BLK_H0_OFF + OBJ_BACK + i*STRIDE"
        print(f"const H_OWNER: usize = 0x{owner_off:x};    // was 0x9c/0xc4 (all 255). CONFIRMED live: "
              f"u64 == each fighter's {'H-base' if owner_kind=='H' else 'cl-base'}.")
    if scale_off is not None:
        print(f"const H_OBJ_SCALE_X: usize = 0x{scale_off:x};  // was 0x130 (constant 426.625). "
              f"INFERRED live: per-object float, +4 = scale-Y.")
    print("\n// ── harvest_objs body ──")
    if gfx_off is not None:
        print("//  read the gfx key as a u32 and mask low-28 (it is a DC-style 32-bit dir key, NOT a u64 ptr):")
        print(f"    let key = le32(&buf, H_GFX1_PTR) & 0x1FFF_FFFF;   // in [B, B+0x10000) for a true effect")
        print("    // (optionally resolve dirIdx = (key - DBASE)/0x10 with B=*(u32)(blk+0x6CE8), DBASE=*(u32)(B+8))")
    if owner_off is not None:
        base_expr = "blk + BLK_H0_OFF + i * STRIDE" if owner_kind == "H" else "blk + BLK_H0_OFF + OBJ_BACK + i * STRIDE"
        print(f"    let ow = rd_u64(&buf, H_OWNER) as usize;")
        print(f"    let owner = (0..6).find(|&i| ow == {base_expr}).map(|i| i as u8).unwrap_or(0xFF);")
    if scale_off is not None:
        print(f"    zx: (lef32(&buf, H_OBJ_SCALE_X).clamp(0.0, 15.999) * 4096.0) as u16,   // real per-obj scale")
    print(f"{'='*94}")


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    cap  = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    try:
        m = Mem()
    except OSError as e:
        sys.exit(f"OpenProcess failed ({e}). Is the game running? Run this terminal the same way "
                 f"you run verify.py / savestate.py (elevated if those need it). READ-ONLY.")
    blk = m.u64(BLK_PTR)
    if not blk:
        sys.exit("no match block (*(EXE+0xAC6EF0) == 0). Start a match first.")
    mode = m.read(blk + MODE_OFF, 5)
    modeb = mode[2] if mode else None
    fc = m.u32(blk + FC_OFF)
    print(f"blk 0x{blk:x}  frame {fc}  mode byte {modeb} "
          f"({'CHAR SELECT' if modeb == 1 else 'IN BATTLE' if modeb == 2 else '?'})   [READ-ONLY]")
    if modeb != 2:
        print("⚠ NOT IN BATTLE. Effects only exist during a fight. Start a match, then rerun.")

    # value-test bases (spec §3): B = *(u32)(blk+0x6CE8), DBASE = *(u32)(B+8)
    B = m.u32(blk + GFX_B_OFF)
    DBASE = m.u32(B + DBASE_OFF) if B else None
    print(f"value-test bases:  B=*(u32)(blk+0x{GFX_B_OFF:x})="
          f"{'0x%x' % B if B else 'NULL/unreadable'}   DBASE=*(u32)(B+8)="
          f"{'0x%x' % DBASE if DBASE is not None else 'unreadable'}")
    band = f"[0x{B:x},0x{B + BANK_WIN:x})" if B else f"[0x{BANK_LO:x},0x{BANK_HI:x}) (empirical fallback)"
    print(f"effect bank under test: {band}")

    print(f"\n>>> SAMPLING {secs:.0f}s — DO A SUPER / THROW A PROJECTILE NOW so effect nodes appear <<<")
    blk2, fighters, nodes = collect(m, secs, cap)
    if not nodes:
        print("\nno drawn non-fighter nodes seen. Effects only appear during supers/projectiles/"
              "hit-sparks — rerun and trigger one within the window.")
        return
    cats = {}
    for nd in nodes:
        cats[nd["cat"]] = cats.get(nd["cat"], 0) + 1
    print(f"\ncaptured {len(nodes)} distinct drawn non-fighter nodes. category histogram (effect=1..4): "
          f"{dict(sorted(cats.items()))}")
    # focus set: the task's effect gate (cat in 1..4). Keep all for owner/scale robustness but flag.
    eff = [nd for nd in nodes if 1 <= nd["cat"] <= 4]
    print(f"of those, {len(eff)} have cat in [1,4] (the effect gate). Analysis uses all captured nodes; "
          f"gfx/owner naturally only hit on genuine effects.")

    dump_nodes(nodes, blk, fighters, B)
    gfx_off   = analyse_gfx(nodes, B, DBASE)
    owner_off, owner_kind = analyse_owner(nodes, blk)
    scale_off = analyse_scale(nodes)

    print(f"\n{'#'*94}")
    g = f"H+0x{gfx_off:x}" if gfx_off is not None else "H+0x?? (retry: trigger a super/projectile)"
    o = f"H+0x{owner_off:x}" if owner_off is not None else "H+0x?? (retry: projectile/assist w/ owner)"
    s = f"H+0x{scale_off:x}" if scale_off is not None else "H+0x?? (see scale table; pick per-obj float)"
    print(f"FOUND:  gfx={g}   owner={o}   scale={s}")
    print(f"{'#'*94}")
    emit_patch(gfx_off, owner_off, owner_kind, scale_off)


if __name__ == "__main__":
    main()
