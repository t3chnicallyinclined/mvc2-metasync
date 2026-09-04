# SUPERGUN-SERVER-ARCH — evaluation of the central-authoritative-server proposal (2026-09-04)

Lane: senior-re-generalist / **SUPERGUN SERVER ARCH**. This document evaluates a proposal. It is an
assessment, **not** a design, and it **changes nothing** in `docs/SUPERGUN-NETCODE.md` §9, which remains the
specified design. Where I disagree with §9 I say so explicitly; I found nothing to disagree with.

Companion lanes and their documents (read, not edited by me): **NETCODE** `docs/SUPERGUN-NETCODE.md` ·
**ENGINE** `docs/RECEIPT-RUNNER-GATE-N1.md`, `-GATE1.md`, `-GATE2.md`, `-GATE3.md`, `-GATE4.md` ·
`docs/FRAME-READSET.md`.
New artefacts, mine: `d3dcap/net/blk_delta.py`, `d3dcap/net/sg_tenancy.py`, seed
`maplecast-flycast/tools/re_kb/128_supergun_server_arch.surql`.

## RE METHOD (restated; `docs/RE-METHOD.md`)

1. Port the SH4 annotations to the Steam binary by function matching.
2. Seed with unique constants, then propagate along the call graph.
3. Translate globals through the block map before comparing reference sets.
4. **Tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph.**

**Step this document is at: 4, with a measurement pass feeding it.** No new function matching was needed —
every address used here was already CONFIRMED by seeds 106/117/119/121/123/127. Step 3 mattered once: the
per-frame write set is attributed to `blk` field groups through the block map (`FRAME-READSET` §3.1) before
any conclusion is drawn from it, which is what turns "1 KB changed" into "66 % of it is object-pool nodes".

Tags: **CONFIRMED** = reproduced by a numeric gate or read on both sides · **INFERRED** = derived from
confirmed numbers or fingerprint only · **UNKNOWN** = not established, with the test named.
BYOR: every input and output below is game-derived and lives under `%TEMP%`. Nothing ROM-derived is committed.

---

## 0. Verdict, before the argument

**The proposal is three separable ideas welded together. One is right, one is wrong-as-stated but right in
spirit, and one is a latency regression the platform should not ship for normal play.**

| component of the proposal | verdict |
|---|---|
| **Central server owns the state; both clients send inputs to it** | **NO for casual/ranked.** Server authority *forces* the relay leg and removes the option to race direct-vs-relay that §9's architecture E already has. It can never be faster than E and is catastrophically slower for same-region pairs (measured geometry: **+78.7 ms propagation floor** for an LA↔LA pair relayed via NY). |
| **Kernel bypass (XDP/AF_XDP/DPDK) + pinned core + cache-resident state** | **Right instinct, wrong mechanism, and worth ~0.02 ms.** eBPF/XDP *cannot* run the frame function (no floating point in the BPF ISA — CONFIRMED). AF_XDP/DPDK kernel bypass is real but Linux-only, so it can only ever apply to a **server**, never to the Windows clients; and it buys tens of microseconds against a **66.7 ms** frame delay. The cache claim, however, is **CONFIRMED and quantified below** — and it is already why the tick is fast. |
| **Server-authoritative = structurally cheat-proof** | **The one genuinely strong argument, and it is not a latency argument.** It is the only reason to consider this design, and it points at a *money-match mode*, not at a default. |

**Recommendation: keep §9's peer design as the default for all play. Do not build a second netcode path
now.** The two-mode idea is coherent but its cost is paid in the *gates*, not in the transport code — every
gate (N1b/N1c/N2/N5) would have to be run twice, and the project's stated failure mode is exactly
insufficiently-gated variants. **The cheat-resistance goal is better served by a cheaper mechanism that
§9 of this document sets out.**

**Q2's answer, measured this pass and the most useful new number in this document: the combat-frame write
set is order-1 KB, not order-100 bytes and not tens of kilobytes.** So state streaming does **not** die on
bandwidth. It dies on latency and on correction quality, which is a different and more interesting death.

---

## 1. The proposal, restated as accurately as I can

Tris, verbatim: *"what if we have a central server both users connect to this blk src, and we keep it in
cache network xdp ddpk, like pioc state machine but for network cards and we put the blk src in that since
thats what needs to be manipulated and both clients are put their inputs there and ggpo is just validated
them and telling them their inputs are good, no p2p, and it can run headless since we can simulate
frames/roll at super low latency"*

Read charitably and precisely, that is:

1. **Authority moves off the peers.** A central process owns the authoritative `blk` and is the only writer.
2. **Both clients send inputs to it**; there is no peer-to-peer path at all.
3. **The packet path avoids the kernel** (XDP / AF_XDP / DPDK), and the state stays **cache-resident on a
   pinned core**, so the server's own contribution to latency is microseconds.
4. **The server is headless** — it runs the frame function without rendering.
5. **GGPO is demoted** from a peer rollback engine to an input validator.

Four of those five are individually sound engineering statements. Points 1+2 together are the problem, and
point 5 is a misreading of what GGPO is (§6).

**What is right and should not be lost:** *"that's what needs to be manipulated"* is exactly correct and
is the observation the whole SUPERGUN thesis rests on. The mutable state is **211,736 bytes**, the frame
touches **~36 KB of it per tick** (`FRAME-READSET` §3), and it fits in cache — see §5.3, where I show the
measured copy rate is **above this machine's DRAM bandwidth**, so the state provably never leaves cache.

---

## 2. What I measured this pass

All measurements on the dev machine: **AMD Ryzen 9 5900XT**, 16 cores / 32 threads, **512 KB L2 per core**
(8 MB total), 64 MB L3, **DDR4-3200** 4×16 GB (dual channel, **51.2 GB/s theoretical peak**), Windows 11
26200. Every number below is reproducible with the commands in §12.

### 2.1 The per-frame WRITE SET of a real combat frame — CONFIRMED, and NEW

`docs/FRAME-READSET.md` §0(iii) measured **120 changed `blk` bytes on one IDLE tick** by p-code emulation.
The brief correctly flagged that the combat-frame figure was the single most load-bearing unknown. It is now
measured, from the per-tick `blk` dumps the receipt runner already produced (`rr_runner --dump-every 1`), by
`d3dcap/net/blk_delta.py`. No new run was needed for stage 9; the Carnival arm reuses the ENGINE lane's
Gate 4 dumps.

**Run A — stage 9, 300 real receipt ticks** (`%TEMP%\rrcap_runner\gate2_300`). Verified to be genuine
combat, not idle: P2 health falls **144 → 106** over the run and the drawn-node count rises **50 → 79**
around ticks 145–175 (a multi-hit sequence with an effect burst).

**Run B — Carnival / stage 3, 300 ticks** (`%TEMP%\rr_g4\run_cd00`, the ENGINE lane's Gate 4 arc-built run).

| quantity (bytes per frame) | stage 9: min / p50 / p90 / p99 / max | Carnival: min / p50 / p90 / p99 / max |
|---|---|---|
| **`blk` bytes that actually changed** | 88 / **363** / 736 / 1553 / **2515** | 466 / **665** / 904 / 1252 / **3160** |
| contiguous changed runs | 54 / 162 / 289 / 496 / 807 | 228 / 310 / 399 / 522 / 1179 |
| run-length delta record (u32 off + u16 len + payload, runs coalesced across gaps < 8 B) | 370 / **1136** / 1924 / 3929 / **5499** | 1414 / **2013** / 2552 / 3501 / **8375** |
| the same, payload zlib-6 | 355 / 951 / 1638 / 2412 / 3666 | 1214 / 1616 / 2096 / 2774 / 3800 |
| **whole-region XOR, zlib-6** (simplest possible encoder) | 437 / **814** / 1336 / 1746 / **2844** | 1081 / **1315** / 1652 / 2222 / **2325** |

**At 60 Hz the authoritative state delta is 49 KB/s (p50) to 171 KB/s (worst frame) on stage 9, and
79–140 KB/s on Carnival**, using nothing cleverer than XOR-then-zlib over the whole 212 KB region.

Where the bytes go (share of all changed bytes over the run):

| region | stage 9 | Carnival | changed on how many of 300 frames (stage 9) |
|---|---|---|---|
| object-pool nodes (`blk+0x6DD8`, 256 × 0x280) | **66.4 %** | **80.2 %** | 300 |
| fighters (`blk+0x3DB8`, 6 × 0x738) | 13.4 % | 8.1 % | 300 |
| stage / camera (`blk+0x6908`) | 7.9 % | 1.7 % | 288 |
| render-list records (`blk+0x1000`, 0x38 stride) | 5.1 % | 5.8 % | 72 |
| battle state (`blk+0x32500`) | 4.0 % | 2.3 % | 300 |
| G / input / draw counts / matrix stack | 2.9 % | 1.9 % | 300 / 300 / 300 / 26 |

**Interpretation, stated carefully.** The delta is dominated by the object pool, and it scales with the
number of *live* nodes, which is exactly the quantity a super or a screen full of effects raises.
**Stage-dependence is confirmed again** (Carnival's p50 is 1.8× stage 9's), consistent with the ENGINE
lane's finding that the *save-set requirement* is stage-dependent (`GATE-N1` §8, `GATE4` §0).

### 2.2 The gap in 2.1, and the bound that survives it — INFERRED

⚠ **Neither run contains a hyper combo / DHC / full-screen super.** The largest event measured is the
79-drawn-node burst at ticks 145–175. **The super case is UNKNOWN and it is the named gap in Q2.**

The bound that makes the conclusion robust anyway: the pool is **256 nodes** (`(0x2EDF0−0x6DD8)/0x280`), and
the node share of the worst measured frame is 66 % of 2515 B ≈ 1660 B across ~79 drawn nodes. A **fully
saturated pool** would scale that to ~5.4 KB, giving a total worst-frame delta of roughly **6–8 KB**, i.e.
**~370–480 KB/s at 60 Hz**. That is 4–8 MTU-sized packets per frame — large but not disqualifying.

> **Falsification of §2.1's conclusion:** run `blk_delta.py` over a 300-tick receipt whose inputs contain a
> hyper combo and a DHC. **If the p99 per-frame delta exceeds ~8 KB, the "order-1 KB" claim is wrong** and
> the state-streaming option must be re-costed. Until that run exists the ceiling above is INFERRED from a
> linear scaling argument, not measured. **Test: U-S2 in §11.**

### 2.3 The render-sufficient state stream already exists, and it is smaller — CONFIRMED

A client that does not simulate does not need all of `blk`; it needs what the renderer reads. That artefact
already exists and is measured: the **tape**. `runner_tape.json.gz` for the same 301-frame stage-9 run is
**164,191 bytes total including one-time anchors** (`aobjs` 53 KB, `battle_anchor` 17 KB, `anodes` 93 KB) —
**545 B/frame amortised**, with the per-frame `frames` section at **1205 B/frame uncompressed JSON**.
Consistent with the independently recorded live-tape rate of 1.8–3.1 MB/min (30–52 KB/s).

**So the "stream state instead of inputs" option is not hypothetical — we have shipped a version of it, and
its measured cost is ~0.5–1.3 KB/frame.**

### 2.4 Multi-tenancy: K concurrent real simulations on one host — CONFIRMED, and NEW

`d3dcap/net/sg_tenancy.py` launches **K real `rr_runner.exe` processes** on the same anchor, 9,000 ticks
each with real inputs (the 300-tick input file looped 30×), and pools their per-tick timings. This is the
actual frame function under actual contention, not a synthetic proxy.

| K (concurrent matches) | n ticks | p50 | p90 | p99 | max | mean | matches/core at p50 |
|---|---|---|---|---|---|---|---|
| 1 | 9,000 | **0.0430** | 0.0741 | 0.1256 | 0.415 | 0.0476 | 387 |
| 4 | 36,000 | 0.0513 | 0.0812 | 0.1494 | 4.13 | 0.0551 | 324 |
| 8 | 72,000 | 0.0562 | 0.0855 | 0.1594 | 6.24 | 0.0610 | 296 |
| 16 | 144,000 | 0.0590 | 0.0879 | 0.2235 | 26.5 | 0.0709 | 282 |
| 24 | 216,000 | 0.0591 | 0.0880 | 0.2323 | 59.1 | 0.0817 | 282 |
| 32 | 288,000 | **0.0591** | 0.0879 | **0.2206** | **96.0** | 0.0919 | 282 |

**p50 degrades only 37 % from 1 to 32 concurrent simulations, and then flattens.** p99 degrades 76 %.
**The `max` column is the important one and it is not an engine property**: 96 ms is OS scheduler
preemption of 32 unpinned, unprioritised processes competing for 32 logical CPUs with everything else on a
desktop. It is precisely the argument *for* Tris's "pinned isolated core" instinct — see §5.4.

⚠ Caveat, stated because it would be easy to over-read: the looped input file drives the sim off-script
after 300 ticks, and at ~tick 9,960 it faults (`0xc0000005` reading `0x38` at RVA `0x2704c8`). That is **my
input file, not an engine defect** — it is state the real game would never reach. Runs were capped at 9,000
ticks. The timing distribution is unaffected; do not cite the fault as anything.

### 2.5 Per-instance memory, and why it is much smaller than it looks — CONFIRMED / INFERRED

One `rr_runner.exe` instance: **peak working set 108 MB**, **commit charge 597 MB** (measured by polling
`WorkingSet64`/`PrivateMemorySize64`). The commit is the runner's own `MEM_COMMIT` of a 256 MiB arena plus a
256 MB bump heap — a server would reserve rather than commit.

The number that matters for tenancy: **over 300 combat ticks the tick dirties only 16 unique 4 KiB DC-RAM
pages — 64 KB of a 32 MB image** (computed from the `--harvest-dump` `dcram_tNNN.dlt` records), at
`0x0CE60000-0x0CE67000` (the texture decompress buffer), `0x0D00B000`, `0x0D01B000`, `0x0D082000`,
`0x0D086000`, `0x0D089000`, `0x0D853000`, `0x0D855000` (the two animated props Gate 4 classified PARTIAL).
Per-tick: p50 **3 pages**, max 9. **CONFIRMED.**

⟹ **DC-RAM is 99.8 % read-only during a match**, so copy-on-write sharing of one 32 MB image across every
tenant with the same roster order + stage is sound, and the private per-match footprint collapses to
roughly `blk` (212 KB) + `ctx` (4 MB) + ~64 KB of COW DC-RAM + staging ≈ **5 MB**, against a shared
~100 MB image set. **INFERRED** — the dirty-page set is measured, but no COW-shared host has been run.
**Test: U-S5.**

**A structural fact for any multi-tenant server, CONFIRMED:** the recompiled image is a **singleton**.
`rr_runner.cpp:709` refuses any base but `0x140000000` (*"the image is position-dependent, contract C1"*),
and the arena is a 256 MiB region at a fixed VA with a fixed internal layout. **There is no instance
handle**, so a headless server cannot hold two live matches in one address space without swapping state in
and out. Tenancy is therefore **one process per match** (what §2.4 measured), or a state-swap of ≥277 KB per
match switch at the measured copy cost of ~4.2 µs each way. This is not an obstacle — it is a design
constraint nobody had written down.

---

## 3. Q1 — the hop problem. **Cannot be settled without Gate N4, and the geometry is decisive anyway.**

### 3.1 The structural argument, which needs no measurement

§9's architecture E races **direct** and **relay** every packet and takes the first arrival, so its latency
is `min(direct, relay)` by construction. A **server-authoritative** design must route every input through
the authority, so its latency is `relay`, always.

> **`min(direct, relay) ≤ relay` is not an empirical claim.** Server authority therefore **cannot** beat
> the already-specified peer design on latency. It can only tie, and only when the relay happens to be on
> the path. Every millisecond of difference is a millisecond the peer design keeps.

This is the single most important sentence in this document and it does not depend on N4, N3 or any
measurement. **What N4 and N3 decide is a different question** — whether *our* relay path beats *Steam's
actual* path — and that question applies equally to both designs, so it cannot break the tie.

### 3.2 The propagation geometry, computed

Great-circle distance × fibre propagation (n ≈ 1.47, ~200,000 km/s). These are **hard floors**; real RTT is
typically 1.5–2× them because of routing, queueing and last-mile.

| pair | km | floor RTT |
|---|---|---|
| LA ↔ NY | 3,935 | **39.4 ms** |
| LA ↔ Chicago | 2,804 | 28.0 ms |
| Chicago ↔ NY | 1,144 | 11.4 ms |
| LA ↔ Seattle | 1,546 | 15.5 ms |

**Relayed LA→X→NY, versus 39.4 ms direct:**

| via | km | floor RTT | penalty |
|---|---|---|---|
| Chicago | 3,948 | 39.5 ms | **+0.3 %** |
| Denver | 3,954 | 39.5 ms | +0.5 % |
| Ashburn | 4,002 | 40.0 ms | +1.7 % |
| Dallas | 4,197 | 42.0 ms | +6.6 % |
| Atlanta | 4,310 | 43.1 ms | +9.5 % |
| Portland | 5,256 | 52.6 ms | **+33.6 %** |

**The killer case is not cross-country. It is same-region play through an off-path authority:**

| pair | direct floor | via a single central NY server |
|---|---|---|
| LA ↔ LA | ~0 ms | **78.7 ms** |
| LA ↔ Seattle | 15.5 ms | **78.0 ms** |
| NY ↔ NY | ~0 ms | 78.7 ms (mirrored, via LA) |

**Conclusion (from geometry, not opinion): a *single* central authoritative server is disqualifying.** For a
continental player base most matches are regional, and this design charges them the full cross-country round
trip on top of everything else. A *fleet* with per-match server selection fixes the geometry — at which
point it is the same relay fleet architecture E already requires for NAT, but with the `min()` removed.

### 3.3 The counter-argument that could partly rescue it, and its status

The honest comparison is not against an idealised direct path but against **Steam's actual path**, and we
have CONFIRMED reasons to think Steam's path is neither direct nor fast:

* `SteamNetworking005` is the **only** networking interface string in the image (`0x1408DE368`,
  `FUN_14003EE40`) — Valve's **legacy** P2P: NAT punch with SDR relay fallback. CONFIRMED.
* All five `SendP2PPacket` sites pass literal `0` = **`k_EP2PSendUnreliable`**, the **buffering** mode;
  `...NoDelay` appears nowhere. CONFIRMED (`SUPERGUN-NETCODE` §8.1). The millisecond cost is UNKNOWN.
* The GGPO clock is **frame-latched** — RTT is measured at ~16.67 ms granularity, against a decision
  threshold of 3 frames. CONFIRMED (§8.2).

**None of that makes server-authoritative better than architecture E**, because E gets to use our transport
too. It only makes both of them better than Steam.

> **Q1 verdict: server-authoritative loses to §9's architecture E on latency, structurally (§3.1) and by
> geometry (§3.2). The magnitude of the loss for real player pairs is UNKNOWN and needs Gate N3/N3b; the
> magnitude of *our* win over Steam is UNKNOWN and needs Gate N4. Q1 as posed — "is our server path better
> than Steam's actual path" — cannot be settled without N4. Q1 as it bears on this decision does not need
> N4, because §3.1 holds under every outcome of it.**

Vantage-point note: the dev host is **~10 ms from rise3** (`SUPERGUN-NETCODE` §1.5). A traceroute run this
pass shows hop 2 `71.190.176.1` (Verizon FiOS) and hops 6–8 in `62.115.x` (Telia) at 5–9 ms, so this host is
US-Northeast and rise3 is within that metro's reach — **INFERRED**; exact rise3 siting is UNKNOWN and is not
load-bearing for anything above.

---

## 4. Q2 — does state-streaming beat input-streaming? **No, but it fails for the right reason, and it is not bandwidth.**

### 4.1 The bandwidth comparison, measured on both sides

| stream | bytes/frame | at 60 Hz | source |
|---|---|---|---|
| **inputs (shipped GGPO)** | 32–40 B payload + 28 B IP/UDP | **~4.1 KB/s** = 33 kbit/s | `FUN_14011df90` PacketSize, CONFIRMED, `SUPERGUN-NETCODE` §2.3 |
| inputs (§9's 64-frame redundant window at 120 Hz) | 288 B | 34.6 KB/s = 277 kbit/s | `SUPERGUN-NETCODE` §4.2 |
| **authoritative `blk` delta (XOR+zlib)** | 814 B p50 / 2,844 B worst | **49–171 KB/s** = 0.4–1.4 Mbit/s | **measured this pass, §2.1** |
| render-sufficient stream (the tape) | 545–1,205 B | 33–72 KB/s | **measured this pass, §2.3** |

**State streaming costs 12–40× the shipped input stream and roughly 1.5–5× §9's already-redundant input
window. It is 0.4–1.4 Mbit/s per client.** That is affordable on any connection that can watch video, and it
is an order of magnitude cheaper than a 720p video stream.

**So: state streaming does NOT die on bandwidth.** The brief's kill-condition ("if it is kilobytes, say so
and kill it") is not met — it is ~1 KB/frame, at the boundary. I am explicitly declining to kill it on
bandwidth, because the measurement does not support that.

### 4.2 The trap the brief names, worked out

Even with a perfect, free state stream, **a client that does not simulate locally sees its own input only
after a full round trip to the authority.** There is no way around this: the authority decides what the
input did, and the client cannot know before it is told. Local prediction is the entire reason rollback
exists.

Quantified against the shipped baseline, for a player at RTT `r` to a well-sited server:

| player situation | own-input added latency, state-streaming | shipped Steam | §9 zero-delay rollback |
|---|---|---|---|
| same metro as the server (r ≈ 10 ms, measured to rise3) | 10 + up to 16.7 (tick phase) = **10–27 ms**, jittery | 66.7 ms, constant | **~0 ms** |
| one region away (r ≈ 40 ms) | **40–57 ms**, jittery | 66.7 ms, constant | ~0 ms |
| cross-country to a central server (r ≈ 70 ms) | **70–87 ms**, jittery | 66.7 ms, constant | ~0 ms |

⟹ **state-streaming with a dumb client lands in the same band as the 66.7 ms Steam already ships, and it
is jittery where Steam's is constant.** It is not an improvement; against §9 it is a 40–90 ms regression.

### 4.3 What state-streaming IS good for, and it is not nothing

Three real uses, none of which is the playing client:

1. **Spectating / THE RAIL.** A spectator has no input, so the round-trip objection vanishes entirely. At
   ~50 KB/s a spectator feed is cheap, exact, and already built (the tape).
2. **Money-match receipts and a witness.** An authoritative per-frame state stream *is* a receipt. See §9.
3. **Resync beyond the rollback ring** (`SUPERGUN-NETCODE` §9.7 / Gate N5b) — but note the ENGINE lane's
   constraint: a state transfer does **not** carry the static geometry objects the renderer reads, so the
   receiver must already hold them from its own arc (`GATE-N1` §9, `GATE4` §1).

> **Q2 verdict: the per-frame delta is order-1 KB (CONFIRMED, two stages, 600 frames). State streaming is
> bandwidth-viable and latency-fatal for a playing client. The realistic shape, as the brief says, is local
> prediction + server authority — and that is *rollback with the authority moved*, which is §7 here and §9
> there, not a new architecture.**

---

## 5. Q3 — is the XDP/eBPF part feasible as described? **No as stated; yes in its practical form; worth ~0.02 ms.**

### 5.1 eBPF/XDP cannot run the frame function. Not "hard" — impossible.

Three independent disqualifiers, each sufficient on its own:

1. **No floating point exists in the BPF instruction set.** The BPF ISA defines eight instruction classes —
   LD, LDX, ST, STX, ALU (32-bit integer), JMP, JMP32, ALU64 (64-bit integer). There is **no
   floating-point class or opcode**
   ([kernel.org, BPF instruction set](https://docs.kernel.org/bpf/standardization/instruction-set.html)).
   The MvC2 frame is float-heavy throughout — the world camera alone is a `LookAt`/perspective composition
   on f32s (`docs/WORLD-CAMERA-GHIDRA.md`), and `rr_runner` carries an `--fma` switch precisely because FMA
   contraction changes results. **CONFIRMED.**
2. **Program complexity.** The verifier's `BPF_COMPLEXITY_LIMIT_INSNS` is **1,000,000** verified
   instructions ([kernel.org, eBPF verifier](https://docs.kernel.org/bpf/verifier.html)). One MvC2 tick
   executes **459,681 instructions**, measured (`FRAME-READSET` §0) — the same order as the *entire*
   verifier budget, for a program that must additionally be proven to terminate on every path. The tick's
   control flow is data-dependent and unbounded by construction. **CONFIRMED.**
3. **Stack and addressing.** All BPF program types are limited to **512 bytes of stack**
   ([kernel.org, BPF design Q&A](https://www.kernel.org/doc/html/latest/bpf/bpf_design_QA.html)); the state
   is 211,736 bytes addressed as a flat structure through computed pointers, not as map lookups.

**"Put the state machine in the NIC" is not achievable, and no amount of engineering makes it achievable.**
Recompiling the frame function to BPF is not an escape either: the input is the vendor's native x86-64
recompilation, and re-recompiling it onto an integer-only ISA would change float results — i.e. break the
byte gate the entire project rests on (Gate N5).

### 5.2 The practical version is real — and it is Linux-only, i.e. **server-side only**

AF_XDP / DPDK / a pinned isolated core / hugepages are all real and all sound. **But they are Linux
kernel-bypass mechanisms and the client is the Windows Steam binary.** The client's packet path is a Windows
socket no matter what we do. So kernel bypass can only ever remove kernel time on the **server** leg — which
in the peer design is the *relay*, and in Tris's design is the *authority*. **CONFIRMED by construction**
(the image is a position-dependent x86-64 PE pinned to `0x140000000`, `rr_runner.cpp:709`; there is no
Linux-native build of the game).

### 5.3 The cache instinct is CORRECT, and here is the arithmetic that proves it

The brief suggested 207 KB fits in "a typical 1–2 MB L2". On **this** machine L2 is **512 KB per core**, so
that framing is generous — but the conclusion is right and can be proven harder:

* A full 211,736 B save takes **0.0042 ms** (`SUPERGUN-NETCODE` §1.2). That is **50.4 GB/s of copy**, i.e.
  **~101 GB/s of read+write memory traffic**.
* This machine's DRAM peak is **51.2 GB/s** (DDR4-3200, dual channel, measured configuration).
* **101 > 51.2 ⟹ the copy cannot be served from DRAM. It is cache-resident. CONFIRMED by arithmetic.**

And the reason *the tick itself* is 0.043 ms is sharper than "the state fits in cache": the tick's per-frame
footprint is far smaller than the state. From `FRAME-READSET` §3 — reads `blk` 10,004 + DC-RAM 22,545 + exe
2,445 + ctx 1,871 = **~36 KB read per tick**; writes 6,692 + 11,488 + 716 + 43,217 + ~64 KB staging ≈ 127 KB.
**~160 KB touched per frame, against 512 KB of L2.** Tris's instinct is right; the mechanism is "the
*working set* is small", not "the state block is small".

### 5.4 What kernel bypass actually buys, next to the terms it competes with

| term | value | source |
|---|---|---|
| **GGPO frame delay (shipped)** | **66.7 ms** | CONFIRMED, `SUPERGUN-NETCODE` §2.2 |
| TIMESYNC blocking `Sleep`, up to | 150 ms, ≤1 per 240 frames | CONFIRMED, §2.2 term 4 |
| one frame budget | 16.667 ms | |
| pad-poll phase within the frame | up to 16.7 ms | UNKNOWN (U3) |
| **scheduler preemption tail, 32 unpinned tick processes** | **up to 96 ms** | **measured, §2.4** |
| any sleep primitive's deadline miss | 0.58–1.08 ms | measured, `SUPERGUN-NETCODE` §1.3 |
| **whole OS UDP socket path, loopback RTT** | **0.057 ms** | measured, §1.4 |
| `sendto()` alone | 0.023 ms | measured, §1.4 |
| the sim tick | 0.043 ms | measured, §2.4 |
| **what AF_XDP/DPDK could remove** | **~0.01–0.03 ms per packet** | **INFERRED** — bounded above by the whole socket path |

**Kernel bypass is worth at most ~0.03 ms against a 66.7 ms frame delay — a factor of ~2,200.** It is the
smallest term on the list.

**The genuinely valuable part of Tris's point 3 is the part that is not networking: pinning and isolation.**
§2.4 measured the OS scheduler injecting **96 ms** stalls into unpinned tick processes — three orders of
magnitude larger than anything kernel bypass could recover, and larger than the frame delay the whole
project exists to delete. **Any host that ticks a match must pin its tick threads to isolated cores.** That
is the actionable form of the instinct, and it applies to §9's relay and to a witness just as much.

> **Q3 verdict: eBPF/XDP execution of the frame is impossible (CONFIRMED, three ways). AF_XDP/DPDK kernel
> bypass is feasible, server-side only, and worth ~0.03 ms — build it last if at all. Pinning + core
> isolation is worth up to two orders of magnitude more and should be a requirement on any tick host, in
> either architecture. The cache claim is CONFIRMED and is already paying off.**

---

## 6. Q4 — what would "GGPO just validates" actually mean? **It would mean deleting GGPO.**

GGPO is three things: (a) an input-prediction and **rollback** engine, (b) a frame-advantage clock
(`TimeSync`), (c) a UDP protocol. Its *value* is (a). Validation is not a GGPO concept at all — upstream has
no validation path, and the Steam build is upstream verbatim with only the transport replaced (CONFIRMED,
`SUPERGUN-NETCODE` §2, cross-checked against the vendored upstream at
`maplecast-flycast/core/deps/ggpo/lib/ggpo`).

If the server is authoritative:

* **Prediction and rollback either move to the server or disappear.** If they move, the design is
  "server-side rollback with client-side prediction" and GGPO's *algorithm* is being reused — but its
  transport (b/c) is exactly the part §9 replaces, so almost nothing of the library survives.
* **If they disappear** (V3), there is nothing left to call GGPO. "Input validation" in that world means a
  sequence number and a signature — a transport concern, not a netcode one.

**The honest names:**

| what was described | accurate name |
|---|---|
| "central server, both send inputs, GGPO validates, clients told their inputs are good" | **authoritative lockstep with a signed input channel** (V3, §8.3) |
| the version of that idea which actually works | **server-authoritative rollback with client-side prediction** |
| what §9 specifies today | **peer rollback with zero input delay and deep speculation** |

> **Q4 verdict: do not keep the GGPO label. In the authoritative design GGPO contributes nothing it is good
> at. Calling it "GGPO validation" would smuggle in an assumption — that prediction survives — which the
> design as described does not contain. Name the thing it has become.**

---

## 7. Q5 — economics, and the honest architecture comparison

### 7.1 The density arithmetic, corrected by measurement

The brief's "0.039 ms ⟹ ~200 matches/core" is the right order but assumes tick cost is independent of
tenancy. Measured (§2.4) it is not — though it degrades less than I expected: **+37 % p50 from 1 to 32
concurrent simulations**, then flat.

| scenario | cost per match-frame | matches per core at 60 Hz |
|---|---|---|
| sim only, single tenant | 0.043 ms | 387 |
| sim only, 32 concurrent tenants (measured) | 0.059 ms | **282** |
| **+ zero-delay rollback at depth 8** (event p50 0.375 ms — `GATE-N1` §1.2, N1b, stage 9, 300 ticks) | 0.434 ms | **38** |
| + rollback at depth 8, **p99** (event 0.863 ms) | 0.922 ms | **18** |
| + rollback at depth 30, p99 (event 2.695 ms) | ~2.75 ms | **6** |

**The rollback term, not the tick, is what sets server density** — it is 10–60× the tick. If the server is
authoritative and simply **waits** for both inputs before ticking (V3, no server-side rollback), density
returns to ~282/core; if it predicts and rolls back like a peer would, it collapses to **18–38/core**.

Memory: **~5 MB private per match** with COW-shared DC-RAM (§2.5, INFERRED) or **~108 MB** without
(CONFIRMED). At 5 MB, 200 matches is ~1 GB and comfortable; at 108 MB it is 21.6 GB and the sharing work
becomes mandatory. **Neither aggregate is L2-resident, and that does not matter** — the tick's *working set*
is ~160 KB (§5.3), so what degrades with tenancy is the p99/max tail (measured), not the p50.

Not counted anywhere above: NIC interrupts and packet processing, per-match crypto, and **the state-delta
encode** — zlib over 212 KB per frame per match is *not* free and is the single largest omission in this
arithmetic. **UNKNOWN: U-S4.**

### 7.2 The comparison the platform actually has to make

| | (a) same-region play | (b) cross-country play | (c) money matches, trust matters |
|---|---|---|---|
| **§9 peer rollback, `d=0`, dual path** | **WINS decisively.** `min(direct, relay)`; direct is ~0–15 ms; own input has ~0 added latency | **WINS.** `min()` is ≤ the authority path by construction; §9 additionally deletes the 66.7 ms and the 150 ms `Sleep` | **LOSES on trust.** Each peer runs the sim, so each holds authoritative state; a modified client can submit inputs a human could not. Desync detection catches an *inconsistent* lie, never a *consistent* one |
| **server-authoritative + client prediction** | **LOSES.** Forced onto the relay leg; up to +78.7 ms of pure propagation for an LA↔LA pair through a distant authority | ties at best (on-path relay: +0.3–1.7 %); loses off-path | **WINS structurally.** The client holds no state that matters; the only thing it can lie about is its own pad word, which is the one thing it is entitled to decide |
| **server-authoritative, no prediction (V3)** | loses badly | ~equal to shipped Steam, but jittery instead of constant | wins on trust, loses the feel |

> **Q5 verdict: §9 wins (a) and (b) outright. Server authority wins only (c) — and (c) is a business
> requirement, not a latency one.** That is exactly the tension the coordinator's synthesis identifies;
> §9 of this document answers it.

---

## 8. The four variants

### 8.1 V1 — Redis / NATS pub/sub as the INPUT transport. **NO for inputs. YES, already, for everything else.**

**Why not for inputs**, against a 16.667 ms deadline:

* **TCP head-of-line blocking.** Redis pub/sub and NATS core are TCP. One lost segment stalls *every*
  message queued behind it until retransmission — one RTT minimum, typically 1.2–2× RTT with delayed ACK.
  In a rollback scheme a lost input packet costs nothing (the next packet carries the redundant window,
  `SUPERGUN-NETCODE` §4.2); under TCP it stalls everything. **This inverts the single most important
  property of the transport.**
* **Store-and-forward.** A broker is by definition an extra hop with a receive-parse-match-publish cycle —
  the §3.1 problem again, with a userspace process added on top of it.
* **Nagle.** Without `TCP_NODELAY` the sender coalesces small writes, and every input packet is small.
* **The irony that must be stated in the verdict:** `SUPERGUN-NETCODE` §8.1 established that the shipped
  game **already** pays a send-buffering delay, because it passes `k_EP2PSendUnreliable` at all five send
  sites (CONFIRMED). **Interposing a TCP broker adds *more* buffering, in more places, on top of the one
  structural defect we have actually proven.** V1 moves in the opposite direction from the thing SUPERGUN
  exists to delete.

**Where they ARE right — and this is not a grudging concession, it is most of the system:** lobby and
matchmaking, invitations, spectator fan-out, THE RAIL's odds and bet flow, result and receipt delivery,
leaderboard and ladder updates, agent telemetry. All human-timescale (100 ms – seconds), all fan-out-shaped,
all better served by a broker than by anything bespoke. **We already run Redis pub/sub for the real-time
feed bus (SSE :7251) and it is the right tool there.**

> **V1 verdict, as a boundary rather than a blanket: the 60 Hz input/state path is bespoke UDP and nothing
> else touches it. Everything above the match — every event whose deadline is a human's patience rather
> than a frame — goes through the broker we already run.**

### 8.2 V2 — "if prediction is verified we keep playing." **This IS rollback's happy path. The design already has it.**

Tris has described the mechanism correctly. GGPO predicts the remote input (repeat-last), runs the frame,
and when the real input arrives it compares: **if it matches the prediction, nothing is rewound and the cost
is exactly zero.** Only a *mis*prediction triggers restore-and-resim. CONFIRMED against the vendored
upstream (`sync.cpp`, `input_queue.cpp`), which the Steam build carries verbatim.

So V2 is not an alternative to rollback — it is the branch rollback takes on most frames. The measured
depth-8 figure of **0.375 ms p50 / 0.863 ms p99 per event** (`GATE-N1` §1.2) is the price of the *other*
branch, 2–5 % of a frame.

> **V2 verdict: correct mechanism, already specified (`SUPERGUN-NETCODE` §9.8, "prediction: repeat-last in
> v1"). No change. The open question it points at is not *whether* to do this but *how often the prediction
> is wrong and how visible it is* — which is Gate N2, still OPEN, and now the highest-value open gate in the
> netcode lane, because it decides how far `d = 0` can be pushed.**

### 8.3 V3 — server-authoritative, no rollback, "snap them in place." **NO. This is the expensive one.**

**(a) Input delay collapses to network latency.** Worked in §4.2: **10–27 ms** for a player in the server's
metro, **40–57 ms** one region away, **70–87 ms** cross-country to a central authority — each with a
0–16.7 ms tick-boundary quantisation on top. The coordinator's rough read is confirmed: **it lands
comparable to the 66.7 ms Steam ships today, and it is jittery where Steam's is constant.** Against §9's
`d = 0` it is a 40–90 ms regression — it gives back the entire prize.

**(b) "Snapping" is not tolerable in this genre, and the reason is mechanical, not aesthetic.** In a shooter
a positional correction of a few units moves where a body is drawn, and the hit is resolved server-side
against the corrected position — the player sees a small lie and lives with it. In MvC2:

* Hit detection is **discrete box overlap evaluated on a specific frame**. A two-frame positional
  correction does not "look slightly off": it changes **whether the move connected**, whether the combo
  dropped, and whether a 40 %-damage chain happened.
* The engine has **no tolerance concept anywhere**. There is no "close enough" in it — which is exactly why
  every gate in this project is byte-exact (`runner_gate.py`, Gate N5).
* Every visible quantity a correction would have to blend — animation cell (`node+0x191`), sprite id
  (`+0x188`), placement (`+0x124..0x137`), palette bank (`+0x39`), hitstop/flash (`+0x170..0x175`) — is
  **produced by the sim** (`FRAME-READSET` §3.1, `TAPE-V3-SPEC` §10). CONFIRMED.

**(c) Is smoothing even available without local simulation? No.** To interpolate or extrapolate a character
between authoritative states you must produce the intermediate placement, cell and flags, and only the sim
produces them. Our renderer *can* draw an arbitrary placement (it draws from tape state), so the position
could be lerped — but the cell, sprite id and hit flags would be stale, so the character would **slide
without animating** and the correction would be *more* visible, not less.

> **⟹ To smooth, you must simulate locally. If you simulate locally, you have local prediction. If you have
> prediction, you have divergence. If you have divergence, you need reconciliation. That is rollback. V3 is
> not an alternative to rollback; it is rollback with the reconciliation step deleted and the latency paid
> in full.**

**(d) Q2 gates V3 on bandwidth — and V3 passes that gate.** The measurement says 49–171 KB/s (§2.1), so V3
does **not** die on bandwidth. **It dies on (a) and (b).** I am being explicit because the brief anticipated
a bandwidth kill and the data does not support one; the actual kill is latency and correction semantics,
which is a stronger and more durable reason.

> **V3 verdict: NO for any playing client.**

### 8.4 V4 — dynamically adjust the delay to keep both sides in sync. **Adaptive delay-based netcode; GGPO already does a bad version of it.**

**What is shipped, CONFIRMED:** `FUN_14011cdc0` = `TimeSync::recommend_frame_wait_duration` (constants
40/10/3/9) drives `FUN_140119010` case 5, which calls `KERNEL32!Sleep(frames_ahead × 1000/60)` — a
**blocking sleep of up to 150 ms** on the game thread, at most one per 240 frames. And §8.2 of the netcode
doc established that the input to that decision is a **frame-quantised** RTT (~16.67 ms granularity), so a
one-frame measurement error is a *persistent bias* against a `MIN_FRAME_ADVANTAGE` of 3. **The shipped
adaptive-delay mechanism is driven by a clock that cannot resolve its own decision threshold.**

**The human argument, with evidence rather than assertion.** The literature supports "large jitter is worse
than the equivalent constant delay", with an important nuance:

* Constant delays up to ~300 ms were tolerated, but adding jitter to a 200 ms delay made the lag **noticed
  more often, hindered players' ability to improve with practice, and increased failure rates**
  ([Player perception of delays and jitter in character responsiveness, ACM SAP](https://dl.acm.org/doi/10.1145/2628257.2628263)).
* But **small** local latency variation does **not** measurably affect performance
  ([Small Latency Variations Do Not Affect Player Performance in First-Person Shooters, 2023](https://epub.uni-regensburg.de/55003/1/schmid_halbhuber_latency_variation_2023.pdf)).
* Mean latency and jitter amplitude/frequency each independently degrade target acquisition
  ([How Changes in the Mean Latency, Jitter Amplitude, and Jitter Frequency Impact Target Acquisition Performance, ACM TAP](https://dl.acm.org/doi/10.1145/3701984)).

⚠ **All of that is FPS/aiming literature, not fighting games. Applying it to MvC2 is INFERRED.** The
transfer is plausible — both are closed-loop motor tasks under adaptation — but it has not been shown for
this genre and I will not pretend it has. **Test: U-S7.**

**The synthesis that follows, and which §9 of the netcode doc already encodes:** the evidence does not say
"never adapt". It says **adapt in steps small enough to sit under the perceptual floor**. `SUPERGUN-NETCODE`
§9.5 specifies exactly that — **continuous ≤1 % frame-period adjustment (0.17 ms/frame)**, expressible at
the measured 10 µs spin-to-deadline precision — instead of whole-frame 16.7 ms jumps or a 150 ms sleep.

> **V4 verdict: the goal is right, the shipped implementation is the thing to beat, and the good version is
> already specified. Adapting the *clock* continuously and imperceptibly: yes, already in §9.5. Adapting the
> *input delay* in whole frames: no — that is precisely the jitter the literature penalises. Frame delay
> stays a per-player, user-set constant (§9.5), which is the right call for a genre where muscle memory
> adapts to a fixed offset and cannot adapt to a moving one.**

---

## 9. The two-mode synthesis — coherent, but I recommend against building it now

The coordinator's proposal: peer rollback with `d=0` for casual/ranked; server-authoritative for money
matches, where stakes justify latency and players already accept friction.

**What is genuinely right about it.** Server authority is the only mechanism on the table that makes
cheating **structurally impossible** rather than **detectable**, and that distinction is real:

* Under peer rollback both peers run the sim, so both *hold* authoritative state. A modified client can
  submit inputs a human could not produce (frame-perfect, reaction-impossible), and every peer-side detector
  is heuristic. Desync detection catches an *inconsistent* lie, never a *consistent* one.
* Under server authority the client holds no state that matters. The only thing it can lie about is its own
  pad word — the one thing it is entitled to decide.

**Why I still recommend against building it now. This is a process argument, not a technical one.**

1. **The cost is in the gates, not the code.** N1b, N1c, N2 and N5 all have to be run and held for *each*
   netcode path. This project's stated recurring failure is confident conclusions verified against the wrong
   thing; two paths double the surface for exactly that, and the money path is where being wrong is most
   expensive.
2. **The deciding gate for the default design has not run.** N2 (misprediction visibility) decides how far
   `d = 0` can be pushed — i.e. whether the *primary* design works as specified. Opening a second
   architecture before the first one's deciding gate has run is the wrong order.
3. **The threat model is not stated anywhere.** No document in this repo defines what a money-match cheat
   looks like, how often it is suspected, or what the current detection rate is. **Building a netcode path
   against an unquantified threat is the same error as optimising an unmeasured latency term.**
4. **A much cheaper mechanism gets most of the trust benefit, and it is nearly free given what exists.**
   Run the money match on the **peer** design and additionally stream its state to a **witness** server —
   measured at 49–171 KB/s (§2.1), or 33–72 KB/s using the tape (§2.3). The witness re-simulates from the
   same inputs (**the receipt runner already is that simulator** — Gate 2 proved runner tape == live tape
   over 301 frames with 0 unexplained differences) and byte-compares. That yields:
   * **byte-exact detection of any divergence**, using the `runner_gate.py` comparison unchanged;
   * **a signed, replayable receipt of the match** — a product feature the platform already sells;
   * **zero added latency to the players**, because the witness is off the critical path;
   * **reuse of code and gates that already exist**, with no second netcode path.

   What it does **not** give is prevention of an *impossible-input* cheat — a macro whose pad words both
   peers accept. **Server authority does not solve that either**: the authority would also have to judge
   whether a pad sequence is human. That is an input-plausibility problem and it is orthogonal to where
   authority lives. Naming it here so the two-mode design is not credited with solving it.

> **Two-mode verdict: coherent and correctly motivated, but recommend NOT building it now.** Build the
> witness instead: it captures the auditability benefit at a fraction of the cost, on the peer design, using
> machinery that already exists and is already gated. Revisit server authority if and only if a measured
> cheat rate justifies it — **U-S6 names that measurement.**

---

## 10. Recommendation

1. **Keep `docs/SUPERGUN-NETCODE.md` §9 as the design.** Nothing in this evaluation changes it. §3.1 is a
   structural argument that a peer design which races direct-vs-relay cannot be beaten on latency by one
   that forces the relay.
2. **Do not build a server-authoritative netcode path.** Do not build a second netcode path at all yet.
3. **Adopt one thing from the proposal immediately, and it is not networking: pin and isolate.** §2.4
   measured a **96 ms** scheduler stall on unpinned tick processes — larger than the 66.7 ms frame delay the
   whole project exists to delete. Any host that ticks a match (relay, witness, or a future server) must pin
   its tick threads to isolated cores. This costs a configuration change and is the largest measured win in
   this document.
4. **Build the witness, not the authority**, if and when trust work is prioritised (§9.4).
5. **Kernel bypass (AF_XDP/DPDK): last, server-side only, and only after N3/N4.** ~0.03 ms.
6. **Gate order is unchanged: N2 next** (misprediction visibility — it decides the default design), then
   **N4** (the only thing that converts "our transport beats Steam's" from a hope into a number). N1b and
   N1c are now **closed** by the ENGINE lane (`GATE-N1` §1.2 and §8: arm C passes on both stages, 0 events
   over budget at any depth, worst single frame 9.51 ms at depth 120).

---

## 11. UNKNOWN list — what this evaluation could not establish, and the test for each

| # | UNKNOWN | Why it matters | Test that settles it |
|---|---|---|---|
| **U-S1** | **Whether our transport path beats Steam's actual path.** | It is the one commercially load-bearing claim and it is UNPROVEN. It applies to *both* architectures equally, so it cannot break the §3.1 tie. | **Gate N4**, unchanged: two of our own machines in one lobby, simultaneous, reading GGPO `endpoint+0x2068` via the agent's RPM path against `sg_probe` raw UDP RTT between the same pair. |
| **U-S2** | **The per-frame write set during a hyper combo / DHC / full-screen super.** §2.1 measured a 79-node effect burst; no super appears in either run. | If p99 exceeds ~8 KB/frame the "order-1 KB" conclusion of §4 is wrong and state streaming must be re-costed. | Capture or build a 300-tick receipt whose inputs contain a super, then `python d3dcap/net/blk_delta.py --dir <dump dir>`. Falsified if p99 > 8 KB. |
| **U-S3** | **Real inter-player RTT distribution for our population**, and how often a relay path beats direct. | Every number in §3.2 is a propagation floor, not a measurement. | **Gates N3 / N3b** (netcode lane), across the ~15 agent machines. |
| **U-S4** | **Server-side cost of encoding a state delta, per match per frame.** zlib over 212 KB × N matches × 60 Hz is not free and is absent from §7.1. | It could dominate server density wherever state streaming is used (witness, spectator). | Add a timing mode to `blk_delta.py`; measure encode ms/frame and re-derive §7.1. |
| **U-S5** | **Whether COW sharing of the 32 MB DC-RAM image across tenants actually works.** §2.5 measured a 64 KB dirty set but ran no shared host. | It is the difference between ~5 MB and ~108 MB per match. | Map DC-RAM as a shared copy-on-write file mapping, run K tenants, compare RSS and `blk` byte-equality against the private-mapping baseline. |
| **U-S6** | **The actual cheat rate in money matches.** No document in this repo quantifies it. | §9's whole recommendation turns on it: an unquantified threat cannot justify a second netcode path. | Instrument the existing money-match flow for disputes and desyncs per 1,000 matches *before* any trust architecture is chosen. |
| **U-S7** | **Whether FPS latency-jitter findings transfer to fighting games.** §8.4 is INFERRED. | It is the substantive argument against V4's whole-frame delay adaptation. | Within-subject test on our own players: fixed 4-frame delay vs a delay oscillating 2–6 frames at the same mean; measure execution success on a fixed combo. |
| **U-S8** | **Per-packet cost of an AF_XDP path vs the Windows socket path, measured rather than cited.** | §5.4's "~0.01–0.03 ms" is INFERRED from the loopback socket measurement. | Only worth doing after N3/N4: `sg_probe` with an AF_XDP backend on rise3 over the same wire path. |

Still open and owned elsewhere, unchanged by this evaluation: **N2** (misprediction visibility, netcode
lane — now the highest-value open gate), **N5b** (mid-match resync, ENGINE + netcode), and **U3 / U4 / U5 /
U7 / U10** from `SUPERGUN-NETCODE` §6 and §8.4.

---

## 12. Commands and artefact index

```
rem Q2 -- per-frame write set, from the receipt runner's per-tick blk dumps (no new run needed)
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\net\blk_delta.py --dir %TEMP%\rrcap_runner\gate2_300 --json %TEMP%\rr_q2_gate2_300.json
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\net\blk_delta.py --dir %TEMP%\rr_g4\run_cd00      --json %TEMP%\rr_q2_carnival.json

rem to produce dumps for a new anchor (ENGINE lane owns d3dcap\receipt -- RUN it, do not edit it)
C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\receipt\runner\rr_runner.exe --pre <run>\pre --out <dir> --ticks 300 --dump-every 1 --inputs <inputs.txt> --heap-mb 1024

rem Q5 -- concurrent-tenancy scaling, measured on the real frame function
python C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\net\sg_tenancy.py --run C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\ttd\runs\receipt-20260903-stage9-anchor --inputs %TEMP%\sg_inputs_long.txt --ticks 9000 --k 1 4 8 16 24 32 --json %TEMP%\sg_tenancy3.json
```

**Mine (new):** `C:\Users\trist\projects\mvc-live-skins-quarters\d3dcap\net\blk_delta.py` ·
`...\d3dcap\net\sg_tenancy.py` · this document ·
`C:\Users\trist\projects\maplecast-flycast\tools\re_kb\128_supergun_server_arch.surql`
(**applied** 2026-09-04; backup `re_kb_data/_exports/re_kb_20260904-162659_pre128.surql`; 16 findings, 15
confirmed + 1 open, all `-cites->` the new source; verified by `SELECT VALUE id FROM finding WHERE
->cites->source CONTAINS source:supergun_server_arch_20260904` returning 16).

> **Seed-authoring note for other lanes, learned the hard way this pass:** `finding.status` carries a
> schema `ASSERT` — a finding may only be `'confirmed'` if it **already** cites a `source` whose `strength`
> is `'reproduction'` or `'code'` (or cites a `routine`). So a seed must set the status **after** the
> `RELATE ... cites ...` statements, and a `strength='measurement'` source will silently block every
> promotion. `apply_seed.py` defers status writes to a second pass, which handles the ordering, but it
> cannot fix the `strength` value.
**Read, not edited:** `d3dcap/net/sg_bench.cpp` (netcode lane) · `d3dcap/receipt/runner/rr_runner.cpp`,
`gate_n1.py`, `gate_n1c.py` (ENGINE lane) · `docs/SUPERGUN-NETCODE.md` (netcode lane).
**Data (BYOR, under `%TEMP%`, never committed):** `rrcap_runner\gate2_300\blk_t*.bin` (stage 9, 301 dumps,
plus `dcram_t*.dlt`) · `rr_g4\run_cd00\blk_t*.bin` (Carnival, 300) · `sg_tenancy\k*` ·
`sg_inputs_long.txt` · `rr_q2_gate2_300.json` · `rr_q2_carnival.json` · `sg_tenancy3.json`.

**Addresses used (all previously CONFIRMED; none newly derived here):** `blk[0..0x33B18)` = 211,736 B ·
object pool `blk+0x6DD8`, 256 × 0x280 · fighters `blk+0x3DB8`, 6 × 0x738 (health `+0x578`, drawn `+0x170`) ·
stage/camera `blk+0x6908` · render-list records `blk+0x1000` (0x38 stride) · frame clock `blk+0x3CC8` ·
battle state `blk+0x32500` · sim tick `FUN_140118950` → `FUN_140607d60` · texture decompress buffer
DC `0x0CE60000` · exe base `0x140000000` (position-dependent, `rr_runner.cpp:709`).

---

## 13. What this document does NOT claim

1. **It does not claim our transport beats Steam's.** That is UNPROVEN and stays UNPROVEN until Gate N4.
   Nothing here depends on it — §3.1 holds under every outcome of N4.
2. **It does not claim the combat write set is bounded.** §2.1 is two stages, 600 frames, no super. The
   ~6–8 KB ceiling in §2.2 is an INFERRED scaling argument. U-S2 is the test.
3. **It does not claim server density is 282 matches/core.** That is sim-only. With rollback it is 18–38,
   and the delta-encode cost (U-S4) and per-packet cost are not in the number at all.
4. **It does not claim jitter is worse than constant delay for fighting games.** The cited evidence is FPS
   literature; the transfer is INFERRED (U-S7).
5. **It does not report any pixel result.** Consistent with `GATE-N1` §9: a save-set or `blk` comparison
   proves **sim** agreement and never **pixel** agreement, and `ctx` equality is specifically not a proxy
   for it. Nothing in this document is a rendering claim.
