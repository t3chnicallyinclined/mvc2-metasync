# MvC2 BC training-data wishlist (what to capture, what to skip)

From the game-ai-ml-expert, grounded in our actual fields + the anotak move tables + the DC reconstruction.
Goal = clone a NAMED player's style from their own match tapes.

## The 3 structural levers (biggest impact)

1. **Egocentric canonicalization (do first, free).** Mirror every frame so *self always faces right* (negate
   x-pos/vel, swap L/R in the label per `facing`). Collapses P1/P2 + left/right → ~halves state space,
   doubles sample efficiency. This IS the "mirror-safe" decision.
2. **The move-table JOIN is the #1 lever.** Raw `sprite_id` is a bad direct feature (huge cardinality) — but
   joined to the anotak table it yields what humans act on: *this move is a launcher / unblockable / has 8
   recovery frames left / is +2 on block*. **RE effort goes to the JOIN KEY (sprite_id / move-id), not more
   raw fields.** ⟵ this is exactly the action-state we're hunting.
3. **Latency is NOT the constraint.** A GRU-256 / small transformer over 32 frames is sub-ms on CPU (1-3% of a
   16.7ms frame). Don't compromise features/history for speed — spend the budget on data quality + label balance.

## ★ RE-priority reframe (what to bother reversing on STEAM)

**Most fields we were going to grind are ALREADY in the DC struct → they come FREE from the DC reconstruction
(the exporter reads them), so we do NOT need to RE them all on Steam.** Focus live-Steam RE on:
1. **sprite_id / move-id (the move-table join key)** — HIGHEST ROI. [in progress]
2. Fields that must be read LIVE for capture, not reconstructed. Everything else (stance, anim_flags,
   anim_timer, undizzy, is_point, assist_onscreen, red_health, benched health, special_move_state phase) is
   [EXP] = already in the DC struct → take from reconstruction, don't re-RE on Steam.

## Feature list (tiers)

MUST: self+opp char_id (embed), health, pos_x (corner), pos_y/in_air, meter level (self+OPP), move-phase
(startup/active/recovery both sides), opp attack block-requirement (high/low/unblockable/throw, from join),
hitstun + hitstun-remaining, signed facing-relative distance, team rosters (3+3) + benched health, is_point,
self last-K inputs (strongest next-input predictor). 
HIGH: velocities, red_health, undizzy, anim_group, cancelable-window (anim_flags 0x20), closing speed, both
corners, assist_type/onscreen/cooldown, combo length, frame-advantage estimate.
SKIP (cosmetic/redundant): hit_flash, char_pal_effect, color, scales, screen/camera coords, stage_id,
z-depth, and — critically — the OPPONENT'S raw inputs (a human reads animation not the pad; feeding opp
inputs makes it precognitive/un-human).

## Derived features (compute from raw — best quality/effort)

opp-recovering + recovery-frames-remaining (punish trigger) · opp-hitstun-remaining (hit-confirm window) ·
frame-advantage = my_recovery_remaining − opp_(hitstun|blockstun)_remaining · my-cancelable-window ·
opp block-requirement · signed distance + closing speed + corners + cross-up · frames-since last hit/block/whiff.

## Action label (what the policy predicts)

9-way direction (canonical) + 6 independent binary button heads (LP/HP/LK/HK/A1/A2), predicted per frame,
run every frame. Motion inputs (QCF/DP) emerge for free from temporal context (GRU) — so use a factored
per-frame bitmask, NOT a combo-class softmax. **Weight loss toward DECISION frames** (input changes / event
edges) — a raw corpus is ~99.5% idle; this is the real trap. Keep (state_t, action_t) so the human's ~12f
reaction lag is baked in; optionally feed state_{t−δ} to keep reactions human-plausible.

## Phased build

P0: canonicalize + decision-frame weighting on CURRENT live fields (pos/health/meter/combo/assist/inputs) +
    a GRU → should beat the MLP baseline, validates the pipeline.
P1: land sprite_id → the move-table join → frame-data derived features. Biggest "looks like a real player" jump.
P2: team/assist + resource economy (rosters, benched hp, assist state, opp meter). 1v1 clone → MvC2 clone.
P3: style embedding + GRU/transformer over ~32f (one net imitates multiple named players).

## The single biggest thing to test first
Does the move-table join fire correctly on a LIVE frame — map captured move-id → anotak record per char →
read back correct phase/frame-data. Validate on ONE rollback-free (Fightcade/offline) reconstructed match
before more RE. Keep the corpus rollback-free (netplay polling captures predicted-during-rollback inputs).
