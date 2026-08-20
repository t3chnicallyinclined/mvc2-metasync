// MetaSync tray agent — headless Windows companion (no window; tray icon only).
//
// Replaces the heavy Tauri webview: the UI moves to the web app (nobd.net/app) and this tiny native agent
// does the local work — read MvC2's memory, apply skins, report matches. T1 is the scaffold: a working tray
// + the proven memory primitive (mem.rs, ported verbatim) + a self-updater skeleton. The heavy game-reading
// logic lands in T2.
#![windows_subsystem = "windows"] // no console window

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

mod autostart;
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
    // One-shot update check on startup: log the result, DO NOT auto-apply yet (T2 gates apply on safe_to_apply
    // + real end-to-end testing). Runs on its own thread so a slow/absent network never delays the tray.
    std::thread::Builder::new()
        .name("updater-check".into())
        .spawn(|| match updater::check_for_update(config::VERSION) {
            Some(u) => eprintln!(
                "[updater] update available: {} (current {}) → {}",
                u.version, config::VERSION, u.bin_url
            ),
            None => eprintln!("[updater] up to date (v{})", config::VERSION),
        })
        .ok();

    // The real reader (T2), ported verbatim from the Tauri app's start_reader. Spawns its own threads:
    //   • the main detect/read/score/report loop (game detection → fighter-array read → per-set scoring →
    //     POST /result, plus the tray-driven presence heartbeat + live-match broadcast),
    //   • the fast per-frame gamestate-capture thread (~3ms, frame-dedup'd), and
    //   • the gamestate uploader (drains the spool between matches).
    // It also updates reader::AgentStatus, which the tray reads for its live status line. Returns immediately.
    reader::start_reader();

    // Run the tray event loop on the main thread. Diverges — returns only when the user picks Quit, which
    // exits the process (and with it the background threads).
    tray::run();
}
