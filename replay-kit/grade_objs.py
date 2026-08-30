#!/usr/bin/env python3
"""grade_objs.py <tape.json.gz> — THE OBJS-RESOLUTION GATE for a 0.3.29 shipping tape.

Coverage% does NOT catch the 0.3.28 objs bug (that tape had 100% coverage AND garbage objs).
This grades the objs stream DIRECTLY: a real 0.3.29 capture must show effect nodes RESOLVING —
  • owner attributed to a real fighter slot (not 0xFF everywhere; some 255 = genuinely-ownerless
    super-flash is EXPECTED and fine),
  • gfx1 (Dat_GFX1 handle, H+0x1A0) non-zero on ~all nodes,
  • sane scale (zx_q/4096 ~ 1.667, NOT the 426.625 ÷16-decode-bug constant),
  • 20-byte record (owner + gfx1 + gfx2), not the 16-byte 0.3.28 layout.
Exit 0 = PASS. This is the falsifiable gate 45 flagged — grade the SHIPPING build's fresh tape.
"""
import gzip, json, base64, struct, sys, collections

# a .cmd console defaults to cp1252; make sure the ÷/— glyphs never mojibake the grade
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    t = json.load(gzip.open(sys.argv[1]))
    ver = t.get("ver"); enc = t.get("objs_enc", "")
    rec_sz = 20 if ("gfx2" in enc or "gfx1" in enc) else 16
    fmt = "<HhhHBBBBII" if rec_sz == 20 else "<HhhHBBBBI"
    print(f"tape ver {ver}   objs record = {rec_sz}B   frames={t.get('frame_count')}")
    oc = t.get("objs")
    if not oc:
        print("[!!] no objs stream — FAIL"); sys.exit(1)
    raw = gzip.decompress(base64.b64decode(oc))
    n = 0; owner = collections.Counter(); cat = collections.Counter()
    gfx1nz = 0; scmin = 1e9; scmax = -1e9; i = 0
    while i + 6 <= len(raw):
        cnt = struct.unpack_from("<H", raw, i + 4)[0]; i += 6
        for _ in range(cnt):
            if i + rec_sz > len(raw): break
            rec = struct.unpack_from(fmt, raw, i); i += rec_sz
            n += 1
            _sid, _sx, _sy, zx_q, _face, c, ow, _layer = rec[:8]
            cat[c] += 1; owner[ow] += 1
            if rec[8]: gfx1nz += 1              # rec[8] = gfx1 (20B) or the single gfx (16B)
            sc = zx_q / 4096.0
            scmin = min(scmin, sc); scmax = max(scmax, sc)
    if n == 0:
        print("[!!] 0 obj nodes — FAIL"); sys.exit(1)
    own_real = sum(v for k, v in owner.items() if k < 6)
    print(f"total obj nodes : {n:,}")
    print(f"cat histogram   : {dict(cat)}")
    print(f"owner histogram : {dict(sorted(owner.items(), key=lambda x: (x[0] == 255, x[0])))}")
    print(f"owner<6 (real)  : {own_real:,}/{n:,} ({100*own_real/n:.1f}%)   owner=255: {owner.get(255,0):,} ({100*owner.get(255,0)/n:.1f}%)")
    print(f"gfx1 non-zero   : {gfx1nz:,}/{n:,} ({100*gfx1nz/n:.1f}%)")
    print(f"scale range     : {scmin:.4f} .. {scmax:.4f}   (want ~1.667; 426.625 = the ÷16 decode bug)")
    ok_rec = rec_sz == 20
    ok_owner = own_real / n > 0.5
    ok_gfx1 = gfx1nz / n > 0.95
    ok_scale = scmax < 20.0
    print()
    print(f"{'[OK]' if ok_rec else '[!!]'} 20-byte 0.3.29 record (owner+gfx1+gfx2)")
    print(f"{'[OK]' if ok_owner else '[!!]'} owner attributed to real slots (bulk <6)")
    print(f"{'[OK]' if ok_gfx1 else '[!!]'} gfx1 handles resolve (~100% non-zero)")
    print(f"{'[OK]' if ok_scale else '[!!]'} scale sane (no 426.625 ÷16 bug)")
    ok = ok_rec and ok_owner and ok_gfx1 and ok_scale
    print(f"\nOBJS GRADE: {'PASS — effects resolve, ship-safe' if ok else 'FAIL — objs not resolving (see marks above)'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
