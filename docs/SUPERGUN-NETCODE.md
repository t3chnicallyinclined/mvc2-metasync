# SUPERGUN NETCODE — measured baseline, architecture comparison, recommended design (2026-09-04)

Lane: senior-re-generalist / SUPERGUN NETCODE. Design + measurement pass only; **no transport code is written yet**.
Companion lanes: SUPERGUN ENGINE (Gate 3 arc loader, `d3dcap/receipt/`) · RECEIPT RUNNER (`docs/WORKSTREAM-RECEIPT-RUNNER.md`).
Artefacts this pass: `d3dcap/net/sg_bench.cpp` + `d3dcap/net/build.bat` (new, mine) ·
`maplecast-flycast/tools/re_kb/117_supergun_netcode_baseline.surql` (applied; backup `re_kb_data/_exports/re_kb_20260904-145333_pre117.surql`).

## RE METHOD (restated; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. **Seed with unique constants, then propagate along the call graph.**
3. Translate globals through the block map before comparing reference sets.
4. **Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.**

**Step this document is at: 2 and 4.** The seeds were upstream GGPO's magic constants
(`2000/500/200/1000` poll intervals, `40/10/3/9` timesync window, `8` max prediction, `0x1C` UDP_HEADER_SIZE,
`0x1020` message allocation). Every one of them landed on a Steam function; the reference read to confirm them
is the vendored upstream at `C:\Users\trist\projects\maplecast-flycast\core\deps\ggpo\lib\ggpo`
(`timesync.h`, `sync.h`, `sync.cpp`, `input_queue.cpp`, `network/udp_msg.h`, `backends/p2p.cpp`).
No top-down trace of a symptom was performed. All pairs and findings are in `re_kb` (9 findings, 13 routines,
6 globals, seed 117).

**Tags used throughout: CONFIRMED** = both sides read and agreeing, or reproduced by a numeric gate ·
**INFERRED** = derived from confirmed numbers or fingerprint only · **UNKNOWN** = not located, with the test named.

---

## 0. The honest headline, before any design

> **The large latency win available to SUPERGUN is not a networking win. It is an engine win that
> unlocks a policy change.**

The shipped game pays **66.7 ms of unconditional input delay** (GGPO frame delay 4) in order to avoid
**0.42 ms of CPU** (8 frames of rollback, measured). It does that because GGPO's defaults were written for
engines whose frame costs 5–16 ms. MvC2's recompiled frame costs **0.047 ms** (measured, §1.1). Removing the
frame delay and raising the speculation cap is worth tens of milliseconds. Everything genuinely
*networking* — raw UDP, dual paths, 120 Hz sends, redundancy — is worth **single-digit milliseconds of p99
and a large reduction in loss-induced stalls**, not tens of milliseconds.

> **"Our network will run better than Steam's" is UNPROVEN and remains so after this pass.** I have no
> measurement of what Steam's transport adds over the wire path. §5 Gate N4 is the specific, cheap test that
> would settle it using the agent's existing `ReadProcessMemory` path — no hooking, no new RE.

---

## 1. What I MEASURED

All host measurements taken 2026-09-04 on the dev machine (Windows 11 26200, `HIGH_PRIORITY_CLASS` +
`THREAD_PRIORITY_TIME_CRITICAL`, QPC 10 MHz). Per-machine numbers; the load-bearing quantity is the **ratio**
to the 16.667 ms frame budget, which is three orders of magnitude.

### 1.1 The sim tick — CONFIRMED

Harness: `C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe` on
`d3dcap\ttd\runs\receipt-20260903-stage9-anchor\pre` (the Gate 1 anchor). Timings from `summary.json`'s `ms` array.

| run | n | min | p50 | p90 | p99 | max | mean | total |
|---|---|---|---|---|---|---|---|---|
| idle, 3000 ticks | 3000 | 0.0201 | **0.0342** | 0.0541 | 0.0763 | 0.2798 | 0.0376 | 112.9 ms |
| real match inputs, 300 ticks | 300 | 0.0183 | **0.0390** | 0.0834 | 0.1578 | 0.1692 | 0.0473 | 14.2 ms |

**3000 frames of real MvC2 simulation in 113 ms of CPU — 26.5 simulated frames per millisecond.**

This is not an approximation of the engine: `FUN_140118950` is the function the shipped game calls per online
frame, and — CONFIRMED by decompiling `FUN_140118f00` — it is *the same call* GGPO's `advance_frame` callback
makes on every rollback re-simulation frame. **The measured number is literally the shipped cost of one
rollback frame.**

### 1.2 The rollback state — CONFIRMED

`d3dcap\net\sg_bench.cpp state`. Region = `0x33B18` = 211,736 B, the single registered GGPO region.

| operation | ring depth | min | p50 | p90 | p99 | max | mean |
|---|---|---|---|---|---|---|---|
| save (blk → ring) | 8 | 0.0034 | **0.0042** | 0.0046 | 0.0091 | 0.0261 | 0.0043 |
| restore (ring → blk) | 8 | 0.0033 | **0.0042** | 0.0048 | 0.0058 | 0.0133 | 0.0043 |
| save | 60 | 0.0033 | 0.0046 | 0.0064 | 0.0212 | 0.0381 | 0.0054 |
| restore | 60 | 0.0034 | 0.0049 | 0.0074 | 0.0114 | 0.0295 | 0.0054 |
| save | 120 | 0.0103 | **0.0206** | 0.0314 | 0.0457 | 0.0804 | 0.0220 |
| restore | 120 | 0.0068 | 0.0168 | 0.0245 | 0.0377 | 0.0650 | 0.0176 |
| FNV-1a hash of the whole region | — | 0.0241 | **0.0248** | 0.0260 | 0.0326 | 0.0467 | 0.0252 |

**A full 211,736-byte savestate costs 4 microseconds.** The cliff at ring depth 120 is the 25 MB working set
leaving cache — that is the real bound on the save ring, not CPU. Desync-detect hashing is 25 µs.

### 1.3 Host pacing — CONFIRMED

`d3dcap\net\sg_bench.cpp timer`. This bounds how late input can be sampled before the tick.

| mechanism | p50 | p99 | max |
|---|---|---|---|
| `Sleep(1)` actual duration (identical with and without `timeBeginPeriod(1)`) | 1.50 ms | 2.55 ms | 2.74 ms |
| `CREATE_WAITABLE_TIMER_HIGH_RESOLUTION` deadline **overshoot** | 0.58 ms | 0.70 ms | 1.08 ms |
| busy **spin to a QPC deadline**, overshoot | 0.00003 ms | 0.0085 ms | 0.143 ms |
| QPC granularity | 100 ns | | |

**No sleep primitive on this OS hits a deadline better than ~0.6 ms. Spinning hits it at ~10 µs.**
Sampling input as late as possible before the tick is worth ~0.6 ms and costs a burned core.

### 1.4 UDP socket floor — CONFIRMED

`d3dcap\net\sg_bench.cpp udp`, loopback ping-pong (OS + stack only, zero wire time).

| payload | RTT p50 | RTT p99 | RTT max | `sendto()` p50 |
|---|---|---|---|---|
| 16 B | 0.0574 | 0.0958 | 0.2138 | 0.0228 |
| 64 B | 0.0569 | 0.1190 | 0.2429 | 0.0226 |
| 256 B | 0.0556 | 0.0939 | 0.2342 | 0.0223 |
| 1200 B | 0.0561 | 0.1070 | 0.3762 | 0.0224 |

**Cost is flat from 16 B to 1200 B.** Packet *size* is free in host time up to the MTU; only bandwidth is a
constraint. This single result decides the redundancy strategy in §4. The whole OS socket path is 0.057 ms =
0.34 % of a frame.

### 1.5 Wire RTT from this host — CONFIRMED (single vantage point)

`15.204.141.58` (rise3, our prod server): min 9 / avg 10 / max 11 ms, 0 % loss over 8 · `1.1.1.1`: 4/5/7 ·
`8.8.8.8`: 3/4/6. **This machine is 10 ms from our own relay candidate.** Cross-country and inter-player RTT
are **UNKNOWN** — §6 U6.

---

## 2. What the SHIPPED path actually does — CONFIRMED by decompilation

The Steam build's online path is **upstream GGPO with only the transport replaced**. Every upstream constant
was found and cross-checked against vendored source: `MAX_PREDICTION_FRAMES 8`, `FRAME_WINDOW_SIZE 40`,
`MIN_UNIQUE_FRAMES 10`, `MIN_FRAME_ADVANTAGE 3`, `MAX_FRAME_ADVANTAGE 9`, `SYNC_RETRY_INTERVAL 2000`,
`SYNC_FIRST_RETRY_INTERVAL 500`, `NUM_SYNC_PACKETS 5`, `RUNNING_RETRY_INTERVAL 200`, `KEEP_ALIVE_INTERVAL 200`,
`QUALITY_REPORT_INTERVAL 1000`, `NETWORK_STATS_INTERVAL 1000`, `UDP_SHUTDOWN_TIMER 5000`, `UDP_HEADER_SIZE 28`,
`MAX_COMPRESSED_BITS 4096`, `RECOMMENDATION_INTERVAL 240`, the event enum `1000..1007`, and the TIMESYNC
handler copied verbatim from the upstream *sample*. **Nothing was retuned for a 60 Hz fighting game.**

### 2.1 The per-frame driver `FUN_140118dd0` — CONFIRMED

```c
uint32 FUN_140118dd0(uint32 local_pad) {          // called from FUN_14003a520 at 0x14003a9aa
   if (local_handle != -1) {
      inputs = local_pad;                          // pad decoded by FUN_14003ad50 in the SAME function, same frame
      if (ggpo_add_local_input(session, handle, &inputs, 4) != OK)
          goto skip;                               // <-- PREDICTION THRESHOLD: THE WHOLE FRAME IS DROPPED
   }
   if (ggpo_synchronize_input(session, &buf16, 16, &flags) == OK) {   // 4 seats x 4 B
      FUN_140118950(&DAT_142d10b90, &buf16, flags);                    // THE SIM TICK
      ggpo_advance_frame(session);
   }
skip: ...
}
```

`FUN_140118f00` (the `advance_frame` callback used during rollback) is the same three calls without the
local-input step. `FUN_140118ae0` builds the callback struct, calls `ggpo_start_session(..., input_size=4, port)`,
`set_disconnect_timeout(3000)`, `set_disconnect_notify_start(1000)`, then `set_frame_delay(handle, delay)`.

### 2.2 The four latency terms owned by GGPO — CONFIRMED

| # | term | measured / read value | mechanism |
|---|---|---|---|
| 1 | **Frame delay** | **4 frames = 66.7 ms**, unconditional | `*(PTR_DAT_140acd3a0 + 0x27C)` ← `*(*(u64*)(DAT_140acd3a8+0xD04B8)+0x48)` (a lobby/match setting) → `ggpo_set_frame_delay`. Live `Sync+0x178 == 4` (ringdiag.py, ranked match). Upstream `InputQueue::AdvanceQueueHead` does `frame += _frame_delay`, so the local input is consumed 4 frames after it is pressed. |
| 2 | **Speculation cap** | **8 frames** | `Sync+0x18C == 8` live; upstream `MAX_PREDICTION_FRAMES`. Measured cost of exhausting it: **0.42 ms**. |
| 3 | **Hard local freeze** | whenever `framecount − last_confirmed ≥ 8` | `Sync::AddLocalInput` returns false; `FUN_140118dd0` skips the frame entirely — no tick, no advance. This is the online stutter players feel. `FUN_14003a520` counts consecutive such frames and raises a UI flag at 600 (10 s). |
| 4 | **TIMESYNC stall** | **`Sleep(frames_ahead × 1000/60)`, up to 9 frames = 150 ms**, at most one per 240 frames | `FUN_140119010` case 5 calls IAT slot `0x1408DB248` = `KERNEL32!Sleep` (resolved by same-boot export resolution, `iat_map.txt`). `frames_ahead` from `FUN_14011cdc0` = `TimeSync::recommend_frame_wait_duration`, clamped to `MAX_FRAME_ADVANTAGE = 9`. A blocking sleep on the game thread. |

### 2.3 The wire — CONFIRMED

* `FUN_14011e230` = `UdpProtocol::SendInput`: pushes into `_pending_output` and calls `SendPendingOutput`
  **immediately** ⟹ **one input packet per frame, 60 Hz.**
* `FUN_14011e3d0` = `SendPendingOutput`: XOR-delta + run-length bit-encodes **every un-ACKed input** into one
  message ⟹ **redundant retransmission of the un-ACKed history is already the shipped behaviour.** A SUPERGUN
  design cannot claim redundancy as a novelty — only a different cadence, encoding and path count.
* `FUN_14011df90` = `UdpMsg::PacketSize`: **Input = `0x20 + ceil(bits/8)`**, InputAck 10, sync/quality 9,
  keepalive 5. Steady state ⟹ **~32–40 B payload at 60 Hz per direction ≈ 4.1 KB/s (33 kbit/s) with the 28 B
  IP+UDP header.**
* `FUN_14011d100` = `Udp::SendTo` **replaced**: ignores flags/addrlen, calls
  `FUN_1400692E0(netmgr, sin_port /* = the peer slot */, buf, len)`. The sockaddrs are built from the literal
  `"192.168.0.%d"` at `0x1408DD5C0`, so the IP is decorative and the peer identity travels in the port field.
* `FUN_1400692E0` prefixes **4 bytes** (`u8 type = 7`, `u16 len`) and calls
  `FUN_14034DB60(*(DAT_142EBCCB8+0x250), buf, len+4, target, 0x10, 7)`.
* Transport: **`SteamNetworking005` is the ONLY Steam networking interface string in the image** (fetched in
  `FUN_14003EE40` into slot [8]). No `SteamNetworkingSockets`, no `SteamNetworkingMessages`. That is Valve's
  **legacy** `ISteamNetworking` P2P — NAT punch with SDR relay fallback.
* Pads: **`XINPUT1_3.dll`** plus `SteamController006`. `FUN_14003AD50` decodes the pad immediately before
  `add_local_input` in the same function, so there is **no extra input queue between poll and sim** — the only
  controllable term there is *when in the frame* the poll happens (UNKNOWN, §6 U3).

### 2.4 Input-to-photon decomposition, and who owns each term

| term | value | ours? |
|---|---|---|
| switch → USB HID report | 1–8 ms, pad-dependent (125–1000 Hz) | **no** (pad hardware) |
| XInput driver → `XInputGetState` return | ~0–1 ms | no (could be bypassed with RawInput/HID; small) |
| poll → tick (sampling phase) | 0–16.7 ms depending on where in the frame we poll | **YES** — worth up to 16 ms, measurable, §6 U3 |
| **GGPO frame delay** | **66.7 ms** | **YES — the single biggest controllable term** |
| sim tick | **0.047 ms measured** | ours, already negligible |
| rollback re-sim when a correction lands | **0.42 ms at depth 8, measured** | ours, already negligible |
| render + present + swapchain queue | UNKNOWN for this title; `config.ini` on this install has `VSYNC=OFF`, `RenderingThread=OFF` | partly ours, §6 U4 |
| display scanout + panel | 4–16 ms | no |
| **network one-way, for the OPPONENT's input** | RTT/2; inside the prediction window it costs a rollback, outside it costs a freeze | **YES** |

---

## 3. Architecture comparison — with the measured numbers

> ⚠ **UPDATED — see §11.3.** Architecture **D (server/client authoritative) is RULED OUT for default play**,
> on latency, by arithmetic rather than measurement: architecture E's latency is `min(direct, relay)` and D's
> is `relay`, always. No outcome of N3 or N4 can reverse that. D's one genuinely strong property — structural
> cheat-proofing — is answered instead by the **witness** (§11.4), at zero latency cost.

Notation: `d` = local input delay in frames, `P` = speculation cap in frames, `owd` = one-way delay in frames
(`RTT / 2 / 16.667`), `f` = frame budget 16.667 ms. Per-frame rollback cost from §1.1 + §1.2, using the
conservative real-input tick mean 0.047 ms and the ring-depth-appropriate save cost:

> **cost(N) = restore + N × (tick + save)**
> N=2 → 0.11 ms (0.6 % of f) · N=8 → **0.42 ms (2.5 %)** · N=16 → 0.83 ms (5.0 %) · N=30 → **1.55 ms (9.3 %)** ·
> N=60 → 3.10 ms (18.6 %) · N=120 → 8.3 ms (50 %, ring leaves cache) · N=240 → ~16.8 ms (**over budget**).
> At the p99 tick (0.158 ms): N=30 → 4.9 ms (29 %). **INFERRED, not confirmed — Gate N1 settles it (§5).**

| architecture | local input latency | opponent-input latency | CPU per frame | stalls | verdict |
|---|---|---|---|---|---|
| **A. Delay-based, no rollback** | `d ≥ owd + jitter` → **50–100 ms** typical | 0 extra | ~0 | none while `d` holds; visible input drop when it does not | Zero artifacts. Latency is the product. Not competitive. |
| **B. GGPO peer rollback — THE INCUMBENT (measured)** | **66.7 ms** (`d=4`) | 0 extra inside window | **0.42 ms worst case** | **freeze when `owd > d+P = 12 frames ≈ 200 ms RTT`; `Sleep` up to 150 ms per TIMESYNC** | **Pays 66.7 ms of latency to save 0.42 ms of CPU.** That trade is only rational for a 10 ms/frame engine. |
| **C. Zero-delay deep speculation (`d=0`, large `P`)** | **~0 ms of network-induced delay**; only the sampling phase | 0 extra | **cost(owd)**: 0.13 ms at 80 ms RTT; 1.55 ms at a 30-frame burst | none until `owd > P`; with `P=30` that is **1 s RTT** | **The opportunity.** Cost is not CPU — it is misprediction visibility (§4.3). |
| **D. Server/client authoritative rollback** | same as C locally | `owd` via the server, i.e. `RTT(A,S)/2 + RTT(S,B)/2` | same as C plus server sim | server can smooth, never freezes for NAT reasons | Buys cheat resistance, guaranteed connectivity, one clock, a clean spectator/RAIL feed. **Costs a hop unless the relay is on-path.** |
| **E. Hybrid — direct P2P *and* relay in parallel, take first arrival** | same as C | **`min(direct, relay)`** | same as C | relay covers the NAT failures and the direct-path loss bursts | **Recommended.** Latency is provably ≤ direct; loss resilience is the product of two independent paths; the relay has to exist anyway for NAT. Costs 2× upstream — measured to be nothing (§1.4). |

**Why the incumbent's numbers are what they are.** `MAX_PREDICTION_FRAMES = 8` exists because a typical
engine costs 5–16 ms per frame, so 8 catch-up frames is 40–130 ms and does not fit in a frame budget.
MvC2 costs **0.047 ms**. The same wall-clock catch-up budget buys **~250 frames**, and the practical bound is
not CPU but the save ring's cache footprint (§1.2) and misprediction visibility. **This is the entire SUPERGUN thesis
and it now rests on two measurements rather than on an adjective.**

---

## 4. Engineering decisions the measurements force

### 4.1 Raw UDP with no framing — mostly a myth, with two real wins
Measured (§1.4): the socket path is 0.057 ms RTT and **flat to 1200 B**. So "no protocol overhead" is worth
microseconds, not milliseconds. The two real wins are:
1. **No coalescing / no Nagle.** Whether the shipped path buffers is **UNKNOWN** (§6 U1: the `EP2PSend` flag).
   If it uses `k_EP2PSendUnreliable` rather than `...NoDelay`, every input eats a buffering delay. **This is
   the one place where "our transport is better than Steam's" could be literally true, and it is unmeasured.**
2. **No reliability layer.** A retransmit-and-wait layer is fatal for rollback; GGPO already avoids it and so must we.
Keep authenticated encryption (ChaCha20-Poly1305 on a ~300 B packet is well under 1 µs) — dropping crypto buys
nothing measurable and costs integrity.

### 4.2 Redundancy and pacing — decided by "size is free"
Because packet cost is flat to the MTU, **abandon GGPO's XOR-RLE encoder and send a raw sliding window of the
last K frames of input in every packet.** With 4 B/frame/seat: K=64 → 256 B + header ≈ 288 B, still one MTU,
still 0.022 ms to send. **A 64-frame window makes any burst of up to 64 consecutive lost packets invisible with
zero retransmission logic.**

Cadence: send at 120 Hz, not 60. A lost packet then costs 8.3 ms of staleness instead of 16.7 ms.
Bandwidth (per direction, per path): 120 × 288 B = **34.6 KB/s = 277 kbit/s**; two paths = 553 kbit/s.
That is ~17× the shipped 33 kbit/s (§2.3) — trivial on a good line, not free on a bad one. **Make cadence and
window adaptive** (60 Hz / K=32 = 77 kbit/s floor), driven by measured loss, never by a guess.

**No jitter buffer.** A jitter buffer is the correct tool for delay-based netcode and is *pure added latency*
in a rollback scheme where re-simulation is 0.047 ms/frame. Jitter is absorbed by rollback depth. This falls
straight out of the measurement.

**No coalescing, ever.** Waiting to batch is added latency with no measured benefit.

### 4.3 Input prediction — the actual limiting factor, and the right metric
CPU is not the constraint on deep speculation; **misprediction visibility is.** GGPO predicts by repeating the
last confirmed input verbatim — decent for held directions, poor for button presses.

The trap to avoid: **bit-accuracy of the prediction is the wrong metric.** Many mispredictions are harmless
(a button pressed during recovery frames changes nothing). The right metric is the **visible state delta** —
how far `sim(predicted)` diverges from `sim(true)` in the columns a viewer can see (px, py, hp, sprite id,
drawn flags) as a function of rollback depth. **That is measurable offline and deterministically with the
runner we already have** (Gate N2, §5).

Candidate predictors, in order of what must be beaten:
1. **repeat-last** (GGPO baseline) — the mandatory control.
2. **decay-to-neutral after k frames** — cheap, plausible; may be worse (causes stop-start).
3. **learned / behaviour-cloned predictor** conditioned on recent inputs and game state. We already have the
   corpus (tapes) and the pipeline (`../mvc2-ai`, Python BC + `.mctele` exporter, per memory
   `mvc2-ai-pipeline`). ⚠ that pipeline targets the **DC/NAOMI** build, not Steam — reusing it is a port, not
   a drop-in.
   **Falsification: if the learned predictor's visible-delta distribution is not stochastically dominated by
   repeat-last's at every depth 1..30, it does not help and is dropped.**

### 4.4 Replacing the TIMESYNC `Sleep`
The shipped stall is a blocking `Sleep` of up to 150 ms. Replacement: **continuous fractional clock
adjustment** — hold the frame-advantage at target by varying the local frame period by ≤1 % (0.17 ms/frame),
which the measured spin-to-deadline precision (10 µs, §1.3) can express exactly. Imperceptible against a
150 ms hard stall. Gate: a two-node run in which frame-advantage stays bounded with **zero** frames whose
period exceeds 1.02×.

### 4.5 NAT traversal — the honest position
UDP hole punching fails for symmetric-NAT and CGNAT pairs. The commonly cited success rate for plain punching
is roughly 80–90 % of pairs (**INFERRED from published measurements, NOT measured here**). Two consequences:
1. **A relay is required regardless**, so architecture E's second path costs nothing extra to *build*.
2. The success rate **for our population is measurable and we already own the fleet to measure it** — the
   agent runs on ~15 machines. Gate N3b (§5) instruments them. `maplecast-flycast` vendors `libjuice` and has
   `core/network/ice.cpp` — an ICE implementation to read, not reinvent.

### 4.6 When a relay genuinely beats direct P2P
Real cases, all testable rather than assumed: (a) ISP pairs whose BGP path is worse than each side's path to a
well-peered datacenter — triangle-inequality violations are common on the public internet; (b) one side has a
bufferbloated last mile but a clean path to the DC; (c) asymmetric routing producing one-directional jitter.
Measured anchor: this host is **10 ms from rise3**. Whether `RTT(A,rise3)/2 + RTT(rise3,B)/2 < RTT(A,B)/2` for
real player pairs is **UNKNOWN** and is exactly what Gate N3 counts. Architecture E does not need to *predict*
the answer — it races both paths every packet and takes the winner.

---

## 5. Recommended design and its falsifiable gates

**SUPERGUN v1 = architecture E: zero-delay deep-speculation rollback over dual-path raw UDP.**

| parameter | value | justification |
|---|---|---|
| local frame delay `d` | **0** | tick is 0.047 ms; the 66.7 ms the incumbent spends buys 0.42 ms of CPU |
| speculation cap `P` | adaptive, **cap 30 frames** (0.5 s) | measured cost(30) = 1.55 ms mean / 4.9 ms at p99 tick = 9–29 % of budget |
| save ring | 64 slots (13.5 MB) | measured cliff between ring 60 (0.005 ms) and ring 120 (0.021 ms) |
| desync detect | FNV-1a over the region every 30 frames | measured 0.025 ms |
| input sampling | spin-to-deadline immediately before the tick | measured 10 µs vs 0.6 ms for any sleep primitive |
| transport | raw UDP, authenticated, **two parallel paths** (direct + relay), take first arrival | measured: packets are free; the relay must exist for NAT anyway |
| cadence | 120 Hz adaptive down to 60 Hz | halves loss-induced staleness for 277 kbit/s |
| payload | raw sliding window, last 64 frames × 4 B/seat, + frame number + ACK watermark + periodic state hash | measured: size is free to the MTU |
| jitter buffer | **none** | rollback absorbs jitter at 0.047 ms/frame |
| clock sync | continuous ≤1 % frame-period adjustment | replaces a 150 ms blocking `Sleep` |
| prediction | repeat-last in v1; anything else must beat it on Gate N2 | the control must exist before the experiment |

### The gates — each names what would DISPROVE the design

**Gate N1 — interleaved rollback cost AND rollback state sufficiency. THE BLOCKING GATE.**
*This is the one that can kill the design, and it is not yet run.*
Add a `--rollback N` mode to `rr_runner.exe` (**ENGINE lane owns `d3dcap/receipt/` — coordinate before writing**):
per tick, save `blk` to a ring; every frame, restore N frames back and re-tick N frames with the recorded
inputs; assert the resulting `blk` is **byte-identical** to what was originally computed for that frame.
Report wall time per frame at N ∈ {0,2,4,8,16,30,60,120}.
* **Disproves the cost model** if the interleaved per-frame time is materially above `restore + N×(tick+save)`
  (cache interference between a 212 KB memcpy and the tick's ~37 KB read set, `docs/FRAME-READSET.md`).
* **Disproves the state model** if resimmed `blk` ≠ original `blk`. The shipped game restores *only* `blk`, so
  `blk` is rollback-sufficient **for the shipped process** — but our runner additionally touches the lazily
  committed host device page (`*(0x140acd3a8)`, PALETTE_RAM +0xD8D04) and leaves a residual in the ctx page
  table (`RECEIPT-RUNNER-GATE1.md` §3.4/§3.5). If our renderer ever *reads* those, rollback must cover them
  too. **This is a real, specific, untested risk and no netcode work should proceed past it.**

**Gate N2 — prediction quality, deterministic and offline.**
For a recorded input pair and each depth k ∈ 1..30: run the runner from frame f with (a) the true remote input
and (b) the predicted remote input; report the distribution of the **visible state delta** (px, py, hp, sprite
id, drawn) at f+k. Compares repeat-last against any candidate.
* **Disproves "prediction X helps"** if X's delta distribution is not dominated by repeat-last's at every depth.
* Reuses `receipt_gate.py` / `runner_gate.py` column machinery — no new oracle, no live game, fully deterministic.

**Gate N3 — transport floor, two-node.** `sg_probe` on rise3 and locally: timestamped 300 B packets at 120 Hz
for a sustained run; report clock-offset-corrected one-way delay distribution, loss, reordering, and
**burst-loss length** distribution, for direct / relayed / both-paths-min.
* **Disproves the dual-path claim** if `min(direct, relay)` p99 one-way is not below direct p99.
**N3b:** the same probe across the ~15 agent machines to measure **our** population's NAT punch success rate and
relay-wins-over-direct rate. Turns §4.5's inferred 80–90 % into a measured number.

**Gate N4 — what Steam's transport actually adds. This is what makes "better than Steam" provable.**
No hooking and no new RE required: during a live online match, read the GGPO `UdpProtocol` endpoint's
`_round_trip_time` at **`endpoint+0x2068`** (and `_kbps_sent` at `+0x2074`) with the agent's existing
`ReadProcessMemory` path, while `sg_probe` measures raw UDP RTT between the same two machines at the same time.
**The difference is Steam's transport overhead.** Two of our own machines in a lobby is a complete experiment.
* **Disproves "our network beats Steam's"** if the delta is not materially positive.
⚠ Confounder to control (this project's recurring failure mode): both measurements must be **simultaneous and
between the same machine pair**, never a Steam match on one day compared with a probe on another.

**Gate N5 — desync is a byte gate, not an opinion.** Any SUPERGUN session must reproduce `blk` byte-for-byte
against the deterministic reference; `runner_gate.py`'s existing comparison is that gate unchanged.

### Sequencing
N1 first — it can invalidate the design. N4 next — it is cheap and it is the only thing that converts the
project's headline claim from a hope into a number. N2 and N3 are parallel and independent. No transport code
before N1 passes.

---

## 6. UNKNOWN list — what I could not establish, and the test for each

| # | UNKNOWN | Why it matters | Test that settles it |
|---|---|---|---|
| U1 | **Which `EP2PSend` flag the shipped path passes to `ISteamNetworking::SendP2PPacket`.** The call is below `FUN_1400692E0` → `FUN_14034DB60` → vtable `+0x38` of `*(netmgr+0x18)`; that implementation is **not located.** | `k_EP2PSendUnreliable` buffers, `...NoDelay` does not. This is the single place where "our transport beats Steam's" could be literally true. | Ghidra: resolve the `+0x38` vtable slot of the object at `netmgr+0x18` (its constructor is reachable from `DAT_142EBCCB8+0x250`). Or live: hook `SendP2PPacket` and log the flag. |
| U2 | **Resolution and update cadence of the engine ms clock** `FUN_14003ABA0` = `*(double*)(DAT_142EBC8B8 + 0x40140) × DAT_1408DD5D0`. | Every GGPO interval and `_round_trip_time` — and therefore the whole timesync loop — is quantised by it. If it advances once per frame, GGPO measures RTT at 16.7 ms granularity. | Sample that double at 1 kHz from an external reader during a match; look at the step size. |
| U3 | **Where in the frame the pad is polled**, relative to the tick and to present. | Worth up to a full 16.7 ms of the controllable budget. | Instrument the live game: timestamp `XInputGetState` return and the `FUN_140118950` entry in the same frame. |
| U4 | **The game's present/swapchain path and its frame queue depth.** `config.ini` on this install has `VSYNC=OFF`, `RenderingThread=OFF`, but those are one user's settings. | 1–3 frames of queued presentation is 16–50 ms. | `steam-d3d11-capture-expert` lane: read the `IDXGISwapChain::Present` sync interval, `SetMaximumFrameLatency`, and whether a waitable swapchain object is used. |
| U5 | **Live values of GGPO's debug `_send_latency` (`endpoint+0x2C`) and `_oop_percent` (`+0x30`).** `PumpSendQueue` honours both. | If non-zero in the shipped build, the game is deliberately adding latency or reordering. | One `ReadProcessMemory` of those two ints during a match. Cheap; do it with Gate N4. |
| U6 | **Real inter-player RTT distribution**, cross-country and otherwise. My only wire measurements are from one vantage point (§1.5). | Every latency claim in §3 is parameterised by `owd`. | Gate N3b across the agent fleet. |
| U7 | **Whether the frame delay is user-selectable, region-derived or fixed per mode.** The path to `ggpo_set_frame_delay` is CONFIRMED; the *source* of the value is a lobby-object field. | Determines whether the 66.7 ms is a fixed baseline or already varies. | Read `*(*(u64*)(DAT_140acd3a8+0xD04B8)+0x48)` across ranked / casual / lobby / regions. |
| U8 | **Interleaved rollback cost and rollback-state sufficiency for OUR runner.** §1.1 and §1.2 were measured **separately**; the composed number in §3 is INFERRED. | It is the headline of the whole design. | **Gate N1.** |
| U9 | **The visual cost of deep mispredictions**, in units anyone can argue about. | It is the true limiting factor on `P`, not CPU. | **Gate N2** produces the distribution; a human judgement then sets the cap. |

---

## 7. Address / artefact index (new in this document)

`FUN_140118dd0` per-frame online driver · `FUN_140118f00` advance_frame callback · `FUN_140118ae0` session
bring-up (`set_disconnect_timeout 3000`, `set_disconnect_notify_start 1000`, `set_frame_delay`) ·
`FUN_140119010` on_event (case 5 TIMESYNC → `Sleep` via IAT `0x1408DB248`) · `FUN_14011cdc0`
`TimeSync::recommend_frame_wait_duration` (40/10/3/9) · `FUN_14011e220` `RecommendFrameDelay` ·
`FUN_14011d940` `UdpProtocol::OnPoll` (2000/500/200/1000/28) · `FUN_14011e740` `SetLocalFrameNumber` ·
`FUN_14011e230` `SendInput` · `FUN_14011e3d0` `SendPendingOutput` · `FUN_14011e310` `SendMsg` ·
`FUN_14011e000` `PumpSendQueue` · `FUN_14011df90` `PacketSize` · `FUN_14011d100` `Udp::SendTo` (replaced) ·
`FUN_1400692E0` transport shim (4-byte prefix, type 7) · `FUN_14034DB60` net-manager send ·
`FUN_14003A520` netplay session start · `FUN_14003AD50` pad decode · `FUN_14003ABA0` GGPO ms clock ·
`FUN_14003EE40` Steam interface fetch.
Globals: frame delay `*(PTR_DAT_140acd3a0+0x27C)` ← `*(*(u64*)(DAT_140acd3a8+0xD04B8)+0x48)` ·
`Sync = *(0x142E10B98)+0x9F0` (`+0x174` players, `+0x178` delay, `+0x184` last-confirmed, `+0x188` framecount,
`+0x18C` max prediction, `+0x190` queues) · endpoint `+0x2068` RTT, `+0x2074` kbps, `+0x2C` send_latency,
`+0x30` oop_percent · `"SteamNetworking005"` `0x1408DE368` · `"192.168.0.%d"` `0x1408DD5C0` ·
`"XINPUT1_3.dll"` `0x140980B20`.
Harness: `d3dcap/net/sg_bench.cpp` (+`build.bat`) · `d3dcap/receipt/runner/rr_runner.exe`.
Graph: seed `maplecast-flycast/tools/re_kb/117_supergun_netcode_baseline.surql` (applied 2026-09-04;
9 findings — 6 confirmed, 1 inferred, 2 open).

---

# 8. U1 and U2 CLOSED — the Steam P2P send flag and the GGPO clock (appended 2026-09-04)

Method step **2** (seed with a unique constant / argument shape, then propagate along the call graph) and **4**
(tag and store). Graph seeds: `maplecast-flycast/tools/re_kb/119_supergun_p2p_send_and_clock.surql` (applied;
backup `re_kb_data/_exports/re_kb_20260904-151244_pre118.surql` — named `pre118` because this seed was applied
**as 118** and renumbered to 119 the same day, the ENGINE lane having already taken 118 for
`receipt_runner_gate3`) plus `120_supergun_citation_fix.surql` (applied; backup
`re_kb_20260904-151946_pre120.surql`), which repairs the two `note` strings that had already gone into the live
graph citing the now-wrong 118 and hardens the buffering-cost item so it cannot read as settled. §6 U1 and U2
are now `resolved` in the graph; one new `open` item replaces them.

> **Seed numbering (agreed 2026-09-04):** SUPERGUN NETCODE takes **even** numbers from 120 up (120, 122, 124…);
> the RECEIPT RUNNER / ENGINE lane takes **odd** (121, 123…). Seeds 119 and 120 are order-independent — they
> carry the same two `note` strings, so re-applying 119 does not regress 120 (verified by replay).
> ⚠ Re-applying any seed prints `N failed`; on a replay those are `RELATE … already exists` idempotency
> artefacts, not real failures. `UPSERT` nodes and `UPDATE` fields converge; only the explicit-id `RELATE`
> edges error. Check the messages before treating a non-zero count as a problem.

## 8.1 U1 — the flag is `k_EP2PSendUnreliable` (0). CONFIRMED.

**`ISteamNetworking::SendP2PPacket` is called from exactly five places in the whole binary, and every one of
them passes the literal `0` — `k_EP2PSendUnreliable`, the BUFFERING mode. `k_EP2PSendUnreliableNoDelay` (1)
appears nowhere.**

Two independent enumerations were run and they return the *same five sites*:

1. **Machine-code argument shape.** In the MSVC x64 ABI, `SendP2PPacket(CSteamID, const void*, uint32,
   EP2PSend, int)` puts `eP2PSendType` in the **5th** slot, i.e. `mov dword ptr [rsp+0x20], imm32` before a
   vtable **slot-0** call. Scanning the mapped image for `C7 44 24 20 0? 00 00 00` followed within 56 bytes
   by `FF 10` / `FF 50 00` returns 4 hits in game code (a 5th is inside the Enigma packer region and is
   unrelated).
2. **Call-graph propagation.** `xrefs_to 0x140A34D90` → 235 references across 72 functions; decompiled all 72
   and grepped for a slot-0 call on `*(singleton+0x40)` → 5 hits.

| site | payload | `cubData` | `eP2PSendType` | channel |
|---|---|---|---|---|
| `FUN_14015C030` | literal `"Steam"` `0x140922A78` | 6 | **0** | 0 |
| `FUN_14015C0F0` | literal `"SteamQosReq"` `0x140922A80` | 12 | **0** | 0 |
| `FUN_14015C0F0` | literal `"SteamQosAns"` `0x140922A90` | 12 | **0** | 0 |
| `FUN_14016E8C0` | literal `"Steam"` `0x14092468C` | 6 | **0** | `this[0xff]` |
| **`FUN_14016ECF0`** | **`param_3` (caller-supplied)** | **`param_4`** | **0** | `this[0xff]` |

**The chain, CONFIRMED end to end.** `FUN_14003EE40` fetches `SteamNetworking005` into **slot `+0x40`** of the
Steam interface struct; every consumer reaches it as
`steam = (*DAT_1408DB898)(&PTR_FUN_140A34D90); ISteamNetworking = *(steam+0x40)`. `FUN_14016ECF0` is virtual
**slot 15 (`+0x78`)** of the concrete transport class whose MT Framework class-registry name string is
**`"Steam"`** (`0x14092468C`, vtable `0x140924698`). It first calls `ISteamNetworking` vtable `+0x30` =
`GetP2PSessionState` and requires `m_bConnectionActive`, then calls vtable `+0x00` = `SendP2PPacket(steamID,
pubData, cubData, 0, channel)`.

> **The class names came out of the image without symbols.** MT Framework lays each class registry entry out
> as `[ctor qword][ASCII class name][vtable]`, so scanning for `nNetwork::*` recovered the whole networking
> class set (`Session`, `SessionDriver`, `SessionListener`, `SessionDatabase`, `Transport`, `Protocol*`,
> `Route`, `Match`, `Member`, …). That technique is reusable and is recorded in seed 119.

**Why "GGPO input packets take this path" is a deduction, not a guess.** Four of the five sites transmit fixed
6- and 12-byte literals. GGPO's Input message is `0x20 + ceil(bits/8)` = 32–40 bytes of variable payload (§2.3).
It is therefore none of the four, and `FUN_14016ECF0` is the only remaining sender. The one escape hatch — a
**cached** `ISteamNetworking*` copied into a variable or global, whose users my enumeration would miss — was
checked and **does not exist**: no store of `*(steam+0x40)` appears anywhere in the decompiled corpus; every
send re-fetches through the singleton.

**Correction to §6 U1's guess at the route.** I predicted the send sat under `FUN_1400692E0` →
`FUN_14034DB60` → vtable `+0x38` of `*(netmgr+0x18)`. That chain is real but **`nNetwork::SessionDriver`
(vtable `0x1409646B0`, 104 slots) has no subclass in the image** — its slots 6 and 7 are still the
pure-virtual stub `FUN_140036560`, and only its own ctor/dtors reference the vtable. The concrete sender is a
*different* class (`"Steam"`). Recorded so nobody re-walks `SessionDriver` looking for the sender.

### What this changes
`k_EP2PSendUnreliable` is documented by Valve as the mode that **may buffer** before sending (that is precisely
what `...NoDelay` exists to opt out of). So **the shipped path pays a send-batching delay on every input packet
that a raw-UDP SUPERGUN transport simply would not pay.** This is the first concrete, attributable term where
"our transport is better than Steam's" is *structurally* true rather than hopeful.

**But do not oversell it, and do not let this become a confident wrong number.** What is CONFIRMED is the
**flag**. What is **UNKNOWN** is **how many milliseconds that flag actually costs**: the buffer window lives
inside `steamclient`, not in the game image, and Valve does not document it for the legacy
`ISteamNetworking` path. It cannot be read statically. **Gate N4 is unchanged and is still the gate** — it
measures the whole Steam transport overhead end to end, of which this buffering is one term. New graph item
`finding:supergun_steam_send_buffering_cost_unknown` (status `open`) carries it.

**Priority consequence:** the transport work moves up, because it now has a named structural defect to beat
rather than only a p99 argument. It does **not** move above Gate N1, and it does not change §0 — the 66.7 ms
frame delay is still the dominant term and still an engine-enabled policy win.

## 8.2 U2 — GGPO's clock is frame-quantised. CONFIRMED.

`FUN_14003ABA0` (= GGPO `Platform::GetCurrentTimeMS`) reads `*(double*)(DAT_142EBC8B8 + 0x40140) × DAT_1408DD5D0`.
**Only four functions in the entire image touch displacement `0x40140`**: the reader, an initialiser
(`FUN_140038430`), the netplay session start (`FUN_14003A520`, also a read), and one writer — `FUN_1400388F0`:

```c
lVar10 = FUN_14011F310();                                   // = QueryPerformanceCounter (IAT 0x1408DB1E0)
*(longlong*)(ctx + 0x40160) = lVar10;                       // raw counter
*(int*)     (ctx + 0x40170) = (int)lVar10 - *(int*)(ctx + 0x40168);   // tick delta
*(longlong*)(ctx + 0x40168) = lVar10;                       // previous counter
dVar19 = (double)lVar10 * *(double*)(ctx + 0x40188);        // ticks -> seconds
*(double*)  (ctx + 0x40140) = dVar19;                       // <-- THE VALUE GGPO READS
*(double*)  (ctx + 0x40148) = dVar19;
*(float*)   (ctx + 0x40150) = (float)(dVar19 - dVar1);      // frame delta time
```

A function that computes `deltaTime = now − lastNow` and stores `lastNow` **is** the per-frame update by
construction; `+0x40150` is then used as the frame-rate divisor, and `FUN_1400388F0` is referenced from exactly
one place — slot 7 (`+0x38`) of the vtable at `0x1408DD460`.

**So: the source is high-resolution QPC, but the value GGPO sees is latched once per frame — quantised to
~16.67 ms.**

### What it breaks, and what it does not
* **Not affected:** the `200 / 1000 / 2000 / 5000 ms` poll, keep-alive, quality-report and sync-retry intervals.
  Frame granularity is far below all of them.
* **Affected, and it matters:** `_round_trip_time`. `FUN_14011E740` = `SetLocalFrameNumber` computes
  `_local_frame_advantage = (rtt × 60 / 1000 + last_received_input.frame) − local_frame`. The `× 60 / 1000`
  converts ms to frames, so **a one-frame RTT quantisation is exactly one frame of frame-advantage error.**
* **The averaging does not save it.** `TimeSync` averages over `FRAME_WINDOW_SIZE = 40`, which suppresses
  zero-mean noise — but RTT is a slowly varying quantity, so its rounding is a **persistent bias** that holds
  across the whole window rather than cancelling. Against `MIN_FRAME_ADVANTAGE = 3`, a persistent 1-frame error
  is **a third of the decision threshold**, and both endpoints quantise independently.

⟹ **The shipped `Sleep(frames_ahead × 1000/60)` stall of up to 150 ms (§2.2 term 4) is driven by a
measurement that cannot resolve better than one frame.** That is an argument for §4.4's replacement
(continuous ≤1 % clock adjustment) on *correctness* grounds and not only on smoothness grounds — and SUPERGUN
must timestamp from QPC directly at send/receive, never from a frame-latched clock. Measured backing already
exists: QPC granularity is 100 ns and spin-to-deadline resolves 10 µs (§1.3).

## 8.3 U3 and U4 — not attempted, deliberately

Both need the client to exist and a live instrumented run; neither falls out of static analysis. They remain
as scoped in §6 (together worth up to 16–50 ms, mostly ours to control — likely more than the transport).
Not blocking.

## 8.4 Updated UNKNOWN ledger

| # | status |
|---|---|
| U1 Steam P2P send flag | **CLOSED — `k_EP2PSendUnreliable` (0) at all five sites** |
| U2 GGPO clock resolution | **CLOSED — frame-latched from QPC, ~16.67 ms granularity** |
| **U10 (new)** how many ms `k_EP2PSendUnreliable` buffering actually costs | **OPEN** — inside `steamclient`, unreadable statically. **Gate N4.** |
| U3 pad poll position in frame · U4 present/swapchain queue depth | OPEN, need the client |
| U5 live `_send_latency` / `_oop_percent` · U6 inter-player RTT · U7 frame-delay source variation | OPEN as before |
| U8 interleaved rollback cost + rollback-state sufficiency | OPEN — **Gate N1, ENGINE lane, still blocking** |
| U9 visual cost of deep mispredictions | OPEN — Gate N2 |

## 8.5 Address index (new in §8)

`FUN_14016ECF0` the only general P2P send (transport vtable `0x140924698` slot 15, `eP2PSend = 0`) ·
`FUN_14016E8C0` peer poke (slot 18) · `FUN_14015C030` / `FUN_14015C0F0` handshake and QoS probes ·
`FUN_14003EE40` Steam interface fetch (`+0x40` = ISteamNetworking) · `DAT_1408DB898` singleton getter ·
`PTR_FUN_140A34D90` singleton descriptor · `FUN_1400388F0` per-frame timing update (vtable `0x1408DD460`
slot 7) · `FUN_140038430` timing init · `FUN_14011F310` QPC wrapper (IAT `0x1408DB1E0`) ·
`nNetwork::Session` ctor `FUN_14034BD40` / vtable `0x140964BA0` / name `0x140964B88` ·
`nNetwork::SessionDriver` vtable `0x1409646B0` (abstract, no subclass) ·
Session array `*(DAT_142EBCCB8 + 0x250 + 8k)`, k = 0..3.

---

# 9. Design specified against Gate N1 (appended 2026-09-04)

Gate N1 is **PASSED** by the SUPERGUN ENGINE lane (`docs/RECEIPT-RUNNER-GATE-N1.md`, seed 121). The blocker in
§5 is cleared and §4 moves from sketch to specification. Graph seed for this section: `122_supergun_design_v1.surql`.

**The result that matters most is not the timing — it is that the assumption was false.** The shipped `blk`-only
save set is **insufficient for our runner**: it diverges from depth 2 up at `blk+0x1D6FC` = DC `0x8C27B034` =
object-pool node 144 field `+0x124`, a sprite-walker placement field. `blk` + the GGPO counter +
`ctx+0x1F8230..0x1F8238` passes at every depth. Had §5 been built on "the shipped game persists `blk`, therefore
`blk` is the rollback state", zero-input-delay would have shipped as desyncs. That is exactly the layer-assignment
error this lane exists to prevent, and the engine lane caught it by measuring instead of composing.

## 9.1 One correction to §1.2 of Gate N1 — the amortised column is eligibility-weighted

> ⚠ **SUPERSEDED IN PART — see §11.1.** The correction below stands and the ENGINE lane acted on it (the
> amortised column is withdrawn). But the *per-event numbers I reconstructed here are themselves superseded*
> by N1b's direct per-event measurement with p99/max. A reconstruction is not a substitute for a measurement.

The Gate N1 cost table is labelled *"worst case (a rollback fired on every frame)"*, but the **amortised ms/frame**
column is not that. A depth-`N` rollback is only eligible after tick `k ≥ N`, so over a 200-tick run there are
`200 − N` events, and the column divides by all 200 frames. At depth 120 only **80 of 200 frames (40 %)** carried a
rollback. That is why depths 60 and 120 read as equal (2.316 vs 2.327) even though per-event resim goes 3.007 → 5.183.

Reconstructing the column as `(200−N)/200 × (restore + resim) + save` reproduces all eight rows to within
p50-vs-mean noise, which confirms the mechanism rather than assuming it:

| depth | events | **per-EVENT = save+restore+resim** | **% of 16.667 ms** | Gate N1 amortised | model | resim per tick |
|---|---|---|---|---|---|---|
| 0 | 200 | 0.011 | 0.1 % | 0.018 | 0.011 | — |
| 2 | 198 | 0.072 | 0.4 % | 0.088 | 0.071 | 0.0301 |
| 4 | 196 | 0.145 | 0.9 % | 0.187 | 0.142 | 0.0316 |
| 8 | 192 | **0.255** | **1.5 %** | 0.286 | 0.245 | 0.0295 |
| 16 | 184 | 0.740 | 4.4 % | 0.721 | 0.682 | 0.0438 |
| 30 | 170 | **1.153** | **6.9 %** | 1.083 | 0.982 | 0.0372 |
| 60 | 140 | **3.046** | **18.3 %** | 2.316 | 2.138 | 0.0501 |
| 120 | 80 | **5.230** | **31.4 %** | 2.327 | 2.106 | 0.0432 |

**The per-EVENT column is the number the design must budget against**, because in a zero-delay scheme at a steady
one-way delay of `k` frames you roll back `k` frames on *every* frame, with no eligibility gap.

**Nothing about the headline changes.** At the shipped depth of 8 the true worst case is **0.255 ms = 1.5 % of a
frame** against **66.7 ms of frame delay** — §0 is now measured end to end rather than composed from two separate
measurements, and it is if anything sharper. What changes is the **ceiling**: a 120-frame ring costs **31 %** of a
frame, not 14 %, and a 60-frame ring costs **18 %**, not 14 %. Those are the numbers the cap is set from in §9.4.

The per-tick resim rate rising from ~0.030 ms (depths 2–8) to ~0.044–0.050 ms (depths 16–120) is the same cache
effect this lane measured standalone (tick p50 0.034 idle / 0.039 real-input, §1.1) and is internally consistent.

## 9.2 The save set — SPECIFIED, and deliberately wider than what was proven minimal

**SUPERGUN save set = `blk[0..0x33B18)` + the GGPO counter (`0x142d10b90`, 0x10 B) + `ctx[0x1F0000..0x200000)`
= 211,752 + 65,536 = 277,288 B.**

Gate N1 proved the *minimum* is `blk` + counter + **8 bytes** (`ctx+0x1F8230..0x1F8238`, two f32, each half
required alone) = 211,760 B. **We are not shipping the minimum, on purpose.** Two of Gate N1's own caveats say
the minimum is not known to be the minimum anywhere else:

* **Caveat 1** — measured on **one** stage-9 offline receipt. Whether a larger ctx window is required on another
  stage, camera or HUD-heavy frame is OPEN.
* **Caveat 2** — the per-frame **reader** of those 8 bytes is **UNKNOWN**. No literal `0x1f8230` displacement
  exists in the 10,803-function disassembly cache, so the access is *indexed*. An indexed read whose index we
  cannot see is an index that can move.

Shipping an 8-byte window because 8 bytes were proven on one frame of one stage is precisely the
"verified against the wrong thing" failure this project keeps repeating. The insurance is almost free, and
Gate N1's own bisection already proved the supersets pass on this stage:
`1F8000-1F9000` **PASS** (4 KB) and `1F0000-200000` **PASS** (64 KB).

**Cost of the insurance, from this lane's measured copy-cost scaling (§1.2):** 65,536 B = **0.0012 ms** p50 per
copy. At the cap of 32 that is +0.04 ms per rollback event — **+0.24 % of a frame** — to remove a whole class of
stage-dependent desync. Taking it is not a close call.

Why not save all 4 MB of ctx (which also PASSed, as `simctx`): scaling the same measurement, 4 MB ≈ **0.09 ms**
per save, so at depth 32 it would add ~2.9 ms/event — that *would* force the cap down. 64 KB is the right point
on the curve.

> **Falsification of §9.2:** if the Gate 4 per-stage ladder finds a required ctx byte **outside**
> `0x1F0000..0x200000`, this decision is wrong and the window must widen (Gate N1c, §9.9). If it finds required
> bytes scattered across ctx, the save set becomes the whole 4 MB and the cap must drop to ~8 — which would
> still beat the shipped 66.7 ms, but the deep-speculation thesis would be dead. **That is the observation that
> would disprove the design, and it has not been made yet.**

**Mechanism of the `blk`-only failure — INFERRED, and worth stating so it is not re-derived.** The two f32 sit
in the NaomiLib projection/viewport block (Gate N1 §3, `FUN_140846a40` writes them wholesale) next to the
world-camera focal length `±812.357` and the ground offset `−338.4`. The field that diverges is a **sprite-walker
placement** field. So the walker's per-frame output plausibly depends on that projection state; restore `blk`
without it and the walker places a node differently. Consistent with every measurement, not confirmed.

## 9.3 The save ring — depth, and the rotation rule the cache cliff dictates

Gate N1 reproduced this lane's cache cliff *interleaved* and identified its cause precisely: restore p50 rises
0.0045 ms (207 KB ring) → ~0.024 ms (24 MB ring), ~5×, **while the per-event copy stays 211 KB**. The cliff is the
ring's **working set**, not the copy size. That has a direct design consequence:

* **Allocate 65 slots** (65 × 277,288 = 18.0 MB) so a deep recovery is always possible, **but rotate modulo
  `active_cap + 1`, not modulo the allocated count.** A player on a clean 40 ms link runs `active_cap = 4`, touches
  5 slots = **1.4 MB**, and never pays the cliff at all. A player on a bad link pays it only while the link is bad.
* At the default cap of 32 the working set is 33 × 277,288 = **9.15 MB** — just past Gate N1's depth-30 measurement
  (6.3 MB, restore 0.0185 ms), so the restore term stays in the ~0.02 ms regime rather than the ~0.024 ms one.

## 9.4 Speculation cap — SPECIFIED

> ⚠ **SUPERSEDED — see §11.2.** N1b has landed. The cap moves from `inferred` to conditionally confirmed,
> and the condition (the render budget, which none of these sim-only numbers contain) is stated there.

| parameter | value | derivation |
|---|---|---|
| hard cap (allocated) | **64 frames** (1.07 s of staleness) | per-event 5.2 ms ≈ 31 % of budget at depth 120; 64 sits well inside that |
| **default active cap** | **32 frames** (533 ms) | per-event ≈ **1.2 ms ≈ 7.4 %** of budget, interpolating Gate N1 depths 16 and 30 |
| active cap, adaptive | `clamp(ceil(owd_p99) + jitter_margin, 4, 32)` | keeps the ring working set proportional to link quality (§9.3) |
| overrun policy | extend toward 64 and spend up to ~5.2 ms on the frame **rather than stall** | a stall costs 16.7 ms; spending 31 % of a frame to avoid one is unambiguously right |
| beyond 64 | not recoverable by rollback → state resync (§9.7) | |

**The one thing this cap is NOT yet safe against.** Gate N1 reports **p50 only**, and a frame budget is a
**deadline, not an average**. This lane's own tick measurements had p99/p50 ratios of **2.2×** (idle) and **4.0×**
(real inputs). Applying those to Gate N1's depth-30 resim: p99 between **2.3 and 4.6 ms** — comfortable at a cap of
32. Applying them at depth 120: **11–21 ms** — i.e. **a p99 rollback at the hard cap can miss the frame deadline
outright**. The cap of 32 is chosen to have that headroom; confirming it needs **Gate N1b** (§9.9).

## 9.5 Frame delay zero — the policy, stated precisely, including the cost

**Default `d = 0`. Per-player, user-adjustable 0–4.**

The semantics matter and are CONFIRMED from upstream source (`input_queue.cpp`, `AdvanceQueueHead`:
`frame += _frame_delay`): frame delay is applied to the **local player's own** input before it enters the sim.
So it is a **self-imposed latency that buys the *opponent* prediction accuracy** — my delay costs me latency and
saves my opponent from predicting me. It is therefore correctly a **per-player** setting, not a session setting,
and a player on a poor uplink can voluntarily add delay to stop their opponent seeing corrections.

**The honest cost of `d = 0`, which §4 under-stated.** Zero delay does not merely remove 66.7 ms — it also
**maximises correction frequency**. At a steady one-way delay of `k` frames, *every* frame carries a `k`-frame
rollback; at `d = k` most frames carry none. The CPU is free (§9.1) but the **visual correction rate is not**.
This is the real trade, it is why `d` stays user-selectable, and it is why Gate N2 (prediction quality measured as
*visible state delta*, not bit-accuracy) is the gate that decides how far this can be pushed.

The asymmetry is the right one for a fighting game: with both players at `d = 0`, **each sees their own character
respond immediately and the opponent's character occasionally correct.** Your own execution feels exact.

Also specified here, from §8.2: **no TIMESYNC `Sleep`**. Frame-advantage is held at target by continuous
fractional clock adjustment (≤ 1 % of the frame period = 0.17 ms, expressible at the measured 10 µs
spin-to-deadline precision, §1.3), and **all send/receive timestamps come from QPC directly** — never from a
frame-latched clock, which is the defect §8.2 found in the shipped build.

## 9.6 Desync detection — specified against the ctx nondeterminism

Gate N1 §2 established by control run that **the tick itself is nondeterministic in two ctx buckets** (decoded
texture pages `+0x100030..0x108FC0`, page-table records `+0x108FC0..0x1E0030`) even with *everything* restored.
Neither is on the frame read set. The design consequence is a hard rule:

* **Hash the save set and nothing else.** Never hash ctx outside `0x1F0000..0x200000`. A desync detector that
  hashed render scratch would fire constantly and teach everyone to ignore it.
* Cost, scaling this lane's measured FNV-1a (0.0248 ms over 211,736 B) to 277,288 B: **≈ 0.033 ms** — 0.2 % of a
  frame, so hashing **every frame locally** is affordable. Exchange the hash with the peer every 30 frames.
* **Any ctx bucket *other* than those two differing is a real failure**, per Gate N1 — especially the texture-slot
  table, which the tick reads as well as writes.

## 9.7 Recovery beyond the ring — designed, NOT proven

If a confirmed input arrives more than 64 frames late, rollback cannot recover and the session must resync from a
state snapshot. The state is **277,288 B** — about 22 ms of wire on a 100 Mbit link — so unlike GGPO, which can
only freeze, we can in principle just resend the state.

> ⚠ **This is designed, not proven, and there is a specific reason to doubt it.** Per
> `rr-ggpo-determinism`, a **battle-state** `blk` is pointer-rich (557 pointers into the decompressed per-character
> asset image) and restoring one into a different process **killed the game twice**; only **character-select**
> states were shown portable. Same-build, same-content peers make it more tractable — and the receipt runner's
> Δ=0 arena placement removes the relocation entirely when both sides map at the same base — but none of that is
> measured. Gate N5b (§9.9) owns it. Until it passes, the honest fallback beyond 64 frames is a stall.

## 9.8 SUPERGUN v1 — the specified design (supersedes the §5 table)

| parameter | value | basis |
|---|---|---|
| local frame delay `d` | **0** default, per-player 0–4 | 66.7 ms vs 0.255 ms at depth 8 (measured, §9.1) |
| save set | **blk + GGPO counter + `ctx[0x1F0000..0x200000)` = 277,288 B** | Gate N1 sufficiency + a proven-PASS superset for 0.24 % of a frame (§9.2) |
| ring | 65 slots allocated (18.0 MB), **rotated modulo `active_cap+1`** | the cliff is the ring working set, not the copy (Gate N1 §1.2) |
| speculation cap | **32** default active, 64 hard | per-event 1.2 ms (7.4 %) at 32; 5.2 ms (31 %) at 120 (§9.1) |
| cap adaptation | `clamp(ceil(owd_p99) + jitter, 4, 32)` | keeps the working set off the cliff on good links |
| overrun | extend toward 64 before stalling; beyond 64 → resync (unproven, §9.7) | a stall is 16.7 ms |
| desync hash | FNV-1a over the **save set only**, every frame local / every 30 exchanged | 0.033 ms; ctx render scratch is nondeterministic (§9.6) |
| input sampling | spin-to-deadline immediately before the tick | 10 µs vs ≥ 0.6 ms for any sleep (§1.3) |
| clock | QPC directly at send/receive; ≤ 1 % continuous frame-period adjustment; **no TIMESYNC `Sleep`** | §8.2 |
| transport | raw UDP, authenticated, **direct + relay in parallel, first arrival wins** | §4.1/§4.6 — **still ungated, see N4** |
| cadence / payload | 120 Hz adaptive to 60; raw sliding window, last 64 frames × 4 B/seat | packet cost flat 16 B→1200 B (§1.4) |
| jitter buffer | **none** | rollback absorbs jitter at 0.03–0.05 ms/frame |
| prediction | repeat-last in v1; anything else must beat it on Gate N2 | the control must exist first |

## 9.9 Gates after Gate N1

> ⚠ **STALE — see §11.7 for the current ledger.** N1b and N1c are both **CLOSED**; the rows below still read OPEN.

| gate | owner | state |
|---|---|---|
| **N1** interleaved rollback cost + state sufficiency | ENGINE | **PASSED** — and it falsified the shipped-save-set assumption. Carries 3 caveats into N1b/N1c. |
| **N1b** (new) **p99 and max**, not p50, of save/restore/resim per depth | ENGINE (asked by this lane) | **OPEN.** A frame budget is a deadline. p50 says a depth-120 rollback costs 5.2 ms; a 4× tail says 21 ms — a missed frame. Re-emit the §1.2 table with p99/max columns and a count of events exceeding 16.667 ms. **Sets the hard cap; the default cap of 32 is provisional until it lands.** |
| **N1c** (new) save-set window **per stage** | ENGINE at Gate 4 | **OPEN.** Re-run the §3 ctx ladder on a different stage/camera/HUD-heavy frame. **Falsifies §9.2** if any required byte falls outside `ctx[0x1F0000..0x200000)`. |
| **N2** prediction quality as **visible state delta** vs depth | this lane | OPEN, unblocked — the runner now has `--rollback`, which is the machinery N2 needs. Now decides how far `d = 0` can be pushed (§9.5). |
| **N3 / N3b** transport floor, two-node; fleet NAT + relay-wins rates | this lane | OPEN |
| **N4** what Steam's transport adds | this lane | **OPEN — STILL THE GATE for any claim that our transport beats Steam's.** Two machines, simultaneous, same pair: GGPO `endpoint+0x2068` read via the agent's existing RPM path against `sg_probe` raw UDP RTT. §8.1 made the claim *structurally* plausible (`k_EP2PSendUnreliable`); it did not make it measured. |
| **N5** desync = byte gate | both | standing |
| **N5b** (new) mid-match state transfer for resync | ENGINE + this lane | **OPEN.** 557 asset-image pointers; cross-process battle-state restore killed the game twice (`rr-ggpo-determinism`). Until it passes, beyond-64 is a stall, not a resync. |

**Sequencing:** N1b before the cap is fixed. N2 next — it is unblocked and it is the gate that decides the
headline user-facing question (how deep zero-delay speculation can go before it looks wrong). N4 stays the
precondition for any transport claim. **Still no transport code.**

## 9.10 What is still NOT proven — read this before quoting anything above

> ⚠ **STALE — see §11.8 for the current list.** Items 2 and 3 below (the cap resting on p50; the save set
> resting on one stage) are closed. The rest stand.

1. **"Our transport beats Steam's" — UNPROVEN.** §8.1 confirmed the shipped build passes
   `k_EP2PSendUnreliable` (the buffering variant) at all five send sites. The **millisecond cost of that
   buffering is UNKNOWN**, lives inside `steamclient`, and cannot be read statically. Gate N4.
2. **The cap of 32 rests on p50.** Gate N1b.
3. **The save set rests on one stage-9 offline receipt.** Gate N1c. If it widens badly, the deep-speculation
   thesis is at risk — this is the single largest technical risk in the design.
4. **The reader of `ctx+0x1F8230..0x1F8238` is UNKNOWN** (indexed access; no literal displacement in the
   10,803-function cache). We are saving a 64 KB superset *because* we cannot see the reader — that is
   mitigation, not knowledge.
5. **Deep-misprediction visual cost is unmeasured.** Gate N2. CPU is not the limit on speculation depth; this is.
6. **Beyond-64 resync is designed, not proven.** Gate N5b.
7. **Behaviour on an ONLINE match is untested throughout** — every rollback measurement to date is an offline
   receipt in a single process.

**And the framing that has not changed since §0:** the 66.7 ms of frame delay is still the dominant term and is
still an *engine*-enabled policy win, not a networking win. Gate N1 sharpened that — 66.7 ms buys 0.255 ms — it
did not move it.

## 9.11 Address / artefact index (new in §9)

Save set: `blk[0..0x33B18)` · GGPO counter `0x142d10b90` (0x10 B) · `ctx[0x1F0000..0x200000)` (64 KB superset of
the proven-minimal `ctx+0x1F8230..0x1F8238`). Divergence witness for the insufficient set: `blk+0x1D6FC` =
DC `0x8C27B034` = object-pool node 144 `+0x124` (sprite-walker placement). Projection-block neighbours:
`ctx+0x1F8200`/`+0x1F8214` = ±812.357 (world-camera focal length), `+0x1F8220` = −320.0, `+0x1F8224` = −338.4
(ground offset), `+0x1F8230` = `497DDC8E`, `+0x1F8234` = `48ABE972`; block initialiser `FUN_140846A40`
(`0x140846BF7`). Nondeterministic ctx buckets (never hash): `+0x100030..0x108FC0`, `+0x108FC0..0x1E0030`.
Harness: `d3dcap/receipt/runner/rr_runner.exe --rollback/--rb-set/--rb-ctx-extra`, `gate_n1.py` (ENGINE lane) ·
`d3dcap/net/sg_bench.cpp` (this lane). Graph: seed 121 (Gate N1) + seed 122 (this design).

---

# 10. Gate 4 — what the second stage establishes, and what it does not (appended 2026-09-04)

Input: the ENGINE lane's Gate 4 (Carnival / stage 3). Graph seed for this section: `124_supergun_gate4_scoping.surql`.
**Nothing in the §9 design changes. One risk is re-scoped, one gate gets a cheaper closure protocol, and one new
blind spot is recorded against §9.6.**

## 10.1 The precise reading

| save set | stage 9 | Carnival (stage 3) |
|---|---|---|
| `blk` (the shipped set) | **FAIL from depth 2 up** | **PASS at every depth** |
| `rr` = `blk` + `ctx+0x1F8230..0x1F8238` | PASS | PASS |

**Established (CONFIRMED):** the *requirement* is **stage-dependent**. The eight bytes were **needed** on stage 9
and **not needed** on Carnival. So the shipped `blk`-only save set is **not wrong everywhere — it is wrong
sometimes**, as a function of stage/camera/situation. That is exactly the desync class that surfaces only online,
under load, on some stages, and never in a developer's smoke test.

**NOT established, and I will not let this land as if it were:**

1. **It does not show the eight bytes are insufficient anywhere.** `rr` passed at every depth on both stages.
2. **It does not close N1c.** Nobody has re-run the ctx **ladder** — the bisection of §3 of Gate N1 — on any stage
   other than 9. Gate 4 ran the `blk` and `rr` **arms**, not the ladder. The *support* of the requirement across
   stages is therefore still unmeasured.
3. ⇒ **Whether the §9.2 64 KB window is doing real work or is pure insurance remains OPEN.** Gate 4 raised the
   prior that stage-dependence is real; it did not exhibit a single byte outside `0x1F8230..0x1F8238` that anything
   needs.

**What it does do for the design:** it converts §9.2 from a judgement call into an evidenced one. The set of
required bytes has now been *observed to vary by stage*, between `{}` on Carnival and `{8 bytes}` on stage 9.
A quantity demonstrated to vary between two stages can vary again on a third. Shipping the measured minimum from
a single frame of a single stage would have been shipping a set that Gate 4 has now proven is not stage-invariant.
**The window stays. Its cost is 0.24 % of a frame (§9.2); its value is unquantified, and I am saying so.**

## 10.2 N1c stays OPEN — with a cheaper closure protocol than a per-stage bisection

Re-running the full ctx ladder on every stage is expensive and unnecessary. The question the design actually needs
answered is not *"what is the minimum on stage X"* but *"is the shipped window sufficient on stage X"*. That is a
**three-arm check at a single depth**, not a bisection:

| arm | save set | what a result means |
|---|---|---|
| A | `blk` + counter | FAIL ⇒ this stage needs ctx state at all (like stage 9). PASS ⇒ like Carnival. |
| B | + `ctx[0x1F8230..0x1F8238)` (the proven minimum) | FAIL ⇒ **the minimum is stage-dependent in its *content*, not only in its necessity — the headline result N1c is looking for.** |
| C | + `ctx[0x1F0000..0x200000)` (**the shipped window**) | FAIL ⇒ **§9.2 is falsified**; the window must widen or the save set becomes the whole 4 MB ctx and the cap drops to ~8. |

Run at depth 8 (cheapest depth that already discriminated on stage 9), across the stage set. **Escalate to the
full ladder only on a stage where B fails and C passes** — that is the only case where knowing the new minimum is
informative. This makes N1c a per-stage cost of three short runs instead of a bisection, and it tests the thing
the design rests on rather than a quantity the design does not use.

**Falsification, stated so it cannot be fudged:** §9.2 survives iff arm C passes on every stage tested. One arm-C
failure anywhere kills the deep-speculation thesis in its current form.

## 10.3 Carnival cost — the §9.1 eligibility correction applies here too, and I cannot yet quote a per-event number

Gate 4 reports Carnival with set `rr` as **depth 8 = 0.405 ms/frame, depth 120 = 1.823 ms/frame**. Those are the
same *amortised* column §9.1 corrected, so they are **not** per-frame worst case and are **not** directly comparable
to the per-event figures the design budgets against.

Inverting the eligibility model gives an *estimate* only, and it is uncomfortably sensitive to a number I was not
given — the tick count of the Carnival run:

| | stage 9 (columns known) | Carnival (reconstructed, **assumes 200 ticks**) |
|---|---|---|
| depth 8, amortised | 0.286 | 0.405 |
| depth 8, **per-EVENT** | **0.255** (1.5 %) | **~0.42** (~2.5 %) — **+66 %** |
| depth 120, amortised | 2.327 | 1.823 |
| depth 120, **per-EVENT** | **5.230** (31.4 %) | **~4.5** (~27 %) — **−14 %** |

**Sensitivity:** at depth 120 the reconstruction reads ~4.52 ms if the run was 200 ticks and ~3.02 ms if it was
300 — a 50 % spread — and it is undefined for any run of ≤ 120 ticks. **So I am not quoting a Carnival per-event
cost as fact.** What I need to state one, and what I am asking for alongside N1b: **the save / restore / resim
p50 columns and the tick count**, per stage, exactly as Gate N1 §1.2 gave for stage 9.

**What survives the uncertainty, and it is the point the coordinator made:** per-stage cost varies **in both
directions** — Carnival is *more* expensive than stage 9 at depth 8 and *less* at depth 120. Per-frame cost is
therefore a function of stage content, not a constant of the engine, and a single-stage cost table cannot size a
cap. **This makes N1b more load-bearing, not less**: p50 on one stage was already the weak basis for the cap of 32;
p50 on stages whose cost varies non-monotonically with depth is weaker still.

**N1b, restated with the Gate 4 finding folded in:** p99 and max (not p50) for save / restore / resim at every
depth, **per stage**, plus the count of rollback events whose total exceeded 16.667 ms, plus the tick count of each
run. Until that lands, `supergun_speculation_cap_specified` stays **`inferred`** and the default cap of 32 stays
provisional. It is not a formality — the cap is the one design parameter that can silently cause dropped frames.

## 10.4 H1 falsified, and a blind spot that lands directly on §9.6

**H1 falsified (ENGINE lane):** 14 of 16 perturbed geometry objects are **static** — read every frame, never
rewritten — and **0** are fully regenerated. The sim is unaffected (61/61 blk identical), but their prior content
is read **for pixels** every frame.

Two consequences for this design, and they point in opposite directions:

* **No save-set impact.** An object that is never written during a match cannot diverge, so it needs no rollback.
  §9.2 is unchanged. I am stating the reasoning rather than assuming the conclusion: *never written ⇒ cannot
  differ between the straight-line and re-simulated timelines ⇒ not rollback state.*
* **Direct impact on §9.7 / Gate N5b.** A resync by state transfer sends the **save set**, which by construction
  does **not** contain these static geometry objects. A receiving peer must therefore already hold them — from the
  arc, loaded identically. That is fine for a same-build, same-content peer and it is *another* reason N5b is not
  a simple 277 KB transfer. Recorded against N5b rather than glossed.

### The `ctx_out`-equality trap — a correction to how §9.6 could be misread

Gate 4 records that `ctx_out` compared **EQUAL** while H1 was in fact false, because submitted geometry lands in a
**staging buffer the runner never dumps**. So *ctx equality is not evidence of render-path equality*, and
**anything gated on ctx equality inherits that blind spot.**

§9.6 is not itself broken by this — it says to hash the **save set only**, and the save set is `blk` + counter +
a 64 KB ctx window that is *simulation* state. But the way §9.6 could be **read** is dangerous, so I am pinning it:

> **The SUPERGUN desync hash proves SIM agreement. It does not prove PIXEL agreement, and ctx equality is
> specifically NOT a proxy for pixel agreement.** Two peers can hash-match on every frame and still render
> differently, because the geometry actually submitted goes to a buffer nothing in this pipeline dumps or compares.
> Pixel agreement is the verification-harness owner's gate and stays that way. **No SUPERGUN result may be
> reported as "frames match" on the strength of a save-set hash.**

That is the same class of error as the one §0 lists among the project's known traps — offline geometry standing in
for live pixels — arriving from a new direction, and it would have been easy to inherit silently.

**Classes E, L and X proven unread** (~6.9 MB of deliberate difference, 300/300 byte-identical `blk`, RNG identical
at tick 300) upgrade from *measured* to *proven*, and independently reinforce Gate N1's "DC-RAM does not need
rolling back". No design change; it removes a residual worry rather than adding a constraint.

## 10.5 Ledger after Gate 4

| item | state |
|---|---|
| §9.2 save set = `blk` + counter + `ctx[0x1F0000..0x200000)` = 277,288 B | **unchanged**, now evidenced: the requirement is CONFIRMED stage-dependent |
| The 64 KB window is doing real work, vs pure insurance | **UNKNOWN** — no stage has needed a byte outside the 8 |
| **N1c** ctx ladder / window sufficiency per stage | **OPEN** — re-scoped to the 3-arm check of §10.2; Gate 4 ran arms, not the ladder |
| **N1b** p99/max, per stage, plus tick counts | **OPEN**, and now more load-bearing (per-stage cost varies in both directions) |
| §9.4 cap of 32 | still **`inferred`**, still provisional |
| §9.6 desync hash | unchanged, but explicitly **not** a pixel-agreement claim (§10.4) |
| §9.7 / **N5b** resync | **OPEN**, and now carries the static-geometry precondition as well as the 557-pointer one |
| §9.1 amortisation correction | applies to Gate 4's numbers too; per-event costs for Carnival are **not yet quotable** |

---

# 11. Reconciliation — N1b, N1c, and the server-architecture evaluation (2026-09-04)

Inputs: `docs/RECEIPT-RUNNER-GATE-N1.md` §1.2 and §8 (N1b/N1c, ENGINE lane, seed 125-ish), `docs/RECEIPT-RUNNER-GATE4.md`
§A3 (N1c on four stages), `docs/SUPERGUN-SERVER-ARCH.md` (server-architecture evaluation). Graph seed: `130_supergun_reconciliation.surql`.
**No design parameter in §9.8 changes. Two gates close, one architecture is ruled out by arithmetic, one new
deployment requirement enters, and two new UNKNOWNs are opened that nobody had named.**

⚠ **Provenance note.** `GATE-N1` §8 reports N1c on **two** stages; the four-stage result is in `GATE4` §A3, which is
newer. I cite §A3. Anyone reading §8 alone will under-count the evidence.

## 11.1 N1b closed — and my own §9.1 numbers are superseded along with theirs

The ENGINE lane withdrew the eligibility-weighted column §9.1 identified and re-emitted per-EVENT costs with
p99/max, per stage, with tick counts (`rr`, 300 ticks, rollback after every eligible tick, `heap_wraps = 0`):

| depth | ring | stage 9 event p50 / p99 / max | stage 9 **frame p99 / max** | Carnival **frame p99 / max** | over budget |
|---|---|---|---|---|---|
| 8 | 1.8 MB | 0.375 / 0.863 / 0.989 | 1.068 / 1.094 | 0.787 / 0.958 | 0 |
| 16 | 3.4 MB | 0.747 / 1.501 / 1.628 | 1.600 / 1.730 | 1.465 / 1.687 | 0 |
| 30 | 6.3 MB | 1.312 / 2.695 / 3.152 | 2.792 / **3.220** | 1.874 / **2.022** | 0 |
| 60 | 12.3 MB | 2.557 / 5.304 / 5.850 | 5.368 / **5.926** | 3.561 / **3.857** | 0 |
| 120 | 24.4 MB | 5.191 / 9.207 / 9.463 | 9.239 / **9.511** | 7.191 / **7.463** | 0 |

`frame` = event + that frame's straight-line tick. **Zero events exceeded 16.667 ms at any depth on either stage.**

**My tail estimate was right, and I am recording that because it validates the method rather than my luck.** §9.4
projected p99 at 2.2–4.0× p50 from this lane's own tick ratios; at depth 8 that predicted 0.83–1.50 ms and the
measured p99 is **0.863**. The extrapolation was sound at the low end.

**And my per-event numbers are superseded.** §9.1 reconstructed depth-8 per-event as **0.255 ms**; the direct
measurement is **0.375 ms** — 47 % higher. The reconstruction was a *correction of a presentation error*, not a
substitute for a measurement, and now that a direct per-event measurement exists it wins. Different run length
(300 vs 200 ticks) and heap sizing account for the gap. **Everything in §9.1's table is withdrawn in favour of the
table above; only its argument survives.**

**One instrumentation lesson worth carrying, because it is the same class as my own.** The first N1b emission showed
1 event over budget at depth 120 (18.31 ms) and an 11.78 ms outlier at depth 60. Both were the runner's **own bump
heap wrapping** — a resim consumes it `depth+1` times faster and a wrap `memset`s up to 64 MiB inside one tick.
`heap_wraps` read exactly 1 at those depths and 0 everywhere else. **Any future timing run must check `heap_wraps`
before its numbers are quoted** — the direct analogue of this lane's "`N failed` on a seed replay is a `RELATE`
artefact, not a failure" rule (§8 preamble).

## 11.2 N1c closed — and the cap moves, with a condition nobody had stated

**N1c: arm C passes on FOUR stages** (`GATE4` §A3) — 9, 3 Carnival, 7 Ice River, 16 River Raft. **Arm B never
failed**, so the escalate branch was never reached. **The §9.2 save set survives.** Arm A split (FAIL on 9, PASS on
the other three) is the stage-dependence result.

Two caveats I carry rather than drop:
* **Two of the four stages (Ice River, River Raft) ran on IDLE inputs** — no fighter action — because no tape
  matched those boots. Idle still exercises prop/water animation and the whole render path, but not combat.
* **Four stages, not seventeen.** Arm C is unbroken, not proven.

### The cap

| basis | value |
|---|---|
| depth 30 worst **frame** | 3.220 ms (stage 9) / 2.022 ms (Carnival) = **19.3 % / 12.1 %** of 16.667 ms |
| depth 60 worst **frame** | 5.926 / 3.857 ms = 35.6 % / 23.1 % |
| depth 120 worst **frame** | 9.511 / 7.463 ms = **57.1 % / 44.8 %** |
| events over budget, any depth, any stage | **0** |

**Default active cap stays 32. Hard cap stays 64.** The numbers would permit more; the condition below is why they
do not, and it is the thing this reconciliation adds:

> ⚠ **Every number above is SIM-ONLY.** They were measured in a **headless runner that does not render**, and they
> are quoted as a percentage of the *whole* 16.667 ms frame. A real client must also render, present and sample
> input inside that same budget. **The budget actually available for rollback is `16.667 − (render + present + input)`,
> and the render term is §6 U4 — UNKNOWN.** So "57 % of budget at depth 120" means 57 % consumed by simulation
> alone, leaving 7.2 ms for everything else.
>
> This is why the hard cap stays 64 rather than moving to 120: at depth 60 the worst frame is 5.93 ms, leaving
> **10.7 ms** for render+present+input, which is plausible; at depth 120 it leaves **7.2 ms**, which probably is not.
> **The hard cap of 64 is admissible iff the render budget is ≤ ~10.7 ms.** That is now a named open item, U-N10.

**Status change:** `supergun_speculation_cap_specified` moves from **`inferred`** to **`confirmed`** *for the
simulation-cost claim* — four stages, p99 and max, zero over-budget events, a worst case measured under a
pathological rollback-every-frame regime far harsher than GGPO would produce. It is **not** confirmed as a
whole-frame budget claim, and U-N10 is the difference.

## 11.3 Q1 settled by arithmetic — architecture D is out, and §0 is reframed

§9's architecture E races direct and relay and takes the first arrival, so its latency is `min(direct, relay)`.
A central authority must route every input through itself, so its latency is `relay`, always.

> **`min(direct, relay) ≤ relay` is not an empirical claim.** No outcome of N3 or N4 can reverse it.

Supporting geometry (propagation floors, not measurements): an **on-path** relay costs **+0.3–1.7 %**
(LA→Chicago/Denver→NY), but a **same-region pair through an off-path authority pays a 78.7 ms floor against ~0 ms
direct**. Server authority is structurally behind the peer design on latency and **cannot be rescued by a better
transport**.

**Consequences for this document:**
* **§3's architecture D (server/client authoritative) is RULED OUT for default play, on latency, by arithmetic.**
  Its one genuinely strong property — cheating made structurally impossible rather than merely detectable — is real
  and is addressed in §11.4, not by authority.
* **§0 is reframed, not overturned.** "The big win is not a networking win" stands. What changes is that the
  *architecture* question is no longer waiting on N4. **N4 now measures the same quantity for both designs**, so it
  is not a discriminator between architectures — it is a measure of our transport's absolute quality against
  Steam's, and it remains the sole gate for the claim that ours is better.

## 11.4 The witness — my judgement: **its own workstream, not part of §9, with three interface obligations that are**

**Verdict: build it, and build it OUTSIDE this design.** I agree with the research lane's recommendation over the
two-mode proposal, and Q1 is why the two fit together so cleanly: **arithmetic killed authority-as-latency; the
witness delivers authority-as-trust at zero latency cost.** They are answers to different questions and should not
be welded together.

**Why it does not belong in §9:**
1. **It is off the critical path by construction**, so it changes **no** parameter in §9.8 — not the save set, not
   the cap, not the cadence, not the prediction. A design section whose parameters it cannot move is the wrong home.
2. **It is gated by different things** — tape fidelity, receipt signing, server density, `blk_delta` encode cost
   (U-S4) — none of which are netcode gates. Folding it in would couple the netcode's gates to a product feature's,
   which is precisely the coupling the server-arch doc argues against for the two-mode design.
3. **It reuses machinery that is already gated elsewhere** (Gate 2: runner tape == live tape, 301 frames, 0
   unexplained differences). Re-homing it here would re-open settled ground.

**Three obligations it places on SUPERGUN, which therefore DO belong in §9 and are added to §9.8 by reference:**

| # | obligation | why |
|---|---|---|
| W1 | **The desync hash is a published contract, not an implementation detail.** FNV-1a over the save set (`blk` + GGPO counter + `ctx[0x1F0000..0x200000)`), every frame locally, exchanged every 30. | The witness compares against exactly this. A silent change to cadence or coverage silently invalidates every receipt. |
| W2 | **The receipt claims SIMULATION fidelity, never VISUAL fidelity.** | §10.4 / `GATE-N1` §9: a save-set hash proves sim agreement; submitted geometry lands in the staging buffer at `*(game_state+0x208)` that nothing dumps. **"Provably the same match" is a sim-exactness claim and must be worded so.** This is the single largest way the witness could overclaim, and it is the project's known offline-geometry-for-live-pixels trap wearing a product label. |
| W3 | **The side-stream must not contend with the input path** — separate socket, separate pacing, and it may never delay an input send. | At 33–72 KB/s that is ~50–120 pkt/s and, at this lane's measured 0.022 ms per `sendto`, ~2.6 ms of CPU per second — negligible. **The risk is pacing coupling, not CPU.** §9.8 forbids coalescing on the input path; the side-stream must not reintroduce it by sharing a queue. |

**Two limits to state before anyone sells it:**
* **The witness inherits SUPERGUN's open risks.** If N1c's arm C ever fails on a later stage, byte-exact witnessing
  breaks in the same instant the netcode does. It is not an independent check of the save set.
* **It detects an *inconsistent* lie, never a *consistent* one.** A macro producing frame-perfect but humanly
  impossible inputs is accepted by both peers and therefore by the witness. **Server authority does not solve that
  either** — the authority would still have to judge whether a pad sequence is human. That is an input-plausibility
  problem, orthogonal to where authority lives, and neither design should be credited with solving it.

## 11.5 Deployment — pin and isolate. Scoped more narrowly than the headline.

Measured (`sg_tenancy.py`, K concurrent real `rr_runner` processes, 9,000 ticks each, real inputs):

| K | p50 | p99 | **max** |
|---|---|---|---|
| 1 | 0.0430 | 0.1256 | **0.415** |
| 8 | 0.0562 | 0.1594 | 6.24 |
| 32 | 0.0591 | 0.2206 | **96.0** |

p50 degrades only 37 % from K=1 to K=32 and then flattens; **the `max` column is the finding**, and 96 ms is larger
than the 66.7 ms of frame delay this workstream exists to delete.

**Scope it correctly, because the headline invites an over-read.** This is a **server-density** measurement — 32
unpinned, unprioritised processes contending on one desktop. **At K=1 the max is 0.415 ms.** So 96 ms is a
contention artefact of unpinned multi-tenancy, **not** a demonstrated property of a single client.

**But the client is not immune, and that case is unmeasured.** A Windows client running alongside OBS, Discord and a
browser is also unpinned and contended. Nothing here measures it. **New open item U-N11.**

**Requirement added to the design:** *any* host that ticks a match — client, relay, witness or farm — pins its tick
thread to a dedicated core and raises its priority. On the client this composes with §9.8's spin-to-deadline input
sampling, which already requires a core it does not share; pinning and spinning reinforce each other rather than
competing.

**Kernel bypass (AF_XDP/DPDK): ~0.03 ms, Linux-only.** Clients are Windows, so it can never apply to them. Server
side only, and only after N3/N4. It is not on the critical path of anything in §9.

## 11.6 The combat write set — for the record, and it changes nothing in §9

CONFIRMED: the real **combat** write set is **~1 KB/frame** — p50 **363 B** changed, **814 B** XOR+zlib, max 3.2 KB.
The earlier 120 B idle figure was an underestimate by **3–6×**, not by orders of magnitude. ⚠ Neither run contains a
**super**; the scaling bound over the 256-node pool puts the ceiling at **~6–8 KB/frame (INFERRED)**, logged as U-S2.

**This changes nothing in §9, and I am saying so explicitly to prevent a plausible mistake.** SUPERGUN streams
**inputs** — 4 B/frame/seat, with a 64-frame redundant window (§9.8) — **not state**. The write set is the size of a
*state* stream, which matters for the witness (§11.4) and for spectating, and not at all for the netcode. Nobody
should "optimise" §9's input stream into a state stream on the strength of this number: state streaming loses on
latency and correction quality, not on bandwidth.

It does usefully **bound the witness side-stream** at 33–72 KB/s, which is consistent with the figure §11.4 uses.

## 11.7 Gate ledger — current (supersedes §9.9)

| gate | owner | state |
|---|---|---|
| **N1** rollback cost + state sufficiency | ENGINE | **PASSED** — falsified the shipped-save-set assumption |
| **N1b** p99/max per stage + tick counts | ENGINE | **CLOSED** (§11.1). 0 events over budget at any depth; worst frame 9.51 ms at depth 120 |
| **N1c** shipped-window sufficiency per stage (3-arm) | ENGINE | **CLOSED so far** (§11.2) — arm C passes on 4 stages, arm B never failed. ⚠ 2 of 4 idle-input; 4 of ~17 stages. **Re-run on every new stage; one arm-C failure still kills §9.2.** |
| **N2** prediction quality as visible state delta | this lane | **OPEN — now the deciding gate for the default design.** Next. |
| **N3 / N3b** transport floor; fleet NAT + relay-wins rates | this lane | OPEN |
| **N4** what Steam's transport adds | this lane | **OPEN — still the sole gate for "our transport beats Steam's".** No longer an architecture discriminator (§11.3). |
| **N5** desync = byte gate | both | standing |
| **N5b** mid-match resync | ENGINE + this lane | OPEN — two doubts: 557 asset pointers, and static geometry is not in any save set |

**Sequencing: N2, then N4.** N1b/N1c are done; N2 decides whether the primary design works as specified, and until
it has run, opening any second architecture is the wrong order.

## 11.8 What is still NOT proven (supersedes §9.10)

1. **"Our transport beats Steam's" — UNPROVEN.** `k_EP2PSendUnreliable` is CONFIRMED (§8.1); its millisecond cost is
   inside `steamclient` and unreadable statically. **Gate N4.**
2. **The cap's whole-frame admissibility — NEW, U-N10.** Every rollback number is **sim-only, headless, no render**.
   The hard cap of 64 is admissible iff render+present+input ≤ ~10.7 ms, which is §6 U4 and UNKNOWN.
3. **Client-side scheduler exposure — NEW, U-N11.** The 96 ms stall is a K=32 server-density artefact (K=1 max is
   0.415 ms). A contended Windows desktop client is unmeasured.
4. **Arm C on the remaining ~13 stages**, and on **combat** inputs for Ice River / River Raft (§11.2).
5. **Deep-misprediction visual cost — Gate N2.** CPU is not the limit on speculation depth; this is.
6. **Beyond-64 resync — Gate N5b.**
7. **Behaviour on an ONLINE match** — every rollback measurement to date is an offline receipt in one process.
8. **The per-frame write set during a super — U-S2**, ~6–8 KB/frame INFERRED. Bounds the witness, not §9.
9. **The cheat rate — U-S6.** Unquantified. It is the only thing that could ever justify revisiting server
   authority, and §11.3 rules authority out on latency regardless.

**§0 stands.** The 66.7 ms of frame delay remains the dominant term and an engine-enabled policy win. N1b sharpened
it again: **66.7 ms of delay buys 0.375 ms p50 / 0.989 ms max of rollback at the shipped depth of 8.**

## 11.9 Artefact index (new in §11)

`docs/RECEIPT-RUNNER-GATE-N1.md` §1.2 (N1b), §8 (N1c, two stages), §9 (the ctx-equality rule) ·
`docs/RECEIPT-RUNNER-GATE4.md` §A3 (**N1c on four stages — the current result**), §A4 · `docs/SUPERGUN-SERVER-ARCH.md`
§0, §3.1–3.2 (Q1), §2.4 (tenancy/pinning), §9 (witness), §11 (U-S1..U-S8) · `d3dcap/receipt/runner/gate_n1c.py` ·
`d3dcap/net/sg_tenancy.py`, `d3dcap/net/blk_delta.py` (research lane) · `d3dcap/net/sg_bench.cpp` (this lane).
Save set unchanged: `blk[0..0x33B18)` + GGPO counter `0x142d10b90` + `ctx[0x1F0000..0x200000)` = 277,288 B.

---

# 12. U-N10 re-scoped, W2 made copy-proof, and three tooling-honesty rules (2026-09-04)

Graph seed: `132_supergun_method_rules.surql`.

## 12.1 U-N10 re-scoped — but the scope is narrower than "render", and narrower than the claim as put to me

**CONFIRMED, and I verified it rather than accepting it.** `FRAME-READSET.md` §1: `FUN_140607d60` runs the whole
frame, and its top-level calls are `FUN_1408441d0`, `FUN_140608a00` (sim) and `FUN_14060b960` — *the render table
loop*: dispatcher `FUN_140620960`, `FUN_1406185e0` ×2, `FUN_140845130`. The doc states it explicitly:

> "tick" = sim + render dispatch + sprite walker + NaomiLib submit, and "render" = the dispatcher alone.

`FUN_140607d60` is wrapped by `FUN_140118950`, which is exactly what this lane times. **So the 0.034–0.039 ms p50
already contains the geometry/draw-list walk and the NaomiLib submit.** That is a real narrowing of U-N10 and it is
correct.

**One correction to the supporting argument, so the re-scope rests on the right evidence.** It is tempting to argue
"the runner traps 252 IAT slots and got 0 hits over 380 ticks, therefore no graphics call happens inside the tick".
**That argument does not hold.** The trapped slice `0x1408db000..0x1408db880` is **257 slots and contains no
`d3d11`/`dxgi` entries at all** — 132 `KERNEL32`, 13 `ntdll`, 112 unresolved. A zero-hit result over a slice that
does not cover graphics imports says nothing about graphics imports.

The evidence that actually supports the split is different and weaker in kind:

| | claim | tag |
|---|---|---|
| inside the timed function | sim + render dispatch + sprite walker + NaomiLib submit | **CONFIRMED** — whole-frame trace, `FRAME-READSET` §1 |
| the tick's render output | memory writes into host staging buffers: `*(game_state+0x208)` (texture staging) and `dev+0xD8D04` (PALETTE_RAM) | **CONFIRMED** sites (`FRAME-READSET` §6.3, `GATE1` §3.4) |
| graphics-API submission and `Present` are **outside** the timed function | the runner executes 300+ ticks **byte-exactly with no graphics device at all**, and the tick's render output is host-memory fills rather than API calls | **INFERRED (strong)** — not proven, because the trapped IAT slice does not cover graphics imports |

**U-N10 is therefore re-scoped from "the render budget is unknown" to:**

> **U-N10 (re-scoped): the CPU cost of turning the NaomiLib staging buffers into draw calls, plus `Present`
> overhead and the input poll — everything in the frame that is NOT inside `FUN_140118950`.** Bounded and much
> smaller than "render". The render lane can put an upper bound on it from the existing browser replay path.

**What this does to the cap.** At depth 60 the worst measured frame is **5.93 ms** (stage 9), leaving **10.7 ms**.
If the remaining term is submit+present rather than all of render, 10.7 ms is very likely ample and **the hard cap
of 64 moves from *admissible-if* toward *admissible*.** I am not moving it yet: "very likely ample" is not a
measurement, and the whole point of §11.2 was to stop a sim-only number being quoted as a whole-frame number. The
cap moves when U-N10 has a figure, not before.

## 12.2 A rollback optimisation this makes visible — with a strong prior AGAINST it, stated as a test

Because render dispatch + walker + submit are **inside** the tick, a depth-`N` rollback re-runs them `N` times, but
**only the final frame's render output is ever displayed.** The shipped game already owns a mechanism for exactly
this: `G+0x770` suppresses render on catch-up frames (`rr-ggpo-determinism`), which is how its fast-forward works.

> **H-N2a:** render dispatch can be suppressed on non-final catch-up frames, saving the render fraction of every
> re-simulated tick and making deep speculation materially cheaper.

**My prior is AGAINST it, for a specific reason.** Gate N1's divergence witness was `blk+0x1D6FC` = object-pool node
144 field `+0x124` — **a sprite-walker placement field, inside `blk`.** The walker's output is therefore *rollback
state*, and suppressing the walker on catch-up frames would change `blk` and desync.

**Falsification (cheap, ENGINE lane, one run):** `--rollback N` with render dispatch suppressed on every catch-up
frame except the last; if the resulting `blk` is not byte-identical to the straight-line state, H-N2a is dead.
**Prediction: it fails.** Recording it anyway, because it is the obvious optimisation someone will propose, and it
is better to have it killed by a one-run test with a stated prediction than re-proposed every month.

A cheaper companion question worth asking in the same run: **what fraction of the 0.037 ms tick is render dispatch
at all?** If it is 10 %, H-N2a was never worth much even if true.

## 12.3 W2 made copy-proof — approved and forbidden wordings

§11.4's W2 says the witness receipt claims **simulation** fidelity, never **visual** fidelity. That is correct but
it is written for an engineer. The failure mode is a non-engineer lifting one sentence into a product page, so here
is the wording contract itself.

**The technical fact, unchanged:** a save-set hash proves the two peers' *simulation state* agreed byte-for-byte.
It cannot prove the two peers *drew the same pixels*, because the geometry actually submitted lands in the host
staging buffer at `*(game_state+0x208)` which nothing in this pipeline dumps or compares — demonstrated in
`GATE4` §1, where 26 KB of scrambled drawn geometry left `ctx_out` byte-**equal**.

| ❌ NOT approved — overclaims | ✅ Approved |
|---|---|
| "Provably the same match" | "Provably the same **inputs and game state**, verified frame by frame" |
| "Pixel-perfect proof" / "verified frame" | "Byte-exact **simulation** receipt" |
| "We verified the video" | "We re-simulated the match on our own server and it matched byte for byte" |
| "Cheat-proof" | "Any **inconsistency** between the two players' games is detected" |
| "Tamper-proof match record" | "Signed, replayable record of the inputs and the resulting game state" |

**The one-sentence version anyone may copy:**

> *We re-run every match on our own servers from the same inputs and check that the game state matches byte for
> byte. That proves the two players' games agreed — it is a simulation receipt, not a recording of the video.*

⚠ And the limit that must accompany any anti-cheat framing: **the witness detects an *inconsistent* lie, never a
*consistent* one.** A macro that produces frame-perfect but humanly impossible inputs is accepted by both peers and
therefore by the witness. Server authority would not solve it either. **Nothing here may be sold as preventing
cheating**; it detects divergence and produces an auditable record.

## 12.4 Three tooling-honesty rules — recorded together, as method

All three were found on the same day, by three different lanes, and they are one family: **a tool that reports a
number without reporting its own health invites a confident wrong conclusion.** They belong where the next lane
trips over them, so they go in the graph as `finding:method_*` and are listed here.

| rule | discovered as | the trap |
|---|---|---|
| **M1 — check `heap_wraps` before quoting any timing** | N1b's first emission showed 1 event over budget at depth 120 (18.31 ms) and an 11.78 ms outlier at depth 60 | Both were the runner's **own** bump heap wrapping — a resim consumes it `depth+1` times faster and a wrap `memset`s up to 64 MiB inside one tick. The instrument, not the engine. The number looked like a real deadline miss. |
| **M2 — `N failed` on a seed replay is a `RELATE` artefact, not a failure** | re-applying seeds 117/119/122/124/130 | `UPSERT` nodes and `UPDATE` fields converge; only explicit-id `RELATE` edges error with "already exists". A non-zero count reads as "the seed did not land" and causes someone to re-derive settled work. **Read the messages before treating the count as a problem.** |
| **M3 — a finding derived from another lane's measurement is NOT an independent confirmation** | seeds 128 and 130 independently recorded the same two conclusions from the same measurements | **Two graph nodes citing one measurement read as two confirmations.** With four lanes writing to one graph this recurs by construction. **Rule: such a finding must (a) cite the original finding, not just the source; (b) state explicitly what it adds beyond the original; (c) carry a "NOT AN INDEPENDENT CONFIRMATION — cite one, not both" marker.** Applied retroactively to `supergun_server_authority_ruled_out` and `supergun_pin_and_isolate`. |

M3 is the one with teeth, because it is the only one that corrupts *evidence weight* rather than a single number,
and because a graph is precisely the artefact people go to in order to count how well-supported something is.

> Suggested home for these beyond the graph: `docs/RE-METHOD.md` "Rules", which is the canonical method text every
> RE agent is pointed at. That file is shared, so I have not edited it — flagging it for the coordinator instead.

## 12.5 U-N11 stays prominent, unchanged

> **A Windows desktop with OBS, Discord and a browser open is the normal condition of the target population, not an
> edge case.** The 96 ms stall is a **K=32 server-density** artefact; at **K=1 the max is 0.415 ms**. Nothing
> measured shows a single client is exposed — and nothing measured shows it is safe either. If a contended client
> can be preempted for tens of milliseconds, **no speculation cap protects it**, because the stall is outside the
> frame function entirely. Settled by running the tick under realistic desktop load, with and without pinning and
> priority elevation, **reporting the max, not the p50**.

---

# 13. GATE N2-A — misprediction visibility, MEASURED (2026-09-04)

Harness: `d3dcap/net/sg_n2.py` (this lane, new). Output `%TEMP%\sg_n2a\n2a.json`. Graph seed: `134_supergun_gate_n2a.surql`.
This is the gate §9.5 and §11.7 named as *the deciding gate for the default design*.

## 13.1 First result: the obvious N2 would have been a confounded gate

**Every input tape in existence for this project has the REMOTE seat identically zero.** All five
`%TEMP%\rrcap_runner\*\inputs.txt` have `seat1` distinct-value set `{0}` — the stage-9 receipt is one-sided.

Repeat-last prediction of an all-zero stream is **exactly right on every frame by construction**. A naive N2 run on
this data would have reported **zero divergence at every depth** and been written up as "prediction is free, push the
cap as deep as you like". It would have been the project's signature failure — a gate that passes because it is
measuring nothing — and it would have passed loudly.

**So N2-A mispredicts the seat whose inputs are real: seat 0, non-idle on 132 of 300 frames (44 %).**

| | |
|---|---|
| **measures** | visible-state divergence after *k* frames of repeat-last on a real human input stream |
| **does NOT measure** | two *simultaneously* mispredicted streams, or opponent-reaction dynamics |

**Method.** One truth run (real inputs, dump every tick). Then for each start frame `f`, **one** run of `f+K` ticks in
which ticks ≥ `f` use repeat-last (the seat word at `f−1` held), dumping every tick. State at `f+j` is exactly what a
player would see after `j` frames of misprediction, so one run yields every depth 1..K. 25 start frames
(`f = 20..260` step 10), depth 30, stage-9 anchor.

## 13.2 The measurement, calibrated against the game's own units

Raw divergence numbers are meaningless without a scale, so both are given. Calibration from the truth run itself:
**stage extent 2,174 world units** in `px` (range −1386.7 .. 787.5), and **median per-frame movement 7.95 units**
when a fighter is moving (p90 30.0). "Frames of movement" = worst displacement ÷ 7.95 — i.e. *how far out of place the
character appears, expressed as normal movement time*.

| depth | `blk` differs | repeat-last bit-correct | worst \|Δpx\| p90 | worst \|Δpx\| max | max as % of stage | **max in frames of movement** |
|---|---|---|---|---|---|---|
| 1 | 16 % | 84 % | 0.00 | 5.83 | 0.3 % | **0.7** |
| 2 | 16 % | 84 % | 0.00 | 8.75 | 0.4 % | **1.1** |
| 4 | 36 % | 68 % | 0.00 | 14.58 | 0.7 % | **1.8** |
| 8 | 40 % | 68 % | 5.83 | 26.25 | 1.2 % | **3.3** |
| 12 | 52 % | 56 % | 40.03 | 66.67 | 3.1 % | 8.4 |
| 16 | 56 % | 68 % | 75.62 | 133.33 | 6.1 % | 16.8 |
| 24 | 60 % | 52 % | 144.37 | 235.83 | 10.8 % | 29.6 |
| 30 | 64 % | 44 % | 197.50 | 272.50 | **12.5 %** | **34.3** |

`Δhp` is **0 at every depth below 24**, and 7 at depths 24–30. n = 25 samples per depth.

## 13.3 What it says — and it is not what the CPU numbers said

**1. The distribution is bimodal, and the median is ZERO at every depth.** `|Δpx|` p50 = 0.000 from depth 1 to
depth 30. Most of the time repeat-last is exactly right and the misprediction costs *nothing at all*. The cost lives
entirely in the tail.

**2. Bit-accuracy is confirmed to be the wrong metric — with data, not by assertion.** §4.3 argued this before any
measurement existed. Here: at depth 8 repeat-last is bit-correct on only **68 %** of frames, yet the *median*
visible divergence is **zero** and p90 is 5.8 units — a quarter of one frame's movement. **Most wrong predictions
change nothing a player can see.** Anyone tuning a predictor on input-bit accuracy would optimise the wrong quantity.

**3. `d = 0` is supported at normal RTTs.** In steady state you roll back as deep as the input was *actually* late,
i.e. `owd` frames, not the cap. At **owd ≤ 4 frames (≤ 133 ms RTT)** the worst observed displacement over 25 start
points is **14.6 units = 1.8 frames of movement = 0.7 % of the stage**, with a median of zero and no HP divergence at
all. That is imperceptible. **This is the measurement §9.5 was waiting for, and it supports the design's headline
choice.**

**4. But deep speculation is NOT a free lunch, and the CPU table was misleading on its own.** §11.2 showed depth 30
costs 1.3 ms p50 — trivially affordable — which invites treating 30 as a normal operating point. **N2-A says a
depth-30 misprediction can put a fighter 272 units out of place: 12.5 % of the stage, 34 frames of normal movement.**
That is an unmistakable teleport.

> **Design consequence, and it changes how §9.4's cap should be read:** the speculation cap is a **loss-burst
> recovery ceiling, not a target**. The depth actually used in steady state is `owd`. Cheap CPU buys the *ability*
> to recover from a 500 ms delivery gap without stalling; it does not make a 500 ms misprediction look acceptable.
> The alternative at that depth is a hard stall, so deep recovery is still the right choice — but it is choosing the
> less-bad of two visible artefacts, not avoiding one.

## 13.4 The caveat that matters most: N2-A is a LOWER bound, not an upper bound

Because seat 1 is idle, **there is no opponent to react to**. Every divergence measured here is pure "my character
ended up somewhere else" with **no compounding through hit, block or hitstun interactions**. The data shows exactly
that signature: `Δhp` is **zero at every depth below 24**.

In real two-sided play an 8-frame misprediction can flip a hit into a block or a whiff into a counter-hit, and the
resulting state difference is not a few units of position — it is a combo that happened versus one that did not,
worth hundreds of HP and a different animation on both characters.

> **⚠ N2-A almost certainly UNDERSTATES divergence for real two-sided play. The numbers in §13.2 are a floor.**
> Nobody may quote "3.3 frames of movement at depth 8" as the expected artefact in a real match. **N2-B — the same
> harness on a tape with two non-idle seats — is required before the misprediction question is closed**, and it is
> now the top-priority open item of this lane.

Other limits, stated so the table is not over-read: one stage (9), one input stream, 25 start points, depth ≤ 30,
`repeat-last` only (no alternative predictor tested yet — the control exists, the experiment does not), and **no
super/hyper in the input stream** (the same gap as U-S2).

## 13.5 What N2-A settles, and what it opens

| question | answer |
|---|---|
| Is `d = 0` visually viable at normal RTT? | **YES, on this evidence** — worst 1.8 frames of movement at owd ≤ 4, median zero (§13.3.3). ⚠ lower bound (§13.4) |
| Is prediction bit-accuracy the right metric? | **NO — measured.** 68 % bit-correct at depth 8 with a median visible delta of zero |
| Should the cap of 32 be treated as an operating point? | **NO.** It is a recovery ceiling; depth 30 is a 12.5 %-of-stage teleport |
| Does a better predictor than repeat-last help? | **UNTESTED.** The control now exists and is measured; no candidate has been run against it |
| Is the misprediction question closed? | **NO — N2-B (two live seats) is required.** N2-A is a floor |

**New open items:**
* **U-N12 — N2-B: two non-idle seats.** Blocked on data, not machinery: no tape in the project has a non-idle remote
  seat. Needs either a recorded two-player tape (the agent's confirmed input ring, `rr-ggpo-input-ring`, is the right
  source) or a synthesised opposing stream. **The harness is written and works; only the inputs are missing.**
* **U-N13 — predictor comparison.** Run any candidate through `sg_n2.py` against the repeat-last control. The
  falsification stated in §4.3 is unchanged and now has a baseline to beat: *a candidate that does not stochastically
  dominate repeat-last on visible delta at every depth does not help.*

## 13.6 Commands

```
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\net\sg_n2.py ^
  --pre C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor\pre ^
  --inputs %TEMP%\rrcap_runner\gate2_300\inputs.txt --out %TEMP%\sg_n2a --depth 30 --stride 10
```

Prints the per-depth table and writes `n2a.json`. `--keep` retains the per-start dumps. The truth run is cached, so
re-runs only repeat the mispredicted arms.

---

# 14. GATE N2-B — the tape is found, the confounder is settled, and the blockage moves one step later (2026-09-04)

Tape: `shake.json.gz`, prod key `76561198029172402_76561198289004472_76561198029172402_59618234`, agent 0.3.50,
stage 8, 5,112 frames, `rollbacks: 938` — a real online match between two humans. Graph seed:
`136_supergun_gate_n2b.surql`.

**Result: N2-B did not run, and the reason is a good one.** Two of its three preconditions are now met and
*measured*; the third failed in a way that produced two findings of its own.

## 14.1 `seat_in[1]` IS the predicted stream — measured, not assumed

The warning was right, and here is the measurement that settles it rather than an appeal to the knowledge base.

**The discriminator: the LOCAL seat cannot be predicted, so it fixes the frame alignment.** Scanning the offset
between the tape's `seat_in` rows (sim frames) and its `confirmed_in` triples (GGPO frames):

| offset | seat 0 agreement | seat 1 agreement |
|---|---|---|
| +0 | 82.80 % | 64.18 % |
| **+1** | **97.59 %** | 73.50 % |
| +2 | 80.08 % | 75.93 % |
| **+3** | 67.25 % | **85.56 %** |

Seat 0 peaks sharply at **+1** — that is the true `sim = ggpo + 1` alignment, and it is fixed by a stream that GGPO
never predicts. Seat 1 peaks two frames *later*, at +3. **A remote stream whose best alignment is lagged relative to
the local one is a lagged stream.**

At the alignment fixed by the local seat (+1), over 5,110 overlapping frames:

| | disagreements with `confirmed_in` |
|---|---|
| seat 0 (local) | 123 = **2.41 %** |
| **seat 1 (remote)** | **1,354 = 26.50 %** |

And the disagreeing seat-1 values are not noise — **98.8 % of them are exactly a confirmed value from 1–3 frames
earlier**: lag 1 = 31.9 %, lag 2 = 47.3 %, lag 3 = 19.6 %. That is the precise signature of GGPO's repeat-last
predictor holding a stale value.

> **Verdict: use `confirmed_in`.** Had N2-B used `seat_in[1]`, it would have measured GGPO's repeat-last predictor
> against **its own output** — a gate that agrees with itself 100 % by construction wherever no rollback occurred,
> and that would have *flattered* the result rather than nulling it. Second confounder of this class caught in two
> sections, and this one was caught by a measurement rather than by suspicion.

## 14.2 A free real-world number, and a caution about reading it

The same analysis yields the shipped netcode's own behaviour on a real match:

* **The remote seat was mispredicted on 26.50 % of frames** (1,354 of 5,110), with **938 rollbacks over 5,112 frames**.
* **Effective one-way staleness ≈ 2 frames** (lag distribution 1 / 2 / 3 = 32 % / 47 % / 20 %).

Cross-checking against §13.2: at depth 2 the N2-A worst displacement was 1.1 frames of movement. So on this match
the shipped netcode's typical correction was small — consistent with it being playable.

⚠ **Do not read that as "our design will see the same".** This is GGPO **with its 4-frame input delay applied**
(§2.2), which is exactly the mechanism that buys the remote input those extra frames of travel time. A `d = 0`
design deliberately gives that up, so its `owd` — and therefore its rollback depth — will be **larger** than the
~2 frames observed here. The comparison is only fair once N2-B measures both at the same `owd`.

## 14.3 The anchor: relocated successfully, all 18 self-checks pass, but the tick faults

The tape carries a `battle_anchor` at sim frame 1430 (`blk` + `game_state` page + exe page + ctx texture-slot table).
It cannot be used directly: **no dump on this machine matches its boot** — the tape wants
`blk 0x15D71000 / ctx 0x0FC71000 / dcram 0x10071000`, and the nearest template is
`blk 0x15AC1000 / ctx 0x0FFC1000 / dcram 0x103C1000`.

Using the tape's addresses with a foreign `ctx` fails immediately and correctly: the runner's self-checks reported
`ctx[0]/ctx[1]/ctx[2]` and `ctx+0x1F81B0` all pointing at the *template's* arena. **The self-checks did their job.**

So I relocated the anchor into the template's arena instead — the `blk` branch, which is the falsified-safe one
(`rr-ggpo-determinism`: 804/804 across three cold boots, zero false positives). Two deltas apply, because
`blk = arena + ((rng & 0x3F) + 0xC0) MB` differs per boot:

| | value |
|---|---|
| blk delta | **−0x2B0000** (applied to 528 intra-`blk` pointers) |
| arena delta | **+0x350000** (applied to 446 pointers into dcram/ctx/arena) |
| verification | the six self-pointers at `blk+0x32500+8k` form a valid permutation — **[2, 0, 4, 3, 1, 5]** — asserted, not assumed |
| DC-RAM | rebuilt from the user's own arc by `dcram_build.py` for **this anchor's** roster (cids 52, 42, 42, 44, 56, 8) and **stage 8** |

**All 18 runner self-checks then PASS.** The relocation is sound as far as the invariants can see.

**But tick 1 faults**, and the diagnosis is precise:

```
EXCEPTION 0xc0000005 at RIP 0x140848ff4 (RVA 0x848ff4) tick 1
  READ 0xffffffffde9e9475   RAX 0xffffffffcdcdcdcd   RDX 0xffc1000 (= ctx)   RBX 0x15acbc58 (= blk+0xac58)
```

`0x140848FF4` is inside **`FUN_140848EE0`** — the NaomiLib **model texture-record walk**: records start at
`model+0x18`, stride `rec + 0x50 + rec[0x4C]`, terminator `rec[0] >= 0` (the same structure `dcram_build.py`
replays for `FUN_140844DC0`). **`RAX = 0xCDCDCDCD` is the asset image's memset fill**, so it walked a model that
the arc build did not populate, read the fill as a record field, and dereferenced it.

> **This is arc-loader coverage, which the ENGINE lane owns (Gate 3/4), not a netcode question.** Handed over with
> the exact site. The mid-match anchor at frame 1430 evidently references a model outside what `dcram_build`
> currently reproduces — plausibly the `--carry-e` / `+0x145000` class that `GATE4` §A2 already handles for the
> river anchors. Everything upstream of it now works: relocation, self-checks, roster, stage.

## 14.4 The fallback I tried — and the control that killed it

With the real anchor not ticking, I ran **N2-B′**: the shake tape's *confirmed* two-seat inputs fed into the
working stage-9 anchor. Both fighters visibly move under those inputs (slot 0 travels 1,050 units, slot 2 travels
1,123, slot 1 loses 28 HP), so it looked like a legitimately two-sided run.

The output looked publishable:

| depth | `blk` differs | repeat-last bit-correct | \|Δpx\| p50 / p90 / max |
|---|---|---|---|
| 1 | 24 % | 76 % | 0.000 / 0.000 / **0.000** |
| 8 | 52 % | 48 % | 0.000 / 0.000 / **0.000** |
| 30 | 72 % | 32 % | 0.000 / 0.000 / **0.000** |

**Read at face value that says "mispredicting the remote seat costs nothing at any depth" — a spectacular result,
and a false one.** `blk` changes, bit-accuracy degrades exactly as expected, and the visible metric is flat zero.
Everything about it *looks* like a working gate.

**The control, run because a flat-zero result is precisely what rule M4 says to distrust:** identical seat-0 inputs,
seat 1 = the real shake stream versus seat 1 = all zeros, 300 ticks.

```
frames where blk differs       : 237 / 300
frames where a FIGHTER differs :   0 / 300      worst |dpos| 0.000
```

**Seat 1's input reaches the input words inside `blk` but drives no fighter at all.** The stage-9 anchor is a
single-player context in which P2 is not player-controlled. **N2-B′ is vacuous for the visible metric**, its zeros
measure nothing, and it is discarded.

> Rule **M4** — *check whether the gate CAN fail before trusting that it passed* — written into `RE-METHOD.md` this
> same session, and it caught my own result within the hour. The zeros would have been the most quotable number in
> this document.

## 14.5 Status

**N2-B remains OPEN, but the blockage has moved and is now much closer to the surface:**

| precondition | before | now |
|---|---|---|
| A two-seat tape exists | blocked | **met** — `shake.json.gz`, both seats ~77 %/70 % active |
| Knowing which stream is ground truth | unknown, and a trap | **met and measured** — `confirmed_in`; `seat_in[1]` is the predicted stream (§14.1) |
| An anchor that ticks | assumed | **BLOCKED** — relocation works and all self-checks pass, but the arc-built DC-RAM lacks a model the frame walks (§14.3) |

**U-N12 is re-scoped:** *"no tape has a non-idle remote seat"* → *"the shake anchor faults at `FUN_140848EE0` on
arc-built DC-RAM; needs ENGINE-lane arc coverage, or a `dump_live` capture taken during a live online match on this
machine so no relocation is needed at all."* The second option is cheap and would also remove the untested
arena-relocation branch from the critical path.

Nothing in §9's design changes. §13's N2-A numbers remain the only misprediction measurement, and they remain a
**floor** (§13.4).
