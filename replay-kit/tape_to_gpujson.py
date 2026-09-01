#!/usr/bin/env python3
# tape_to_gpujson.py — decode a 0.3.28 Steam MvC2 state tape (.json / .json.gz) into a
# plain tape.json the WebGPU tape-render harness (web/tapecanvas/gpu.html) fetches directly.
#
# Output shape (consumed by tape-adapter.mjs loadTapeJson):
#   { schema, frames:[[...34 cols...],...], costume:[6], p1_team:[3], p2_team:[3],
#     objs:[[gameFrame,[[sid,sx,sy,zx,face,cat,owner,layer,gfx1,gfx2],...]],...] }
#   (0.3.29: obj zx is scale×4096 — decode ÷4096; gfx1=Dat_GFX1 H+0x1A0, gfx2=Dat_GFX2 H+0x1A4 bank handles.)
#
# The objs stream is the tape's own gzip+base64 blob decoded to plain arrays. No render
# decisions here — this is a pure transport unpack (the adapter does the state mapping).
#
# Usage:
#   python tape_to_gpujson.py <tape.json.gz> [out.json]
#   (default out = ../web/tapecanvas/tape.json)

import sys, os, gzip, json, base64, struct

def load_tape(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return json.loads(raw)

def decode_objs(tape):
    # Record: 16 B (0.3.28, single gfx); 20 B (0.3.29, gfx1+gfx2); 32 B (0.3.32, +12 B effect wire).
    # Detect from objs_enc. Pure transport unpack — no render decisions here.
    if 'objs' not in tape or not tape['objs']:
        return []
    enc = str(tape.get('objs_enc', ''))
    rec = 32 if ('is_effect' in enc or '32B' in enc) else (20 if 'gfx2' in enc else 16)
    data = gzip.decompress(base64.b64decode(tape['objs']))
    out, off, n = [], 0, len(data)
    while off + 6 <= n:
        frame = struct.unpack_from('<I', data, off)[0]; off += 4
        count = struct.unpack_from('<H', data, off)[0]; off += 2
        objs = []
        for _ in range(count):
            sid, sx, sy = struct.unpack_from('<Hhh', data, off)
            zx = struct.unpack_from('<H', data, off + 6)[0]
            face, cat, owner, layer = struct.unpack_from('<BBBB', data, off + 8)
            gfx1 = struct.unpack_from('<I', data, off + 12)[0]
            if rec >= 32:
                gfx2 = struct.unpack_from('<I', data, off + 16)[0]
                is_effect, blend, drawn, atimer = struct.unpack_from('<BBBB', data, off + 20)
                zy, effect_key = struct.unpack_from('<HH', data, off + 24)
                depth = struct.unpack_from('<f', data, off + 28)[0]
                # Element order KEEPS [10]=blend [11]=is_effect [12]=drawn (fromJsonObject contract);
                # extras [13]=zy [14]=effect_key [15]=depth carried for over-capture. atimer dropped
                # (render-unused; still on the binary wire for future use).
                objs.append([sid, sx, sy, zx, face, cat, owner, layer, gfx1, gfx2,
                             blend, is_effect, drawn, zy, effect_key, depth])
            elif rec >= 20:
                gfx2 = struct.unpack_from('<I', data, off + 16)[0]
                objs.append([sid, sx, sy, zx, face, cat, owner, layer, gfx1, gfx2])
            else:
                objs.append([sid, sx, sy, zx, face, cat, owner, layer, gfx1])
            off += rec
        out.append([frame, objs])
    return out

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    src = sys.argv[1]
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, '..', 'web', 'tapecanvas', 'tape.json')
    tape = load_tape(src)
    gpu = {
        'schema': tape['schema'],
        'frames': tape['frames'],
        'costume': tape.get('costume', [1, 2, 1, 2, 1, 2]),
        'p1_team': tape.get('p1_team', [0, 0, 0]),
        'p2_team': tape.get('p2_team', [0, 0, 0]),
        # stage_id (Steam blk+0x6D3C, wire field) — forwarded to the STAGE backdrop
        # (renderer/stage-client.mjs via tape-adapter loadTapeJson). Absent on pre-0.3.29
        # tapes -> null -> no backdrop (bodies on black). CONFIRMED: this tape's stage_id=0
        # -> STG00 Airship (Day) [stage_id 0 = disc file idx 0; filedic Air Ship = STG00].
        'stage_id': tape.get('stage_id'),
        'objs_enc': tape.get('objs_enc', ''),          # lets the adapter detect 16 vs 20 B
        'objs': decode_objs(tape),
    }
    if 'fxBankMap' in tape:                             # optional handle->atlas calibration
        gpu['fxBankMap'] = tape['fxBankMap']
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as f:
        json.dump(gpu, f, separators=(',', ':'))
    sz = os.path.getsize(out)
    print(f'wrote {out}  ({sz/1e6:.1f} MB)  frames={len(gpu["frames"])}  '
          f'objframes={len(gpu["objs"])}  p1_team={gpu["p1_team"]}  p2_team={gpu["p2_team"]}  '
          f'costume={gpu["costume"]}')

if __name__ == '__main__':
    main()
