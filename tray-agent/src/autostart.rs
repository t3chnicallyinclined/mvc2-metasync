// "Start at login" helper — registers the current exe to launch when the user logs in. Same three fns
// (`enable` / `disable` / `is_enabled`) on every platform; cfg-split bodies pick the OS mechanism:
//
//   • Windows: the per-user HKCU Run key (no elevation). Value name = config::AUTOSTART_KEY.
//       HKCU\Software\Microsoft\Windows\CurrentVersion\Run\MetaSyncAgent = "<full path to this exe>"
//   • Linux/Bazzite: an XDG autostart desktop entry read by GNOME/KDE/most DEs at login.
//       ~/.config/autostart/metasync-agent.desktop  (Exec=<full path to this exe>)
//
// On any other target the three fns are inert stubs so the crate still type-checks.

// Only the Windows Run-key impl uses the registry value name; gated so Linux doesn't see an unused import.
#[cfg(windows)]
use crate::config::AUTOSTART_KEY;

#[cfg(windows)]
mod imp {
    use super::AUTOSTART_KEY;
    use winreg::enums::{HKEY_CURRENT_USER, KEY_READ, KEY_WRITE};
    use winreg::RegKey;

    const RUN_PATH: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";

    /// Full, quoted-safe path to the running executable. winreg quotes nothing for us, but Run entries with
    /// spaces are fine unquoted since the value is a single program path (no args).
    fn exe_path() -> std::io::Result<String> {
        let p = std::env::current_exe()?;
        Ok(p.to_string_lossy().into_owned())
    }

    /// true iff the Run value exists AND still points at *this* exe (a stale path from a moved install reads
    /// as "not enabled" so the tray checkbox reflects reality and re-enabling rewrites the correct path).
    pub fn is_enabled() -> bool {
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        let run = match hkcu.open_subkey_with_flags(RUN_PATH, KEY_READ) {
            Ok(k) => k,
            Err(_) => return false,
        };
        let stored: String = match run.get_value(AUTOSTART_KEY) {
            Ok(v) => v,
            Err(_) => return false,
        };
        match exe_path() {
            Ok(cur) => stored.eq_ignore_ascii_case(&cur),
            Err(_) => !stored.is_empty(),
        }
    }

    /// Create/overwrite the Run value with the current exe path.
    pub fn enable() -> std::io::Result<()> {
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        // create_subkey opens-or-creates; Run always exists on Windows but be defensive.
        let (run, _) = hkcu.create_subkey_with_flags(RUN_PATH, KEY_WRITE)?;
        run.set_value(AUTOSTART_KEY, &exe_path()?)
    }

    /// Remove the Run value (ignore "not found" so calling disable when already off is a no-op).
    pub fn disable() -> std::io::Result<()> {
        let hkcu = RegKey::predef(HKEY_CURRENT_USER);
        let run = match hkcu.open_subkey_with_flags(RUN_PATH, KEY_WRITE) {
            Ok(k) => k,
            Err(_) => return Ok(()),
        };
        match run.delete_value(AUTOSTART_KEY) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e),
        }
    }
}

#[cfg(unix)]
mod imp {
    use std::io::Write;

    // XDG autostart: GNOME/KDE/XFCE/most DEs launch every *.desktop in ~/.config/autostart at login.
    const DESKTOP_FILE: &str = "metasync-agent.desktop";

    /// ~/.config (honoring XDG_CONFIG_HOME), the standard root for the autostart dir.
    fn config_home() -> std::path::PathBuf {
        std::env::var_os("XDG_CONFIG_HOME")
            .map(std::path::PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| std::path::PathBuf::from(h).join(".config")))
            .unwrap_or_else(std::env::temp_dir)
    }

    fn autostart_dir() -> std::path::PathBuf {
        config_home().join("autostart")
    }

    fn desktop_path() -> std::path::PathBuf {
        autostart_dir().join(DESKTOP_FILE)
    }

    /// Full path to the running executable (used as the desktop entry's Exec).
    fn exe_path() -> std::io::Result<String> {
        let p = std::env::current_exe()?;
        Ok(p.to_string_lossy().into_owned())
    }

    /// true iff the autostart entry exists AND its Exec line still points at THIS exe (a stale path from a
    /// moved install reads as "not enabled" so the tray checkbox reflects reality and re-enabling rewrites the
    /// correct path — same semantics as the Windows Run-key check).
    pub fn is_enabled() -> bool {
        let contents = match std::fs::read_to_string(desktop_path()) {
            Ok(c) => c,
            Err(_) => return false,
        };
        match exe_path() {
            Ok(cur) => contents
                .lines()
                .filter_map(|l| l.trim().strip_prefix("Exec="))
                .any(|e| e.trim() == cur),
            // current_exe() failed → fall back to "the entry exists and is non-empty".
            Err(_) => !contents.trim().is_empty(),
        }
    }

    /// Create/overwrite the autostart desktop entry pointing at the current exe.
    pub fn enable() -> std::io::Result<()> {
        let exe = exe_path()?;
        let dir = autostart_dir();
        std::fs::create_dir_all(&dir)?;
        // Minimal, spec-compliant entry. X-GNOME-Autostart-enabled + Hidden=false keep it enabled after a DE
        // toggles it; Terminal=false runs it silently (the agent has no console UI of its own).
        let entry = format!(
            "[Desktop Entry]\n\
             Type=Application\n\
             Name=MetaSync Agent\n\
             Comment=Reads MvC2 memory, applies skins, and reports matches\n\
             Exec={exe}\n\
             Terminal=false\n\
             X-GNOME-Autostart-enabled=true\n\
             Hidden=false\n"
        );
        let mut f = std::fs::File::create(dir.join(DESKTOP_FILE))?;
        f.write_all(entry.as_bytes())
    }

    /// Remove the autostart entry (ignore "not found" so disabling when already off is a no-op).
    pub fn disable() -> std::io::Result<()> {
        match std::fs::remove_file(desktop_path()) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e),
        }
    }
}

// Any non-Windows, non-Unix target (not a shipping target): inert stubs so the crate still type-checks.
#[cfg(not(any(windows, unix)))]
mod imp {
    pub fn is_enabled() -> bool {
        false
    }
    pub fn enable() -> std::io::Result<()> {
        Ok(())
    }
    pub fn disable() -> std::io::Result<()> {
        Ok(())
    }
}

pub use imp::{disable, enable, is_enabled};
