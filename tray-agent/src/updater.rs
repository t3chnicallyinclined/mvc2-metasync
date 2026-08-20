// Self-updater — T1 SKELETON.
//
// What is real here: the manifest fetch + JSON parse + version compare (check_for_update), and the wiring of
// the three crates the real apply path needs (ureq download, minisign-verify signature check, self-replace
// exe swap). What is stubbed for a later task: apply_update is written end-to-end but is NEVER called at
// startup yet (main only logs check_for_update), and safe_to_apply() is a placeholder that will later gate on
// "no game running". No auto-apply happens until that gate + real end-to-end testing land.
//
// Sync by design: this agent has no async runtime. ureq is blocking; updates run on a worker thread.

use crate::config;
use serde::Deserialize;
use std::io::Read;

// TODO(security): this is the SHIPPED MetaSync minisign PUBLIC key (also embedded in tauri.conf.json — it is
// public by nature; the matching PRIVATE key lives off-repo at ~/.mvc-updater and is never committed). It is a
// placeholder in the sense that apply_update() is not yet wired into a live update flow — verify against this
// before self-replace once T2 enables auto-apply. Format = the raw minisign pubkey line (the `RWR…` string).
const MINISIGN_PUBKEY: &str = "RWRo5jDUn+WO6ZTvJokalltgwzdBSQ+VdX7MRNZB7iI9rrQhPXH48FL1";

/// A newer release the manifest advertised. `sig_url` defaults to `<bin_url>.sig` when the manifest omits it,
/// matching the minisign convention the release pipeline uses.
#[derive(Debug, Clone)]
pub struct Update {
    pub version: String,
    pub bin_url: String,
    pub sig_url: String,
    pub notes: Option<String>,
}

/// Shape of latest.json. Extra fields are ignored so the manifest can evolve. `platforms` mirrors the Tauri
/// updater manifest layout loosely; we also accept a flat `url`/`version` form. Only what we read is declared.
#[derive(Debug, Deserialize)]
struct Manifest {
    version: String,
    #[serde(default)]
    notes: Option<String>,
    /// Flat form: a direct download URL for this platform's binary.
    #[serde(default)]
    url: Option<String>,
    /// Optional explicit signature URL/string. When absent we derive `<url>.sig`.
    #[serde(default)]
    signature: Option<String>,
}

#[derive(Debug)]
pub enum UpdateError {
    Http(String),
    Parse(String),
    Verify(String),
    Io(String),
    NotSafe,
    NoAsset,
}

impl std::fmt::Display for UpdateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            UpdateError::Http(e) => write!(f, "http error: {e}"),
            UpdateError::Parse(e) => write!(f, "manifest parse error: {e}"),
            UpdateError::Verify(e) => write!(f, "signature verify failed: {e}"),
            UpdateError::Io(e) => write!(f, "io error: {e}"),
            UpdateError::NotSafe => write!(f, "not safe to apply (game running)"),
            UpdateError::NoAsset => write!(f, "manifest had no downloadable asset"),
        }
    }
}
impl std::error::Error for UpdateError {}

/// Fetch latest.json and return Some(Update) iff the advertised version is strictly newer than `current`.
/// Network/parse failures return None (a failed update check must never break the tray).
pub fn check_for_update(current: &str) -> Option<Update> {
    let manifest = match fetch_manifest(config::UPDATE_MANIFEST) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("[updater] manifest fetch failed: {e}");
            return None;
        }
    };
    if !is_newer(&manifest.version, current) {
        return None;
    }
    let bin_url = manifest.url?; // no asset for this platform → nothing to offer
    let sig_url = manifest
        .signature
        .unwrap_or_else(|| format!("{bin_url}.sig"));
    Some(Update {
        version: manifest.version,
        bin_url,
        sig_url,
        notes: manifest.notes,
    })
}

fn fetch_manifest(url: &str) -> Result<Manifest, UpdateError> {
    ureq::get(url)
        .timeout(std::time::Duration::from_secs(8))
        .call()
        .map_err(|e| UpdateError::Http(e.to_string()))?
        .into_json::<Manifest>()
        .map_err(|e| UpdateError::Parse(e.to_string()))
}

/// Strict "remote > current" over dotted numeric versions (e.g. "0.2.6" > "0.2.5"). Missing segments read as
/// 0; a non-numeric segment stops the comparison conservatively (treated as equal there). No semver crate —
/// the release versions are plain `major.minor.patch`.
fn is_newer(remote: &str, current: &str) -> bool {
    let parse = |s: &str| -> Vec<u64> {
        s.trim_start_matches('v')
            .split('.')
            .map(|p| p.parse::<u64>().unwrap_or(0))
            .collect()
    };
    let (r, c) = (parse(remote), parse(current));
    let n = r.len().max(c.len());
    for i in 0..n {
        let rv = r.get(i).copied().unwrap_or(0);
        let cv = c.get(i).copied().unwrap_or(0);
        if rv != cv {
            return rv > cv;
        }
    }
    false
}

/// GATE for auto-applying an update. TODO(T2): return false while MvC2 is running so we never swap the exe
/// mid-match — will be `mem::find_game_pid().is_none()` once the reader loop owns process detection. For the
/// T1 skeleton there is no auto-apply path calling this, so it is safe to return true.
pub fn safe_to_apply() -> bool {
    // Never swap the running exe while MvC2 is up — an update mid-match would kill the reader/painter. The
    // reader owns process detection; when the game is closed it's safe to self-replace + restart.
    crate::mem::find_game_pid().is_none()
}

/// Relaunch the just-updated exe and exit THIS (still-old-code) process. `self_replace` swapped the file on
/// disk, but the running image is still the old binary — only a fresh launch runs the new code. The `--updated`
/// arg tells the new process to wait briefly for us to exit + release the single-instance mutex before it claims it.
pub fn restart() -> ! {
    if let Ok(exe) = std::env::current_exe() {
        let _ = std::process::Command::new(exe).arg("--updated").spawn();
    }
    std::process::exit(0);
}

/// Full apply path — download the signed binary + its .sig, verify with minisign against MINISIGN_PUBKEY,
/// then swap the running exe via self-replace. Written end-to-end so every crate compiles and the flow is
/// real, but NOT invoked at startup in T1 (main only logs the check result). Returns Err on any failure so a
/// caller can surface it without ever leaving a half-swapped binary (self-replace is atomic on Windows).
pub fn apply_update(update: &Update) -> Result<(), UpdateError> {
    if !safe_to_apply() {
        return Err(UpdateError::NotSafe);
    }

    let bin = download_bytes(&update.bin_url)?;
    let sig_str = download_string(&update.sig_url)?;
    verify_signature(&bin, &sig_str)?;

    // Stage to a temp file next to nothing sensitive, then let self-replace atomically swap the live exe.
    let mut tmp = std::env::temp_dir();
    tmp.push(format!("metasync-agent-{}.new", update.version));
    std::fs::write(&tmp, &bin).map_err(|e| UpdateError::Io(e.to_string()))?;
    self_replace::self_replace(&tmp).map_err(|e| UpdateError::Io(e.to_string()))?;
    let _ = std::fs::remove_file(&tmp); // best-effort cleanup; ignore if the OS still holds it
    Ok(())
}

fn download_bytes(url: &str) -> Result<Vec<u8>, UpdateError> {
    let resp = ureq::get(url)
        .timeout(std::time::Duration::from_secs(60))
        .call()
        .map_err(|e| UpdateError::Http(e.to_string()))?;
    let mut buf = Vec::new();
    resp.into_reader()
        .read_to_end(&mut buf)
        .map_err(|e| UpdateError::Io(e.to_string()))?;
    if buf.is_empty() {
        return Err(UpdateError::NoAsset);
    }
    Ok(buf)
}

fn download_string(url: &str) -> Result<String, UpdateError> {
    ureq::get(url)
        .timeout(std::time::Duration::from_secs(30))
        .call()
        .map_err(|e| UpdateError::Http(e.to_string()))?
        .into_string()
        .map_err(|e| UpdateError::Io(e.to_string()))
}

/// Minisign verification of `bin` against the embedded public key using the detached `.sig` contents.
/// ⚠ The `.sig` that `cargo tauri signer sign` writes is the minisign signature **base64-encoded** (Tauri's
/// convention — the whole `untrusted comment:…` file is one base64 blob). `minisign_verify::Signature::decode`
/// wants the RAW minisign text, so base64-decode first; fall back to the raw string when it's already
/// un-encoded, so either form verifies.
fn verify_signature(bin: &[u8], sig_str: &str) -> Result<(), UpdateError> {
    use base64::Engine;
    let pk = minisign_verify::PublicKey::from_base64(MINISIGN_PUBKEY)
        .map_err(|e| UpdateError::Verify(format!("bad pubkey: {e}")))?;
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(sig_str.trim())
        .ok()
        .and_then(|b| String::from_utf8(b).ok())
        .filter(|s| s.contains("untrusted comment"));
    let raw = decoded.as_deref().unwrap_or(sig_str);
    let sig = minisign_verify::Signature::decode(raw)
        .map_err(|e| UpdateError::Verify(format!("bad signature: {e}")))?;
    // allow_legacy = false: require modern (prehashed) minisign signatures, matching the release pipeline.
    pk.verify(bin, &sig, false)
        .map_err(|e| UpdateError::Verify(e.to_string()))
}

/// Show a native popup with the update outcome so the user sees it immediately — not buried in the tray menu
/// text they'd have to re-open. Modal + top-most; returns when dismissed. No-op-to-stderr on non-Windows.
#[cfg(windows)]
pub fn notify(title: &str, msg: &str) {
    use windows::core::HSTRING;
    use windows::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, MB_ICONINFORMATION, MB_OK, MB_SETFOREGROUND, MB_TOPMOST,
    };
    unsafe {
        let _ = MessageBoxW(
            None,
            &HSTRING::from(msg),
            &HSTRING::from(title),
            MB_OK | MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND,
        );
    }
}
#[cfg(not(windows))]
pub fn notify(title: &str, msg: &str) {
    eprintln!("[notify] {title}: {msg}");
}
