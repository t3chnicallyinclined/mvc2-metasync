// Windows "Start with Windows" helper — writes the current exe path to the per-user Run key so the agent
// launches at login. Per-user (HKCU) needs no elevation. Value name = config::AUTOSTART_KEY.
//
//   HKCU\Software\Microsoft\Windows\CurrentVersion\Run\MetaSyncAgent = "<full path to this exe>"
//
// The whole module is Windows-only; on any other target the three fns are inert stubs so the crate still
// type-checks (the agent only ships on Windows anyway).

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

#[cfg(not(windows))]
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
