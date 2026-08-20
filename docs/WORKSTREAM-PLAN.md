# MetaSync — Tauri → (tray agent + PWA) cutover: full workstream plan to release

Master plan to take the rewrite to completion/release/test. Written 2026-08-19. Owners: **PWA/tray = this
session**; **server/injector/RE = the nobd-arcade owner** (see memory `mvc-arcade-tray-contracts`). 0.2.5
(game-modes + wagers/arcade) shipped on the Tauri app; this plan retires it.

## Definition of done
The Tauri desktop app is fully replaced by **PWA (nobd.net/app) + tiny tray agent**, released with
auto-update, and proven end-to-end: a hosted arcade match runs, a wager settles, skins apply, matches report
— all with no webview.

## Lanes, tasks, status (⬜ todo · 🔄 in progress · ✅ done · ⛔ gated)

### Lane P — PWA (this session, `metasync-rewrite/app`, ONE sequential lane — shared worktree)
| # | Task | Status | Blocks/needs |
|---|---|---|---|
| P0 | Read/social app (ranks, match, tournament, regions, library, profiles, auth, actions, settings) | ✅ live | — |
| P1 | **Wager/marquee UI** (balance, MARQUEE, rail, quarter-up, staked-tourney badges) | ✅ live `4a7fd7f` | — |
| P2 | Scope switcher (Ranked/Lobby/Tournament boards) + Season Zero line | ✅ live `949cd5a` | — |
| P3 | **Skin picker / loadout UI** (per-char selection, optimistic) | ⛔ | needs S3 (skin-apply endpoint + agent) |
| P4 | Polish: notification prefs, a11y, bracket render w/ real data | ⬜ | — |

> **Lane P is at full parity with Tauri 0.2.5 and beyond** — only P3 remains, gated on S3.

### Lane T — Tray agent (this session, NEW worktree `mvc-live-skins-tray`, RUNS PARALLEL to Lane P)
| # | Task | Status | Blocks/needs |
|---|---|---|---|
| T1 | **Scaffold**: crate + `mem.rs` verbatim + tray shell + self-updater skeleton | ✅ `1c47500` (compiles, tray runs) | — |
| T2 | **Memory-reader port** (verbatim reader half of `sync.rs`: cadence, gamestate, `/result` `/heartbeat` `/match/live`, Steam identity + `/register`) | ✅ `8c13fb8` (compiles; **needs live-game test**) | — |
| T2b | Data-path fix: `runtime_dir` `C:\g` → `%LOCALAPPDATA%\MetaSync\runtime` | ✅ `82b9da7` | — |
| T2c | Hardening: memory-first ephemeral state, drop `records.json`, DPAPI token, single-instance guard | ⬜ | after the T2 live-game test |
| T3 | **Skin applier** (paint loop, write-last-wins, `paint_slots`) port | ⬜ next | (unblocked; do after T2 validated) |
| T4 | **Arcade host-driver**: `read_my_lobby` (⚠ **1GB region cap 0x4000_0000**) + drive injector via `nobd_arcade.cmd/result/ready` file protocol + host heartbeat | ⛔ | **injector proven live** (owner, S2) |
| T5 | **Command-channel client** (SSE `cmd.{steamid}` → apply skins live) | ⛔ | S4 gateway authz |
| **T6** | **Bazzite/Linux build** — cfg-gate autostart (Run-key→`.desktop`) + Linux tray deps (appindicator); build/test in the `tauri44` distrobox on the Beelink. The RE reader (`mem.rs`) already has a verbatim `cfg(unix)` backend. | ⬜ | — |
| **T7** | **Installers + migration** — standalone signed tray-agent installer (Win + Linux) added to `latest.json`; the Tauri `0.3.0` migration build (see below) | ⬜ | T3/T4 |

### Lane S — Server / injector / RE (nobd-arcade OWNER — coordinate, don't build)
| # | Task | Status |
|---|---|---|
| S1 | Wager economy + endpoints (coins/wager/marquee/staked-tourney/ledger) | ✅ live |
| S2 | **Injector menu-drive proof** (capture-replay cycle) — the gate for T4 | 🔄 owner |
| S3 | Skin-apply endpoint (`POST /skin/apply`) — the gate for P3 | ⬜ (define w/ owner) |
| S4 | Host registry (enroll/heartbeat/hosts + fee routing) + gateway `cmd.*` authz | 🔄/⬜ owner |

## Dependency graph
```mermaid
graph LR
  P1[P1 wager UI] --> P2[P2 scope switch] --> P4[P4 polish]
  T1[T1 scaffold] --> T2[T2 reader] --> T3[T3 skin apply]
  T2 --> T4[T4 host-driver]
  Sync([frozen sync.rs]) --> T2
  Inj([injector proven ·owner]) --> T4
  S4([gateway cmd authz ·owner]) --> T5[T5 cmd client]
  S3([skin/apply ·owner]) --> P3[P3 skin picker]
  T3 --> REL{{Release}}
  T4 --> REL
  P1 --> REL
  REL --> TEST{{E2E test}}
```

## What runs in parallel NOW (no shared-resource collision)
- **Lane P** (wager UI, agent running in `app/`) **‖** **Lane T1** (tray scaffold, agent in the separate
  `mvc-live-skins-tray` worktree). Different repos/worktrees → no dev-server/build collision.
- Sequential within Lane P (one `app/` worktree). Sequential within Lane T after T1 (one tray worktree).
- Lane S is the owner's; we consume + coordinate.

## Gates to unblock the rest (who clears them)
1. ✅ **Frozen `sync.rs` — RESOLVED:** the `v0.2.5` release tag = commit **`02f8883`** ("game modes +
   scoped leaderboards + arcade gs-218"); its `sync.rs` carries both the game-modes reader AND the arcade RE
   (`read_my_lobby` + 1GB cap). Tray worktree `mvc-live-skins-tray` [branch `tray-agent`] is based off it →
   **T2/T3/T4 code is unblocked** (T4's *live* test still waits on the injector, gate #2).
2. **Injector proven live** (owner, S2) → unblocks T4 end-to-end.
3. **`POST /skin/apply` + `cmd.*` gateway authz** (owner/server, S3/S4) → unblocks P3 + T5.

## Migration & distribution (Tauri → tray agent + PWA)
The app splits, so the two halves reach users differently:
- **PWA** = a URL (`nobd.net/app`) — nothing to push; live today, optional Add-to-Home-Screen.
- **Tray agent** = delivered once through the Tauri app's existing auto-updater, then self-updates forever.

**No data migration:** identity = SteamID, all data (rank/records/coins/wagers) is server-side. The agent
auto-registers on first run (`/register`) → instant full identity. Nothing to copy.

**Two-step, smooth:**
1. **`0.3.0` — SIDE-BY-SIDE (the migration hop).** The Tauri `0.3.0` auto-update installs `metasync-agent`
   (Win + Linux) + registers autostart, **disables the old app's own reader + autostart** (so the two never
   double-report), and shows a one-time notice ("MetaSync is now a tray app + nobd.net/app; it starts with
   Windows now"). The Tauri shell stays installed but **inert** — low-risk, reversible; the agent does the
   game bridge and the PWA is the UI.
2. **`0.3.x`/`0.4` — COME OFF IT.** Once the agent's proven in the field, a follow-up retires the inert
   Tauri shell (self-uninstall / cleanup), leaving just the tray agent + PWA.

**New users** download a standalone signed tray-agent installer from nobd (Win + Linux), in `latest.json`.

## Release + test
- **Tray build/sign/publish (T7):** build `--release` on **both** platforms (Windows here; **Linux in the
  `tauri44` distrobox on the Beelink `Tris@192.168.1.183`**, same as the Tauri app) → sign with the existing
  minisign key (`~/.mvc-updater/signing.key`) → add both platform entries to `latest.json` on nobd
  (`/opt/skinsync/update/`). Self-updater applies only when no game is running.
- **E2E test (multi-party), on Windows AND Bazzite/Proton:** injector capture-replay (owner) → tray T4 drives
  a hosted lobby → 2 players join via `steam://joinlobby/…` → a real match → wager settles (memory-read
  referee) → skin applies → result reports.
- **Cross-platform status:** ✅ **Windows built** (`metasync-agent.exe`, compiles + tray runs). ⬜
  **Bazzite/Linux NOT built yet** (T6) — the RE reader has a verbatim `cfg(unix)` backend, but the shell
  (autostart Run-key, tray deps) is Windows-only and needs the cfg-gate + a distrobox build.

## Coordination points (keep synced with the owner)
1. Injector `cmd/result/ready` file protocol — one driver (tray), one contract.
2. Host-registry + `cmd.*` gateway endpoints — owner defines, tray/PWA wire the client.
3. Reader offsets / 1GB region cap — shared; re-verify both sides if the game updates.
