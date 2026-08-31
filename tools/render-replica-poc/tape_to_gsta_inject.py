#!/usr/bin/env python3
"""tape_to_gsta_inject.py <tape.json[.gz]> [out.gsta] [--max-rows N]

Converts a RetroReceipts agent tape (0.3.29 `frames`) into a per-frame
STATE-INJECTION stream for the flycast `applyStateInject()` hook (staged patch
tools/render-replica-poc/state_inject.patch) OR the built-in MAPLECAST_STATE_REPLICA
GSTA feed.

Output layout (little-endian), one record per tape frame, in tape order:
    magic  'GSI1'                      (once, file header)
    u32    n_records
    then n_records x:
        u32  dc_game_frame             (tape `frame` column == DC game-frame)
        376  GSTA payload              (EXACT maplecast_gamestate::serialize() layout)

The 376-byte GSTA payload is byte-identical to what the engine's own
serialize()/deserialize() produce (core/network/maplecast_gamestate.cpp:2142),
so the hook reuses deserialize() verbatim (rule 12). Fields the tape does NOT
carry are written as 0 and MUST be ignored by the consumer (the applyStateInject
hook applies only the tape-backed subset via read-overlay-write; see patch).

TAPE-BACKED fields (what injects faithfully):
    per char: pos_x, pos_y, vel_x, vel_y, facing, sprite_id, anim_timer,
              health, red_health, screen_x, screen_y, sprite_scale_x/y,
              pal_12e (hit-flash), draw_layer, assist_type
    global:   camera_x/y (eyeX/eyeY), game_timer, meter levels+fill, combos, stage_id
NON-TAPE fields (left 0 here; hook keeps the SH4's live value):
    animation_state(0x1D0), special_move_id(0x1E9), palette_id(0x52D),
    overlay_1a4(0x1A4, super/aura), pal_12d(0x12D), render_extra/hyper/flight/stance.

Slot remap (THIS tape family, per docs/RENDER-ACCURACY-PROGRAM.md 2026-08-30):
    tape_slot -> dc_slot = {0:0, 2:2, 4:4, 1:5, 3:1, 5:3}
    (DC CHAR_BASE is interleaved P1=0/2/4, P2=1/3/5; P2 point lands in dc slot 5)
"""
import base64, gzip, json, re, struct, sys

# DC CHAR_BASE order is P1C1,P2C1,P1C2,P2C2,P1C3,P2C3 (interleaved).
# The tape stores 6 fighters in its own (Steam pick) order; this maps them.
TAPE_TO_DC = {0: 0, 2: 2, 4: 4, 1: 5, 3: 1, 5: 3}
DC_FROM_TAPE = {dc: tp for tp, dc in TAPE_TO_DC.items()}   # dc_slot -> tape_slot


def load(path):
    op = gzip.open if path.endswith(".gz") else open
    with op(path, "rt") as f:
        return json.load(f)


def schema_index(tape):
    cols = [c.strip().split("[")[0]
            for c in re.split(r",(?![^\[]*\])",
                              tape["schema"].strip().lstrip("[").rstrip("]"))]
    return {c: i for i, c in enumerate(cols)}


def clampf(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def u8(v):
    return int(v) & 0xFF


def u16(v):
    return int(v) & 0xFFFF


def build_gsta(row, I, assist_dc, stage_id):
    """Return a 376-byte GSTA payload for one tape row (serialize() layout)."""
    buf = bytearray(376)
    off = 0

    def pu8(v):
        nonlocal off
        buf[off] = u8(v); off += 1

    def pu16(v):
        nonlocal off
        struct.pack_into("<H", buf, off, u16(v)); off += 2

    def pu32(v):
        nonlocal off
        struct.pack_into("<I", buf, off, int(v) & 0xFFFFFFFF); off += 4

    def pf32(v):
        nonlocal off
        struct.pack_into("<f", buf, off, clampf(v)); off += 4

    # --- header (25 bytes) ---
    pu8(1)                                  # in_match = 1 (force)
    pu8(row[I["timer"]])                    # game_timer
    pu8(stage_id)                           # stage_id
    pu8(row[I["p1_meter"]])                 # p1_meter_level
    pu8(row[I["p2_meter"]])                 # p2_meter_level
    pu16(0)                                 # p1_combo (not distinctly in tape header)
    pu16(0)                                 # p2_combo
    pu16(row[I["meter_fill"]])             # p1_meter_fill
    pu16(row[I["p2_meter_fill"]])          # p2_meter_fill
    pf32(row[I["eyeX"]])                    # camera_x
    pf32(row[I["eyeY"]])                    # camera_y
    pu32(row[I["frame"]])                   # frame_counter (DC game-frame)

    hp = row[I["hp"]]; px = row[I["px"]]; py = row[I["py"]]
    vx = row[I["vx"]]; vy = row[I["vy"]]; rhp = row[I["red_hp"]]
    facing = row[I["facing"]]; sid = row[I["sid"]]; atimer = row[I["atimer"]]
    sx = row[I["sx"]]; sy = row[I["sy"]]; zx = row[I["zx"]]; zy = row[I["zy"]]
    flash = row[I["flash"]]; layer = row[I["layer"]]

    # --- 6 chars x 57 bytes ---
    for dc in range(6):
        tp = DC_FROM_TAPE[dc]
        alive = 1 if (u8(hp[tp]) > 0 or u16(sid[tp]) != 0xFFFF) else 0
        pu8(alive)               # +0 active (informational; hook keeps LIVE)
        pu8(0)                   # +1 character_id  (NON-TAPE -> hook keeps LIVE)
        pu8(u8(facing[tp]))      # +2 facing_right (0x110)
        pu8(u8(hp[tp]))          # +3 health (0x420)
        pu8(u8(rhp[tp]))         # +4 red_health (0x424)
        pu8(0)                   # +5 special_move_id  (NON-TAPE)
        pu8(u8(assist_dc[dc]))   # +6 assist_type (0x4C9)
        pu8(0)                   # +7 palette_id  (NON-TAPE)
        pf32(px[tp])             # +8  pos_x (0x034)
        pf32(py[tp])             # +12 pos_y (0x038)
        pf32(sx[tp])             # +16 screen_x (0x0E0)
        pf32(sy[tp])             # +20 screen_y (0x0E4)
        pf32(vx[tp])             # +24 vel_x (0x05C)
        pf32(vy[tp])             # +28 vel_y (0x060)
        pu16(sid[tp])            # +32 sprite_id (0x144)
        pu16(0)                  # +34 animation_state (0x1D0) NON-TAPE
        pu16(atimer[tp])         # +36 anim_timer (0x142)
        pf32(zx[tp])             # +38 sprite_scale_x (0x050)
        pf32(zy[tp])             # +42 sprite_scale_y (0x054)
        pu8(0)                   # +46 pal_12d (0x12D) NON-TAPE
        pu8(0)                   # +47 pal_12e (0x12E) DROPPED: tape idx28 "flash" is a
                                 #     per-slot CONSTANT [16,24,32,40,48,56] (not hit-flash);
                                 #     leave the SH4's live value (read-overlay-write).
        pu8(0)                   # +48 overlay_1a4 (0x1A4) NON-TAPE (super/aura)
        pu8(u8(layer[tp]))       # +49 draw_layer
        pu8(0)                   # +50 render_extra NON-TAPE
        pu8(u8(facing[tp]))      # +51 facing_1d2 (0x1D2) authoritative xflip
        pu8(0)                   # +52 pal_color_25 NON-TAPE
        pu8(0)                   # +53 hyper_armor NON-TAPE
        pu8(0)                   # +54 flight_flag NON-TAPE
        pu8(0)                   # +55 stance NON-TAPE
        pu8(0)                   # +56 _pad

    # --- tail (9 bytes) ---
    pu16(0xFFFF)   # p1_buttons (neutral, active-low)
    pu16(0xFFFF)   # p2_buttons
    pu8(0); pu8(0); pu8(0); pu8(0)   # p1_lt/rt p2_lt/rt
    pu8(0)         # stage_anim_timer (NON-TAPE; hook keeps LIVE)

    assert off == 376, off
    return bytes(buf)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[0])
    tape = load(sys.argv[1])
    out = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") \
        else "inject.gsta"
    max_rows = None
    if "--max-rows" in sys.argv:
        max_rows = int(sys.argv[sys.argv.index("--max-rows") + 1])

    I = schema_index(tape)
    rows = tape.get("frames") or []
    if max_rows:
        rows = rows[:max_rows]
    stage_id = int(tape.get("stage_id", 0))

    # assist is per-DC-slot: tape assist_p1/assist_p2 are per-member in PICK order.
    ap1 = tape.get("assist_p1") or [0, 0, 0]
    ap2 = tape.get("assist_p2") or [0, 0, 0]
    # DC slots P1=0/2/4 P2=1/3/5, member m -> dc = m*2 (P1) / m*2+1 (P2)
    assist_dc = [0] * 6
    for m in range(3):
        assist_dc[m * 2] = ap1[m] if m < len(ap1) else 0
        assist_dc[m * 2 + 1] = ap2[m] if m < len(ap2) else 0

    recs = []
    for r in rows:
        gf = int(r[I["frame"]])
        recs.append(struct.pack("<I", gf) + build_gsta(r, I, assist_dc, stage_id))

    with open(out, "wb") as fo:
        fo.write(b"GSI1")
        fo.write(struct.pack("<I", len(recs)))
        for rec in recs:
            fo.write(rec)

    print(f"wrote {out}: {len(recs)} records ({len(recs)*380 + 8} bytes)")
    print(f"  tape frames {tape.get('frame_first')}..{tape.get('frame_last')}  span {tape.get('frame_span')}")
    print(f"  teams p1 {tape.get('p1_team')}  p2 {tape.get('p2_team')}  stage {stage_id}")
    print(f"  assist_dc (P1=0/2/4 P2=1/3/5): {assist_dc}")
    print(f"  slot remap tape->dc: {TAPE_TO_DC}")
    print(f"  record stride 380 (u32 frame + 376 GSTA)")


if __name__ == "__main__":
    main()
