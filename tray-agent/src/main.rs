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

mod autostart;
mod tray;

use std::time::Duration;

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

    // Placeholder background worker. In T2 this becomes the memory-reader loop that uses `mem::Proc`
    // (open the game process, sig-scan, read palettes/lobby/match state, report to the server). For the
    // scaffold it just sleeps, with a light `find_game_pid` probe so the ported primitive is exercised.
    std::thread::Builder::new()
        .name("reader".into())
        .spawn(|| {
            loop {
                // TODO(T2): reader loop here.
                //   let pid = mem::find_game_pid()?;              // detect MvC2
                //   let proc = mem::Proc::open_rw(pid)?;          // mem::Proc — the ported Win32 primitive
                //   let base = mem::exe_base(pid);                // module base for exe-relative reads
                //   ... sig-scan + palette read/write + match detection (port of sync.rs in T2) ...
                let _game_running = mem::find_game_pid().is_some();
                std::thread::sleep(Duration::from_secs(5));
            }
        })
        .ok();

    // Run the tray event loop on the main thread. Diverges — returns only when the user picks Quit, which
    // exits the process (and with it the background threads).
    tray::run();
}
