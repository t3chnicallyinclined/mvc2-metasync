# MetaSync

A Windows companion app for **Marvel vs Capcom 2** on the Steam *MARVEL vs CAPCOM Fighting Collection*.

MetaSync reads the game's memory locally to give you:

- **Live skins** — recolor any character with custom 16-colour palettes that apply live, per side, even in same-character mirrors. Save, bake, or apply on the fly.
- **A live match overlay** — your team, the opponent, the side you're on, and the running set score, detected automatically from the match.
- **Leaderboards & matchup intel** *(with Live Sync on)* — ELO ranks, win/streak/OCV/perfect/comeback/combo boards, per-opponent head-to-head history, and your win chance vs the player across the table.

MetaSync is a **companion app** — it never modifies game files on disk. Skins are applied to the running game's palettes in memory and disappear when you close it.

## Bring Your Own ROM (BYOR)

MetaSync ships **no game data** — no ROMs, no sprites, no palettes extracted from the game. It reads everything it needs from your own legally-owned copy at runtime. Nothing in this repository is derived from the game.

## Live Sync & offline mode

MetaSync works **offline** for its local features (skins + overlay). Turning on **Live Sync** connects you to the MetaSync network for leaderboards, player sync, and stats — and syncs your match data (associated with your Steam ID) to power them. You choose: the first time you go live you're asked to agree once, and you can drop back to offline at any time. See [docs/TERMS-AND-PRIVACY.md](docs/TERMS-AND-PRIVACY.md).

## Architecture

- **Frontend** (`web/`) — vanilla-JS ES modules (no framework, no bundler). The library, live match view, skin editor, and leaderboards.
- **Backend** (`src-tauri/`) — a [Tauri v2](https://tauri.app) Rust shell. Reads the game's memory (read-only), applies palettes, and talks to the MetaSync server over HTTPS.
- **Render hook** (`hook/`) — an optional in-process palette hook that repaints skins at the render layer for rock-solid, flicker-free application.

The app talks to a MetaSync server only over HTTP(S). The server is a separate service; its endpoints are documented in [SERVER.md](SERVER.md) so you can point the client at your own if you want to self-host.

## Building

Prerequisites: [Rust](https://rustup.rs) (stable, MSVC toolchain), the Tauri v2 prerequisites for Windows (WebView2 ships with Windows 11), and the Visual Studio Build Tools C++ workload.

```sh
cd src-tauri
cargo tauri dev      # run locally
cargo tauri build    # produce an installer under src-tauri/target/release/bundle/
```

The frontend is static — there's no npm build step for `web/`.

## License

MIT — see [LICENSE](LICENSE).
