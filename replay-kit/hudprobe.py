#!/usr/bin/env python3
"""hudprobe.py — READ-ONLY live probe that CONFIRMS the NATIVE HUD render path (list 0x0B).

WHAT THIS CLOSES
    flycast-internals cross-check (CONFIRMED): the HUD is a SEPARATE LATE PASS. Its nodes hang off
    the list-head table (DC 0x8c287a5c), reached via list index 0x0B — they are NOT in the
    blk+0x2F4D0 draw-list slot arrays that fxprobe/verify.py walk. Life bars are OPAQUE gouraud
    parallelograms. flycast-internals flagged ONE thing to settle live: are the HUD-node geometry
    fields already SCREEN-SPACE (renderer uses them directly) or do they need a node->screen
    transform (bank0f loc_8c0f0408)? This probe answers that from a LIVE Steam match.

STATIC GROUND TRUTH (marvelous2 _marv_re, CONFIRMED):
  * bank04 loc_8c044ef0 = the list-head walker:
        r0 = *(loc_8c045004) = 0x8c287a5c          ; list-head TABLE base
        r14 = list_id ; shll2 r14                    ; *** 4-BYTE ENTRIES on DC ***
        head = *(u32)(0x8c287a5c + list_id*4)        ; list 0x0B -> *(0x8c287a88)
        loop: call *(node+0x10)(node) ; node = *(node+0x0C)   ; NEXT @ +0x0C, UPDATE-FN @ +0x10
  * bank03 loc_8c0301f6 = the per-HUD-element render fn. It SPECIAL-CASES list 0x0B
    (bank03:191 `cmp/eq 0x0B` and bank03:216 the {5,6,0x0B,0x0D} group) and reads bar geometry at
        node+0x34 (X), node+0x38 (Y), node+0x3C (X2)     [loc_8c030302 / loc_8c030340 lerp math]
    lerping each against a HUD reference struct at 0x8c26a518 (+0x18/+0x1C/+0x20). node+0xCC is a
    per-element FLAGS word whose bits (0x100/0x80/0x08/0x04/0x02/0x10) gate which components animate.
    node+0xC8 = the element's gfx/render-data pointer (textured elements: digits/portraits/pips).
  * The node-family shares the fighter/pool-node PREFIX, so the standard Steam node fields apply to
    textured HUD elements: sid @ H+0x188 (&0x7FFF), screen anchor @ H+0x124/+0x128, drawn @ H+0x170,
    category @ H+0x03.

DC -> STEAM PREDICTION (INFERRED via mvc2-dc-steam-block-map delta ladder; probe CONFIRMS live):
  * list-head table: DC 0x8c287a5c is in the "object pool + head-list growth" region (Δ=0x8C258910).
        Steam table  = blk + (0x8c287a5c - 0x8C258910) = blk + 0x2F14C
    On Steam pointers are 64-bit, so entries almost certainly widened to 8 bytes:
        Steam list-0x0B head  ~=  *(blk + 0x2F14C + 0x0B*8)  =  *(blk + 0x2F1A4)     (INFERRED)
    BUT the region is only 0x384 B on Steam (same as DC), so 4-byte entries (32-bit blk-relative or
    truncated handles) are ALSO possible. The probe DOES NOT hardcode: it scans the whole table
    window and interprets every slot as u64-abs / u32-abs / u32-(blk-relative), then keeps whichever
    interpretation walks a clean chain of real HUD nodes. The winning (offset, width) PINS the format.
  * node NEXT/UPDATE-FN widen too (DC +0x0C/+0x10). Probe tries NEXT in {0x08,0x0C,0x10} and
    UPDATE-FN in {0x10,0x18}, and validates the update-fn points at EXECUTABLE memory.
  * bar geometry: DC +0x34/+0x38/+0x3C  ->  Steam predicted +0x50/+0x54/+0x58  (fighter δ=0x1C).
  * lerp deltas:  Steam predicted +0x78/+0x7C/+0x80  (fighter +0x78/+0x7C are x/y vel — same family).
  * display value DC +0x21, team/side DC +0x20 / +0x02, owner ptr DC +0x18  -> Steam offsets NOT
    assumed (the HUD node is its OWN struct; its internal δ ladder is not guaranteed == the fighter's).
    We DUMP a raw H+0x00..0x1C0 window per node so these get PINNED OFFLINE.

CORRELATION (this is why you must TAKE DAMAGE): the probe reads the list-0x0B nodes AND the six
fighter healths at the SAME sampling instant (pass-phase note), so the bar-geometry float that
SHRINKS in lockstep with a draining health bar is identified directly from live data — that both
pins the real Steam geometry offset AND answers the screen-space question.

SAFETY: attaches with mvcmem.Mem = PROCESS_VM_READ only. It CANNOT write. Safe to run mid-match.
Every followed pointer is range/alignment/executability-checked and the walk is cycle-guarded and
length-capped, so a transiently-inconsistent list (mid engine update) can never wander into garbage.

usage:  python hudprobe.py [seconds] [max_nodes]     (defaults: 20s, 24 nodes)
        writes replay-kit/hudprobe_capture.json (raw node windows + health timeline) for offline pinning.
"""
import ctypes
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mvcmem import EXE, Mem, MBI, k32   # MBI + k32 exported by mvcmem; Mem is READ-ONLY

# ── CONFIRMED Steam constants (savestate.py / verify.py / fxprobe.py) ─────────────────────────────
BLK_PTR      = EXE + 0xAC6EF0          # blk = *(u64)(EXE+0xAC6EF0)                (CONFIRMED)
MODE_OFF     = 0x3CB8                  # byte[2]: 1=char-select 2=in-battle        (verify.py)
FC_OFF       = 0x3CC8                  # sim frame counter                          (savestate.py)
H0           = 0x3DB8                  # fighter slot 0 base                        (reader.rs/verify.py)
STRIDE       = 0x738                   # fighter stride                             (CONFIRMED)
HEALTH_OFF   = 0x578                   # fighter health u32, low16 0..144           (sync.rs cl+0x40c = H+0x16C+0x40c)
DRAW_LIST    = 0x2F4D0                 # main-pass draw-list slot arrays            (verify.py cmd_pool)
DRAW_COUNTS  = 0x324D0                 # u8 count per layer                         (verify.py)
DRAW_LAYER   = 0x300
N_LAYERS     = 16
MAX_PER_LAYER= 0x60

# ── HUD list-head table — PINNED FROM A LIVE blk DUMP 2026-08-29 (the DC delta was WRONG) ──────────
# The block-map head-list Δ predicted blk+0x2F14C = ALL ZEROS. Reading blk_dump.bin (blk=0x157e1000,
# in-battle) the REAL layout is TWO parallel per-list arrays, 8-byte stride, indexed by list-id:
#     HEAD_table = blk + 0x2ee58 + list*8      TAIL_table = blk + 0x2ede8 + list*8
# list 0x0B: head = *(blk+0x2eeb0) = cat-0x0B node (prev==0); walk NEXT(+0x08) -> tail *(blk+0x2ee40).
# Cross-checked (delta-free): the HUD nodes are exactly the object-pool nodes with +0x03 == 0x0B.
DC_TABLE     = 0x8c287a5c             # bank04 loc_8c045004 (DC head-table base)     (CONFIRMED DC)
HEAD_TABLE_OFF = 0x2ee58              # Steam HEAD_table base (list 0)               (CONFIRMED dump)
TAIL_TABLE_OFF = 0x2ede8              # Steam TAIL_table base (list 0)               (CONFIRMED dump)
LIST_ID      = 0x0B
HEAD_0B      = HEAD_TABLE_OFF + LIST_ID * 8       # = 0x2eeb0  (list-0x0B head slot)  (CONFIRMED dump)
TAIL_0B      = TAIL_TABLE_OFF + LIST_ID * 8       # = 0x2ee40  (list-0x0B tail slot)  (CONFIRMED dump)
# delta-free pool-scan (primary): object pool base/stride, filter category +0x03 == 0x0B
POOL_BASE    = 0x6dd8                 # block-map pool base                          (CONFIRMED live nodes)
POOL_STRIDE  = 0x280                  #                                             (CONFIRMED)
POOL_END     = 0x2edd8
# node link/field offsets — PINNED (HUD node is its own struct; the fighter +0x44 delta does NOT apply)
HN_CAT       = 0x03    # list/category byte (==0x0B)
HN_NEXT      = 0x08    # doubly-linked NEXT (u64, in-blk)
HN_PREV      = 0x10    # doubly-linked PREV
HN_UPDFN     = 0x18    # per-element update fn (module ptr)
HN_BARX      = 0x50    # bar/screen X  (DC +0x34)
HN_BARY      = 0x54    # bar/screen Y  (DC +0x38)
HN_BARX2     = 0x58    # bar/screen X2 (DC +0x3C)
HN_GFX       = 0xA0    # gfx/render-data ptr (DC +0xC8 analog) — per-node VA        (INFERRED-strong)
# legacy scan window (kept for the fallback auto-discovery only)
TABLE_OFF    = HEAD_TABLE_OFF
HEAD_PRED_8  = HEAD_0B
HEAD_PRED_4  = HEAD_0B
TABLE_SCAN_LO = TAIL_TABLE_OFF - 0x40
TABLE_SCAN_HI = DRAW_LIST

# node prefix (shared with fighter/pool node) — Steam CONFIRMED
H_CATEGORY   = 0x03
H_DRAWN      = 0x170
H_SCREEN_X   = 0x124
H_SCREEN_Y   = 0x128
H_SPRITE_ID  = 0x188
# node NEXT / UPDATE-FN candidates (DC +0x0C / +0x10)
NEXT_OFFS    = (0x08, 0x0C, 0x10)
UPD_OFFS     = (0x10, 0x18)
# HUD-node candidate fields — Steam predictions (INFERRED) + DC raw offsets (to pin offline)
GEOM_PRED    = (0x50, 0x54, 0x58)     # DC +0x34/+0x38/+0x3C  (bar X / Y / X2)
GEOM_DC      = (0x34, 0x38, 0x3C)
LERP_PRED    = (0x78, 0x7C, 0x80)     # DC +0x5C/+0x60/+0x64  (INFERRED)
DC_DISPLAY   = 0x21                   # display value (u8), DC
DC_TEAM      = 0x20                   # team/side (u8), DC
DC_SIDE2     = 0x02                   # secondary side byte, DC
DC_OWNER     = 0x18                   # owner ptr, DC
DC_FLAGS     = 0xCC                   # per-element flags word, DC (drives which geom bits lerp)
DC_GFX       = 0xC8                   # element gfx/render-data ptr, DC

NODE_SZ      = 0x1C0                  # the raw prefix the task asked to dump (H+0x00..0x1C0)
NODE_READ    = 0x200                  # read a touch more so 8-byte reads near 0x1C0 don't clip

# HUD band heuristic (640x480, life bars top-left / top-right)
P1_BAND_X = (10.0, 330.0);  P2_BAND_X = (310.0, 630.0);  BAR_BAND_Y = (0.0, 90.0)

CAPTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hudprobe_capture.json")

# page protection bits
PAGE_EXEC = 0x10 | 0x20 | 0x40 | 0x80   # EXECUTE / _READ / _READWRITE / _WRITECOPY
PAGE_NOACCESS, PAGE_GUARD, MEM_COMMIT = 0x01, 0x100, 0x1000


# ── buffer field readers ──────────────────────────────────────────────────────────────────────────
def u8b(b, o):  return b[o] if o < len(b) else None
def u16b(b, o): return struct.unpack_from("<H", b, o)[0] if o + 2 <= len(b) else None
def u32b(b, o): return struct.unpack_from("<I", b, o)[0] if o + 4 <= len(b) else None
def u64b(b, o): return struct.unpack_from("<Q", b, o)[0] if o + 8 <= len(b) else None
def f32b(b, o): return struct.unpack_from("<f", b, o)[0] if o + 4 <= len(b) else None


def region_protect(m, addr):
    """(state, protect) for the page containing addr, via VirtualQueryEx (read-only query)."""
    mbi = MBI()
    r = k32.VirtualQueryEx(m.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
    if not r:
        return None, None
    return mbi.State, mbi.Protect


def is_exec(m, addr):
    if not addr:
        return False
    st, pr = region_protect(m, addr)
    return st == MEM_COMMIT and pr is not None and (pr & PAGE_EXEC) and not (pr & PAGE_GUARD)


def is_committed(m, addr):
    if not addr:
        return False
    st, pr = region_protect(m, addr)
    return st == MEM_COMMIT and pr not in (None, PAGE_NOACCESS) and not (pr & PAGE_GUARD)


def node_plausible(blk, p):
    """A HUD node lives inside blk (the pool/head-list region), 4-aligned."""
    return p is not None and (p & 3) == 0 and (blk + 0x1000) <= p < (blk + 0x60000)


# ── the linked-list walk (self-discovering: format + next-offset unknown) ───────────────────────────
def candidate_ptrs_from_slot(blk, buf, off):
    """Interpret a table/link slot 3 ways; yield (kind, resolved_ptr)."""
    out = []
    v64 = u64b(buf, off)
    if v64 is not None:
        out.append(("u64", v64))
    v32 = u32b(buf, off)
    if v32 is not None:
        out.append(("u32abs", v32))
        out.append(("u32rel", (blk + v32) & 0xFFFFFFFFFFFFFFFF))
    return out


def walk(m, blk, head, next_off, next_kind, cap=64):
    """Follow the chain from head using (next_off,next_kind); return list of (addr,buf)."""
    nodes, seen, p = [], set(), head
    while node_plausible(blk, p) and p not in seen and len(nodes) < cap:
        buf = m.read(p, NODE_READ)
        if not buf or len(buf) < NODE_SZ:
            break
        seen.add(p)
        nodes.append((p, buf))
        cands = candidate_ptrs_from_slot(blk, buf, next_off)
        nxt = next((pt for (k, pt) in cands if k == next_kind), 0)
        if nxt == 0:
            break                       # clean null-terminated tail
        p = nxt
    return nodes


def score_chain(m, blk, nodes, upd_off):
    """How many nodes have an executable update-fn at upd_off (the strongest 'real node' signal)."""
    if not nodes:
        return 0
    good = 0
    for _addr, buf in nodes:
        if is_exec(m, u64b(buf, upd_off)):
            good += 1
    return good


def discover_hud_poolscan(m, blk):
    """PRIMARY, delta-free: the list-0x0B HUD nodes are the object-pool nodes whose category byte
       +0x03 == 0x0B with a module update-fn. Returns a `best`-shaped tuple or None.
       (PINNED from blk_dump.bin 2026-08-29; independent of the mispredicted head-list Δ.)"""
    nodes = []
    for off in range(POOL_BASE, POOL_END, POOL_STRIDE):
        a = blk + off
        buf = m.read(a, NODE_READ)
        if not buf or len(buf) < NODE_SZ:
            continue
        if buf[HN_CAT] != 0x0B:
            continue
        upd = u64b(buf, HN_UPDFN)
        if upd is None or not is_exec(m, upd):
            continue
        nodes.append((a, buf))
    if len(nodes) < 2:
        return None
    head_tab = m.u64(blk + HEAD_0B)                       # cross-check the pinned head-table slot
    head = next((a for a, b in nodes if u64b(b, HN_PREV) == 0), nodes[0][0])
    meta = dict(table_slot=blk + HEAD_0B, table_off=HEAD_0B, slot_kind="u64",
                head=head_tab if any(a == head_tab for a, _ in nodes) else head,
                next_off=HN_NEXT, next_kind="u64", upd_off=HN_UPDFN, exec_hits=len(nodes))
    return (len(nodes), len(nodes), meta, nodes)


def discover_list(m, blk):
    """Scan the table window, try every (slot, kind, next_off, next_kind, upd_off); return best walk."""
    # PRIMARY: pinned pool-scan (the head-list Δ was wrong; blk+0x2f14c reads zeros).
    ps = discover_hud_poolscan(m, blk)
    if ps is not None:
        return b"", ps
    win = m.read(blk + TABLE_SCAN_LO, TABLE_SCAN_HI - TABLE_SCAN_LO)
    best = None   # (score, chain_len, meta, nodes)
    if not win:
        return None, None
    # prioritise the predicted slots first (for a clean 'CONFIRMED prediction' message), then all slots
    pred_offs = [HEAD_PRED_8 - TABLE_SCAN_LO, HEAD_PRED_4 - TABLE_SCAN_LO]
    all_offs = list(range(0, len(win) - 8, 4))
    order = pred_offs + [o for o in all_offs if o not in pred_offs]
    for so in order:
        if so < 0 or so + 8 > len(win):
            continue
        for (kind, head) in candidate_ptrs_from_slot(blk, win, so):
            if not node_plausible(blk, head):
                continue
            for noff in NEXT_OFFS:
                # infer next_kind from the head node itself (only kinds that resolve in-range)
                first = m.read(head, NODE_READ)
                if not first:
                    continue
                for (nkind, _pt) in candidate_ptrs_from_slot(blk, first, noff):
                    nodes = walk(m, blk, head, noff, nkind)
                    if len(nodes) < 2:
                        continue
                    for uoff in UPD_OFFS:
                        sc = score_chain(m, blk, nodes, uoff)
                        if sc < max(2, len(nodes) // 2):
                            continue
                        table_slot = blk + TABLE_SCAN_LO + so
                        meta = dict(table_slot=table_slot, table_off=TABLE_SCAN_LO + so,
                                    slot_kind=kind, head=head, next_off=noff, next_kind=nkind,
                                    upd_off=uoff, exec_hits=sc)
                        cand = (sc, len(nodes), meta, nodes)
                        if best is None or (sc, len(nodes)) > (best[0], best[1]):
                            best = cand
    if best is None:
        return win, None
    return win, best


# ── draw-list overlap check (prove HUD nodes are NOT in the blk+0x2F4D0 slot arrays) ────────────────
def drawlist_handles(m, blk):
    handles = set()
    counts = m.read(blk + DRAW_COUNTS, N_LAYERS)
    table = m.read(blk + DRAW_LIST, N_LAYERS * DRAW_LAYER)
    if not counts or not table:
        return handles
    for L in range(N_LAYERS):
        for i in range(min(counts[L], MAX_PER_LAYER)):
            h = struct.unpack_from("<Q", table, L * DRAW_LAYER + i * 8)[0]
            if h:
                handles.add(h)
    return handles


# ── per-node classification + dump ─────────────────────────────────────────────────────────────────
def classify(buf):
    sid = (u16b(buf, H_SPRITE_ID) or 0) & 0x7FFF
    sx, sy = f32b(buf, H_SCREEN_X), f32b(buf, H_SCREEN_Y)
    textured = sid != 0 and sx is not None and -64.0 <= sx <= 704.0 and -64.0 <= sy <= 544.0
    # bar signal: a plausible screen-range float at the predicted geometry offsets
    geom = [f32b(buf, o) for o in GEOM_PRED]
    bar = any(g is not None and 0.0 <= g <= 640.0 for g in geom)
    if textured and not bar:
        return "TEXTURED"
    if bar and not textured:
        return "BAR"
    if textured and bar:
        return "BAR+TEX"
    return "?"


def in_band(x, y):
    if x is None or y is None:
        return False
    if not (BAR_BAND_Y[0] <= y <= BAR_BAND_Y[1]):
        return False
    return (P1_BAND_X[0] <= x <= P1_BAND_X[1]) or (P2_BAND_X[0] <= x <= P2_BAND_X[1])


def dump_node(idx, addr, blk, buf, in_drawlist):
    kind = classify(buf)
    print(f"\n-- HUD node #{idx}  0x{addr:x}  (blk+0x{addr-blk:x})  class={kind}  "
          f"in-drawlist(blk+0x2F4D0)? {'YES <<< OVERLAP!' if in_drawlist else 'no (separate late pass, as expected)'}")
    print(f"   prefix: cat(H+0x03)={u8b(buf,H_CATEGORY)}  drawn(H+0x170)={u8b(buf,H_DRAWN)}  "
          f"sid(H+0x188)={(u16b(buf,H_SPRITE_ID) or 0)&0x7FFF}  "
          f"screen(H+0x124/128)=({f32b(buf,H_SCREEN_X):.1f},{f32b(buf,H_SCREEN_Y):.1f})")
    # geometry — predicted Steam AND DC-raw, side by side (offline pinning uses both)
    gp = [f32b(buf, o) for o in GEOM_PRED]
    gd = [f32b(buf, o) for o in GEOM_DC]
    lp = [f32b(buf, o) for o in LERP_PRED]
    print(f"   GEOM  pred +0x50/54/58 = ({gp[0]:.2f},{gp[1]:.2f},{gp[2]:.2f})   "
          f"DC-raw +0x34/38/3C = ({gd[0]:.2f},{gd[1]:.2f},{gd[2]:.2f})")
    print(f"   LERP  pred +0x78/7C/80 = ({lp[0]:.3f},{lp[1]:.3f},{lp[2]:.3f})")
    print(f"   DC-offs raw: display+0x21={u8b(buf,DC_DISPLAY)}  team+0x20={u8b(buf,DC_TEAM)}  "
          f"side+0x02={u8b(buf,DC_SIDE2)}  owner+0x18=0x{u64b(buf,DC_OWNER):x}  "
          f"flags+0xCC=0x{u32b(buf,DC_FLAGS):08x}  gfx+0xC8=0x{u64b(buf,DC_GFX):x}")
    # screen-space verdict on the predicted geometry
    verdict = "IN HUD BAND -> SCREEN-SPACE" if in_band(gp[0], gp[1]) else "NOT in HUD band"
    print(f"   geom-vs-screen (pred +0x50/54 as x/y): {verdict}")
    # self-describing raw window
    print(f"   raw H+0x00..0x1C0:")
    for row in range(0, NODE_SZ, 32):
        chunk = buf[row:row + 32]
        print(f"      +0x{row:03x}  " + " ".join(f"{c:02x}" for c in chunk))


# ── geometry-vs-screen validation: correlate bar-geometry floats with draining health ──────────────
def find_moving_geom(samples, node_addr):
    """Across time samples, find node floats in [0,640] that changed the most (the fill endpoint)."""
    series = {}          # off -> list of values
    for s in samples:
        buf = s["nodes"].get(node_addr)
        if not buf:
            continue
        for o in range(0x40, 0x90, 4):
            v = f32b(buf, o)
            if v is not None and -32.0 <= v <= 672.0:
                series.setdefault(o, []).append(v)
    moved = []
    for o, vals in series.items():
        if len(vals) >= 3:
            rng = max(vals) - min(vals)
            if rng > 0.5:
                moved.append((rng, o, min(vals), max(vals)))
    moved.sort(reverse=True)
    return moved


def main():
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    cap  = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    try:
        m = Mem()
    except OSError as e:
        sys.exit(f"OpenProcess failed ({e}). Run this terminal the same way you run "
                 f"verify.py / fxprobe.py (elevated if those need it). READ-ONLY.")
    blk = m.u64(BLK_PTR)
    if not blk:
        sys.exit("no match block (*(EXE+0xAC6EF0)==0). Start a match first.")
    mode = m.read(blk + MODE_OFF, 5)
    modeb = mode[2] if mode else None
    fc = m.u32(blk + FC_OFF)
    print(f"blk 0x{blk:x}  frame {fc}  mode {modeb} "
          f"({'CHAR SELECT' if modeb==1 else 'IN BATTLE' if modeb==2 else '?'})   [READ-ONLY]")
    if modeb != 2:
        print("⚠ NOT IN BATTLE — the HUD list only exists during a fight. Start a match, then rerun.")
    print(f"DC table 0x{DC_TABLE:x} (list-0x0B head *(0x{DC_HEAD_0B:x}))  ->  Steam predicted "
          f"table blk+0x{TABLE_OFF:x}, head blk+0x{HEAD_PRED_8:x}(8B)/blk+0x{HEAD_PRED_4:x}(4B)  [INFERRED]")

    # ── STEP 1 + 3(head): discover + walk the list-0x0B linked list ──────────────────────────────
    print(f"\n{'='*94}\nSTEP 1  resolve list-head table + walk list 0x0B (auto-discovering format)\n{'='*94}")
    win, best = discover_list(m, blk)
    if not best:
        print("could NOT find a clean list-0x0B chain in the table window. Either not in battle, or the")
        print("predicted table region (blk+0x%x..blk+0x%x) is off. Raw table window head:" %
              (TABLE_SCAN_LO, TABLE_SCAN_HI))
        if win:
            for row in range(0, min(0x80, len(win)), 16):
                print(f"   blk+0x{TABLE_SCAN_LO+row:x}  " + " ".join(f"{c:02x}" for c in win[row:row+16]))
        return
    sc, n, meta, nodes = best
    pred = "== PREDICTED" if meta["table_off"] in (HEAD_PRED_8, HEAD_PRED_4) else "(not the predicted slot)"
    print(f"CONFIRMED list-0x0B head:")
    print(f"   table slot   : blk+0x{meta['table_off']:x} (abs 0x{meta['table_slot']:x})  {pred}")
    print(f"   slot format  : {meta['slot_kind']}   (DC was u32*4-stride; this pins the Steam width)")
    print(f"   head node    : 0x{meta['head']:x} (blk+0x{meta['head']-blk:x})")
    print(f"   NEXT offset  : node+0x{meta['next_off']:x} as {meta['next_kind']}   (DC was +0x0C)")
    print(f"   UPDATE-FN    : node+0x{meta['upd_off']:x} -> executable on {meta['exec_hits']}/{n} nodes  (DC was +0x10)")
    print(f"   chain length : {n} nodes")

    # ── STEP 3: overlap check vs the main-pass draw list ─────────────────────────────────────────
    dl = drawlist_handles(m, blk)
    node_addrs = [a for a, _ in nodes]
    overlap = [a for a in node_addrs if a in dl]
    print(f"\n{'='*94}\nSTEP 3  overlap check vs blk+0x2F4D0 draw-list slot arrays\n{'='*94}")
    print(f"draw-list distinct handles this frame: {len(dl)}   HUD nodes also in it: "
          f"{len(overlap)} {'<<< UNEXPECTED (not a separate pass!)' if overlap else '-> CONFIRMED separate late pass'}")

    # ── STEP 2: per-node dump ────────────────────────────────────────────────────────────────────
    print(f"\n{'='*94}\nSTEP 2  per-node field dump (first {min(cap,n)} of {n})\n{'='*94}")
    for i, (addr, buf) in enumerate(nodes[:cap]):
        dump_node(i, addr, blk, buf, addr in dl)

    # ── STEP 4 + 5: same-instant HUD + health timeline; correlate drain with geometry ────────────
    print(f"\n{'='*94}\nSTEP 4/5  SAME-INSTANT HUD-geom + fighter-health timeline "
          f"({secs:.0f}s — TAKE DAMAGE / BUILD METER NOW)\n{'='*94}")
    samples = []
    t0 = time.time()
    while time.time() - t0 < secs:
        # snapshot both structures at the SAME instant (pass-phase note: bars lerp)
        healths = []
        for i in range(6):
            h = m.u32(blk + H0 + i * STRIDE + HEALTH_OFF)
            healths.append((h & 0xFFFF) if h is not None else None)
        snap = {}
        for addr in node_addrs:
            b = m.read(addr, NODE_READ)
            if b:
                snap[addr] = b
        samples.append(dict(t=time.time() - t0, frame=m.u32(blk + FC_OFF),
                            health=healths, nodes=snap))
        time.sleep(0.03)
    print(f"captured {len(samples)} same-instant samples.")
    hs = [s["health"] for s in samples]
    if hs:
        first, last = hs[0], hs[-1]
        print(f"fighter health start->end (slots 0..5): "
              f"{[f'{a}->{b}' for a, b in zip(first, last)]}")
        drained = [i for i in range(6) if first[i] and last[i] is not None and first[i] - last[i] > 2]
        print(f"slots that DRAINED: {drained if drained else 'NONE — you did not take/deal enough damage; rerun and get hit'}")

    print(f"\n-- per-node: which float MOVED, and does its range read as SCREEN PIXELS?")
    for addr in node_addrs:
        moved = find_moving_geom(samples, addr)
        if not moved:
            continue
        rng, off, lo, hi = moved[0]
        pred_hit = " == predicted +0x50" if off == 0x50 else (" == predicted +0x54" if off == 0x54 else "")
        band = "screen-pixel range" if (0.0 <= lo and hi <= 640.0 and rng > 1.0) else "NOT a pixel range"
        print(f"   node 0x{addr:x}: biggest mover = node+0x{off:x}{pred_hit}  "
              f"range [{lo:.1f}..{hi:.1f}] Δ={rng:.1f}  -> {band}")
    print(f"\nVERDICT GUIDE:")
    print(f"  * a mover at +0x50/+0x54 whose range is 0..640 and shrinks with a draining health slot")
    print(f"    => HUD-node geometry IS screen-space; the renderer can consume +0x50/54/58 directly.")
    print(f"  * a mover in 0..1 (normalised) or in world units, or none in a pixel range")
    print(f"    => a node->screen transform is needed (bank0f loc_8c0f0408, referenced from bank03).")

    # ── raw capture file for offline pinning ─────────────────────────────────────────────────────
    out = dict(blk=hex(blk), frame=fc, mode=modeb,
               discovered=dict(table_slot=hex(meta["table_slot"]), table_off=hex(meta["table_off"]),
                               slot_kind=meta["slot_kind"], head=hex(meta["head"]),
                               next_off=meta["next_off"], next_kind=meta["next_kind"],
                               upd_off=meta["upd_off"], chain_len=n),
               dc_reference=dict(table=hex(DC_TABLE), head_0B=hex(DC_HEAD_0B),
                                 geom="node+0x34/0x38/0x3C", next="node+0x0C", updfn="node+0x10"),
               table_window=dict(base=hex(blk + TABLE_SCAN_LO),
                                 bytes=win.hex() if win else None),
               nodes=[dict(addr=hex(a), blk_off=hex(a - blk), raw=b[:NODE_SZ].hex())
                      for a, b in nodes],
               timeline=[dict(t=round(s["t"], 3), frame=s["frame"], health=s["health"],
                              nodes={hex(a): b[:NODE_SZ].hex() for a, b in s["nodes"].items()})
                         for s in samples])
    with open(CAPTURE_PATH, "w") as f:
        json.dump(out, f)
    print(f"\nRAW CAPTURE written: {CAPTURE_PATH}")
    print(f"  (table window + per-node H+0x00..0x1C0 + same-instant health timeline — pin the Steam")
    print(f"   HUD offsets offline against this, then fold into the 0.3.31 reader capture spec.)")


if __name__ == "__main__":
    main()
