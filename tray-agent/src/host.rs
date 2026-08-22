// "Host lobbies (this machine)" — turns this box into an arcade/tournament HOST node.
//
// LINUX-ONLY. The whole host runtime (mint/cache a token, create + rotate lobbies via ydotool, heartbeat,
// self-heal) lives in an EXTERNAL shell daemon — `arcade_hostd.sh`, bundled by the installer to
// `$HOME/.local/share/retro-receipts/arcade-host/` — managed as a systemd --user service. This module does
// NOT reimplement any of that: it only SHELLS OUT to that script.
//
//   • ENABLE : `bash <dir>/arcade_hostd.sh register`   → enables + starts the --user service.
//   • DISABLE: `bash <dir>/arcade_hostd.sh unregister` → unregisters from the pool + disables the service.
//   • STATUS : `bash <dir>/arcade_hostd.sh status`     → prints enabled/active (+ lobby json); parsed loosely.
//
// where <dir> = $HOME/.local/share/retro-receipts/arcade-host (see `host_dir()` — the single source of truth
// for the path, kept in one place so a future relocation is a one-line change).
//
// The script is a SEPARATE packaging task. If it's absent, `host_enable()` refuses (never claims success) so
// the tray can tell the user "host scripts not installed" and revert the toggle. On Windows every entry point
// is a no-op returning "Linux only (Windows soon)" — auto-hosting isn't supported there yet.
//
// register/unregister can be slow (systemctl + ydotool), so they run on a spawned thread — the same pattern
// the reader uses for its heartbeat POST — and never block the tray's event-loop thread. `status` is a quick
// one-shot and is called synchronously at startup (like autostart::is_enabled()).

use std::sync::atomic::AtomicBool;

/// Whether this machine is currently a host. Set at startup from `host_status()` (the live service is
/// authoritative) and toggled by the tray. When true the tray shows the "don't play on this machine" banner.
pub static HOST_MODE: AtomicBool = AtomicBool::new(false);

/// A loosely-parsed snapshot of the host daemon's state, for the tray's startup reconciliation.
#[allow(dead_code)] // some fields are used only for logging / future UI; kept for a complete picture.
pub struct HostStatus {
    /// Auto-hosting is possible on this OS at all (Linux only for now).
    pub supported: bool,
    /// The `arcade_hostd.sh` script is present at $HOME (its packaging is a separate task).
    pub installed: bool,
    /// The service is reported enabled/active by `status`.
    pub active: bool,
    /// The raw (trimmed) status text or the error, for logging.
    pub detail: String,
}

/// The canonical install dir the installer bundles the host scripts into. Single source of truth for the
/// path — change it here if packaging moves. `$HOME/.local/share/retro-receipts/arcade-host`.
#[cfg(target_os = "linux")]
fn host_dir() -> Option<std::path::PathBuf> {
    std::env::var_os("HOME")
        .map(|h| std::path::PathBuf::from(h).join(".local/share/retro-receipts/arcade-host"))
}

/// Full path to the host daemon script inside `host_dir()`.
#[cfg(target_os = "linux")]
fn script_path() -> Option<std::path::PathBuf> {
    host_dir().map(|d| d.join("arcade_hostd.sh"))
}

/// Run `bash $HOME/arcade_hostd.sh <arg>` and return its combined stdout+stderr. Synchronous; callers that
/// can't block (the tray event loop) invoke this from a spawned thread.
#[cfg(target_os = "linux")]
fn run_hostd(arg: &str) -> Result<String, String> {
    let script = script_path().ok_or_else(|| "no HOME dir".to_string())?;
    let out = std::process::Command::new("bash")
        .arg(&script)
        .arg(arg)
        .output()
        .map_err(|e| format!("failed to run {}: {e}", script.display()))?;
    let mut s = String::from_utf8_lossy(&out.stdout).into_owned();
    let err = String::from_utf8_lossy(&out.stderr);
    if !err.trim().is_empty() {
        s.push('\n');
        s.push_str(&err);
    }
    Ok(s)
}

/// Enable hosting: kick off `arcade_hostd.sh register` on a background thread. Returns synchronously so the
/// tray gets an immediate, HONEST answer:
///   • `Ok(())`  — supported + the script is installed; `register` was spawned.
///   • `Err(msg)` — not Linux, or the script isn't installed (the tray must NOT show ON in this case).
/// The actual service start happens off-thread; failures there are logged (the tray already reflects "on").
pub fn host_enable() -> Result<(), String> {
    #[cfg(target_os = "linux")]
    {
        let script = script_path().ok_or_else(|| "no HOME dir".to_string())?;
        if !script.exists() {
            return Err("host scripts not installed".into());
        }
        std::thread::spawn(move || match run_hostd("register") {
            Ok(out) => eprintln!("[host] register → {}", out.trim()),
            Err(e) => eprintln!("[host] register failed: {e}"),
        });
        Ok(())
    }
    #[cfg(not(target_os = "linux"))]
    {
        Err("Linux only (Windows soon)".into())
    }
}

/// Disable hosting: best-effort `arcade_hostd.sh unregister` on a background thread. No-op off Linux. The tray
/// always clears HOST_MODE for the OFF path regardless (unregistering a not-installed/never-registered host is
/// harmless), so this returns nothing.
pub fn host_disable() {
    #[cfg(target_os = "linux")]
    {
        // Nothing to unregister if the script was never installed.
        match script_path() {
            Some(p) if p.exists() => {
                std::thread::spawn(move || match run_hostd("unregister") {
                    Ok(out) => eprintln!("[host] unregister → {}", out.trim()),
                    Err(e) => eprintln!("[host] unregister failed: {e}"),
                });
            }
            _ => eprintln!("[host] unregister skipped — host scripts not installed"),
        }
    }
}

/// Query the daemon's state. Linux: returns `installed=false` when the script is absent; otherwise runs
/// `status` and parses it loosely — enabled/active/ok:true means hosting, guarding against systemd's
/// "inactive"/"disabled" (which contain "active"/"abled"). Non-Linux: `supported=false`.
pub fn host_status() -> HostStatus {
    #[cfg(target_os = "linux")]
    {
        let script = match script_path() {
            Some(p) => p,
            None => {
                return HostStatus {
                    supported: true,
                    installed: false,
                    active: false,
                    detail: "no HOME dir".into(),
                }
            }
        };
        if !script.exists() {
            return HostStatus {
                supported: true,
                installed: false,
                active: false,
                detail: "host scripts not installed".into(),
            };
        }
        match run_hostd("status") {
            Ok(out) => {
                let low = out.to_lowercase();
                let active = low.contains("ok:true")
                    || low.contains("\"ok\":true")
                    || low.contains("\"ok\": true")
                    || (low.contains("active") && !low.contains("inactive"))
                    || (low.contains("enabled") && !low.contains("disabled"));
                HostStatus {
                    supported: true,
                    installed: true,
                    active,
                    detail: out.trim().to_string(),
                }
            }
            Err(e) => HostStatus {
                supported: true,
                installed: true,
                active: false,
                detail: e,
            },
        }
    }
    #[cfg(not(target_os = "linux"))]
    {
        HostStatus {
            supported: false,
            installed: false,
            active: false,
            detail: "Linux only (Windows soon)".into(),
        }
    }
}
