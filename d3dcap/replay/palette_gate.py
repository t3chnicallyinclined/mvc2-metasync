#!/usr/bin/env python3
"""palette_gate.py -- deterministic gate for the PALETTE SOURCE rule (docs/PALETTE-SOURCE-GHIDRA.md).

    python palette_gate.py 4445 4505 5168 7279          # capgate: captured LUT pages vs blk staging lines
    python palette_gate.py --ttd ../ttd/runs/<run>/pre   # same-moment blk.bin + dcram.bin: staging vs DatPal rows

Rule under test (Steam, CONFIRMED by decompile, see the doc):
  * per fighter slot s, palette-bank base = DAT_140a6d188[s] = 0x10 + 8*s (node+0x172);
  * the engine STAGES its resolved 16-colour rows at blk+0x1040 + bank*0x38: +8 u32 flag (1 raw / 2 dim /
    0 uploaded), +0x18 16 x u16 ARGB4444; FUN_140613390 uploads flagged lines to host PALETTE_RAM;
  * every character draw binds t1 = the 256x1 R8G8B8A8 LUT of its texture-slot bank
    (slot table ctx+0x1e00a0+idx*0x18 +4), each channel = nibble*17.
Gate 1 (capgate): for every indexed draw, tex[1][0:64] must equal SOME staged line converted with that rule.
Gate 2 (ttd): staged row k of slot s must equal dcram[DatPal + var*0x100 + k*0x20] (var = node+0x39),
              and DatPal+0 (what the v3/v4 tape ships as `pal`) is reported against the rendered row 0.
Never prints palette bytes (ROM-derived); prints counts and bank ids only.
"""
import argparse, collections, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blkstate as BS, emu_gate as G, emitter_gate as E

STAGE_OFF, STAGE_STRIDE, STAGE_FLAG, STAGE_COLS, N_LINES = 0x1040, 0x38, 0x8, 0x18, 0x80
SLOTBASE = [0x10, 0x18, 0x20, 0x28, 0x30, 0x38]          # DAT_140a6d188 (bytes read from mvc_dump.bin)


def line(blk, bank):
    o = STAGE_OFF + bank * STAGE_STRIDE
    return struct.unpack_from('<I', blk, o + STAGE_FLAG)[0], blk[o + STAGE_COLS:o + STAGE_COLS + 32]


def rgba8(cols32):
    """16 x u16 ARGB4444 -> 64 B R8G8B8A8, nibble*17 (the expansion the captured LUT pages carry)."""
    out = bytearray()
    for c in struct.unpack('<16H', cols32):
        out += bytes([((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, ((c >> 12) & 15) * 17])
    return bytes(out)


def fighters(blk):
    out = {}
    for s in range(6):
        o = BS.H0_OFF + s * BS.SLOT_STRIDE
        out[s] = dict(char=blk[o + 1], var=blk[o + 0x39], base=struct.unpack_from('<H', blk, o + 0x172)[0],
                      datpal=struct.unpack_from('<Q', blk, o + 0x1b8)[0], drawn=blk[o + 0x170],
                      nrows=struct.unpack_from('<b', blk, o + 0x4c)[0])
    return out


def gate_capgate(frames):
    tot = collections.Counter()
    prev = {}
    for fr in frames:
        try:
            meta, blk, base = G.frame_state(fr, BS.CAP)
        except SystemExit as e:
            print('frame %d: STATE: %s' % (fr, e)); continue
        pack = os.path.join(HERE, 'capgate', 'frame_%d.pack' % fr)
        if not os.path.exists(pack):
            print('frame %d: state dump present, NO .pack in capgate -> not gateable' % fr); continue
        man, B = E.load_pack(pack)
        by_rgba = collections.defaultdict(list)
        for bank in range(N_LINES):
            by_rgba[rgba8(line(blk, bank)[1])].append(bank)
        texs = man['textures']
        n = ok = 0
        banks = collections.Counter()
        bad = collections.Counter()
        for d in man['draws']:
            t = d.get('tex') or []
            if not (len(t) >= 2 and t[1] and texs.get(t[1], {}).get('w') == 256 and texs[t[1]].get('h') == 1):
                continue
            n += 1
            lut = B(texs[t[1]])[:64]
            m = by_rgba.get(lut)
            if m:
                ok += 1; banks[tuple(m)] += 1
            else:
                bad[(t[1], lut)] += 1
        f = fighters(blk)
        print('frame %d: indexed draws %d, LUT == staged bank byte-exact %d/%d' % (fr, n, ok, n))
        print('  fighters: ' + ', '.join('s%d char %02x var %d base %02x%s' % (s, x['char'], x['var'], x['base'], ' DRAWN' if x['drawn'] else '') for s, x in f.items()))
        for bk, c in sorted(banks.items()):
            print('  bank(s) %s -> %d draws; owner slot(s) %s row(s) %s' % (
                ['%02x' % b for b in bk], c, sorted({(b - 0x10) // 8 for b in bk if 0x10 <= b < 0x40}),
                [b - SLOTBASE[(b - 0x10) // 8] for b in bk if 0x10 <= b < 0x40]))
        pend = ['%02x' % b for b in range(N_LINES) if line(blk, b)[0]]
        print('  staging lines with a PENDING flag at walk time: %s' % (pend or 'none'))
        for (key, lut), c in bad.items():
            earlier = [(pf, ['%02x' % b for b in bb]) for pf, tab in prev.items() for r, bb in tab.items() if r == lut]
            print('  MISMATCH tex %s x%d draws: equals a staged bank of an EARLIER captured frame: %s' % (key, c, earlier or 'no'))
        prev[fr] = dict(by_rgba)
        tot['ok'] += ok; tot['n'] += n
    print('CAPGATE TOTAL exact/total = %d/%d' % (tot['ok'], tot['n']))


def gate_ttd(run):
    meta = json.load(open(os.path.join(run, 'meta.json')))
    blk = open(os.path.join(run, 'blk.bin'), 'rb').read()
    dc = open(os.path.join(run, 'dcram.bin'), 'rb').read()
    dcbase = int(meta['dcram'], 16)
    tot = ok = 0; v_checked = v_mism = 0
    for s, x in fighters(blk).items():
        off = x['datpal'] - dcbase
        if not (0 <= off < len(dc)):
            print('slot %d: DatPal outside the dcram image' % s); continue
        res = ''
        for k in range(8):
            src = dc[off + x['var'] * 0x100 + k * 0x20:][:0x20]
            eq = src == line(blk, x['base'] + k)[1]
            tot += 1; ok += eq; res += '=' if eq else 'X'
        r0 = dc[off:off + 0x20] == line(blk, x['base'])[1]
        if x['var']:
            v_checked += 1; v_mism += (not r0)
        print('slot %d char %02x var %d base %02x DatPal DC %08x: staged row k == DatPal+var*0x100+k*0x20 -> %s ; DatPal+0 == rendered row 0: %s'
              % (s, x['char'], x['var'], x['base'], 0x0C000000 + off, res, r0))
    print('TTD TOTAL rows exact/total = %d/%d ; var!=0 fighters whose DatPal+0 (the v3/v4 tape `pal`) != rendered row 0: %d/%d'
          % (ok, tot, v_mism, v_checked))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('frames', nargs='*', type=int)
    ap.add_argument('--ttd', help='a ttd/runs/<run>/pre directory (blk.bin + dcram.bin + meta.json)')
    a = ap.parse_args()
    if a.ttd:
        gate_ttd(a.ttd)
    if a.frames:
        gate_capgate(a.frames)
