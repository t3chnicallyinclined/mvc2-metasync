// Game-state reader + match reporting — ported VERBATIM from src-tauri/src/sync.rs (frozen v0.2.5).
//
// This is T2: the reader that detects MvC2, reads its memory (fighter array + battle globals), scores the
// set, and reports matches to the skinsync server. The RE is byte-identical to the Tauri app — the offset
// table, the scene==5 pointer-follow anchor, the struct field reads, the adaptive cadence, and the frame
// dedup are all copied without change. ONLY the Tauri glue is different:
//   • the app published a `Snapshot` (Mutex) for the webview to poll + drove heartbeat / live-match from JS
//     (`#[tauri::command]`); here the reader owns those calls directly (direct HTTP) and ALSO publishes an
//     `AgentStatus` (see bottom of file) that tray.rs reads for its status line.
//   • the skin painter (paint_slots / paint_live), the arcade host-driver (read_my_lobby as a command / the
//     injector), and the ~89 webview command proxies are NOT ported (T3 / T4 / the PWA already does them).
//
// The internal `Snapshot` (produced by the reader thread, consumed by the gamestate-capture thread) is kept
// intact because the two threads coordinate through it (ram_base, side_confirmed). It is NOT the tray's view;
// the tray reads `AgentStatus`. Everything between the two ─── rulers is a faithful copy of sync.rs.
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};
// Cross-platform process-memory layer (Windows: Win32 APIs; Linux: /proc + process_vm_*). Ported verbatim in
// T1 (src/mem.rs). ALL game-memory reads/region-walks + pid/module-base lookups go through this.
use crate::mem;
// c_void is only needed by the Windows-only registry helpers (reg_dword / reg_string) below.
#[cfg(windows)]
use std::ffi::c_void;

// Same base the Tauri app used as `SKINSYNC` (config::SERVER_BASE == "https://nobd.net/skinsync"), so every
// request path below (/result, /heartbeat, /match/live, /register, …) is byte-identical to the shipped app.
const SKINSYNC: &str = crate::config::SERVER_BASE;
const STEAMID_HI: u32 = 0x0110_0001; // universe=public, type=individual, instance=desktop

// ════════════════════════════════════════════════════════════════════════════════════════════════════════
// ▼▼▼ VERBATIM PORT FROM sync.rs — do NOT edit the RE (offsets / anchor / struct reads / cadence). ▼▼▼
// ════════════════════════════════════════════════════════════════════════════════════════════════════════
// ══ MvC2 Steam offsets — the ONE table (RPM read-only). The REVERSED Steam-build layout ═══════════════
// The Steam MvC2 build's runtime struct differs from Demul: 6 fighter slots at STRIDE 0x738, order
// P1C1,P2C1,P1C2,P2C2,P1C3,P2C3 (even slot = P1, odd = P2 → side is the slot-index parity). Each slot
// starts with a cluster of ~16 working-buffer pointers; per-fighter fields are relative to that slot start
// `cl` = base + slot*STRIDE. The array BASE is VOLATILE per match (auto-found by fingerprint / pointer-follow
// — see find_array / pointer_follow_array). Battle-globals + meter are relative to the array base `ram`;
// kcode / localPlayerNum / the match-block pointer are relative to the game module (exe) base.
// ⚠ CONFIRMED-CORRECT — do NOT change: STRIDE 0x738, OFF_HEALTH 0x40c, OFF_REDHP 0x410, OFF_CHARID 0x554,
//    OFF_COMBO 0x1ca, OFF_INPUT 0x4fc, and the MATCH_PTR/MATCH_ARR pointer chain.

// ── (1) per-fighter slot offsets (relative to cl = base + slot*STRIDE) ──
pub(crate) const STRIDE: usize = 0x738;          // fighter-slot stride; even slot = P1, odd = P2
const OFF_COLOR:  usize = 0x6;        // palette/button-colour index
pub(crate) const OFF_DATPAL: usize = 0x4c;       // → this fighter's 16-colour ARGB4444 palette pointer (working-buffer range)
// Effect-safe paint window: skin ONLY the 6 base button-color groups [0, 0x600) in the DatPal block; PRESERVE
// [0x600, …) — the shared Status-Effects block + Extras (grenade/armor/lightning). 6 groups × 0x100 = 0x600.
pub(crate) const PAL_BASE_REGION: usize = 0x600;
const OFF_COMBO:  usize = 0x1ca;      // combo this fighter is DEALING (confirmed correct)
const OFF_HITSTUN: usize = 0x1d1;     // hitstun flag (u8): 0xFF = in hitstun/real hit, 0 = neutral-or-blocking.
                                      // ⚠ WAS 0x909 (= 0x1d1 + STRIDE) → read the NEXT slot's flag (same >stride
                                      // bug class as the old health 0xb44→0x40c). Fixed 2026-08-15 (RE-confirmed).
const OFF_HEALTH: usize = 0x40c;      // health (u32, full=144). ⚠ WAS 0xb44 (> stride → read the NEXT slot's health
                                      // = every win logged as a loss); 0x40c is the same-struct field. Confirmed
                                      // live: re-scoring a full set gives 6W-1L vs the user's ground-truth 8-2.
const OFF_REDHP:  usize = 0x410;      // recoverable (red) health (u16) = health+4. ⚠ WAS 0xb48 (old >stride bug).
const OFF_ASSIST: usize = 0x4e9;      // assist type: alpha=0 beta=1 gamma=2 (confirmed live 2026-08-11; DC +0x4C9 does NOT map)
const OFF_INPUT:  usize = 0x4fc;      // per-fighter input register (CPS2-decoded pad state for that side)
pub(crate) const OFF_CHARID: usize = 0x554;      // CPS2 unit id (char_id)
const OFF_POS_X:  usize = 0x61c;      // fighter world X (f32)
const OFF_POS_Y:  usize = 0x620;      // fighter world Y (f32)
const OFF_XVEL:   usize = 0x644;      // x velocity (f32)
const OFF_YVEL:   usize = 0x648;      // y velocity (f32)
const OFF_FACING: usize = 0x720;      // facing (u8) 0/1
const OFF_ACTION: usize = 0x76c;      // action/move-phase state (u8). TODO: likely next-slot (RE 2026-08-15), verify before fix
const OFF_COMBO_RECV: usize = 0x902;  // combo this fighter is RECEIVING. TODO: likely next-slot (RE 2026-08-15) —
                                      //   true combo (dealt) = OFF_COMBO 0x1ca is already correct; verify before fix

// ── (2) battle-globals + meter (relative to the array base `ram`) ──
// The DC BattleState struct transfers BYTE-FAITHFUL to array+0x2e5dc (MET_BARS/FILL are that base +0x5a/+0x7c;
// Ghidra-confirmed) → GROUND-TRUTH win/round state, no health inference.
const MET_BARS:       usize = 0x2e636;  // P1 meter bars 0-5; P2 = +1 (adjacent, per DC layout)
const MET_FILL:       usize = 0x2e658;  // P1 meter fine fill (u16) — confirmed +1 per Magneto LP
const OFF_PHASE:      usize = 0x2e5dc;  // u8: <5 = active fight, 5 = KO, 6 = win-pose, 9 = results
const OFF_BG_INMATCH: usize = 0x2e610;  // u8: 1 while a real match runs (the game's own gate)
const OFF_ROUND:      usize = 0x2e617;  // u8: game index within the set
const OFF_WINRESULT:  usize = 0x2e61a;  // u8: 0x00 = P1(even) won, 0x01 = P2(odd) won, 0xFF = draw. LATCHED at KO.
const OFF_BG_TIMER:   usize = 0x2e61c;  // u8: 99->0 round timer

// ── (3) exe-relative globals (relative to the game module base; default 0x140000000) + the anchor ──
const MATCH_PTR_OFF:   usize = 0xac6ef0;    // exe global → pointer to the CURRENT match block. ⚠ do NOT change
const MATCH_ARR_ADD:   usize = 0x3f24;      // fighter_array = *(exe+MATCH_PTR_OFF) + this. ⚠ pointer chain — do NOT change
const KCODE_OFF:       usize = 0xac6f58;    // flycast kcode[0] (the LOCAL pad) offset from the exe base
const LOCALPLAYER_OFF: usize = 0xac7230;    // localPlayerNum: 0 = P1, 1 = P2 (flycast's own side global, next to kcode;
                                            //   differential-capture confirmed: 0 in a live P1 match, 1 across 3 P2 matches)
const GSTATE_PTR_OFF:  usize = 0xacd3a0;    // exe global → pointer to game_state (scene id @ +0x8, locked picks @ +PICKS_OFF)
const PICKS_OFF:       usize = 0x758;       // char-select LOCKED picks (stride-4 char_ids) at game_state+this
const SESSION_PTR_OFF: usize = 0xacd3a8;    // exe global → pointer to the online SESSION object (hosted-lobby state).
                                            //   Adjacent to game_state (0xacd3a0); read only by the hosted-lobby path.
// ── Tier-3 set-score (the game's OWN per-set WINS tally — the HUD "WINS" counter). exe-relative global →
// POINTER to the set-score block: sc = *(exe+SET_SCORE_PTR_OFF). The tally increments on ANY game win — KO OR
// TIMEOUT — resetting per set, so a game-over always bumps exactly one side by +1. Read-only + ADDITIVE: the
// SERVER derives/auto-confirms the winner from the delta (covers timeouts the health-KO judge can't). Live-
// validated 2026-08-16 (lobby RE). Side mapping is the SAME as everywhere: localPlayerNum 0→P1, 1→P2.
const SET_SCORE_PTR_OFF: usize = 0x2edf628; // exe global → pointer to the set-score block (sc = *(exe+this))
const SET_P1_WINS_OFF:   usize = 0xbc;      // sc+this (u8) = P1 set-wins tally
const SET_P2_WINS_OFF:   usize = 0xbd;      // sc+this (u8) = P2 set-wins tally
const ARRAY_OFF:       usize = 0x10b3_3fc8; // anchor: fighter array = flycast_reservation_base + this (gs-70)

// ── (3b) hosted-lobby opponent detection (session-relative + MemberInfo-record-relative) ──
// In a HOSTED lobby the opponent's SteamID is NOT stored with the ranked pairing geometry; it lives in a heap
// MemberInfo record whose layout is fixed relative to OUR id. These locate it (see find_opponent_lobby).
// ⚠ HEURISTIC deltas — live-validated 2026-08-16 against a single lobby layout; harden as more lobbies are seen.
const LOBBY_HOSTED_OFF:  usize = 0xd0320;   // session+this (u32) == 1 → we are HOSTING a versus lobby
const LOBBY_NETSESS_OFF: usize = 0x1b8;     // session+this (i32) >= 0 → a net session is live
const LOBBY_OPP_GAP:     usize = 0x148;     // opp SteamID addr = (addr holding OUR id) + this  (rec+0x3c → rec+0x184)
const LOBBY_OPP_NAME:    usize = 0x184;     // opp persona addr  = (addr holding OUR id) + this  (= opp id addr + 0x3c)

// ── (4) limits / ranges ──
pub(crate) const WB_LO: u32 = 0x1000_0000;       // working-buffer pointer range LO (each fighter's own DAT region)
pub(crate) const WB_HI: u32 = 0x1420_0000;       // working-buffer pointer range HI
const HP_FULL: u16 = 144;             // full health
pub(crate) const MAX_CID: u8 = 0x3A;             // Servbot = highest CPS2 unit id (58)

// ── client registration (B): a per-install token the server mints, bound to the local SteamID. Stored in
//    %LOCALAPPDATA%\MetaSync\auth.json and attached (Bearer) to every write request. The SteamID is read
//    locally (self_ident → Steam registry) and can't be edited in the UI, so writes can't spoof another id. ──
static AUTH: std::sync::Mutex<Option<(String, String)>> = std::sync::Mutex::new(None); // (token, steamid)

fn metasync_dir() -> std::path::PathBuf {
    let base = std::env::var("LOCALAPPDATA").ok().map(std::path::PathBuf::from).unwrap_or_else(std::env::temp_dir);
    let dir = base.join("MetaSync");
    let _ = std::fs::create_dir_all(&dir);
    dir
}
fn auth_path() -> std::path::PathBuf { metasync_dir().join("auth.json") }

fn load_auth() {
    if let Some(v) = std::fs::read_to_string(auth_path()).ok().and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok()) {
        let tok = v.get("token").and_then(|x| x.as_str()).unwrap_or("").to_string();
        let sid = v.get("steamid").and_then(|x| x.as_str()).unwrap_or("").to_string();
        if !tok.is_empty() && sid.len() == 17 { *AUTH.lock().unwrap() = Some((tok, sid)); }
    }
}
fn auth_token() -> Option<String> { AUTH.lock().unwrap().as_ref().map(|(t, _)| t.clone()) }
fn auth_steamid_stored() -> Option<String> { AUTH.lock().unwrap().as_ref().map(|(_, s)| s.clone()) }

/// A ureq POST carrying the Bearer token when we have one (write routes require it server-side).
fn auth_post(url: &str) -> ureq::Request {
    // H1: default timeout on every authed POST so a hung/slow server can never park a Tauri worker thread
    // indefinitely (which would eventually starve detect_state and freeze the UI). Callers may override.
    let r = ureq::post(url).timeout(std::time::Duration::from_secs(8));
    match auth_token() { Some(t) => r.set("Authorization", &format!("Bearer {}", t)), None => r }
}

/// A ureq GET carrying the Bearer token when we have one (auth'd read routes require it server-side).
/// Same default timeout guard as auth_post so a hung server can never park a Tauri worker thread.
fn auth_get(url: &str) -> ureq::Request {
    let r = ureq::get(url).timeout(std::time::Duration::from_secs(8));
    match auth_token() { Some(t) => r.set("Authorization", &format!("Bearer {}", t)), None => r }
}

/// Register this install with the server (once per SteamID) and cache the returned token. Idempotent — a
/// no-op when we already hold a token for this SteamID. Safe to call often; called as soon as the local
/// SteamID is known (startup, from the Steam registry — no game needed).

pub fn ensure_registered(steamid: String) -> Result<(), String> {
    if steamid.len() != 17 { return Ok(()); } // no valid local id yet → caller retries later
    if auth_token().is_some() && auth_steamid_stored().as_deref() == Some(steamid.as_str()) { return Ok(()); }
    let resp = ureq::post(&format!("{}/register", SKINSYNC))
        .timeout(std::time::Duration::from_secs(8))
        .send_json(serde_json::json!({ "steamid": steamid }))
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())?;
    let token = resp.get("token").and_then(|x| x.as_str()).unwrap_or("").to_string();
    if token.is_empty() { return Err("no token".into()); }
    *AUTH.lock().unwrap() = Some((token.clone(), steamid.clone()));
    let _ = std::fs::write(auth_path(), serde_json::json!({ "token": token, "steamid": steamid }).to_string());
    Ok(())
}

// ---- team detection via per-character DAT signatures (see detect_state below) ----
// Each fighter's decompressed DAT carries a unique 64-byte gfx1 chunk. When a character is
// loaded for a match the game copies its DAT into a "working buffer" in the 0x10000000-0x14000000
// region (above the identity-mapped guest ROM at 0x0C000000). Exactly the 6 on-screen fighters
// have a copy there — so scanning that window for the 56 sigs yields the current teams, split
// P1 (first 3 by address) / P2 (last 3). Roster + side are correct; within-side point/assist
// order comes from the live palette, not load order.
const CHAR_SIGS: &str = include_str!("../char_sigs.json");

// Read a REG_DWORD from HKCU. None if missing/wrong type.
#[cfg(windows)]
fn reg_dword(subkey: &str, value: &str) -> Option<u32> {
    use windows::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_DWORD};
    use windows::core::HSTRING;
    unsafe {
        let mut data = 0u32; let mut sz = 4u32;
        let r = RegGetValueW(HKEY_CURRENT_USER, &HSTRING::from(subkey), &HSTRING::from(value),
            RRF_RT_REG_DWORD, None, Some(&mut data as *mut u32 as *mut c_void), Some(&mut sz));
        if r.is_ok() { Some(data) } else { None }
    }
}
// Read a REG_SZ from HKCU. None if missing.
#[cfg(windows)]
fn reg_string(subkey: &str, value: &str) -> Option<String> {
    use windows::Win32::System::Registry::{RegGetValueW, HKEY_CURRENT_USER, RRF_RT_REG_SZ};
    use windows::core::HSTRING;
    unsafe {
        let (sub, val) = (HSTRING::from(subkey), HSTRING::from(value));
        let mut sz = 0u32;
        if RegGetValueW(HKEY_CURRENT_USER, &sub, &val, RRF_RT_REG_SZ, None, None, Some(&mut sz)).is_err() || sz == 0 { return None; }
        let mut buf = vec![0u16; sz as usize / 2 + 1];
        let mut sz2 = (buf.len() * 2) as u32;
        if RegGetValueW(HKEY_CURRENT_USER, &sub, &val, RRF_RT_REG_SZ, None, Some(buf.as_mut_ptr() as *mut c_void), Some(&mut sz2)).is_err() { return None; }
        let n = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
        Some(String::from_utf16_lossy(&buf[..n]))
    }
}
// Our persona name from Steam's OWN config (config/loginusers.vdf), keyed by SteamID64. Lowercased for the
// "opponent isn't us" name compare. None if Steam path / entry not found.
// Windows-only: on Linux the persona comes straight from linux_self_ident's loginusers.vdf parse.
#[cfg(windows)]
fn steam_persona_name(id64: u64) -> Option<String> {
    let steam_path = reg_string("Software\\Valve\\Steam", "SteamPath")?;
    let vdf = std::fs::read_to_string(format!("{}/config/loginusers.vdf", steam_path)).ok()?;
    let key = format!("\"{}\"", id64);
    let rest = &vdf[vdf.find(&key)? + key.len()..];
    let after = &rest[rest.find("\"PersonaName\"")? + "\"PersonaName\"".len()..];
    let q1 = after.find('"')? + 1;
    let q2 = after[q1..].find('"')?;
    Some(after[q1..q1 + q2].trim().to_string())   // original case (display); callers lowercase for compares
}
// Our own Steam identity — sourced from Steam ITSELF, not a hook file. Primary: SteamID64 from the registry
// (HKCU\Software\Valve\Steam\ActiveProcess\ActiveUser = 32-bit account id; SteamID64 = 0x110000100000000 + it),
// which Steam keeps current, + persona name from Steam's own loginusers.vdf. The hook's legacy steam_self.txt
// is only a last-resort fallback. CACHED once resolved (our id/name don't change during a session).
fn self_ident() -> (u64, String) {
    static CACHE: OnceLock<Mutex<Option<(u64, String)>>> = OnceLock::new();
    let m = CACHE.get_or_init(|| Mutex::new(None));
    let mut g = m.lock().unwrap();
    if let Some(v) = g.as_ref() { return v.clone(); }
    // PRIMARY: Steam's own record of the signed-in user (platform-split, see active_user_ident).
    if let Some(v) = active_user_ident().filter(|(id, _)| *id != 0) {
        *g = Some(v.clone()); return v;
    }
    // LAST-RESORT fallback: the hook's legacy steam_self.txt (Windows path; absent on Linux → skipped).
    if let Ok(s) = std::fs::read_to_string(crate::runtime_dir().join("steam_self.txt")) {
        let mut it = s.lines();
        if let Some(id) = it.next().and_then(|l| l.trim().parse::<u64>().ok()) {
            let v = (id, it.next().map(|l| l.trim().to_string()).unwrap_or_default());
            *g = Some(v.clone()); return v;
        }
    }
    (0, String::new())
}

// Steam's signed-in user (id64, persona) — the primary self-identity source, platform-split.
// Windows: HKCU\...\ActiveProcess\ActiveUser (32-bit account id) → SteamID64 + persona from loginusers.vdf.
#[cfg(windows)]
fn active_user_ident() -> Option<(u64, String)> {
    let acct = reg_dword("Software\\Valve\\Steam\\ActiveProcess", "ActiveUser").filter(|&a| a != 0)?;
    let id = 0x0110_0001_0000_0000u64 + acct as u64;   // SteamID64 = 0x110000100000000 + account id
    Some((id, steam_persona_name(id).unwrap_or_default()))
}
// Linux: the MostRecent signed-in user in Steam's loginusers.vdf (no registry). ⚠ live-validate on the Beelink.
#[cfg(unix)]
fn active_user_ident() -> Option<(u64, String)> { linux_self_ident() }

// ── Linux Steam config helpers (used only by the identity path; live-validate on the Beelink) ──
#[cfg(unix)]
fn linux_steam_root() -> Option<String> {
    let home = std::env::var("HOME").ok()?;
    // native install, Flatpak, and the classic symlink roots — first with a readable loginusers.vdf wins.
    for cand in [
        format!("{}/.steam/steam", home),
        format!("{}/.local/share/Steam", home),
        format!("{}/.steam/root", home),
        format!("{}/.var/app/com.valvesoftware.Steam/.local/share/Steam", home),
    ] {
        if std::path::Path::new(&format!("{}/config/loginusers.vdf", cand)).exists() {
            return Some(cand);
        }
    }
    None
}
// Extract the value from a VDF `"Key"  "Value"` line (case-insensitive key). None if the line isn't that key.
#[cfg(unix)]
fn vdf_kv(line: &str, key: &str) -> Option<String> {
    let mut parts = line.split('"').filter(|s| !s.trim().is_empty());
    let k = parts.next()?;
    if !k.eq_ignore_ascii_case(key) { return None; }
    Some(parts.next()?.to_string())
}
// Parse loginusers.vdf: each 17-digit SteamID64 is a block key holding "PersonaName" + "MostRecent". Return
// the MostRecent="1" user (id64, persona); fall back to the first user seen.
#[cfg(unix)]
fn linux_self_ident() -> Option<(u64, String)> {
    let root = linux_steam_root()?;
    let vdf = std::fs::read_to_string(format!("{}/config/loginusers.vdf", root)).ok()?;
    let mut cur_id: Option<u64> = None;
    let mut cur_name = String::new();
    let mut best: Option<(u64, String)> = None;   // MostRecent="1"
    let mut first: Option<(u64, String)> = None;  // fallback: first block
    for line in vdf.lines() {
        let t = line.trim();
        // a bare `"7656..."` line (no whitespace inside the quotes) = a user-id block key
        if t.starts_with('"') && t.ends_with('"') && !t.trim_matches('"').contains(char::is_whitespace) {
            let inner = t.trim_matches('"');
            if inner.len() == 17 && inner.bytes().all(|b| b.is_ascii_digit()) {
                cur_id = inner.parse::<u64>().ok();
                cur_name = String::new();
                continue;
            }
        }
        if let Some(id) = cur_id {
            if let Some(v) = vdf_kv(t, "PersonaName") {
                cur_name = v;
                if first.is_none() { first = Some((id, cur_name.clone())); }
            }
            if let Some(v) = vdf_kv(t, "MostRecent") {
                if v == "1" { best = Some((id, cur_name.clone())); }
            }
        }
    }
    best.or(first)
}
fn read_self_id() -> Option<u64> { let id = self_ident().0; if id != 0 { Some(id) } else { None } }
// Used so the OPPONENT is never us — the friends/persona cache smears our name next to other players'
// SteamIDs, so a scan can otherwise return a candidate wearing our own name and show "us" on both sides.
fn read_self_name() -> String { self_ident().1.to_lowercase() }

// Locate the running game process (Windows: Toolhelp by exe name; Linux: /proc/*/cmdline + the PE at
// 0x140000000). Thin wrapper so every call site is unchanged.
fn find_game_pid() -> Option<u32> { mem::find_game_pid() }


fn name_quality(s: &str) -> i32 {
    // Unicode-aware: CJK/accented/cyrillic letters count as letters (not junk), so a non-ASCII handle isn't
    // out-ranked by ASCII memory-garbage. Only true symbols/emoji/control punctuation count against it.
    let letters = s.chars().filter(|c| c.is_alphabetic()).count() as i32;
    let spaces = s.chars().filter(|c| *c == ' ').count() as i32;
    let junk = s.chars().filter(|c| !c.is_alphanumeric() && *c != ' ' && *c != '_' && *c != '-' && *c != '.').count() as i32;
    letters * 2 + spaces.min(3) - junk * 3
}

// Read exactly `len` bytes at `addr` from an already-open Proc. None on short/failed read (full-length only).
unsafe fn read_window(h: &mem::Proc, addr: usize, len: usize) -> Option<Vec<u8>> {
    h.read(addr, len).filter(|b| b.len() == len)
}

// Persona run near an address — the opponent's name sits right beside its SteamID in the session.
// Steam stores personas as UTF-8, so a name byte is printable ASCII OR any UTF-8 multibyte byte (>=0x80).
// The old ASCII-only scan cut the name at the first non-ASCII byte (★/emoji/accents/CJK) — or, when the ASCII
// remainder was too short, grabbed a different nearby ASCII string entirely → the wrong opponent name.
fn name_near_rpm(h: &mem::Proc, addr: usize) -> String {
    let buf = match unsafe { read_window(h, addr.saturating_sub(0x40), 0xC0) } { Some(b) => b, None => return String::new() };
    let (mut best, mut cur): (Vec<u8>, Vec<u8>) = (Vec::new(), Vec::new());
    for &c in &buf {
        if (0x20..0x7f).contains(&c) || c >= 0x80 { cur.push(c); }
        else { if cur.len() > best.len() { best = cur.clone(); } cur.clear(); }
    }
    if cur.len() > best.len() { best = cur; }
    // Lossy-decode (a window edge can bisect a multibyte sequence) and strip any replacement chars the cut left.
    let t = String::from_utf8_lossy(&best).trim().trim_matches('\u{FFFD}').trim().to_string();
    if t.chars().count() >= 3 && plausible_opponent_name(&t) { t } else { String::new() }
}

// Scan ONE committed region for SteamID64s → collect our-id addresses + candidate-id addresses.
// CHUNKED reads (a whole-region read fails if ANY page inside is unreadable → silently drops the region that
// holds the session struct). STEP BY 4: the paired SteamIDs are 4-aligned but NOT 8-aligned (ours @ 0x..2ac,
// opp @ 0x..41c), so an i+=8 walk from an 8-aligned base steps right over every pairing.
unsafe fn scan_region_sids(h: &mem::Proc, base: usize, size: usize, my_id: u64,
                           my_addrs: &mut Vec<usize>, cand: &mut HashMap<u64, Vec<usize>>) {
    if size == 0 || size > 0x4000_0000 { return; }
    let mut off = 0usize;
    while off < size {
        let n = (size - off).min(0x80_0000);
        if let Some(buf) = read_window(h, base + off, n) {
            let mut i = 0usize;
            while i + 8 <= buf.len() {
                if u32::from_le_bytes([buf[i+4],buf[i+5],buf[i+6],buf[i+7]]) == STEAMID_HI {
                    let v = u64::from_le_bytes(buf[i..i+8].try_into().unwrap());
                    if v == my_id { if my_addrs.len() < 128 { my_addrs.push(base + off + i); } }
                    else { let e = cand.entry(v).or_default(); if e.len() < 24 { e.push(base + off + i); } }
                }
                i += 4;
            }
        }
        off += n;
    }
}
// Best paired opponent = the id that appears ≥2× within 0x400 of one of our id's occurrences → (sid, an addr near it).
fn best_pair(my_addrs: &[usize], cand: &HashMap<u64, Vec<usize>>) -> Option<(u64, usize)> {
    let mut best: Option<(u64, usize, usize)> = None;   // (sid, pairing_count, an-address-near-it)
    for (sid, addrs) in cand {
        let (mut pair, mut na) = (0usize, 0usize);
        for &a in addrs { if my_addrs.iter().any(|&m| (a as isize - m as isize).abs() < 0x400) { pair += 1; na = a; } }
        if pair >= 2 && best.map_or(true, |b| pair > b.1) { best = Some((*sid, pair, na)); }
    }
    best.map(|(sid, _p, na)| (sid, na))
}

// ★ DETERMINISTIC LOCAL SIDE from the session-struct pairing: P1's SteamID is stored ~0x170 ABOVE P2's. So if my
// id is the HIGHER of a ~0x170-apart pair → I'm P1; the lower → P2. 0 = no structural pair found (side unknown).
// (Verified: P2-vs-Duc → opp/P1 higher; P1-vs-Underdogg → me higher. Only the ~0x170 pair encodes side; other
//  co-located copies in the friends cache have arbitrary geometry, so we require the 0x170 gap specifically.)
fn detect_side(my_addrs: &[usize], opp_addrs: &[usize]) -> u8 {
    for &m in my_addrs { for &o in opp_addrs {
        let d = m as isize - o as isize;
        if (d.abs() - 0x170).abs() <= 0x10 { return if d > 0 { 1 } else { 2 }; }
    }}
    0
}
// Opponent display name = the MOST COMMON plausible string across ALL of its id copies. The real gamertag recurs
// at several copies; one-off garbage (e.g. "cjU>") appears once → the mode filters it out. (Taking the first
// non-empty string grabbed whichever copy we hit first, which was sometimes junk.)
unsafe fn name_of_opp(h: &mem::Proc, opp_addrs: &[usize]) -> String {
    let mut counts: HashMap<String, u32> = HashMap::new();
    for &a in opp_addrs { let nm = name_near_rpm(h, a); if !nm.is_empty() { *counts.entry(nm).or_insert(0) += 1; } }
    counts.into_iter().max_by_key(|(_, c)| *c).map(|(n, _)| n).unwrap_or_default()
}
// Turn a completed scan (my id addresses + candidate opp ids) into (opp_id, name, side) + refresh the caches.
unsafe fn finish_opp(h: &mem::Proc, my_addrs: &[usize], cand: &HashMap<u64, Vec<usize>>,
                     region: &mut Option<(usize, usize)>, cache: &mut Option<(usize, u8, String, u64)>) -> Option<(u64, String, u8)> {
    best_pair(my_addrs, cand).map(|(sid, na)| {
        let opp_addrs = cand.get(&sid).cloned().unwrap_or_default();
        let side = detect_side(my_addrs, &opp_addrs);
        let name = name_of_opp(h, &opp_addrs);   // resolved once from the most-common copy; cached below
        *cache = Some((na, side, name.clone(), sid));   // store the id too → fast-path can detect a CHANGED opponent
        if let Some(r) = h.region_at(na) {
            *region = Some((r.base, r.size));
        }
        (sid, name, side)
    })
}

// DETERMINISTIC opponent + side. Three tiers, fastest first: FAST (cached slot, re-validated) → WARM (cached
// region scan) → COLD (full sweep, first lock of a launch). Returns (opp_id, name, local_side 1/2/0).
fn find_opponent_netplay(pid: u32, my_id: u64, cache: &mut Option<(usize, u8, String, u64)>, region: &mut Option<(usize, usize)>) -> Option<(u64, String, u8)> {
    if pid == 0 || my_id == 0 { return None; }
    let proc = mem::Proc::open_read(pid)?;
    let h = &proc;
    unsafe {
        // 1. FAST PATH — cached slot, RE-VALIDATING THE PAIRING: the opponent is live only while OUR id is still
        //    co-located within 0x400 (a freed-but-not-zeroed slot lingers → returned the GHOST opponent forever).
        //    Returns the CACHED name (resolved once from the best copy) — don't re-scrape a single slot each cycle
        //    (that clobbered the good name with whatever junk sat next to this particular copy).
        if let Some((a, side, cached_name, cached_id)) = cache.clone() {
            let v = read_window(h, a, 8).map(|b| u64::from_le_bytes([b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7]])).unwrap_or(0);
            // Trust the cache ONLY if the SAME opponent id is still at the slot. If the value changed to a
            // DIFFERENT valid SteamID (the game reused this session slot for a NEW opponent), the cached NAME is
            // stale → invalidate + re-hunt so the new opponent AND name resolve fresh. This fixes "stuck on the
            // old opponent after they left mid-session and I went on to the next one."
            if v == cached_id && (v >> 32) as u32 == STEAMID_HI && v != my_id {
                let lo = a.saturating_sub(0x400);
                let paired = read_window(h, lo, 0x808).map_or(false, |w| {
                    let mut i = 0usize;
                    while i + 8 <= w.len() {
                        if u64::from_le_bytes([w[i],w[i+1],w[i+2],w[i+3],w[i+4],w[i+5],w[i+6],w[i+7]]) == my_id { return true; }
                        i += 4;
                    }
                    false
                });
                if paired { return Some((v, cached_name, side)); }
            }
            *cache = None;   // pairing gone / opponent CHANGED → fall through to WARM / COLD (re-resolves id + name)
        }
        // 2. WARM PATH — remembered region only.
        if let Some((rb, rs)) = *region {
            let mut my_addrs: Vec<usize> = Vec::new();
            let mut cand: HashMap<u64, Vec<usize>> = HashMap::new();
            scan_region_sids(h, rb, rs, my_id, &mut my_addrs, &mut cand);
            if let Some(r) = finish_opp(h, &my_addrs, &cand, region, cache) { return Some(r); }
            // stale region (new session elsewhere) → fall through to the full sweep, which refreshes it
        }
        // 3. COLD PATH — full committed-memory sweep (readable regions, exactly as the old VirtualQueryEx walk).
        let mut my_addrs: Vec<usize> = Vec::new();
        let mut cand: HashMap<u64, Vec<usize>> = HashMap::new();
        for r in h.regions() {
            if r.readable { scan_region_sids(h, r.base, r.size, my_id, &mut my_addrs, &mut cand); }
        }
        finish_opp(h, &my_addrs, &cand, region, cache)
    }
}

// A persona that STARTS exactly at `addr` — the lobby MemberInfo stores the name inline at a fixed field offset,
// unlike the ranked session cache where the name sits *near* the id (name_near_rpm). Read a forward window and
// take the LEADING printable/UTF-8 run (Steam personas are UTF-8, same handling as name_near_rpm).
fn name_fwd_rpm(h: &mem::Proc, addr: usize) -> String {
    let buf = match unsafe { read_window(h, addr, 0x80) } { Some(b) => b, None => return String::new() };
    let mut run: Vec<u8> = Vec::new();
    for &c in &buf {
        if (0x20..0x7f).contains(&c) || c >= 0x80 { run.push(c); } else { break; }
    }
    let t = String::from_utf8_lossy(&run).trim().trim_matches('\u{FFFD}').trim().to_string();
    if t.chars().count() >= 3 && plausible_opponent_name(&t) { t } else { String::new() }
}

// HOSTED-LOBBY opponent + side — the ADDITIVE fallback to find_opponent_netplay's ranked geometry. In a Steam
// "host a lobby" versus match the opponent's SteamID is NOT co-located with ours by the ~0x170 ranked pairing
// (so best_pair/detect_side find nothing); it lives in a heap MemberInfo record with a layout fixed relative to
// OUR id: our id @ rec+0x3c, opp id @ rec+0x184 (= our id + 0x148), opp persona @ rec+0x1c0 (= opp id + 0x3c).
// So we locate the record by scanning committed memory for an address A that holds OUR id where A+0x148 holds a
// DIFFERENT individual-account SteamID — that's the opponent; the persona is at A+0x184. Gated FIRST by the
// game's own hosted-versus flag (session+0xd0320 == 1), so it costs ~4 reads and NEVER sweeps outside a lobby,
// and can't misfire in ranked. On success it also PRIMES `cache` — the same slot find_opponent_netplay's fast
// path re-validates — so subsequent cycles re-confirm the opponent cheaply instead of re-sweeping. RPM
// read-only. Returns (opp_id, name, local_side 1/2/0) — side comes from localPlayerNum, exactly like ranked.
fn find_opponent_lobby(pid: u32, my_id: u64, exe_base: usize, cache: &mut Option<(usize, u8, String, u64)>) -> Option<(u64, String, u8)> {
    if pid == 0 || my_id == 0 || exe_base == 0 { return None; }
    let proc = mem::Proc::open_read(pid)?;
    let h = &proc;
    unsafe {
        // ── O(1) hosted-lobby gate ── two cheap derefs; bail unless we're hosting a versus lobby, so this
        // path is nearly free in ranked/offline and never runs the full sweep there.
        let session = read_at(h, exe_base + SESSION_PTR_OFF, 8).filter(|b| b.len() >= 8)
            .map(|b| u64::from_le_bytes([b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7]]) as usize)
            .filter(|&s| s > 0x10000);
        let session = match session { Some(s) => s, None => { return None; } };
        let hosted = rpm_u32(h, session + LOBBY_HOSTED_OFF) == Some(1);
        let net_ok = read_at(h, session + LOBBY_NETSESS_OFF, 4).filter(|b| b.len() >= 4)
            .map(|b| i32::from_le_bytes([b[0],b[1],b[2],b[3]])).map_or(false, |v| v >= 0);
        if !(hosted && net_ok) { return None; }

        // side from flycast localPlayerNum (0=P1→1, 1=P2→2; else unknown). Downstream ignores this for stats
        // (manual gate) but uses it for the team label, same as the ranked path.
        let side = match rpm_u32(h, exe_base + LOCALPLAYER_OFF) { Some(0) => 1, Some(1) => 2, _ => 0 };

        // ── committed-memory sweep for OUR id, then probe the MemberInfo delta ── mirrors the COLD sweep in
        // find_opponent_netplay (same region walk + chunked, page-safe RPM). Bounded: at most a couple of small
        // probe-reads per my_id hit (capped), first plausibly-named opponent wins.
        let mut named:  Option<(u64, usize, String)> = None; // (opp_id, addr-holding-OUR-id, name)
        let mut id_only: Option<(u64, usize)> = None;        // valid opp id but junk/no name at +0x184 (fallback)
        let mut id_only_conflict = false;                    // >1 distinct id-only candidate → don't trust it
        let mut probes = 0u32;                               // cap the per-hit probe reads (worst-case bound)
        'sweep: for r in h.regions() {
            if r.readable && r.size <= 0x4000_0000 {
                let (base, size) = (r.base, r.size);
                let mut off = 0usize;
                while off < size {
                    let n = (size - off).min(0x80_0000);
                    if let Some(buf) = read_at(h, base + off, n) {
                        let mut i = 0usize;
                        while i + 8 <= buf.len() {
                            // our id is 4-aligned but not 8-aligned in these records (same as the ranked scan) → step 4
                            if u32::from_le_bytes([buf[i+4],buf[i+5],buf[i+6],buf[i+7]]) == STEAMID_HI
                               && u64::from_le_bytes(buf[i..i+8].try_into().unwrap()) == my_id {
                                let a = base + off + i;
                                if probes < 8192 {
                                    probes += 1;
                                    // opp SteamID at A+0x148 — a DIFFERENT individual-account id → the lobby opponent
                                    if let Some(ob) = read_at(h, a + LOBBY_OPP_GAP, 8).filter(|b| b.len() >= 8) {
                                        let opp = u64::from_le_bytes([ob[0],ob[1],ob[2],ob[3],ob[4],ob[5],ob[6],ob[7]]);
                                        if (opp >> 32) as u32 == STEAMID_HI && opp != my_id {
                                            let name = name_fwd_rpm(h, a + LOBBY_OPP_NAME);
                                            if !name.is_empty() { named = Some((opp, a, name)); break 'sweep; }
                                            match id_only {
                                                None => id_only = Some((opp, a)),
                                                Some((x, _)) if x != opp => id_only_conflict = true,
                                                _ => {}
                                            }
                                        }
                                    }
                                }
                            }
                            i += 4;
                        }
                    }
                    off += n;
                }
            }
        }
        // Prefer the named hit; else a SINGLE unambiguous id-only record (name resolves next cycle / isn't needed
        // for the /peers skin fetch, which keys on the id).
        let result: Option<(u64, usize, String)> = match named {
            Some(v) => Some(v),
            None => match (id_only, id_only_conflict) {
                (Some((opp, a)), false) => Some((opp, a, String::new())),
                _ => None,
            },
        };
        if let Some((opp, a, name)) = &result {
            // PRIME the ranked fast-path cache: point it at the opp-id field (A+0x148). Our id sits 0x148 below,
            // well within the fast path's ±0x400 pairing window, so next cycle re-validates cheaply (no sweep).
            *cache = Some((*a + LOBBY_OPP_GAP, side, name.clone(), *opp));
        }
        result.map(|(opp, _a, name)| (opp, name, side))
    }
}

// ── READ-ONLY lobby locator (read_my_lobby command) ──────────────────────────────────────────────
// "Owner-adjacency fingerprint": a Steam lobby's structure stores the lobby CSteamID immediately
// followed (8 bytes later) by the OWNER's user CSteamID. OUR lobby is the one whose owner == our own
// SteamID. We tally every (lobby-id | our-id) adjacency across the game's committed PRIVATE heap and
// take the argmax; members = the distinct user CSteamIDs sitting within ±0x4000 of that lobby id.
// Pure ReadProcessMemory — no writes, never panics (Option-guarded; any failure → { in_lobby:false }).
// Reuses the same helpers as find_opponent_lobby: read_self_id / find_game_pid / read_at / the
// committed-region VirtualQueryEx walk.

// CSteamID bit layout: universe=bits56-63, type=bits52-55, instance=bits32-51.
fn is_lobby(v: u64) -> bool {
    (v >> 56) & 0xFF == 1 && (v >> 52) & 0xF == 8 && (((v >> 32) & 0xFFFFF) & 0x60000) != 0
}
fn is_user(v: u64) -> bool {
    (v >> 56) & 0xFF == 1 && (v >> 52) & 0xF == 1 && ((v >> 32) & 0xFFFFF) == 1
}

const MVC_APPID: u32 = 2634890; // MvC Fighting Collection Steam app id (for the join link)

fn not_in_lobby() -> serde_json::Value {
    serde_json::json!({ "in_lobby": false, "lobby_id": "", "owner_id": "", "join_link": "", "members": [] })
}

/// READ-ONLY: locate the user's CURRENT Steam lobby in the running game's memory and return a
/// shareable `steam://joinlobby/...` link + the member SteamID list. All u64 ids are serialized as
/// STRINGS (JS loses precision above 2^53). Never panics — any failure / game-not-running maps to
/// `{ in_lobby:false }`.

pub fn read_my_lobby() -> serde_json::Value {
    read_my_lobby_inner().unwrap_or_else(not_in_lobby)
}

fn read_my_lobby_inner() -> Option<serde_json::Value> {
    let our_id = read_self_id()?;   // no Steam identity → treat as not-in-lobby
    let pid = find_game_pid()?;     // game not running → not-in-lobby
    let proc = mem::Proc::open_read(pid)?;
    let h = &proc;
    unsafe {
        // ── Pass 1: committed-PRIVATE-heap sweep (same region walk + chunked, page-safe read_at as
        // find_opponent_lobby). Tally owner-adjacency per lobby id and remember each lobby id's addrs.
        // The old predicate `Type==MEM_PRIVATE && matches!(prot, 0x02|0x04|0x20|0x40)` (committed readable
        // private heap) maps EXACTLY to `r.private && r.readable` (WRITECOPY can't occur on private commit).
        let mut counts: HashMap<u64, u32> = HashMap::new();          // lobby id → owner-adjacency hits
        let mut lobby_at: HashMap<u64, Vec<usize>> = HashMap::new(); // lobby id → addresses it occupies
        for r in h.regions() {
            // ⚠ region cap raised 0x800_0000 (128MB) → 0x4000_0000 (1GB) for PROTON/WINE hosts: on Linux the
            // game's heap — where the lobby-owner structure lives — consolidates into ONE large region that the
            // old 128MB cap skipped, so read_my_lobby returned NOT-IN-LOBBY on Bazzite (live-confirmed 2026-08-19:
            // owner-adjacency only appeared once regions >128MB were scanned). Windows heaps stay small; the
            // higher cap is harmless there and correct on Proton.
            if r.private && r.readable && r.size <= 0x4000_0000 {
                let (base, size) = (r.base, r.size);
                let mut off = 0usize;
                while off < size {
                    let n = (size - off).min(0x80_0000);
                    if let Some(buf) = read_at(h, base + off, n) {
                        let mut i = 0usize;
                        while i + 8 <= buf.len() {
                            let v = u64::from_le_bytes(buf[i..i+8].try_into().unwrap());
                            if is_lobby(v) {
                                let e = lobby_at.entry(v).or_default();
                                if e.len() < 512 { e.push(base + off + i); }
                            } else if v == our_id {
                                // our id is a user id; the OWNER field sits 8 bytes AFTER its lobby id, so
                                // the lobby id is the 8 bytes immediately BEFORE this occurrence.
                                let a = base + off + i;
                                let lob = if i >= 8 {
                                    u64::from_le_bytes(buf[i-8..i].try_into().unwrap())
                                } else {
                                    // chunk boundary: read the preceding 8 bytes directly (page-safe)
                                    read_at(h, a.wrapping_sub(8), 8).filter(|b| b.len() >= 8)
                                        .map(|b| u64::from_le_bytes(b[..8].try_into().unwrap())).unwrap_or(0)
                                };
                                if is_lobby(lob) { *counts.entry(lob).or_insert(0) += 1; }
                            }
                            i += 4;
                        }
                    }
                    off += n;
                }
            }
        }

        // our lobby = the most-tallied owner-adjacency. None → not in a lobby.
        let lobby_id = match counts.into_iter().max_by_key(|&(_, c)| c).map(|(id, _)| id) {
            Some(id) => id,
            None => { return None; }
        };
        let anchors = lobby_at.get(&lobby_id).cloned().unwrap_or_default();

        // ── Pass 2: members = distinct user CSteamIDs within ±0x4000 of any occurrence of the chosen
        // lobby id (host + joiners, includes us). Read a bounded window around each anchor (page-safe;
        // a partial/failed read just contributes what it can).
        let mut seen: std::collections::HashSet<u64> = std::collections::HashSet::new();
        let mut members: Vec<String> = Vec::new();
        for &la in anchors.iter().take(64) {
            for (start, len) in [(la.saturating_sub(0x4000), 0x4000usize), (la, 0x4000usize)] {
                if let Some(buf) = read_at(h, start, len) {
                    let mut i = 0usize;
                    while i + 8 <= buf.len() {
                        let v = u64::from_le_bytes(buf[i..i+8].try_into().unwrap());
                        if is_user(v) && seen.insert(v) { members.push(v.to_string()); }
                        i += 4;
                    }
                }
            }
        }
        if seen.insert(our_id) { members.push(our_id.to_string()); } // owner is always a member

        Some(serde_json::json!({
            "in_lobby": true,
            "lobby_id": lobby_id.to_string(),
            "owner_id": our_id.to_string(),
            "join_link": format!("steam://joinlobby/{}/{}/{}", MVC_APPID, lobby_id, our_id),
            "members": members,
        }))
    }
}

pub fn sync_heartbeat(id: String, name: String) -> Result<serde_json::Value, String> {
    auth_post(&format!("{}/heartbeat", SKINSYNC)).send_json(serde_json::json!({ "id": id, "name": name, "ver": env!("CARGO_PKG_VERSION"), "platform": if cfg!(windows) { "windows" } else { "linux" }, "client": "tray" }))
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

// ---- stateful team detection (menu / character-select / match) ----

struct Sig { cid: u32, name: String, bytes: [u8; 64] }

// parsed once: the 56 signatures + a first-byte bucket table for a fast single-pass scan
fn sigtab() -> &'static (Vec<Sig>, Vec<Vec<usize>>) {
    static T: OnceLock<(Vec<Sig>, Vec<Vec<usize>>)> = OnceLock::new();
    T.get_or_init(|| {
        let map: HashMap<String, serde_json::Value> = serde_json::from_str(CHAR_SIGS).unwrap_or_default();
        let mut sigs: Vec<Sig> = Vec::new();
        for (k, v) in map {
            let cid: u32 = match k.parse() { Ok(n) => n, Err(_) => continue };
            let name = v["name"].as_str().unwrap_or("").to_string();
            let hex = v["sig"].as_str().unwrap_or("");
            if hex.len() != 128 { continue; }
            let mut bytes = [0u8; 64];
            let mut ok = true;
            for i in 0..64 {
                match u8::from_str_radix(&hex[i * 2..i * 2 + 2], 16) { Ok(b) => bytes[i] = b, Err(_) => { ok = false; break; } }
            }
            if ok { sigs.push(Sig { cid, name, bytes }); }
        }
        let mut buckets: Vec<Vec<usize>> = vec![Vec::new(); 256];
        for (i, s) in sigs.iter().enumerate() { buckets[s.bytes[0] as usize].push(i); }
        (sigs, buckets)
    })
}

#[derive(Clone)]
struct Found { cid: u32, name: String, addr: usize }

// ---- shared snapshot, produced by the single background reader thread (see start_reader) ----
// EVERY game-memory read happens on that one thread. The Tauri commands below are O(1) reads of this
// snapshot, so nothing heavy ever runs on the IPC path — the UI cannot be stalled by a scan.
struct Snapshot {
    state: String,                       // game_off | menu | select | match
    roster: Vec<Found>,                  // addr-sorted; [0..3]=P1, [3..6]=P2
    opponent: Option<(String, String)>,  // (steamid, name) via NaCherO co-location
    game: Option<GameSt>,                // live game state (RPM-read player array)
    score: (u32, u32),                   // (P1, P2) games won this set, computed from KO events
    local_side: u8,                      // auto-detected local side: 0=unknown, 1=P1, 2=P2 (input correlation)
    manual_side: u8,                     // user override: 0=auto (use local_side), 1=P1, 2=P2. Wins over auto for
                                         //   BOTH team labels and stats attribution. Reset when the opponent changes.
    side_confirmed: bool,                // ★ is the side TRUSTWORTHY for stats? true only via the manual toggle (or a
                                         //   future deterministic lock). The fuzzy auto-detectors do NOT set this.
                                         //   Games are BUFFERED (never recorded) until this is true → no wrong stats.
    in_session: bool,                    // ★ live netplay pairing present THIS cycle — the fastest, deterministic
                                         //   "we're in an online match" signal (true at loading/select, before fighters load)
    paint_slots: Vec<(u8, u8, u32)>,     // (player, char_id, datpal) — exact render-palette pointers for painting,
                                         //   NOT liveness-gated, so skins paint at match start via the pointer (no scan)
    ram_base: usize,                     // ★ the reader's CURRENTLY-LOCATED fighter array (anchor OR find_array). The
                                         //   array is NOT always at the anchor — it relocates per match — so paint_live
                                         //   uses THIS (the real located base) to resolve live DatPals, not just the anchor.
    session_id: String,                  // current ranked set's id ("" = none) — surfaced to the UI for the session chip
    match_index: u32,                    // games committed this set (0..SESSION_CAP)
    picks: Vec<u8>,                      // ★ char-select LOCKED picks (char_ids) read live from game_state+0x758 —
                                         //   populated DURING selection (before the fighter array), for instant skin preload
    scene: i32,                          // ★ game_state+0x8 screen-state id (5=match/fighting, else menu/select/results);
                                         //   the game's own screen controller — FPS-guards heavy scans + drives screen UI
}
// The side used for team-labeling + stats: the manual override wins; else the auto-detector.
fn snapshot() -> &'static Mutex<Snapshot> {
    static S: OnceLock<Mutex<Snapshot>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(Snapshot { state: "game_off".into(), roster: Vec::new(), opponent: None, game: None, score: (0, 0), local_side: 0, manual_side: 0, side_confirmed: false, in_session: false, paint_slots: Vec::new(), ram_base: 0, session_id: String::new(), match_index: 0, picks: Vec::new(), scene: -1 }))
}

// Per-fighter live state (the 6 fighter slots: char_id, palette colour index, health, DatPal, and the live
// 16-colour palette) read DIRECTLY from the game's player array via read-only RPM — ground truth from
// the game's own memory, no hook. See read_gamestate_rpm.
#[derive(Clone)]
struct GSlot { player: u8, pos: u8, char_id: u8, color: u8, health: u16, combo: u16, datpal: u32, pal: [u8; 32], addr: usize }

// The fighter's live 16-colour palette (ARGB4444 LE at the DatPal target) → the hook's RGBA sig format
// (RRGGBBAA per colour, index0 transparent) — the SAME expansion the ROM decoder + capture_live use, so a
// sig built here matches the on-screen texture the hook watches. All-zero pal → empty (no live palette).
pub(crate) fn pal_sig(pal: &[u8; 32]) -> String {
    if pal.iter().all(|&b| b == 0) { return String::new(); }
    let mut s = String::with_capacity(128);
    for i in 0..16 {
        if i == 0 { s.push_str("00000000"); continue; }
        let v = (pal[i * 2] as u16) | ((pal[i * 2 + 1] as u16) << 8);
        let r = (((v >> 8) & 0xF) * 17) as u8;
        let g = (((v >> 4) & 0xF) * 17) as u8;
        let b = ((v & 0xF) * 17) as u8;
        s.push_str(&format!("{:02x}{:02x}{:02x}ff", r, g, b));
    }
    s
}
#[derive(Clone)]
struct GameSt { in_match: u8, match_state: u8, stage: u8, timer: u32, frame: u32, ram: usize, slots: Vec<GSlot>, meter1: u8, meter2: u8,
                // ── battle-globals (gs-99): the game's own ground-truth match/round state ──
                phase: u8, win_result: u8, round_no: u8, bg_in_match: u8 }


// ── App-side player-array reader (RPM, READ-ONLY) — the REVERSED Steam-build layout ──
// (All MvC2 memory offsets — STRIDE / OFF_* / MET_* / exe globals / the anchor — live in the ONE table
//  near the top of this file. The array BASE is VOLATILE per match; see find_array / pointer_follow_array.)

pub(crate) unsafe fn rpm_u8(h: &mem::Proc, a: usize) -> Option<u8> { read_at(h, a, 1).filter(|b| b.len() >= 1).map(|b| b[0]) }
unsafe fn rpm_u16(h: &mem::Proc, a: usize) -> Option<u16> { read_at(h, a, 2).filter(|b| b.len() >= 2).map(|b| b[0] as u16 | ((b[1] as u16) << 8)) }
pub(crate) unsafe fn rpm_u32(h: &mem::Proc, a: usize) -> Option<u32> { read_at(h, a, 4).filter(|b| b.len() >= 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]])) }

// ── Tier-3 set-score read (read-only RPM, ADDITIVE observation) ──────────────────────────────────────
// Deref *(exe_base+SET_SCORE_PTR_OFF) → the set-score block, validate the pointer, then read the game's own
// per-set WINS tally: P1 @ sc+0xbc, P2 @ sc+0xbd (u8 each). The tally bumps on ANY game win (KO OR TIMEOUT),
// so the SERVER can auto-confirm the winner from the delta — covering timeouts the health-KO judge misses.
// Every read is Option-returning (read_at/rpm_u8) and the pointer bytes are length-guarded → CANNOT panic.
// Any bad/short read (or a null-ish pointer) → None, so a failed read is simply absent downstream.
unsafe fn read_set_score(h: &mem::Proc, exe_base: usize) -> Option<(u8, u8)> {
    if exe_base == 0 { return None; }
    let b = read_at(h, exe_base + SET_SCORE_PTR_OFF, 8).filter(|b| b.len() >= 8)?;
    let sc = u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]) as usize;
    if sc <= 0x10000 { return None; }   // reject a null / obviously-invalid pointer
    let p1 = rpm_u8(h, sc + SET_P1_WINS_OFF)?;
    let p2 = rpm_u8(h, sc + SET_P2_WINS_OFF)?;
    Some((p1, p2))
}

// One-time locate of a FINE (per-render-frame) guest frame_counter: a u32 near the array that ticks up by
// ~1 EVERY render frame, SMOOTHLY. The critical distinction (root cause of the v0.1.10 6Hz decimation): the
// game also has a COARSE counter that jumps by ~10 every ~10 frames (flat, then +10). At the old 180ms
// sampling both look like "~11 per sample", so the old hunt could pick the coarse one → dedup-by-counter
// stored only every 10th frame → 6Hz. We now sample FAST (~22ms): the fine counter ticks every sample by a
// small amount; the coarse one reads flat between its jumps → rejected. If nothing qualifies we return None,
// and the caller's synthetic per-poll index is ALSO dense (~60Hz) — so the capture is never decimated.
unsafe fn hunt_frame_counter(h: &mem::Proc, array: usize) -> Option<usize> {
    let r = h.region_at(array)?;
    let rbase = r.base; let rend = r.base + r.size;
    let lo = array.saturating_sub(0x80_0000).max(rbase);
    let hi = (array + 0x80_0000).min(rend);
    if hi <= lo + 0x1000 { return None; }
    let size = (hi - lo) & !3usize;
    const NS: usize = 12;                                   // ~12 samples @ 22ms ≈ 264ms, fast enough to see per-frame ticks
    let mut snaps: Vec<Vec<u32>> = Vec::with_capacity(NS);
    for _ in 0..NS {
        let buf = read_at(h, lo, size)?;
        if buf.len() < size { return None; }
        let words: Vec<u32> = (0..size / 4).map(|i| { let o = i * 4; u32::from_le_bytes([buf[o], buf[o + 1], buf[o + 2], buf[o + 3]]) }).collect();
        snaps.push(words);
        std::thread::sleep(std::time::Duration::from_millis(22));
    }
    let n = snaps.iter().map(|v| v.len()).min().unwrap_or(0);
    let ns = snaps.len();
    let mut best: Option<(usize, i64)> = None;
    'off: for i in 0..n {
        let mut ticks = 0usize;                             // samples where it advanced (a live per-frame counter ticks most samples)
        let mut deltas: Vec<i64> = Vec::with_capacity(ns - 1);
        for s in 0..ns - 1 {
            let delta = snaps[s + 1][i] as i64 - snaps[s][i] as i64;
            if delta < 0 || delta > 6 { continue 'off; }    // monotonic + NO coarse jumps (kills the +10-every-10-frames counter)
            if delta >= 1 { ticks += 1; }
            deltas.push(delta);
        }
        if ticks < (ns - 1) * 3 / 4 { continue 'off; }      // must tick nearly every 22ms sample (fine, not flat-then-jump)
        deltas.sort();
        let med = deltas[deltas.len() / 2];
        if med < 1 || med > 3 { continue 'off; }            // ~1-2 per sample at 22ms (≈1.3 render frames/sample)
        let score = (med - 1).abs();                        // prefer the finest (closest to 1 tick/sample)
        if best.map_or(true, |(_, b)| score < b) { best = Some((lo + i * 4, score)); }
    }
    best.map(|(a, _)| a)
}

// ── AUTO GAME-STATE RECORDING (tester beta) ────────────────────────────────────────────────────────
// Every client auto-records FULL per-frame game state during a match and uploads it to the skinsync
// server keyed by the SAME consensus match_key the leaderboard uses (so a recording joins its metadata
// and both players' recordings of one game correlate). Gated behind the `share_gameplay_data` setting
// (default true for the beta). BYOR-safe: numeric memory-read state only, no ROM/game bytes.
//
// A dedicated fast thread (start_gamestate_capture) fills a frame-keyed buffer (LAST-WRITE-WINS so a
// rollback self-corrects — same approach as scratchpad/ranked_capture.py). It resets at each fresh
// game start and STOPS (but keeps the buffer) at game end. The reader thread's on_game_win() snapshots
// that buffer and spawns the upload alongside the /result report (never on the reader hot path).
static SHARE_GAMEPLAY: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(true); // beta default = share
// TRUE while a live match is actively being recorded. The uploader NEVER runs while this is set, so a big
// spooled upload can never compete with the game for CPU/IO — recordings are drained only between matches.
static GS_IN_MATCH: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
fn share_file() -> std::path::PathBuf { crate::runtime_dir().join("share_gameplay.txt") }
const GS_CAP: usize = 20_000;                       // max unique frames buffered per game (~5.5 min @60fps)
const GS_SPOOL_CAP: usize = 300;                    // max pending recordings on disk (soft backpressure)
const SKINSYNC_GAMESTATE: &str = "https://nobd.net/skinsync/gamestate";

// Per-user spool for finished recordings, drained by the uploader between matches. LOCALAPPDATA so it
// survives an app restart (a recording captured before a crash still uploads next launch); temp is a fallback.
fn gs_cache_dir() -> std::path::PathBuf {
    let base = std::env::var("LOCALAPPDATA").ok().map(std::path::PathBuf::from)
        .unwrap_or_else(std::env::temp_dir);
    let dir = base.join("MetaSync").join("gs-cache");
    let _ = std::fs::create_dir_all(&dir);
    dir
}
// Write bytes atomically (tmp + rename) so the uploader never reads a half-written spool file. The tmp
// suffix (.gz→.gztmp / .meta→.metatmp) is chosen so it can't collide with the *.meta scan pattern.
fn atomic_write(path: &std::path::Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = path.with_extension("writing");
    std::fs::write(&tmp, bytes)?;
    std::fs::rename(&tmp, path)
}
const GS_SCHEMA: &str = "[frame,p1_in,p2_in,kcode,hp[6],px[6],py[6],p1_meter,p2_meter,meter_fill,combo_dealt[6],combo_recv[6],vx[6],vy[6],red_hp[6],facing[6],hitstun[6],action[6]]";

fn gs_now_ms() -> u64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0) }

fn load_share_setting() {
    if let Ok(s) = std::fs::read_to_string(share_file()) {
        let t = s.trim();
        if t == "0" || t.eq_ignore_ascii_case("false") || t.eq_ignore_ascii_case("off") {
            SHARE_GAMEPLAY.store(false, std::sync::atomic::Ordering::SeqCst);
        }
    }
}

// One captured frame row (matches GS_SCHEMA). Frame-keyed in a BTreeMap → sorted + last-write-wins.
#[derive(Clone)]
struct GsRow {
    frame: u32, p1_in: u16, p2_in: u16,
    kcode: u32,   // ★ the LOCAL pad (flycast kcode[0] @ exe+KCODE_OFF) — correlate vs p1_in/p2_in offline to find
                  //   which team is the reporter's (mirror-proof, skin-independent) → objective W/L attribution.
    hp: [u16; 6], px: [f32; 6], py: [f32; 6],
    m1: u8, m2: u8, mfill: u16, cd: [u16; 6], cr: [u16; 6],
    // additional per-slot match state
    vx: [f32; 6], vy: [f32; 6], rhp: [u16; 6], face: [u8; 6], hitstun: [u8; 6], act: [u8; 6],
}
struct GsCapture {
    frames: std::collections::BTreeMap<u32, GsRow>, // frame_counter -> row (last-write-wins, sorted)
    frame_addr: usize,                              // located guest frame counter (0 = synthetic index)
    synthetic: bool,                                // true when no counter found → monotonic per-frame index
    assist: [u8; 6],                                // assist type per slot (alpha=0/beta=1/gamma=2) — fixed per match
    local_pn: u8,                                   // ★ raw localPlayerNum (exe+LOCALPLAYER_OFF) at match start — the
                                                    //   game's own local netplay index (0/1), UN-overridden by any app
                                                    //   layer. Candidate side signal; validated offline vs the frame KO.
    set_start: Option<(u8, u8)>,                    // ★ Tier-3: the game's own per-set WINS tally (P1,P2) snapshotted at
                                                    //   THIS game's START. Paired with set_end (read at win-report) so the
                                                    //   server auto-confirms the winner from the +1 delta (KO AND timeout).
    last_update: Option<std::time::Instant>,        // for the recency guard in the snapshot
}
impl Default for GsCapture {
    fn default() -> Self { GsCapture { frames: std::collections::BTreeMap::new(), frame_addr: 0, synthetic: false, assist: [0; 6], local_pn: 255, set_start: None, last_update: None } }
}
fn gs_capture() -> &'static Mutex<GsCapture> {
    static S: OnceLock<Mutex<GsCapture>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(GsCapture::default()))
}

// A snapshot of the current/just-ended game's frames, taken by on_game_win at KO time.
struct GsSnapshot { frames: Vec<GsRow>, frame_addr: usize, synthetic: bool, assist: [u8; 6], local_pn: u8, set_start: Option<(u8, u8)> }
// Return the buffered game IFF it was actively updating within the last few seconds (i.e. it IS the game
// that just ended). This guards against attaching a stale/other game's buffer to a late (pending-flush) win.
fn gamestate_snapshot() -> Option<GsSnapshot> {
    let c = gs_capture().lock().unwrap();
    if c.frames.is_empty() { return None; }
    if c.last_update.map_or(true, |t| t.elapsed().as_secs() > 6) { return None; }
    Some(GsSnapshot { frames: c.frames.values().cloned().collect(), frame_addr: c.frame_addr, synthetic: c.synthetic, assist: c.assist, local_pn: c.local_pn, set_start: c.set_start })
}

fn le32(b: &[u8], o: usize) -> u32 { u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]) }
fn lef32(b: &[u8], o: usize) -> f32 { f32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]) }

fn gs_team_wiped(hp: &[u16; 6]) -> bool { (hp[0] == 0 && hp[2] == 0 && hp[4] == 0) || (hp[1] == 0 && hp[3] == 0 && hp[5] == 0) }
#[allow(dead_code)] // superseded by gs_match_load; kept as a documented helper
fn gs_both_alive(hp: &[u16; 6]) -> bool { (hp[0] > 0 || hp[2] > 0 || hp[4] > 0) && (hp[1] > 0 || hp[3] > 0 || hp[5] > 0) }
// TRUE match-load = frame 0 of the FIGHT: all real chars (slots 0..4; slot5 = un-loaded 3rd char reads a
// sentinel) at full 144 AND the two point chars at the symmetric spawn spacing (|x|>190, opposite sides).
// This does NOT fire on a mid-match fresh-character swap (only 1-2 slots refresh) — the fix for the v1
// `gs_both_alive` gate that started 4/10 captures mid-fight. Caught during the intro (points still at ~+-213,
// pre-movement) so the tape's frame-0 == the twin's, and positions self-align on replay.
fn gs_match_load(r: &GsRow) -> bool {
    let full = (0..5).all(|i| r.hp[i] >= 144);
    let pts = r.px[0].abs() > 190.0 && r.px[1].abs() > 190.0 && (r.px[0] > 0.0) != (r.px[1] > 0.0);
    full && pts
}

// Read one full per-frame row off the located array. 6 slot reads (0xB48 each, covers every field) + the
// 3 global-meter reads. Read-only RPM; runs on the dedicated capture thread only.
unsafe fn read_gs_row(h: &mem::Proc, base: usize, frame: u32, exe_base: usize) -> Option<GsRow> {
    let mut s: Vec<Vec<u8>> = Vec::with_capacity(6);
    for i in 0..6 {
        let buf = read_at(h, base + i * STRIDE, 0xB50)?;   // 0xB50 (was 0xB48) to include red_health @ +0xb48
        if buf.len() < 0xB50 { return None; }
        s.push(buf);
    }
    let hp = |i: usize| -> u16 { let v = le32(&s[i], OFF_HEALTH) & 0xffff; if v > 999 { 999 } else { v as u16 } };
    let rhp = |i: usize| -> u16 { let v = u16le(&s[i], OFF_REDHP); if v > 999 { 999 } else { v } };
    let hp_arr = [hp(0), hp(1), hp(2), hp(3), hp(4), hp(5)];
    // STRONG negative gate (matches read_fighters): any real fighter health > 144 means this is a
    // stale/half-written savestate COPY — drop the frame so garbage (hp=235) never enters a recording.
    if hp_arr.iter().any(|&v| v > HP_FULL) { return None; }
    Some(GsRow {
        frame,
        p1_in: u16le(&s[0], OFF_INPUT), p2_in: u16le(&s[1], OFF_INPUT),
        kcode: if exe_base != 0 { rpm_u32(h, exe_base + KCODE_OFF).unwrap_or(0) } else { 0 },
        hp: hp_arr,
        px: [lef32(&s[0], OFF_POS_X), lef32(&s[1], OFF_POS_X), lef32(&s[2], OFF_POS_X), lef32(&s[3], OFF_POS_X), lef32(&s[4], OFF_POS_X), lef32(&s[5], OFF_POS_X)],
        py: [lef32(&s[0], OFF_POS_Y), lef32(&s[1], OFF_POS_Y), lef32(&s[2], OFF_POS_Y), lef32(&s[3], OFF_POS_Y), lef32(&s[4], OFF_POS_Y), lef32(&s[5], OFF_POS_Y)],
        m1: rpm_u8(h, base + MET_BARS).unwrap_or(0),
        m2: rpm_u8(h, base + MET_BARS + 1).unwrap_or(0),
        mfill: rpm_u16(h, base + MET_FILL).unwrap_or(0),
        cd: [u16le(&s[0], OFF_COMBO), u16le(&s[1], OFF_COMBO), u16le(&s[2], OFF_COMBO), u16le(&s[3], OFF_COMBO), u16le(&s[4], OFF_COMBO), u16le(&s[5], OFF_COMBO)],
        cr: [u16le(&s[0], OFF_COMBO_RECV), u16le(&s[1], OFF_COMBO_RECV), u16le(&s[2], OFF_COMBO_RECV), u16le(&s[3], OFF_COMBO_RECV), u16le(&s[4], OFF_COMBO_RECV), u16le(&s[5], OFF_COMBO_RECV)],
        vx: [lef32(&s[0], OFF_XVEL), lef32(&s[1], OFF_XVEL), lef32(&s[2], OFF_XVEL), lef32(&s[3], OFF_XVEL), lef32(&s[4], OFF_XVEL), lef32(&s[5], OFF_XVEL)],
        vy: [lef32(&s[0], OFF_YVEL), lef32(&s[1], OFF_YVEL), lef32(&s[2], OFF_YVEL), lef32(&s[3], OFF_YVEL), lef32(&s[4], OFF_YVEL), lef32(&s[5], OFF_YVEL)],
        rhp: [rhp(0), rhp(1), rhp(2), rhp(3), rhp(4), rhp(5)],
        face: [s[0][OFF_FACING], s[1][OFF_FACING], s[2][OFF_FACING], s[3][OFF_FACING], s[4][OFF_FACING], s[5][OFF_FACING]],
        hitstun: [s[0][OFF_HITSTUN], s[1][OFF_HITSTUN], s[2][OFF_HITSTUN], s[3][OFF_HITSTUN], s[4][OFF_HITSTUN], s[5][OFF_HITSTUN]],
        act: [s[0][OFF_ACTION], s[1][OFF_ACTION], s[2][OFF_ACTION], s[3][OFF_ACTION], s[4][OFF_ACTION], s[5][OFF_ACTION]],
    })
}

// The dedicated per-frame capture thread. Idle-cheap (300ms) until a live match; fast (~3ms) while a game
// runs. Autonomous game-boundary detection mirrors ranked_capture.py: a game = both teams alive → record
// until a team is wiped (or the frame counter freezes / the array dies). The buffer is KEPT after a game
// ends so the reader's on_game_win can snapshot it; it's reset at the NEXT fresh game start.
fn start_gamestate_capture() {
    std::thread::spawn(|| {
        use std::sync::atomic::Ordering::SeqCst;
        let mut full_since: Option<std::time::Instant> = None; // how long all real chars have been full (match-load fallback timer)
        loop {
            if !SHARE_GAMEPLAY.load(SeqCst) { std::thread::sleep(std::time::Duration::from_millis(500)); continue; }
            let pid = match find_game_pid() { Some(p) => p, None => { std::thread::sleep(std::time::Duration::from_millis(600)); continue; } };
            let proc = match mem::Proc::open_read(pid) { Some(p) => p, None => { std::thread::sleep(std::time::Duration::from_millis(600)); continue; } };
            let h = &proc;
            let exe_base = game_exe_base(pid);   // for the local pad (kcode) recorded per frame → offline side-attribution
            // wait for a live match with BOTH teams alive (a fresh game start, not a mid-KO/loading copy).
            // Prefer the base the MAIN reader already located via find_array (struct-layout scan → the LIVE copy,
            // not a rollback savestate). anchor_array is only a fallback for the brief window before the reader
            // locks on — using it as the primary source is why the capture recorded ZERO frames (it kept landing
            // on rejected savestate copies).
            let base = {
                let rb = { snapshot().lock().unwrap().ram_base };
                // rely SOLELY on the main reader's located (most-animating) base — never the fixed anchor, which on
                // this relocating build points at stale savestate copies (the between-match "random Ryu" source).
                if rb != 0 && unsafe { array_valid(h, rb) } { rb }
                else { std::thread::sleep(std::time::Duration::from_millis(300)); continue; }
            };
            let start_row = match unsafe { read_gs_row(h, base, 0, exe_base) } { Some(r) => r, None => { std::thread::sleep(std::time::Duration::from_millis(200)); continue; } };
            // TRUE match-load gate. Ideal: catch the +-213 spawn during the intro (gs_match_load) so the tape
            // starts at frame 0 of the FIGHT. Fallback: if all real chars have been full for ~1.5s but we never
            // caught the spawn (attached mid-intro), start anyway so a match is never entirely missed. The 50ms
            // poll (vs v1's 200ms) is what lets us land inside the ~1-2s intro window.
            let full = (0..5).all(|i| start_row.hp[i] >= 144);
            if full { full_since.get_or_insert_with(std::time::Instant::now); } else { full_since = None; }
            let ready = gs_match_load(&start_row)
                || (full && full_since.map_or(false, |t| t.elapsed().as_millis() > 1500));
            if !ready { std::thread::sleep(std::time::Duration::from_millis(50)); continue; }
            full_since = None; // consumed → re-arm the fallback timer for the next match

            // ── a game is starting → reset the buffer, locate the guest frame counter (one-time, ~1s), and
            //    snapshot the assist type per slot (chosen at char-select, fixed for the whole match) ──
            let fc = unsafe { hunt_frame_counter(h, base) };
            let mut assist = [0u8; 6];
            for i in 0..6 { assist[i] = unsafe { rpm_u8(h, base + i * STRIDE + OFF_ASSIST) }.unwrap_or(0); }
            // Tier-3: snapshot the game's own per-set WINS tally at THIS game's START (read-only, guarded → None
            // on any failure). Paired with set_end (read at win-report) so the server auto-confirms via the delta.
            let set_start = unsafe { read_set_score(h, exe_base) };
            {
                let mut c = gs_capture().lock().unwrap();
                c.frames.clear();
                c.frame_addr = fc.unwrap_or(0);
                c.synthetic = fc.is_none();
                c.assist = assist;
                c.local_pn = if exe_base != 0 { unsafe { rpm_u32(h, exe_base + LOCALPLAYER_OFF) }.unwrap_or(255) as u8 } else { 255 };
                c.set_start = set_start;
                c.last_update = None;
            }
            GS_IN_MATCH.store(true, SeqCst);   // pause the uploader for the duration of the fight
            trace(&format!("[gamestate] recording START base=0x{base:x} fc={} (share={})",
                fc.map(|a| format!("0x{a:x}")).unwrap_or_else(|| "SYNTHETIC".into()), SHARE_GAMEPLAY.load(SeqCst)));

            // ── fast per-frame loop until the game ends ──
            let mut last = u32::MAX;
            let mut synth = 0u32;
            let mut wipe_since: Option<std::time::Instant> = None;
            let mut last_new = std::time::Instant::now();
            let mut prev_sig: Option<([u16; 6], [u32; 6])> = None; // freeze detector (state byte-identical → frozen)
            let mut same_ct = 0u32;
            loop {
                if !SHARE_GAMEPLAY.load(SeqCst) { break; }
                let frame = match fc { Some(a) => unsafe { rpm_u32(h, a) }.unwrap_or(0), None => { synth += 1; synth } };
                // P0.3: guard the per-frame read+record so one panicking frame can't kill the capture thread.
                // Returns true when the freeze-guard wants to stop the tape (kept as a signal so the `break`
                // still fires outside the closure); a panic is logged and treated as "no row this frame".
                let frozen = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| -> bool {
                    if frame != last {
                        if let Some(row) = unsafe { read_gs_row(h, base, frame, exe_base) } {
                            {
                                let mut c = gs_capture().lock().unwrap();
                                // LAST-WRITE-WINS: a rollback re-visits an earlier frame → overwrites it with the
                                // confirmed state. Cap at GS_CAP unique frames (still allow updates to existing keys).
                                if c.frames.len() < GS_CAP || c.frames.contains_key(&frame) {
                                    c.frames.insert(frame, row.clone());
                                    c.last_update = Some(std::time::Instant::now());
                                }
                            }
                            wipe_since = if gs_team_wiped(&row.hp) { wipe_since.or_else(|| Some(std::time::Instant::now())) } else { None };
                            last = frame; last_new = std::time::Instant::now();
                            // FREEZE GUARD: a synthetic frame counter keeps incrementing even on a stuck/stale base;
                            // if the actual state is byte-identical for many frames, the base is frozen — stop the
                            // tape instead of filling it with a stuck copy (the 20k-identical-garbage-frame artifact).
                            let sig = (row.hp, [row.px[0].to_bits(), row.px[1].to_bits(), row.px[2].to_bits(), row.px[3].to_bits(), row.px[4].to_bits(), row.px[5].to_bits()]);
                            if Some(&sig) == prev_sig.as_ref() { same_ct += 1; } else { same_ct = 0; prev_sig = Some(sig); }
                            if same_ct > 240 { return true; }   // ~0.7s of zero change → frozen base
                        }
                    }
                    false
                })).unwrap_or_else(|_| { trace("[gamestate] frame panicked — recovering, continuing"); false });
                if frozen { break; }                                                           // frozen base → stop the tape
                if wipe_since.map_or(false, |t| t.elapsed().as_millis() > 600) { break; }     // a team wiped → game over
                if last_new.elapsed().as_millis() > 2500 { break; }                            // frame counter froze → moved on
                if !unsafe { array_valid(h, base) } { break; }                                 // array relocated/gone
                std::thread::sleep(std::time::Duration::from_millis(3));                        // ~gentle fast poll, dedup by frame
            }
            GS_IN_MATCH.store(false, SeqCst);  // fight over → the uploader may drain the spool again
            {
                let n = gs_capture().lock().unwrap().frames.len();
                trace(&format!("[gamestate] recording END frames={n} (held for upload on win-report)"));
            }
            // handle (proc) is dropped at the end of this outer-loop iteration → its Drop closes it
            // don't immediately re-lock the just-ended game: the both-alive gate at the top of the loop already
            // holds until the next game loads both teams, so a brief pause here is all we need.
            std::thread::sleep(std::time::Duration::from_millis(300));
        }
    });
}

// gzip (flate2 is already a dependency) → base64 (std-only, no crate). Used only off the reader hot path.
fn gzip_bytes(data: &[u8]) -> Vec<u8> {
    use std::io::Write;
    let mut e = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::default());
    let _ = e.write_all(data);
    e.finish().unwrap_or_default()
}
fn b64_encode(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((data.len() + 2) / 3 * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(T[((n >> 18) & 0x3f) as usize] as char);
        out.push(T[((n >> 12) & 0x3f) as usize] as char);
        out.push(if chunk.len() > 1 { T[((n >> 6) & 0x3f) as usize] as char } else { '=' });
        out.push(if chunk.len() > 2 { T[(n & 0x3f) as usize] as char } else { '=' });
    }
    out
}

// Tier-3: an Option set-score → a top-level JSON value. Some((p1,p2)) → [p1,p2] (2-int array); None → null.
// Explicit (not the tuple-through-json! path) so the shape is unambiguous and absent-safe by construction.
fn set_score_json(v: Option<(u8, u8)>) -> serde_json::Value {
    match v { Some((a, b)) => serde_json::json!([a, b]), None => serde_json::Value::Null }
}

// Build the stored record (metadata + frame array), gzip it, and SPOOL it to the local cache as
// <match_key>_<reporter>.json.gz + a .meta envelope. The uploader drains the spool between matches, so no
// large upload ever runs during a fight. The .gz gunzips to this exact record (server writes it verbatim).
fn spool_gamestate(match_key: &str, reporter: &str, side: u8, p1_team: &[u8], p2_team: &[u8],
                   winner: &str, loser: &str, gs: &GsSnapshot, session_id: &str, match_index: u32,
                   set_end: Option<(u8, u8)>) {
    let dir = gs_cache_dir();
    // soft backpressure: if uploads are failing and the spool is huge, stop piling on.
    let pending = std::fs::read_dir(&dir)
        .map(|rd| rd.flatten().filter(|e| e.file_name().to_string_lossy().ends_with(".meta")).count())
        .unwrap_or(0);
    if pending >= GS_SPOOL_CAP { trace(&format!("[gamestate] spool full ({pending}) — dropping {match_key}")); return; }

    let ts = gs_now_ms();
    let id = format!("{}_{}", match_key, reporter);
    let frames: Vec<serde_json::Value> = gs.frames.iter().map(|r| serde_json::json!([
        r.frame, r.p1_in, r.p2_in, r.kcode, r.hp, r.px, r.py, r.m1, r.m2, r.mfill, r.cd, r.cr,
        r.vx, r.vy, r.rhp, r.face, r.hitstun, r.act
    ])).collect();
    // the complete artifact that lands on disk (server writes the gunzip-able bytes verbatim)
    let assist_p1 = [gs.assist[0], gs.assist[2], gs.assist[4]];
    let assist_p2 = [gs.assist[1], gs.assist[3], gs.assist[5]];
    // Tier-3: the game's own per-set WINS tally — set_start (this game's start) + set_end (win-report). Each is
    // an Option<(u8,u8)> that serializes as [p1,p2] or null (a failed read → null), so old tapes / failed reads
    // are absent-safe. The server derives/auto-confirms the winner from the +1 delta (works for KO AND timeout).
    let set_start = gs.set_start;
    let record = serde_json::json!({
        "id": id, "match_key": match_key, "reporter": reporter, "side": side,
        "local_pn": gs.local_pn,   // raw localPlayerNum (0/1/255=unknown) — candidate side signal for offline validation
        "session_id": session_id, "match_index": match_index,   // gs-96: the ranked set this game belongs to
        "ver": env!("CARGO_PKG_VERSION"),   // gs-98: app build that recorded this (fixed vs pre-fix)
        "p1_team": p1_team, "p2_team": p2_team, "winner": winner, "loser": loser,
        "assist": gs.assist, "assist_p1": assist_p1, "assist_p2": assist_p2,
        "set_start": set_score_json(set_start), "set_end": set_score_json(set_end),   // Tier-3 set-score (KO+timeout); [p1,p2] or null
        "ts": ts, "schema": GS_SCHEMA,
        "frame_counter_addr": gs.frame_addr as u64, "synthetic_frames": gs.synthetic,
        "frame_count": frames.len(), "frames": frames,
    });
    let gz = gzip_bytes(&serde_json::to_vec(&record).unwrap_or_default());

    // "Only one person needs to upload." The designated uploader is the participant with the smaller
    // SteamID (both are 17-digit steamid64 → lexicographic == numeric). The other side waits a grace window
    // and only uploads if the designated one never did (offline). The server exists-check is the real backstop.
    let other = if reporter == winner { loser } else { winner };
    let designated = reporter < other;

    // envelope the uploader POSTs (frames_gz gets base64'd from the .gz at upload time) + spool bookkeeping.
    // Tier-3 set_start/set_end ride at the TOP LEVEL as [p1,p2] int arrays (or null) so the server can
    // auto-confirm the winner from the +1 delta without unzipping the frames.
    let meta = serde_json::json!({
        "match_key": match_key, "reporter": reporter, "side": side,
        "session_id": session_id, "match_index": match_index, "ver": env!("CARGO_PKG_VERSION"),
        "p1_team": p1_team, "p2_team": p2_team, "winner": winner, "loser": loser,
        "assist_p1": assist_p1, "assist_p2": assist_p2,
        "set_start": set_score_json(set_start), "set_end": set_score_json(set_end),
        "ts": ts, "schema": GS_SCHEMA,
        "designated": designated, "spool_ts": ts,
    });
    let base = format!("{}_{}", match_key, reporter);
    let _ = atomic_write(&dir.join(format!("{base}.json.gz")), &gz);
    let _ = atomic_write(&dir.join(format!("{base}.meta")), &serde_json::to_vec(&meta).unwrap_or_default());
    trace(&format!("[gamestate] spooled {} frames -> {base} (designated={designated})", frames.len()));
}

// Does the server already hold a recording for this match_key (either side)? Clients check this before
// uploading so a match is stored once. A network error returns false → we attempt the upload anyway (the
// server is idempotent per reporter, so a duplicate is harmless).
fn gs_exists_on_server(match_key: &str) -> bool {
    match ureq::get(&format!("{}/gamestate/exists?key={}", SKINSYNC, match_key))
        .timeout(std::time::Duration::from_secs(6)).call() {
        Ok(resp) => resp.into_json::<serde_json::Value>().ok()
            .and_then(|v| v.get("exists").and_then(|b| b.as_bool())).unwrap_or(false),
        Err(_) => false,
    }
}

// Drain the local spool: for each finished recording, dedup-check then POST. Runs ONLY between matches
// (GS_IN_MATCH is false) so it never competes with the game. Returns after the first match that starts.
fn drain_gs_cache() {
    use std::sync::atomic::Ordering::SeqCst;
    let dir = gs_cache_dir();
    let rd = match std::fs::read_dir(&dir) { Ok(r) => r, Err(_) => return };
    let now = gs_now_ms();
    for e in rd.flatten() {
        // a match just started, or sharing was turned off → stop immediately, resume next idle cycle.
        if GS_IN_MATCH.load(SeqCst) || !SHARE_GAMEPLAY.load(SeqCst) { return; }
        let fname = e.file_name().to_string_lossy().to_string();
        if !fname.ends_with(".meta") { continue; }
        let base = &fname[..fname.len() - 5];
        let meta_path = dir.join(&fname);
        let gz_path = dir.join(format!("{base}.json.gz"));
        let cleanup = || { let _ = std::fs::remove_file(&meta_path); let _ = std::fs::remove_file(&gz_path); };

        let meta: serde_json::Value = match std::fs::read_to_string(&meta_path).ok()
            .and_then(|t| serde_json::from_str(&t).ok()) { Some(v) => v, None => { cleanup(); continue; } };
        let key = meta.get("match_key").and_then(|v| v.as_str()).unwrap_or("");
        if key.is_empty() { cleanup(); continue; }
        let spool_ts = meta.get("spool_ts").and_then(|v| v.as_u64()).unwrap_or(0);
        let designated = meta.get("designated").and_then(|v| v.as_bool()).unwrap_or(true);

        // prune recordings stuck for over a week (server unreachable the whole time).
        if now.saturating_sub(spool_ts) > 7 * 24 * 3600 * 1000 { cleanup(); continue; }
        // non-designated side holds off ~90s so the designated uploader goes first (dedup below then wins).
        if !designated && now.saturating_sub(spool_ts) < 90_000 { continue; }
        // already on the server (the opponent uploaded it)? drop our copy.
        if gs_exists_on_server(key) { trace(&format!("[gamestate] {key} already on server — dropping local")); cleanup(); continue; }

        // upload: base64 the spooled gz and POST the envelope + frames_gz.
        let gz = match std::fs::read(&gz_path) { Ok(b) => b, Err(_) => { cleanup(); continue; } };
        let mut body = meta.clone();
        if let Some(o) = body.as_object_mut() { o.remove("designated"); o.remove("spool_ts"); o.insert("frames_gz".into(), serde_json::Value::from(b64_encode(&gz))); }
        match auth_post(SKINSYNC_GAMESTATE).timeout(std::time::Duration::from_secs(30)).send_json(body) {
            Ok(_) => { trace(&format!("[gamestate] uploaded {base} ({} bytes gz)", gz.len())); cleanup(); }
            Err(e) => { trace(&format!("[gamestate] upload {base} failed ({e}) — retry next cycle")); }
        }
    }
}

// Background uploader: drains the spool at startup and every ~20s, but only between matches. Own thread so
// the reader/UI never block on the network.
fn start_gamestate_uploader() {
    std::thread::spawn(|| {
        use std::sync::atomic::Ordering::SeqCst;
        std::thread::sleep(std::time::Duration::from_secs(6)); // let the app settle before the first drain
        loop {
            // P0.3: guard each drain so a panicking upload/parse can't kill the uploader thread.
            let guard = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                if SHARE_GAMEPLAY.load(SeqCst) && !GS_IN_MATCH.load(SeqCst) { drain_gs_cache(); }
            }));
            if guard.is_err() { trace("[gamestate] uploader cycle panicked — recovering, continuing"); }
            std::thread::sleep(std::time::Duration::from_secs(20));
        }
    });
}

pub(crate) fn is_wb(v: u32) -> bool { v >= WB_LO && v < WB_HI }

// Cheap re-validation of a cached base: >=5 of the 6 slots have a working-buffer DatPal pointer at
// cl+0x4c. That single fixed-offset pointer is the array's strongest cheap fingerprint (16k loose
// clusters exist, but only the real 6-run keeps a WB pointer at exactly +0x4c across every slot).
pub(crate) unsafe fn array_valid(h: &mem::Proc, base: usize) -> bool {
    if base == 0 { return false; }
    // >=5 WB DatPals AND no garbage health (>144). The health clause is essential: without it a STALE savestate
    // copy that still holds WB DatPals but reads garbage health passes validation, PINS ram_base, and
    // read_fighters then rejects it every cycle (health>144) → permanent "no gamestate" while find_array never
    // re-runs (ram_base != 0). Frozen copies with sane-but-stale health are handled separately by the liveness gate.
    (0..6).filter(|&i| is_wb(rpm_u32(h, base + i * STRIDE + OFF_DATPAL).unwrap_or(0))).count() >= 5
        && !(0..6).any(|i| (rpm_u32(h, base + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff) > HP_FULL as u32)
}

// ── ANCHOR: compute the live fighter array from flycast's guest-RAM reservation base ──────────────────
// flycast reserves the whole guest address space as one big RW block; the live MvC2 fighter array sits at a
// FIXED offset inside it (empirically STABLE across launches: reservation_base + 0x10b33fc8 landed exactly on
// the live array in every launch tested — 0x95e0000→0x1a113fc8 and 0x9760000→0x1a293fc8). The rollback netcode
// keeps ~14 savestate COPIES of the array, but they ALL share the SAME DatPals, so this one computed read
// paints correctly — no ~1GB find_array scan, no volatile-copy flicker, no drop. This is the performant anchor.
// (ARRAY_OFF = reservation_base + this fixed offset — defined in the ONE offsets table at the top of the file.)
// The reservation base: the >=128MB committed PAGE_READWRITE block that contains the working-buffer window
// (host 0x10000000). ASLR'd per launch, but found deterministically by region enumeration (no content scan).
unsafe fn flycast_base(h: &mem::Proc) -> usize {
    // The old predicate was `State==COMMIT && Protect == PAGE_READWRITE` (exact). For committed PRIVATE memory
    // that is EXACTLY `private && readable && writable && !executable` (a private commit can't be WRITECOPY), and
    // on Linux that is the guest reservation's `rw-p` anonymous mapping — same region, same semantics.
    for r in h.regions() {
        let (base, size) = (r.base, r.size);
        if r.private && r.readable && r.writable && !r.executable
            && size >= 0x0800_0000 && base <= 0x1000_0000 && 0x1000_0000 < base + size {
            return base;
        }
    }
    0
}
// The anchor: reservation_base + ARRAY_OFF, accepted when it holds a REAL roster (match-static char_ids).
// gs-71: DELIBERATELY NOT health-gated. The DatPals we paint through are shared + stable across every
// rollback copy, and char_ids don't change mid-match — so locking on the roster makes the anchor hold for
// the ENTIRE match, where a health gate flickered (the savestate at this fixed offset oscillates frame to
// frame → "any fighter 1..144" drops between frames → array unlatched → paint_slots emptied → skins blinked
// out; that was the "not applied right away / keeps un-applying" bug). Reject only the between-games
// [0,1,2,3,4,5] template. Health at this fixed offset is savestate-noisy — fine for painting; live
// health/score come from the find_array copy. O(1), no scan.
pub(crate) unsafe fn anchor_array(h: &mem::Proc) -> Option<usize> {
    let fb = flycast_base(h);
    if fb == 0 { return None; }
    let cand = fb + ARRAY_OFF;
    if !array_valid(h, cand) { return None; }
    // NEGATIVE GATE (live-capture-confirmed): reject a stale/half-written savestate copy at the fixed anchor
    // (any health > 144) so we fall back to find_array's strong locator instead of trusting a garbage copy.
    if (0..6).any(|i| (rpm_u32(h, cand + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff) > HP_FULL as u32) { return None; }
    let live = (0..6).any(|i| { let hp = rpm_u32(h, cand + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff; (1..=144).contains(&hp) });
    if !live { return None; }
    // MOTION GATE (capture-confirmed): the fixed anchor 0x10b33fc8 lands on a FROZEN savestate COPY (stuck at a
    // past frame — the whole bug). Only the live array's positions move frame-to-frame, so if the anchor is
    // identical across a short gap it's a frozen copy → reject it and let find_array's liveness locate take over.
    let pos = |c: usize| -> Vec<u8> { let mut v = Vec::new(); for i in 0..6 { if let Some(b) = read_at(h, c + i * STRIDE + OFF_POS_X, 0x40) { v.extend_from_slice(&b); } } v };
    let p1 = pos(cand); std::thread::sleep(std::time::Duration::from_millis(40)); let p2 = pos(cand);
    if !p1.is_empty() && p1 == p2 { return None; } // frozen → fall through to find_array
    Some(cand)
}
// The roster straight off the anchored array — NO scan. Ordered P1(slots 0,2,4) then P2(slots 1,3,5) so
// [0..3]=P1 and [3..6]=P2, matching the signature-scan roster it replaces. Returns the six real slots (so a
// mirror correctly reads 6, unlike the sig-scan's unique-dedup which broke the n>=6 "match" gate). Empty when
// the array isn't live → the caller falls back to the signature scan (which still covers character-select).
unsafe fn anchor_roster(h: &mem::Proc) -> Vec<Found> {
    let base = match anchor_array(h) { Some(b) => b, None => return Vec::new() };
    let (sigs, _) = sigtab();
    let mut out = Vec::new();
    for &i in &[0usize, 2, 4, 1, 3, 5] {
        let cid = rpm_u8(h, base + i * STRIDE + OFF_CHARID).unwrap_or(255) as u32;
        if cid > MAX_CID as u32 { continue; }
        let name = sigs.iter().find(|s| s.cid == cid).map(|s| s.name.clone()).unwrap_or_default();
        out.push(Found { cid, name, addr: base + i * STRIDE });
    }
    out
}

// Heavy (~1.25GB scan) — run only when the cached base is stale/missing AND fighters are loaded, throttled.
// Locates the array by the fighter-STRUCT LAYOUT (gs-89): for each 4-byte-aligned base, require >=5 of the 6
// slots (base + i*0x738) to hold a WB DatPal @+0x4c AND a valid char_id @+0x554, with BOTH sides (even/odd
// slots) carrying a living fighter (health 1..=144 @+0xb44). This is the invariant the external capture tool
// uses — it finds the live array every time; the OLD pointer-density heuristic (>=14 WB pointers clustered per
// slot) matched 0 real candidates in a live fight (find_array_replica confirmed). Returns the array base
// (volatile — never cache across matches blindly).
unsafe fn find_array(h: &mem::Proc) -> Option<usize> {
    const STRIDE_W: usize = STRIDE / 4;      // 0x738 in words
    const DP_W: usize  = OFF_DATPAL / 4;     // DatPal  @ +0x4c
    const CID_W: usize = OFF_CHARID / 4;     // char_id @ +0x554
    const HP_W: usize  = OFF_HEALTH / 4;     // health  @ +0xb44
    let need = HP_W.max(CID_W).max(DP_W) + 5 * STRIDE_W + 2;  // furthest word indexed from a base (+2 margin).
                                             // ⚠ MUST be the MAX field offset, not HP_W: once OFF_HEALTH moved to
                                             // 0x40c (< char_id 0x554), char_id became the furthest field — using
                                             // HP_W here indexed char_id past the buffer → OOB panic in find_array.
    let mut raw: Vec<usize> = Vec::new();
    for r in h.regions() {
        let base = r.base; let size = r.size;
        // include the ~512MB guest-RAM virtmem blocks (earlier scans wrongly capped at 256MB and missed them)
        if !(r.readable && size >= 0x10000 && size <= 0x5000_0000) { continue; }
        // Read in bounded CHUNKS: a whole-region read of a ~512MB..1.25GB block allocates that entire size at once
        // (read_at does vec![0u8; len]); find_array now runs frequently, so repeated giant allocations are an
        // OOM/abort hazard. 64MB base windows + a `tail` overlap (so a base near the window end can still index all
        // 6 slots) bound the allocation to ~80MB regardless of region size.
        const CHUNK: usize = 0x0400_0000;               // 64MB of base positions per read
        let tail = (need + 2) * 4;                       // bytes past a base to reach slot 5's health (+margin)
        let mut off = 0usize;
        while off + need * 4 < size {
            let rd = (CHUNK + tail).min(size - off);
            let buf = match read_at(h, base + off, rd) { Some(v) if v.len() == rd => v, _ => { off += CHUNK; continue; } };
            let words = buf.len() / 4;
            if words <= need { off += CHUNK; continue; }
            let word = |i: usize| -> u32 { u32::from_le_bytes([buf[i*4], buf[i*4+1], buf[i*4+2], buf[i*4+3]]) };
            // one pass → a per-word predicate byte (bit0=DatPal-WB, bit1=char_id-valid, bit2=health-alive)
            let pred: Vec<u8> = (0..words).map(|i| {
                let v = word(i); let mut p = 0u8;
                if is_wb(v) { p |= 1; }
                if (v & 0xff) <= MAX_CID as u32 { p |= 2; }
                let hp = v & 0xffff; if hp >= 1 && hp <= HP_FULL as u32 { p |= 4; }
                p
            }).collect();
            // process only CHUNK-worth of bases; the tail overlap supplied their slots. Last chunk: all that fit.
            let lim = (words - need).min(CHUNK / 4);
            let slot_present = |b: usize| (pred[b + DP_W] & 1) != 0 && (pred[b + CID_W] & 2) != 0;
            for b in 0..lim {
                // cheap early-reject: if BOTH slot 0 and slot 1 are absent, >=2 slots are missing → can't reach 5/6.
                if !slot_present(b) && !slot_present(b + STRIDE_W) { continue; }
                let mut present = 0u32; let (mut ev, mut od) = (false, false);
                for i in 0..6 {
                    let so = b + i * STRIDE_W;
                    if slot_present(so) {
                        present += 1;
                        if (pred[so + HP_W] & 4) != 0 { if i % 2 == 0 { ev = true; } else { od = true; } }
                    }
                }
                if present >= 5 && ev && od { raw.push(base + off + b * 4); }
            }
            off += CHUNK;
        }
    }
    if raw.is_empty() { return None; }
    raw.sort(); raw.dedup();
    // score + both-sides-alive (re-read live; the structured scan can match at a couple of neighbouring offsets).
    // even slot = P1, odd = P2; a side is "alive" if any of its fighters has real health (1..=144).
    let side_alive = |c: usize, par: usize| (0..6).filter(|&i| i % 2 == par)
        .any(|i| { let hp = rpm_u32(h, c + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff; (1..=144).contains(&hp) });
    let mut cands: Vec<(usize, usize)> = Vec::new();
    for &c in raw.iter() {
        // ★ NEGATIVE GATE (live-capture-confirmed): reject any candidate with an impossible health (>144) —
        // that's a stale/half-written savestate COPY (the live capture showed copies reading hp=11200/62807).
        if (0..6).any(|i| (rpm_u32(h, c + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff) > HP_FULL as u32) { continue; }
        let score = (0..6).filter(|&i| {
            let cl = c + i * STRIDE;
            is_wb(rpm_u32(h, cl + OFF_DATPAL).unwrap_or(0)) && (rpm_u32(h, cl + OFF_HEALTH).unwrap_or(0xffff) & 0xffff) <= HP_FULL as u32
        }).count();
        // ★ require BOTH teams to have a LIVING fighter — a frozen post-KO copy reads one whole side at 0.
        if score >= 5 && side_alive(c, 0) && side_alive(c, 1) { cands.push((c, score)); }
    }
    if cands.is_empty() { return None; }
    cands.sort_by(|a, b| b.1.cmp(&a.1));

    // ── FRAME-COUNTER live-copy selection (gs-97, the DEFINITIVE stale-read fix) ──
    // The rollback netcode keeps ~14 full savestate COPIES of guest RAM, each with the fighter array at the SAME
    // offset. The animation heuristic below can lock a re-simulating STALE copy and the reader then caches it for
    // a WHOLE match → systematically wrong health → inverted W/L for every game of a set (the Rychu04 8↔2 flip).
    // The LIVE copy is the one at the CURRENT frame: its frame counter is HIGHEST and ADVANCING; every savestate
    // holds an OLDER frame. The counter sits at a FIXED offset from the array (both live in guest RAM at fixed
    // guest offsets), so we locate that offset ONCE (cached) and then pick the candidate whose counter is highest
    // among those still advancing. This is immune to how many copies exist or where ASLR put them.
    static FC_REL: std::sync::atomic::AtomicI64 = std::sync::atomic::AtomicI64::new(0);
    let mut fc_rel = FC_REL.load(std::sync::atomic::Ordering::Relaxed);
    if fc_rel == 0 {
        // find the per-frame counter near a candidate (any copy with an advancing counter works — the offset is
        // shared across all copies). Try the top few by score so a frozen top candidate doesn't block discovery.
        for &(c, _) in cands.iter().take(5) {
            if let Some(fc) = hunt_frame_counter(h, c) { fc_rel = fc as i64 - c as i64; FC_REL.store(fc_rel, std::sync::atomic::Ordering::Relaxed); break; }
        }
    }
    if fc_rel != 0 {
        let fc_of = |c: usize| -> Option<u32> { rpm_u32(h, (c as i64 + fc_rel) as usize) };
        let t0: Vec<Option<u32>> = cands.iter().map(|&(c, _)| fc_of(c)).collect();
        std::thread::sleep(std::time::Duration::from_millis(120));
        let mut best: Option<(u32, usize)> = None;   // (frame_counter, base) — highest ADVANCING = the live copy
        for (i, &(c, _)) in cands.iter().enumerate() {
            if let (Some(a), Some(b)) = (t0[i], fc_of(c)) {
                if b > a && b != 0xffff_ffff && best.map_or(true, |(bb, _)| b > bb) { best = Some((b, c)); }
            }
        }
        if let Some((_, c)) = best { return Some(c); }
        // counter located but nothing advanced this instant (a lull between rounds) → fall through to animation.
    }

    // FALLBACK — animation probe (used until the frame counter is located, or in a lull): sample a wide per-fighter
    // region (position/velocity 0x61c + action/anim 0x100) across ~180ms and take the MOST-changed candidate; None
    // if nothing moved (never lock a frozen copy — the 0.1.25 best-effort-stale regression).
    let anim = |c: usize| -> Vec<u8> {
        let mut v = Vec::with_capacity(6 * 0x80);
        for i in 0..6 {
            if let Some(b) = read_at(h, c + i * STRIDE + OFF_POS_X, 0x40) { v.extend_from_slice(&b); }
            if let Some(b) = read_at(h, c + i * STRIDE + 0x100, 0x40) { v.extend_from_slice(&b); }
        }
        v
    };
    let before: Vec<Vec<u8>> = cands.iter().map(|&(c, _)| anim(c)).collect();
    std::thread::sleep(std::time::Duration::from_millis(180));
    let mut best: Option<(usize, usize)> = None;   // (change_count, base)
    for (i, &(c, _)) in cands.iter().enumerate() {
        if before[i].is_empty() { continue; }
        let after = anim(c);
        if after.is_empty() { continue; }
        let changed = before[i].iter().zip(after.iter()).filter(|(a, b)| a != b).count();
        if changed > 0 && best.map_or(true, |(bc, _)| changed > bc) { best = Some((changed, c)); }
    }
    best.map(|(_, c)| c)
}

// Cheap (~6 small reads/slot) — read the six fighters from a located base. side = slot parity (VALIDATED:
// even=P1, odd=P2); pos = C1/C2/C3 by pair. in_match is derived (any present fighter with live health):
// the array only exists once fighters are loaded, so this reliably distinguishes an active fight.
unsafe fn read_fighters(h: &mem::Proc, base: usize) -> Option<GameSt> {
    if base == 0 { return None; }
    let mut slots = Vec::new();
    let mut any_live = false;
    for i in 0..6 {
        let cl = base + i * STRIDE;
        let cid = rpm_u8(h, cl + OFF_CHARID).unwrap_or(255);
        if cid > MAX_CID { continue; } // not a live fighter slot
        let health = (rpm_u32(h, cl + OFF_HEALTH).unwrap_or(0) & 0xffff) as u16;
        // STRONG negative gate (naomi-re-expert): a real fighter's health is 0..=144. A value above that is a
        // stale/half-written savestate COPY (the hp=235 that produced frozen garbage tapes + inverted wins) —
        // reject the whole base so the caller re-locates onto the live mem_b array instead of a dead copy.
        if health > HP_FULL { return None; }
        if health > 0 { any_live = true; }
        let dp = rpm_u32(h, cl + OFF_DATPAL).unwrap_or(0);
        let mut pal = [0u8; 32];  // the fighter's live 16-colour palette (ARGB4444) at the DatPal target
        if is_wb(dp) { if let Some(v) = read_at(h, dp as usize, 32) { let n = v.len().min(32); pal[..n].copy_from_slice(&v[..n]); } }
        slots.push(GSlot {
            player: if i % 2 == 0 { 1 } else { 2 },  // even slot = P1, odd = P2
            pos: (i as u8 / 2) + 1,                  // (0,1)→C1 (2,3)→C2 (4,5)→C3
            char_id: cid,
            color: rpm_u8(h, cl + OFF_COLOR).unwrap_or(0),
            health,
            combo: (rpm_u32(h, cl + OFF_COMBO).unwrap_or(0) & 0xffff) as u16,   // combo this fighter is dealing
            datpal: dp,
            pal,
            addr: cl,
        });
    }
    if slots.is_empty() { return None; }
    let meter1 = rpm_u8(h, base + MET_BARS).unwrap_or(0);           // P1 bars (global, relative to array base)
    let meter2 = rpm_u8(h, base + MET_BARS + 1).unwrap_or(0);       // P2 bars (adjacent, per DC layout)
    // ── battle-globals (gs-99): the game's own match/round state (ground truth for W/L) ──
    let phase       = rpm_u8(h, base + OFF_PHASE).unwrap_or(0);
    let win_result  = rpm_u8(h, base + OFF_WINRESULT).unwrap_or(0);
    let round_no    = rpm_u8(h, base + OFF_ROUND).unwrap_or(0);
    let bg_in_match = rpm_u8(h, base + OFF_BG_INMATCH).unwrap_or(0);
    let bg_timer    = rpm_u8(h, base + OFF_BG_TIMER).unwrap_or(0) as u32;
    Some(GameSt { in_match: if any_live { 1 } else { 0 }, match_state: phase, stage: 0, timer: bg_timer, frame: 0, ram: base, slots, meter1, meter2,
                  phase, win_result, round_no, bg_in_match })
}

// ── POINTER-FOLLOW locator (gs-98) — THE fix for the array-alignment inversion ──────────────────────────
// The game keeps a pointer to the CURRENT match block at a FIXED exe global, right beside kcode/localPlayerNum.
//   fighter_array = *(exe + 0xac6ef0) + 0x3f24
// Confirmed live across 3 relocations AND every mode (training/arcade/ranked). This is the PRIMARY locator: no
// ~1GB scan, and — crucially — NO one-STRIDE alignment ambiguity. The old find_array scan matched the fighter
// block at TWO offsets one STRIDE (0x738) apart (true base vs base+0x738), so it randomly picked the SHIFTED
// copy → swapped even/odd → flipped P1/P2 → inverted the W/L. Following the pointer lands on the true base every
// time. Same win cures the stale-copy skin flicker: this is the live block, never a rollback ghost.
// (MATCH_PTR_OFF / MATCH_ARR_ADD are defined in the ONE offsets table at the top of the file.)
// ── char-select picks (gs-100) ──────────────────────────────────────────────────────────────────────
// game_state = *(exe+0xacd3a0) (an exe-fixed global, e.g. 0x140ac6d40). During character select the LOCKED
// picks land at game_state+0x758 as a stride-4 char_id list (-1 = slot not yet locked); a parallel
// [char_id, assist] stride-8 array sits at +0x6b4. Confirmed live: Iron Man(0x33)+Sentinel(0x34) appeared at
// +0x758 the instant they were locked (the cursor HOVER is a grid coord and does NOT write here — only locks
// do). Reading this gives instant team detection BEFORE the fighter array exists, for skin preload + display.
// (GSTATE_PTR_OFF / PICKS_OFF are defined in the ONE offsets table at the top of the file.)
/// Read your char-select LOCKED picks (the 3-char team at game_state+0x758; `0xffffffff` = slot not yet locked).
/// SELF-GATING (no netplay dependency, so it fires on MATCH 1 with no delay): surfaces ONLY during an ACTIVE
/// partial selection — ≥1 char locked AND ≥1 slot still unlocked. A settled state (all 3 locked, or a stale
/// menu team with no in-team -1) returns empty, so we never flash a stale team here — the live fighter array
/// drives menus/matches. Cheap: one pointer deref + one 12-byte read.
unsafe fn read_char_picks(h: &mem::Proc, exe_base: usize) -> Vec<u8> {
    if exe_base == 0 { return Vec::new(); }
    let gs = match read_at(h, exe_base + GSTATE_PTR_OFF, 8).filter(|b| b.len() >= 8) {
        Some(b) => u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]) as usize,
        None => return Vec::new(),
    };
    if gs < 0x10000 { return Vec::new(); }
    let b = match read_at(h, gs + PICKS_OFF, 3 * 4) { Some(b) if b.len() >= 12 => b, _ => return Vec::new() };
    let mut picks = Vec::new();
    for i in 0..3 {
        let v = u32::from_le_bytes([b[i*4], b[i*4+1], b[i*4+2], b[i*4+3]]);
        if v <= 0x3A { picks.push(v as u8); }           // a locked character (0xffffffff = not yet locked → skipped)
    }
    picks   // NO -1 requirement (a fully-locked team has no in-team -1). The CALLER gates on scene==5 && no live
            // fighters (= char-select), so a settled menu/in-fight state never surfaces a stale team here.
}
unsafe fn pointer_follow_array(h: &mem::Proc, exe_base: usize) -> Option<usize> {
    if exe_base == 0 { return None; }
    let blk = read_at(h, exe_base + MATCH_PTR_OFF, 8)
        .filter(|b| b.len() >= 8)
        .map(|b| u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]))? as usize;
    if blk == 0 { return None; }
    let arr = blk.checked_add(MATCH_ARR_ADD)?;
    if arr < 0x10000 || arr > 0x7fff_ffff_ffff { return None; }
    if !array_valid(h, arr) { return None; }
    // LIVENESS (mirrors find_array's animation gate): between matches the pointer still holds the LAST match's
    // now-FROZEN block. Only accept a block that's actually advancing, so we never surface a stale match — and
    // so a truly-frozen read falls through to the scan (which also returns None when frozen), never to a wrong
    // alignment. Sample position(+0x61c) + action/anim(+0x100) across ~70ms.
    let snap = |a: usize| -> Vec<u8> {
        let mut v = Vec::with_capacity(6 * 0x80);
        for i in 0..6 {
            if let Some(b) = read_at(h, a + i * STRIDE + OFF_POS_X, 0x40) { v.extend_from_slice(&b); }
            if let Some(b) = read_at(h, a + i * STRIDE + 0x100, 0x40) { v.extend_from_slice(&b); }
        }
        v
    };
    let s0 = snap(arr);
    std::thread::sleep(std::time::Duration::from_millis(70));
    let s1 = snap(arr);
    if s0.is_empty() || s0 == s1 { return None; }   // frozen/unreadable → let the caller fall back to the scan
    Some(arr)
}

// gs-101 OVERKILL: pointer-follow with NO liveness sleep. Used ONLY when scene==5 (game_state+0x8) already
// GUARANTEES we're in a live fight, so the game's own match-block pointer necessarily points at the current
// (rendered) block — never a frozen savestate. Pure O(1): two reads + a validate, microseconds, no scan.
unsafe fn pointer_follow_fast(h: &mem::Proc, exe_base: usize) -> Option<usize> {
    if exe_base == 0 { return None; }
    let blk = read_at(h, exe_base + MATCH_PTR_OFF, 8)
        .filter(|b| b.len() >= 8)
        .map(|b| u64::from_le_bytes([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7]]))? as usize;
    if blk == 0 { return None; }
    let arr = blk.checked_add(MATCH_ARR_ADD)?;
    if arr < 0x10000 || arr > 0x7fff_ffff_ffff { return None; }
    if !array_valid(h, arr) { return None; }
    Some(arr)
}

// Self-contained gamestate read used by BOTH the hook path and the RPM fallback. Opens its own read-only
// handle, re-validates (or re-finds, throttled) the volatile array base, then does the cheap per-fighter
// read. `allow_find` gates the heavy scan to when fighters are likely loaded (sig-scan roster non-empty).
fn read_gamestate_rpm(pid: u32, ram_base: &mut usize, last_find: &mut std::time::Instant, fighting: bool, live_ctx: bool, hint: usize) -> Option<GameSt> {
    if pid == 0 { return None; }
    let proc = mem::Proc::open_read(pid)?;
    let h = &proc;
    let out = unsafe {
        if *ram_base != 0 && !array_valid(h, *ram_base) { *ram_base = 0; }       // volatile → dropped
        // ANCHOR (gs-70): compute the array from flycast's reservation base + ARRAY_OFF when we don't already
        // have a base. NOT primary — reverted from gs-71, which forced this static-anchor copy every cycle and
        // regressed cross-round painting (at a round reload the anchor copy's DatPal pointers go null/stale while
        // find_array's ANIMATING copy still tracks the live render). So: anchor to acquire O(1), then the
        // liveness gate below hands off to find_array's animating copy if this one freezes.
        // PRIMARY locator: the struct-layout scan. The fighter array is VOLATILE on this build — it RELOCATES
        // every match (the external logger confirmed a different base per game: 0x15f5.., 0x1815.., 0x1625..), so
        // the fixed anchor below CANNOT track it. Worse, running the anchor first STARVED the scan: the anchor set
        // ram_base to a stale copy, so find_array (gated on ram_base==0) never ran → game 1 read garbage and
        // games 2..N read nothing (the "1 of 10 recorded" bug). So scan FIRST, throttled so the ~1GB read doesn't
        // thrash; once found, array_valid keeps it cached cheaply until the array relocates.
        // gs-101 OVERKILL LOCATOR: pointer-ONLY, scene-gated. scene==5 (fighting) GUARANTEES the block is live, so
        // we O(1) pointer-follow it (only when ram_base is missing) — NO struct-layout scan, NO liveness sleep, NO
        // 1200ms throttle. Between fights (fighting=false) we never even look: there is no live array, so ram_base
        // stays 0 and the reader correctly shows no gamestate. This removes the LAST heavy scan from the hot path.
        if *ram_base == 0 {
            if fighting {
                // scene==5 GUARANTEES the block is live → O(1) pointer, no liveness sleep, no scan.
                *ram_base = pointer_follow_fast(h, game_exe_base(pid)).unwrap_or(0);
            } else if live_ctx {
                // In a match context but not the fight frame (KO / win-pose / results / loading). Use the
                // liveness-CHECKED pointer (70ms anim gate) so we still capture the KO frame + never pin a frozen
                // between-match copy — still NO struct-layout scan. Not the FPS-critical path, so the gate is fine.
                *ram_base = pointer_follow_array(h, game_exe_base(pid)).unwrap_or(0);
            }
            if *ram_base != 0 { trace(&format!("[find] located live array @ {:x} (ptr)", *ram_base)); }
        }
        let _ = last_find;
        // The fixed-anchor + last-base(hint) fallbacks are REMOVED. On this build the array RELOCATES every match
        // (traces show a different, sometimes HIGH, base per game — 0x7ff9..), so the fixed anchor points at
        // nothing or at a STALE savestate copy. BETWEEN matches (no live fight) that stale copy is exactly the
        // "scan brings in a random Ryu" bug + inverted W/L (the copy holds a previous round's dead team). So
        // find_array (most-animating, None when nothing moves) is the SOLE locator: during a fight it returns the
        // live copy; between fights it returns None → the reader shows no gamestate (correct) instead of stale data.
        let _ = hint;
        // read_fighters returns None on a garbage/empty base (health>144 or no valid fighter slots). Drop the base
        // in that case so the NEXT cycle re-acquires (anchor → find_array) instead of pinning a dead base forever —
        // the second half of the "no gamestate" deadlock (a base array_valid accepts but read_fighters rejects).
        if *ram_base != 0 {
            match read_fighters(h, *ram_base) { Some(g) => Some(g), None => { *ram_base = 0; None } }
        } else { None }
    };
    out
}

// Publish the per-fighter DatPal map for the in-process hook: one line per fighter
//   "<slot> <side> <char_id> <datpal_hexaddr> <health>"
// so the hook can read each fighter's palette in-process and correlate its guest DatPal ADDRESS with the
// D3D atlas position it lands at (→ per-side / mirror painting). Written only while fighters are loaded;
// cleared to empty otherwise so the hook never keys off stale addresses. Read-only w.r.t. game memory.
fn write_fighters(game: &Option<GameSt>) {
    let body = match game {
        Some(g) if !g.slots.is_empty() => g.slots.iter().enumerate()
            .map(|(i, s)| format!("{} {} {} {:08x} {} {:x}", i, s.player, s.char_id, s.datpal, s.health, s.addr))
            .collect::<Vec<_>>().join("\n"),
        _ => String::new(),
    };
    let _ = std::fs::write(crate::runtime_dir().join("fighters.txt"), body);
}


// ── Per-SET score, computed from KO events (no need to find the game's own score variable) ──
// A ranked set is many games vs the SAME opponent, so we key the score to the sticky opponent SteamID
// and reset when it changes. We watch each team's aliveness (any fighter with health > 0): when a team
// gets wiped while the other survives, that's a game win. We catch it both at the KO edge (still in
// match) and as a fallback from the last-known aliveness if the match ends before we sample the edge.
#[derive(Default)]
struct ScoreState { set_opp: Option<String>, p1: u32, p2: u32, was_in: bool, la1: bool, la2: bool, judged: bool,
    // a game is only SCORED if we actually observed it CONTESTED (both teams alive at the same time). This
    // rejects frozen/stale buffers where one side reads permanently dead — which otherwise phantom-judges a
    // win every cycle (the exact bug in the trace: P2 read all-0 forever → endless P1 "wins").
    saw_both: bool,
    // per-GAME rich-stat trackers (reset when a fresh game starts): did side take any damage; was side ever
    // down to 1 char while the opponent still had all 3.
    g1_dmg: bool, g2_dmg: bool, g1_low: bool, g2_low: bool,
    // per-GAME rich logging: teams (char_ids per side, captured live), biggest combo each side dealt, and
    // meter bars spent each side (sum of bar-count decreases). Reset when a fresh game starts.
    teams: Option<(Vec<u8>, Vec<u8>)>, g1_maxcombo: u16, g2_maxcombo: u16,
    g1_met: u32, g2_met: u32, last_m1: u8, last_m2: u8, met_init: bool,
    // Games finished BEFORE the side was confirmed — held here (never recorded) and committed the moment the user
    // confirms their side (the "never record a guess" gate). Cleared with the rest on a new opponent.
    pending: Vec<PendingGame>,
    // CONFIRMED-KO debounce: pend_w = the side that looks KO-winner right now (a team FULLY dead), pend_n =
    // consecutive cycles it has held. We only record once pend_n reaches 2 — that rides out the speculative
    // rollback frame the app used to judge from (logger-proven: the array shows the RIGHT winner once settled).
    pend_w: u8, pend_n: u32,
    // ── SESSION (ranked set) ── a unique id per set (vs one opponent), HARD-capped at SESSION_CAP games (the 11th
    // opens a fresh session), persisted to disk so an app restart mid-set RESUMES it, and stamped onto every result
    // + recording so each match is tied to its set → per-session stats. match_index = games committed this session.
    session_id: Option<String>, match_index: u32, session_started_ms: u64 }

const SESSION_CAP: u32 = 10;                    // a ranked set is at most 10 games; the 11th opens a new session
fn session_file() -> std::path::PathBuf { crate::runtime_dir().join("mvc_session.txt") }

// Unique per set: reporter + opponent + start-ms (+ a cheap nonce so two sets vs the same opp in the same ms differ).
fn new_session_id(my_id: u64, opp_id: &str) -> String {
    let ms = gs_now_ms();
    let nonce = ms.rotate_left(17) ^ (opp_id.len() as u64).wrapping_mul(0x9e37_79b9_7f4a_7c15);
    format!("s_{}_{}_{:x}", my_id, opp_id, ms ^ (nonce & 0xffff))
}
fn save_session(st: &ScoreState) {
    let (Some(sid), Some(opp)) = (st.session_id.as_deref(), st.set_opp.as_deref()) else { return };
    let body = serde_json::json!({ "opp": opp, "session_id": sid, "p1": st.p1, "p2": st.p2,
        "match_index": st.match_index, "started_ms": st.session_started_ms });
    let _ = std::fs::write(session_file(), serde_json::to_vec(&body).unwrap_or_default());
}
fn load_session() -> Option<serde_json::Value> {
    std::fs::read_to_string(session_file()).ok().and_then(|s| serde_json::from_str(&s).ok())
}

// A finished game held until the side is confirmed. winner = the side (1/2) that won; my_side is resolved at commit.
#[derive(Clone)]
struct PendingGame { winner: u8, opp: (String, String), ocv: bool, perfect: bool, comeback: bool, rich: GameRich,
    session_id: String, match_index: u32 }

// Rich per-game payload for logging (both teams + combat stats). Winner/loser & my/opp are resolved downstream.
#[derive(Clone, Default)]
struct GameRich { p1_team: Vec<u8>, p2_team: Vec<u8>, p1_combo: u16, p2_combo: u16, p1_met: u32, p2_met: u32,
    origin: String }
fn rich_of(st: &ScoreState) -> GameRich {
    let (p1_team, p2_team) = st.teams.clone().unwrap_or_default();
    GameRich { p1_team, p2_team, p1_combo: st.g1_maxcombo, p2_combo: st.g2_maxcombo, p1_met: st.g1_met, p2_met: st.g2_met,
        origin: detect_origin() }
}

// GAME MODE origin, captured at the KO moment (rich_of runs only in the game-end judgment, so this is one
// lobby read per finished game — and a buffered pending game keeps the origin from when it was PLAYED, not
// when the side-confirm flush finally reports it). "lobby" = the live session says we're in a Steam lobby
// (host or member — read_my_lobby covers both); everything else is ranked matchmaking. The server treats
// this as a CLAIM: tournament/money stamping and the ranked-eligibility decision stay server-side.
fn detect_origin() -> String {
    let l = read_my_lobby();
    if l.get("in_lobby").and_then(|v| v.as_bool()).unwrap_or(false) { "lobby".into() } else { "ranked".into() }
}

// ── PERSISTENT HEAD-TO-HEAD RECORD (C:\g\records.json, keyed by opponent SteamID) ──────────────────
// A "game" is won when one side's whole team is KO'd (all fighters health→0). We attribute it to YOU via
// the deterministic side (local_side: 1=P1, 2=P2; 0=unknown → skip, don't guess). Accumulates across sets.
fn record_result(steamid: &str, name: &str, i_won: bool) {
    if steamid.is_empty() || steamid == "0" { return; }
    let mut r = std::fs::read_to_string(crate::runtime_dir().join("records.json")).ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = r.as_object_mut() {
        let e = obj.entry(steamid.to_string()).or_insert_with(|| serde_json::json!({"name": "", "wins": 0, "losses": 0}));
        if !name.is_empty() { e["name"] = serde_json::json!(name); }
        let k = if i_won { "wins" } else { "losses" };
        let c = e[k].as_u64().unwrap_or(0); e[k] = serde_json::json!(c + 1);
    }
    let _ = std::fs::write(crate::runtime_dir().join("records.json"), serde_json::to_string_pretty(&r).unwrap_or_default());
    trace(&format!("[record] {} vs {} ({steamid})", if i_won { "WIN" } else { "LOSS" }, name));
}
// Is `nm` a plausible gamertag vs memory junk? The SteamID scan sometimes glues a random ASCII run next to a
// SteamID-shaped value (URLs like "googleapis.com", UI fragments like "…you while waiting for opponent"). We
// refuse to record a result against anything that clearly isn't a handle, so garbage never hits the board.
fn plausible_opponent_name(nm: &str) -> bool {
    let s = nm.trim();
    let nchars = s.chars().count();
    if nchars < 3 || nchars > 32 { return false; }            // Steam persona cap is 32 CHARS (count, not bytes —
                                                              //   a CJK/emoji handle is many bytes but few chars)
    if s.matches(' ').count() > 2 { return false; }           // gamertags aren't sentences
    if s.chars().any(|c| "<>{}[]|=\\^~`".contains(c)) { return false; }  // symbol junk (e.g. "cjU>") isn't a gamertag
    let low = s.to_lowercase();
    // URL/file fragments AND game/UI/netcode strings the scan keeps grabbing (title, menus, log lines).
    for bad in [".com", ".net", ".org", ".io", ".gg", "http", "www.", "://", ".dll", ".exe", ".dat", "googleapi",
                "marvel", "capcom", "heroes", "new age", "session", "exiting", "waiting", "opponent", "loading",
                "connect", "matchmak", "lobby", "player", "press", "select", "steam"] {
        if low.contains(bad) { return false; }
    }
    // ≥3 letter/digit chars, Unicode-aware: CJK/accented/cyrillic handles count; ★/emoji/punctuation don't.
    s.chars().filter(|c| c.is_alphanumeric()).count() >= 3
}

// A finished game: record the local per-opponent H2H AND report it to the global leaderboard. The rich-stat
// flags (ocv/perfect/comeback) always describe the WINNER — computed symmetrically from both sides' health,
// so we credit them correctly whether we won or lost.
fn on_game_win(winner: u8, opp: &Option<(String, String)>, my_side: u8, ocv: bool, perfect: bool, comeback: bool, rich: &GameRich, session_id: &str, match_index: u32) {
    if my_side != 1 && my_side != 2 { return; }
    // Belt-and-suspenders: NEVER record unless the side is confirmed (manual toggle / deterministic lock). The
    // fuzzy auto-detectors set local_side for the UI label only — a confidently-WRONG side must never post stats.
    if !snapshot().lock().unwrap().side_confirmed { trace("[record] SKIP — side not confirmed (buffering)"); return; }
    let (opp_id, opp_name) = match opp { Some(o) => (o.0.clone(), o.1.clone()), None => return };
    // The SteamID scan is noisy — refuse to attribute a game to an opponent whose co-located name is clearly
    // memory junk (a real fix for the identity is still needed; this just stops the garbage getting recorded).
    if !plausible_opponent_name(&opp_name) {
        trace(&format!("[record] SKIP implausible opponent \"{}\" ({}) — not a gamertag", opp_name, opp_id));
        return;
    }
    let i_won = winner == my_side;
    record_result(&opp_id, &opp_name, i_won);                 // local per-opponent H2H (unchanged)
    let (my_id_num, my_name) = self_ident();
    if my_id_num == 0 { return; }
    let my_id = my_id_num.to_string();
    let reporter = my_id.clone();   // consensus: we report as OURSELVES; server counts only when BOTH sides do
    let (winner_id, winner_name, loser_id, loser_name) =
        if i_won { (my_id, my_name, opp_id, opp_name) } else { (opp_id, opp_name, my_id, my_name) };
    // teams + combat stats always describe the WINNER's side (symmetric, credited correctly whether we won or lost)
    let (winner_team, loser_team, winner_combo, winner_met) = if winner == 1 {
        (rich.p1_team.clone(), rich.p2_team.clone(), rich.p1_combo, rich.p1_met)
    } else {
        (rich.p2_team.clone(), rich.p1_team.clone(), rich.p2_combo, rich.p2_met)
    };
    // Attach the per-frame recording of THIS game (recency-guarded so a late pending-flush can't grab a
    // later game's buffer). p1_team/p2_team are the fixed sides (not winner/loser) so the recording keeps
    // the on-screen P1/P2 orientation; `my_side` labels which side is the local reporter.
    let gs = gamestate_snapshot();
    // Tier-3: read the game's OWN set-score at win-report time (set_end). set_start rode in on the snapshot.
    // Only bother when a recording exists (otherwise nothing gets spooled, so the read would be wasted work
    // and a needless reader-thread pause). Read-only + guarded → a bad read is simply absent in the envelope.
    let set_start = gs.as_ref().and_then(|g| g.set_start);
    let set_end = if gs.is_some() { read_set_end(set_start) } else { None };
    report_result_server(reporter, winner_id, winner_name, loser_id, loser_name, ocv, perfect, comeback,
        winner_team, loser_team, winner_combo, winner_met,
        my_side, rich.p1_team.clone(), rich.p2_team.clone(), gs, session_id.to_string(), match_index, set_end,
        rich.origin.clone());
}

// Tier-3: read the set-score at win-report time with a SHORT retry. The HUD "WINS" tally can update a frame
// or two AFTER the KO resolves, so re-read (≤3 tries, ~50ms between) until it's a clean +1 over set_start on
// exactly ONE side, then stop; if it never lands clean, take whatever the last successful read was (the
// server treats a non-clean delta as inconclusive and falls back). Opens its own read-only handle; ANY
// failure → None. Panic-safe: every read is Option-returning (read_set_score never panics). Additive only.
fn read_set_end(set_start: Option<(u8, u8)>) -> Option<(u8, u8)> {
    let pid = find_game_pid()?;
    let proc = mem::Proc::open_read(pid)?;
    let h = &proc;
    let exe = game_exe_base(pid);
    let clean = |s: (u8, u8), e: (u8, u8)| {
        let (d1, d2) = (e.0 as i32 - s.0 as i32, e.1 as i32 - s.1 as i32);
        (d1 == 1 && d2 == 0) || (d1 == 0 && d2 == 1)   // exactly one side bumped by +1 → a clean game-over delta
    };
    let mut out: Option<(u8, u8)> = None;
    for i in 0..3 {
        if let Some(cur) = unsafe { read_set_score(h, exe) } {
            out = Some(cur);
            if set_start.map_or(false, |s| clean(s, cur)) { break; }
        }
        if i < 2 { std::thread::sleep(std::time::Duration::from_millis(50)); }
    }
    out
}

// Fire-and-forget POST of a finished game to the skinsync leaderboard (own thread so the reader never blocks
// on the network). The server dedupes so the same game reported by both players counts once. The server now
// RETURNS the consensus `key` it derived for this result — we reuse that EXACT key to correlate the game-state
// recording (so a recording joins its metadata AND both players' recordings of one game share one match_key).
fn report_result_server(reporter: String, winner: String, winner_name: String, loser: String, loser_name: String,
                        ocv: bool, perfect: bool, comeback: bool,
                        winner_team: Vec<u8>, loser_team: Vec<u8>, biggest_combo: u16, meters_used: u32,
                        // game-state recording context (uploaded only if share_gameplay_data + a recording exists)
                        side: u8, p1_team: Vec<u8>, p2_team: Vec<u8>, gs: Option<GsSnapshot>,
                        session_id: String, match_index: u32, set_end: Option<(u8, u8)>, origin: String) {
    std::thread::spawn(move || {
        use std::sync::atomic::Ordering::SeqCst;
        // ── TRAY: "Pause reporting" gate. While PAUSED we send NOTHING for this finished game — neither the
        // /result POST nor the per-frame recording upload below. Local scoring/H2H already ran in on_game_win.
        if PAUSED.load(Ordering::Relaxed) { return; }
        // gs-105 frame-derived per-match stats from the recording (BOTH teams — hp/red_hp state is global, and hp
        // 0..144 is roster-comparable per the MvC2 spec). Non-zero only when a recording exists (share-gameplay on).
        // Keyed to the WINNER's side so the server attributes w*→winner, l*→loser (symmetric, no dedup issue):
        //  • chip = PEAK recoverable(red) health on the opponent at one moment (a MAX, bounded ≤432) — NOT a
        //    sum of frame rises: red-hp oscillates (recovers off-screen, jumps on char-swap) + tapes span
        //    multiple games, so summing rises over-counts wildly (saw 27k). Peak is the honest, bounded read.
        //  • comeback = the WINNER's max character-count deficit overcome (loser doesn't "come back").
        //  (damage-dealt has no clean source — MvC2 keeps no cumulative damage counter — so its board is retired.)
        let winner_side: u8 = if winner == reporter { side } else { 3 - side };
        let (wdmg, ldmg, wchip, lchip, wcomeback): (u32, u32, u32, u32, u8) = gs.as_ref().map(|g| {
            let ws: [usize; 3] = if winner_side == 1 { [0, 2, 4] } else { [1, 3, 5] };
            let ls: [usize; 3] = if winner_side == 1 { [1, 3, 5] } else { [0, 2, 4] };
            let (mut wchip, mut lchip) = (0u32, 0u32);
            let mut comeback = 0i32;
            for f in &g.frames {
                // peak recoverable on each team (winner's chip pressure = peak red on the loser's team)
                let l_red: u32 = ls.iter().map(|&s| f.rhp[s] as u32).sum();
                if l_red > wchip { wchip = l_red; }
                let w_red: u32 = ws.iter().map(|&s| f.rhp[s] as u32).sum();
                if w_red > lchip { lchip = w_red; }
                let wa = ws.iter().filter(|&&s| f.hp[s] > 0).count() as i32;
                let la = ls.iter().filter(|&&s| f.hp[s] > 0).count() as i32;
                if la - wa > comeback { comeback = la - wa; }
            }
            (0u32, 0u32, wchip.min(432), lchip.min(432), comeback.max(0) as u8)
        }).unwrap_or((0, 0, 0, 0, 0));
        let body = serde_json::json!({
            "reporter": reporter.clone(), "winner": winner.clone(), "loser": loser.clone(),
            "winner_name": winner_name, "loser_name": loser_name,
            "ocv": ocv, "perfect": perfect, "comeback": comeback,
            "winner_team": winner_team, "loser_team": loser_team, "biggest_combo": biggest_combo, "meters_used": meters_used,
            // gs-105 frame-derived per-side stats (0 when no recording): damage dealt, chip dealt, winner's comeback
            "wdmg": wdmg, "ldmg": ldmg, "wchip": wchip, "lchip": lchip, "wcomeback": wcomeback,
            "side": side,   // gs-92: which side the reporter was (1=P1,2=P2) — makes every game auditable server-side
            "session_id": session_id, "match_index": match_index,   // gs-96: tie each game to its ranked set (≤10 games)
            "ver": env!("CARGO_PKG_VERSION"),   // gs-98: which app build recorded this — so we can tell fixed vs pre-fix
            "origin": origin, // GAME MODE claim ("ranked"|"lobby", read at the KO): the server stamps tournament/
                              // money server-side and decides ranked-eligibility (lobby needs both season-registered)
        });
        // capture the server-derived match_key from the /result response (single source of truth → both
        // players consense on ONE key, and each tags its own recording with it).
        let key: Option<String> = match auth_post(&format!("{}/result", SKINSYNC))
            .timeout(std::time::Duration::from_secs(5)).send_json(body) {
            Ok(resp) => resp.into_json::<serde_json::Value>().ok()
                .and_then(|v| v.get("key").and_then(|k| k.as_str()).map(|s| s.to_string())),
            Err(_) => None,
        };
        // ── upload the per-frame recording (gated on the consent setting + a fresh recording) ──
        if !SHARE_GAMEPLAY.load(SeqCst) { return; }
        let gs = match gs { Some(g) => g, None => return };
        let key = match key { Some(k) if !k.is_empty() => k, _ => { trace("[gamestate] no match_key returned — skipping recording upload"); return; } };
        spool_gamestate(&key, &reporter, side, &p1_team, &p2_team, &winner, &loser, &gs, &session_id, match_index, set_end);
        trace(&format!("[gamestate] spooled {} frames as {}_{} (uploads between matches)", gs.frames.len(), key, reporter));
    });
}

// Record a finished game now if the side is confirmed, else BUFFER it (the "never record a guess" gate).
fn commit_or_buffer(st: &mut ScoreState, winner: u8, opp: &Option<(String, String)>, confirmed: bool, my_side: u8,
                    ocv: bool, perfect: bool, comeback: bool, rich: GameRich, session_id: String, match_index: u32) {
    if confirmed { on_game_win(winner, opp, my_side, ocv, perfect, comeback, &rich, &session_id, match_index); }
    else if let Some(o) = opp { st.pending.push(PendingGame { winner, opp: o.clone(), ocv, perfect, comeback, rich, session_id, match_index }); }
}

// Stamp the CURRENT game with (session_id, its index in the set), then advance the counter + persist. Called once
// per judged game so the 11th game rolls a new session (via the cap check in update_score) and a restart resumes.
fn session_stamp(st: &mut ScoreState) -> (String, u32) {
    let sid = st.session_id.clone().unwrap_or_default();
    let mi = st.match_index;
    st.match_index = st.match_index.saturating_add(1);
    save_session(st);
    (sid, mi)
}

fn update_score(st: &mut ScoreState, game: &Option<GameSt>, opp: &Option<(String, String)>, my_side: u8, confirmed: bool) {
    let cur = opp.as_ref().map(|o| o.0.clone());
    // Reset the set ONLY for a genuinely different, present opponent. A transient None (opponent momentarily
    // undetected between games / long char-select) must NOT wipe the set score — hold it until a real,
    // different SteamID actually appears.
    if let Some(cur_id) = cur {
        if st.set_opp.as_deref() != Some(cur_id.as_str()) {
            *st = ScoreState { set_opp: Some(cur_id.clone()), ..Default::default() };
            // RESUME the same running set after an app restart mid-session (same opponent, still under the cap) so
            // the score + session id pick up where they left off; otherwise mint a fresh session for this set.
            if let Some(v) = load_session() {
                if v.get("opp").and_then(|x| x.as_str()) == Some(cur_id.as_str())
                    && (v.get("match_index").and_then(|x| x.as_u64()).unwrap_or(SESSION_CAP as u64)) < SESSION_CAP as u64 {
                    st.session_id = v.get("session_id").and_then(|x| x.as_str()).map(String::from);
                    st.p1 = v.get("p1").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
                    st.p2 = v.get("p2").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
                    st.match_index = v.get("match_index").and_then(|x| x.as_u64()).unwrap_or(0) as u32;
                    st.session_started_ms = v.get("started_ms").and_then(|x| x.as_u64()).unwrap_or(0);
                }
            }
            if st.session_id.is_none() {
                let (my_id, _) = self_ident();
                st.session_id = Some(new_session_id(my_id, &cur_id));
                st.session_started_ms = gs_now_ms();
            }
            save_session(st);
        }
    }
    // Side just got confirmed → flush the games we buffered this set, in order, with the now-known side.
    if confirmed && !st.pending.is_empty() {
        for pg in std::mem::take(&mut st.pending) {
            on_game_win(pg.winner, &Some(pg.opp), my_side, pg.ocv, pg.perfect, pg.comeback, &pg.rich, &pg.session_id, pg.match_index);
        }
    }
    match game {
        Some(g) => {
            let alive    = |p: u8| g.slots.iter().any(|s| s.player == p && s.health > 0);
            let alive_ct = |p: u8| g.slots.iter().filter(|s| s.player == p && s.health > 0).count();
            let took_dmg = |p: u8| g.slots.iter().any(|s| s.player == p && s.health < HP_FULL);
            let (a1, a2) = (alive(1), alive(2));
            if g.in_match == 1 {
                if a1 && a2 {
                    // fresh game beginning (both teams back up after the last KO) → reset per-game trackers
                    if st.judged { st.g1_dmg = false; st.g2_dmg = false; st.g1_low = false; st.g2_low = false;
                        st.g1_maxcombo = 0; st.g2_maxcombo = 0; st.g1_met = 0; st.g2_met = 0; st.met_init = false; st.teams = None;
                        // ── SESSION HARD CAP ── the set just reached SESSION_CAP games → the game NOW starting opens
                        // a NEW session (rolled lazily at the next start so the completed set's score stays visible).
                        if st.match_index >= SESSION_CAP {
                            if let Some(opp_id) = st.set_opp.clone() {
                                let (my_id, _) = self_ident();
                                st.session_id = Some(new_session_id(my_id, &opp_id));
                                st.session_started_ms = gs_now_ms();
                                st.match_index = 0; st.p1 = 0; st.p2 = 0; st.pend_w = 0; st.pend_n = 0;
                                save_session(st);
                            }
                        }
                    }
                    st.judged = false;
                    st.saw_both = true;                        // a genuine CONTESTED game is in progress
                }
                // accumulate per-game rich-stat signals while the game is live
                if took_dmg(1) { st.g1_dmg = true; }
                if took_dmg(2) { st.g2_dmg = true; }
                if alive_ct(1) == 1 && alive_ct(2) == 3 { st.g1_low = true; }
                if alive_ct(2) == 1 && alive_ct(1) == 3 { st.g2_low = true; }
                // capture teams + combat stats live (for rich per-game logging)
                if st.teams.is_none() {
                    let p1t: Vec<u8> = g.slots.iter().filter(|s| s.player == 1).map(|s| s.char_id).collect();
                    let p2t: Vec<u8> = g.slots.iter().filter(|s| s.player == 2).map(|s| s.char_id).collect();
                    if !p1t.is_empty() && !p2t.is_empty() { st.teams = Some((p1t, p2t)); }
                }
                let mc1 = g.slots.iter().filter(|s| s.player == 1).map(|s| s.combo).max().unwrap_or(0);
                let mc2 = g.slots.iter().filter(|s| s.player == 2).map(|s| s.combo).max().unwrap_or(0);
                if mc1 > st.g1_maxcombo { st.g1_maxcombo = mc1; }
                if mc2 > st.g2_maxcombo { st.g2_maxcombo = mc2; }
                if !st.met_init { st.last_m1 = g.meter1; st.last_m2 = g.meter2; st.met_init = true; }
                if g.meter1 < st.last_m1 { st.g1_met += (st.last_m1 - g.meter1) as u32; }   // bars spent = decreases
                if g.meter2 < st.last_m2 { st.g2_met += (st.last_m2 - g.meter2) as u32; }
                st.last_m1 = g.meter1; st.last_m2 = g.meter2;
                // CONFIRMED-KO winner: one team FULLY dead (no fighter alive) while the other still has one. Require
                // it to HOLD for 2 cycles (pend_n>=2) so the speculative rollback frame — where the wrong team
                // briefly reads dead — is never recorded. Once rollback settles the array shows the true winner
                // (logger-proven). cur_w: 1 = P1(even) won, 2 = P2(odd) won, 0 = no KO (both alive or both dead).
                // ── gs-99 GROUND-TRUTH WINNER. Primary = HEALTH (which team is FULLY dead at the KO — proven since
                // 0.1.43, unambiguous at the KO frame). win_result (array+0x2e61a: 0x00=P1/even won→1, 0x01=P2/odd→2,
                // 0xFF=draw) is a FALLBACK for the frames health can't resolve. ⚠ The battle-globals `phase` @ +0
                // reads a POINTER on Steam (the DC page's leading fields are pointers here — LAW 1 only holds from
                // the meter onward, meter-confirmed), so we do NOT gate on phase. The "not both-teams-alive" guard
                // IS the gate: win_result is consulted only once a team is dead (a real KO), never mid-fight, so no
                // stale "opens 0-1/1-0" count slips in. DISAGREE logging flags any win_result-vs-health drift.
                let hp_w = if !a1 && a2 { 2u8 } else if !a2 && a1 { 1u8 } else { 0u8 };
                let wr_w = if !(a1 && a2) { match g.win_result { 0 => 1u8, 1 => 2u8, _ => 0u8 } } else { 0u8 };
                if wr_w != 0 && hp_w != 0 && wr_w != hp_w {
                    trace(&format!("[winres] DISAGREE win_result→P{} vs health→P{} (wr={:#04x} round={})", wr_w, hp_w, g.win_result, g.round_no));
                }
                let cur_w = if hp_w != 0 { hp_w } else { wr_w };   // PREFER proven health; win_result fills gaps only
                if cur_w != 0 && cur_w == st.pend_w { st.pend_n = st.pend_n.saturating_add(1); }
                else { st.pend_w = cur_w; st.pend_n = if cur_w != 0 { 1 } else { 0 }; }
                if !st.judged && st.saw_both && cur_w != 0 && st.pend_n >= 2 {
                    st.judged = true; let r = rich_of(st); let (sid, mi) = session_stamp(st);
                    if cur_w == 2 { st.p2 += 1; let (o, p, c) = (alive_ct(2) == 3, !st.g2_dmg, st.g2_low); commit_or_buffer(st, 2, opp, confirmed, my_side, o, p, c, r, sid, mi); }
                    else          { st.p1 += 1; let (o, p, c) = (alive_ct(1) == 3, !st.g1_dmg, st.g1_low); commit_or_buffer(st, 1, opp, confirmed, my_side, o, p, c, r, sid, mi); }
                }
                st.la1 = a1; st.la2 = a2; st.was_in = true;
            } else if st.was_in && !st.judged && st.saw_both { // match-flag off before we confirmed in-frame → settle from the pending KO (the round is over, so its last state is settled)
                if st.pend_w != 0 && st.pend_n >= 1 {
                    st.judged = true; let r = rich_of(st); let (sid, mi) = session_stamp(st);
                    if st.pend_w == 1 { st.p1 += 1; let (p, c) = (!st.g1_dmg, st.g1_low); commit_or_buffer(st, 1, opp, confirmed, my_side, false, p, c, r, sid, mi); }
                    else { st.p2 += 1; let (p, c) = (!st.g2_dmg, st.g2_low); commit_or_buffer(st, 2, opp, confirmed, my_side, false, p, c, r, sid, mi); }
                } else { trace(&format!("[record] MISS(match-end) — no KO seen (pend_w={} pend_n={}) → dropped (under-count)", st.pend_w, st.pend_n)); }
                st.was_in = false; st.saw_both = false; st.pend_w = 0; st.pend_n = 0;
            } else { st.was_in = g.in_match == 1; if g.in_match != 1 { st.saw_both = false; } }
        }
        None => {   // game data gone (liveness gate / match over): settle from the pending KO (round is over → settled)
            if st.was_in && !st.judged && st.saw_both && st.pend_w != 0 && st.pend_n >= 1 {
                st.judged = true; let r = rich_of(st); let (sid, mi) = session_stamp(st);
                if st.pend_w == 1 { st.p1 += 1; let (p, c) = (!st.g1_dmg, st.g1_low); commit_or_buffer(st, 1, opp, confirmed, my_side, false, p, c, r, sid, mi); }
                else { st.p2 += 1; let (p, c) = (!st.g2_dmg, st.g2_low); commit_or_buffer(st, 2, opp, confirmed, my_side, false, p, c, r, sid, mi); }
            }
            st.was_in = false; st.saw_both = false; st.pend_w = 0; st.pend_n = 0;
        }
    }
}

pub fn report_live_match(opp: String, my_chars: Vec<i64>, opp_chars: Vec<i64>) {
    if opp.len() != 17 || !opp.bytes().all(|b| b.is_ascii_digit()) { return; } // real SteamID only
    let body = serde_json::json!({ "opp": opp, "my_chars": my_chars, "opp_chars": opp_chars });
    let _ = auth_post(&format!("{}/match/live", SKINSYNC))
        .timeout(std::time::Duration::from_secs(5))
        .send_json(body); // fire-and-forget: errors intentionally ignored
}

fn trace(msg: &str) {
    use std::io::Write;
    let path = crate::runtime_dir().join("suite_trace.log");
    if std::fs::metadata(&path).map(|m| m.len() > 1_000_000).unwrap_or(false) { let _ = std::fs::write(&path, b""); }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0);
        let _ = writeln!(f, "{:.3} {}", t, msg);
    }
}
fn trace_cycle(prev: &mut String, src: &str, state: &str, roster: &[Found], opp: &Option<(String, String)>, game: &Option<GameSt>, score: (u32, u32)) {
    let cids: Vec<String> = roster.iter().map(|f| f.cid.to_string()).collect();
    let (inm, ms, hp) = match game {
        Some(g) => (g.in_match as i32, g.match_state as i32,
                    g.slots.iter().map(|s| format!("p{}c{}:id{}hp{}", s.player, s.pos, s.char_id, s.health)).collect::<Vec<_>>().join(" ")),
        None => (-1i32, -1i32, String::from("(no gamestate)")),
    };
    let oppd = opp.as_ref().map(|o| format!("{} \"{}\"", o.0, o.1)).unwrap_or_else(|| "-".into());
    let line = format!("[{}] state={} in_match={} mstate={} roster=[{}] opp={} score={}-{} hp:{}",
        src, state, inm, ms, cids.join(","), oppd, score.0, score.1, hp);
    if line != *prev { *prev = line.clone(); trace(&line); }
}

pub(crate) unsafe fn read_at(h: &mem::Proc, addr: usize, len: usize) -> Option<Vec<u8>> {
    h.read(addr, len)
}

fn roster_ids(r: &[Found]) -> Vec<u32> { r.iter().map(|f| f.cid).collect() }

// All sig occurrences in committed readable regions overlapping [lo,hi), via RPM (crash-safe: RPM
// returns an error on bad memory — it never faults the game or us, unlike in-process pointer reads).
unsafe fn rpm_occurrences(h: &mem::Proc, lo: usize, hi: usize) -> Vec<(usize, u32, String)> {
    let (sigs, buckets) = sigtab();
    let mut occ = Vec::new();
    for r in h.regions() {
        let base = r.base; let size = r.size;
        if r.readable && base < hi && base + size > lo {
            let a = base.max(lo); let b = (base + size).min(hi);
            if let Some(buf) = read_at(h, a, b - a) {
                if buf.len() >= 64 {
                    let end = buf.len() - 64;
                    let mut i = 0;
                    while i <= end {
                        for &si in &buckets[buf[i] as usize] {
                            let s = &sigs[si];
                            if buf[i..i + 64] == s.bytes { occ.push((a + i, s.cid, s.name.clone())); }
                        }
                        i += 1;
                    }
                }
            }
        }
    }
    occ
}

// The LOADED team(s) = the working-buffer copies the game makes per match. Each is a small address
// cluster of <= 12 distinct chars (never the ~56-distinct resident ROM). A 3v3 puts BOTH teams' six
// chars in memory, but the two sides can land in SEPARATE clusters > 4 MB apart — so we must union
// EVERY non-resident cluster, not just the densest one (picking one silently dropped a whole team →
// "only 1-2 of 3 chars"). Layout-independent — works wherever ASLR put the guest RAM this launch.
fn pick_working(mut occ: Vec<(usize, u32, String)>) -> Vec<Found> {
    occ.sort_by_key(|o| o.0);
    // segment into clusters by the 4 MB gap; a "working" cluster has 1..=12 distinct chars
    // (the resident ROM's ~56 distinct is excluded; it's packed tight so it stays one cluster).
    let mut clusters: Vec<(usize, usize, usize)> = Vec::new(); // (lo_idx, len, distinct)
    let mut i = 0;
    while i < occ.len() {
        let mut j = i + 1;
        while j < occ.len() && occ[j].0 - occ[j - 1].0 <= 0x40_0000 { j += 1; }
        let d = occ[i..j].iter().map(|x| x.1).collect::<std::collections::HashSet<_>>().len();
        if (1..=12).contains(&d) { clusters.push((i, j - i, d)); }
        i = j;
    }
    // union all working clusters (first-seen addr per cid wins), densest first so a cap keeps the
    // most-likely-real team. Cap at 8: a 3v3 is 6 distinct; more than 8 means the resident ROM split
    // across the gap and is leaking in — fall back to just the single densest cluster (old behaviour).
    clusters.sort_by(|a, b| b.2.cmp(&a.2));
    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for &(lo, len, _) in &clusters {
        for k in lo..lo + len { if seen.insert(occ[k].1) { out.push(Found { cid: occ[k].1, name: occ[k].2.clone(), addr: occ[k].0 }); } }
    }
    if out.len() > 8 {
        out.clear(); seen.clear();
        if let Some(&(lo, len, _)) = clusters.first() {
            for k in lo..lo + len { if seen.insert(occ[k].1) { out.push(Found { cid: occ[k].1, name: occ[k].2.clone(), addr: occ[k].0 }); } }
        }
    }
    out.sort_by_key(|f| f.addr);
    out
}

// Game module base (Windows: Toolhelp Module32; Linux: first exe mapping ~0x140000000). Thin wrapper so
// every call site (game_exe_base(pid)) is unchanged.
fn game_exe_base(pid: u32) -> usize { mem::exe_base(pid) }

// ── Anchor persistence ── the heap-located addresses (fighter-array base, opponent session region, roster
// region) are ASLR'd PER GAME-LAUNCH but stable for the game's whole run. Persisting them means an APP restart
// (game still running) skips every cold scan → instant. All loads are VALIDATED downstream (array_valid / the
// WARM pairing scan / the roster re-scan), so a stale file after a game relaunch just falls back to one scan.
fn save_anchors(pid: u32, ram: usize, opp: Option<(usize, usize)>, work: Option<(usize, usize)>) {
    let (ob, os) = opp.unwrap_or((0, 0)); let (wl, wh) = work.unwrap_or((0, 0));
    let _ = std::fs::write(crate::runtime_dir().join("mvc_anchors.txt"), format!("{:x} {:x} {:x} {:x} {:x} {:x}", pid, ram, ob, os, wl, wh));
}
fn load_anchors() -> (u32, usize, Option<(usize, usize)>, Option<(usize, usize)>) {
    let s = std::fs::read_to_string(crate::runtime_dir().join("mvc_anchors.txt")).unwrap_or_default();
    let v: Vec<usize> = s.split_whitespace().filter_map(|x| usize::from_str_radix(x, 16).ok()).collect();
    if v.len() >= 6 {
        (v[0] as u32, v[1], if v[2] != 0 && v[3] != 0 { Some((v[2], v[3])) } else { None },
                            if v[4] != 0 && v[5] != 0 { Some((v[4], v[5])) } else { None })
    } else { (0, 0, None, None) }
}

fn u16le(b: &[u8], o: usize) -> u16 { (b[o] as u16) | ((b[o + 1] as u16) << 8) }

// LIVENESS: a live match's fighter animation changes every frame. Hash a volatile slice of each fighter's
// struct; if it's byte-identical across reader cycles the buffer is FROZEN (menus / match over / a stale
// base still pointing at an old match), so we must NOT report it as a live match — that is the root of the
// "detects old matches" bug. Returns 0 if nothing readable.
fn game_liveness_hash(pid: u32, game: &GameSt) -> u64 {
    let proc = match mem::Proc::open_read(pid) { Some(p) => p, None => return 0 };
    let h = &proc;
    let mut hh = 0xcbf2_9ce4_8422_2325u64;
    let mut any = false;
    for s in &game.slots {
        if s.addr != 0 {
            if let Some(chunk) = unsafe { read_at(h, s.addr + 0x100, 0xC0) } {     // action/animation region
                for b in &chunk { hh = (hh ^ *b as u64).wrapping_mul(0x0000_0100_0000_01b3); }
                any = true;
            }
        }
    }
    if any { hh } else { 0 }
}

/// The single reader thread. Reads the game's memory DIRECTLY via read-only RPM (no hook, no IPC files) —
/// roster / side / opponent / health all come from cross-process reads on this one thread, so all heavy
/// work is OFF the Tauri IPC path and no command can ever block the UI. Spawned once at app startup.
pub fn start_reader() {
    // NOTE: the old input-correlation side detectors (churn-based start_side_detector and +0x4fc-based
    // start_inputdec_detector) were REMOVED — the +0x4fc field is side-agnostic so inputdec always locked P1,
    // which inverted the stats. Side now comes DETERMINISTICALLY from the session-struct pairing (P1's SteamID
    // is stored above P2's), set in the reader loop.
    load_share_setting();            // restore the gameplay-data sharing consent (beta default = on)
    load_auth();                     // restore the registration token (attached to every write request)
    // silent auto-registration: the moment the local SteamID is readable (Steam registry, no game needed),
    // register + cache the token so writes are authed from the first launch — zero user interaction.
    std::thread::spawn(|| {
        for _ in 0..40 {
            let (id, _) = self_ident();
            if id != 0 { let _ = ensure_registered(id.to_string()); if auth_token().is_some() { break; } }
            std::thread::sleep(std::time::Duration::from_secs(3));
        }
    });
    start_gamestate_capture();       // dedicated fast thread: auto-records full per-frame state during matches
    start_gamestate_uploader();      // drains the recording spool between matches (dedup'd, never during a fight)
    std::thread::spawn(|| {
        let mut cur_pid: u32 = 0;
        // ── TRAY decouple: these three replace the webview-driven presence heartbeat + live-match broadcast.
        // The app called sync_heartbeat / report_live_match from JS on timers; with no webview the reader drives
        // them itself (direct HTTP). Cadence mirrors the app: heartbeat ~60s (< server's 75s ONLINE window),
        // live-match ~20s keepalive per opponent (server TTL 60s).
        let mut last_hb = std::time::Instant::now() - std::time::Duration::from_secs(60);
        let mut live_rep_last = std::time::Instant::now() - std::time::Duration::from_secs(60);
        let mut live_rep_opp = String::new();
        let mut side_seen: u8 = 0;       // gs-77: localPlayerNum debounce — last side value read
        let mut side_stable: u32 = 0;    // consecutive reads of the SAME side; confirm only when stable (kills the stale-read first-match flash)
        let mut handle: Option<mem::Proc> = None;   // dropping/reassigning this closes the previous handle
        let mut roster: Vec<Found> = Vec::new();
        let mut stable: u32 = 0;
        let mut work: Option<(usize, usize)> = None; // located team region (cheap-tracked between relocates)
        let mut empty_streak: u32 = 0;               // consecutive empty track cycles before a wide relocate
        let mut opp: Option<(String, String)> = None;
        let mut opp_backoff: i32 = 0;
        let mut opp_pending: Option<String> = None;  // a DIFFERENT candidate id; must persist 2 scans to swap (anti-flip)
        let mut opp_addr: Option<(usize, u8, String, u64)> = None; // cached (session-slot, side, name, opp_id) → instant re-reads; opp_id lets us detect a CHANGED opponent
        let mut opp_region: Option<(usize, usize)> = None; // cached session REGION → warm re-locks skip the 2GB sweep (per-launch stable)
        let mut in_session = false;                   // live netplay pairing present (fast "in a match" signal)
        let mut opp_lost: Option<std::time::Instant> = None; // when the pairing first went missing while holding an opp → set-over grace
        let mut exe_base = 0usize;                     // game module base (for localPlayerNum @ exe+LOCALPLAYER_OFF)
        let mut sess_key = String::new();
        let mut ss = ScoreState::default();          // per-set score, keyed to the sticky opponent
        let mut last_active = std::time::Instant::now(); // last time fighters were loaded / in a match
        let mut prev_live_hash = 0u64; let mut frozen_cycles = 0u32; // liveness gate (drop frozen/stale match data)
        let mut prev_log = String::new();            // last trace line (log only on change)
        let mut last_find = std::time::Instant::now() - std::time::Duration::from_secs(10); // find_array throttle
        let mut live_seen: Option<std::time::Instant> = None; // last cycle we had a LIVE array read → keeps find_array re-acquiring through rollback flicker, and gates the deterministic side lock
        let mut ram_base: usize = 0;                 // located player-array base (0 = not yet found; volatile per match)
        // ★ persisted anchors (keyed to the game pid): an app restart while the SAME game is running restores them
        // in the pid-change block below → skips ALL cold scans. Every restored value is validated downstream, so a
        // stale file (game relaunched → different pid) is simply ignored and we scan once.
        let (anchor_pid, anchor_ram, anchor_opp, anchor_work) = load_anchors();
        let mut saved_anchors: (usize, Option<(usize, usize)>, Option<(usize, usize)>) = (0, None, None);
        let mut last_good_base: usize = 0;           // sticky fighter-array base → reused across matches (no re-scan)
        const OUT_TIMEOUT: u64 = 150;                // sec fully-gone before dropping the SESSION opponent — long
                                                     // enough to survive a slow char-select / loading BETWEEN GAMES
                                                     // of a set (so the teams/opponent don't blink away mid-set); a
                                                     // DIFFERENT opponent still switches instantly, and it's hidden
                                                     // at a true menu, so a stale name never actually shows.
        loop {
            // ── TRAY: presence heartbeat (was the webview's sync_heartbeat on a 60s timer). Runs regardless of
            // game state (presence = "any open app"). Spawned so a slow POST never stalls the reader cycle.
            // Gated by "Pause reporting" (tray): while PAUSED we send no presence at all (last_hb is left un-reset
            // so an unpause fires the heartbeat immediately).
            if !PAUSED.load(Ordering::Relaxed) && last_hb.elapsed().as_secs() >= 55 {
                last_hb = std::time::Instant::now();
                let (id, name) = self_ident();
                if id != 0 {
                    std::thread::spawn(move || {
                        if let Ok(v) = sync_heartbeat(id.to_string(), if name.is_empty() { "Player".into() } else { name }) {
                            if let Some(n) = v.get("online").and_then(|x| x.as_u64()) {
                                agent_status().lock().unwrap().online = n as u32;
                            }
                        }
                    });
                }
            }
            // (re)acquire the process handle; drop it if the game is gone
            match find_game_pid() {
                Some(p) => {
                    if p != cur_pid || handle.is_none() {
                        handle = mem::Proc::open_read(p);   // reassignment drops+closes any previous handle
                        cur_pid = p; roster.clear(); work = None; opp = None; opp_addr = None; opp_region = None; in_session = false; opp_lost = None; sess_key.clear(); ram_base = 0; exe_base = game_exe_base(p);
                        // SAME game as our persisted anchors → restore them (skip cold scans on an app restart)
                        if p == anchor_pid { ram_base = anchor_ram; opp_region = anchor_opp; work = anchor_work; }
                        last_good_base = ram_base;   // sticky base = restored anchor (same game) or 0 (new game)
                    }
                    // T2: the render-hook auto-inject (do_inject_hook) is the painter/host-driver path (T3/T4) —
                    // not part of the reader, so it's intentionally NOT ported here. `p` is used only to (re)open
                    // the handle above.
                    let _ = p;
                }
                None => {
                    handle = None;   // drops+closes the previous handle
                    cur_pid = 0; roster.clear(); work = None; opp = None; opp_addr = None; opp_region = None; in_session = false; opp_lost = None; ss = ScoreState::default();
                    { let mut s = snapshot().lock().unwrap(); s.state = "game_off".into(); s.roster.clear(); s.opponent = None; s.game = None; s.score = (0, 0); s.paint_slots.clear(); }
                    { let mut a = agent_status().lock().unwrap(); a.game_running = false; a.in_session = false; a.state = "game_off".into(); a.opponent = None; a.score = (0, 0); a.reporting = false; }
                    if prev_log != "GAME_OFF" { prev_log = "GAME_OFF".into(); trace("[game_off] game closed → cleared roster/opponent/score"); }
                    std::thread::sleep(std::time::Duration::from_millis(1000));
                    continue;
                }
            }
            let h = match handle.as_ref() { Some(h) => h, None => { std::thread::sleep(std::time::Duration::from_millis(1000)); continue; } };

            // P0.3: guard the ENTIRE per-cycle body (all game-memory reads + parsing + the snapshot publish) so
            // one panicking frame can't kill the reader/detection/painting thread — it logs and continues to the
            // next cycle (mirrors the server's per-request catch_unwind). Real Result errors below are untouched.
            let cycle = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            // roster + mode — LAYOUT-INDEPENDENT (robust to per-launch ASLR of the guest RAM):
            // cheaply re-scan the located team region each cycle; only if it stays empty for 2 cycles do
            // a bounded wide relocate. The wide scan therefore never fires mid-match (buffers are stable
            // there) — it only runs at menus/match-start, so it can't hitch live gameplay.
            // ★ ROSTER via SIGNATURE, not the +0x554 char_id. The point char's +0x554 misreads as 0=Ryu,
            // so anchor_roster (which reads +0x554) planted phantom Ryus in ~38% of recorded teams. The
            // fingerprint scan (pick_working ⟵ rpm_occurrences) reads characters by their DAT signature —
            // immune to that misread — and was the ORIGINAL, reliable source. It was swapped to anchor_roster
            // purely to drop the 1 GB wide relocate from the hot path; the fix keeps the fingerprint source but
            // BOUNDS it to the located array's region (~MBs — the same bounded scan that already ran every cycle
            // at char-select, so its cost is proven). anchor_roster survives only as a last-resort so the
            // opponent still surfaces in the brief window before the region is bounded (may carry a phantom Ryu).
            let mut team = if let Some((lo, hi)) = work {
                pick_working(unsafe { rpm_occurrences(h, lo, hi) })
            } else { Vec::new() };
            if !team.is_empty() {
                empty_streak = 0;
                if let (Some(f), Some(l)) = (team.first(), team.last()) {
                    work = Some((f.addr.saturating_sub(0x10_0000), l.addr + 0x10_0000)); // track region drift
                }
            } else {
                empty_streak += 1;
                if work.is_none() || empty_streak >= 2 {
                    team = pick_working(unsafe { rpm_occurrences(h, 0x0200_0000, 0x4000_0000) });
                    work = match (team.first(), team.last()) {
                        (Some(f), Some(l)) => Some((f.addr.saturating_sub(0x10_0000), l.addr + 0x10_0000)),
                        _ => None,
                    };
                    empty_streak = 0;
                }
                if team.is_empty() { team = unsafe { anchor_roster(h) }; } // last-resort only
            }
            let n = team.len();
            let same = roster_ids(&team) == roster_ids(&roster);
            if same && n > 0 { stable = stable.saturating_add(1); } else { stable = 1; }
            // in_session (live netplay pairing) forces at least "select" even before fighters load, so the
            // opponent surfaces the instant the match forms rather than after the 6-fighter roster stabilizes.
            let state = if n >= 6 && stable >= 2 { "match" } else if n > 0 || in_session { "select" } else { "menu" }.to_string();
            roster = team;

            // opponent: STICKY across a set. Looked for only while fighters are loaded (n>0). Once locked we
            // HOLD it — a DIFFERENT candidate must appear in TWO consecutive scans before we swap, so a single
            // between-games ranking wobble can never flip the opponent (which used to reset the set score). A
            // sustained out-of-match stretch (set over / matchmaking) clears it via the OUT_TIMEOUT below, which
            // re-enables an immediate fresh lock for the next opponent.
            let _ = &sess_key;
            // OPPONENT / SESSION — runs REGARDLESS of roster. The netplay pairing forms at loading/character-select,
            // BEFORE fighters load (nethunt found it while in_match=-1), so this is the earliest, deterministic
            // "we're in an online match" signal. When the session slot is cached the check is a single 8-byte read
            // (cheap → effectively every cycle for responsive liveness); only the COLD full scan is paced by backoff.
            if opp_addr.is_some() || opp_backoff <= 0 {
                let my_id = read_self_id().unwrap_or(0);
                // ranked (netplay pairing geometry) FIRST; hosted-lobby MemberInfo scan as the ADDITIVE fallback
                // (returns None instantly outside a hosted lobby). Both feed the SAME opp_addr cache + downstream
                // flow, so the sticky-opponent / side / /peers logic below is identical for ranked and lobby.
                let resolved = find_opponent_netplay(cur_pid, my_id, &mut opp_addr, &mut opp_region);
                let resolved = resolved.or_else(|| find_opponent_lobby(cur_pid, my_id, exe_base, &mut opp_addr));
                match resolved {
                    Some((oid, onm, oside)) => {
                        // DETERMINISTIC → lock immediately (no anti-flip). Cached slot makes re-validation near-free.
                        let sid = oid.to_string();
                        let changed = opp.as_ref().map(|o| o.0 != sid).unwrap_or(false);
                        // ⚠ The address-position side rule (P1's id above P2's) was DISPROVEN live: user was P2 with
                        // their id at BOTH the higher (vs Love_Guru) and lower (vs Duc) address across sessions. So
                        // we do NOT auto-confirm from `oside` — side stays on the manual gate until a REAL signal
                        // (flycast localPlayerNum) lands. New opponent → require fresh confirmation.
                        let _ = oside;
                        if changed { let mut s = snapshot().lock().unwrap(); s.manual_side = 0; s.side_confirmed = false; }
                        let cur_nm = opp.as_ref().map(|o| o.1.clone()).unwrap_or_default();
                        opp = Some((sid, if onm.is_empty() { cur_nm } else { onm }));
                        opp_pending = None;
                        in_session = true;
                        opp_lost = None;                       // pairing present → session alive
                        opp_backoff = if opp_addr.is_some() { 1 } else { 10 };   // cached → re-check next cycle (cheap); cold → pace the scan
                    }
                    None => {
                        opp_addr = None; in_session = false;
                        if opp.is_some() {
                            // Pairing GONE while we hold an opponent. The connection stays alive BETWEEN GAMES of a
                            // set, so a genuine absence = DISCONNECTED / set over. The fast path now re-validates the
                            // pairing, so a None here is trustworthy → short 2s grace (rides out one transient miss).
                            if opp_lost.is_none() { opp_lost = Some(std::time::Instant::now()); }
                            if opp_lost.map_or(false, |t| t.elapsed().as_secs() >= 2) {
                                opp = None; opp_addr = None; opp_lost = None;   // SET OVER → looking. KEEP opp_region:
                                // the session region is per-launch stable, so the NEXT opponent re-locks via a cheap
                                // WARM region scan instead of a full COLD sweep.
                            }
                            opp_backoff = 2;                   // re-check quickly to confirm the disconnect
                        } else {
                            opp_lost = None; opp_backoff = 3;  // looking for a match → pace the cold scan
                        }
                    }
                }
            }
            if opp_backoff > 0 { opp_backoff -= 1; }

            // ★ DETERMINISTIC SIDE is resolved AFTER the liveness gate below — it needs a LIVE fighter read
            // (game.is_some()), which is the only signal that's both fresh (mid-fight → localPlayerNum is THIS
            // match's) and independent of the laggy pairing scan + flickering roster. Just resolve the module base
            // here so it's ready.
            if exe_base == 0 && cur_pid != 0 { exe_base = game_exe_base(cur_pid); }   // module base for localPlayerNum

            // ── gs-101: SCENE STATE (game_state+0x8; 5 = actively fighting) ── the master screen id (the game's own
            // dispatcher gates match-load on ==5; confirmed live). We use it as an FPS GUARD: while scene==5 the
            // fight frame must do ZERO heavy work, so every expensive scan is blocked and only the tiny per-cycle
            // health/state reads run. Cheap: one pointer deref + one 4-byte read.
            let scene = if exe_base != 0 {
                unsafe { read_at(h, exe_base + GSTATE_PTR_OFF, 8) }
                    .filter(|b| b.len() >= 8)
                    .map(|b| u64::from_le_bytes([b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7]]) as usize)
                    .filter(|&gs| gs > 0x10000)
                    .and_then(|gs| unsafe { read_at(h, gs + 0x8, 4) })
                    .map(|b| i32::from_le_bytes([b[0],b[1],b[2],b[3]]))
                    .unwrap_or(-1)
            } else { -1 };
            let fighting = scene == 5;

            // Game state: auto-find + read the reversed player array via read-only RPM. The heavy find is
            // attempted only when fighters are loaded (n>0) and throttled; once found, the volatile base is
            // re-validated & read cheaply.
            // allow_find is broadened PAST the flickering sig-scan roster: the fixed anchor lands on frozen/garbage
            // savestate copies mid-rollback → anchor_roster empties (n=0) → the old `n>0` gate starved find_array
            // EXACTLY when it was needed (the "reads flash on/off, no wins recorded" bug). Once we've seen a live
            // array recently (live_seen) OR pairing is up, keep letting find_array re-acquire the real live copy.
            // The latch expires ~20s after the last live read so idle menus never thrash the ~1GB scan.
            // gs-101: the array locator is now pointer-ONLY + scene-gated INSIDE read_gamestate_rpm. Pass `fighting`
            // (scene==5) → it O(1) pointer-follows the live block; there is NO scan anywhere in the hot path now.
            let raw_game = read_gamestate_rpm(cur_pid, &mut ram_base, &mut last_find, fighting,
                n > 0 || in_session || live_seen.map_or(false, |t| t.elapsed().as_secs() < 20), last_good_base);
            if ram_base != 0 { last_good_base = ram_base; }   // remember the located base → reuse it, never re-scan
            // ── PAINT SLOTS ── the EXACT per-fighter render-palette pointers (cl+0x4c) + char_id, straight from
            // the located array. This is the "follow the pointer, don't scan" path: it is NOT subject to the
            // liveness gate below, because painting needs the pointer, not animation. So skins paint at match
            // START (static, pre-first-hit) through the exact DatPal — no working-buffer scan, no fuzzy match.
            // Sticky (held across a transient miss); cleared on game-off / new pid.
            if let Some(g) = &raw_game {
                let ps: Vec<(u8, u8, u32)> = g.slots.iter().filter(|s| s.datpal != 0).map(|s| (s.player, s.char_id, s.datpal)).collect();
                if !ps.is_empty() { snapshot().lock().unwrap().paint_slots = ps; }
            }
            // ── LIVENESS GATE ── drop game data that isn't actively updating. A live fight animates every
            // frame, so a hash that's unchanged across cycles = a FROZEN buffer (menu / match over / stale
            // base) → treat as NO live match, so we never surface an old match's roster/opponent/side.
            let mut game = match raw_game {
                Some(g) => {
                    let hh = game_liveness_hash(cur_pid, &g);
                    if hh != 0 && hh == prev_live_hash { frozen_cycles = frozen_cycles.saturating_add(1); }
                    else { frozen_cycles = 0; prev_live_hash = hh; }
                    // ~1.2s byte-identical → not a live/current copy. Drop the base so the next find re-acquires a
                    // LIVE one (find_array prefers an animating base, whose DatPals track the current round's
                    // render). Restored from gs-70 — removing this (gs-71) pinned painting to the static anchor
                    // copy and broke cross-round painting.
                    if frozen_cycles >= 3 { ram_base = 0; None } else { Some(g) }
                }
                None => { frozen_cycles = 0; None }
            };
            // gs-91: the +0x554 char_id field reads a wrong value (0 = Ryu, sometimes another id) for some live
            // fighters in the find_array copy, while the sig-scan roster carries the real 6 chars. The roster's
            // ORDER is by address (not team parity), so we can't map it positionally — instead, treat the roster as
            // the authoritative SET: any game slot whose char_id isn't one of the real chars is a mis-read, and gets
            // the leftover real char no correctly-read slot accounted for. (Common case = one point-slot reading 0 →
            // exactly one leftover → unambiguous.) Keeps the overlay/skin on the true character. The team split for
            // display comes from the game slots' own player field, which IS reliable — not the roster order.
            // gs-93: the old set-difference fill produced PHANTOM DUPLICATES ("opponent has 2 Ryus") because 0 is
            // BOTH the mis-read default AND a real char (Ryu) — a mis-read 0 looked "known" whenever the roster held
            // a real Ryu, so it was never corrected. Fix: the 6 live slots must COLLECTIVELY equal the sig-scan
            // roster MULTISET. Claim greedily from that pool, trusting NON-zero reads first (a 0 read is the
            // unreliable default); a 0 that matches a still-unclaimed roster Ryu is kept as a real Ryu; any slot
            // left unclaimed (a mis-read) takes a remaining pool char. Guarantees no character shows more times than
            // the roster actually contains → no phantom dupes. (Exact per-slot identity still needs char-select.)
            // gs-95: the point/active fighter's +0x554 char-id reads 0 (=Ryu) even on the LIVE copy → a phantom
            // "Ryu" on that character's card. The old multiset fix couldn't correct it: its pool (roster via
            // anchor_roster) reads the SAME +0x554, so slot AND pool agreed on the phantom. Real fix (RE-confirmed):
            // when a slot reads 0, identify EVERY fighter by its DAT FINGERPRINT (the char_sigs structural signature,
            // which is +0x554-INDEPENDENT and skin/color-invariant), located per slot via the DatPal→DAT-bank rank.
            // The 6 DAT banks load at a fixed 0x150000 stride and each slot's DatPal points into its own bank, so
            // sorting slots by DatPal ↔ banks by address pairs each slot to its true character. Only applied when all
            // 6 slots have a valid DatPal AND exactly 6 banks are found; otherwise the +0x554 reads stand (safe).
            if let Some(g) = game.as_mut() {
                if g.slots.iter().any(|s| s.char_id == 0) {
                    let dps: Vec<u32> = g.slots.iter().map(|s| s.datpal).filter(|&d| is_wb(d)).collect();
                    if dps.len() == 6 {
                        let lo = (*dps.iter().min().unwrap() as usize).saturating_sub(0x160000);
                        let hi = (*dps.iter().max().unwrap() as usize) + 0x160000;
                        let mut occ = unsafe { rpm_occurrences(h, lo, hi) };   // (addr, cid, name), unsorted, no dedup
                        occ.sort_by_key(|o| o.0);
                        // one hit per DAT bank: keep the first of each cluster separated by >= 0x100000 (banks are
                        // 0x150000 apart). A mirror (same char, two banks) correctly yields two same-cid entries.
                        let mut banks: Vec<u8> = Vec::new(); let mut last_a = 0usize;
                        for (a, cid, _) in &occ {
                            if banks.is_empty() || *a >= last_a + 0x100000 { banks.push(*cid as u8); last_a = *a; }
                        }
                        if banks.len() == 6 {
                            let mut order: Vec<usize> = (0..6).collect();
                            order.sort_by_key(|&i| g.slots[i].datpal);   // slots in DatPal (= bank address) order
                            for (rank, &si) in order.iter().enumerate() { g.slots[si].char_id = banks[rank]; }
                        }
                    }
                }
            }
            // live_seen latch: set on every LIVE array read → keeps find_array re-acquiring through rollback flicker
            // (allow_find above) and gates the deterministic side lock below.
            if game.is_some() { live_seen = Some(std::time::Instant::now()); }

            // ── SIDE — AUTHORITATIVE from localPlayerNum (gs-94) ── localPlayerNum @ exe+0xac7230 is the game's OWN
            // local netplay index (0/1). Validated live: stable 16/16 within a session, while the char-based method
            // flip-flopped on point-char mis-reads and inverted the stats. It is PER-MACHINE (each app reads its own
            // user's index) and, because the game state is shared, the two players' values are complementary — so it
            // cleanly identifies YOUR team. Map it straight to the user's parity and CONFIRM it: 0 => P1/even slots,
            // 1 => P2/odd slots (ground-truth confirmed 2026-08-14; see the mapping at the read below). ⚠ an earlier
            // version of THIS comment said "0 => odd/P2" — that was WRONG and contradicted the code; deleted.
            // An explicit manual override (rare now) still wins; otherwise localPlayerNum decides and games record
            // immediately (no buffering, no wrong guess). NOTE: unproven case is localPlayerNum=1 (the side-flip) —
            // the next session on the other side confirms it live, and every recording carries local_pn + the frame
            // KO so we can validate/correct offline regardless.
            let _ = (&mut side_seen, &mut side_stable);
            // ★ Read localPlayerNum ONLY once fighters are LIVE (game.is_some()), NEVER during matchmaking.
            // WHY (regression fixed): the netplay PAIRING (in_session) appears at the ranked-matchmaking screen —
            // BEFORE the game reassigns localPlayerNum for the new session — so localPlayerNum still holds the LAST
            // session's value in that window. Reading on in_session locked that STALE value as the side, inverting
            // the win. By the time fighters are on screen the game has settled localPlayerNum to this match's real
            // value, so a live-game read is always correct. (Trade-off: side/names aren't known until game 1 loads;
            // the char-select names feature will use a proper char-select signal, not the racy pairing.)
            if game.is_some() && exe_base != 0 {
                if let Some(pn) = unsafe { rpm_u32(h, exe_base + LOCALPLAYER_OFF) } {
                    // ⚠ lpn→side. GROUND TRUTH (clean pointer-follow read, ranked, 2026-08-14): localPlayerNum=1 →
                    // the user is on the ODD/P2 slots (their team read on odd; they lost round 1; win_result agreed).
                    // ⇒ 0 => P1/even (side 1), 1 => P2/odd (side 2). The earlier (0=>2,1=>1) came from SHIFTED
                    // sig-scan reads (pre-pointer-follow) that inverted characters + W/L + skins together. Names are
                    // side-INDEPENDENT (p1name=you, p2name=opp; applySideLayout is a fixed you-left/opp-right layout),
                    // so this flip does NOT touch names — the old "flip breaks the name" note WAS that misdiagnosis.
                    let side = match pn { 0 => 1u8, 1 => 2u8, _ => 0u8 };
                    if side != 0 {
                        let mut s = snapshot().lock().unwrap();
                        // ALWAYS track the raw localPlayerNum side — it's the authoritative, ground-truth-confirmed
                        // side and now drives the W/L VERDICT directly (see the update_score caller). manual_side
                        // still overrides the DISPLAY label via effective_side, but NEVER the recorded result — a
                        // stale manual toggle must not be able to invert a whole set (the Duc-class failure).
                        s.local_side = side; s.side_confirmed = true;
                    }
                }
            }
            // NOTE: we do NOT reset the debounce when game is None (a flash gap between live reads) — localPlayerNum
            // is read ONLY on a live fighter read, so a wrong char-select value never enters the debounce, and the
            // value-change branch above already resets on any genuine side flip. Accumulating across sparse live
            // reads is what lets the side lock inside the first match despite the read flashing on and off.
            // Hold the opponent while EITHER the game reads live OR fighters are present (sig-scan roster n) —
            // robust to a flaky reversed-struct read so we never drop + re-hunt the opponent mid-set. Drop
            // only after a sustained gone stretch (set over / menus).
            let active = game.as_ref().map(|g| g.in_match == 1).unwrap_or(false) || n > 0 || in_session;
            if active { last_active = std::time::Instant::now(); }
            else if opp.is_some() && last_active.elapsed().as_secs() > OUT_TIMEOUT { opp = None; opp_addr = None; }
            // VERDICT side = RAW localPlayerNum (authoritative, ground-truth mapping 0=>P1 / 1=>P2) via local_side,
            // NOT effective_side: a stale/wrong manual override must never flip the RECORDED winner (the Duc-class
            // inversion). manual_side still steers the on-screen label through effective_side elsewhere; the W/L
            // result now follows the pointer only. The server (reconcile.rs) agrees via the same local_pn→side map.
            let (side_for_stats, side_ok) = { let s = snapshot().lock().unwrap(); (s.local_side, s.side_confirmed) };
            update_score(&mut ss, &game, &opp, side_for_stats, side_ok);
            write_fighters(&game);
            let sc = (ss.p1, ss.p2);
            trace_cycle(&mut prev_log, "rpm", &state, &roster, &opp, &game, sc);

            // gs-102: char-select LOCKED picks (game_state+0x758). Gate = scene==5 (in a match SESSION) AND no live
            // fighter read (game.is_none()) → that pair is EXACTLY the char-select/loading window (fighters load only
            // for the fight). Fires the instant you lock a char, match 1 included (no netplay dependency), surfaces a
            // FULLY-locked team too, and never shows a stale team at a real menu (scene!=5 there). Handoff to the
            // fighter array is automatic (once fighters load, game.is_some() → picks stop, the array drives display).
            let picks = if exe_base != 0 && fighting && game.is_none() { unsafe { read_char_picks(h, exe_base) } } else { Vec::new() };
            let picking = !picks.is_empty();   // captured before `picks` is moved into the snapshot below

            // ── TRAY: live-match broadcast (was the webview's report_live_match). While actively in a match vs a
            // real 17-digit opponent, POST /match/live so peers see "🟢 Now Playing". ~20s keepalive per opponent
            // (server TTL 60s); a NEW opponent reports immediately. my_chars / opp_chars come from the live fighter
            // slots split by the authoritative side (side_for_stats). Spawned so the POST never stalls the cycle.
            // Gated by "Pause reporting" (tray): while PAUSED we broadcast no live match (live_rep_* left un-updated
            // so an unpause reports the current match immediately).
            if !PAUSED.load(Ordering::Relaxed) && state == "match" {
                if let Some((oid, _)) = opp.as_ref() {
                    if oid.len() == 17 && oid.bytes().all(|b| b.is_ascii_digit())
                        && (oid.as_str() != live_rep_opp.as_str() || live_rep_last.elapsed().as_secs() >= 20) {
                        live_rep_opp = oid.clone();
                        live_rep_last = std::time::Instant::now();
                        let (mine, theirs): (Vec<i64>, Vec<i64>) = match &game {
                            Some(g) if side_for_stats == 1 || side_for_stats == 2 => (
                                g.slots.iter().filter(|s| s.player == side_for_stats).map(|s| s.char_id as i64).collect(),
                                g.slots.iter().filter(|s| s.player != side_for_stats).map(|s| s.char_id as i64).collect(),
                            ),
                            _ => (Vec::new(), Vec::new()),
                        };
                        let opp_id = oid.clone();
                        std::thread::spawn(move || report_live_match(opp_id, mine, theirs));
                    }
                }
            }

            // ── TRAY: publish AgentStatus (what tray.rs shows). Derived from the same per-cycle signals the
            // webview used to poll via detect_state / detect_opponent. Kept separate from the internal Snapshot.
            {
                let mut a = agent_status().lock().unwrap();
                a.game_running = true;
                a.state = state.clone();
                a.in_session = in_session;
                a.opponent = if state != "menu" {
                    opp.as_ref().map(|o| if o.1.is_empty() { o.0.clone() } else { o.1.clone() })
                } else { None };
                a.score = sc;
                a.reporting = state == "match" && opp.as_ref().map_or(false, |o| o.0.len() == 17);
            }

            // publish snapshot (tiny critical section)
            {
                let mut s = snapshot().lock().unwrap();
                // Never surface an opponent at a true menu (no roster) — stops a stale friends-cache lock
                // (e.g. an old "wenzel") lingering on screen while you're idle. Held internally for scoring;
                // just not displayed until you're in/entering a match (select/match).
                let show_opp = state != "menu";
                s.state = state;
                s.roster = roster.clone();
                s.opponent = if show_opp { opp.clone() } else { None };
                s.game = game;
                s.score = sc;
                s.session_id = ss.session_id.clone().unwrap_or_default();
                s.match_index = ss.match_index;
                s.in_session = in_session;
                s.ram_base = last_good_base;   // gs-74: publish the located array base so paint_live paints the REAL array (it relocates off the anchor per match)
                s.picks = picks;               // gs-100: char-select locked picks (empty unless online char-select)
                s.scene = scene;               // gs-101: game screen-state id (5=fighting)
            }

            // adaptive cadence: fast cheap region-tracking when we have the team; back off at menus
            // (where the wide relocate runs) so idle scanning stays light
            // Fast cadence whenever we have a team OR a live netplay session (populate/track quickly); back off
            // only when truly idle at menus. (Was 2000ms idle → a match entered mid-sleep waited up to 2s.)
            // persist the anchors whenever they change, keyed to the game pid → next app restart skips the scans
            { let cur = (ram_base, opp_region, work); if cur != saved_anchors { save_anchors(cur_pid, ram_base, opp_region, work); saved_anchors = cur; } }
            // faster cadence while picking (picks present) so characters pop in near-instantly; fast with a
            // team/session; back off only when truly idle at menus.
            std::thread::sleep(std::time::Duration::from_millis(
                if picking { 150 } else if !roster.is_empty() || in_session { 300 } else { 500 }));
            }));   // end P0.3 per-cycle panic guard
            if cycle.is_err() {
                trace("[reader] cycle panicked — recovering, continuing");
                std::thread::sleep(std::time::Duration::from_millis(500));   // avoid a hot-spin on repeated panics
            }
        }
    });
}

// ════════════════════════════════════════════════════════════════════════════════════════════════════════
// ▲▲▲ END VERBATIM PORT. Below is the T2 tray-decouple glue (replaces the webview's Snapshot polling). ▲▲▲
// ════════════════════════════════════════════════════════════════════════════════════════════════════════

/// What the tray shows. The reader thread updates this every cycle (and clears it on game-off); tray.rs reads
/// it for its status line. This is the decoupled replacement for the webview polling detect_state / the app's
/// `emit`: the reader owns the derived UI state and the tray just renders it. Cheap O(1) reads, never blocks.
#[derive(Clone, Default)]
pub struct AgentStatus {
    pub game_running: bool,          // MvC2 process detected + handle open
    pub in_session: bool,            // live netplay pairing present (in/entering an online match)
    pub state: String,               // game_off | menu | select | match
    pub opponent: Option<String>,    // opponent display name (or SteamID) while in/entering a match
    pub score: (u32, u32),           // (P1, P2) games won this set
    pub reporting: bool,             // actively reporting a live match (in a fight vs a real 17-digit SteamID)
    pub online: u32,                 // last heartbeat's live-online count (0 until the first heartbeat lands)
}

pub fn agent_status() -> &'static Mutex<AgentStatus> {
    static A: OnceLock<Mutex<AgentStatus>> = OnceLock::new();
    A.get_or_init(|| Mutex::new(AgentStatus::default()))
}

// ── TRAY control flag (drives the production tray menu; see tray.rs) ───────────────────────────────────
/// "Pause reporting" (tray, session-only, default OFF): while true the reader SKIPS every server-reporting
/// path — the presence heartbeat, the live-match broadcast, and the /result game report (+ its recording
/// upload). NOT persisted — every launch starts reporting-on. Set by the tray; read at the three gated report
/// sites in start_reader() and at report_result_server(). Detection/scoring/painting are unaffected.
pub(crate) static PAUSED: AtomicBool = AtomicBool::new(false);

/// The Steam persona the reader identified (Steam registry / loginusers.vdf, via `self_ident`) for the tray's
/// "Signed in as {name}" row. `None` when no Steam identity is resolvable yet OR the persona is unknown — the
/// tray renders that as "Steam not detected". Cheap after the first resolve (self_ident caches its result).
pub(crate) fn signed_in_name() -> Option<String> {
    let (id, name) = self_ident();
    if id == 0 {
        return None;
    }
    let name = name.trim();
    if name.is_empty() {
        None
    } else {
        Some(name.to_string())
    }
}

// ── T3 painter view ── the skin painter (painter.rs) runs as a SIBLING thread and coordinates through the
// SAME internal `Snapshot` the reader publishes each cycle (paint_slots / ram_base / side / scene / state).
// This is the decoupled replacement for the webview reading `st.paint_slots` and driving paint_live /
// paint_signatures from JS: the reader owns detection + the located array, the painter owns the writes.
// paint_view() is a tiny O(1) clone so the painter never holds the reader's lock while it does its (slower)
// RPM palette writes. It exposes ONLY what the painter's resolution needs — no game-memory access leaks out.
#[derive(Clone, Default)]
pub(crate) struct PaintView {
    pub state: String,                    // game_off | menu | select | match
    pub scene: i32,                       // 5 = fighting (game_state+0x8)
    pub paint_slots: Vec<(u8, u8, u32)>,  // (player, char_id, datpal) — exact per-fighter render-palette pointers
    pub ram_base: usize,                  // located fighter array (0 = none) → paint_live resolves live DatPals off it
    pub local_side: u8,                   // 0=unknown 1=P1 2=P2 (auto-detected)
    pub side_confirmed: bool,             // side trustworthy → mirror split + opponent skins may layer per-side
    pub in_session: bool,                 // live netplay pairing present this cycle
}
pub(crate) fn paint_view() -> PaintView {
    let s = snapshot().lock().unwrap();
    PaintView {
        state: s.state.clone(), scene: s.scene, paint_slots: s.paint_slots.clone(),
        ram_base: s.ram_base, local_side: s.local_side, side_confirmed: s.side_confirmed, in_session: s.in_session,
    }
}

/// One-line tray status derived from AgentStatus (the string tray.rs puts on its disabled status item +
/// tooltip). Mirrors the app's own vocabulary: "watching for MvC2" / "in a match" / "● reporting".
pub fn status_line() -> String {
    let a = agent_status().lock().unwrap();
    if !a.game_running {
        return "MetaSync — watching for MvC2".into();
    }
    let base = match a.state.as_str() {
        "match" => {
            let opp = a.opponent.as_deref().unwrap_or("opponent");
            format!("🎮 in a match vs {} ({}-{})", opp, a.score.0, a.score.1)
        }
        "select" => "MetaSync — match starting…".into(),
        _ => "MetaSync — MvC2 running".into(),
    };
    if a.reporting { format!("{}  ● reporting", base) } else { base }
}

