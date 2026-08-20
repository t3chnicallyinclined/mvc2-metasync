// Persisted user preferences — a tiny JSON file under runtime_dir(): `prefs.json`.
//
// Currently one key: `apply_skins` (bool) — the tray's "Apply my skins" toggle, which gates the painter
// (painter::SKINS_ENABLED). Persisted so the choice survives restarts. Session-only prefs (e.g. "Pause
// reporting") are deliberately NOT stored here — they reset every launch by design.
//
// Shape: { "apply_skins": true }
//
// All reads default safely (absent / blank / malformed file → the default), and the write is best-effort
// (a failed write just means the choice isn't remembered next run — never fatal).

fn prefs_path() -> std::path::PathBuf {
    crate::runtime_dir().join("prefs.json")
}

/// Load the persisted "Apply my skins" preference. Defaults to `true` (paint) when the file is missing,
/// blank, malformed, or the key is absent.
pub fn load_apply_skins() -> bool {
    let raw = std::fs::read_to_string(prefs_path()).unwrap_or_default();
    serde_json::from_str::<serde_json::Value>(&raw)
        .ok()
        .and_then(|v| v.get("apply_skins").and_then(|x| x.as_bool()))
        .unwrap_or(true)
}

/// Persist the "Apply my skins" preference. Best-effort — a failed write is ignored.
pub fn save_apply_skins(on: bool) {
    let _ = std::fs::write(
        prefs_path(),
        serde_json::json!({ "apply_skins": on }).to_string(),
    );
}
