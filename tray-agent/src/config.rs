// Central constants for the MetaSync tray agent. Kept in one place so the endpoints/version match the
// shipped app and the separate web app.

/// Base of the skinsync REST API (leaderboard, presence, results, defaults, …). Same origin the Tauri app
/// used as `SKINSYNC`.
pub const SERVER_BASE: &str = "https://nobd.net/skinsync";

/// Signed self-update manifest (minisign). Same endpoint the Tauri updater plugin points at.
pub const UPDATE_MANIFEST: &str = "https://nobd.net/skinsync/update/latest.json";

/// The web app the tray "Open MetaSync" item launches in the default browser (the replacement for the
/// old in-app webview).
pub const WEB_APP: &str = "https://nobd.net/app";

/// This crate's version (from Cargo.toml) — reported to the updater and shown in the tray status line.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Registry value name under HKCU\...\Run for the autostart entry.
pub const AUTOSTART_KEY: &str = "MetaSyncAgent";
