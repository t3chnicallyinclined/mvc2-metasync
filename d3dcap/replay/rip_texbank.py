#!/usr/bin/env python3
"""rip_texbank.py -- rip a Steam MvC2 texture BANK (effects / HUD / stage / common) straight out of
game_50.arc into tcw_pages-compatible PNGs, using the rule the game itself uses to number them.

THE RULE (Ghidra, mvc_dump.bin, all CONFIRMED by reading the functions; see docs/TEXTURE-BANKS-GHIDRA.md):

    FUN_1408458a0(base)            *(u32*)(ctx+0x1e0098) = base          (SH4: loc_8C11B800 -> 0x8C2DEE54)
    FUN_140844dc0(model, texHdrs)  for every record of the model with texIndex >= 0:
                                       TCW = texIndex + *(ctx+0x1e0098)
                                       slot[TCW] <- texHdrs[texIndex] = {u16 w, u16 h, u8 fmt, u8 type, .., u32 loc@+8}
                                       pixels = *(ctx+0x1e0088)[loc & 0x1ffffff]  (= DC RAM image)
    bank loader FUN_14060c370 / boot loader FUN_14060c070 pair (POL file, TEX file) -> DC addresses,
    FUN_14060d770(POL, TEX) rebases every record's loc to TEX + offset, so
                                       pixels = TEXfile[loc - firstLoc]
    Host decode FUN_14004ba50 (the bytes the D3D capture sees):
        type 1  = twiddled 16bpp, recursion TL,BL,TR,BR (FUN_140051f70)  -> y is bit 0 of the twiddle
        type 3  = VQ: 256 x 4 u16 codebook, then index bytes in 2x2-block twiddle order (FUN_140052280)
        fmt 0   = ARGB1555: R,G,B = c*255/31 (integer), A = 0xFF if bit15 else 0        (line 2413)
        fmt 1   = RGB565:   R,B = c*255/31, G = c*255/63, A = 0xFF                        (line 753)
        fmt 2   = ARGB4444: c*0x11                                                        (case 2)
        output byte order R,G,B,A (DXGI R8G8B8A8_UNORM = the capture's fmt 28)

Archive: game_50.arc (ARC v7, one zlib entry "bin\\mvsc2") -> IBIS header -> Sega AFS at +0x40 (890 entries,
{u32 off, u32 size} pairs at +8) == the game's ctx[0] archive image read by FUN_14060dcf0(i, dcAddr).

Usage:
    python rip_texbank.py --bank arc                 # rip the effects bank (base 0xC50, AFS 799/800)
    python rip_texbank.py --bank hud                 # base 0xC90, AFS 835/836
    python rip_texbank.py --bank stage --stage 0B    # base 0xC10, AFS 801+2*id / 802+2*id
    python rip_texbank.py --bank arc --gate          # compare against tcw_pages/index.json (sha over RGBA8)
    python rip_texbank.py --bank arc --add C51 C5A   # write those TCWs into the library (obj='arc')
    python rip_texbank.py --bank arc --decode ripstage --gate   # falsification arm: rip_stage.py's decode

ROM-derived output is gitignored (BYOR). The gate is the truth: a mismatch means THIS rule/decode is
wrong, never the captured page.
"""
import argparse, hashlib, json, os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ARC = r"C:\Program Files (x86)\Steam\steamapps\common\MARVEL vs. CAPCOM Fighting Collection" \
              r"\nativeDX11x64\arc\pc\game_50.arc"
LIB = os.path.join(HERE, "tcw_pages")

# bank name -> (TCW base, POL AFS entry, TEX AFS entry, Steam POL DC addr, Steam TEX DC addr, evidence)
BANKS = {
    # FUN_14060c070 (boot): FUN_14060dcf0(799,0xd000000) FUN_14060dcf0(800,0xd026000) FUN_14060d770(...)
    # FUN_14060c370 case 2: FUN_14060d080(0xc50, &PTR_DAT_142edf590, 0xd000000)   (SH4 case loc_8c032c76:
    # loc_8c0322d4(0x0CED0000, 0x0CDA4000); loc_8c032320(0x0C50, 0x8C26A908, 0x0CED0000))
    "arc":    (0xC50, 799, 800, 0x0D000000, 0x0D026000, "FUN_14060c070 + FUN_14060c370 case 2"),
    # FUN_14060c070: (0x343,0xd082000) (0x344,0xd099000); FUN_14060d560: FUN_1408458a0(0xc90) over PTR_DAT_142edf598
    "hud":    (0xC90, 0x343, 0x344, 0x0D082000, 0x0D099000, "FUN_14060c070 + FUN_14060d560"),
    # FUN_14060c070: (0x345,0xd0c6000) (0x346,0xd0e5000); FUN_14060c370 case 5: FUN_1408458a0(0x810) over PTR_DAT_142edf5a0
    "common": (0x810, 0x345, 0x346, 0x0D0C6000, 0x0D0E5000, "FUN_14060c070 + FUN_14060c370 case 5"),
    # FUN_14060c370 case 1: DAT_140a6aa80[stage] -> 0xd82d000, DAT_140a6aa30[stage] -> 0xd85d000; FUN_14060d470: 0xC10
    "stage":  (0xC10, None, None, 0x0D82D000, 0x0D85D000, "FUN_14060c370 case 1 + FUN_14060d470"),
}


def u16(b, o): return struct.unpack_from("<H", b, o)[0]
def u32(b, o): return struct.unpack_from("<I", b, o)[0]


# ---------------------------------------------------------------- archive (rom.rs load_mvsc2, ported)
def load_afs(arc_path):
    b = open(arc_path, "rb").read()
    if b[:4] != b"ARC\0" or u16(b, 4) != 7 or u16(b, 6) != 1:
        sys.exit("not the expected ARC v7 / 1-entry game_50.arc: %s" % arc_path)
    toc = 8
    csize, doff = u32(b, toc + 68), u32(b, toc + 76)
    m = zlib.decompress(b[doff:doff + csize])
    if m[:4] != b"IBIS" or m[0x40:0x44] != b"AFS\0":
        sys.exit("inflated payload is not IBIS/AFS")
    afs = 0x40
    n = u32(m, afs + 4)
    ents = [(afs + u32(m, afs + 8 + i * 8), u32(m, afs + 12 + i * 8)) for i in range(n)]
    return m, ents


def afs_entry(m, ents, i):
    off, sz = ents[i]
    return m[off:off + sz], off, sz


# ---------------------------------------------------------------- texture header list (16-byte records)
def tex_records(pol):
    """POL header: u32@0 model table ptr (DC), u32@4 count, u32@8 texHdrs (DC), u32@0x10 texHdrs end.
    Records: {u16 w, u16 h, u8 fmt, u8 type, u16 pad, u32 loc, u32 pad}. FUN_14060d8f0 / FUN_140844dc0."""
    ram = u32(pol, 0) & 0xFFFFFF00
    ts, te = u32(pol, 8) - ram, u32(pol, 0x10) - ram
    recs = []
    for k, a in enumerate(range(ts, te, 16)):
        recs.append(dict(idx=k, w=u16(pol, a), h=u16(pol, a + 2), fmt=pol[a + 4], type=pol[a + 5],
                         loc=u32(pol, a + 8)))
    return ram, u32(pol, 4), recs


# ---------------------------------------------------------------- host decode (FUN_14004ba50 & helpers)
def _twiddle_index_table(n):
    """Twiddled index for (x, y) in an n x n square, from FUN_140051f70's recursion order:
    quadrant order TL, BL, TR, BR => y contributes bit 0, x bit 1 at every level."""
    def spread(v):
        r = 0
        for i in range(16):
            r |= ((v >> i) & 1) << (2 * i)
        return r
    sx = [spread(x) << 1 for x in range(n)]
    sy = [spread(y) for y in range(n)]
    return sx, sy


def detwiddle16(src, w, h):
    """FUN_14004ba50 LAB_14004bbc4: square textures in one pass; non-square as w/h (or h/w) squares of
    side min(w,h) laid out along the long axis. Returns a list of w*h u16 in row-major order."""
    n = min(w, h)
    sx, sy = _twiddle_index_table(n)
    out = [0] * (w * h)
    words = struct.unpack_from("<%dH" % (w * h), src, 0)
    if w == h:
        for y in range(h):
            row = y * w
            ty = sy[y]
            for x in range(w):
                out[row + x] = words[sx[x] | ty]
    elif w > h:          # squares side by side along x (FUN_140051f70(src+k*n*n, dst+k*n))
        for k in range(w // n):
            base = k * n * n
            for y in range(n):
                row = y * w + k * n
                ty = sy[y]
                for x in range(n):
                    out[row + x] = words[base + (sx[x] | ty)]
    else:                # squares stacked along y (dst + k*n*n texels)
        for k in range(h // n):
            base = k * n * n
            for y in range(n):
                row = (k * n + y) * w
                ty = sy[y]
                for x in range(n):
                    out[row + x] = words[base + (sx[x] | ty)]
    return out


def expand_vq(src, w, h):
    """FUN_140052050 / FUN_140052280 / FUN_140051f70(cb+idx*8, dst, stride, 2): index bytes walk 2x2 blocks in
    the same twiddle order; each codebook entry is 4 u16 in that order (TL, BL, TR, BR). Expanding each index
    to its 4 words IN STREAM ORDER yields exactly a twiddled 16bpp image (block-level twiddle x texel-level
    twiddle = full twiddle), so the plain detwiddle applies afterwards."""
    cb = src[:0x800]
    idx = src[0x800:0x800 + (w * h) // 4]
    out = bytearray(w * h * 2)
    for i, e in enumerate(idx):
        out[i * 8:i * 8 + 8] = cb[e * 8:e * 8 + 8]
    return bytes(out)


def to_rgba_host(words, fmt):
    """FUN_14004ba50 scalar tails (lines 753-755 fmt 1, 2413-2415 fmt 0, case 2 fmt 2)."""
    out = bytearray(len(words) * 4)
    if fmt == 1:
        for i, v in enumerate(words):
            o = i * 4
            out[o] = ((v >> 11) * 0xFF) // 0x1F
            out[o + 1] = (((v >> 5) & 0x3F) * 0xFF) // 0x3F
            out[o + 2] = ((v & 0x1F) * 0xFF) // 0x1F
            out[o + 3] = 0xFF
    elif fmt == 0:
        for i, v in enumerate(words):
            o = i * 4
            out[o] = (((v >> 10) & 0x1F) * 0xFF) // 0x1F
            out[o + 1] = (((v >> 5) & 0x1F) * 0xFF) // 0x1F
            out[o + 2] = ((v & 0x1F) * 0xFF) // 0x1F
            out[o + 3] = 0xFF if v & 0x8000 else 0
    elif fmt == 2:
        for i, v in enumerate(words):
            o = i * 4
            hi, lo = v >> 8, v & 0xFF
            out[o] = (hi & 0xF) * 0x11
            out[o + 1] = (lo >> 4) * 0x11
            out[o + 2] = (lo & 0xF) * 0x11
            out[o + 3] = (hi >> 4) * 0x11
    else:
        return None
    return bytes(out)


def decode_host(texf, rec, first_loc):
    w, h, fmt, typ = rec["w"], rec["h"], rec["fmt"], rec["type"]
    off = rec["loc"] - first_loc
    need = 0x800 + (w * h) // 4 if typ == 3 else w * h * 2
    if off < 0 or off + need > len(texf):
        # the record points past the static TEX file: the slot's pixels are written at RUNTIME
        # (HUD bank: 0xC99 <- FUN_1406162e0, 0xC9A..0xCA5 <- FUN_14060d560 portrait copies,
        # 0xCA6.. <- FUN_140616330; all from the fighters' DATs through FUN_140611e90)
        return None, "RUNTIME slot: loc offset 0x%x+0x%x is past the TEX file (0x%x)" % (off, need, len(texf))
    if typ == 3:
        src = expand_vq(texf[off:off + need], w, h)
    elif typ == 1:
        src = texf[off:off + need]
    else:
        return None, "type %d not handled (host: 0x%02x00 path)" % (typ, typ)
    return to_rgba_host(detwiddle16(src, w, h), fmt), None


def decode_ripstage(texf, rec, first_loc):
    """Falsification arm: tools/rip_stage.py's decode (x-LSB morton, r*8 for 1555, replicate for 565)."""
    sys.path.insert(0, r"C:\Users\trist\projects\maplecast-flycast\tools")
    import rip_stage as RS
    t = dict(w=rec["w"], h=rec["h"], fmt=rec["fmt"], type=rec["type"], baseLocation=rec["loc"], ramOffset=first_loc)
    w, h, rgba = RS.decode_texture(texf, t)
    return rgba, None if rgba is not None else "fmt %d unsupported" % rec["fmt"]


# ---------------------------------------------------------------- driver
def rip_bank(bank, m, ents, stage=None, decode="host"):
    base, pol_i, tex_i, dc_pol, dc_tex, ev = BANKS[bank]
    if bank == "stage":
        sid = int(stage, 16)
        pol_i, tex_i = 801 + 2 * sid, 802 + 2 * sid
    pol, poff, psz = afs_entry(m, ents, pol_i)
    texf, toff, tsz = afs_entry(m, ents, tex_i)
    ram, nmodels, recs = tex_records(pol)
    first = next((r["loc"] for r in recs if r["w"] > 0), None)
    pages = []
    dec = decode_host if decode == "host" else decode_ripstage
    for r in recs:
        if r["w"] == 0:
            continue
        rgba, err = dec(texf, r, first)
        tcw = base + r["idx"]
        pages.append(dict(tcw=tcw, key="%08X" % tcw, rec=r, rgba=rgba, err=err,
                          sha=hashlib.sha256(rgba).hexdigest()[:16] if rgba else None))
    meta = dict(bank=bank, base=base, pol_entry=pol_i, tex_entry=tex_i, pol_afs_off=poff, pol_size=psz,
                tex_afs_off=toff, tex_size=tsz, dc_pol=dc_pol, dc_tex=dc_tex, pol_ram=ram, models=nmodels,
                evidence=ev, first_loc=first)
    return meta, pages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arc", default=DEFAULT_ARC)
    ap.add_argument("--bank", default="arc", choices=sorted(BANKS))
    ap.add_argument("--stage", default="0B", help="stage id (hex) for --bank stage")
    ap.add_argument("--decode", default="host", choices=["host", "ripstage"])
    ap.add_argument("--out", default=None, help="write every page PNG + index here (default: tcw_pages/<bank>_rip)")
    ap.add_argument("--gate", action="store_true", help="compare against tcw_pages/index.json")
    ap.add_argument("--add", nargs="*", help="TCWs (hex) to add to tcw_pages/index.json with obj='arc'")
    ap.add_argument("--lib", default=LIB)
    ap.add_argument("--fix-miskeyed", action="store_true",
                    help="with --add: when the library holds a DIFFERENT page under a ripped TCW and that page is "
                         "byte-exact with another TCW of this bank (proof it was keyed by the object's FIRST record, "
                         "tcw_build.py line 66), move it to <key>_<sha6> and put the ripped page under the key")
    a = ap.parse_args()

    m, ents = load_afs(a.arc)
    meta, pages = rip_bank(a.bank, m, ents, a.stage, a.decode)
    print("bank %s: base 0x%X  POL AFS %d (off 0x%X size 0x%X, ram 0x%08X, %d models)  TEX AFS %d (off 0x%X size 0x%X)"
          % (meta["bank"], meta["base"], meta["pol_entry"], meta["pol_afs_off"], meta["pol_size"], meta["pol_ram"],
             meta["models"], meta["tex_entry"], meta["tex_afs_off"], meta["tex_size"]))
    for p in pages:
        r = p["rec"]
        print("  TCW %s idx %2d %3dx%-3d fmt %d type %d loc 0x%08X  %s" % (p["key"], r["idx"], r["w"], r["h"], r["fmt"],
              r["type"], r["loc"], p["sha"] or p["err"]))

    from PIL import Image
    out = a.out or os.path.join(a.lib, "%s_rip" % a.bank + ("_" + a.stage if a.bank == "stage" else ""))
    os.makedirs(out, exist_ok=True)
    idx = {}
    for p in pages:
        if not p["rgba"]:
            continue
        r = p["rec"]
        fn = "tcw_%s_%dx%d_f28.png" % (p["key"], r["w"], r["h"])
        Image.frombytes("RGBA", (r["w"], r["h"]), p["rgba"]).save(os.path.join(out, fn))
        idx[p["key"]] = dict(file=fn, w=r["w"], h=r["h"], fmt=28, sha=p["sha"], obj="arc", bank=a.bank,
                             texIndex=r["idx"], srcFmt=r["fmt"], srcType=r["type"], loc="%08X" % r["loc"],
                             decode=a.decode)
    json.dump(dict(meta={k: (("0x%X" % v) if isinstance(v, int) else v) for k, v in meta.items()}, pages=idx),
              open(os.path.join(out, "index.json"), "w"), indent=1)
    print("wrote %d pages -> %s" % (len(idx), out))

    if a.gate:
        lib_path = os.path.join(a.lib, "index.json")
        lib = json.load(open(lib_path))
        by_sha = {}
        for p in pages:
            if p["sha"]:
                by_sha.setdefault(p["sha"], []).append(p["key"])
        by_key = {p["key"]: p for p in pages}
        lo, hi = meta["base"], meta["base"] + len(pages)
        n_in, n_exact, n_bysha, n_miss = 0, 0, 0, 0
        print("\nGATE (%s decode) against %s: %d library entries" % (a.decode, lib_path, len(lib)))
        for k, e in sorted(lib.items()):
            tcw = int(k.split("_")[0], 16)
            if not (lo <= tcw < hi):
                continue
            n_in += 1
            key = "%08X" % tcw
            p = by_key.get(key)
            same = p and p["sha"] == e["sha"]
            elsewhere = by_sha.get(e["sha"], [])
            if same:
                n_exact += 1
                verdict = "BYTE-EXACT"
            elif elsewhere:
                n_bysha += 1
                verdict = "page IS in this bank as TCW %s (library key mis-attributed)" % "/".join(elsewhere)
            else:
                n_miss += 1
                verdict = "NO MATCH (rip %s %dx%d vs lib %dx%d)" % (p["sha"] if p else "-", p["rec"]["w"] if p else 0,
                                                                  p["rec"]["h"] if p else 0, e["w"], e["h"])
            print("  %-16s lib sha %s  -> %s" % (k, e["sha"], verdict))
        print("GATE RESULT: %d library entries in bank range: %d byte-exact under their key, %d byte-exact under "
              "another TCW of this bank, %d unmatched" % (n_in, n_exact, n_bysha, n_miss))
        # reverse: every library sha (any key) found in this bank?
        found = [(k, by_sha[e["sha"]]) for k, e in lib.items() if e["sha"] in by_sha]
        print("reverse: %d of %d library pages (any key) are byte-exact pages of this bank" % (len(found), len(lib)))

    if a.add is not None:
        lib_path = os.path.join(a.lib, "index.json")
        lib = json.load(open(lib_path))
        want = [int(x, 16) for x in a.add] if a.add else [p["tcw"] for p in pages]
        # mis-key proof set: every static page of every bank (a capture keyed by an object's FIRST record can
        # point at a page of ANOTHER bank, e.g. library 0xC90 holds effects 0xC5A)
        proof_pages = list(pages)
        for b in ("arc", "hud"):
            if b != a.bank:
                proof_pages += rip_bank(b, m, ents, a.stage, a.decode)[1]
        proof_pages += rip_bank("stage", m, ents, a.stage, a.decode)[1]
        added = 0
        for p in pages:
            if p["tcw"] not in want or not p["rgba"]:
                continue
            r = p["rec"]
            fn = "tcw_%s_%dx%d_f28.png" % (p["key"], r["w"], r["h"])
            if p["key"] in lib and lib[p["key"]]["sha"] == p["sha"]:
                continue
            if p["key"] in lib:
                old = lib[p["key"]]
                proof = [q["key"] for q in proof_pages if q["sha"] == old["sha"] and q["key"] != p["key"]]
                if a.fix_miskeyed and proof:
                    moved = "%s_%s" % (p["key"], old["sha"][:6])
                    lib[moved] = dict(old, miskeyed_true_tcw=proof[0])
                    del lib[p["key"]]
                    key = p["key"]
                    print("  ~ %s held sha %s which is really TCW %s -> moved to %s; key takes the ripped page"
                          % (p["key"], old["sha"], proof[0], moved))
                else:
                    print("  ! %s already in library with sha %s (rip %s) -- NOT overwriting; adding as %s_%s"
                          % (p["key"], old["sha"], p["sha"], p["key"], p["sha"][:6]))
                    key = "%s_%s" % (p["key"], p["sha"][:6])
                    fn = "tcw_%s_%dx%d_f28.png" % (key, r["w"], r["h"])
            else:
                key = p["key"]
            Image.frombytes("RGBA", (r["w"], r["h"]), p["rgba"]).save(os.path.join(a.lib, fn))
            lib[key] = dict(file=fn, list=None, w=r["w"], h=r["h"], fmt=28, sha=p["sha"], obj="arc",
                            bank=a.bank, texIndex=r["idx"], srcFmt=r["fmt"], srcType=r["type"])
            added += 1
            print("  + %s  %dx%d  sha %s  (%s)" % (key, r["w"], r["h"], p["sha"], fn))
        json.dump(lib, open(lib_path, "w"), indent=1)
        print("added %d pages; library now %d" % (added, len(lib)))


if __name__ == "__main__":
    main()
