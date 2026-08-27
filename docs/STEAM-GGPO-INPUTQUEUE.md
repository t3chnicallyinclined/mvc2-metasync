# Steam MvC2 — GGPO's confirmed input ring, located

**Found 2026-08-27 via Ghidra on the Steam binary.** This is the structure GGPO's own spectate and
record paths read. It replaces the 1-frame latch at `G+0x218` that the agent currently polls.

## Why the latch is the wrong read

`G+0x218` is the post-`SynchronizeInputs` latch. For the **remote** seat it holds a **prediction**
whenever the peer's packet is late, and GGPO's predictor repeats the last confirmed input verbatim —
so a poller records a lag-smeared opponent. The local seat is never predicted (`AddLocalInput` stamps
the frame and queues it *before* the frame simulates), so only half of each recorded word is trustworthy.

GGPO's own recorder never samples a pad. It waits until a frame is **confirmed**, reads it from the
ring below, writes it once, and advances a monotonic cursor:

```c
while (_next_spectator_frame <= total_min_confirmed) {
   input.frame = _next_spectator_frame;
   _sync.GetConfirmedInputs(input.bits, ..., _next_spectator_frame);
   if (config::RecordMatches) AddToReplay(input);
   _next_spectator_frame++;
}
```

Predictions are never stored in `_inputs` — `_prediction` is a **separate member**. So reading the
ring is not "filtering out predictions"; it is structurally incapable of returning one.

## The chain — CONFIRMED (read from the decompilation)

```
session   = *(u64*)0x142E10B98        // ggpo session handle
sync      = session + 0x9F0           // the Sync object
queues    = *(u64*)(sync + 0x190)     // Sync::_input_queues  (heap array, has an array cookie at -8)
nplayers  = *(i32*)(sync + 0x174)
delay     = *(i32*)(sync + 0x178)     // frame delay
queue[k]  = queues + k * 0xE44        // sizeof(InputQueue) == 3652
```

Evidence, `FUN_14011c8e0` = `Sync::Init`:

```c
uVar14 = *(int *)(param_1 + 0x174);                 // num_players
uVar6  = 0xe44 * uVar14;                            // stride 0xE44
puVar8 = FUN_14011fb40(uVar6 + 8);                  // + array cookie
*puVar8 = uVar14; puVar8++;
for (; uVar14; uVar14--) { FUN_14011a190(puVar11, 4); puVar11 += 0xe44; }   // ctor, input_size = 4
*(ulonglong **)(param_1 + 400) = puVar8;            // _input_queues @ Sync+0x190
FUN_14011a500(queues + i*0xe44, i, *(param_1+0x178));  // InputQueue::Init(id, frame_delay)
```

Both session entry points store the handle in the **same** global:

| function | is | stores |
|---|---|---|
| `FUN_140119950` | `ggpo_start_session` (P2P) | `DAT_142e10b98`, backend `0x2AD88` B |
| `FUN_1401199d0` | `ggpo_start_spectating` | `DAT_142e10b98`, backend `0x85C0` B |
| `FUN_14011a8a0` | Peer2PeerBackend ctor | `Sync` at `+0x9F0` |
| `FUN_140118290` | region registration | see below |
| `FUN_140119380` | `save_game_state` | — |

Other decoded API: `FUN_140119930(s,3000)` set_disconnect_timeout · `FUN_140119920(s,1000)`
disconnect_notify_start · `FUN_1401198c0(s,player,&handle)` add_player · `FUN_140119940(s,h,delay)`
set_frame_delay. `input_size = 4` — four bytes per player, i.e. the two u32s we already read.

⚠ `FUN_14011d120` is **UdpProtocol** (stride `0x5FA8`), NOT InputQueue — it has a vtable and three
`GameInput::init(-1,0)` calls. The `new[]` in the backend constructor is the endpoint array. Do not
confuse the two; both are `new[]`-allocated with a cookie.

## Inside one InputQueue — INFERRED (upstream layout, size-matched)

`sizeof(InputQueue) == 0xE44 == 3652` is **exactly** upstream GGPO's size, so the fork did not change
the layout and the upstream offsets should hold:

| field | offset | note |
|---|---|---|
| header (`_id,_head,_tail,_length,_first_frame,_last_user_added_frame,_last_added_frame,_first_incorrect_frame,_last_frame_requested,_frame_delay`) | +0 | 40 B |
| **`_inputs[128]`** | **+40** | `GameInput`, stride **28** |
| `_prediction` | +3624 | separate — never a stored input |

Arithmetic closes exactly: `40 + 128*28 = 3624`, `3624 + 28 = 3652 = 0xE44`.

```c
GameInput { i32 frame; i32 size; u8 bits[20]; }   // stride 28, size == 4 here
```

**Read frame `f`:** `e = _inputs + (f % 128) * 28`; valid iff `*(i32*)e == f`. Lifetime is 128 frames
= **2.13 s at 60 Hz**, so a 250 ms poll has ~8x margin. Both queues together are ~7 KB — cheaper than
one `read_gs_row`.

⚠ **VERIFY LIVE BEFORE BUILDING ON IT.** One match settles it: with a fight running, confirm
`_inputs[f%128].frame == f` and `.size == 4` for the current `f` (= `blk+0x3CC8`), and that
`_last_added_frame` (header) tracks the newest valid entry. If those hold, the inferred offsets are
confirmed. If not, scan for the signature instead: a run of >=64 records at a fixed stride where
dword0 increments by 1 and dword1 is constant `4`; back up 40 bytes for the header.

## Bonus: the registration struct

`FUN_140118290` reads the registered region out of a **struct**, not a flat global:

```c
DAT_142d10950 = 1;                                             // region count
DAT_142d107d0 = *(longlong *)(PTR_DAT_140acd3a0 + 0x1b0);      // base -> blk
DAT_142d108d0 = *(int *)(PTR_DAT_140acd3a0 + 0x1b8);           // size -> 0x33B18
if (*(uint *)(PTR_DAT_140acd3a0 + 0x48) < 3) { ... }           // the multi-region arm
```

⚠ `PTR_DAT_140acd3a0` is a **pointer that gets dereferenced**. `replay-kit/netprobe.py` reads
`G_SEL = EXE + 0xAC6D40 + 0x48` **flat**, which is a different address — its live read of `11` may
have been coincidence. Re-derive against `*(u64*)0x140ACD3A0 + 0x48` before trusting the fork arm.
Also note `blk` is independently reachable as `*(*(u64*)0x140ACD3A0 + 0x1b0)`.

`Sync::Init` also zeroes `*(u32*)(PTR_DAT_140acd3a0 + 0x770)` — adjacent to the rollback counter we
read at `G+0x76C`. Worth reconciling which base that counter actually hangs off.

## What this unlocks

1. **Correct inputs.** Confirmed values for both seats instead of predicted remote ones.
2. **A slow poll.** 250 ms instead of 3 ms — the rollback-burst race disappears, since corrections
   are already finalized in the ring rather than flashing through a latch for microseconds.
3. **The host-node plan.** If the node is a GGPO participant (see `netprobe_linux.py`), it can read
   BOTH seats' confirmed inputs from one process and stamp the true pair.

Related: `docs/STEAM-GGPO-DETERMINISM.md`, `docs/TAPE-V2-SCHEMA.md`,
`docs/patches/agent-0.3.25-frame-clock.md`.
