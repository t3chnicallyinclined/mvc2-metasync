// Persisted user preferences — a tiny JSON object in `runtime_dir()/prefs.json`.
//
// Keys:
//   • `apply_skins` (bool, default true) — the "Apply my skins" toggle (gates painter::SKINS_ENABLED).
//   • `autostart_choice` (bool, ABSENT until the user picks) — the "Start with Windows" preference. While
//     ABSENT the default is ON: every launch re-asserts the Run key (also self-heals a stale path after a
//     move/reinstall). Once the user toggles it in the tray we record their choice here and honor it forever —
//     so an explicit OFF is never re-enabled behind their back, and an explicit ON is kept fresh.
//   • `autostart_initialized` (LEGACY, ignored) — a former first-run-only flag; superseded by `autostart_choice`.
// Session-only prefs (e.g. "Pause reporting") are deliberately NOT stored — they reset every launch by design.
//
// Reads default safely (absent / blank / malformed → the default); writes are best-effort. Every write does a
// read-modify-write on the whole object so setting one key never clobbers the others.

fn prefs_path() -> std::path::PathBuf {
    crate::runtime_dir().join("prefs.json")
}

fn load_obj() -> serde_json::Map<String, serde_json::Value> {
    std::fs::read_to_string(prefs_path())
        .ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

fn save_obj(m: &serde_json::Map<String, serde_json::Value>) {
    let _ = std::fs::write(prefs_path(), serde_json::Value::Object(m.clone()).to_string());
}

/// The "Apply my skins" preference. Defaults to `true` (paint) when missing/blank/malformed.
pub fn load_apply_skins() -> bool {
    load_obj().get("apply_skins").and_then(|x| x.as_bool()).unwrap_or(true)
}

/// Persist "Apply my skins" (preserves the other keys).
pub fn save_apply_skins(on: bool) {
    let mut m = load_obj();
    m.insert("apply_skins".into(), on.into());
    save_obj(&m);
}

/// The user's explicit "Start with Windows" choice, or `None` when they've never picked (→ default ON).
pub fn autostart_choice() -> Option<bool> {
    load_obj().get("autostart_choice").and_then(|x| x.as_bool())
}

/// Record the user's explicit "Start with Windows" choice (preserves the other keys). Once set, the launch
/// path honors it instead of the default.
pub fn save_autostart_choice(on: bool) {
    let mut m = load_obj();
    m.insert("autostart_choice".into(), on.into());
    save_obj(&m);
}
