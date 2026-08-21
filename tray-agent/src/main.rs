// MetaSync tray agent — headless Windows companion (no window; tray icon only).
//
// Replaces the heavy Tauri webview: the UI moves to the web app (nobd.net/app) and this tiny native agent
// does the local work — read MvC2's memory, apply skins, report matches. T1 is the scaffold: a working tray
// + the proven memory primitive (mem.rs, ported verbatim) + a self-updater skeleton. The heavy game-reading
// logic lands in T2.
// `windows_subsystem = "windows"` (no console window) is a Windows-only attribute; cfg_attr keeps it inert
// on Linux/Bazzite where the agent is a normal process launched from the tray/DE.
#![cfg_attr(windows, windows_subsystem = "windows")] // no console window (Windows only)

// The validated RE memory primitive, copied byte-for-byte from src-tauri/src/mem.rs. In T1 only
// find_game_pid is exercised (the reader loop that consumes Proc/exe_base lands in T2) → allow unused so the
// scaffold builds clean WITHOUT editing mem.rs (this attribute on the mod decl covers the module's contents).
#[allow(unused)]
mod mem;

#[allow(dead_code)] // several constants (SERVER_BASE, …) are consumed in T2.
mod config;

#[allow(dead_code)] // apply_update / safe_to_apply are wired but not invoked until T2 enables auto-apply.
mod updater;

// The ported game-state reader + match reporting (T2). #[allow(dead_code)] because the verbatim RE port
// carries several helpers the app's webview commands used that the tray doesn't call (e.g. read_self_name,
// auth_get) — clippy nits on verbatim code are expected and intentionally left; see mem.rs for the same rule.
#[allow(dead_code)]
mod reader;

// The ported skin painter (T3): writes skin palettes into the game's render palette out-of-process via RPM,
// write-last-wins, driven by the reader's paint_slots + ram_base (verbatim paint RE from sync.rs; only the
// webview trigger is replaced with a reader-driven local-first apply). #[allow(dead_code)] for the same reason
// as reader — the verbatim port carries helpers the tray's single call path doesn't all exercise.
#[allow(dead_code)]
mod painter;

mod autostart;
// Persisted tray preferences (prefs.json) — currently just the "Apply my skins" toggle restored below.
mod prefs;
// Machine-wide single-instance guard (named mutex on Windows / flock on Unix). Called first in main().
mod single_instance;
mod tray;

// Runtime data dir. The reader's call sites (`crate::runtime_dir()`) stay byte-identical to sync.rs; only the
// returned PATH changes here. On WINDOWS we deliberately do NOT reuse the app's legacy `C:\g` — that path only
// mattered for the injected D3D-hook DLL (compiled to watch `C:\g\skins.dat`), which the tray never uses (it
// paints out-of-process via RPM). Instead everything lives under the standard per-user app-data root
// `%LOCALAPPDATA%\MetaSync\runtime`, next to `auth.json` + `gs-cache` (best practice; no stray top-level dir,
// no clash with a co-installed Tauri app, clean uninstall).
pub(crate) fn runtime_dir() -> std::path::PathBuf {
    #[cfg(windows)]
    {
        let base = std::env::var_os("LOCALAPPDATA")
            .map(std::path::PathBuf::from)
            .unwrap_or_else(std::env::temp_dir);
        let dir = base.join("MetaSync").join("runtime");
        let _ = std::fs::create_dir_all(&dir);
        dir
    }
    #[cfg(not(windows))]
    {
        let base = std::env::var_os("XDG_DATA_HOME")
            .map(std::path::PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| std::path::PathBuf::from(h).join(".local/share")))
            .unwrap_or_else(std::env::temp_dir);
        base.join("mvc-live-skins")
    }
}

fn main() {
    // If the self-updater relaunched us (`--updated`), give the OLD process a moment to exit and release the
    // machine-wide single-instance mutex before we claim it — else the guard sees it held and exits us.
    if std::env::args().any(|a| a == "--updated") {
        std::thread::sleep(std::time::Duration::from_millis(1500));
    }

    // FIRST: ensure only ONE agent runs machine-wide. If another instance already holds the lock, this logs
    // and exit(0)s here — before any reader/painter/tray starts — so two agents can't double-report matches.
    single_instance::enforce_single_instance();

    // Startup auto-update: on its own thread (a slow/absent network never delays the tray), and APPLY it when
    // it's safe — MvC2 NOT running, so the exe is never swapped mid-match. Short delay lets the tray come up
    // first; if the game is open we log + defer (the tray menu can also trigger it, and next launch retries).
    // apply_update verifies the minisign signature before the self-replace.
    std::thread::Builder::new()
        .name("updater-check".into())
        .spawn(|| {
            std::thread::sleep(std::time::Duration::from_secs(8));
            match updater::check_for_update(config::VERSION) {
                Some(u) if updater::safe_to_apply() => {
                    eprintln!("[updater] applying {} (current {})", u.version, config::VERSION);
                    match updater::apply_update(&u) {
                        Ok(()) => {
                            updater::notify("MetaSync", &format!("Updated to v{} — restarting.", u.version));
                            updater::restart()
                        }
                        Err(e) => {
                            eprintln!("[updater] apply failed: {e}");
                            updater::notify("MetaSync Update", &format!("Update failed:\n\n{e}"));
                        }
                    }
                }
                Some(u) => eprintln!("[updater] {} available but MvC2 running — deferring", u.version),
                None => eprintln!("[updater] up to date (v{})", config::VERSION),
            }
        })
        .ok();

    // The real reader (T2), ported verbatim from the Tauri app's start_reader. Spawns its own threads:
    //   • the main detect/read/score/report loop (game detection → fighter-array read → per-set scoring →
    //     POST /result, plus the tray-driven presence heartbeat + live-match broadcast),
    //   • the fast per-frame gamestate-capture thread (~3ms, frame-dedup'd), and
    //   • the gamestate uploader (drains the spool between matches).
    // It also updates reader::AgentStatus, which the tray reads for its live status line. Returns immediately.
    reader::start_reader();

    // Restore the persisted "Apply my skins" preference (default ON) into the painter's gate BEFORE the painter
    // starts, so a user who turned skins off stays off across restarts without a first paint slipping through.
    painter::SKINS_ENABLED.store(prefs::load_apply_skins(), std::sync::atomic::Ordering::Relaxed);

    // "Start with Windows" is ON by DEFAULT: until the user makes an explicit choice in the tray, every launch
    // re-asserts the Run-key autostart (which also self-heals a stale path after a move/reinstall/auto-update).
    // Once they've toggled it, honor that choice forever — an explicit OFF is never re-enabled behind their back.
    match prefs::autostart_choice() {
        None => {
            let _ = autostart::enable();
        }
        Some(true) => {
            let _ = autostart::enable();
        } // keep it fresh (repairs a stale path)
        Some(false) => {} // user opted out — leave it disabled
    }

    // The skin painter (T3), ported verbatim from the app's paint_live / paint_signatures. Spawns one sibling
    // thread that reads the reader's PaintView (paint_slots + ram_base + side + state) each tick and auto-applies
    // the user's LOCAL skins (runtime_dir()/skins.json) via RPM — per-side paint_live + the array-free base layer.
    // Local-first: no webview, no phone yet (the live "change a skin from your phone" push is T5). Returns immediately.
    painter::start_painter();

    // Phase 3: poll our web-set loadout (the /app skin picker) in the background and mirror it into the
    // painter's in-memory store — a skin picked on the web applies on the next match with no local files.
    painter::start_loadout_sync();
    // Phase 3 live push: subscribe to our private cmd.<steamid> SSE channel so a web skin change applies
    // INSTANTLY (the poll above is the reconciling fallback).
    reader::start_cmd_subscribe();

    // Run the tray event loop on the main thread. Diverges — returns only when the user picks Quit, which
    // exits the process (and with it the background threads).
    tray::run();
}
