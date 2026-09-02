# WORKSTREAM — from here to the smallest possible tape

> **STATUS: 2026-09-02, written from three expert reviews** (senior-re-generalist,
> gsta-verification-harness, flycast-internals-expert). This supersedes the first draft of this file
> **including its central premise**, which was wrong. `RENDER-ACCURACY-PROGRAM.md` remains the SSOT
> for what has actually been proven.

---

## 0. ⚠⚠ THE CORRECTION THAT REORDERS EVERYTHING

The first draft of this workstream, and several statements made while writing it, said *"flycast
reproduces Steam's raw sim state BIT-EXACT, so the hard part of Architecture A is already proven."*

**That over-states the SSOT, and the ledger says the opposite.**
`RENDER-ACCURACY-PROGRAM.md:425-436`, 2026-08-30, a frame-exact B2 re-run on a clean tape with
assists on and measured alignment:

> **bit-exact on ALL 6 fighters through f1223** → input/assist/init reconstruction is COMPLETE and
> CORRECT. **FIRST divergence f1224: `char15.px` off by exactly 1 float32 ULP (1.5e-5)**, then
> `char44.vx` 1 ULP as a constant offset — **DC SH4 vs Steam x86-64 rounding**. Benign until the
> **first super**, which amplifies it across a hit-decision boundary → HP cascades → a different
> match. ⟹ **no input/assist/init/RNG fix can close a 1-ULP float gap; free-run resim is NOT viable
> for a full faithful match.**

And gate **G-COMBAT** (`:242-247`) records the status plainly: **"NOT PASSED, NOT KILLED."**

`CONFIRMED-TAPE-AND-FLYR-REPLAY.md`, which the first draft quoted, is the **older and weaker**
result — it labels itself "RNG-blind, bit-exact only up to the first hit". The newer, stricter ledger
entry governs. Two independent expert reviews caught this; it should not have needed catching.

**What this does NOT change:** the input feed is tiny and that number is real and measured.
**What it DOES change:** what a small feed currently buys you.

## 0b. ⭐ DIRECTION CHANGE — Path A is dropped, and so is resim-as-primary

Tris, 2026-09-02: *"why are we even thinking about path a? we proved path b end result can be pixel
perfect, now we just optimise the hell out of the data/bandwidth and see how we can derive that
pixel-perfect end with the least amount of data … lets find the Steam version of the SH4 process that
emulates the frame."*

He is right, and it dissolves the problem the rest of this document was built around.

**Both alternatives fail for the SAME reason and Path B does not:**
* **Path A** (reconstruct the draw list from a state tape) hits the effect-cell / HUD / 3D-class
  ceiling. Those assets do not exist offline.
* **flycast resim** hits the **1-ULP cross-core wall** — DC SH4 vs Steam x86-64 rounding.
* **Steam's own code has NEITHER problem.** It is the arithmetic that produced the pixels we
  captured. There is no cross-core divergence because there is no cross-core.

⟹ **The question is no longer "which engine reproduces the match" but "what is the smallest input to
STEAM'S OWN render path that reproduces the frame".** Everything below in Lane C about determinism
certificates is about the flycast path, and is now a SECONDARY lane.

### What was found in Ghidra, immediately, from the capture's own call-site data

The capture records that **885 of 890 draws in a frame come from ONE return address, `0x1402B72F4`**.
That address is 964 bytes inside **`FUN_1402B6F30`**, and decompiling it settles what that layer is:

**`FUN_1402B6F30` is Steam's COMMAND-LIST EXECUTOR — the structural analogue of the DC's TA FIFO.**
It walks a stack of 16-byte command records, switches on a **4-bit opcode** (`*(u16*)(cmd+2) & 0xF`,
cases 0-7 and 0xE), and for each one sets pipeline state from four object pointers at `cmd+8`,
`+0x10`, `+0x18`, `+0x20` (via `FUN_1402BC2A0` / `FUN_1402BA6F0` / `FUN_1402BA920` / `FUN_1402BAF60`)
and then calls a virtual on the device wrapper — `+0x60` and `+0x68` are the draws, `+0xA0`/`+0xA8`
the instanced variants, `+0x170`/`+0x1C8` blits, `+0x1A8` a clear, `+0x148` another draw class.
Opcode 6 **pushes a nested command buffer** — a call-list, exactly like a TA object list.

**The command buffer itself is located:**
```
renderer + 0x8678F0 + parity*8   base pointer   (double-buffered)
renderer + 0x867900 + parity*4   count, in 16-byte records
renderer + 0x678C0               the parity index (XOR'd by a flag at renderer+0x42)
renderer + 0xC0                  the D3D11 context   ← already probed by d3dcap
```
`FUN_1402BCC60` is the frame SUBMIT: GPU timestamp begin → execute the list → end → reset. So the
command list is **built earlier in the frame and consumed here**.

### What that changes

This is a **higher-level, far more compact representation than the D3D11 draw stream, and it is the
game's own output.** A record is 16 bytes plus four references into a pipeline-state pool that the
capture already measured at only **11-16 distinct combinations per frame**.

**The open question, and it is now THE question:**
> **What builds that command list, and what does it read?**
> If the command list is a pure function of `blk`, then the minimal feed is a **`blk` delta per
> frame** — no simulation, no inputs, no determinism certificate, no float divergence — and Steam's
> own emitter (or a faithful port of it) turns that back into pixel-perfect frames.

That is directly measurable with tooling we already have, and it is the next thing to do:

* **D1 — measure the `blk` delta rate.** `verify.py rng` already reported **6,466 of 52,934 words
  changed over 600 frames**. Get the PER-FRAME figure and its compressed size. If a frame's `blk`
  delta is ~1 KB raw / ~200 B gzipped, **that is the floor, and it beats every other candidate while
  being immune to every determinism hazard in this document.**
* **D2 — find the emitter.** Walk backwards from the command buffer at `renderer+0x8678F0`: who
  writes it? `FUN_1402B3B80` is only the GPU timestamp query, so the builder runs earlier in the
  frame. Ghidra has the binary loaded (29,678 functions, `0x140001000`-`0x143D52749`).
* **D3 — is it a pure function of `blk`?** The falsifiable form: capture `blk` + the command list on
  two frames with identical `blk` content and check the command lists are identical. If they differ,
  something outside `blk` feeds the renderer and D1's floor is wrong.
* **D4 — capture the command list directly** instead of the D3D11 stream. A shim hook at
  `FUN_1402B6F30`'s entry has the base pointer and count in registers.

### D1 RESULT — measured live, 600 consecutive in-battle frames, 60.1 samples/s

```
changed BYTES     median   507   p90 1,044   p99 2,278   mean   568   max 2,903
changed WORDS     median   216   p90   432   p99   989   mean   243   max 1,256
contiguous RUNS   median   215   p90   414   p99   933   mean   236   max 1,193
GZIPPED payload   median   426   p90   897   p99 1,576   mean   484   max 1,983   B/frame

of 52,934 words in blk, 11,433 (21.6%) changed at least once
                            69 (0.13%) changed in over half the frames
```

⚠ **The 484 B figure EXCLUDES the run headers, and that is a flaw in how the script reports.** With
236 runs per frame at 8 B each, the naive encoded size is **2,453 B/frame raw**. So the honest range
for a straightforward encoder is **~0.8-1.2 KB/frame**, i.e. **8-13 MB for a 3-minute match**, not
5 MB.

**But run-length is the wrong encoding for this shape.** 568 changed bytes spread over 236 runs is
**2.4 bytes per run** — the changes are scattered, not clustered, so per-run headers cost more than
the payload. The distribution says what to do instead:
* only **11,433 of 52,934 words ever change** ⟹ ship a **static volatile-word index once**, then a
  per-frame sparse bitmap over just those 11,433 bits (1,430 B raw, very sparse, compresses hard)
* only **69 words change in over half the frames** ⟹ a hot/cold split shrinks it further
* (`replay-kit/volatile_set.py` already computes an adjacent set — the words that differ between two
  cold boots — for a portable anchor. Different set, same idea.)
Realistic target with a proper encoder: **~0.6-0.9 KB/frame, 6-10 MB per 3-minute match.**

### D1b — `blk` DECOMPOSED. Tris's hypothesis holds, and the structure is now explicit.

Tris: *"the first frames of the match load all the data — that's probably what's in blk too."*
Measured, with the per-word change histogram saved from a second 600-frame run:

```
REGION                            words   volatile        %
fighter slots (6 x 0x738)         2,772        269     9.7%
match options                        50          9    18.0%
camera                                4          3    75.0%
object pool                      44,810     14,147    31.6%     <- 84.6% of blk
everything else                   5,301        267     5.0%     <- ESSENTIALLY STATIC
```

**"Everything else" is 95% static over 600 frames.** That is the loaded match data, exactly as
predicted: it ships ONCE in the anchor and never again.

**And the dominant region is confirmed to BE the object pool, by periodicity rather than by
assertion.** Testing candidate strides for how cleanly volatility separates into hot/cold columns:

```
stride 0x280 (160 words) x 280 rows -> 85.0% of columns decisive, 69 hot columns
stride 0x400                        -> 16.0%
stride 0x380 / 0x300 / 0x200 / 0x180 -> ~15.6% each
```

`0x280` wins by 5x. That independently corroborates `mvc2-dc-steam-block-map` ("object pool CONFIRMED
live, stride 0x280, inside blk, node = fighter-struct prefix") from a completely different direction —
a volatility histogram, not a disassembly.

**The pool, located and sized:**
```
base   byte 0x6908 in blk (word 6,722)
shape  280 nodes x 0x280 B
live   241 of 280 nodes changed at least once over 600 frames; 191 have >20 hot words
hot    69 of 160 words per node are volatile in >50% of nodes
```

### ⭐ THE PHASE IS SETTLED — from a live pointer walk, reproduced 4x identically

`replay-kit/poolphase.py` dereferences the list head at `*(blk + 0x2EEB0)` (per
`mvc-hud-list0b-live-re`) and walks it via `+0x08`. That yields real node ADDRESSES, so the phase is
measured rather than fitted:

```
list head *(blk+0x2EEB0) = 0x18df1dd8
walked 44 nodes, 44 inside blk
residue of (node - blk) mod 0x280:   0x258  x44      <- unanimous, 4 runs identical
category byte at +0x03:              {11: 44}        <- all cat 0x0B
lowest node blk+0x9D58; first node at/after the fighter slots: blk+0x6B58
```

**The ledger was right and my guess was wrong.** `blk+0x6DD8` has residue `0x258`; my `0x6908` has
residue `0x008`. The pool is `blk + 0x258 + k*0x280`, and the first node at or after the six fighter
structs is **`blk+0x6B58`**.

Two structural facts fall out:
* **the array holds MULTIPLE categories.** All 44 walked nodes are `cat 0x0B` — the HUD/UI list from
  `mvc-hud-list0b-live-re` — out of ~287 node slots. So the `0x280` array is a shared object pool and
  the list-0x0B nodes are one tenant of it.
* re-running the field scan at the CONFIRMED phase, **12 of 17 in-range known fighter-struct fields
  land on hot columns, against a chance level of ~7.3**:

```
HOT      +0x050 px      +0x054 py       +0x124 screenX  +0x128 screenY  +0x12C depth
         +0x130 zx      +0x134 zy       +0x154 facing   +0x170 drawn    +0x188 sid
         +0x1A0 gfx1    +0x1D0 anim_state
NOT HOT  +0x058 vx      +0x05C vy       +0x144 sprite_id  +0x168 anim_ptr  +0x1A4 gfx2
```
Every RENDER-relevant field is hot; velocity and the animation pointers are not. That is consistent
with "node = fighter-struct prefix", and unlike the retracted version it rests on a phase that was
measured independently of the histogram. ⚠ 12 vs 7.3 on n=17 is **suggestive, not conclusive** — it is
the confirmed phase that makes the mapping trustworthy, not the hit count.

### ⚠ The pointer-array reading was REFUTED by reading the values — and it exposed a sampling error

`nodefields.py` classified every hot column across all 44 live nodes. **Everything from `+0x120`
onward is ZERO, unanimous** — including `screenX`, `screenY`, `depth`, `zx`, `zy`, `facing`, `sid`,
`gfx1`, `anim_state`, and the entire 8-byte-spaced run. So it is not a pointer array in these nodes.

The contradiction with the histogram is the finding: **the node is a VARIANT.** Category `0x0B` uses
only `+0x000..+0x120`. The hot columns past `+0x120` come from the OTHER ~243 slots — other
categories. **The 44 nodes I sampled are not representative of the pool**, and reading a per-category
layout off a pool-wide histogram was a mistake in the same family as the phase error.

### ⭐ What the read DID find, and it is better

```
+0x000  0x0B000000            the category byte at +0x03. Confirms the walk.
+0x008  ptr:blk, 44 distinct  the next link. Confirms the chain.
+0x018  0x140653CE0, 9 DISTINCT VALUES across 44 nodes
        -> inside the EXE IMAGE. A PER-NODE HANDLER FUNCTION POINTER, and 9 handlers in this list.
+0x034  small int             the slot/player index
+0x050  61.3f  +0x054 -45.5f  real coordinates at the fighter-struct px/py offsets
+0x0A0  ptr, 28 distinct      a per-node resource, in neither blk nor the exe
+0x0F0  0x00010C11            a constant
```

Ghidra resolves `0x140653CE0` in one step. It is written by **`FUN_140653FD0` — a node CONSTRUCTOR**:

```c
if ((*(uint *)(i*0x738 + 0x4324 + DAT_142edf560) & 0x7000000) == 0) {   // gate on fighter i
  node = FUN_14061DBE0(0, 0x0B, 1);                                     // <- THE POOL ALLOCATOR,
  if (node) {                                                           //    category passed in
    *(u8  *)(node + 0x170) = 1;                                         // drawn
    *(u64 *)(node + 0x018) = &LAB_140653CE0;                            // <- the handler
    *(u64 *)(node + 0x0A0) = *(PTR_DAT_142edf598 + 0x300);
    *(u32 *)(node + 0x0F0) = 0x10C11;
    *(u32 *)(node + 0x094) = *(node+0x098) = *(node+0x09C) = 0x3F800000; // 1.0f x3
    *(char*)(node + 0x034) = (char)i;
```

**Every one of those matches the live read exactly** — `0x10C11` at `+0x0F0`, three `1.0f` at
`+0x094/98/9C`, the slot index at `+0x034`, the handler at `+0x018`. Static code and live memory agree
field for field, which is a far stronger cross-check than either alone.

Two things are now named:
* **`FUN_14061DBE0` is the pool allocator**, taking the CATEGORY as an argument. It has **40+ call
  sites** — one per object type the game can spawn.
* **`+0x18` is a per-node handler function pointer**, not a vtable. The object system is
  "allocate a node, install its handler".

### What this means for D2 (scoping the emitter)

The emitter is **bounded and enumerable, but it is not small**: an allocator with ~40+ spawners, plus
a handler per node class. ⚠ And a caution that matters for the whole architecture: **those handlers
are game LOGIC — they update objects.** Porting them is porting a chunk of the game, which is exactly
what a replay should not have to do.

### ⭐⭐ D2 ANSWERED — the frame function, found from the live game in two runs

Static analysis stalled because the object system dispatches through per-node handler pointers
Ghidra never resolved. So the shim was taught to record a **backtrace** on every vertex/index buffer
write. Two runs, and the chain resolves end to end:

```
  x4719  flags=0x9  2,097,152 B   0x140371740 <- 0x1402B6B34 <- 0x140056020 <- 0x14026DF8A
  x4719  flags=0x2    524,288 B   0x140371740 <- 0x1402B6B65 <- 0x140056020 <- 0x14026DF8A
```
```
FUN_14026DD20                the game loop
  └─ FUN_140055D40           ⭐ THE FRAME FUNCTION — ticks ~30 subsystems, then:
       └─ FUN_1402B6A50      uploads the 2 MiB VERTEX buffer + the 512 KB INDEX buffer
            └─ FUN_140371620 generic buffer upload -> UpdateSubresource
```

* **2,097,152 B is exactly the vertex buffer `d3dcap` already dumps.** The chain that writes it is now
  named, and its two upload calls sit 49 bytes apart in one function.
* **The game writes geometry through `UpdateSubresource`, never `Map`** — the only `Map` writer in the
  session is Steam's overlay DLL. Geometry arrives as a whole-buffer push.
* `FUN_140055D40` calls ~30 subsystem virtuals at `+0x30` on objects held at `param_1+0x3FF60`
  through `+0x40130`, and only THEN calls the uploader. So the buffer is already full when it uploads.

**⟹ The game rebuilds the ENTIRE 2 MiB vertex buffer in CPU memory every frame, from scratch.**

That is the most important structural fact yet, and it is exactly the shape the architecture needs:
a whole-buffer rebuild each frame is, by construction, a **pure function of the state at that
moment**. It does not prove D3 — but a game that incrementally patched its vertex buffer would have
made D3 false on the spot, and this one does not.

### ⭐⭐⭐ AND WE DO NOT HAVE TO PORT IT — the emitter is ALREADY reverse-engineered, on the DC side

Tris: *"we have the ROM though, we know exactly how the game behaves too."* Correct, and it changes
the build entirely. The re_kb already carries the DC sprite-emission chain, cited to instruction:

```
loc_8c030af8   satellite/effect setup   (sibling of loc_8c03093c "Render Main Sprite")
  -> loc_8c034bea   sel dispatch on node+0x144: 0xFF = terminator, &0x8000 = scaled, else ->
    -> loc_8c0344d4   THE BODY WALKER            bank03.asm:10218
         record loop          loc_8c03489e :10772
         per-record entry     loc_8c0345c4 :10349   (@(0x6,r11) = sel)
         count gate           loc_8c034782 :10608
         PER-TILE SUBMIT      loc_8c034864 :10739
         flag axes            0x4000 @10477 / 0x8000 @10503; neg Y control 0x20, neg X control 0x10
         the transform itself fr12 = (r10+r4)*scaleX@0xEC,  fr13 = (@0x14+r5)...
  -> bank12   loc_8c1216c0 transform,  loc_8c1244b0 / 0x8C1248CC  SPRITE-PARA SUBMIT
```

**Steam's emitter IS a recompile of that code.** So "port Steam's ~30 subsystems" was the wrong
framing — the correct one is *implement the DC emitter we already have*, and
`buildEmitterDrawList` in `sprite-client.mjs` is already a partial implementation of exactly this
walker.

**⟹ The reason to go to Steam was never the LOGIC. It is the ASSETS and the ORACLE:**
* the effect cells and the HUD bank, which do not exist offline
* a pixel-exact reference to check the emitter against, which never existed before

And it re-prices everything. The build is no longer "reverse-engineer and port an unknown
subsystem". It is:

1. **feed the existing emitter properly** — `blk` delta gives 276 B of node state where the tape gave
   32 B, which is the measured ratio behind the reconstruction ceiling;
2. **map `blk` -> DC work-RAM** — already established as 5 piecewise deltas that close to the byte
   (`mvc2-dc-steam-block-map`), and the object pool is confirmed on both sides;
3. **fix the assembly data** — ⚠ this is the real open risk, not the code. The union-of-tiles search
   found no convergence (best 0.685), which means our offline `_asm.json` geometry may not describe
   the engine's actual quads. **More state does not fix a wrong assembly table.**

⚠ Two honest cautions against over-reading this:
* the DC chain is CONFIRMED for the BODY walker. The effect/satellite path, the 3D class and the HUD
  list are separately mapped and less complete.
* `node+0x144` is the `sel` dispatch field on the DC side. In our Steam pool read it was **not** hot —
  but the 44 nodes sampled were category 0x0B (HUD), which is a different tenant of the pool. Nothing
  is settled there yet.

### The honest scoping verdict

The emitter is **one (or a few) of those ~30 subsystems**, not the whole game — and per the section
above, **we do not need to port it at all**, because it is a recompile of DC code we have already
disassembled and partly implemented. Steam's value here is the oracle and the assets, not the logic.

**Next, and it is small:** `FUN_140371620` receives a descriptor carrying the SOURCE pointer
(`+0x20`, or `+0x38` on the alternate path). Log it, and we learn **where the CPU-side vertex buffer
lives**. If that buffer's contents are derivable from `blk`, the architecture is real; if it is fed
from an arena we do not carry, we learn that before building anything.

**So the question sharpens again:** for a REPLAY we do not need the spawners or the update logic. We
need only the path that turns node STATE into draw commands. Is that a separate walk over the pool, or
is drawing done inside the same handlers that update? **That is the next thing to establish, and it
decides whether this ports or not.**

There is also a **regular 8-byte-strided run of hot words from `+0x1A8` to `+0x228`** (17 entries) —
the shape of a pointer table or an array inside the node. Unidentified; worth a look.

⚠ **What was retracted, and why it matters as a lesson: the node PHASE was undetermined, and the field mapping I first
wrote down was chance.** Reshaping from `0x6908` gave "8 of 18 known fighter-struct fields land on hot
columns", which looked like confirmation. It is not: **a random 69-of-160 hot set hits ~7.8 of 18 by
chance.** 8 is exactly noise.

A full phase sweep settles that it cannot be resolved this way: the ledger's base `0x6DD8` scores
12/18, but so do `0x6B58`, `0x6938` and `0x6918` — four different phases tie, and 11/18 is reached by
several more. **Volatility alone cannot fix the phase.** It needs the allocator
(`loc_8c044dce`, per the ledger) or a live pointer walk, not a histogram.

**What survives, and it is the load-bearing part:**
* the `0x280` periodicity itself — 85% of columns decisive vs ~16% for every other stride, a 5x
  margin. The region IS a `0x280`-stride array.
* 69 of 160 words per node are volatile in over half the nodes, whatever those words are called.
* the region sizes and volatility percentages above.

### ⭐ Why the state tape hits a ceiling — the version that does not depend on the phase

The agent's tape carries **32 B per object node**. The volatile part of a pool node is **69 words =
276 B**. **The tape is a lossy projection keeping under an eighth of what changes.** That ratio holds
regardless of which offsets the words sit at, and it is why reconstruction has a ceiling and always
will — while `blk` is the right feed for a pixel-exact replay and the tape stays right for everything
else.

### The per-frame economics

Although 241 nodes are live across 600 frames, only **~3.5 nodes' worth of hot columns change per
frame** (244 changed words / 69 per node). The pool is mostly quiescent frame to frame — which is
precisely why the delta stays under a kilobyte while the full state is 211 KB.

### Where that lands it

| feed | per frame | 3-min match | needs |
| --- | ---: | ---: | --- |
| confirmed GGPO inputs | ~0.9 B | ~0.01 MB | a determinism certificate we do not have |
| the agent state tape | ~136 B | ~1.5 MB | a reconstructing renderer — the effect/HUD ceiling |
| **blk delta** | **~0.6-1.2 KB** | **~6-13 MB** | **Steam's own emitter, client-side** |
| D3D11 draw stream | ~37-62 KB | ~400 MB | nothing — but undeliverable |

**~40-80x smaller than the draw stream, ~5x larger than the state tape — and unlike either, it needs
no simulation, no inputs, no determinism certificate and no float-equivalence proof.**

### ⚠ THE STRUCTURAL CONSEQUENCE, and it reframes D2

Capturing the command list is **NOT** the compression win. The executor reads
`*(longlong*)(record+8)` — the 16-byte records hold **pointers** to command objects elsewhere, and
following ~890 of them at ~0x40 bytes each is ~57 KB/frame, the same order as the D3D11 stream.

**The win is `blk`. Which means the client must RUN STEAM'S EMITTER** — the code that turns `blk`
into the command list. So D2's real purpose is not "find the function" but **SCOPE IT**:

> How many functions sit between `blk` and the command list, and what else do they read?
> If it is a bounded subsystem, it ports to WASM and this architecture is real.
> If it reaches into the whole game, it does not.

That is the question to answer next, and it is a static-analysis question — no live session needed.

⚠ **Nothing here weakens the epistemics.** A command list is still an observation of OUR instrument;
"pure function of `blk`" is a hypothesis with a named falsifier (D3), not a finding.

## 1. The two honest product framings — pick one deliberately

| | **(A) "A faithful replay of this match"** | **(B) "The receipt — THIS match, byte for byte"** |
| --- | --- | --- |
| method | free-run resim from confirmed inputs | needs the 1-ULP gap closed or bypassed |
| feed | **5,610 bytes gzipped for a whole 6,580-frame match** (measured) | same, plus whatever closes the gap |
| fidelity | faithful through neutral and early combat, then **drifts into a different but plausible fight at the first super** | exact |
| status | **works today**, server-side | **falsified as free-run**; one cheap lever untried |
| good for | highlights, a shareable replay, showing what happened | a money-match dispute, a verifiable record |

**Neither is wrong. They are different products, and the difference is invisible in a demo and
decisive in a dispute.** Per `rr-ggpo-determinism`: *do not settle a money dispute on a
re-simulation.* That memory was right and remains right.

⚠ **This decision is Tris's and must be made explicitly, not by default.** If it is (A), Lane A below
ships and Lane C shrinks to a sanity check. If it is (B), Lane C is the whole programme.

## 2. The numbers, measured, so nobody re-derives them

**The feed** — converter run on a real tape this session:
```
tape 59604650: 6,580 frames, teams p1[42,44,50] p2[52,42,56]
movie.txt        144,840 bytes
movie.txt.gz       5,610 bytes    ← the ENTIRE match's input feed
```
Against the TA mirror artefact for a comparable match: `render_ta_wire_full.zcst` = 313,229,658 B for
8,497 frames = **36,864 B/frame**. **Ratio ≈ 50,000 : 1.** The instinct that the feed should be tiny
is right by four and a half orders of magnitude.

**The three per-frame costs, for scale:**
| what | per frame | a 3-minute match |
| --- | --- | --- |
| confirmed inputs (movie.txt.gz) | **~0.9 B** | **~10 KB** |
| the agent's state tape (gzipped) | ~136 B | ~1.5 MB |
| Path B's D3D11 draw stream (gzipped) | ~37-62 KB | ~400 MB |
| the TA mirror `.zcst` | 37-53 KB | **240-350 MB** |

⟹ **Neither the draw stream nor the TA mirror is a delivery format.** Both are internal ground-truth
artefacts. Path B is an ORACLE and an ASSET SOURCE.

**Path B itself** — 300 consecutive frames of a 3-meter triple super replay at 0.011-0.018% of pixels
differing, zero missing coverage. ⚠ That number is our D3D11 replay of a captured draw stream — a
same-engine closed loop. It is a very good number **about the capture** and says nothing about resim,
reconstruction or determinism.

**Assets are bounded:** 379 of 383 texture generations arrive in the first 9 frames of a match;
~1 MB of raw texels covers 4-10 s; 931 KB after sha256 dedupe. ⟹ a **content-addressed library plus a
per-match manifest of hashes**, not a save state.

## 3. Three lanes. C gates B. A ships regardless.

---

# LANE C — DETERMINISM
**Owner: senior-re-generalist + flycast-internals-expert. Gate held by gsta-verification-harness.**

## C0 — ⭐ THE CROSS-BUILD FP CENSUS. Do this first. Zero new code.
Nobody has ever run the determinism harness across build targets, and there are **three different
floating-point targets** in play:
* Windows MSVC (`build-headless-win`) — `/fp:precise`, no scalar FMA contraction
* Linux GCC (rise3) — **`-ffp-contract=fast` is the GCC C++ default**; `a*b+c` may be fused
* wasm32 clang — WASM MVP has **no scalar FMA**, so contraction is impossible

`grep "fp-contract\|ffast-math\|fp:fast" CMakeLists.txt` → **no explicit FP flags anywhere.** And
SH4's `FIPR` (`core/hw/sh4/interpr/sh4_fpu.cpp:400-418`) is a four-term double accumulation —
precisely the shape a compiler contracts. `FSRRA` (`:357-368`) is `1.f/sqrtf()`; the x64 dynarec does
**not** lower it to a hardware approximation (`grep fsrra core/rec-x64/rec_x64.cpp` → no hits), so
interpreter-vs-dynarec is probably safe. Cross-*host* is not.

**Run:** the same movie under `MAPLECAST_GSHASH_LOG` on Windows-MSVC and on Linux-GCC; `diff`.
**PASS:** byte-identical for ≥5,000 frames.
**FAIL:** names the first divergence frame — **and every cross-host resim result to date is suspect.**
*Needs a rise3 build. Highest value-per-hour item in this document, and it was on nobody's list.*

## C0b — executor equivalence. OFFLINE, NO CODE CHANGES.
`MAPLECAST_USE_INTERPRETER` already exists (`core/emulator.cpp:568`) and already switches the
executor. Every determinism result we have came from the **native x64 dynarec**; a browser would run
the **interpreter**, a third engine nobody has compared. `flycast-wasm/README.md:12-15` — the stable
WASM branches are "Interpreter only."
**Run:** two headless runs, identical but for `MAPLECAST_USE_INTERPRETER=1`, both with
`MAPLECAST_GSHASH_LOG`; `diff`. **PASS:** byte-identical through match end.

## C1 — the last untried lever on the ULP wall. Cheap, low probability.
`RENDER-ACCURACY-PROGRAM.md:435-436` already names it. Set explicit FP flags (`-ffp-contract=off`,
`/fp:strict`), audit `FIPR`'s double accumulation and `FSRRA` against the recompile's arithmetic.
**PASS:** free-run resim bit-exact to the tape's recorded Steam raw state **through the first super**
on a clean (`rollbacks:0`) tape with RNG draw count > 0.
**A pass unblocks framing (B) entirely.** A fail closes the input-side approach for good.

## C2 — DECISION GATE. Tris's call, written and dated.
If C1 fails: ship framing **(A)**, or fund **state injection** — driving the engine with the recorded
per-frame state. ⚠ State injection is **not** speculative and **not** free: it was built and run, and
poking `sprite_id (0x144)` without `anim_pointer (0x168)` / `animation_state (0x1D0)` produced
**100,990 SH4 exceptions**; position-only injection stalls the render after the first inject; and the
one stable injector disables the VRAM memwatch so **it cannot emit a `.zcst`** (`:634-648`). That
tension is unresolved and must be costed before anyone commits to it.

## C3-C5 — the Steam-side chain (ONE live session covers all of it)
"Determinism" is **five independent links**, not one gate, and A needs all five:

| link | claim | status |
| --- | --- | --- |
| **L1** | Steam's trajectory is a pure function of (char-select config, inputs) | **OPEN** — `verify.py rng` returned a correctly self-reported *no-information* result |
| **L2** | the inputs we recorded == the inputs Steam consumed | **OPEN, CONFIRMED BUG** — `tape_to_flycast_movie.py:97` hardcodes `seat0→P1`; the mapping is **per-tape**, keyed on `local_pn` |
| **L3** | flycast (native dynarec) reproduces Steam's trajectory | **INCONCLUSIVE** — the 1-ULP wall at f1224 |
| **L4** | flycast (WASM/interpreter) == flycast (native) | **NEVER TESTED** → C0b |
| **L5** | pvr2's render of that TA == Steam's pixels | **NOT BUILT** → Lane B |

* **C3 — `rrtape4.py play m035949.rr4`** on a cold-booted Steam. ⚠ **`play`, not `ab`.** `ab` compares
  two of *our* runs; `play` compares our run against the tape's own **119 checkpoints from the
  original live game**, including a **CRC32 of the whole 211,736-byte region**.
  ⚠ **The confound:** `feed_tape` polls the frame clock from Python, so a missed poll is
  indistinguishable from a determinism failure. **A FAIL is only a finding if the first-divergence
  frame REPRODUCES across three runs. If the frame MOVES, it is the feeder.**
* **C4 — `rrtape4.py ab`, only AFTER a blocking fix.** ⚠ Today `ab` will print
  **"✅ A == C … the claim we needed, and it holds"** for a churn that sat on the character-select
  screen and never fought. `rrtape4.py:527-547` — `churn()` writes random pad words and returns only
  `fed`; it never checks mode, never checks that hp moved, never checks `ROLLBACKS`. **That is a false
  win with a checkmark on it.** Fix first: report frames with `mode[2]==2`, the hp delta, the rollback
  delta, and refuse to pass without evidence of a fight.
* **C5 — `verify.py rng --exe`** during a super, with `lcg_scan` looped over a small constant table
  (DC, MSVC `rand`, glibc) — a generator-*family* probe for ~3× the cost. ⚠ **Do NOT run `--arena`**:
  256 MB × 38,400 steps on a non-frozen read, for the same zero information a negative always gives.
* **Preconditions in the same session:** `verify.py reg` (the `G+0x48` fork ≥ 3 — ⚠ `rrtape4.py:65`
  defines `G_SEL` and **never reads it**) and `verify.py blk2` (the second registered block at
  `blk+0x33B18` is **NOT rollback-saved** — the textbook "set before, read during" hazard, and there
  is no recorded run of it anywhere).

## Hazards that survive all of §6's items
* **H1 — match options live inside `blk`, and a flycast cold boot has its own.** `FUN_140608690`
  copies difficulty/damage/time into `blk+0x3C40…0x3D07`. Damage level changes gameplay outright.
  Fix is cheap and must be designed in **now**: a per-match option block on the wire, plus a poke.
* **H2 — stage id** (`blk+0x6D3C`, `blk+0x32530`), same shape. ⚠ **UNKNOWN whether the resim even
  lands on the right stage** — no stage path was found in `maplecast_autoselect.cpp`.
* **H3 — ⚠ every checkpointed `.rr4` we own is TRAINING MODE.** Derived from the checkpoint stream,
  not a label: only slot 1 takes damage, hp *regenerates* to 144 repeatedly, `timer` pinned at 99.
  **A training-mode result says nothing about versus**, which adds round transitions, KO/results
  phases, switch-in and snapback — and round transitions re-enter `FUN_140608690`.
* **H4 — point characters are identified by sprite-id match, NOT team-array order.** A wrong point
  character reproduces as an X-position divergence at the first assist — **exactly the signature B2
  attempt 1 reported.**
* **H5 — ⚠ Architecture A has ZERO ERROR TOLERANCE and nobody has priced it.** One dropped input frame
  desyncs the client permanently, undetectably. **Ship a periodic state checksum with the inputs** —
  six char-struct XXH3s every N frames is ~8 B/s, ~5% of the feed. It converts a silent catastrophic
  failure into a detected one, **and turns every match played in production into a live determinism
  datapoint.** Design it into the wire, not after.
* **H6 — anchor privacy:** the 56-bit unlock mask makes a `blk` anchor per-account identifiable.

## The anchor is SOLVED — do not re-litigate it
Cold-boot MENUNAV costs **zero bytes** and is already a complete unattended state machine
(`maplecast_autoselect.cpp:212-231`): it pulses START on both pads until char-select, latches
`g_everCS` so it can never mash through the VS intro, reads the **live** 8×8 grid table at
`0x8C161FEC`, BFS's the cursor to each target, handles colour-select, and hands off the instant
`in_match != 0`. And battle-init calls **`srand(1)`** (`loc_8C11E770`, hard-writing `RngVal` at
`0x8C16BC2C`), so **any anchor at or before battle-init is RNG-equivalent** — an anchor buys nothing
that running the ROM does not already give you. Savestates are 5-9.5 MB, restore-stall, and are
format-coupled to the build. The Steam-`blk` anchor is triple-blocked and retired.

---

# LANE A — MAKE THE PIPELINE THAT WORKS TODAY UNATTENDED
**Owner: flycast-internals-expert. Ships regardless of Lane C.**

The path that works end to end today:
```
tape → tape_to_flycast_movie.py → movie.txt
     → flycast headless (MAPLECAST_AUTOSELECT + MENUNAV + MOVIE_IN + MIRROR_SERVER)
     → capture_mirror_full.mjs → .zcst → play_zcst.html (FrameDecoder → TAParser → PVR2 → WebGPU)
```

* **A1 — one-shot tape→resim driver.** One script reads a tape and emits `MAPLECAST_AUTOSELECT`,
  `MAPLECAST_ASSIST` (per-character in **pick order**, with the per-tape slot remap), the movie, **and
  the measured pace offset**. ⚠ Fixes `tape_to_flycast_movie.py:97` — key the seat on `local_pn`.
  ⚠ `ggpo_sim_tie` is MISLEADING (one tape's real offset was **+1**, not the reported +6) — the
  alignment must be **measured** by correlation, not read.
  *Accept:* on ≥5 tapes with mixed `local_pn`, emitted P1/P2 match the tape's `p1_in`/`p2_in` at
  ≥99.9%, and the resim reaches `in_match` with the correct roster read back from guest RAM.
  **This blocks every other resim result from being trustworthy.**
* **A1b — resolve the HP/HK trigger conflict.** `replay_reader.cpp:414-417` says MvC2's HP/HK live on
  the DC analog triggers; `tape_to_flycast_movie.py:32` maps them digital and puts assists on the
  triggers. **If the comment is right, two of six attack buttons are being dropped on every resim to
  date.** *Route to `mvc2-sh4-re-expert` for a `loc_8c010080` citation.*
* **A2 — stage selection.** *Accept:* guest-RAM read-back equals the tape's `stage_id` on ≥5 tapes.
* **A3 — unattended runner.** *Accept:* one command produces a playable artefact for 10/10 tapes with
  no human input, including one with `rollbacks > 500`.
* **A4 — the product loader. ⚠ `play_zcst.html` is demo-grade and its own hint text is false.**
  `:92-97` loads the **entire** `.zcst` via `arrayBuffer()` — 313-440 MB — then `:111-117` runs a full
  index pass decoding every message before frame 0 renders. `:56` claims "a backward seek re-decodes
  from the last keyframe, ~1s"; `seekTo()` at `:133` re-decodes from **message 0** every time. The
  wire *does* force a keyframe every 60 frames (`maplecast_mirror.cpp:2606`) — the player just never
  indexes them. *Accept:* time-to-first-frame < 3 s, peak memory < 500 MB, backward seek < 1 s.
* **A5 — artefact size.** Enable `MAPLECAST_ZSTREAM` / `MAPLECAST_VCACHE` and measure. If a full match
  cannot get well under 100 MB, **the `.zcst` is not a delivery format** and the product wire must be
  re-scoped. *May force a product decision.*

---

# LANE B — PIXEL TRUTH
**Owner: gsta-verification-harness. Contingent on C2.**

## ⚠ B0 — G-PIXEL CANNOT BE BUILT AS SPECIFIED. A build-config impossibility, recorded nowhere.
`RENDER-ACCURACY-PROGRAM.md:249-252` specs it as `MAPLECAST_GSTA_SHOT_EVERY=1` + `GetLastFrame`. But
`core/hw/pvr/Renderer_if.cpp:489-494` forces `norend` **unconditionally when headless, even on GPU
builds**, and `core/rend/norend/norend.cpp` has no framebuffer and no `GetLastFrame`.
⟹ **the resim rig physically cannot produce a client framebuffer.** G-PIXEL must diff the *browser's*
render against a reference from a **second, non-headless build**. Whoever picks up B3 will otherwise
hit this wall with no warning.

## The measurement, ordered cheapest-first — and geometry before pixels
⚠ **A pixel diff between flycast/pvr2 and Steam/D3D11 is confounded across three layers** — sim
divergence, TA-vs-draw-call translation, and rasteriser differences. A number out of it cannot be
attributed to a layer. **That is this project's signature failure mode in new clothes.**

⭐ **Start with the round-start still.** At round start both sides are at fixed spawn positions, fixed
sprite ids, zero RNG consumed — **identical by construction**. That frame is alignable with certainty
on day one, **with no determinism requirement at all**, and it buys the entire asset-identity,
geometry, palette, blend-class and layer-order comparison before anyone argues about supers.

| # | gate | threshold | proves | does NOT prove |
| --- | --- | --- | --- | --- |
| **M0** | Steam sim-clock delta across the burst | 300/300 steps == +1 | 1 Present = 1 sim frame, no rollback | nothing about flycast |
| **M1** | sidecar-vs-draw phase (384×224, corner-aware) | one phase ∈{−1,0,+1} explains ≥99% of drawn fighters | the sidecar describes the frame we captured | nothing about the resim |
| **M2** | preconditions: 6 char ids, stage, round | **exact, zero tolerance** | the two runs are the same fight | nothing about frames |
| **M3** | state fingerprint, bit-exact, single constant `k` | N/N frames, `k` constant, anchor unique within ±600 | alignment is established | that the render agrees |
| **M4** | drawn-object census | exact, per frame | no missing/extra objects — catches compositing bugs geometry cannot see | nothing about where |
| **M6** | **asset identity**: Steam R8 tiles + palettes vs `MAPLECAST_PARTDUMP` | ≥99% byte-identical | the two builds ship the same art — **the precondition that makes any pixel number interpretable** | nothing about layout |
| **M5** | geometry, per-part rects, **union rule** | ≤1 native px on ≥99.5% | positions/sizes agree | nothing about colour or order |
| **M7** | pixel diff, edge-masked, 640×480 | ≥99.5% within ±1 LSB | our two renderers of the same state agree | **nothing about MvC2** |

**Alignment is exact, not searched.** Three clocks are in play — d3dcap's `g_frame` (Present calls),
the publish `frameNum`, and **the game frame**. flycast already reads and publishes the game clock
(`0x8C3496B0`, `maplecast_rollback.cpp:940`, `maplecast_mirror.cpp:3983`), and Steam's is
`blk+0x3CC8`. Join on a **state fingerprint hash**, assert the anchor is **unique within ±600 frames
on both sides**, derive ONE constant `k`, and **ban per-frame offset search in the code** — a tool
allowed to re-search per frame will always find something and will convert a real divergence into a
plausible match.
⚠ **Do NOT compare memory hashes cross-core**: `gshashLogTick` hashes DC char structs at stride
`0x5A4`; Steam's stride is `0x738`. Field-by-field only.
⚠ **Capture the reference burst in an OFFLINE local-VS match.** `blk+0x3CC8` mirrors GGPO's
`_framecount`, which `Sync::LoadFrame` assigns **backward** on rollback; and a presented frame during
rollback shows a mispredicted state the resim will never produce. Offline removes the whole class.

### Expected differences — do NOT chase these
Steam is 2× DC resolution into a 2048×1024 scene RT then a 9-pass bloom/SMAA chain (**diff the scene
RT, never the backbuffer**); reversed-Z + log depth on our side vs forward-Z on Steam (only an
**order** inversion is a bug); `depth32float` vs `D24_UNORM_S8_UINT` (the **cape** is an exact Z tie
resolved by submission order — flicker under diff is expected); ±1 ULP `mad` fusion; Steam uses only
**seven distinct z values** across all character draws; uninitialised vertex `NORMAL` is NaN by design.

### Would indicate a REAL bug
⭐ **Any per-object BLEND difference.** Steam exposes it at the API — `SRC_ALPHA × INV_SRC_ALPHA` vs
**`SRC_ALPHA × ONE`** — and blend is the one thing reconstruction structurally cannot get (it is a
runtime PVR register, not a part field). **This is the Rosetta stone and it is worth every hour.**
Also: palette content mismatch, missing/extra objects, alpha-test coverage differences.

### The corroboration that makes near-exactness a legitimate expectation
Steam's four pixel shaders are **specialisations of flycast's own DX11 macro matrix**
(`core/rend/dx11/dx11_shaders.cpp:263-340`). The shading semantics are literally the same code
lineage. Model differences as **flycast shader tuples**; anything that cannot be expressed as a tuple
difference is a bug.

---

# 4. What NOT to build

1. **❌ A full maplecast-flycast WASM emulator, as the primary plan.** `grep -i emscripten CMakeLists.txt`
   → **zero hits**; the fork has no WASM target. The only WASM assets on this box are a
   **renderer-only** 851 KB module (`packages/renderer/` — TA parser + PVR2 GLES, zero SH4) and a
   **third-party repo against upstream flycast** whose last committed state is `build-error.log`:
   `rec_wasm.cpp.o Error 1`. Measured interpreter performance: **0.4-5 FPS on a 9800X3D**. A 3-minute
   match = 10,800 frames = **36 minutes of wall clock in a tab.**
2. **❌ Fixing the WASM JIT.** 51 of 70 SHIL ops, foreign repo, build failing.
3. **❌ Re-litigating the anchor.** MENUNAV works, costs zero bytes, and `srand(1)` makes any
   pre-battle anchor RNG-equivalent.
4. **❌ Fixing the savestate restore-stall now.** MENUNAV makes it unnecessary. ⚠ Note the existing fix
   (`rend_resync_after_rollback`) is likely aimed at the wrong thing — it Sets `renderEnd` explicitly,
   yet the single-threaded symptom is "1 frame then idle", which a `renderEnd` deadlock cannot explain.
5. **❌ Streaming the TA mirror as the product wire.** 240-350 MB/match.
6. **❌ Chasing rasteriser differences from the EXPECTED list.**
7. **❌ Hand-expanding the additive gfx1 allowlist.** The Steam capture supplies ground truth instead.
8. **❌ A geometry-only gate as a sign-off.** It cannot see texture, decode, texcache or thread-timing
   bugs. But geometry **first**, as a cheap filter — that is different and it is right.
9. **❌ Letting "0.011-0.018% differing" migrate into a sentence about MvC2.**

# 5. Rules. Each one was paid for.

1. **A pixel diff is a MEASUREMENT, not a mechanism.** `record_attempt(outcome='masks_only')`, never a
   finding. re_kb writes go through `tools/re_kb/kb.py`, never raw SQL.
2. **A runtime pointer is never an identity; a per-frame identity is never a cross-frame one.**
   Four bugs in one session.
3. **A statistic derived from an instrument is never evidence about that instrument's blind spot.**
4. **Report coverage and colour separately.**
5. **Hand-execute on the CPU before blaming the GPU.**
6. **Real assets only.** Never an approximation, never a tuned coordinate.
7. **BYOR.** `.pack`, `.seq`, `.bmp`, `.bin`, replay `*.png` are ROM-derived and gitignored.
8. **Prefer an instrument with no blind spot over one that shares the hypothesis's assumption.**
9. **Reproduce a first-divergence frame three times before calling it falsification.** A frame that
   MOVES is a feeder bug; a frame that STAYS is a finding.
10. **Do not generalise a training-mode result to versus.**
11. **Calibrate a threshold on one set of frames, FREEZE it, then evaluate on held-out frames.** A
    threshold tuned after seeing the result is not a gate.
12. **When two docs disagree, the newer and stricter one governs** — and say so out loud. §0 of this
    file exists because that was not done.

# 6. Live-session batching

| batch | what | serves |
| --- | --- | --- |
| **L1** | ONE solo Steam session: `verify.py reg` + `blk2`, `rrtape4.py play`, then `ab` (after the churn fix), then `rng --exe`. ⚠ NOT `--arena`. | C3, C4, C5 |
| **L2** | an **OFFLINE local-VS** match with d3dcap + sidecar + the agent recording a tape of the same match; bursts at **round start** (~120 frames) AND the super (300 frames) | Lane B, M0-M7 |
| **L3** | a **versus** tape with checkpoints (every `.rr4` we have is training mode) | H3 |
| **L4** | a burst with real camera movement | validates the stage-is-static result, measured on a stationary camera |

Everything in Lane C except C3-C5, and everything in Lane B after capture, is **offline**.

# 7. Open contradictions someone must resolve

* ⚠ **`RENDER-ACCURACY-PROGRAM.md:1441+` records a 2026-08-31 product decision to DROP the flycast
  resim** in favour of a Steam self-replay video, while the 2026-08-30 pivot says build the resim
  render. **This is upstream of this entire workstream.** Resolve it before anyone spends a session.
* The G-COMBAT ledger entry has an internal inconsistency — first hit at f1217 but "diverged at the
  first assist entry (f1199)", i.e. the divergence precedes the hit it says was exact. Reconcile
  before quoting.
* Is DC `0x8C3496B0` the same counter as Steam `blk+0x3CC8`? INFERRED-consistent, not proven; the two
  sit in different segments of the 5-delta piecewise DC↔blk map. **Route to `mvc2-sh4-re-expert`.**
* Asset identity Steam vs DC GDI — UNKNOWN until M6 runs. Everything pixel-level is conditional on it.

---

## 12. ⭐⭐⭐ M6 ANSWERED — the asset identity is CONFIRMED, and the assembly table is SOUND

> 2026-09-02. `d3dcap/replay/asm_ident.py`, run on packs already on disk. No live session, no new
> capture, no game state, zero fitted constants. This closes the open item that section 11 ended on
> ("Asset identity Steam vs DC GDI — UNKNOWN until M6 runs. Everything pixel-level is conditional on
> it") and it retires the "the assembly data may be wrong" risk that the rest of this document was
> written around.

### 12.1 What Steam's character path actually is

Measured on frame 2574 (84 indexed draws). Every character draw is **one quad**, and:

* quads are exactly **8x8, 16x16 or 32x32** in native units — integer, square, power of two;
* the **UV span in TEXELS equals the size in native units EXACTLY**. Scale is 1:1. There is no zoom
  and no transform;
* every quad samples a **32x32 R8_UNORM index page** plus a 256x1 RGBA palette, POINT on both;
* **index values are 0..15 only** — 4bpp is preserved end to end, index 0 is the transparent entry;
* **each quad carries its own z**, stepping by a constant ~1.79e-7 per draw. Draw order is encoded in
  the depth value — the registration counter, exactly as `mvc-render-composite-model` states.

So the Steam character path is a **plain 2D tile blit**: the sprite is cut into 8/16/32 tiles taken
from 32x32 pages. The DC assembly record `(dx, dy, part)` sits **one level above** this, which is why
comparing the two needs a union and not a per-quad match.

### 12.2 M6: the pixel banks are the SAME BYTES

Take each captured 32x32 index page and search for a byte-exact copy in every offline `PLxx_idx.png`
— a 4bpp bitmap match across **60 candidate characters** with zero free parameters.

```
frame 2574:  8 pages matched byte-exact -> PL17 x7, PL2C x1
frame 5630: 12 pages matched byte-exact -> PL32 x7, PL2A x5
frame 3893:  8 pages matched byte-exact -> PL17 x6, PL2C x2
```

Matches are at **exactly 1.000**, not a threshold, and matched positions cluster into contiguous
32-aligned blocks in the atlas. **⟹ the ROM-extracted index pixels ARE the bytes Steam draws.** The
offline extraction pipeline is correct at the pixel level, and Steam vs DC GDI asset identity is
CONFIRMED rather than assumed.

A second capability falls out for free: **the character is recoverable from a capture that carries no
game state at all.** That does not remove the need to log `blk` at Present, but it does mean every
capture already on disk can be labelled retroactively.

### 12.3 The falsifier: does the assembly table place the parts?

For each matched tile we know its atlas position AND its screen position, so we can resolve which
packed part contains it and derive that part's screen top-left. Seven independent tiles on frame 2574
collapse onto just **two** part placements, each confirmed redundantly and with **no disagreeing
observation**. Then: is there one assembly whose records place every observed part at one origin?

```
frame 2574  PL17   part 1149 (32x64) @ 328.8,82.1  [2 tiles]   part 1158 (64x128) @ 296.8,130.1  [5]
            -> EXACT, zero residual, facing LEFT.  origin (319.8, 202.067).  sel 10 of 681
frame 5630  PL32   part 89   (32x32) @ 363.6,167.1 [1 tile]    part 81  (128x64) @ 315.6, 87.1  [6]
            -> EXACT, zero residual, facing LEFT.  origin (354.6, 202.067).  sel  1 of 581
```

**Two different characters, two different frames, both exact, and both land on `origin_y =
202.067`.** Neither run was given the other's answer — a shared ground line is an independent
cross-check that the model is not fitting noise. Frame 5630 pins the `sel` **uniquely, 1 of 581**.

### 12.4 The placement law (confirmed, no fitted constants)

```
screen_x = origin_x - dx           # facing LEFT (mirrored);  + dx when facing right
screen_y = origin_y + dy
within a part, a tile at atlas offset (offx, offy):
    x += offx
    y += (part_h - tile_h - offy)  # the packed part bitmap rows are BOTTOM-UP
```

### 12.5 ⚠⚠ THE MISTAKE THIS ALMOST BECAME, and the rule that catches it

The first version of this test reported "1 of 2 parts agree" and pointed at the assembly table as the
defect. It was **my test that was wrong, not the data**, and the tell was sitting in the numbers:

```
observed part-to-part delta   dx = +32   dy = -48
table   part-to-part delta    dx = -32   dy = -48
```

**One axis exactly negated and the other exactly equal is the signature of a MIRROR** — the facing
flip, the DC walker's neg-X control (`0x10`, bank03) surfacing in Steam pixels. It is not the
signature of corrupt geometry, which does not politely preserve one axis.

> **RULE: a near-miss in ONE axis only is a transform you have not modelled. It is almost never bad
> data.** Corruption is not axis-aligned.

The same applies to the earlier **union-of-tiles / IoU test that "found no convergence, best 0.685"**
and was read as evidence against the assembly data. That reading was wrong for a different reason:
**silhouette IoU between two conservative covers of a humanoid has no discriminating power.** Steam's
tiles and the assembly's part rects over-approximate the same sprite at different granularities, so
two *different* characters also score 0.7-0.8. Re-run here it tops out at **0.802 on an unrelated
character**. The test could not have failed for the right reason, so it could not have passed for one
either. **A test with no discriminating power produces a null result, not a negative one — and the
two must never be recorded as the same thing.**

### 12.6 What this does NOT establish

* The placement law is confirmed on **2 parts per body, on 2 frames**. It is not certified over a
  whole pose, and no record has been checked for characters other than PL17 and PL32.
* Frames 2700 and 3893 matched only ONE part each. **With a single part the origin is always
  solvable**, so those runs test nothing and the tool refuses them rather than reporting a pass.
* **The within-part vertical inversion is measured but NOT explained.** Five tiles of part 1158 are
  consistent only with bottom-up part rows while the record says `flipy=0`. The likely cause is the
  row order `rip_gfx2_assembly.py` writes into `_parts.png`, not the engine — but it is unproven, and
  it is exactly the shape of defect that turns a limb into a column or a blob. Check it before
  blaming placement for one (see `mvc-render-composite-model`, the Blackheart "column to blob" note).
* Effect cells, the HUD bank and the 3D class are untouched by this. It covers the **body walker's**
  output only.

### 12.7 What it changes for the build

The three-part plan in section 11 was: (1) feed the emitter 276 B of node state instead of 32 B,
(2) map `blk` to DC work RAM, (3) **fix the assembly data — flagged as the real open risk.**

**Item 3 is now closed, and it was never broken.** Pixels, parts and placement records are all sound;
what was missing was the facing sign and the part row order in the consumer. That removes the one
risk that could have invalidated everything downstream, and it means `buildEmitterDrawList` can be
validated against the Path B capture **tile by tile** rather than against a whole-frame percentage —
a diff that says *which* tile is misplaced, instead of "0.685".

### 12.8 ⚠ CORRECTION, same session — "facing LEFT (mirrored)" was an over-claim

12.3 and 12.4 above first labelled the `- dx` sign as **"facing LEFT (mirrored)"**. That label was
inferred from the sign alone, and a direct test kills it:

```
frame 2574 vs PL17:  matched UNFLIPPED 7   matched ONLY-FLIPPED 0
frame 5630 vs PL32:  matched UNFLIPPED 7   matched ONLY-FLIPPED 0
```

**14 of 14 tiles match the atlas unflipped; not one matches only when mirrored.** The drawn content
is never mirrored, so nothing is being flipped and the sign cannot be a facing flip. `screen_x =
origin_x - dx` stands — it is measured, exact and replicated — but it is a **dx sign convention in
the rip**, and the tool now reports it as `dx NEGATED` / `dx AS-IS` rather than naming a facing.

The arithmetic in 12.3 is unaffected: two characters, two frames, zero residual, shared ground line.

**⚠ AND IT SURFACES A CONCRETE DISCREPANCY IN THE CONSUMER.** `sprite-client.mjs:1069` mirrors as

```js
const cdx = cfl ? -(sp.dx + sp.wG) : sp.dx;   // mirror the (asymmetric) anchor when flipped
```

The capture says `-dx`, with **no width term**. The two differ by the part's own width — which is
precisely the displacement that scrambles a body while leaving it roughly in the right place, and it
scales with part size, so big parts land further out than small ones. Whether the renderer or the rip
carries the wrong convention is NOT settled here; the capture only says what Steam draws. **Settle it
before trusting either**, and settle it with `asm_ident.py` against a frame where a body is known to
be facing right, since every body measured so far resolved under the same sign.

The band-order rule in 12.4 (`y += part_h - tile_h - offy`) needs the same caution: each tile's
PIXELS are upright (a byte-exact unflipped match proves that), so what is reversed is the order the
32-row **bands** stack, not the rows inside them. Measured on 5 tiles of one part; not explained.

---

## 13. ⭐⭐⭐ `blk` IS THE WHOLE ROLLBACK STATE — read out of Ghidra, not inferred

Tris, 2026-09-02: *"make sure you aren't guessing, we have the rom, steam ghidra, marvelous2
disassembly … all we really need to do is move the game forward 1 frame."* So this was read out of the
binary. Every address below is rebased to `0x140000000`.

### 13.1 Where `blk` comes from

`BLK_PTR = EXE + 0xAC6EF0` → **`0x140AC6EF0`**, and it has exactly **two** xrefs in the whole binary:
one READ in `FUN_140118290`, one WRITE in `FUN_140608690`.

**`FUN_140608690` is MATCH INIT.** It does, in order:

```c
DAT_142edf560 = *(longlong *)(DAT_142ef0ab0 + 0x10);       // blk
memset(DAT_142edf560, 0, 0x33b18);                          // <-- exactly BLKSZ
*(PTR_DAT_140acd3a0 + 0x1b0) = DAT_142edf560;               // register block 1: ptr
*(PTR_DAT_140acd3a0 + 0x1b8) = 0x33b18;                     //                   size
DAT_142edf568 = DAT_142edf560 + 0x33b18;                    // a SECOND block, immediately after
memset(DAT_142edf568, 0, 0x33b20);
*(PTR_DAT_140acd3a0 + 0x1c0) = DAT_142edf568;               // register block 2
*(PTR_DAT_140acd3a0 + 0x1c8) = 0x33b20;
DAT_142edf580 = DAT_142edf560 + 0x3cb8;                     // the GAMEFLOW struct inside blk
```

So `blk` is zeroed at match start, and the **frame clock at `blk+0x3CC8` is `DAT_142edf580 + 0x10`**.
Match options are written at `blk+0x3c40` / `+0x3c43`, which matches the region map already in §11.

### 13.2 The save-state builder settles the question

`FUN_140118290` is the state SAVE path — it zeroes a 1 MB staging buffer, then:

```c
DAT_142d10950 = 0;                                    // descriptor COUNT
DAT_142d10954 = 0;                                    // total BYTES
if (*(uint *)(PTR_DAT_140acd3a0 + 0x48) < 3) { FUN_1401183a0(); return; }
if (*(PTR + 0x1b0) != 0 && (n = *(int *)(PTR + 0x1b8)) != 0) {
    DAT_142d10950 = 1;                                // ONE descriptor
    DAT_142d107d0  = *(PTR + 0x1b0);                  // = blk
    DAT_142d108d0  = n;                               // = 0x33b18
    DAT_142d10954  = n;
}
```

`DAT_142d107d0[]` / `DAT_142d108d0[]` / `DAT_142d10950` / `DAT_142d10954` are a **scatter-gather
descriptor list** — pointers, sizes, count, total. And `FUN_1401183a0` (the `< 3` branch, i.e. the
*other* titles in the Collection) shows what a NON-trivial state looks like: ~7 subsystem blocks
appended one by one, plus, for `< 2`, raw slices of an emulated address space obtained from
`FUN_1401125d0(n)` — `+0x500000` (0x830), `+0x800100` (0x80), `+0x900000` (0x30000), `+0xff0000`
(0x10000), `+0x400000`, `+0x660000`, `+0x700000`, `+0x708000`, `+0x804000`. Those are DC/NAOMI
memory-map offsets.

> **⟹ On the `>= 3` path the ENTIRE save state is ONE descriptor: `blk`, 0x33B18 bytes.**
> Not a memset size we reasoned from — the save-state builder itself registers exactly one block.

⚠ **The second 0x33B20 block is NOT in the save list.** It is allocated beside `blk` and registered at
`+0x1c0`, but `FUN_140118290` never adds it. Do not treat it as state until something is shown to
save or restore it; a shadow/compare buffer is the likelier reading.

⚠ **INFERRED, not confirmed: that MvC2 is the `>= 3` case.** The deduction is that `FUN_1401183a0`
never touches `+0x1b0`, while `FUN_140608690` is the thing that fills `+0x1b0` — so a title using the
`< 3` path would never see its `blk` saved. Strong, but the honest close is to read
`*(PTR_DAT_140acd3a0 + 0x48)` live. One `u32`. Do it before this gets quoted as CONFIRMED.

### 13.3 ⚠⚠ ROLLBACK STATE IS NOT RENDER INPUT — this does NOT close D3

GGPO save/load only has to be sufficient to **re-simulate identically**. It says nothing about what
the RENDERER reads. Our own Path B capture proves the character path samples a pool of 32×32 index
pages and 256×1 palettes — **assets, which are not in `blk`**. So the candidate is `blk` + the loaded
asset set, and **D3 (are two frames with identical `blk` guaranteed to produce identical command
lists?) is still unrun.** §11's warning stands unchanged.

### 13.4 "Isn't it StartRender?" — no, on either side

* **flycast:** `STARTRENDER` is a PVR register (`core/hw/pvr/pvr_regs.cpp:131`, `case
  STARTRENDER_addr`). Writing it kicks the TA → framebuffer render of a display list **that the game
  already built**. It renders a frame; it does not advance the simulation by one frame.
* **Steam:** there is no PVR and no TA at all. The structural analogue is the command-list executor
  `FUN_1402B6F30` and the frame submit `FUN_1402BCC60` (§11).

**The Steam per-frame function is `FUN_140055D40`** — and it is the SHELL frame, not the game: it
ticks ~30 subsystems through `vtable+0x30` / `+0x48` / `+0x50`, polls Steam (`DAT_1408db5a8`,
`DAT_1408db5c0`, `DAT_1408db5a0`), then calls `FUN_1402b6a50` to submit the renderer. The MvC2 match
logic is a module in the `0x1406xxxxx` range: `FUN_140607e90` reads `DAT_142edf580` (= `blk+0x3CB8`)
and mirrors gameflow, round and per-fighter state out into `PTR_DAT_140acd3a0`; `FUN_14060af70`,
`FUN_14060b440`, `FUN_14060c070`, `FUN_14060a1f0` are its siblings.

**So "move the game forward one frame" is one of `FUN_140055D40`'s subsystem ticks, and it has not
been isolated yet.** Naming it is a bounded next step: `FUN_140055D40` makes ~30 dispatched calls, and
the one that advances `blk+0x3CC8` can be found by breaking on writes to that address, or by hooking
each `+0x30` in turn. Do not guess which; there are 30 candidates and they all look alike.

---

## 14. ⭐⭐⭐ THE STAGE IS STATIC, AND THE HUD BANK IS ALREADY IN EVERY CAPTURE

> Tris, 2026-09-02: *"the stage we can run statically from assets, we can learn how it's displayed
> from the 10 second gold source we have — that has the full HUD and background render, it's static
> but moving camera."* Both halves are measured below, and the second one retires a recorded blocker.

### 14.1 The stage mesh is fixed; only the camera moves

Hashing each `vs_world` draw's vertex bytes and intersecting the sets:

```
frame_5481   208 distinct world-space draws
frame_5630   489
frame_2574   462
5630 vs 2574  (DIFFERENT MATCHES)  455 shared          <- essentially all of it
5481 vs 5630  (same match)          86 shared  (41%)   <- mid-super, most of the stage culled
```

**455 draws byte-identical across two different matches.** The stage is a fixed world-space mesh
keyed by `stage_id`; per frame only the CAMERA changes and the visible subset varies with culling.
The low 5481 overlap is not a counter-example — that frame is inside a 3-meter super, where the
flash replaces most of the background.

⟹ **Rip the stage once per `stage_id` and reuse it for every replay on that stage.** The camera is
already in the tape (`eyeX`, `eyeY`, `ground`), and the geometry is world-space with the camera in a
constant buffer, which is exactly why the vertex bytes repeat.

### 14.2 ⭐ THE HUD SPRITE BANK IS IN THE CAPTURE — the "live dump" blocker is obsolete

`frame_5630` carries a **256x128 RGBA texture with 17,101 non-transparent pixels**, which is exactly
the bank `sprite.wgsl`'s `fs_hud` documents. Dumped and flipped (it is stored bottom-up like every
other page — see §13's V-axis note), it is the complete HUD font:

> ASCII upper and lower case, digits, punctuation, `©` `®` `™`, `対応`, `WINS`, `VM 対応！`, `ED`,
> hearts and arrows.

**This contradicts `mvc-hud-list0b-live-re`**, which records *"the UI sprite bank is NOT offline →
live-dump via `replay-kit/hud_bankdump.py`"*. That was true of the OFFLINE ROM extraction. It is not
true of the D3D11 captures: Steam has to upload the bank to draw it, so the shim sees it, and every
capture ever taken already contains it. No live dump is needed for the font.

⚠ **Scope, so this is not over-read.** What is confirmed is the **font/glyph bank**. The HUD also has
health bars, meters, portraits and the timer, and those may live in other pages — `frame_5630` also
carries `(256,256)`, `(128,128)x2`, `(64,64)x3` and a `(1,1)` RGBA texture, and which of those are
HUD versus stage has NOT been determined. The way to settle it is by which draws bind them, not by
size. `mvc-hud-list0b-live-re`'s other finding stands untouched: the HUD objects are list-`0x0B`
pool nodes and are NOT in any tape, so the HUD's *state* still has to come from somewhere.

### 14.3 What this makes buildable

| piece | geometry / pixels | per-frame state | status |
|---|---|---|---|
| bodies | offline atlas | tape `sid/sx/sy/facing/costume` | **PIXEL-EXACT** (§13, `emitter_gate.py`) |
| objects (capes, projectiles) | offline atlas, owner's char | tape `objs` stream | drawing; ordering open |
| stage | **rip once per stage_id from a capture** | tape `eyeX/eyeY` | geometry proven static |
| HUD chrome | **the 256x128 bank, from any capture** | list-0x0B nodes, NOT in the tape | bank found; state is the gap |
| effects / supers | offline + capture pages | tape `objs` + `cat`/blend | additive state liftable from the super capture |

The one genuinely missing input is **HUD state** — the list-`0x0B` nodes are not recorded in the tape
at all. Everything else now has both its pixels and its per-frame state identified.

---

## 15. ⭐⭐⭐ THE RENDER MODEL, CLOSED FOR SPRITES — measured against Steam, per pixel (2026-09-02)

Everything below was established with state and pixels from the SAME frame (the shim now dumps `blk`
at Present), verified against Steam's own draw stream, and where it mattered, read out of the Steam
binary in Ghidra or the DC disassembly. `v3gate.py` is the falsifier: 30 state-carrying frames,
**20 exact** (14 at 100.00%, six within 1–2 px); every remaining miss is in the super frames and has
a named cause below.

### 15.1 What is PROVEN (v3gate 100.00% on quiet frames)
* **Placement law**: `origin = (floor(sx640)·3/5, floor(sy480)·7/15)` — the engine TRUNCATES the
  640×480 screen coord to an integer first (433.6→433, 422.5→422). `part_left = origin_x − dx`
  (mirrored: `origin_x + dx − w`), `part_top = origin_y + dy`; part bitmaps are packed bottom-up.
* **Paint order is DEPTH order, not walk order.** Steam's walker submits `z = base + 0.001·(k+1)`
  per record; the sink `qsort`s the whole pass by z DESCENDING, ties FIFO (comparator
  `@0x1408434d0`). Measured: within a body z falls along draw order (record 0 nearest); within a
  layer the later-registered node has the larger base (`layerAcc += 0.001·parts`) and is BEHIND;
  across layers the base is linear in the layer INDEX (`0.979379 + 0.000359·L`, lower = nearer).
  ⟹ paint: layers far→near (LayerZ table for 8..15, flagged), reverse registration within a layer,
  reverse record within a node. **`sort = −8` means IN FRONT** (front of the array → nearest).
* **The one-frame staleness**: the walker WRITES `+0x124/+0x128` during the render, so state must
  be read AFTER it (Present). Pairing frame N with `blk(N+1)` fixed every moving-character miss.
* **sid bit 15 is a record-FORMAT flag** (Ghidra `FUN_1406129f0`), not a flip. Removing the XOR
  took the super frames from 28.7% to 40.4%.
* **Palette row is per RECORD**, `(flags>>4)&7` from the ROM (body 0, Storm's lightning 2, her
  satellites 1), applied on Steam by which 256×1 palette the draw binds — index pages are plain
  1..15 under every palette (0 texels > 15 in 130k). This closes the "PL32 sub-row 2" gap.
* **One pixel blob per character**: effect nodes inherit the owner's GFX1 pointer by struct copy
  (bank09) and share its GFX2 (+0x1B0 identical). The effect texels ARE in our atlases.
* **`+0x148` bit 15 (DC `node+0x104`, the walker's rotation path)** ⇔ node absent from the
  axis-aligned indexed stream: 370/0/0/24 over 30 frames, zero exceptions. Rotated sprites are
  not tiles on Steam.

### 15.2 What REMAINS, each with its evidence and owner
| gap | evidence | status |
|---|---|---|
| **rotated sprites** (`+0x148` bit15) | 24 nodes, zero rotated quads in the indexed stream | SH4 expert on `loc_8c03481c` inputs/math |
| **runtime reveal / blank** | same sid: one bolt's part 156 page all-zero, sibling shows only the tip; Cable's beam 32×40 of 64 with texels only in rows 0..7/40..47 | SH4 expert: tile arena `node+0xDC/+0x120`, animation script |
| **P4 body absent** | `+0x170=1`, `sid 0x8000`, `flash 0x0030` (others 0x10/0x18/0x20), one PL34 tile in the frame, not in the world pass either | SH4 expert: flash 0x30 path |
| **world-space RGBA class** | 118 on-screen `vs_world/texalpha` draws in a super frame from **12 shared pages** (two present in all 30 frames = 1P/2P markers + shadow disc; one = the additive effects sheet); not keyed by any System-B node's `gfx1` | System A nodes — not in `blkstate`, not in the tape; needs its own state source |
| **tape staleness** | agent samples at a random phase relative to the walk | design: sample after the walk (agent change) |

### 15.3 Tape v3 → v4 deltas implied
`rot` (`+0x148` bit 15 + angle field once specified), the reveal state for effect nodes (field TBD),
and a System-A node stream for shadows/markers/effect glows. None of these change the body path,
which is exact.
