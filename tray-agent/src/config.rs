// Central constants for the MetaSync tray agent. Kept in one place so the endpoints/version match the
// shipped app and the separate web app.

/// Base of the skinsync REST API (leaderboard, presence, results, defaults, …). Same origin the Tauri app
/// used as `SKINSYNC`.
pub const SERVER_BASE: &str = "https://nobd.net/skinsync";

/// Signed self-update manifest (minisign). The tray agent's OWN manifest (flat form: {version,url,signature}),
/// SEPARATE from the Tauri app's nested latest.json — its `url` must point at a metasync-agent binary, never
/// the Tauri installer. PER-PLATFORM: a Linux binary + .sig can't be served from the Windows manifest, so each
/// OS points at its own manifest (whose `url` is the matching-platform agent binary on the GitHub release).
#[cfg(windows)]
pub const UPDATE_MANIFEST: &str = "https://nobd.net/skinsync/update/agent-latest.json";
#[cfg(not(windows))]
pub const UPDATE_MANIFEST: &str = "https://nobd.net/skinsync/update/agent-latest-linux.json";

/// The web app the tray "Open MetaSync" item launches in the default browser (the replacement for the
/// old in-app webview).
pub const WEB_APP: &str = "https://nobd.net/app";

/// This crate's version (from Cargo.toml) — reported to the updater and shown in the tray status line.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Registry value name under HKCU\...\Run for the autostart entry.
pub const AUTOSTART_KEY: &str = "MetaSyncAgent";
