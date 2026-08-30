#!/usr/bin/env python3
"""hud_bankdump.py — READ-ONLY one-time dump of the LIVE list-0x0B HUD sprite bank.

WHY THIS EXISTS (retargeted 2026-08-29 per the sprite-render correction)
    * The tape's objs owner=0 / sid&0x8000 / cat1-4 nodes are the layer-0 EFFECT pool, NOT the HUD
      (proven by position scatter: each sel appears at 200-390 distinct (sx,sy), 73% off-screen).
    * The REAL HUD is the list-0x0B LATE PASS that hudprobe.py walks live. It is NOT in the
      blk+0x2F4D0 draw-list, so it is NOT in any tape's readAllDrawn capture.
    * The shared UI GFX1 bank (frame/bars/timer/meters/portraits/names) is CONFIRMED not offline
      (sprite-render scanned ~700 Dev Files; handle 5888 -> 0x0C001700 = live NAOMI-RAM mirror).
    => Both the HUD element SET and their sprite bank exist ONLY in live memory. This captures both
       in one read-only pass so every tape renders the full HUD offline forever.

WHAT IT DOES
    1. Reuses hudprobe.discover_list() to auto-find + walk the list-0x0B HUD node chain.
    2. For each node: pins the gfx/render-data pointer field (DC node+0xC8 -> Steam offset AUTO-
       DISCOVERED from the raw node window; every candidate is translated + validated, the winner
       is reported so it can be folded into the reader). Also records node+0xCC flags (DC) and the
       shared prefix fields (sid H+0x188, screen H+0x124/128, cat H+0x03, Dat_GFX1 H+0x1A0).
    3. Follows that pointer through the arena mirror and DUMPS the referenced regions: the element
       DESCRIPTOR, its CELL RECORDS, and the decoded SPRITE SHEET pixels. Chases nested NAOMI/VA
       pointers to depth 2, dedup by resolved address, each region hard-bounded to its committed page
       run and a size cap.
    4. Writes an offline asset bundle: hud_bank_dump.json (catalog + per-node fields + raw node
       windows) and hud_bank/<addr>.bin (raw region blobs). Assemble the UI atlas offline with the
       CONFIRMED GFX1 decode (rip_hud_quads.decode_tex: twiddle + PAL4/PAL8 + ARGB4444).

ADDRESS TRANSLATION (CONFIRMED)
    arena = *(u64)(EXE + 0xAC6D40)                                   (bootdet.py:43, restore_blk.py)
    NAOMI/DC addr  N in [0x0C000000, 0x10000000)  mirrors to:
        steam_VA = arena + 0x8400000 + (N - 0x0C000000)             (HANDOVER-2026-08-26-REPLAY.md:156
                                                                     "the asset image IS NAOMI main RAM")
    A field may instead already hold a real committed 64-bit VA; both are handled + tagged.

STATIC GROUND TRUTH (marvelous2 _marv_re, CONFIRMED)
    * bank03 loc_8c0301f6 (per-HUD-element render):
        gfx = *(node + 0xC8);  if gfx != 0 -> textured render bank11.loc_8c1201E0(gfx)
                               else        -> procedural bar   bank12.loc_8c121100
        node+0xCC = per-element FLAGS (bit 0x4000 gated sub-draw; category 0x0B special lerp).
    * bank03 loc_8c033e90 (GFX1 load-time packer) resolves a cell the same way the body walker does:
        cell = GFX1 + *(u32)(GFX1 + sel*4);  cell = [u16 count][per-part: u8 w/8, u8 h/8, ...],
        parts are LZSS-decoded (loc_8c03552a) to twiddled PAL4/PAL8 or ARGB4444. Use this as the
        offline decode template for the dumped cell records + sheet.

SAFETY: PROCESS_VM_READ only (mvcmem.Mem). It CANNOT write. Every followed pointer is
    translated, committed-checked, and length-capped; the walk is cycle-guarded. Safe mid-match.

usage:  python hud_bankdump.py [max_nodes] [--maxregion BYTES]
        defaults: 48 nodes, 512 KiB per region. Writes replay-kit/hud_bank_dump.json + hud_bank/.
"""
import ctypes
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from mvcmem import EXE, Mem, MBI, k32
import hudprobe as HP   # reuse the CONFIRMED list-0x0B discovery + safety helpers

# ── arena mirror (CONFIRMED) ────────────────────────────────────────────────────────────────────
ARENA_PTR    = EXE + 0xAC6D40          # arena = *(u64)(EXE+0xAC6D40)              (bootdet.py:43)
ARENA_SIZE   = 256 * 1024 * 1024
ASSET_OFF    = 0x8400000               # NAOMI-RAM mirror offset within the arena  (HANDOVER:156)
NAOMI_LO, NAOMI_HI = 0x0C000000, 0x10000000

# ── HUD list-0x0B PINNED from the live blk dump 2026-08-29 (blk=0x157e1000, frame 13368) ──────────
# The DC->Steam head-list delta was wrong (predicted table blk+0x2f14c = ALL ZEROS). The REAL layout,
# read straight from the dump, is TWO parallel per-list arrays (8-byte stride, indexed by list-id):
#     HEAD_table = blk + 0x2ee58 + list*8      TAIL_table = blk + 0x2ede8 + list*8
# list 0x0B: head = *(blk+0x2eeb0) = a cat-0x0B pool node with prev==0; walk NEXT(+0x08) to the tail.
# Equivalent delta-free discovery (used as primary here): scan the object pool for category +0x03==0x0B.
POOL_BASE    = 0x6dd8                   # object-pool base (block-map; CONFIRMED: nodes at this stride)
POOL_STRIDE  = 0x280                    # CONFIRMED live (139-handle GCD)
POOL_END     = 0x2edd8                  # pool end (256 * 0x280 from base)
HEAD_0B      = 0x2eeb0                  # *(blk+0x2eeb0) = list-0x0B head node    (CONFIRMED dump)
TAIL_0B      = 0x2ee40                  # *(blk+0x2ee40) = list-0x0B tail node    (CONFIRMED dump)
# node fields — PINNED from the dump (HUD node is its OWN struct; fighter +0x44 delta does NOT apply)
H_CATEGORY   = 0x03                     # list/category byte == 0x0B for HUD      (CONFIRMED)
H_NEXT       = 0x08                     # doubly-linked NEXT (u64, in-blk)        (CONFIRMED)
H_PREV       = 0x10                     # doubly-linked PREV (u64, in-blk)        (CONFIRMED)
H_UPDATE_FN  = 0x18                     # per-element update fn (module ptr)      (CONFIRMED)
H_BAR_X      = 0x50                     # bar/screen X   (DC +0x34)               (CONFIRMED float)
H_BAR_Y      = 0x54                     # bar/screen Y   (DC +0x38)               (CONFIRMED float)
H_BAR_X2     = 0x58                     # bar/screen X2  (DC +0x3C)               (CONFIRMED float)
H_HOME_X     = 0xD8                     # home/reference copy of X/Y (lerp anchor)(CONFIRMED float)
H_GFX        = 0xA0                     # gfx/render-data ptr (DC +0xC8 analog)   (INFERRED-strong;
                                        #   only render-data-shaped ptr; per-node VA into 0x12c7xxxx)
DC_GFX       = 0xC8                     # DC reference offset for proximity rank (Steam real = 0xA0)
GFX_SCAN_LO, GFX_SCAN_HI = 0x40, 0x160 # fallback window to scan for the gfx-ptr field
NODE_READ    = HP.NODE_READ
NODE_SZ      = HP.NODE_SZ

OUT_JSON   = os.path.join(HERE, "hud_bank_dump.json")
OUT_BINDIR = os.path.join(HERE, "hud_bank")
MEM_COMMIT = 0x1000
PAGE_NOACCESS, PAGE_GUARD = 0x01, 0x100


# ── translation + bounded region reader ───────────────────────────────────────────────────────────
def region_end(m, addr):
    """End VA of the committed, readable page-run containing addr (0 if not readable)."""
    mbi = MBI()
    a = addr
    end = addr
    while True:
        r = k32.VirtualQueryEx(m.h, ctypes.c_void_p(a), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if not r:
            break
        base = mbi.BaseAddress or 0
        size = mbi.RegionSize or 0
        if size == 0:
            break
        if mbi.State != MEM_COMMIT or mbi.Protect in (0, PAGE_NOACCESS) or (mbi.Protect & PAGE_GUARD):
            break
        end = base + size
        a = end
    return end if end > addr else 0


def resolve(m, arena, v):
    """Map a raw field value to a (kind, steam_VA) we can read, or (None, None).
       kind: 'naomi' (mirrored asset addr) or 'va' (already a real committed VA)."""
    if v is None or v == 0:
        return None, None
    if NAOMI_LO <= v < NAOMI_HI and arena:
        va = arena + ASSET_OFF + (v - NAOMI_LO)
        if region_end(m, va) > va:
            return "naomi", va
        return None, None
    # real VA? (module, arena, or heap) — must be committed+readable and sanely aligned
    if (v & 3) == 0 and 0x10000 <= v < 0x7FFFFFFFFFFF and region_end(m, v) > v:
        return "va", v
    return None, None


def read_region(m, va, cap):
    """Read up to cap bytes from va, clamped to its committed page-run."""
    end = region_end(m, va)
    if end <= va:
        return b""
    n = min(cap, end - va)
    out = bytearray()
    off = 0
    while off < n:
        chunk = m.read(va + off, min(0x10000, n - off))
        if not chunk:
            break
        out += chunk
        off += len(chunk)
    return bytes(out)


# ── gfx-pointer field discovery on the live node ──────────────────────────────────────────────────
def looks_like_renderdata(m, arena, va):
    """Loose: the region opens with a small count/dim OR carries a resolvable nested pointer."""
    hdr = m.read(va, 0x40)
    if not hdr or len(hdr) < 0x10:
        return 0
    score = 0
    c0 = struct.unpack_from("<H", hdr, 0)[0]          # GFX1 cell opens with a u16 part-count
    if 0 < c0 <= 256:
        score += 1
    w = struct.unpack_from("<H", hdr, 0)[0]           # or a small dim near the front
    if 4 <= w <= 1024:
        score += 1
    for o in range(0, 0x40, 4):
        v = struct.unpack_from("<I", hdr, o)[0]
        k, _ = resolve(m, arena, v)
        if k:
            score += 1
            break
    for o in range(0, 0x38, 8):
        v = struct.unpack_from("<Q", hdr, o)[0]
        k, _ = resolve(m, arena, v)
        if k:
            score += 1
            break
    return score


def discover_gfx_field(m, arena, buf):
    """Scan the node window for the field that holds the gfx/render-data pointer.
       Returns list of (offset, width, kind, raw, resolved_va, score) best-first."""
    cands = []
    for off in range(GFX_SCAN_LO, GFX_SCAN_HI, 4):
        for width, raw in ((4, HP.u32b(buf, off)), (8, HP.u64b(buf, off))):
            if raw is None:
                continue
            kind, va = resolve(m, arena, raw)
            if not kind:
                continue
            sc = looks_like_renderdata(m, arena, va)
            # prefer proximity to the DC gfx offset (0xC8) and a real render-data signature
            prox = -abs(off - DC_GFX)
            cands.append((sc, prox, off, width, kind, raw, va))
    cands.sort(reverse=True)
    seen = set()
    out = []
    for sc, prox, off, width, kind, raw, va in cands:
        if va in seen:
            continue
        seen.add(va)
        out.append(dict(off=off, width=width, kind=kind, raw=raw, va=va, score=sc))
    return out


# ── the dump ──────────────────────────────────────────────────────────────────────────────────────
def dump_chain(m, arena, root_va, cap, catalog, blobs, depth=2):
    """DFS the descriptor -> cell/sheet, translating nested NAOMI/VA pointers, bounded + deduped."""
    stack = [(root_va, 0)]
    while stack:
        va, d = stack.pop()
        if va in catalog or d > depth:
            continue
        data = read_region(m, va, cap)
        if not data:
            continue
        rel = None
        if arena and arena <= va < arena + ARENA_SIZE:
            rel = va - arena
        catalog[va] = dict(va=hex(va), len=len(data), depth=d,
                           arena_off=hex(rel) if rel is not None else None,
                           naomi=hex(NAOMI_LO + (rel - ASSET_OFF)) if (rel is not None and rel >= ASSET_OFF) else None)
        blobs[va] = data
        if d < depth:
            # chase nested pointers found in the first 0x100 bytes of the descriptor
            head = data[:0x100]
            for o in range(0, len(head) - 8, 4):
                for raw in (struct.unpack_from("<I", head, o)[0], struct.unpack_from("<Q", head, o)[0]):
                    k, nva = resolve(m, arena, raw)
                    if k and nva not in catalog:
                        stack.append((nva, d + 1))


def discover_hud(m, blk):
    """Locate the list-0x0B HUD chain. Primary = pool-scan (delta-free): pool nodes whose
       category byte +0x03 == 0x0B with a module update-fn. Cross-checked against the pinned
       head-table slot *(blk+0x2eeb0). Returns (head_addr, [(addr,buf), ...])."""
    pool = []
    for off in range(POOL_BASE, POOL_END, POOL_STRIDE):
        a = blk + off
        b = m.read(a, NODE_READ)
        if not b or len(b) < NODE_SZ:
            continue
        if b[H_CATEGORY] != 0x0B:
            continue
        upd = HP.u64b(b, H_UPDATE_FN)
        if upd is None or not (0x140000000 <= upd < 0x141000000):
            continue
        pool.append((a, b))
    head_tab = m.u64(blk + HEAD_0B)          # cross-check the pinned head-table slot
    return head_tab, pool


def main():
    cap_nodes = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 48
    maxregion = 512 * 1024
    if "--maxregion" in sys.argv:
        maxregion = int(sys.argv[sys.argv.index("--maxregion") + 1])

    try:
        m = Mem()
    except OSError as e:
        sys.exit(f"OpenProcess failed ({e}). Run this terminal the same way you run hudprobe.py "
                 f"(elevated if that needs it). READ-ONLY.")
    blk = m.u64(HP.BLK_PTR)
    arena = m.u64(ARENA_PTR)
    if not blk:
        sys.exit("no match block (*(EXE+0xAC6EF0)==0). Start a TRAINING match first.")
    if not arena:
        sys.exit("no arena (*(EXE+0xAC6D40)==0). Start the game / a match first.")
    mode = m.read(blk + HP.MODE_OFF, 5)
    modeb = mode[2] if mode else None
    print(f"blk 0x{blk:x}  arena 0x{arena:x}  asset-mirror 0x{arena + ASSET_OFF:x}  "
          f"mode {modeb} ({'IN BATTLE' if modeb == 2 else 'NOT battle'})   [READ-ONLY]")
    if modeb != 2:
        print("⚠ NOT IN BATTLE — the list-0x0B HUD only exists during a fight. Start a training match, rerun.")

    # ── locate list-0x0B via delta-free pool-scan (cat +0x03 == 0x0B) ─────────────────────────────
    head_tab, nodes = discover_hud(m, blk)
    n = len(nodes)
    if n == 0:
        sys.exit("no cat-0x0B HUD nodes in the pool. Are you in a live battle with the HUD on screen? "
                 "(If the pool base/stride moved on a new build, re-pin from a fresh blk dump.)")
    ht_ok = (head_tab and any(a == head_tab for a, _ in nodes))
    print(f"list-0x0B: {n} HUD nodes (pool-scan cat+0x03==0x0B); "
          f"head-table *(blk+0x{HEAD_0B:x}) = 0x{head_tab:x} {'[in chain ✓]' if ht_ok else '[MISMATCH — verify]'}")

    catalog, blobs = {}, {}
    node_records = []
    for i, (addr, buf) in enumerate(nodes[:cap_nodes]):
        cat = HP.u8b(buf, H_CATEGORY)
        bx, by, bx2 = HP.f32b(buf, H_BAR_X), HP.f32b(buf, H_BAR_Y), HP.f32b(buf, H_BAR_X2)
        upd = HP.u64b(buf, H_UPDATE_FN)
        # PRIMARY gfx ptr = node+0xA0 (pinned). Auto-discovery kept as a cross-check / fallback.
        gfx_raw = HP.u64b(buf, H_GFX)
        gfx_kind, gfx_va = resolve(m, arena, gfx_raw)
        gfx_cands = discover_gfx_field(m, arena, buf)

        rec = dict(idx=i, addr=hex(addr), blk_off=hex(addr - blk), cat=cat,
                   update_fn=hex(upd) if upd else None,
                   bar_geom=[round(v, 2) if v is not None else None for v in (bx, by, bx2)],
                   gfx_pinned=dict(off=hex(H_GFX), raw=hex(gfx_raw) if gfx_raw else None,
                                   kind=gfx_kind, va=hex(gfx_va) if gfx_va else None),
                   gfx_candidates=[dict(off=hex(c["off"]), width=c["width"], kind=c["kind"],
                                        raw=hex(c["raw"]), va=hex(c["va"]), score=c["score"])
                                   for c in gfx_cands[:4]],
                   raw=buf[:NODE_SZ].hex())

        # follow the pinned +0xA0 gfx ptr (and the top auto-discovered one, if different) into the bank
        followed = []
        roots = []
        if gfx_va:
            roots.append((H_GFX, gfx_va, gfx_kind))
        for c in gfx_cands[:1]:
            if c["va"] != gfx_va:
                roots.append((c["off"], c["va"], c["kind"]))
        for off_, va, kind in roots:
            before = set(catalog)
            dump_chain(m, arena, va, maxregion, catalog, blobs)
            new = [hex(v) for v in catalog if v not in before]
            followed.append(dict(off=hex(off_), root=hex(va), kind=kind, regions=new))
        rec["followed"] = followed
        node_records.append(rec)
        gline = (f"+0xA0 -> 0x{gfx_va:x} ({gfx_kind})" if gfx_va else "NO gfx ptr at +0xA0")
        print(f"  node #{i} 0x{addr:x} cat=0x{cat:02x} bar=({bx:.0f},{by:.0f},{bx2:.0f}) "
              f"upd=0x{upd:x}  gfx: {gline}")

    # ── write the offline bundle ──────────────────────────────────────────────────────────────────
    os.makedirs(OUT_BINDIR, exist_ok=True)
    for va, data in blobs.items():
        with open(os.path.join(OUT_BINDIR, f"{va:012x}.bin"), "wb") as f:
            f.write(data)
    bundle = dict(
        blk=hex(blk), arena=hex(arena), asset_mirror=hex(arena + ASSET_OFF),
        translate="steam_VA = arena + 0x8400000 + (naomi - 0x0C000000)   [CONFIRMED HANDOVER:156]",
        list0b=dict(head_table=hex(HEAD_0B), head_node=hex(head_tab),
                    next_off=hex(H_NEXT), prev_off=hex(H_PREV), updfn_off=hex(H_UPDATE_FN),
                    cat_off=hex(H_CATEGORY), gfx_off=hex(H_GFX),
                    bar_geom_off="node+0x50/0x54/0x58", chain_len=n),
        dc_reference=dict(render_fn="loc_8c0301f6", gfx_dc="node+0xC8", flags_dc="node+0xCC",
                          textured_render="loc_8c1201E0", packer="loc_8c033e90",
                          note="Steam HUD node is its OWN struct; gfx pinned to node+0xA0 from dump."),
        regions=list(catalog.values()),
        nodes=node_records,
    )
    with open(OUT_JSON, "w") as f:
        json.dump(bundle, f, indent=1)
    total = sum(len(b) for b in blobs.values())
    print(f"\nDUMPED {len(blobs)} unique regions ({total // 1024} KiB) -> {OUT_BINDIR}/")
    print(f"catalog + per-node gfx pins -> {OUT_JSON}")
    print("OFFLINE: pin the winning gfx offset (gfx_candidates[0].off) as the Steam node+0xC8, then")
    print("decode each region with rip_hud_quads.decode_tex (twiddle + PAL4/PAL8 + ARGB4444), keyed")
    print("by node sid/screen, to assemble the shared UI atlas. Feed Ghidra the node update-fn / render")
    print("addresses (live addr == Ghidra addr; DYNAMIC_BASE off) to confirm the struct + format.")


if __name__ == "__main__":
    main()
