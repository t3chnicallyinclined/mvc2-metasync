# AGENT CHANGE — capture what re-simulation needs, and nothing else

Target: `RetroReceipts-agent/agent/src/reader.rs` (shipping line, currently **0.3.23**).
Everything here is measured live on the Steam build — see `docs/STEAM-GGPO-DETERMINISM.md`.

**Why this is small:** the agent already reads the whole `0x33B18` match block every frame. The
complete deterministic simulation state is *already in its hands* — it just throws all but a few
fields away. This change keeps two more things so a server can re-simulate the match exactly.

---

## What re-simulation needs

| | why |
|---|---|
| **Authoritative inputs** `G+0x218 + seat*4` | the raw pad word, upstream of the 12-entry translation table. What we record today (`cl+0x4fc`) is TWO STAGES DOWNSTREAM and lossy. |
| **Seat map** `G+0x258 + k*4` | which GGPO player is which seat. Never read today — **this is the root cause of the documented side-swap.** |
| **A character-select snapshot** | the only portable anchor. A battle-state snapshot is NOT portable (557 pointers into per-character asset data); a char-select one is (proven cross-process, 36 MB blk delta, game kept running). |
| **Rollback count** `G+0x76C` | tape-quality signal — non-zero means GGPO rewound during capture. |

Everything else a receipt needs (positions, sprites, effects, assists, stage, HUD, damage) the
server DERIVES by re-simulating. It does not need to be captured.

---

## 1. Constants — add beside the existing exe-relative block (~reader.rs:105-115)

```rust
// ⚠ CORRECTION: KCODE_OFF is NOT "flycast kcode[0] (the LOCAL pad)". It is G+0x218 — GGPO SEAT 0's
// post-synchronisation input word. Which seat is local comes from SEATMAP_OFF, which we never read;
// that omission is the root cause of the documented side-swap.
const SEATIN_OFF:   usize = 0xac6f58;   // G+0x218: raw input, seat k at +k*4 (u32, 24-bit mask)
const SEATMAP_OFF:  usize = 0xac6f98;   // G+0x258: GGPO player k -> seat index (i32, -1 = unmapped)
const ROLLBACK_OFF: usize = 0xac74ac;   // G+0x76C: load_game_state count; >0 means GGPO rewound
const MODE_OFF:     usize = 0x3cb8;     // blk+0x3CB8: byte[2] 1 = CHARACTER SELECT, 2 = IN BATTLE
```

`SEATIN_OFF` deliberately equals the old `KCODE_OFF` — same address, correct name. Keep `KCODE_OFF`
as an alias if anything else references it.

The input chain, measured (value sets differ between stages, confirming the table sits between):
```
G+0x218 (RAW)  ->  bit table @0x140A4F780  ->  blk+0x3C66+i*0x14  ->  cl+0x4fc  (what we ship today)
```

## 2. Row — two columns, APPENDED (reader.rs:1193)

Append only, exactly as 0.3.23 did, so positional consumers of older columns are unaffected.

```rust
struct GsRow {
    // ... existing fields unchanged ...
    sid: [u16; 6], atimer: [u8; 6], eye_x: f32, eye_y: f32, ground: f32,
    // 0.3.24: the AUTHORITATIVE inputs — raw pad words, upstream of the translation table.
    // p1_in/p2_in above are the downstream decoded values and are kept only for compatibility.
    seat_in: [u32; 2],
}
```

Schema string (reader.rs:1097) — append `seat_in[2]`:

```rust
const GS_SCHEMA: &str = "[frame,p1_in,p2_in,kcode,hp[6],px[6],py[6],p1_meter,p2_meter,meter_fill,\
combo_dealt[6],combo_recv[6],vx[6],vy[6],red_hp[6],facing[6],hitstun[6],drawn[6],sid[6],atimer[6],\
eyeX,eyeY,ground,seat_in[2]]";
```

Populate where the row is built (reader.rs:1354):

```rust
seat_in: if exe_base != 0 {
    [rpm_u32(h, exe_base + SEATIN_OFF).unwrap_or(0),
     rpm_u32(h, exe_base + SEATIN_OFF + 4).unwrap_or(0)]
} else { [0, 0] },
```

## 3. Envelope — seat map, rollback count, and the anchor snapshot

Add to the record envelope (beside `frame_counter_addr`, `synthetic_frames`):

```rust
"seat_map":    [i32; 4],   // G+0x258+k*4 — GGPO player k -> seat index
"rollbacks":   u32,        // G+0x76C at match end; >0 = GGPO rewound during capture
"anchor":      String,     // base64(gzip(blk[0..0x33B18])) captured at CHARACTER SELECT
"anchor_blk":  u64,        // the blk address it was captured at   } required to
"anchor_arena":u64,        // *(exe+0xac6d40), the 256 MiB arena   } relocate it
"anchor_frame":u32,        // blk+0x3CC8 at capture
"build_id":    String,     // pin the game build; determinism holds for identical builds ONLY
```

### Capturing the anchor

The capture loop already reads `[blk, blk+0x33B18)` every frame. When
`blk+MODE_OFF` byte[2] transitions to `1` (character select) and no anchor is held for this match,
**keep that buffer** — gzip it and stash it. That is the entire cost: no extra read, no extra RPM.

```rust
// blk+0x3CB8 byte[2]:  1 = CHARACTER SELECT, 2 = IN BATTLE
let mode2 = buf[MODE_OFF + 2];
if mode2 == 1 && st.anchor.is_none() {
    st.anchor       = Some(gzip_bytes(&buf[..0x33B18]));   // ~17 KB compressed
    st.anchor_blk   = blk;
    st.anchor_arena = rpm_u64(h, exe_base + 0xac6d40).unwrap_or(0);
    st.anchor_frame = u32le(&buf, 0x3CC8);
}
```

⚠ **Character select only.** A battle-state anchor is NOT portable — it holds 557 pointers into the
decompressed per-character asset image, and relocation fixes their addresses but not the fact that
the bytes there belong to whichever characters that session loaded. It crashed the game twice.
At character select nothing is loaded, so nothing dangles.

⚠ **Take it at a frame boundary.** Read `blk+0x3CC8` before and after the copy and discard the
capture if it moved — otherwise a torn snapshot ships. Online, also record `G+0x76C`; a non-zero
rollback count during capture means the frame you snapshotted may have been re-simulated.

---

## Size

| | |
|---|---|
| anchor (once per match) | 211,736 B → **~17 KB gzip** |
| `seat_in[2]` per frame | 8 B raw, ~2 B/frame compressed |
| **5-minute match** | **~50 KB** — and it reproduces the match EXACTLY |

Today's tape is ~188 KB and cannot reproduce assists, projectiles, effects, stage or HUD at all.

---

## Staging

Bump to **0.3.24**, build, publish to the staging channel, download and install, then play one
match. Verify from the uploaded tape:

1. `schema` ends with `seat_in[2]`
2. `seat_in[0]` is non-zero on frames you pressed something, and its value set DIFFERS from
   `p1_in` (proving it is the raw word, not the decoded one)
3. `seat_map` is present and not all zeros
4. `anchor` is present, ~17 KB, and `anchor_blk` / `anchor_arena` are non-zero
5. `rollbacks` is 0 for an offline match

Then a server-side re-simulation of that tape should reproduce the match — the check being that the
derived winner/damage matches what the existing stats layer reported independently.

## Explicitly NOT in scope

- Removing the existing columns. Keep writing them; this is additive and reversible.
- The draw-list objects at `blk+0x2f4d0` (assists/projectiles/effects). The server gets those free
  by re-simulating — capturing them would be duplicated work.
