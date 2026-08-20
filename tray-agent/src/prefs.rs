// Persisted user preferences — a tiny JSON object in `runtime_dir()/prefs.json`.
//
// Keys:
//   • `apply_skins` (bool, default true) — the "Apply my skins" toggle (gates painter::SKINS_ENABLED).
//   • `autostart_initialized` (bool, default false) — set once, the first time the agent runs, when we
//     register "Start with Windows" by DEFAULT. After that the user's tray toggle owns the Run key; we never
//     re-enable it behind their back.
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

/// First-run gate for default-on autostart. Returns `true` exactly ONCE (the first launch), marking it done
/// and persisting so subsequent launches leave the Run key to the user's choice.
pub fn take_first_run() -> bool {
    let mut m = load_obj();
    if m.get("autostart_initialized").and_then(|x| x.as_bool()).unwrap_or(false) {
        false
    } else {
        m.insert("autostart_initialized".into(), true.into());
        save_obj(&m);
        true
    }
}
