# MetaSync — Beta Go-Live Readiness

_Status doc for the tester beta. Last updated this session._

MetaSync (`mvc-live-skins`) is a Tauri desktop app for the Steam MARVEL vs CAPCOM Fighting
Collection: live in-match skins + a consensus-verified match-tracking leaderboard. The beta ships
that player-facing product to testers; **data collection for the ML play-engine rides on top of it.**

---

## 1. Readiness at a glance

| Area | State | Blocking beta? |
|---|---|---|
| Live skins (per-side paint via the anchor) | Working (gs-76); **needs a live-match verify pass** | ⚠ verify |
| Match-tracking leaderboard / profiles | Working (consensus-verified) | No |
| Opponent identify + **your side (P1/P2)** | **Now solvable** — `localPlayerNum @ exe+0xac7230` (was flagged unrecoverable) | ⚠ wire in |
| Record button (dev feature) | **Removed** from tester UI this session | Done |
| Auto-updater / minisign signing | Working (key off-repo at `~/.mvc-updater`) | No |
| Data capture — **our** recorder | **Upgraded** (side/meter/combo added) | Done (dev) |
| Data capture — **in-app** (tester auto-collect) | Not built (button removed; needs background auto-capture) | ⚠ decision |
| Deterministic reconstruction (training twin) | **Downstream of beta** — dedicated agent closing it now | No (not beta-gating) |
| BYOR / privacy / consent | Rules exist; tester consent copy not written | ⚠ for data collection |

**Bottom line:** the *skins+leaderboard* product is close to tester-ready — the one hard gate is a
**live-match verification pass** of the anchor-based paint. Everything else blocking is small wiring
or a product decision, not new engineering.

---

## 2. The one real decision: how does the beta collect data?

Removing the Record button implies testers shouldn't *manually* record. Two models:

- **A — App auto-captures in the background** (no button): every tester match is captured + uploaded.
  Maximum data, but needs: background auto-capture in `sync.rs` (reuse the `capture_*` backend that's
  still there), an upload path to the skinsync server, storage, and **explicit tester consent** copy.
  Bigger lift; the right end-state.
- **B — We collect; testers just play** (beta ships skins only): data harvesting stays *our* activity
  via the upgraded `ranked_capture.py`. Zero added beta surface, ships fastest, but only our own
  matches feed the corpus during beta.

**Recommendation: ship beta on Model B, build Model A as the fast-follow.** It de-risks go-live
(skins is the tested product) and we still start collecting rich data now (our runs), while the
auto-capture + consent flow is built and tested before it touches testers.

---

## 3. Data we now collect (and what's still missing)

Per the Steam-expert audit, our recorder was a thin slice. **Added this session** (confirmed offsets):

- `human_side` (`localPlayerNum`) — which side is the human. **Solves per-player attribution.**
- `meter` (bars P1/P2 + fine-fill), `combo` (dealt/received per fighter), `color` per fighter.
- Schema is now: `[frame, p1_in, p2_in, hp[6], px[6], py[6], p1_meter, p2_meter, meter_fill, combo_dealt[6], combo_recv[6]]` + `human_side`, `color`.
- **Facing** is derived in post from `px` (`sign(px_p1 − px_p2)`) — no capture change needed; the true
  per-fighter facing byte is a P0 follow-up (one correlation pass on the 0x738 struct).

Still to add (each = one live read to confirm the 0x738 offset, then a one-line recorder edit):

1. **Real facing byte** (P0) — beats the position proxy for crossups/corner.
2. **Frame counter → fixed pointer anchor** (`game_struct = *(exe+0x2edf580)`, screen-state at `+3`) —
   replaces the per-game heuristic hunt that silently falls back to a fake index (corrupts alignment).
3. **Action label**: `sprite_id`/`anim` — the ground-truth action for behavior cloning.
4. **Combat state**: hitstun, hitstop, stance/in-air, velocity, red-health, `num_wins` round score.
5. **Char-select navigation**: cursor (col,row) trajectory + pick timing (a *new* behavior class;
   confirms the "portrait id ≠ char_id" point — char-select uses grid cells).

---

## 4. Go-live checklist (sequenced)

**Gate (must pass):**
- [ ] Live-match verify pass of gs-76 skins (no freeze; cards fill at match start; library skins hold).
- [ ] Wire `localPlayerNum` into side detection (replaces the persona-cache guess) + rebuild.
- [ ] Confirm record-button removal in a staged build (`stage-frontend.mjs` + bump `gs-77`).
- [ ] Tester onboarding: install/update flow, "what it does / reads game memory read-only" copy.

**Ship beta (Model B):**
- [ ] Package + sign the build; publish `latest.json` to the updater channel.
- [ ] Short tester guide (how to install, enable live sync, report issues).

**Fast-follow (Model A + data quality):**
- [ ] Background auto-capture in `sync.rs` + upload to skinsync + consent copy.
- [ ] Data upgrades #1–2 above (facing byte, frame-counter anchor) — the two that most improve corpus quality.
- [ ] Reconstruction loop lands (agent) → validates the corpus is trainable end-to-end.

---

## 5. Roadmap beyond beta

1. **Corpus growth**: Model A auto-capture across testers → volume; data upgrades #3–5 → richness.
2. **Reconstruction at scale**: the picker + headless flycast (being closed now) reconstructs any
   captured game from one char-select save → deterministic training frames + a fidelity oracle.
3. **Training**: `mvc2-ai` behavior-cloning on the richer corpus (facing + action labels are the
   biggest quality unlocks), then state-conditioned models, then self-play.
4. **DLL frame-hook** (foothold already in the game folder) → lossless one-sample-per-frame capture,
   replacing the poller.
