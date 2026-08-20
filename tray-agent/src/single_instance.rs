// Single-instance guard — ensure exactly ONE MetaSync agent runs per machine.
//
// Two agents reading the same MvC2 process would each detect + report the same set, double-counting matches
// (critical to avoid during the 0.3.0 "side-by-side" migration where an old and a new agent could briefly
// co-exist). `enforce_single_instance()` is the FIRST thing main() calls: if another instance already holds
// the lock, we log and `exit(0)` before spawning the reader / painter / tray.
//
// The lock is held for the WHOLE process lifetime and released by the OS on exit — so a crash never leaves a
// stale lock that blocks the next launch.
//   • Windows: a named kernel mutex (`Global\MetaSyncAgentSingleton`). CreateMutexW succeeds even when the
//     mutex already exists, but sets last-error to ERROR_ALREADY_EXISTS — the canonical single-instance probe.
//   • Linux/Unix: an advisory `flock(LOCK_EX | LOCK_NB)` on `runtime_dir()/agent.lock`. A second agent's
//     non-blocking lock fails with EWOULDBLOCK. The fd is kept open for the process lifetime.
// On any error creating the lock we FAIL OPEN (log + continue) — the guard must never keep the only legitimate
// instance from starting.

/// Exit the process immediately if another agent instance already holds the machine-wide lock. Otherwise
/// acquire it and hold it for the process lifetime. Call this first in `main()`.
#[cfg(windows)]
pub fn enforce_single_instance() {
    use windows::core::HSTRING;
    use windows::Win32::Foundation::{GetLastError, ERROR_ALREADY_EXISTS, FALSE, HANDLE};
    use windows::Win32::System::Threading::CreateMutexW;

    // `Global\` scopes the mutex across ALL sessions (RDP / fast-user-switching), so the guard is truly
    // machine-wide, not per-login-session.
    let name = HSTRING::from("Global\\MetaSyncAgentSingleton");
    unsafe {
        // NULL security attrs, not initially owned. On success `_mutex` is a valid handle whether or not the
        // mutex pre-existed; the pre-existence is reported ONLY via GetLastError below.
        let _mutex: HANDLE = match CreateMutexW(None, FALSE, &name) {
            Ok(h) => h,
            // Couldn't create the mutex at all (rare) — fail open so we never block the sole instance.
            Err(e) => {
                eprintln!("[single-instance] CreateMutexW failed: {e} — continuing without the guard.");
                return;
            }
        };
        // Read last-error IMMEDIATELY: the windows-crate wrapper does not touch it on the success path, so it
        // still reflects CreateMutexW's own ERROR_ALREADY_EXISTS when another instance created the mutex first.
        if GetLastError() == ERROR_ALREADY_EXISTS {
            eprintln!("[single-instance] another MetaSync agent is already running — exiting.");
            std::process::exit(0);
        }
        // `_mutex` is intentionally never closed: HANDLE is a Copy wrapper with no Drop, so letting it fall out
        // of scope leaves the OS handle open (leaked by design). The kernel holds the named mutex until this
        // process exits — exactly the process-lifetime hold single-instance requires.
    }
}

/// Linux/Unix: advisory flock on `runtime_dir()/agent.lock`, held for the process lifetime.
#[cfg(unix)]
pub fn enforce_single_instance() {
    use std::os::unix::io::AsRawFd;

    let dir = crate::runtime_dir();
    let _ = std::fs::create_dir_all(&dir); // runtime_dir() already tries this on Windows; be sure on Unix too
    let path = dir.join("agent.lock");

    let file = match std::fs::OpenOptions::new().create(true).write(true).truncate(false).open(&path) {
        Ok(f) => f,
        // Can't even open the lock file — fail open so we never block the sole instance.
        Err(e) => {
            eprintln!("[single-instance] cannot open lock file {}: {e} — continuing without the guard.", path.display());
            return;
        }
    };

    // Non-blocking exclusive lock. Held until the fd closes; the kernel releases it automatically on exit
    // (crash-safe — no stale lock file semantics to clean up, unlike a PID file).
    let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
    if rc != 0 {
        let err = std::io::Error::last_os_error();
        if err.raw_os_error() == Some(libc::EWOULDBLOCK) {
            eprintln!("[single-instance] another MetaSync agent holds {} — exiting.", path.display());
            std::process::exit(0);
        }
        // Some other flock error (e.g. EINTR/ENOLCK) — fail open rather than block the only instance.
        eprintln!("[single-instance] flock failed on {}: {err} — continuing without the guard.", path.display());
        return;
    }

    // Keep the fd open for the whole process: std::fs::File closes on Drop (which would drop the lock), so we
    // deliberately leak it. The lock lives exactly as long as the process.
    std::mem::forget(file);
}

/// Fallback for any target that is neither Windows nor Unix (not a shipping target): no-op guard.
#[cfg(not(any(windows, unix)))]
pub fn enforce_single_instance() {}
