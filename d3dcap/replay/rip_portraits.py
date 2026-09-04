#!/usr/bin/env python3
"""rip_portraits.py -- rip the per-character HUD PORTRAIT + NAME-PLATE pages (TCW 0xC9A..0xCA5) out of
game_50.arc, keyed by ROM char id, using the rule the game itself uses.

THE RULE (Ghidra, mvc_dump.bin -- CONFIRMED by reading the functions and the tables; see
docs/PORTRAIT-PAGES-GHIDRA.md):

    FUN_14060c370 case 6 : FUN_14060dcf0(DAT_140a6d190[cid], fighterBase+0x148000)  ->  fighter+0x1F8
        DAT_140a6d190 is a u16 table = 3 + cid   (cids 25/26 collapse onto entry 27)   [read from the exe]
    FUN_14060d560 (every match load), for each of the six fighter slots s (stride 0x738):
        data = *(blk + 0x3FB0 + s*0x738)                       # = fighter+0x1F8, the 32 KB HUD/portrait file
        FUN_140611e90(data + data[0], DC 0x0CE60000)           # 16-bit LZSS -> up to 4 x 0x800-B pages
        k = DAT_140a6aac8[s]                = {0,3,1,4,2,5}[s]                        [read from the exe]
        portrait: 0x800 B from DC 0x0CE60000 + DAT_140a6aac4[*(fighter+0x655)] * 0x800   ({1,0,3,0})
                  -> HUD texHdr[10 + k].loc      -> TCW 0xC9A + k
        name:     0x800 B from DC 0x0CE61000  (= page 2, FIXED)
                  -> HUD texHdr[16 + k].loc      -> TCW 0xCA0 + k
    HUD texHdr records 10..21 are 32x32 fmt 1 (RGB565) type 1 (twiddled)  [read from AFS 835]

    Slot order is EVEN = P1 / ODD = P2 (legacy/src-tauri/src/sync.rs: p1_team_cid = [cid(0),cid(2),cid(4)]),
    so with k = {0,3,1,4,2,5}[s]:  P1 team i -> 0xC9A+i / 0xCA0+i ;  P2 team i -> 0xC9D+i / 0xCA3+i.

Usage:
    python rip_portraits.py                       # rip every cid -> portraits/index.json + PNGs
    python rip_portraits.py --gate                # gate against the captured tcw_pages 0xC9A..0xCA5
    python rip_portraits.py --cids 42 44 52       # a subset

ROM-derived output is gitignored (BYOR).
"""
import argparse, hashlib, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rip_texbank as RT

OUT = os.path.join(HERE, "portraits")
LIB = os.path.join(HERE, "tcw_pages")

# exe tables, read from mvc_dump.bin (see the module doc); hard-coded here so the rip needs no Ghidra.
DAT_140a6aac8 = (0, 3, 1, 4, 2, 5)     # fighter slot -> HUD record offset k
DAT_140a6aac4 = (1, 0, 3, 0)           # *(fighter+0x655) -> decompressed page index of the PORTRAIT
NAME_PAGE = 2                          # DC 0x0CE61000 - 0x0CE60000 = 2 * 0x800
PAGE = 0x800                           # one 32x32 RGB565 page
NCHAR = 59                             # DAT_140a6d190 has 59 non-zero entries


def afs_index(cid):
    """DAT_140a6d190[cid] (u16): 3 + cid, with 25/26 collapsed onto 27."""
    return 27 if cid in (25, 26) else 3 + cid


def lzss16(src, off=0, out_words=None):
    """FUN_140611e90, ported verbatim. 16-BIT LZSS: a control word supplies 16 flags MSB-first; flag 0 =
    literal word; flag 1 = match word `w`: count = w>>11, offset = w & 0x7FF, and when count == 0 the NEXT
    word is the count and `w` itself is the offset. offset 0 + count > 0 = write `count` zero words;
    offset 0 + count 0 = END.  Offsets/counts are in 16-bit WORDS, back-referencing the output."""
    out = bytearray()
    ctrl, mask, p = 0, 0, off

    def w16(i):
        return struct.unpack_from("<H", src, i)[0]

    while True:
        while True:
            if mask == 0:
                ctrl = w16(p)
                mask = 0x8000
                p += 2
            v = w16(p)
            p += 2
            bit = ctrl & mask
            mask >>= 1
            if bit:
                break
            out += src[p - 2:p]
            if out_words and len(out) >= out_words * 2:
                return bytes(out)
        cnt = v >> 11
        if cnt == 0:
            cnt = w16(p)
            offs = v
            p += 2
        else:
            offs = v & 0x7FF
        if offs == 0:
            if cnt == 0:
                return bytes(out)
            out += b"\0" * (cnt * 2)
        else:
            q = len(out) - offs * 2
            for _ in range(cnt):
                out += out[q:q + 2]
                q += 2
        if out_words and len(out) >= out_words * 2:
            return bytes(out)


# the two OTHER runtime-patched slots of the same file (CONFIRMED writers, ripped for completeness):
#   FUN_1406162e0(fighter): decompress sub-blob 1 (offset word @+4) -> re-upload TCW 0xC99   (256x256 fmt1 type3 VQ)
#   FUN_140616330(fighter): decompress sub-blob 2 (offset word @+8) -> re-upload TCW 0xCA6 + (*(fighter+0x230)>>1)
#                                                                      (128x128 fmt1 type3 VQ, records 22..24)
BIG = ((1, 256, 256, "big"), (2, 128, 128, "banner"))


def vq_rgba(blob, w, h):
    """One VQ page (type 3): 0x800-B codebook + w*h/4 index bytes, then the host detwiddle + RGB565."""
    need = 0x800 + (w * h) // 4
    if len(blob) < need:
        return None
    return RT.to_rgba_host(RT.detwiddle16(RT.expand_vq(blob[:need], w, h), w, h), 1)


def page_rgba(blob, page):
    """One 0x800-B page as the host would upload it: 32x32, type 1 (twiddled), fmt 1 (RGB565)."""
    b = blob[page * PAGE:(page + 1) * PAGE]
    if len(b) < PAGE:
        return None
    return RT.to_rgba_host(RT.detwiddle16(b, 32, 32), 1)


def char_file(m, ents, cid):
    """AFS entry 3+cid: the 32 KB per-character HUD/portrait file (fighter+0x1F8)."""
    i = afs_index(cid)
    if i >= len(ents):
        return None
    f, _, _ = RT.afs_entry(m, ents, i)
    return f if len(f) >= 12 else None


def char_pages(m, ents, cid):
    """Every decompressed 0x800 page of AFS entry 3+cid's sub-blob 0 (the set FUN_14060d560 draws from):
    pages 0/1/3 = the portrait under assist type beta/alpha/gamma, page 2 = the NAME PLATE."""
    f = char_file(m, ents, cid)
    if f is None:
        return None
    off = struct.unpack_from("<I", f, 0)[0]
    if off <= 0 or off >= len(f):
        return None
    blob = lzss16(f, off, out_words=4 * PAGE // 2)
    return [page_rgba(blob, k) for k in range(4)]


def char_big(m, ents, cid):
    """Sub-blobs 1 and 2 -> the 256x256 'big' art (TCW 0xC99) and the 128x128 banner (TCW 0xCA6+)."""
    f = char_file(m, ents, cid)
    if f is None:
        return {}
    out = {}
    for sub, w, h, tag in BIG:
        off = struct.unpack_from("<I", f, sub * 4)[0]
        if off <= 0 or off >= len(f):
            continue
        need = 0x800 + (w * h) // 4
        rgba = vq_rgba(lzss16(f, off, out_words=need // 2), w, h)
        if rgba:
            out[tag] = (rgba, w, h)
    return out


def sha(b):
    return hashlib.sha256(b).hexdigest()[:16]


def write_png(path, rgba, w, h):
    from PIL import Image
    Image.frombytes("RGBA", (w, h), bytes(rgba)).save(path)


def png_rgba(path):
    from PIL import Image
    return Image.open(path).convert("RGBA").tobytes()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arc", default=RT.DEFAULT_ARC)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--cids", type=int, nargs="*")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--big", action="store_true", help="also rip the 0xC99 / 0xCA6 art (sub-blobs 1 and 2)")
    a = ap.parse_args()
    m, ents = RT.load_afs(a.arc)
    cids = a.cids if a.cids else list(range(NCHAR))

    if a.gate:
        # the captured library's 0xC9A..0xCA5 pages vs the ripped per-cid pages.
        import glob
        want = {}
        for p in glob.glob(os.path.join(LIB, "tcw_00000C9[A-F]*_32x32_f28.png")) + \
                 glob.glob(os.path.join(LIB, "tcw_00000CA[0-5]*_32x32_f28.png")):
            want[os.path.basename(p)] = sha(png_rgba(p))
        got = {}
        for cid in cids:
            pg = char_pages(m, ents, cid)
            if not pg:
                continue
            for k, q in enumerate(pg):
                if q:
                    got.setdefault(sha(q), []).append("cid %d page %d" % (cid, k))
        hit = sum(1 for f, s in want.items() if s in got)
        for f in sorted(want):
            print("%-40s %s  %s" % (f, want[f], ", ".join(got.get(want[f], ["-- NO MATCH"]))))
        print("GATE: %d/%d captured portrait/name pages reproduced from the character DATs" % (hit, len(want)))
        return 0 if hit == len(want) else 1

    os.makedirs(a.out, exist_ok=True)
    idx = {}
    for cid in cids:
        pg = char_pages(m, ents, cid)
        if not pg or pg[NAME_PAGE] is None:
            print("cid %d: no pages" % cid)
            continue
        # All four 0x800 pages: the consumer picks the portrait with DAT_140a6aac4[assist] and the name with
        # NAME_PAGE, so the assist-type variant is resolved at render time from the tape's `assist[slot]`.
        ent = {"pages": [None] * 4}
        for k in range(4):
            if pg[k] is None:
                continue
            fn = "pc_%02d_p%d.png" % (cid, k)
            write_png(os.path.join(a.out, fn), pg[k], 32, 32)
            ent["pages"][k] = dict(file=fn, w=32, h=32, fmt=28, sha=sha(pg[k]))
        if a.big:
            for tag, (rgba, w, h) in char_big(m, ents, cid).items():
                fn = "pc_%02d_%s.png" % (cid, tag)
                write_png(os.path.join(a.out, fn), rgba, w, h)
                ent[tag] = dict(file=fn, w=w, h=h, fmt=28, sha=sha(rgba))
        idx[str(cid)] = ent
        shas = [(p or {}).get("sha", "-") for p in ent["pages"]]
        print("cid %2d -> AFS %3d  pages %s" % (cid, afs_index(cid), " ".join(s[:6] for s in shas)))
    json.dump(dict(meta=dict(rule="FUN_14060d560", slot_k=list(DAT_140a6aac8), assist_page=list(DAT_140a6aac4),
                             name_page=NAME_PAGE, portrait_tcw=0xC9A, name_tcw=0xCA0), chars=idx),
              open(os.path.join(a.out, "index.json"), "w"), indent=1)
    print("%d characters -> %s" % (len(idx), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
