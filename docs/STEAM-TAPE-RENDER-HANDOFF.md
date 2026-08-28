# Steam-Tape → Canvas Replay — Workstream Handoff

> **Purpose:** the single anti-drift anchor for "render a Steam MvC2 tape on canvas."
> Read this first every session. Update it (and commit) at the end of every session.
> _Started: 2026-08-27._

## END GOAL (one line)

Feed our **Steam 0.3.26 tape** into the **existing MapleCast render pipeline** so it plays back on
a browser canvas. **We are NOT building a new renderer** — the renderer is already solved.

## The one decision that keeps us from drifting

`maplecast-flycast` already draws MvC2 pixel-exact from a **GSTA/OBJS state stream**
(`web/webgpu-test.html` → `web/webgpu/sprite-client.mjs` `onOBJS`/`buildDrawList`, sprite machine
CLOSED 5/5, bodies byte-exact). `king.html`/`webgpu-test.html` are **reference for solved problems**,
not code to copy or re-derive.

- ✅ **The path we take:** Steam tape → **OBJS state adapter** → existing sprite-client → canvas.
  Our tape columns (`sid, sx, sy, zx, facing, hp` per fighter) map ~1:1 to the per-object OBJS state
  (sprite_id, screen x/y, scale, xflip). This is the FAST + correct route, and it is **engine-agnostic**:
  it consumes high-level state (sprite_id indexes the baked atlas = same game art on DC/NAOMI/Steam;
  screen coords are screen coords), so it sits ABOVE the DC-vs-NAOMI memory-map difference — **no guest
  RAM needed at all.**
- ❌ **Not this (for the tape):** the render-replica / MCRR path (`replay.html` + `mc_render_rec.bin`)
  needs **raw guest-RAM regions** (char structs, idxtab/rectab, VRAM `bodytex`) — which our tape, being
  high-level derived state, does not carry. Separately note the engine gap: MapleCast's render-replica is
  authored against **DC** addresses (`0x8C…`, `mvc2.gdi`), while our tape + the flycast proof are **NAOMI**
  (same game code, different RAM map). A RAM-level path would need **NAOMI** guest RAM — which we only get
  by re-simulating the confirmed inputs in flycast NAOMI (Path 2, below) AND re-deriving the read-set for
  the NAOMI map. That is the pixel-perfect track, not the fast one.
- ❌ **Not this:** a from-scratch Artifact/canvas renderer (attempted + parked — it re-solves what the
  sprite-client already solved).

### DC vs NAOMI — keep this straight
- **MapleCast render stack = Dreamcast build** (`mvc2.gdi`, DC area-3 `0x8C…` throughout).
- **Our Steam tape + flycast determinism proof = NAOMI.** Same MvC2 code, different RAM base/layout.
- The **OBJS/sprite-client** path is unaffected (high-level, engine-agnostic). Any **RAM-level** path is
  DC-addressed today and would need NAOMI remapping. Don't feed NAOMI addresses into DC-addressed code.

## Where things live (cross-repo map)

| Piece | Repo | Notes |
|---|---|---|
| The renderer (sprite-client, webgpu, atlases, bake) | `maplecast-flycast` (`web/`, `tools/`) | render authority = its `docs/RENDER-STATE.md` + `_consolidated/CURRENT-STATE.md` |
| The Steam tape capture (0.3.26 agent) | `RetroReceipts-agent` | worktree-locked here → ship as diffs (`docs/patches/agent-0.3.26-reader.diff`) |
| The tape/replay specs + this handoff | `mvc-live-skins-quarters/docs` | `CONFIRMED-TAPE-AND-FLYR-REPLAY.md`, `REPLAY-ENGINE-DESIGN.md`, this file |
| The tape server (`/rr/gamestate`) | `RetroReceipts-server` | I own deploy (149.28.44.118) |
| The tape→movie converter (flycast Path 2) | `mvc-live-skins-quarters/replay-kit` | `tape_to_flycast_movie.py` |

## DONE this session (2026-08-27)

- **Tape is FINAL + verified.** 0.3.26 captures render columns (`sx/sy/zx/zy`) + `stage_id` +
  `confirmed_in`. Live-verified on the server: tape **59596085** = 6519 render frames + **6650 dense
  confirmed-input frames** (both seats, zero gaps). Teams P1 [42,44,50] vs P2 [52,42,36], stage 0.
- **413 upload blocker FIXED.** `nginx /rr/` had no `client_max_body_size` → inherited the 1 MB default;
  render-column tapes upload as `base64(gz)` in JSON (+33% → ~1.26 MB) and 413'd. Added
  `client_max_body_size 64M;` to the `/rr/` block on 149.28.44.118 (backup in `/root/nginx-backups/`,
  NOT sites-enabled). All tapes now upload 200.

## NEXT

1. **Test canvas (IN PROGRESS, sprite-render expert):** wire tape 59596085 → OBJS → existing
   sprite-client, serve a page, watch it play. The fastest watchable milestone.
2. Formalize the **tape → OBJS adapter** (schema + coordinate transform) once the expert confirms the
   OBJS shape + viewport mapping.
3. Fold the adapter into `maplecast-flycast` (a clone/branch), following its deploy discipline below.

## TEST / DEPLOY (from `maplecast-flycast/docs/DEPLOYMENT.md`)

- **rise3 = OVH Rise build box** `ubuntu@15.204.141.58` (key `~/.ssh/ovh_maplecast`). Prod = `149.28.44.118`.
- **Git-first, always:** edit local → `git commit` → `deploy/scripts/deploy-web.sh <HOST>` /
  `deploy-headless.sh <HOST>` (they back up + confirm). **Never raw scp to prod.** If prod was edited
  directly, `scp` it back to git and commit BEFORE changing anything.
- **Isolation:** never disturb the live `maplecast-headless.service` or prod data. Isolated instances only.
- Recurring bites: nginx globs `*.bak` in sites-enabled (keep backups elsewhere); `client_max_body_size`
  default 1 MB; systemd capability-stripping; `/dev/shm` 64→256 MB; version-gate savestates/tapes by build_id.

## GUARDRAILS (best practices — the anti-drift contract)

1. Don't rebuild what's solved. Adapter, not renderer.
2. Read the authority docs + ask the RE/sprite experts before deriving anything.
3. Git-first; deploy scripts only; never raw scp to prod.
4. Keep the 4 wire parsers in lockstep; version-gate by `build_id`.
5. One handoff doc stays current — update + commit every session.

## PARKED (deliberately not doing)

- From-scratch Artifact/canvas box-renderer (`scratchpad/proof/replay_template.html`) — superseded by
  the sprite-client path.
- Agent upload `base64(gz)` → raw `Content-Type: application/gzip` (−33% wire) — nice-to-have; nginx fix
  already unblocked uploads. Both-sides change, backwards-compat design noted; do later.

## BACKGROUND (running, legitimate)

- **flycast through-combat proof** (Path 2, pixel-perfect via flycast NAOMI) — determinism gate; if it
  passes we ALSO get a pixel-perfect path. Uses NAOMI ROM `Downloads/mvsc2-naomi.zip` + unlocked IC22
  `Downloads/MvC2_Unlocked IC22 (1).Bin`. Separate from the canvas track.
- **sprite-render expert** — wiring the test canvas (task 1 above).
