// Cross-player skin sync.
//
// SNOOP (read-only): find the online opponent's SteamID by scanning the game process's
// memory for the player structs — a SteamID64 (public/individual, high dword 0x01100001)
// stored next to a printable Fighter-ID string. Pure ReadProcessMemory; no writes, no
// packets — it cannot affect the match. Our own SteamID (from steam_self.txt, which the
// hook reads via Steamworks getters) is excluded.
//
// SYNC: publish our active loadout to the skinsync coordinator keyed by our SteamID, and
// query candidate opponent SteamIDs — whichever candidate has a live loadout IS the
// opponent running the app. The frontend merges their skins into skins.dat (the hook
// repaints them live, exactly like our own).
use std::ffi::c_void;
use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use serde::Serialize;
use windows::Win32::Foundation::{CloseHandle, HANDLE, FALSE};
use windows::Win32::System::Threading::{OpenProcess, PROCESS_VM_READ, PROCESS_VM_WRITE, PROCESS_VM_OPERATION, PROCESS_QUERY_INFORMATION};
use windows::Win32::System::Memory::{VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_GUARD, PAGE_NOACCESS};
use windows::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
use windows::Win32::UI::Input::XboxController::{XInputGetState, XINPUT_STATE};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
    Module32FirstW, MODULEENTRY32W, TH32CS_SNAPMODULE,
};

const SKINSYNC: &str = "https://nobd.net/skinsync";
const STEAMID_HI: u32 = 0x0110_0001; // universe=public, type=individual, instance=desktop

// ---- team detection via per-character DAT signatures (see detect_state below) ----
// Each fighter's decompressed DAT carries a unique 64-byte gfx1 chunk. When a character is
// loaded for a match the game copies its DAT into a "working buffer" in the 0x10000000-0x14000000
// region (above the identity-mapped guest ROM at 0x0C000000). Exactly the 6 on-screen fighters
// have a copy there — so scanning that window for the 56 sigs yields the current teams, split
// P1 (first 3 by address) / P2 (last 3). Roster + side are correct; within-side point/assist
// order comes from the live palette, not load order.
const CHAR_SIGS: &str = include_str!("../char_sigs.json");
const WIN_LO: usize = 0x1000_0000; // working-buffer window low
const WIN_HI: usize = 0x1400_0000; // working-buffer window high

#[derive(Serialize, Clone)]
pub struct Candidate { pub steamid: String, pub name: String }

// Read a REG_DWORD from HKCU. None if missing/wrong type.
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
    if let Some(acct) = reg_dword("Software\\Valve\\Steam\\ActiveProcess", "ActiveUser").filter(|&a| a != 0) {
        let id = 0x0110_0001_0000_0000u64 + acct as u64;
        let v = (id, steam_persona_name(id).unwrap_or_default());
        *g = Some(v.clone()); return v;
    }
    if let Ok(s) = std::fs::read_to_string("C:\\g\\steam_self.txt") {
        let mut it = s.lines();
        if let Some(id) = it.next().and_then(|l| l.trim().parse::<u64>().ok()) {
            let v = (id, it.next().map(|l| l.trim().to_string()).unwrap_or_default());
            *g = Some(v.clone()); return v;
        }
    }
    (0, String::new())
}
fn read_self_id() -> Option<u64> { let id = self_ident().0; if id != 0 { Some(id) } else { None } }
// Used so the OPPONENT is never us — the friends/persona cache smears our name next to other players'
// SteamIDs, so a scan can otherwise return a candidate wearing our own name and show "us" on both sides.
fn read_self_name() -> String { self_ident().1.to_lowercase() }

fn find_game_pid() -> Option<u32> {
    unsafe {
        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0).ok()?;
        let mut pe = PROCESSENTRY32W { dwSize: std::mem::size_of::<PROCESSENTRY32W>() as u32, ..Default::default() };
        let mut pid = None;
        if Process32FirstW(snap, &mut pe).is_ok() {
            loop {
                let end = pe.szExeFile.iter().position(|&c| c == 0).unwrap_or(pe.szExeFile.len());
                let name = String::from_utf16_lossy(&pe.szExeFile[..end]);
                if name.starts_with("MarvelVsCapcom") { pid = Some(pe.th32ProcessID); break; }
                if Process32NextW(snap, &mut pe).is_err() { break; }
            }
        }
        let _ = CloseHandle(snap);
        pid
    }
}

// nearest printable ASCII run (3..=24 chars) to `center` in `win` that looks like a Fighter ID.
// Returns (name, distance-in-bytes-from-center) so the caller can prefer tight co-location.
fn extract_name(win: &[u8], center: usize) -> Option<(String, usize)> {
    let mut best: Option<(usize, String)> = None;
    let mut i = 0;
    while i < win.len() {
        if (0x20..=0x7e).contains(&win[i]) {
            let start = i;
            while i < win.len() && (0x20..=0x7e).contains(&win[i]) { i += 1; }
            let run = &win[start..i];
            if run.len() >= 3 && run.len() <= 24 {
                let s = String::from_utf8_lossy(run).to_string();
                let alnum = s.chars().filter(|c| c.is_alphanumeric()).count();
                let junk = s.contains('\\') || s.contains('/') || s.contains(".dll")
                    || s.contains(".txt") || s.contains(".dat") || s.contains(".exe");
                if alnum >= 3 && !junk && !s.chars().all(|c| c.is_ascii_digit()) {
                    let mid = start + run.len() / 2;
                    let dist = if mid > center { mid - center } else { center - mid };
                    if best.as_ref().map_or(true, |(d, _)| dist < *d) { best = Some((dist, s)); }
                }
            }
        } else {
            i += 1;
        }
    }
    best.map(|(d, s)| (s, d))
}

// How persona-like a Fighter-ID string is. Real handles ("NaCherO", "Satsui No Tanden") score high;
// random bytes read as ASCII ("db!Q", "%3#R2D") score low. This + tight co-location is what isolates
// the actual opponent from the ~59 SteamID-shaped values a broad scan turns up (mostly friends cache).
fn name_quality(s: &str) -> i32 {
    let letters = s.chars().filter(|c| c.is_ascii_alphabetic()).count() as i32;
    let spaces = s.chars().filter(|c| *c == ' ').count() as i32;
    let junk = s.chars().filter(|c| !c.is_ascii_alphanumeric() && *c != ' ' && *c != '_' && *c != '-' && *c != '.').count() as i32;
    letters * 2 + spaces.min(3) - junk * 3
}

// Read `len` bytes at `addr` from an already-open handle. None on short/failed read.
unsafe fn read_window(h: HANDLE, addr: usize, len: usize) -> Option<Vec<u8>> {
    let mut buf = vec![0u8; len]; let mut got = 0usize;
    if ReadProcessMemory(h, addr as *const c_void, buf.as_mut_ptr() as *mut c_void, len, Some(&mut got)).is_ok() && got == len { Some(buf) } else { None }
}

fn scan(pid: u32, my_id: u64) -> Vec<Candidate> {
    // id -> (best co-located persona name, its score, up to a few ADDRESSES where this id occurs)
    let mut found: HashMap<u64, (String, i32, Vec<usize>)> = HashMap::new();
    unsafe {
        let h: HANDLE = match OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) {
            Ok(h) => h,
            Err(_) => return vec![],
        };
        let mut my_addrs: Vec<usize> = Vec::new();  // sites of OUR id — the opponent is the id PAIRED near these (live netplay session)
        let mut addr: usize = 0;
        loop {
            let mut mbi = MEMORY_BASIC_INFORMATION::default();
            let got = VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>());
            if got == 0 { break; }
            let base = mbi.BaseAddress as usize;
            let size = mbi.RegionSize;
            if size == 0 { break; }
            let prot = mbi.Protect.0;
            let readable = mbi.State == MEM_COMMIT
                && (prot & PAGE_GUARD.0) == 0
                && (prot & PAGE_NOACCESS.0) == 0
                && (prot & 0xEE) != 0; // RO/RW/WC/ER/ERW/ERWC
            if readable {
                let mut buf = vec![0u8; size];
                let mut read: usize = 0;
                let ok = ReadProcessMemory(h, base as *const c_void, buf.as_mut_ptr() as *mut c_void, size, Some(&mut read)).is_ok();
                if ok && read >= 16 {
                    let b = &buf[..read];
                    let mut i = 0usize; // 8-aligned value positions (base is page-aligned)
                    while i + 8 <= b.len() {
                        let hi = u32::from_le_bytes([b[i + 4], b[i + 5], b[i + 6], b[i + 7]]);
                        if hi == STEAMID_HI {
                            let v = u64::from_le_bytes([b[i], b[i + 1], b[i + 2], b[i + 3], b[i + 4], b[i + 5], b[i + 6], b[i + 7]]);
                            if v != my_id {
                                // Co-located Fighter-ID string near the SteamID (match struct holds them ~128B
                                // apart) → display name + a first-pass score; the address list feeds the
                                // freshness gate below.
                                let lo = i.saturating_sub(192);
                                let hie = (i + 192).min(b.len());
                                let e = found.entry(v).or_insert_with(|| (String::new(), i32::MIN, Vec::new()));
                                if let Some((nm, dist)) = extract_name(&b[lo..hie], i - lo) {
                                    let q = name_quality(&nm) - (dist as i32) / 24; // persona-like AND close
                                    if q > e.1 { e.0 = nm; e.1 = q; }
                                }
                                if e.2.len() < 12 { e.2.push(base + i); }
                            } else if my_addrs.len() < 128 { my_addrs.push(base + i); }   // our own id site
                        }
                        i += 8;
                    }
                }
            }
            addr = base + size;
            if addr == 0 { break; }
        }

        // FRESHNESS GATE. Rank by name first + keep the strongest few, then PREFER whichever candidate is
        // LIVE: the real opponent's SteamID sits in the active netplay session, whose surrounding bytes change
        // every frame; a friends/persona-cache entry is static. Re-read a small window around each occurrence
        // twice ~180ms apart — any change means live. Additive: if nothing looks live we fall back to best
        // name, so this never does worse than before, it only rejects stale-cache winners.
        // opponent = SteamID PAIRED with ours in the netplay session (within 0x400 of one of our id's sites).
        let paired = |addrs: &Vec<usize>| addrs.iter().filter(|&&a| my_addrs.iter().any(|&m| (a as isize - m as isize).abs() < 0x400)).count();
        let mut scored: Vec<(u64, String, i32, Vec<usize>)> = found.into_iter()
            .filter(|(_, (nm, _, a))| !nm.is_empty() || paired(a) > 0)   // keep named OR netplay-paired
            .map(|(id, (nm, q, a))| (id, nm, q, a)).collect();
        scored.sort_by(|a, b| b.2.cmp(&a.2));
        scored.truncate(32);
        let win = 0x100usize;
        let probes: Vec<(usize, usize)> = scored.iter().enumerate()
            .flat_map(|(ci, (_, _, _, addrs))| addrs.iter().map(move |&a| (ci, a.saturating_sub(0x40)))).collect();
        let before: Vec<Option<Vec<u8>>> = probes.iter().map(|&(_, a)| read_window(h, a, win)).collect();
        std::thread::sleep(std::time::Duration::from_millis(180));
        let mut live = vec![false; scored.len()];
        for (k, &(ci, a)) in probes.iter().enumerate() {
            if let (Some(x), Some(y)) = (&before[k], read_window(h, a, win)) { if x != &y { live[ci] = true; } }
        }
        let _ = CloseHandle(h);
        // live candidates first, then by name score. Frontend takes [0].
        // netplay pairing is DECISIVE (DDH_BD paired x11 vs 300+ scattered copies paired x0), then liveness, then name.
        let pair: Vec<usize> = scored.iter().map(|(_, _, _, a)| paired(a)).collect();
        let mut order: Vec<usize> = (0..scored.len()).collect();
        order.sort_by(|&i, &j| pair[j].cmp(&pair[i]).then(live[j].cmp(&live[i])).then(scored[j].2.cmp(&scored[i].2)));
        order.into_iter().take(16).map(|i| Candidate { steamid: scored[i].0.to_string(), name: scored[i].1.clone() }).collect()
    }
}

// ---- Tauri commands ----

#[tauri::command]
pub fn sync_self() -> serde_json::Value {
    // Registry-first (via self_ident), no hook/file dependency — so "You: <name>" and the leaderboard
    // "me" highlight resolve even with the hook retired.
    let (id, name) = self_ident();
    serde_json::json!({ "steamid": if id != 0 { id.to_string() } else { String::new() }, "name": name })
}

#[tauri::command]
pub fn detect_opponent() -> Result<serde_json::Value, String> {
    // O(1): the reader thread already ran the NaCherO co-location scan (once per session) and stored
    // the single best opponent. We just hand it back as a one-element candidate list.
    let my_id = read_self_id().unwrap_or(0);
    let s = snapshot().lock().unwrap();
    let candidates: Vec<Candidate> = s.opponent.as_ref()
        .map(|(id, nm)| vec![Candidate { steamid: id.clone(), name: nm.clone() }])
        .unwrap_or_default();
    Ok(serde_json::json!({ "my_id": my_id.to_string(), "candidates": candidates }))
}

#[tauri::command]
pub fn sync_publish(steamid: String, name: String, skins: serde_json::Value, effect: Option<String>) -> Result<serde_json::Value, String> {
    let body = serde_json::json!({ "steamid": steamid, "name": name, "skins": skins, "effect": effect });
    ureq::post(&format!("{}/publish", SKINSYNC)).send_json(body)
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn sync_unpublish(steamid: String) -> Result<(), String> {
    ureq::delete(&format!("{}/publish?id={}", SKINSYNC, steamid)).call()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn sync_fetch_peers(ids: Vec<String>) -> Result<serde_json::Value, String> {
    ureq::post(&format!("{}/peers", SKINSYNC)).send_json(serde_json::json!({ "ids": ids }))
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

// presence: heartbeat that we're online (any open app), returns the current online count
#[tauri::command]
pub fn sync_heartbeat(id: String, name: String) -> Result<serde_json::Value, String> {
    ureq::post(&format!("{}/heartbeat", SKINSYNC)).send_json(serde_json::json!({ "id": id, "name": name }))
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

// presence: live list of connected clients ({ online, players[] })
#[tauri::command]
pub fn sync_presence() -> Result<serde_json::Value, String> {
    ureq::get(&format!("{}/presence", SKINSYNC)).call()
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
    game: Option<GameSt>,                // real SH4 game state (RPM-read reversed player array)
    score: (u32, u32),                   // (P1, P2) games won this set, computed from KO events
    local_side: u8,                      // auto-detected local side: 0=unknown, 1=P1, 2=P2 (input correlation)
}
fn snapshot() -> &'static Mutex<Snapshot> {
    static S: OnceLock<Mutex<Snapshot>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(Snapshot { state: "game_off".into(), roster: Vec::new(), opponent: None, game: None, score: (0, 0), local_side: 0 }))
}

// Per-fighter live state (the 6 fighter slots: char_id, palette colour index, health, DatPal, and the live
// 16-colour palette) read DIRECTLY from the reversed SH4 player array via read-only RPM — ground truth from
// the game's own memory, no hook. See read_gamestate_rpm.
#[derive(Clone)]
struct GSlot { player: u8, pos: u8, char_id: u8, color: u8, health: u16, combo: u16, datpal: u32, pal: [u8; 32], addr: usize }

// The fighter's live 16-colour palette (ARGB4444 LE at the DatPal target) → the hook's RGBA sig format
// (RRGGBBAA per colour, index0 transparent) — the SAME expansion the ROM decoder + capture_live use, so a
// sig built here matches the on-screen texture the hook watches. All-zero pal → empty (no live palette).
fn pal_sig(pal: &[u8; 32]) -> String {
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
struct GameSt { in_match: u8, match_state: u8, stage: u8, timer: u32, frame: u32, ram: usize, slots: Vec<GSlot>, meter1: u8, meter2: u8 }


// ── App-side player-array reader (RPM, READ-ONLY) — the REVERSED Steam-build layout ──
// The Steam MvC2 build's runtime struct differs from Demul: 6 fighter slots at STRIDE 0x738, order
// P1C1,P2C1,P1C2,P2C2,P1C3,P2C3 (even slot = P1, odd = P2 → side is the slot-index parity). Each slot
// starts with a cluster of ~16 working-buffer pointers; per-fighter fields (relative to that start `cl`):
// DatPal @ cl+0x4c (→16-colour ARGB4444 palette), char_id @ cl+0x554 (CPS2 unit id), color @ cl+0x6,
// health (u32, full=144) @ cl+0xb44. The array BASE is VOLATILE per match, so we auto-find it by
// fingerprint (no hardcoded base, no Cheat Engine): a cluster = a 40-word window holding >=14
// working-buffer pointers; the real array = the unique run of 6 such clusters at exactly 0x738 stride
// whose DatPal pointers all land in the working-buffer range. Validated live end-to-end.
const STRIDE: usize = 0x738;
const WB_LO: u32 = 0x1000_0000;   // working-buffer pointer range (each fighter's own DAT region)
const WB_HI: u32 = 0x1420_0000;
const OFF_DATPAL: usize = 0x4c;
const OFF_COLOR:  usize = 0x6;
const OFF_CHARID: usize = 0x554;
const OFF_HEALTH: usize = 0xb44;
const OFF_COMBO:  usize = 0x1ca;    // combo this fighter is DEALING (confirmed via training); +0x902 = RECEIVED
const MET_BARS:   usize = 0x2e636;  // P1 meter bars 0-5 (relative to the array base `ram`); P2 = +1 (adjacent, per DC layout)
const MET_FILL:   usize = 0x2e658;  // P1 meter fine fill (u16) — confirmed +1 per Magneto LP
const HP_FULL: u16 = 144;
const MAX_CID: u8 = 0x3A;          // Servbot = highest CPS2 unit id (58)

unsafe fn rpm_u8(h: HANDLE, a: usize) -> Option<u8> { read_at(h, a, 1).filter(|b| b.len() >= 1).map(|b| b[0]) }
#[allow(dead_code)] // red-health (health+4) reader — kept for future use
unsafe fn rpm_u16(h: HANDLE, a: usize) -> Option<u16> { read_at(h, a, 2).filter(|b| b.len() >= 2).map(|b| b[0] as u16 | ((b[1] as u16) << 8)) }
unsafe fn rpm_u32(h: HANDLE, a: usize) -> Option<u32> { read_at(h, a, 4).filter(|b| b.len() >= 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]])) }

fn is_wb(v: u32) -> bool { v >= WB_LO && v < WB_HI }

// Cheap re-validation of a cached base: >=5 of the 6 slots have a working-buffer DatPal pointer at
// cl+0x4c. That single fixed-offset pointer is the array's strongest cheap fingerprint (16k loose
// clusters exist, but only the real 6-run keeps a WB pointer at exactly +0x4c across every slot).
unsafe fn array_valid(h: HANDLE, base: usize) -> bool {
    if base == 0 { return false; }
    (0..6).filter(|&i| is_wb(rpm_u32(h, base + i * STRIDE + OFF_DATPAL).unwrap_or(0))).count() >= 5
}

// Heavy (~1.25GB scan) — run only when the cached base is stale/missing AND fighters are loaded, throttled.
// 1) find every candidate cluster (a 40-word window with >=14 working-buffer pointers), 2) find bases where
// >=5 of base+i*0x738 (i=0..6) is also a cluster, 3) pick the base whose slots best satisfy the per-fighter
// invariant (WB DatPal + sane health). Returns the array base (volatile — never cache across matches blindly).
unsafe fn find_array(h: HANDLE) -> Option<usize> {
    const WIN: usize = 40;   // ~0xA0-byte window
    const MINP: usize = 14;  // the real cluster holds ~16 working-buffer pointers
    let mut clusters: Vec<usize> = Vec::new();
    let mut addr = 0usize;
    loop {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 { break; }
        let base = mbi.BaseAddress as usize; let size = mbi.RegionSize;
        if size == 0 { break; }
        let prot = mbi.Protect.0;
        let readable = mbi.State == MEM_COMMIT && (prot & PAGE_GUARD.0) == 0 && (prot & PAGE_NOACCESS.0) == 0 && (prot & 0xEE) != 0;
        addr = base + size; if addr <= base { break; }
        // include the ~512MB guest-RAM virtmem blocks (earlier scans wrongly capped at 256MB and missed them)
        if !(readable && size >= 0x10000 && size <= 0x5000_0000) { continue; }
        let buf = match read_at(h, base, size) { Some(v) if v.len() == size => v, _ => continue };
        let words = buf.len() / 4;
        if words < WIN { continue; }
        let flag: Vec<u8> = (0..words).map(|i| { let o = i*4; if is_wb(u32::from_le_bytes([buf[o],buf[o+1],buf[o+2],buf[o+3]])) {1} else {0} }).collect();
        let mut sum: usize = flag[..WIN].iter().map(|&x| x as usize).sum();
        let mut i = 0usize; let mut last: isize = -(STRIDE as isize);
        while i + WIN <= words {
            if sum >= MINP {
                let a = base + i * 4;
                if (a as isize - last) > 0x200 { clusters.push(a); last = a as isize; }
            }
            sum -= flag[i] as usize;
            if i + WIN < words { sum += flag[i + WIN] as usize; }
            i += 1;
        }
    }
    clusters.sort(); clusters.dedup();
    let has_cluster = |t: usize| clusters.iter().any(|&x| (x as isize - t as isize).abs() <= 0x40);
    // candidate bases: a cluster whose 6-run at 0x738 stride is >=5/6 present, then scored by the real
    // per-fighter invariant (WB DatPal at cl+0x4c AND a sane health at cl+0xb44).
    let mut cands: Vec<(usize, usize)> = Vec::new();
    // even slot = P1, odd = P2; a side is "alive" if any of its fighters has real health (1..=144).
    let side_alive = |c: usize, par: usize| (0..6).filter(|&i| i % 2 == par)
        .any(|i| { let hp = rpm_u32(h, c + i * STRIDE + OFF_HEALTH).unwrap_or(0); (1..=144).contains(&hp) });
    for &c in clusters.iter() {
        if (0..6).filter(|&i| has_cluster(c + i * STRIDE)).count() < 5 { continue; }
        let score = (0..6).filter(|&i| {
            let cl = c + i * STRIDE;
            is_wb(rpm_u32(h, cl + OFF_DATPAL).unwrap_or(0)) && rpm_u32(h, cl + OFF_HEALTH).unwrap_or(0xffff) <= 0x200
        }).count();
        // ★ require BOTH teams to have a LIVING fighter — a frozen post-KO copy reads one whole side at 0
        // (the "P2 reads dead → phantom wins / broken side" bug). Rejecting one-sided buffers at the source is
        // the real fix. (A genuine KO frame is transient; the base is already cached from when both were alive.)
        if score >= 5 && side_alive(c, 0) && side_alive(c, 1) { cands.push((c, score)); }
    }
    if cands.is_empty() { return None; }
    cands.sort_by(|a, b| b.1.cmp(&a.1));
    // LIVENESS: a live match animates the fighter structs every frame; a frozen/stale copy (a leftover
    // post-match savestate — the trace's endless phantom wins) does not. Sample each candidate's animating
    // region, wait, re-sample, and PREFER whichever actually changed, so we never lock a frozen buffer.
    let anim = |c: usize| -> Vec<u8> {
        let mut v = Vec::with_capacity(6 * 0xC0);
        for i in 0..6 { if let Some(b) = read_at(h, c + i * STRIDE + 0x100, 0xC0) { v.extend_from_slice(&b); } }
        v
    };
    let before: Vec<Vec<u8>> = cands.iter().map(|&(c, _)| anim(c)).collect();
    std::thread::sleep(std::time::Duration::from_millis(150));
    for (i, &(c, _)) in cands.iter().enumerate() {
        if !before[i].is_empty() && anim(c) != before[i] { return Some(c); }  // this candidate is LIVE
    }
    Some(cands[0].0)   // none demonstrably live → best static (reader's saw_both gate still guards scoring)
}

// Cheap (~6 small reads/slot) — read the six fighters from a located base. side = slot parity (VALIDATED:
// even=P1, odd=P2); pos = C1/C2/C3 by pair. in_match is derived (any present fighter with live health):
// the array only exists once fighters are loaded, so this reliably distinguishes an active fight.
unsafe fn read_fighters(h: HANDLE, base: usize) -> Option<GameSt> {
    if base == 0 { return None; }
    let mut slots = Vec::new();
    let mut any_live = false;
    for i in 0..6 {
        let cl = base + i * STRIDE;
        let cid = rpm_u8(h, cl + OFF_CHARID).unwrap_or(255);
        if cid > MAX_CID { continue; } // not a live fighter slot
        let hp_raw = rpm_u32(h, cl + OFF_HEALTH).unwrap_or(0);
        let health = if hp_raw <= 0x200 { hp_raw as u16 } else { 0 };
        if health > 0 && health <= HP_FULL { any_live = true; }
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
    Some(GameSt { in_match: if any_live { 1 } else { 0 }, match_state: 0, stage: 0, timer: 0, frame: 0, ram: base, slots, meter1, meter2 })
}

// Self-contained gamestate read used by BOTH the hook path and the RPM fallback. Opens its own read-only
// handle, re-validates (or re-finds, throttled) the volatile array base, then does the cheap per-fighter
// read. `allow_find` gates the heavy scan to when fighters are likely loaded (sig-scan roster non-empty).
fn read_gamestate_rpm(pid: u32, ram_base: &mut usize, last_find: &mut std::time::Instant, allow_find: bool) -> Option<GameSt> {
    if pid == 0 { return None; }
    let h = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid).ok()? };
    let out = unsafe {
        if *ram_base != 0 && !array_valid(h, *ram_base) { *ram_base = 0; }       // volatile → dropped
        if *ram_base == 0 && allow_find && last_find.elapsed().as_millis() >= 3000 {
            *last_find = std::time::Instant::now();
            *ram_base = find_array(h).unwrap_or(0);
            // find_array is a heavy ~1GB scan. If it came up empty (char-select/loading — the array isn't
            // instantiated yet, but sig-scan fighters linger), back the NEXT attempt WAY off so the scan
            // never thrashes and stacks up under other work. Once found, array_valid is cheap → no re-scan.
            if *ram_base == 0 { *last_find += std::time::Duration::from_millis(2000); }  // modest backoff: don't thrash, but acquire the new match's array fast (skins on at round start)
        }
        if *ram_base != 0 { read_fighters(h, *ram_base) } else { None }
    };
    unsafe { let _ = CloseHandle(h); }
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
    let _ = std::fs::write("C:\\g\\fighters.txt", body);
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
    g1_met: u32, g2_met: u32, last_m1: u8, last_m2: u8, met_init: bool }

// Rich per-game payload for logging (both teams + combat stats). Winner/loser & my/opp are resolved downstream.
#[derive(Clone, Default)]
struct GameRich { p1_team: Vec<u8>, p2_team: Vec<u8>, p1_combo: u16, p2_combo: u16, p1_met: u32, p2_met: u32 }
fn rich_of(st: &ScoreState) -> GameRich {
    let (p1_team, p2_team) = st.teams.clone().unwrap_or_default();
    GameRich { p1_team, p2_team, p1_combo: st.g1_maxcombo, p2_combo: st.g2_maxcombo, p1_met: st.g1_met, p2_met: st.g2_met }
}

// ── PERSISTENT HEAD-TO-HEAD RECORD (C:\g\records.json, keyed by opponent SteamID) ──────────────────
// A "game" is won when one side's whole team is KO'd (all fighters health→0). We attribute it to YOU via
// the deterministic side (local_side: 1=P1, 2=P2; 0=unknown → skip, don't guess). Accumulates across sets.
fn record_result(steamid: &str, name: &str, i_won: bool) {
    if steamid.is_empty() || steamid == "0" { return; }
    let mut r = std::fs::read_to_string("C:\\g\\records.json").ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = r.as_object_mut() {
        let e = obj.entry(steamid.to_string()).or_insert_with(|| serde_json::json!({"name": "", "wins": 0, "losses": 0}));
        if !name.is_empty() { e["name"] = serde_json::json!(name); }
        let k = if i_won { "wins" } else { "losses" };
        let c = e[k].as_u64().unwrap_or(0); e[k] = serde_json::json!(c + 1);
    }
    let _ = std::fs::write("C:\\g\\records.json", serde_json::to_string_pretty(&r).unwrap_or_default());
    trace(&format!("[record] {} vs {} ({steamid})", if i_won { "WIN" } else { "LOSS" }, name));
}
// Is `nm` a plausible gamertag vs memory junk? The SteamID scan sometimes glues a random ASCII run next to a
// SteamID-shaped value (URLs like "googleapis.com", UI fragments like "…you while waiting for opponent"). We
// refuse to record a result against anything that clearly isn't a handle, so garbage never hits the board.
fn plausible_opponent_name(nm: &str) -> bool {
    let s = nm.trim();
    if s.len() < 2 || s.len() > 24 { return false; }
    if s.matches(' ').count() > 2 { return false; }           // gamertags aren't sentences
    let low = s.to_lowercase();
    // URL/file fragments AND game/UI/netcode strings the scan keeps grabbing (title, menus, log lines).
    for bad in [".com", ".net", ".org", ".io", ".gg", "http", "www.", "://", ".dll", ".exe", ".dat", "googleapi",
                "marvel", "capcom", "heroes", "new age", "session", "exiting", "waiting", "opponent", "loading",
                "connect", "matchmak", "lobby", "player", "press", "select", "steam"] {
        if low.contains(bad) { return false; }
    }
    s.chars().filter(|c| c.is_ascii_alphanumeric()).count() * 2 >= s.len()   // ≥50% alphanumeric
}

// A finished game: record the local per-opponent H2H AND report it to the global leaderboard. The rich-stat
// flags (ocv/perfect/comeback) always describe the WINNER — computed symmetrically from both sides' health,
// so we credit them correctly whether we won or lost.
fn on_game_win(winner: u8, opp: &Option<(String, String)>, my_side: u8, ocv: bool, perfect: bool, comeback: bool, rich: &GameRich) {
    if my_side != 1 && my_side != 2 { return; }
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
    report_result_server(reporter, winner_id, winner_name, loser_id, loser_name, ocv, perfect, comeback,
        winner_team, loser_team, winner_combo, winner_met);
}

// Fire-and-forget POST of a finished game to the skinsync leaderboard (own thread so the reader never blocks
// on the network). The server dedupes so the same game reported by both players counts once.
fn report_result_server(reporter: String, winner: String, winner_name: String, loser: String, loser_name: String,
                        ocv: bool, perfect: bool, comeback: bool,
                        winner_team: Vec<u8>, loser_team: Vec<u8>, biggest_combo: u16, meters_used: u32) {
    std::thread::spawn(move || {
        let body = serde_json::json!({
            "reporter": reporter, "winner": winner, "loser": loser, "winner_name": winner_name, "loser_name": loser_name,
            "ocv": ocv, "perfect": perfect, "comeback": comeback,
            "winner_team": winner_team, "loser_team": loser_team, "biggest_combo": biggest_combo, "meters_used": meters_used,
        });
        let _ = ureq::post(&format!("{}/result", SKINSYNC))
            .timeout(std::time::Duration::from_secs(5)).send_json(body);
    });
}

fn update_score(st: &mut ScoreState, game: &Option<GameSt>, opp: &Option<(String, String)>, my_side: u8) {
    let cur = opp.as_ref().map(|o| o.0.clone());
    // Reset the set ONLY for a genuinely different, present opponent. A transient None (opponent momentarily
    // undetected between games / long char-select) must NOT wipe the set score — hold it until a real,
    // different SteamID actually appears.
    if let Some(cur_id) = cur {
        if st.set_opp.as_deref() != Some(cur_id.as_str()) { *st = ScoreState { set_opp: Some(cur_id), ..Default::default() }; }
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
                        st.g1_maxcombo = 0; st.g2_maxcombo = 0; st.g1_met = 0; st.g2_met = 0; st.met_init = false; st.teams = None; }
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
                if !st.judged && st.saw_both {                 // KO edge (only for a game we saw contested)
                    if st.la1 && !a1 && a2 {
                        st.p2 += 1; st.judged = true; let r = rich_of(st);
                        on_game_win(2, opp, my_side, alive_ct(2) == 3, !st.g2_dmg, st.g2_low, &r);
                    } else if st.la2 && !a2 && a1 {
                        st.p1 += 1; st.judged = true; let r = rich_of(st);
                        on_game_win(1, opp, my_side, alive_ct(1) == 3, !st.g1_dmg, st.g1_low, &r);
                    }
                }
                st.la1 = a1; st.la2 = a2; st.was_in = true;
            } else if st.was_in && !st.judged && st.saw_both { // match ended before the KO edge (contested game only)
                if st.la1 && !st.la2 { st.p1 += 1; st.judged = true; let r = rich_of(st); on_game_win(1, opp, my_side, false, !st.g1_dmg, st.g1_low, &r); }
                else if st.la2 && !st.la1 { st.p2 += 1; st.judged = true; let r = rich_of(st); on_game_win(2, opp, my_side, false, !st.g2_dmg, st.g2_low, &r); }
                st.was_in = false; st.saw_both = false;
            } else { st.was_in = g.in_match == 1; if g.in_match != 1 { st.saw_both = false; } }
        }
        None => {   // game data gone (liveness gate / match over): judge from the LAST-known alive states
            if st.was_in && !st.judged && st.saw_both {
                if st.la1 && !st.la2 { st.p1 += 1; st.judged = true; let r = rich_of(st); on_game_win(1, opp, my_side, false, !st.g1_dmg, st.g1_low, &r); }
                else if st.la2 && !st.la1 { st.p2 += 1; st.judged = true; let r = rich_of(st); on_game_win(2, opp, my_side, false, !st.g2_dmg, st.g2_low, &r); }
            }
            st.was_in = false; st.saw_both = false;
        }
    }
}

/// Head-to-head record vs a SteamID: { name, wins, losses }. 0-0 if none yet.
#[tauri::command]
pub fn get_record(steamid: String) -> serde_json::Value {
    std::fs::read_to_string("C:\\g\\records.json").ok()
        .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        .and_then(|r| r.get(&steamid).cloned())
        .unwrap_or_else(|| serde_json::json!({ "wins": 0, "losses": 0 }))
}

/// Global leaderboard from the skinsync server for a tab (streak | wins | ocv | perfect | comeback).
/// Returns { tab, field, players: [{ steamid, name, wins, losses, stat }] } (backend fetch → no CORS/CSP).
#[tauri::command]
pub fn leaderboard(tab: String, limit: Option<u32>) -> Result<serde_json::Value, String> {
    let lim = limit.unwrap_or(10).min(50);
    ureq::get(&format!("{}/leaderboard?tab={}&limit={}", SKINSYNC, tab, lim))
        .timeout(std::time::Duration::from_secs(6))
        .call().map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

/// Full player profile (record + team-comp usage + recent-match history) for the click-a-name analytics.
/// Backend fetch → no CORS/CSP. Returns { found, name, wins, losses, best_combo, teams:[{team,games,wins}], recent:[…] }.
#[tauri::command]
pub fn profile(steamid: String) -> Result<serde_json::Value, String> {
    ureq::get(&format!("{}/profile?steamid={}", SKINSYNC, steamid))
        .timeout(std::time::Duration::from_secs(6))
        .call().map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

// ── real-time trace: append the app's view of (game state + its own decisions) to a log I can read ──
// One line per CHANGE (so it's readable, not a flood), size-capped. Correlate with the game to see
// exactly what the app saw and did at each moment — no guessing about the ranked flow.
fn trace(msg: &str) {
    use std::io::Write;
    let path = "C:\\g\\suite_trace.log";
    if std::fs::metadata(path).map(|m| m.len() > 1_000_000).unwrap_or(false) { let _ = std::fs::write(path, b""); }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
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

unsafe fn read_at(h: HANDLE, addr: usize, len: usize) -> Option<Vec<u8>> {
    let mut buf = vec![0u8; len];
    let mut read: usize = 0;
    if ReadProcessMemory(h, addr as *const c_void, buf.as_mut_ptr() as *mut c_void, len, Some(&mut read)).is_ok() && read > 0 {
        buf.truncate(read);
        Some(buf)
    } else { None }
}

// scan the working-buffer window for every character sig; returns hits sorted by address (one per cid)
unsafe fn full_scan(h: HANDLE) -> Vec<Found> {
    let (sigs, buckets) = sigtab();
    let mut hits: Vec<Found> = Vec::new();
    let mut seen: std::collections::HashSet<u32> = std::collections::HashSet::new();
    let mut addr = WIN_LO;
    while addr < WIN_HI {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        let got = VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>());
        if got == 0 { break; }
        let base = mbi.BaseAddress as usize;
        let size = mbi.RegionSize;
        if size == 0 { break; }
        let prot = mbi.Protect.0;
        let readable = mbi.State == MEM_COMMIT
            && (prot & PAGE_GUARD.0) == 0
            && (prot & PAGE_NOACCESS.0) == 0
            && (prot & 0xEE) != 0;
        if readable && base < WIN_HI && base + size > WIN_LO {
            let lo = base.max(WIN_LO);
            let hi = (base + size).min(WIN_HI);
            if let Some(buf) = read_at(h, lo, hi - lo) {
                if buf.len() >= 64 {
                    let end = buf.len() - 64;
                    let mut i = 0;
                    while i <= end {
                        for &si in &buckets[buf[i] as usize] {
                            let s = &sigs[si];
                            if !seen.contains(&s.cid) && buf[i..i + 64] == s.bytes {
                                seen.insert(s.cid);
                                hits.push(Found { cid: s.cid, name: s.name.clone(), addr: lo + i });
                            }
                        }
                        i += 1;
                    }
                }
            }
        }
        addr = base + size;
        if addr <= base { break; }
    }
    hits.sort_by_key(|f| f.addr);
    hits
}

// cheap confirm: are all cached sigs still resident at their known addresses?
unsafe fn confirm(h: HANDLE, roster: &[Found]) -> bool {
    let (sigs, _) = sigtab();
    for f in roster {
        let want = match sigs.iter().find(|s| s.cid == f.cid) { Some(s) => &s.bytes, None => return false };
        match read_at(h, f.addr, 64) {
            Some(b) if b.len() == 64 && &b[..] == &want[..] => {}
            _ => return false,
        }
    }
    true
}

fn roster_ids(r: &[Found]) -> Vec<u32> { r.iter().map(|f| f.cid).collect() }

// All sig occurrences in committed readable regions overlapping [lo,hi), via RPM (crash-safe: RPM
// returns an error on bad memory — it never faults the game or us, unlike in-process pointer reads).
unsafe fn rpm_occurrences(h: HANDLE, lo: usize, hi: usize) -> Vec<(usize, u32, String)> {
    let (sigs, buckets) = sigtab();
    let mut occ = Vec::new();
    let mut addr = lo;
    while addr < hi {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 { break; }
        let base = mbi.BaseAddress as usize;
        let size = mbi.RegionSize;
        if size == 0 { break; }
        let prot = mbi.Protect.0;
        let readable = mbi.State == MEM_COMMIT && (prot & PAGE_GUARD.0) == 0 && (prot & PAGE_NOACCESS.0) == 0 && (prot & 0xEE) != 0;
        if readable && base < hi && base + size > lo {
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
        addr = base + size;
        if addr <= base { break; }
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


// ── Auto local-side detection (input correlation) ──────────────────────────────────────────────────
// GGPO netplay is transparent to the emulated game, so "which side is local" isn't in DC RAM. But the LOCAL
// fighter is the one that ACTS when YOUR pad is active — so per side we track how much the fighters' state
// churns while you're inputting vs idle; the side that churns WITH your input is you. Mirror-proof (keys on
// input, not character). Read-only. The "am I inputting?" trigger comes from the local stick directly via
// XInput (offset-free, robust across game updates); we OR in flycast's host kcode[0] as a backup so keyboard
// and DirectInput players (whose pads flycast still funnels into kcode) are covered too.
const KCODE_OFF: usize = 0xac6f58;      // flycast kcode[0] offset from the game exe base (default base 0x140000000)

/// True if ANY local XInput pad (0..4) is being pressed — face buttons, d-pad, triggers, or a deflected
/// stick. This is the real local input, read straight from the OS, so it needs no game-memory offset.
fn xinput_active() -> bool {
    for i in 0..4u32 {
        let mut st = XINPUT_STATE::default();
        if unsafe { XInputGetState(i, &mut st) } == 0 {          // 0 = ERROR_SUCCESS = pad connected
            let g = st.Gamepad;
            let deflect = |v: i16| v.unsigned_abs() > 12000;
            if g.wButtons.0 != 0 || g.bLeftTrigger > 40 || g.bRightTrigger > 40
                || deflect(g.sThumbLX) || deflect(g.sThumbLY) || deflect(g.sThumbRX) || deflect(g.sThumbRY) {
                return true;
            }
        }
    }
    false
}

fn game_exe_base(pid: u32) -> usize {
    unsafe {
        let snap = match CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid) { Ok(s) => s, Err(_) => return 0 };
        let mut me = MODULEENTRY32W { dwSize: std::mem::size_of::<MODULEENTRY32W>() as u32, ..Default::default() };
        let base = if Module32FirstW(snap, &mut me).is_ok() { me.modBaseAddr as usize } else { 0 };
        let _ = CloseHandle(snap);
        base
    }
}

// ── DETERMINISTIC SIDE via Input_DEC (per-player input in DC RAM) ───────────────────────────────────
// From marvelous2 (MvC2 SH4 disasm) + maplecast shadow_exec: the game's per-player input is Input_DEC in
// emulated DC RAM — P1 @ DC 0x8C2681DC, P2 @ +0x14 (stride 0x14): +0 cur / +2 prev / +4 (cur&~prev) /
// +6 (prev&~cur), CPS2-decoded. DC RAM is a runtime MEM_PRIVATE region (earlier scans only did MEM_IMAGE →
// missed it). We scan committed memory for the invariant-shaped pairs, then over a few seconds of your
// natural play find the slot whose `cur` is a clean FUNCTION of your pad (kcode[0]) — that slot IS you.
// Deterministic, mirror-proof, dummy-proof (keys on INPUT, not animation). Read-only; bg thread; once/set.
static INPUTDEC_LOCKED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
const IDEC_STRIDE: usize = 0x14;
fn u16le(b: &[u8], o: usize) -> u16 { (b[o] as u16) | ((b[o + 1] as u16) << 8) }
fn idec_inv(cur: u16, prev: u16, ep: u16, er: u16) -> bool { ep == (cur & !prev) && er == (prev & !cur) }

// candidate P1-slot addresses across committed memory (input present → cur nonzero, input-shaped).
// GENTLE: caps candidates + total bytes (DC RAM sits in the low ~100 MB) and yields between regions so the
// scan burst can't starve the emulator of a CPU frame.
fn idec_candidates(h: HANDLE) -> Vec<usize> {
    let mut out = Vec::new(); let mut addr = 0usize; let mut scanned = 0usize;
    loop {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if unsafe { VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) } == 0 { break; }
        let b = mbi.BaseAddress as usize; let s = mbi.RegionSize; if s == 0 { break; }
        let p = mbi.Protect.0;
        let ok = mbi.State == MEM_COMMIT && (p & PAGE_GUARD.0) == 0 && (p & PAGE_NOACCESS.0) == 0 && (p & 0xEE) != 0;
        let nx = b + s; if nx <= b { break; }
        if ok && s <= 0x0400_0000 {
            if let Some(buf) = unsafe { read_at(h, b, s) } {
                let mut o = 0usize;
                while o + 8 + IDEC_STRIDE <= buf.len() {
                    let (cur, prev, ep, er) = (u16le(&buf, o), u16le(&buf, o+2), u16le(&buf, o+4), u16le(&buf, o+6));
                    if cur != 0 && cur != 0xffff && cur.count_ones() <= 8 && prev.count_ones() <= 8 && idec_inv(cur, prev, ep, er) {
                        let (c2, p2, e2, r2) = (u16le(&buf, o+0x14), u16le(&buf, o+0x16), u16le(&buf, o+0x18), u16le(&buf, o+0x1a));
                        if idec_inv(c2, p2, e2, r2) && c2.count_ones() <= 8 && p2.count_ones() <= 8 {
                            out.push(b + o);
                            if out.len() >= 3000 { return out; }
                        }
                    }
                    o += 2;
                }
                scanned += s;
                std::thread::sleep(std::time::Duration::from_millis(1));   // yield a slice back to the game
            }
        }
        if scanned > 0x1800_0000 { break; }   // ~384 MB is plenty to reach DC RAM (candidates cluster ~64-80 MB)
        addr = nx;
    }
    out
}
fn idec_pair(h: HANDLE, a: usize) -> [u16; 2] {   // both slots' cur in ONE read (halves the RPM load)
    match unsafe { read_at(h, a, IDEC_STRIDE + 2) } {
        Some(b) if b.len() >= IDEC_STRIDE + 2 => [u16le(&b, 0), u16le(&b, IDEC_STRIDE)],
        _ => [0, 0],
    }
}

// find your side by correlating each candidate slot's cur with your pad. Returns 1 (P1) or 2 (P2).
fn idec_find_side(h: HANDLE, kaddr: usize) -> Option<u8> {
    let all = idec_candidates(h);
    if all.is_empty() { return None; }
    // Pass A (light, ~0.7s): sample ALL candidates a few times, keep only the LIVE ones (cur actually varies) —
    // drops frozen rollback copies + junk from thousands to a handful, so Pass B is cheap.
    let mut seen: Vec<[std::collections::HashSet<u16>; 2]> = (0..all.len()).map(|_| [std::collections::HashSet::new(), std::collections::HashSet::new()]).collect();
    for _ in 0..12 {
        for (i, &a) in all.iter().enumerate() { let pr = idec_pair(h, a); seen[i][0].insert(pr[0]); seen[i][1].insert(pr[1]); }
        std::thread::sleep(std::time::Duration::from_millis(55));
    }
    let cands: Vec<usize> = all.iter().enumerate()
        .filter(|(i, _)| seen[*i][0].len() >= 2 || seen[*i][1].len() >= 2).map(|(_, &a)| a).collect();
    if cands.is_empty() || cands.len() > 800 { return None; }   // none live, or too noisy to trust → bail cheaply
    // Pass B: correlate the few live candidates against your pad during natural play.
    let mut samples: Vec<(u32, Vec<[u16; 2]>)> = Vec::with_capacity(70);
    for _ in 0..70 {
        let k = unsafe { rpm_u32(h, kaddr) }.unwrap_or(0);
        let row: Vec<[u16; 2]> = cands.iter().map(|&a| idec_pair(h, a)).collect();
        samples.push((k, row));
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    let kstates: std::collections::HashSet<u32> = samples.iter().map(|s| s.0).collect();
    if kstates.len() < 3 { return None; }   // need input variety
    // the slot whose cur is the cleanest FUNCTION of kcode (your input deterministically drives it) is you.
    let (mut best_score, mut best_slot) = (0i32, 0usize);
    for i in 0..cands.len() {
        let mut track = [0usize; 2];   // how cleanly cur is a FUNCTION of your kcode (your input drives it)
        let mut vary = [false; 2];     // does cur take >=2 values (this slot is an ACTIVE input)
        for s in 0..2 {
            let mut ok = 0usize;
            for &ks in &kstates {
                let mut vc: std::collections::HashMap<u16, usize> = std::collections::HashMap::new(); let mut tot = 0;
                for (k, row) in &samples { if *k == ks { *vc.entry(row[i][s]).or_insert(0) += 1; tot += 1; } }
                if tot < 2 { continue; }
                if *vc.values().max().unwrap() * 100 >= tot * 80 { ok += 1; }
            }
            let distinct: std::collections::HashSet<u16> = samples.iter().map(|(_, r)| r[i][s]).collect();
            vary[s] = distinct.len() >= 2;
            track[s] = ok;
        }
        let (me, other) = if track[0] >= track[1] { (0, 1) } else { (1, 0) };
        // ★ PORT-INDEXED requirement: your slot tracks your pad AND the OTHER slot is an ACTIVE input that
        // does NOT track your pad (= the opponent). This rejects side-agnostic LOCAL input buffers (whose
        // other slot is empty/a copy) — those always read as P1 and were the wrong-side bug.
        if track[me] >= 3 && vary[other] && (track[other] as i32) < (track[me] as i32) - 1 {
            let score = track[me] as i32 * 2 - track[other] as i32;   // prefer clean me + independent opponent
            if score > best_score { best_score = score; best_slot = me; }
        }
    }
    if best_score > 0 { Some((best_slot + 1) as u8) } else { None }
}

// ★ Authoritative local side straight from the LIVE fighter structs the reader already located — no memory
// scan. Found empirically from a full-set recording (slana): each fighter's input register @ struct +0x4FC is
// a clean FUNCTION of that side's pad, so over a few seconds of your natural play the LOCAL side's fighters'
// +0x4FC track your kcode (deterministically) while the remote side carries network input. The player whose
// input is the cleaner function of your pad IS you. Mirror-proof; keys on INPUT, not animation.
const OFF_INPUT: usize = 0x4fc;
fn struct_side_detect(h: HANDLE, kaddr: usize, fighters: &[(u8, usize)]) -> Option<u8> {
    if !fighters.iter().any(|(p, _)| *p == 1) || !fighters.iter().any(|(p, _)| *p == 2) { return None; }
    let mut samples: Vec<(u32, Vec<u16>)> = Vec::with_capacity(70);
    for _ in 0..70 {
        let k = unsafe { rpm_u32(h, kaddr) }.unwrap_or(0);
        let row: Vec<u16> = fighters.iter().map(|&(_, a)| unsafe { read_at(h, a + OFF_INPUT, 2) }.map(|b| u16le(&b, 0)).unwrap_or(0)).collect();
        samples.push((k, row));
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    let kstates: std::collections::HashSet<u32> = samples.iter().map(|s| s.0).collect();
    if kstates.len() < 3 { return None; }   // need input variety to correlate
    let mut track = [0i32; 3]; let mut vary = [false; 3];
    for (fi, &(pl, _)) in fighters.iter().enumerate() {
        if pl != 1 && pl != 2 { continue; }
        let mut ok = 0i32;
        for &ks in &kstates {
            let mut vc: std::collections::HashMap<u16, usize> = std::collections::HashMap::new(); let mut tot = 0;
            for (k, row) in &samples { if *k == ks { *vc.entry(row[fi]).or_insert(0) += 1; tot += 1; } }
            if tot >= 2 && *vc.values().max().unwrap() * 100 >= tot * 80 { ok += 1; }   // same kcode ⇒ same input
        }
        let distinct: std::collections::HashSet<u16> = samples.iter().map(|(_, r)| r[fi]).collect();
        if distinct.len() >= 2 { vary[pl as usize] = true; }
        track[pl as usize] += ok;
    }
    if track[1] >= track[2] + 2 && vary[1] { Some(1) }
    else if track[2] >= track[1] + 2 && vary[2] { Some(2) }
    else { None }
}

fn start_inputdec_detector() {
    std::thread::spawn(|| {
        let mut cur_pid = 0u32; let mut cur_opp = String::new();
        let mut next_try = std::time::Instant::now();     // cooldown gate so a failed lock can't re-scan in a tight loop
        loop {
            std::thread::sleep(std::time::Duration::from_millis(1500));
            // side is a NETPLAY concept — only run in a live match with a real opponent; re-derive per new set.
            let (in_match, opp) = { let s = snapshot().lock().unwrap();
                (s.game.as_ref().map(|g| g.in_match == 1).unwrap_or(false),
                 s.opponent.as_ref().map(|o| o.0.clone()).unwrap_or_default()) };
            if !in_match || opp.is_empty() { continue; }
            let pid = match find_game_pid() { Some(p) => p, None => continue };
            if pid != cur_pid || opp != cur_opp {   // new game / new opponent (new set) → re-derive
                cur_pid = pid; cur_opp = opp; INPUTDEC_LOCKED.store(false, std::sync::atomic::Ordering::Relaxed);
                next_try = std::time::Instant::now();
            }
            if INPUTDEC_LOCKED.load(std::sync::atomic::Ordering::Relaxed) { continue; }   // locked this set → hold
            if std::time::Instant::now() < next_try { continue; }                          // in cooldown → don't scan
            let base = game_exe_base(pid); if base == 0 { continue; }
            let h = match unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) } { Ok(h) => h, Err(_) => continue };
            // PRIMARY: the proven struct-based read (+0x4FC on the located fighters); FALLBACK: the old scan.
            let fighters: Vec<(u8, usize)> = { let s = snapshot().lock().unwrap();
                s.game.as_ref().map(|g| g.slots.iter().map(|sl| (sl.player, sl.addr)).collect()).unwrap_or_default() };
            let found = struct_side_detect(h, base + KCODE_OFF, &fighters)
                .or_else(|| idec_find_side(h, base + KCODE_OFF));
            if let Some(side) = found {
                snapshot().lock().unwrap().local_side = side;
                INPUTDEC_LOCKED.store(true, std::sync::atomic::Ordering::Relaxed);
                trace(&format!("[side] locked deterministic side = P{side} (struct +0x4fc)"));
            } else {
                next_try = std::time::Instant::now() + std::time::Duration::from_secs(15);  // failed → back off 15s
            }
            unsafe { let _ = CloseHandle(h); }
        }
    });
}

fn start_side_detector() {
    std::thread::spawn(|| {
        let mut cur_pid = 0u32; let mut exe_base = 0usize;
        let mut last: [Option<Vec<u8>>; 6] = Default::default();
        let (mut act, mut idl) = ([0f64; 2], [0f64; 2]);
        let (mut an, mut idn) = (0u32, 0u32);
        loop {
            std::thread::sleep(std::time::Duration::from_millis(60));
            // fighter cluster addresses + side (0/1), from the shared snapshot (set by the reader thread)
            let fighters: Vec<(usize, usize)> = {
                let s = snapshot().lock().unwrap();
                match s.game.as_ref() {
                    Some(g) if g.in_match == 1 => g.slots.iter().filter(|x| x.addr != 0)
                        .map(|x| ((x.player.saturating_sub(1)) as usize, x.addr)).collect(),
                    _ => Vec::new(),
                }
            };
            if fighters.is_empty() { last = Default::default(); act = [0.0; 2]; idl = [0.0; 2]; an = 0; idn = 0; continue; }
            let pid = match find_game_pid() { Some(p) => p, None => continue };
            if pid != cur_pid { cur_pid = pid; exe_base = game_exe_base(pid); last = Default::default(); act = [0.0; 2]; idl = [0.0; 2]; an = 0; idn = 0;
                snapshot().lock().unwrap().local_side = 0; }   // fresh game → re-detect from scratch (keeps side across between-games churn)
            let h = match unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) } { Ok(h) => h, Err(_) => continue };
            // primary trigger: the local stick, straight from Windows (offset-free, no game memory needed).
            // backup: flycast's host kcode[0] at the known offset — covers keyboard / DirectInput pads that
            // XInput can't see (only consulted when the module base resolved).
            let active = xinput_active()
                || (exe_base != 0 && unsafe { rpm_u32(h, exe_base + KCODE_OFF) }.unwrap_or(0) != 0);
            for (i, (side, cl)) in fighters.iter().enumerate().take(6) {
                let cur = unsafe { read_at(h, cl + 0x100, 0x300) };  // action/animation region of the struct
                if let (Some(c), Some(p)) = (&cur, &last[i]) {
                    if c.len() == p.len() {
                        let churn = c.iter().zip(p).filter(|(a, b)| a != b).count() as f64;
                        if *side < 2 { if active { act[*side] += churn; } else { idl[*side] += churn; } }
                    }
                }
                last[i] = cur;
            }
            if active { an += 1; } else { idn += 1; }
            unsafe { let _ = CloseHandle(h); }
            // Evaluate once we have some of BOTH input-active and idle samples. Score each side by how much
            // MORE it churns while I'm inputting vs idle, NORMALIZED (robust to animation size): my fighter
            // reacts to my pad, the opponent's churn is independent of it.
            if an >= 12 && idn >= 8 {
                let ex = |sd: usize| {                            // normalized input-correlation in ~[-1,1]
                    let a = act[sd] / an as f64; let i = idl[sd] / idn as f64;
                    (a - i) / (a + i + 1.0)
                };
                let (e0, e1) = (ex(0), ex(1));
                let (win, win_e, lose_e) = if e0 >= e1 { (1u8, e0, e1) } else { (2u8, e1, e0) };
                // churn is only a FALLBACK now — if the deterministic Input_DEC detector has locked the side,
                // don't let the (fuzzier) churn signal overwrite it.
                if win_e > 0.10 && (win_e - lose_e) > 0.06 && !INPUTDEC_LOCKED.load(std::sync::atomic::Ordering::Relaxed) {
                    let mut s = snapshot().lock().unwrap();
                    // hysteresis: flipping an already-locked side needs a bigger margin than the first lock,
                    // so brief cross-talk (I get hit while idle, etc.) can't flip-flop the answer.
                    let need = if s.local_side != 0 && s.local_side != win { 0.15 } else { 0.06 };
                    if (win_e - lose_e) >= need { s.local_side = win; }
                }
                for x in act.iter_mut().chain(idl.iter_mut()) { *x *= 0.6; } an = an * 3 / 5; idn = idn * 3 / 5;  // decay → keeps adapting
            }
        }
    });
}

// LIVENESS: a live match's fighter animation changes every frame. Hash a volatile slice of each fighter's
// struct; if it's byte-identical across reader cycles the buffer is FROZEN (menus / match over / a stale
// base still pointing at an old match), so we must NOT report it as a live match — that is the root of the
// "detects old matches" bug. Returns 0 if nothing readable.
fn game_liveness_hash(pid: u32, game: &GameSt) -> u64 {
    let h = match unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) } { Ok(h) => h, Err(_) => return 0 };
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
    unsafe { let _ = CloseHandle(h); }
    if any { hh } else { 0 }
}

/// The single reader thread. Reads the game's memory DIRECTLY via read-only RPM (no hook, no IPC files) —
/// roster / side / opponent / health all come from cross-process reads on this one thread, so all heavy
/// work is OFF the Tauri IPC path and no command can ever block the UI. Spawned once at app startup.
pub fn start_reader() {
    start_side_detector();          // churn fallback (fuzzy)
    start_inputdec_detector();      // ★ deterministic side via Input_DEC (authoritative once locked)
    std::thread::spawn(|| {
        let mut cur_pid: u32 = 0;
        let mut handle: Option<HANDLE> = None;
        let mut roster: Vec<Found> = Vec::new();
        let mut stable: u32 = 0;
        let mut work: Option<(usize, usize)> = None; // located team region (cheap-tracked between relocates)
        let mut empty_streak: u32 = 0;               // consecutive empty track cycles before a wide relocate
        let mut opp: Option<(String, String)> = None;
        let mut opp_backoff: i32 = 0;
        let mut opp_pending: Option<String> = None;  // a DIFFERENT candidate id; must persist 2 scans to swap (anti-flip)
        let mut sess_key = String::new();
        let mut ss = ScoreState::default();          // per-set score, keyed to the sticky opponent
        let mut last_active = std::time::Instant::now(); // last time fighters were loaded / in a match
        let mut prev_live_hash = 0u64; let mut frozen_cycles = 0u32; // liveness gate (drop frozen/stale match data)
        let mut prev_log = String::new();            // last trace line (log only on change)
        let mut last_find = std::time::Instant::now() - std::time::Duration::from_secs(10); // find_array throttle
        let mut ram_base: usize = 0;                 // located player-array base (0 = not yet found; volatile per match)
        const OUT_TIMEOUT: u64 = 40;                 // sec fully-gone before dropping — long enough to survive a slow
                                                     // char-select (part of the set); a DIFFERENT opponent still
                                                     // switches instantly, so this only ever shows a stale name if
                                                     // you sit at the true main menu (harmless).
        loop {
            // (re)acquire the process handle; drop it if the game is gone
            match find_game_pid() {
                Some(p) => {
                    if p != cur_pid || handle.is_none() {
                        if let Some(old) = handle.take() { unsafe { let _ = CloseHandle(old); } }
                        handle = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, p).ok() };
                        cur_pid = p; roster.clear(); work = None; opp = None; sess_key.clear(); ram_base = 0;
                    }
                }
                None => {
                    if let Some(old) = handle.take() { unsafe { let _ = CloseHandle(old); } }
                    cur_pid = 0; roster.clear(); work = None; opp = None; ss = ScoreState::default();
                    { let mut s = snapshot().lock().unwrap(); s.state = "game_off".into(); s.roster.clear(); s.opponent = None; s.game = None; s.score = (0, 0); }
                    if prev_log != "GAME_OFF" { prev_log = "GAME_OFF".into(); trace("[game_off] game closed → cleared roster/opponent/score"); }
                    std::thread::sleep(std::time::Duration::from_millis(1000));
                    continue;
                }
            }
            let h = match handle { Some(h) => h, None => { std::thread::sleep(std::time::Duration::from_millis(1000)); continue; } };

            // roster + mode — LAYOUT-INDEPENDENT (robust to per-launch ASLR of the guest RAM):
            // cheaply re-scan the located team region each cycle; only if it stays empty for 2 cycles do
            // a bounded wide relocate. The wide scan therefore never fires mid-match (buffers are stable
            // there) — it only runs at menus/match-start, so it can't hitch live gameplay.
            let mut team = if let Some((lo, hi)) = work { pick_working(unsafe { rpm_occurrences(h, lo, hi) }) } else { Vec::new() };
            if team.is_empty() {
                empty_streak += 1;
                if work.is_none() || empty_streak >= 2 {
                    team = pick_working(unsafe { rpm_occurrences(h, 0x0200_0000, 0x4000_0000) });
                    work = match (team.first(), team.last()) {
                        (Some(f), Some(l)) => Some((f.addr.saturating_sub(0x10_0000), l.addr + 0x10_0000)),
                        _ => None,
                    };
                    empty_streak = 0;
                }
            } else { empty_streak = 0; }
            let n = team.len();
            let same = roster_ids(&team) == roster_ids(&roster);
            if same && n > 0 { stable = stable.saturating_add(1); } else { stable = 1; }
            let state = if n == 0 { "menu" } else if n >= 6 && stable >= 2 { "match" } else { "select" }.to_string();
            roster = team;

            // opponent: STICKY across a set. Looked for only while fighters are loaded (n>0). Once locked we
            // HOLD it — a DIFFERENT candidate must appear in TWO consecutive scans before we swap, so a single
            // between-games ranking wobble can never flip the opponent (which used to reset the set score). A
            // sustained out-of-match stretch (set over / matchmaking) clears it via the OUT_TIMEOUT below, which
            // re-enables an immediate fresh lock for the next opponent.
            let _ = &sess_key;
            if n > 0 && opp_backoff <= 0 {
                let my_id = read_self_id().unwrap_or(0);
                let my_nm = read_self_name();
                // opponent is NEVER us: scan already drops our SteamID; here we also drop any candidate whose
                // co-located persona name is ours (cache noise), so we never lock "ourselves" as the opponent.
                match scan(cur_pid, my_id).into_iter()
                    .find(|c| plausible_opponent_name(&c.name) && (my_nm.is_empty() || c.name.trim().to_lowercase() != my_nm)) {
                    Some(c) => {
                        match &opp {
                            None => { opp = Some((c.steamid.clone(), c.name.clone())); opp_pending = None; } // first lock
                            Some(o) if o.0 == c.steamid => { opp_pending = None; }                           // still them → confirm
                            Some(_) => {                                                                     // a DIFFERENT id…
                                if opp_pending.as_deref() == Some(c.steamid.as_str()) {                      // …seen twice → real change
                                    opp = Some((c.steamid.clone(), c.name.clone())); opp_pending = None;
                                } else { opp_pending = Some(c.steamid.clone()); }                            // …first sighting → wait
                            }
                        }
                        opp_backoff = 20;                 // have someone → re-check slowly
                    }
                    None => opp_backoff = if opp.is_some() { 20 } else { 3 }, // not found → retry FAST until we lock
                }
            }
            if opp_backoff > 0 { opp_backoff -= 1; }

            // Game state: auto-find + read the reversed player array via read-only RPM. The heavy find is
            // attempted only when fighters are loaded (n>0) and throttled; once found, the volatile base is
            // re-validated & read cheaply.
            let game = read_gamestate_rpm(cur_pid, &mut ram_base, &mut last_find, n > 0);
            // ── LIVENESS GATE ── drop game data that isn't actively updating. A live fight animates every
            // frame, so a hash that's unchanged across cycles = a FROZEN buffer (menu / match over / stale
            // base) → treat as NO live match, so we never surface an old match's roster/opponent/side.
            let game = match game {
                Some(g) => {
                    let hh = game_liveness_hash(cur_pid, &g);
                    if hh != 0 && hh == prev_live_hash { frozen_cycles = frozen_cycles.saturating_add(1); }
                    else { frozen_cycles = 0; prev_live_hash = hh; }
                    // ~1.2s byte-identical → not a live match. Drop the base too, so the next find re-acquires
                    // a LIVE one (find_array now prefers an animating base) instead of clinging to the frozen copy.
                    if frozen_cycles >= 3 { ram_base = 0; None } else { Some(g) }
                }
                None => { frozen_cycles = 0; None }
            };
            // Hold the opponent while EITHER the game reads live OR fighters are present (sig-scan roster n) —
            // robust to a flaky reversed-struct read so we never drop + re-hunt the opponent mid-set. Drop
            // only after a sustained gone stretch (set over / menus).
            let active = game.as_ref().map(|g| g.in_match == 1).unwrap_or(false) || n > 0;
            if active { last_active = std::time::Instant::now(); }
            else if opp.is_some() && last_active.elapsed().as_secs() > OUT_TIMEOUT { opp = None; }
            update_score(&mut ss, &game, &opp, snapshot().lock().unwrap().local_side);
            write_fighters(&game);
            let sc = (ss.p1, ss.p2);
            trace_cycle(&mut prev_log, "rpm", &state, &roster, &opp, &game, sc);

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
            }

            // adaptive cadence: fast cheap region-tracking when we have the team; back off at menus
            // (where the wide relocate runs) so idle scanning stays light
            std::thread::sleep(std::time::Duration::from_millis(if roster.is_empty() { 2000 } else { 400 }));
        }
    });
}

/// O(1) read of the snapshot. { state, p1[], p2[], count, changed } plus the real game state
/// (in_match / match_state / stage + per-slot char/color/health) whenever the hook is injected.
#[tauri::command]
pub fn detect_state() -> serde_json::Value {
    let s = snapshot().lock().unwrap();
    let to_json = |r: &[Found]| serde_json::Value::Array(r.iter().map(|f| serde_json::json!({
        "cid": f.cid, "name": f.name, "addr": format!("{:x}", f.addr)
    })).collect());
    let p1: Vec<Found> = s.roster.iter().take(3).cloned().collect();
    let p2: Vec<Found> = s.roster.iter().skip(3).take(3).cloned().collect();
    let mut out = serde_json::json!({ "state": s.state, "count": s.roster.len(), "changed": false, "p1": to_json(&p1), "p2": to_json(&p2), "has_game": false,
        "score": { "p1": s.score.0, "p2": s.score.1 }, "local_side": s.local_side });
    if let Some(g) = s.game.as_ref() {
        let slots: Vec<serde_json::Value> = g.slots.iter().map(|sl| serde_json::json!({
            "player": sl.player, "pos": sl.pos, "cid": sl.char_id, "color": sl.color, "health": sl.health,
            "datpal": format!("{:x}", sl.datpal), "sig": pal_sig(&sl.pal)
        })).collect();
        // ground-truth screen: in_match (any fighter with live health) is the definitive "fight is live"
        // flag. The array only exists once fighters are loaded, so a non-empty slots list that isn't yet
        // in a live fight = character-select / versus / loading. (char_id 0 is Ryu — a valid fighter.)
        let screen = if g.in_match == 1 { "match" }
            else if !g.slots.is_empty() { "select" }
            else { "menu" };
        out["has_game"] = serde_json::json!(true);
        out["in_match"] = serde_json::json!(g.in_match);
        out["match_state"] = serde_json::json!(g.match_state);
        out["stage"] = serde_json::json!(g.stage);
        out["timer"] = serde_json::json!(g.timer);
        out["frame"] = serde_json::json!(g.frame);
        out["screen"] = serde_json::json!(screen);
        out["slots"] = serde_json::json!(slots);
    }
    out
}

/// O(1) read of the on-screen fighters' live palettes (used by capture_live) — straight from the RPM-read
/// slot palettes already in the snapshot, expanded to the hook's RRGGBBAA sig format. No hook, no file.
pub fn live_palettes() -> Vec<String> {
    let s = snapshot().lock().unwrap();
    let mut out = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    if let Some(g) = s.game.as_ref() {
        for sl in &g.slots {
            let sig = pal_sig(&sl.pal);
            if !sig.is_empty() && seen.insert(sig.clone()) { out.push(sig); }
        }
    }
    out
}

// ── PER-SIDE LIVE PAINT (WriteProcessMemory) ──────────────────────────────────────────────────────
// The reversed struct gives each fighter a DISTINCT DatPal address (P1 vs P2, ~0x3f0000 apart), so we
// can recolor exactly ONE side — even an identical same-colour mirror — by writing the skin straight into
// that fighter's guest palette. MvC2 has 6 button colours (0x100 apart) plus attack/effect sub-palettes
// after 0x600; we auto-detect EVERY real palette row (colour0 transparent + varied, mostly-opaque colours)
// across 0..0x2000 and write the skin to each, so nothing flashes back on specials. Cosmetic working-buffer
// data — safe offline. NOTE: this is the only place the app WRITES game memory; everything else is read-only.
fn is_real_row(b: &[u8]) -> bool {
    if b.len() < 32 { return false; }
    let c0 = (b[0] as u16) | ((b[1] as u16) << 8);
    if (c0 >> 12) != 0 { return false; }                       // colour0 must be transparent
    let cols: Vec<u16> = (1..16).map(|i| (b[i*2] as u16) | ((b[i*2+1] as u16) << 8)).collect();
    let mut d = cols.clone(); d.sort(); d.dedup();
    d.len() >= 4 && cols.iter().filter(|&&c| (c >> 12) == 0xf).count() >= 8
}
// 16 RGB colours (0xRRGGBB) → a 32-byte ARGB4444 row (colour0 transparent, rest opaque).
fn skin_row(colors: &[u32]) -> [u8; 32] {
    let mut row = [0u8; 32];
    for i in 1..16 {
        let c = colors.get(i).copied().unwrap_or(0);
        let (r, g, b) = ((c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff);
        let v: u16 = 0xf000 | (((r >> 4) as u16) << 8) | (((g >> 4) as u16) << 4) | ((b >> 4) as u16);
        row[i*2] = (v & 0xff) as u8; row[i*2+1] = (v >> 8) as u8;
    }
    row
}
#[derive(serde::Deserialize)]
pub struct PaintTarget { pub datpal: String, pub colors: Vec<u32> }

// real-row offsets cached per DatPal so the per-poll re-apply writes directly (no 256-row rescan each time)
fn row_cache() -> &'static Mutex<HashMap<usize, Vec<usize>>> {
    static C: OnceLock<Mutex<HashMap<usize, Vec<usize>>>> = OnceLock::new();
    C.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Drop the cached per-DatPal real-row offsets. Called on each new match/select — DatPals relocate per match,
/// so the next paint re-scans fresh rather than trusting stale offsets. (Replaces the old hook region reset.)
pub fn clear_row_cache() { row_cache().lock().unwrap().clear(); }

/// Write each target skin (16 RGB colours) into every real palette row of that fighter's DatPal block.
/// `targets` come from the frontend per poll: one per on-screen fighter that should be skinned, already
/// resolved to the correct SIDE (your skins → your datpal, synced opponent skins → their datpal).
#[tauri::command]
pub fn paint_palettes(targets: Vec<PaintTarget>) -> Result<String, String> {
    if targets.is_empty() { return Ok("0".into()); }
    let pid = find_game_pid().ok_or("game not found")?;
    let h = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, FALSE, pid) }
        .map_err(|e| e.to_string())?;
    let mut rows = 0usize;
    for t in &targets {
        let dp = usize::from_str_radix(t.datpal.trim_start_matches("0x"), 16).unwrap_or(0);
        if dp == 0 || t.colors.len() < 16 || !is_wb(dp as u32) { continue; }
        let row = skin_row(&t.colors);
        // real-row offsets: cached per DatPal — scan the 256 rows ONCE, then re-apply writes directly.
        let offsets: Vec<usize> = {
            let mut c = row_cache().lock().unwrap();
            if c.len() > 64 { c.clear(); }                 // DatPals are volatile per match → bound the cache
            match c.get(&dp) {
                Some(v) => v.clone(),
                None => {
                    let mut v = Vec::new();
                    for off in (0..0x2000usize).step_by(0x20) {
                        if let Some(orig) = unsafe { read_at(h, dp + off, 32) } { if is_real_row(&orig) { v.push(off); } }
                    }
                    c.insert(dp, v.clone()); v
                }
            }
        };
        if offsets.is_empty() { continue; }
        // ── SAFETY GATE (prevents crashing the game) ──────────────────────────────────────────────────
        // The DatPal base is VOLATILE per match; a cached/relocated address can end up pointing at unrelated
        // game memory. Writing there corrupts the process and crashes it. So we NEVER write blind: read the
        // head row first and require it to STILL be a live palette. If it's unreadable or no longer
        // palette-shaped, the address is stale → drop the cache entry and skip entirely (re-scan fresh next
        // tick). If it already equals our skin, the skin is still on → skip the writes.
        match unsafe { read_at(h, dp + offsets[0], 32) } {
            Some(cur) if is_real_row(&cur) => { if cur.as_slice() == &row[..] { continue; } } // still live & applied
            _ => { row_cache().lock().unwrap().remove(&dp); continue; }                        // stale/invalid → do NOT write
        }
        for off in offsets {
            let mut w = 0usize;
            unsafe { let _ = WriteProcessMemory(h, (dp + off) as *const c_void, row.as_ptr() as *const c_void, 32, Some(&mut w)); }
            if w == 32 { rows += 1; }
        }
    }
    unsafe { let _ = CloseHandle(h); }
    Ok(rows.to_string())
}

