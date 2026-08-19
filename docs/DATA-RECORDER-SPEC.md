# MetaSync Data Recorder — Spec (`.mvctape`)

Status: **DESIGN** (2026-08-18). Owner: tristech. Supersedes the ad-hoc `capture_start/stop` + `/gamestate` batch path.

## 0. Goal

Record **all live game state on every client, continuously, with zero measurable impact on the game** — feeding tournament stats, replays, and the ML/AI pipeline from one canonical stream. Out-of-process only (no injection into the closed Steam game). The reader must never block the game or the GUI.

Non-goals: frame-perfect *input reconstruction* / deterministic replay (impossible out-of-process on the Steam recompile — see §6; that's the maplecast/flycast path). We record **resolved state**, not a re-simulatable input log.

---

## 1. Why out-of-process (and why NOT a shim)

The maplecast `.mctele` exporter is an **in-process** hook — it works because flycast is **open source** and we recompiled it. The Steam "MARVEL vs CAPCOM Fighting Collection" is closed; injecting a streaming shim there is high-risk (Proton/anti-cheat, maintenance) for little gain. We already read it out-of-process today (Win32 `ReadProcessMemory` / Linux `process_vm_readv`) with no frame-loop impact. The recorder formalizes that into a dedicated, always-on, decoupled pipeline.

```
        GAME PROCESS (untouched)
                │  RPM / process_vm_readv  (read-only, ~µs/frame)
                ▼
   ┌─────────────────────────┐   wait-free SPSC (rtrb), drop-oldest on overflow
   │  SAMPLER thread @60Hz    │ ───────────────────────────────────────────────┐
   │  spin_sleep deadline pace│                                                 │
   │  quanta TSC timestamps   │                                                 ▼
   └─────────────────────────┘                                   ┌──────────────────────────┐
                │ writes latest snapshot (seqlock)               │  WRITER/UPLOADER thread   │
                ▼                                                 │  • roll frames → .zst chunk│
   ┌─────────────────────────┐   reads latest (never blocks)     │  • append to live tape     │
   │  GUI (Tauri commands)    │ ◀──────────────────────────────  │  • POST chunk → server     │
   │  overlay / dashboard     │   optional PINE-style local sock  └──────────────────────────┘
   └─────────────────────────┘
```

The sampler is the only thread that touches the game. It hands frames to the writer over a **wait-free ring** and never waits on disk or network — that is the "zero impact" guarantee.

---

## 2. The frame schema (`repr(C)` POD)

One fixed-size record per sampled frame. `#[repr(C)]` + `bytemuck::Pod` → the record IS its bytes (`&[u8]` for free, no serializer on the hot path). All multi-byte fields little-endian. Sizes are illustrative — the **header size-table (§4) is authoritative**, so fields can be appended without breaking old parsers.

```rust
#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct FighterState {   // one per active fighter slot (up to 6: even=P1 side, odd=P2 side)
    slot: u8,           // 0..5 (slot*STRIDE = cl); even = P1, odd = P2
    char_id: u8,        // OFF_CHARID 0x554  (map to name via §5 lookup)
    color: u8,          // cl+0x6 variant/color
    on_point: u8,       // is this the active point character
    health: u16,        // OFF_HEALTH 0x40c (0..144)
    red_health: u16,    // OFF_REDHP  0x410 (recoverable)
    x: i32, y: i32,     // position  (offsets TBD — add in a schema bump)
    action_state: u16,  // animation/action id (offset TBD)
    hitstun: u16,       // (offset TBD)
    flags: u32,         // block/invuln/airborne bitfield (offset TBD)
}

#[repr(C)]
#[derive(Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
struct FrameRecord {
    // ── identity / timing (ALWAYS first, never reordered) ──
    game_frame: u32,    // the game's OWN fine per-frame counter (hunt_frame_counter) — the SPINE
    sample_seq: u32,    // our monotonic sample index (dedup/gap accounting)
    t_mono_ns: u64,     // quanta TSC timestamp at sample
    stable: u8,         // 1 = <= finalized watermark (§6), 0 = tentative
    n_fighters: u8,
    // ── match context ──
    in_match: u8,       // session+0x1cd (1 = round live)
    phase: u8, round_no: u8, win_result: u8, stage: u8,
    timer: u32,
    set_p1: u8, set_p2: u8,      // set-score tally  sc+0xbc / +0xbd
    local_side: i8,              // localPlayerNum (0=P1, 1=P2, -1=spectator)
    meter_p1: u8, meter_p2: u8,  // MET_BARS/FILL
    // ── inputs (pre-frame intent) ──
    input_p1: u16, input_p2: u16,   // OFF_INPUT on slots 0 & 1
    // ── fighters ──
    fighters: [FighterState; 6],
}
```

Design choices (from Slippi prior art):
- **Anchor everything to `game_frame`** (the game's internal counter), not our sample index — non-negotiable for dedup + rollback handling.
- **Split intent from resolved state**: `input_p1/p2` = pre-frame intent (great for AI); the `FighterState` array = post-resolution state (great for stats). Same record carries both.
- **Append-only fields.** New fields (positions, action-state, velocities as offsets get pinned) go at the END of `FighterState`/`FrameRecord`, and the size-table header lets old parsers skip them. Never reorder.

---

## 3. Match session boundaries

A **session** = one contiguous set in one lobby. Detected by edge-watching (LiveSplit ASL pattern — keep prev vs current):
- **start**: `in_match` 0→1 with a fresh `set_p1==0 && set_p2==0`, or `read_my_lobby` gaining both player SteamIDs.
- **end**: set tally reaches the FT target, or the lobby member set drops, or `in_match` stays 0 for N seconds.

Each session gets its own tape file with a header carrying the SteamIDs, side map, char picks, and lobby id. The recorder is **always sampling**; sessions just bracket the interesting frames (menu frames compress to nothing).

---

## 4. File format (`.mvctape`) — self-describing, append-only

Layout mirrors Slippi's winning choices (size-table header + append-only events + uncompressed metadata for indexing):

```
[MAGIC "MVCT"][u16 format_version]
[HEADER  (UNCOMPRESSED JSON)]  ← indexable server-side without decompressing the body:
   { schema_version, offset_map_version, recorded_at, app_version, platform,
     tournament_id?, match_id?, lobby_id?, players:[{steamid,side,name,team?}], notes }
[RECORD-TYPE TABLE]            ← Slippi 0x35 lesson: id → byte-size for every record type
   { 0x01 FrameRecord: <bytes>, 0x02 FighterState: <bytes>, 0x10 SessionStart, 0x11 SessionEnd, ... }
[BODY: length-prefixed records]   ← live, row-order, crash-safe, tail-able
```

- **Live path**: append raw length-prefixed `FrameRecord`s (row order) — simplest, crash-safe, resumable, tail-able by a live consumer.
- **Rotation = the compressed chunk**: the writer accumulates ~1s of frames → `zstd` → `tape-<seq>.zst` (header + type-table left plaintext/uncompressed for indexing) → hands the path to the uploader → starts the next chunk. (crate: hand-rolled rotor or `rolling-file`.)
- **Archive/compaction (offline job)**: transpose finished sessions to **columnar (Arrow) + zstd** (peppi `.slpp` lesson) — ~2× smaller and far faster for Polars/ML scans (`frames.health[n]` vs `frames[n].health`). Optionally Parquet for cold storage. Never on the 60Hz path.

**Versioning** (Slippi lesson): `schema_version` bumps on any field addition; fields tagged with the version they appeared in; `offset_map_version` ties the file to the exact offset map used (see §5) so a mis-pinned offset era is identifiable and re-derivable.

---

## 5. Offset map as DATA, not code

Our offsets churn (health `0xb44`→`0x40c`, the array pointer chain, etc. — the memory notes are a graveyard of this). Every prior-art tool (Cheat Engine `.CT`, dolphin-memory-engine, RetroAchievements, LiveSplit ASL) converges on: **express the memory map as versioned data; the recorder is a generic engine that reads it.** Ship a new map, not a new binary, when an offset moves.

`offsets/mvc2-steam.toml` (versioned):
```toml
version = 7
[exe_globals]
session_ptr   = 0xacd3a8   # → session object
localplayer   = 0xac7230   # localPlayerNum
set_score_ptr = 0x2edf628  # → sc block
[array]                    # fighter array (volatile base → pointer-follow / fingerprint at attach)
pointer_path = [0xac6ef0, 0x3f24]
stride       = 0x738
[fighter]                  # {offset, type} per field, RA code-note style
health    = { off = 0x40c, ty = "u16" }
red_hp    = { off = 0x410, ty = "u16" }
char_id   = { off = 0x554, ty = "u8"  }
input     = { off = "OFF_INPUT", ty = "u16" }
[session]
active    = { off = 0x1cd, ty = "u8" }   # 1 = round live
hosted    = { off = 0xd0320, ty = "u32" }
[lookup.char_id]           # RA Rich-Presence style value→label
214 = "Strider"   # ⚠ unit order = PalMod roster, NOT Ryu-first
# ...
```
Reads are addressed relative to **named regions** resolved at attach (libretro/BizHawk lesson) so they survive ASLR/relocation. `offset_map_version` in every tape header == the schema era.

---

## 6. Out-of-process realities (the honest part)

We poll at ~60Hz from outside; the game runs its own loop with rollback. Consequences and mitigations (Slippi's in-process hook avoids all of these — we can't):

1. **Sample≠frame drift** → duplicate reads (same `game_frame` twice) and gaps (missed frames on a stall/rollback burst). **Mitigation:** dedup on `game_frame`; treat gaps as expected, not corruption; keep `sample_seq` + a `dropped_frames` counter for accounting.
2. **No true "finalized frame."** We can sample a mid-rollback / re-simulated state. **Mitigation:** emulate Slippi's finalized index with a **watermark = current `game_frame` − safety margin**; mark records `stable=1` at/below it, `stable=0` above. Downstream **stats consume only stable frames**; a live scoreboard/overlay may show tentative.
3. **Can't perfectly reconstruct from inputs** (the Steam build is a native recompile; state-cloning is a proven dead-end per the RE notes). **Mitigation:** bias the schema toward **resolved post-state**; keep inputs too (cheap, good for AI) but never treat them as source of truth.

---

## 7. Threading & pacing

- **Sampler**: deadline loop — keep an absolute `next = next + 16_667µs`, `spin_sleep::sleep_until(next)`, stamp with `quanta::Instant` (TSC, ~ns, no syscall). Avoids cumulative drift and the Windows `Sleep()` 15.6ms floor. On Windows also `timeBeginPeriod(1)`.
- **Handoff**: `rtrb` wait-free SPSC ring sized for a few seconds of frames. On full → **drop-oldest + bump `dropped_frames`** (telemetry, shedding is fine). The sampler never allocates or blocks.
- **Writer/uploader**: drains the ring, appends to the live tape, rolls zstd chunks, uploads. Slow disk/network only ever backs up the ring (→ drop-oldest), never the sampler.
- **GUI snapshot**: sampler also publishes the latest `FrameRecord` into a seqlock/`ArcSwap` the GUI reads lock-free — no round trip to the game for live display.

Cost budget: reading ~6 fighters × ~10 fields + ~10 globals = a few dozen small `process_vm_readv`/RPM calls per frame, batched by region. That's the same work the current reader already does; at 60Hz it is negligible and out-of-process, so the game's frame loop is untouched.

---

## 8. Transport

- **Live upload**: POST each `tape-<seq>.zst` chunk to `/skinsync/gamestate` (already exists) with `{tournament_id?, match_id?, session_id, seq, sha256}`; server appends to the session's object. Resumable by `seq`. Uncompressed header lets the server index without decompressing.
- **Local fan-out (optional, later)**: expose the live stream over a **PINE-style local socket** (batched typed reads, one round trip/frame) so an overlay, the AI trainer, and a dashboard all read ONE feed instead of each attaching to the game. Copy PINE's batched-request design even if not the protocol itself.
- **Keep the recorder dumb**: it stores raw state only. Stats/ELO/AI features are computed **downstream** (slippi-js pattern) so a schema change never invalidates stored tapes.

---

## 9. Crate shortlist (adopt)

| Role | Crate | Why |
|---|---|---|
| Module base / region discovery | **`proc-maps`** (rbspy) | one API for Win module-base + Linux `/proc/pid/maps`; kills our most platform-divergent code |
| Process discovery | `sysinfo` | find PID by name (attach only, not per-frame) |
| Reads | keep hand-rolled RPM / `process_vm_readv` | `read-process-memory` is a near-identical wrapper — no hot-path win |
| Frame pacing | **`spin_sleep`** | sub-ms deadline pacing, dodges Windows 15.6ms floor |
| Timestamps | **`quanta`** | TSC, ~ns, no syscall |
| Handoff | **`rtrb`** | wait-free SPSC; sampler never blocks |
| Encode | **`bytemuck`** (+ `#[repr(C)]`) | free `&[u8]`, no serializer on hot path |
| Compress | **`zstd`** (or `lz4_flex` if CPU-bound) | 8–12× on fixed-layout rows; beats gzip |
| Zero-copy replay (opt.) | `rkyv` | mmap a tape, cast to `&Archived<Frame>` |
| Analytics archive (offline) | `arrow` / `parquet` | columnar for Polars/ML; never on 60Hz path |
| Rolling | hand-rolled chunk rotor (or `rolling-file`) | chunk = rotation = upload unit |

---

## 10. What we reuse from today's code

Already built (`src-tauri/src/sync.rs`) — the recorder wraps these, doesn't replace them:
- `find_game_pid` / `game_exe_base` / `mem::Proc` reads (cross-platform, and the Linux argv[0] pid fix).
- `hunt_frame_counter` — already distinguishes the fine per-frame counter from the coarse one (fixed the old 6Hz decimation). This is the `game_frame` spine.
- The offset table (STRIDE/OFF_*/MET_*/exe globals), `read_set_score`, `read_session_active`, `read_my_lobby`, `GSlot`/`GameSt`.
- `CAPTURING` capture thread + `/skinsync/gamestate` upload — evolve from on-demand-batch to always-on-streaming.

---

## 11. Build plan (phased)

1. **Schema + map** — pin `FrameRecord`/`FighterState` as `#[repr(C)]`; extract the offset table into `offsets/mvc2-steam.toml` (v7) + a loader. Ship the size-table header + versioning. *(No behavior change; the current capture starts writing the new record.)*
2. **Decoupled sampler** — move sampling to a `spin_sleep`+`quanta` deadline loop feeding an `rtrb` ring; writer drains → live `.mvctape` + zstd chunks. GUI reads the seqlock snapshot. Verify game frametime unchanged (it will be — out-of-process).
3. **Always-on + sessions** — edge-detect session start/end; always sample; bracket sessions; finalized watermark → `stable` flag.
4. **Upload streaming** — chunked resumable upload to `/gamestate`; server stores per-session; keep header plaintext for indexing.
5. **Downstream** — offline compaction to Arrow+zstd; a reference parser (Rust + Python) + a published `.mvctape` spec (the real reason Slippi's ecosystem exists). Feed the ML pipeline from the columnar archive.
6. **(Optional) PINE-style local socket** — one live feed for overlay/trainer/dashboard.

---

## 12. Open items / TBD offsets

- Pin position `x/y`, `action_state`, `hitstun`, and the block/invuln `flags` offsets in the fighter struct (schema bump when done — append only).
- Confirm the finalized-watermark safety margin empirically against a rollback-heavy match.
- Decide zstd level for the live chunk path (speed vs ratio) on Steam Deck.
