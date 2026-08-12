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
use windows::Win32::System::Memory::{VirtualQueryEx, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_GUARD, PAGE_NOACCESS, PAGE_READWRITE};
use windows::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
use windows::Win32::UI::Input::XboxController::{XInputGetState, XINPUT_STATE};
use windows::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W, TH32CS_SNAPPROCESS,
    Module32FirstW, MODULEENTRY32W, TH32CS_SNAPMODULE,
};

const SKINSYNC: &str = "https://nobd.net/skinsync";
const STEAMID_HI: u32 = 0x0110_0001; // universe=public, type=individual, instance=desktop

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
    let r = ureq::post(url);
    match auth_token() { Some(t) => r.set("Authorization", &format!("Bearer {}", t)), None => r }
}

/// Register this install with the server (once per SteamID) and cache the returned token. Idempotent — a
/// no-op when we already hold a token for this SteamID. Safe to call often; called as soon as the local
/// SteamID is known (startup, from the Steam registry — no game needed).
#[tauri::command]
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

// Printable-ASCII run near an address — the opponent's persona sits right beside its SteamID in the session.
fn name_near_rpm(h: HANDLE, addr: usize) -> String {
    let buf = match unsafe { read_window(h, addr.saturating_sub(0x40), 0xC0) } { Some(b) => b, None => return String::new() };
    let (mut best, mut cur) = (String::new(), String::new());
    for &c in &buf { if (0x20..0x7f).contains(&c) { cur.push(c as char); } else { if cur.len() > best.len() { best = cur.clone(); } cur.clear(); } }
    if cur.len() > best.len() { best = cur; }
    let t = best.trim().to_string();
    if t.len() >= 3 && plausible_opponent_name(&t) { t } else { String::new() }
}

// Scan ONE committed region for SteamID64s → collect our-id addresses + candidate-id addresses.
// CHUNKED reads (a whole-region read fails if ANY page inside is unreadable → silently drops the region that
// holds the session struct). STEP BY 4: the paired SteamIDs are 4-aligned but NOT 8-aligned (ours @ 0x..2ac,
// opp @ 0x..41c), so an i+=8 walk from an 8-aligned base steps right over every pairing.
unsafe fn scan_region_sids(h: HANDLE, base: usize, size: usize, my_id: u64,
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
unsafe fn name_of_opp(h: HANDLE, opp_addrs: &[usize]) -> String {
    let mut counts: HashMap<String, u32> = HashMap::new();
    for &a in opp_addrs { let nm = name_near_rpm(h, a); if !nm.is_empty() { *counts.entry(nm).or_insert(0) += 1; } }
    counts.into_iter().max_by_key(|(_, c)| *c).map(|(n, _)| n).unwrap_or_default()
}
// Turn a completed scan (my id addresses + candidate opp ids) into (opp_id, name, side) + refresh the caches.
unsafe fn finish_opp(h: HANDLE, my_addrs: &[usize], cand: &HashMap<u64, Vec<usize>>,
                     region: &mut Option<(usize, usize)>, cache: &mut Option<(usize, u8, String)>) -> Option<(u64, String, u8)> {
    best_pair(my_addrs, cand).map(|(sid, na)| {
        let opp_addrs = cand.get(&sid).cloned().unwrap_or_default();
        let side = detect_side(my_addrs, &opp_addrs);
        let name = name_of_opp(h, &opp_addrs);   // resolved once from the most-common copy; cached below
        *cache = Some((na, side, name.clone()));
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if VirtualQueryEx(h, Some(na as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) != 0 && mbi.RegionSize != 0 {
            *region = Some((mbi.BaseAddress as usize, mbi.RegionSize));
        }
        (sid, name, side)
    })
}

// DETERMINISTIC opponent + side. Three tiers, fastest first: FAST (cached slot, re-validated) → WARM (cached
// region scan) → COLD (full sweep, first lock of a launch). Returns (opp_id, name, local_side 1/2/0).
fn find_opponent_netplay(pid: u32, my_id: u64, cache: &mut Option<(usize, u8, String)>, region: &mut Option<(usize, usize)>) -> Option<(u64, String, u8)> {
    if pid == 0 || my_id == 0 { return None; }
    unsafe {
        let h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid).ok()?;
        // 1. FAST PATH — cached slot, RE-VALIDATING THE PAIRING: the opponent is live only while OUR id is still
        //    co-located within 0x400 (a freed-but-not-zeroed slot lingers → returned the GHOST opponent forever).
        //    Returns the CACHED name (resolved once from the best copy) — don't re-scrape a single slot each cycle
        //    (that clobbered the good name with whatever junk sat next to this particular copy).
        if let Some((a, side, cached_name)) = cache.clone() {
            let v = read_window(h, a, 8).map(|b| u64::from_le_bytes([b[0],b[1],b[2],b[3],b[4],b[5],b[6],b[7]])).unwrap_or(0);
            if (v >> 32) as u32 == STEAMID_HI && v != my_id {
                let lo = a.saturating_sub(0x400);
                let paired = read_window(h, lo, 0x808).map_or(false, |w| {
                    let mut i = 0usize;
                    while i + 8 <= w.len() {
                        if u64::from_le_bytes([w[i],w[i+1],w[i+2],w[i+3],w[i+4],w[i+5],w[i+6],w[i+7]]) == my_id { return true; }
                        i += 4;
                    }
                    false
                });
                if paired { let _ = CloseHandle(h); return Some((v, cached_name, side)); }
            }
            *cache = None;   // pairing gone (set over / new session) → fall through to WARM / COLD
        }
        // 2. WARM PATH — remembered region only.
        if let Some((rb, rs)) = *region {
            let mut my_addrs: Vec<usize> = Vec::new();
            let mut cand: HashMap<u64, Vec<usize>> = HashMap::new();
            scan_region_sids(h, rb, rs, my_id, &mut my_addrs, &mut cand);
            if let Some(r) = finish_opp(h, &my_addrs, &cand, region, cache) { let _ = CloseHandle(h); return Some(r); }
            // stale region (new session elsewhere) → fall through to the full sweep, which refreshes it
        }
        // 3. COLD PATH — full committed-memory sweep.
        let mut my_addrs: Vec<usize> = Vec::new();
        let mut cand: HashMap<u64, Vec<usize>> = HashMap::new();
        let mut addr = 0usize;
        loop {
            let mut mbi = MEMORY_BASIC_INFORMATION::default();
            if VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 { break; }
            let base = mbi.BaseAddress as usize; let size = mbi.RegionSize; if size == 0 { break; }
            let p = mbi.Protect.0;
            let ok = mbi.State == MEM_COMMIT && (p & PAGE_GUARD.0) == 0 && (p & PAGE_NOACCESS.0) == 0 && (p & 0xEE) != 0;
            if ok { scan_region_sids(h, base, size, my_id, &mut my_addrs, &mut cand); }
            let nx = base + size; if nx <= base { break; } addr = nx;
        }
        let out = finish_opp(h, &my_addrs, &cand, region, cache);
        let _ = CloseHandle(h);
        out
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

// Manual side override (the You:P1/P2 toggle). 0 = auto (use the input-correlation detector), 1 = P1, 2 = P2.
// Wins over auto-detection for BOTH team labels and stats attribution; auto-cleared when the opponent changes.
#[tauri::command]
pub fn set_manual_side(side: u8) -> Result<(), String> {
    if side > 2 { return Err("side must be 0, 1 or 2".into()); }
    let mut s = snapshot().lock().unwrap();
    s.manual_side = side;
    s.side_confirmed = side != 0;   // user picked a side → CONFIRMED → buffered games flush + future games record
    Ok(())
}

#[tauri::command]
pub fn sync_publish(steamid: String, name: String, skins: serde_json::Value, effect: Option<String>) -> Result<serde_json::Value, String> {
    let body = serde_json::json!({ "steamid": steamid, "name": name, "skins": skins, "effect": effect });
    auth_post(&format!("{}/publish", SKINSYNC)).send_json(body)
        .map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

#[tauri::command]
pub fn sync_unpublish(steamid: String) -> Result<(), String> {
    let mut r = ureq::delete(&format!("{}/publish?id={}", SKINSYNC, steamid));
    if let Some(t) = auth_token() { r = r.set("Authorization", &format!("Bearer {}", t)); }
    r.call().map_err(|e| e.to_string())?;
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
    auth_post(&format!("{}/heartbeat", SKINSYNC)).send_json(serde_json::json!({ "id": id, "name": name }))
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
}
// The side used for team-labeling + stats: the manual override wins; else the auto-detector.
fn effective_side(s: &Snapshot) -> u8 { if s.manual_side != 0 { s.manual_side } else { s.local_side } }
fn snapshot() -> &'static Mutex<Snapshot> {
    static S: OnceLock<Mutex<Snapshot>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(Snapshot { state: "game_off".into(), roster: Vec::new(), opponent: None, game: None, score: (0, 0), local_side: 0, manual_side: 0, side_confirmed: false, in_session: false, paint_slots: Vec::new(), ram_base: 0 }))
}

// Per-fighter live state (the 6 fighter slots: char_id, palette colour index, health, DatPal, and the live
// 16-colour palette) read DIRECTLY from the game's player array via read-only RPM — ground truth from
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
const OFF_COMBO:  usize = 0x1ca;    // combo this fighter is dealing; +0x902 = received
const OFF_COMBO_RECV: usize = 0x902; // combo this fighter is RECEIVING (the +0x902 pair to OFF_COMBO)
const OFF_POS_X:  usize = 0x61c;    // fighter world X (f32) — per ranked_capture schema
const OFF_POS_Y:  usize = 0x620;    // fighter world Y (f32)
const OFF_ASSIST: usize = 0x4e9;    // assist type per fighter: alpha=0 beta=1 gamma=2 (confirmed live 2026-08-11 vs ground truth on 2 array bases; DC +0x4C9 does NOT map)
// ── additional per-fighter match-state fields ──
const OFF_XVEL:   usize = 0x644;    // x velocity (f32)
const OFF_YVEL:   usize = 0x648;    // y velocity (f32)
const OFF_REDHP:  usize = 0xb48;    // recoverable health (u16) = health+4
const OFF_FACING: usize = 0x720;    // facing (u8) 0/1
const OFF_HITSTUN:usize = 0x909;    // hitstun flag (u8) 0xFF while in hitstun, 0 otherwise
const OFF_ACTION: usize = 0x76c;    // action/move-phase state (u8)
const MET_BARS:   usize = 0x2e636;  // P1 meter bars 0-5 (relative to the array base `ram`); P2 = +1 (adjacent, per DC layout)
const MET_FILL:   usize = 0x2e658;  // P1 meter fine fill (u16) — confirmed +1 per Magneto LP
const HP_FULL: u16 = 144;
const MAX_CID: u8 = 0x3A;          // Servbot = highest CPS2 unit id (58)

unsafe fn rpm_u8(h: HANDLE, a: usize) -> Option<u8> { read_at(h, a, 1).filter(|b| b.len() >= 1).map(|b| b[0]) }
#[allow(dead_code)] // red-health (health+4) reader — kept for future use
unsafe fn rpm_u16(h: HANDLE, a: usize) -> Option<u16> { read_at(h, a, 2).filter(|b| b.len() >= 2).map(|b| b[0] as u16 | ((b[1] as u16) << 8)) }
unsafe fn rpm_u32(h: HANDLE, a: usize) -> Option<u32> { read_at(h, a, 4).filter(|b| b.len() >= 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]])) }

// ── MATCH DATA — per-frame match-state recorder (synced to the service when sharing is on) ──
// Records, per GAME FRAME, both players' input (+0x4FC on slots 0 & 1) keyed by the guest
// frame_counter, plus the match context (teams, local side). Reuses the same anchor the reader
// already uses; strictly read-only. One row per new frame_counter.
static CAPTURING: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
const LOCALPLAYER_HOST_OFF: usize = 0xac7230; // exe+off: 0=P1, 1=P2 (localPlayerNum)

#[derive(Default)]
struct CapState { frames: Vec<(u32, u16, u16, [u16; 6])>, meta: serde_json::Value, status: String, path: String }
fn cap_state() -> &'static Mutex<CapState> {
    static S: OnceLock<Mutex<CapState>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(CapState::default()))
}

// One-time locate of a FINE (per-render-frame) guest frame_counter: a u32 near the array that ticks up by
// ~1 EVERY render frame, SMOOTHLY. The critical distinction (root cause of the v0.1.10 6Hz decimation): the
// game also has a COARSE counter that jumps by ~10 every ~10 frames (flat, then +10). At the old 180ms
// sampling both look like "~11 per sample", so the old hunt could pick the coarse one → dedup-by-counter
// stored only every 10th frame → 6Hz. We now sample FAST (~22ms): the fine counter ticks every sample by a
// small amount; the coarse one reads flat between its jumps → rejected. If nothing qualifies we return None,
// and the caller's synthetic per-poll index is ALSO dense (~60Hz) — so the capture is never decimated.
unsafe fn hunt_frame_counter(h: HANDLE, array: usize) -> Option<usize> {
    let mut mbi = MEMORY_BASIC_INFORMATION::default();
    if VirtualQueryEx(h, Some(array as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 { return None; }
    let rbase = mbi.BaseAddress as usize; let rend = rbase + mbi.RegionSize;
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

fn cap_set_status(s: &str) { cap_state().lock().unwrap().status = s.to_string(); }

fn capture_loop() {
    use std::sync::atomic::Ordering::SeqCst;
    let pid = match find_game_pid() { Some(p) => p, None => { cap_set_status("game not running"); CAPTURING.store(false, SeqCst); return; } };
    let h = match unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) } { Ok(h) => h, Err(_) => { cap_set_status("open failed"); CAPTURING.store(false, SeqCst); return; } };
    let exe = game_exe_base(pid);
    cap_set_status("waiting for match");
    let mut tries = 0u32;
    let array = loop {
        if !CAPTURING.load(SeqCst) { return; }
        // anchor first (O(1)); fall back to the same heavy scan the skin reader uses when the anchor is stale
        let a = unsafe { anchor_array(h) }.or_else(|| unsafe { find_array(h) });
        if let Some(a) = a { break a; }
        tries += 1;
        cap_set_status(&format!("waiting for match (scan {tries})"));
        std::thread::sleep(std::time::Duration::from_millis(300));
    };
    cap_set_status(&format!("array @ 0x{array:x} — locating frame counter"));
    let cid = |i: usize| unsafe { rpm_u8(h, array + i * STRIDE + OFF_CHARID) }.unwrap_or(255);
    let side = unsafe { rpm_u8(h, exe + LOCALPLAYER_HOST_OFF) }.unwrap_or(255);
    {
        let mut st = cap_state().lock().unwrap();
        st.meta = serde_json::json!({
            "local_side": side,
            "p1_team_cid": [cid(0), cid(2), cid(4)],
            "p2_team_cid": [cid(1), cid(3), cid(5)],
        });
    }
    cap_set_status("locating frame counter");
    let fc = unsafe { hunt_frame_counter(h, array) };
    cap_state().lock().unwrap().meta["frame_counter_addr"] = serde_json::json!(fc.map(|a| a as u64));
    cap_set_status(if fc.is_some() { "recording" } else { "recording (frame ctr NOT found)" });
    let mut last = u32::MAX;
    let mut synth = 0u32;
    while CAPTURING.load(SeqCst) {
        let frame = match fc { Some(a) => unsafe { rpm_u32(h, a) }.unwrap_or(0), None => { synth += 1; synth } };
        if frame != last {
            let p1 = unsafe { rpm_u16(h, array + OFF_INPUT) }.unwrap_or(0);
            let p2 = unsafe { rpm_u16(h, array + STRIDE + OFF_INPUT) }.unwrap_or(0);
            // health: all 6 fighters (Steam health u32 @+0xb44, low16 = 0..144).
            let mut hp = [0u16; 6];
            // clamp to real MvC2 max (144): a never-played (benched) char's slot can read
            // uninitialized garbage (e.g. 999) — an un-played char is at full health = 144.
            for i in 0..6 { hp[i] = (unsafe { rpm_u32(h, array + i * STRIDE + OFF_HEALTH) }.unwrap_or(0) as u16).min(144); }
            cap_state().lock().unwrap().frames.push((frame, p1, p2, hp));
            last = frame;
        }
        std::thread::sleep(std::time::Duration::from_millis(2));   // ~500Hz poll, dedup by frame
    }
    cap_set_status("stopped");
}

#[tauri::command]
pub fn capture_start(path: String) -> Result<String, String> {
    use std::sync::atomic::Ordering::SeqCst;
    if CAPTURING.swap(true, SeqCst) { return Err("already recording".into()); }
    let path = if path.trim().is_empty() {
        let home = std::env::var("USERPROFILE").unwrap_or_else(|_| ".".into());
        let ts = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0);
        format!("{}\\mvc2-sessions\\session-{}.json", home, ts)
    } else { path };
    { let mut st = cap_state().lock().unwrap(); st.frames.clear(); st.meta = serde_json::json!({}); st.status = "starting".into(); st.path = path.clone(); }
    std::thread::spawn(capture_loop);
    Ok(path)
}

#[tauri::command]
pub fn capture_status() -> serde_json::Value {
    let st = cap_state().lock().unwrap();
    serde_json::json!({ "recording": CAPTURING.load(std::sync::atomic::Ordering::SeqCst), "status": st.status, "frames": st.frames.len(), "meta": st.meta })
}

#[tauri::command]
pub fn capture_stop() -> Result<serde_json::Value, String> {
    CAPTURING.store(false, std::sync::atomic::Ordering::SeqCst);
    std::thread::sleep(std::time::Duration::from_millis(150));   // let the loop flush its last rows
    let st = cap_state().lock().unwrap();
    let frames: Vec<serde_json::Value> = st.frames.iter().map(|(f, p1, p2, hp)| serde_json::json!([f, p1, p2, hp])).collect();
    let session = serde_json::json!({ "meta": st.meta, "frame_count": st.frames.len(), "frames": frames });
    if let Some(parent) = std::path::Path::new(&st.path).parent() { let _ = std::fs::create_dir_all(parent); }
    std::fs::write(&st.path, serde_json::to_vec(&session).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    Ok(serde_json::json!({ "path": st.path, "frames": st.frames.len(), "meta": st.meta }))
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
const SHARE_FILE: &str = "C:\\g\\share_gameplay.txt";
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
const GS_SCHEMA: &str = "[frame,p1_in,p2_in,hp[6],px[6],py[6],p1_meter,p2_meter,meter_fill,combo_dealt[6],combo_recv[6],vx[6],vy[6],red_hp[6],facing[6],hitstun[6],action[6]]";

fn gs_now_ms() -> u64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis() as u64).unwrap_or(0) }

fn load_share_setting() {
    if let Ok(s) = std::fs::read_to_string(SHARE_FILE) {
        let t = s.trim();
        if t == "0" || t.eq_ignore_ascii_case("false") || t.eq_ignore_ascii_case("off") {
            SHARE_GAMEPLAY.store(false, std::sync::atomic::Ordering::SeqCst);
        }
    }
}

/// Whether MetaSync auto-shares per-frame match data with the service. Beta default: true.
#[tauri::command]
pub fn get_share_gameplay() -> bool { SHARE_GAMEPLAY.load(std::sync::atomic::Ordering::SeqCst) }

/// Toggle gameplay-data sharing (persisted to disk so it survives restarts).
#[tauri::command]
pub fn set_share_gameplay(on: bool) -> Result<(), String> {
    SHARE_GAMEPLAY.store(on, std::sync::atomic::Ordering::SeqCst);
    let _ = std::fs::create_dir_all("C:\\g");
    let _ = std::fs::write(SHARE_FILE, if on { "1" } else { "0" });
    Ok(())
}

/// Record Live-Sync consent to the service (audit trail). Fire-and-forget; never blocks the UI.
#[tauri::command]
pub fn record_consent(steamid: String, version: String) {
    std::thread::spawn(move || {
        let _ = auth_post(&format!("{}/consent", SKINSYNC))
            .timeout(std::time::Duration::from_secs(8))
            .send_json(serde_json::json!({ "steamid": steamid, "version": version }));
    });
}

/// Send a community leaderboard-stat suggestion to the service. Blocks briefly so the UI
/// can confirm delivery (success toast); returns an error the frontend surfaces on failure.
#[tauri::command]
pub fn suggest_stat(steamid: String, name: String, text: String) -> Result<(), String> {
    let text = text.chars().take(600).collect::<String>();
    auth_post(&format!("{}/suggest", SKINSYNC))
        .timeout(std::time::Duration::from_secs(10))
        .send_json(serde_json::json!({ "steamid": steamid, "name": name, "text": text }))
        .map(|_| ())
        .map_err(|e| e.to_string())
}

// One captured frame row (matches GS_SCHEMA). Frame-keyed in a BTreeMap → sorted + last-write-wins.
#[derive(Clone)]
struct GsRow {
    frame: u32, p1_in: u16, p2_in: u16,
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
    last_update: Option<std::time::Instant>,        // for the recency guard in the snapshot
}
impl Default for GsCapture {
    fn default() -> Self { GsCapture { frames: std::collections::BTreeMap::new(), frame_addr: 0, synthetic: false, assist: [0; 6], last_update: None } }
}
fn gs_capture() -> &'static Mutex<GsCapture> {
    static S: OnceLock<Mutex<GsCapture>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(GsCapture::default()))
}

// A snapshot of the current/just-ended game's frames, taken by on_game_win at KO time.
struct GsSnapshot { frames: Vec<GsRow>, frame_addr: usize, synthetic: bool, assist: [u8; 6] }
// Return the buffered game IFF it was actively updating within the last few seconds (i.e. it IS the game
// that just ended). This guards against attaching a stale/other game's buffer to a late (pending-flush) win.
fn gamestate_snapshot() -> Option<GsSnapshot> {
    let c = gs_capture().lock().unwrap();
    if c.frames.is_empty() { return None; }
    if c.last_update.map_or(true, |t| t.elapsed().as_secs() > 6) { return None; }
    Some(GsSnapshot { frames: c.frames.values().cloned().collect(), frame_addr: c.frame_addr, synthetic: c.synthetic, assist: c.assist })
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
unsafe fn read_gs_row(h: HANDLE, base: usize, frame: u32) -> Option<GsRow> {
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
            let h = match unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid) } { Ok(h) => h, Err(_) => { std::thread::sleep(std::time::Duration::from_millis(600)); continue; } };
            // wait for a live match with BOTH teams alive (a fresh game start, not a mid-KO/loading copy)
            let base = match unsafe { anchor_array(h) } { Some(b) => b, None => { unsafe { let _ = CloseHandle(h); } std::thread::sleep(std::time::Duration::from_millis(300)); continue; } };
            let start_row = match unsafe { read_gs_row(h, base, 0) } { Some(r) => r, None => { unsafe { let _ = CloseHandle(h); } std::thread::sleep(std::time::Duration::from_millis(200)); continue; } };
            // TRUE match-load gate. Ideal: catch the +-213 spawn during the intro (gs_match_load) so the tape
            // starts at frame 0 of the FIGHT. Fallback: if all real chars have been full for ~1.5s but we never
            // caught the spawn (attached mid-intro), start anyway so a match is never entirely missed. The 50ms
            // poll (vs v1's 200ms) is what lets us land inside the ~1-2s intro window.
            let full = (0..5).all(|i| start_row.hp[i] >= 144);
            if full { full_since.get_or_insert_with(std::time::Instant::now); } else { full_since = None; }
            let ready = gs_match_load(&start_row)
                || (full && full_since.map_or(false, |t| t.elapsed().as_millis() > 1500));
            if !ready { unsafe { let _ = CloseHandle(h); } std::thread::sleep(std::time::Duration::from_millis(50)); continue; }
            full_since = None; // consumed → re-arm the fallback timer for the next match

            // ── a game is starting → reset the buffer, locate the guest frame counter (one-time, ~1s), and
            //    snapshot the assist type per slot (chosen at char-select, fixed for the whole match) ──
            let fc = unsafe { hunt_frame_counter(h, base) };
            let mut assist = [0u8; 6];
            for i in 0..6 { assist[i] = unsafe { rpm_u8(h, base + i * STRIDE + OFF_ASSIST) }.unwrap_or(0); }
            {
                let mut c = gs_capture().lock().unwrap();
                c.frames.clear();
                c.frame_addr = fc.unwrap_or(0);
                c.synthetic = fc.is_none();
                c.assist = assist;
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
                if frame != last {
                    if let Some(row) = unsafe { read_gs_row(h, base, frame) } {
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
                        if same_ct > 240 { break; }   // ~0.7s of zero change → frozen base
                    }
                }
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
            unsafe { let _ = CloseHandle(h); }
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

// Build the stored record (metadata + frame array), gzip it, and SPOOL it to the local cache as
// <match_key>_<reporter>.json.gz + a .meta envelope. The uploader drains the spool between matches, so no
// large upload ever runs during a fight. The .gz gunzips to this exact record (server writes it verbatim).
fn spool_gamestate(match_key: &str, reporter: &str, side: u8, p1_team: &[u8], p2_team: &[u8],
                   winner: &str, loser: &str, gs: &GsSnapshot) {
    let dir = gs_cache_dir();
    // soft backpressure: if uploads are failing and the spool is huge, stop piling on.
    let pending = std::fs::read_dir(&dir)
        .map(|rd| rd.flatten().filter(|e| e.file_name().to_string_lossy().ends_with(".meta")).count())
        .unwrap_or(0);
    if pending >= GS_SPOOL_CAP { trace(&format!("[gamestate] spool full ({pending}) — dropping {match_key}")); return; }

    let ts = gs_now_ms();
    let id = format!("{}_{}", match_key, reporter);
    let frames: Vec<serde_json::Value> = gs.frames.iter().map(|r| serde_json::json!([
        r.frame, r.p1_in, r.p2_in, r.hp, r.px, r.py, r.m1, r.m2, r.mfill, r.cd, r.cr,
        r.vx, r.vy, r.rhp, r.face, r.hitstun, r.act
    ])).collect();
    // the complete artifact that lands on disk (server writes the gunzip-able bytes verbatim)
    let assist_p1 = [gs.assist[0], gs.assist[2], gs.assist[4]];
    let assist_p2 = [gs.assist[1], gs.assist[3], gs.assist[5]];
    let record = serde_json::json!({
        "id": id, "match_key": match_key, "reporter": reporter, "side": side,
        "p1_team": p1_team, "p2_team": p2_team, "winner": winner, "loser": loser,
        "assist": gs.assist, "assist_p1": assist_p1, "assist_p2": assist_p2,
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
    let meta = serde_json::json!({
        "match_key": match_key, "reporter": reporter, "side": side,
        "p1_team": p1_team, "p2_team": p2_team, "winner": winner, "loser": loser,
        "assist_p1": assist_p1, "assist_p2": assist_p2,
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
            if SHARE_GAMEPLAY.load(SeqCst) && !GS_IN_MATCH.load(SeqCst) { drain_gs_cache(); }
            std::thread::sleep(std::time::Duration::from_secs(20));
        }
    });
}

fn is_wb(v: u32) -> bool { v >= WB_LO && v < WB_HI }

// Cheap re-validation of a cached base: >=5 of the 6 slots have a working-buffer DatPal pointer at
// cl+0x4c. That single fixed-offset pointer is the array's strongest cheap fingerprint (16k loose
// clusters exist, but only the real 6-run keeps a WB pointer at exactly +0x4c across every slot).
unsafe fn array_valid(h: HANDLE, base: usize) -> bool {
    if base == 0 { return false; }
    (0..6).filter(|&i| is_wb(rpm_u32(h, base + i * STRIDE + OFF_DATPAL).unwrap_or(0))).count() >= 5
}

// ── ANCHOR: compute the live fighter array from flycast's guest-RAM reservation base ──────────────────
// flycast reserves the whole guest address space as one big RW block; the live MvC2 fighter array sits at a
// FIXED offset inside it (empirically STABLE across launches: reservation_base + 0x10b33fc8 landed exactly on
// the live array in every launch tested — 0x95e0000→0x1a113fc8 and 0x9760000→0x1a293fc8). The rollback netcode
// keeps ~14 savestate COPIES of the array, but they ALL share the SAME DatPals, so this one computed read
// paints correctly — no ~1GB find_array scan, no volatile-copy flicker, no drop. This is the performant anchor.
const ARRAY_OFF: usize = 0x10b3_3fc8; // build-marker: gs-70 anchor (rebuild forced 2026-08-05)
// The reservation base: the >=128MB committed PAGE_READWRITE block that contains the working-buffer window
// (host 0x10000000). ASLR'd per launch, but found deterministically by region enumeration (no content scan).
unsafe fn flycast_base(h: HANDLE) -> usize {
    let mut addr = 0usize;
    loop {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 { break; }
        let base = mbi.BaseAddress as usize; let size = mbi.RegionSize;
        if size == 0 { break; }
        if mbi.State == MEM_COMMIT && mbi.Protect.0 == PAGE_READWRITE.0 && size >= 0x0800_0000 && base <= 0x1000_0000 && 0x1000_0000 < base + size { return base; }
        let n = base + size; if n <= addr { break; } addr = n;
        if addr > 0x7FFF_FFFF_FFFF { break; }
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
unsafe fn anchor_array(h: HANDLE) -> Option<usize> {
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
unsafe fn anchor_roster(h: HANDLE) -> Vec<Found> {
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
        // ★ NEGATIVE GATE (live-capture-confirmed): reject any candidate with an impossible health (>144) —
        // that's a stale/half-written savestate COPY. The live capture showed copies reading hp=11200/62807
        // while the live mem_b array is all <=144; the old `<=0x200` check let hp=235 garbage through.
        if (0..6).any(|i| (rpm_u32(h, c + i * STRIDE + OFF_HEALTH).unwrap_or(0) & 0xffff) > HP_FULL as u32) { continue; }
        let score = (0..6).filter(|&i| {
            let cl = c + i * STRIDE;
            is_wb(rpm_u32(h, cl + OFF_DATPAL).unwrap_or(0)) && (rpm_u32(h, cl + OFF_HEALTH).unwrap_or(0xffff) & 0xffff) <= HP_FULL as u32
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
    // LIVENESS (capture-confirmed): only the LIVE array's per-frame fields (position/velocity @ +0x61c..0x64c)
    // move every frame; the rollback savestate COPIES are frozen snapshots — the app's fixed anchor lands on
    // one, which is the whole bug. Probe that region across ~180ms (~11 frames) and lock ONLY a candidate that
    // actually MOVED. If none moved this instant, return None and retry — never lock a static copy.
    let anim = |c: usize| -> Vec<u8> {
        let mut v = Vec::with_capacity(6 * 0x40);
        for i in 0..6 { if let Some(b) = read_at(h, c + i * STRIDE + OFF_POS_X, 0x40) { v.extend_from_slice(&b); } }
        v
    };
    let before: Vec<Vec<u8>> = cands.iter().map(|&(c, _)| anim(c)).collect();
    std::thread::sleep(std::time::Duration::from_millis(180));
    for (i, &(c, _)) in cands.iter().enumerate() {
        if !before[i].is_empty() && anim(c) != before[i] { return Some(c); }  // this candidate is LIVE (moving)
    }
    None   // nothing demonstrably live right now → don't lock a frozen copy; the caller retries next cycle
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
    Some(GameSt { in_match: if any_live { 1 } else { 0 }, match_state: 0, stage: 0, timer: 0, frame: 0, ram: base, slots, meter1, meter2 })
}

// Self-contained gamestate read used by BOTH the hook path and the RPM fallback. Opens its own read-only
// handle, re-validates (or re-finds, throttled) the volatile array base, then does the cheap per-fighter
// read. `allow_find` gates the heavy scan to when fighters are likely loaded (sig-scan roster non-empty).
fn read_gamestate_rpm(pid: u32, ram_base: &mut usize, last_find: &mut std::time::Instant, allow_find: bool, hint: usize) -> Option<GameSt> {
    if pid == 0 { return None; }
    let h = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid).ok()? };
    let out = unsafe {
        if *ram_base != 0 && !array_valid(h, *ram_base) { *ram_base = 0; }       // volatile → dropped
        // ANCHOR (gs-70): compute the array from flycast's reservation base + ARRAY_OFF when we don't already
        // have a base. NOT primary — reverted from gs-71, which forced this static-anchor copy every cycle and
        // regressed cross-round painting (at a round reload the anchor copy's DatPal pointers go null/stale while
        // find_array's ANIMATING copy still tracks the live render). So: anchor to acquire O(1), then the
        // liveness gate below hands off to find_array's animating copy if this one freezes.
        if *ram_base == 0 { if let Some(a) = anchor_array(h) { *ram_base = a; } }
        // Fallbacks (only if the anchor offset ever shifts on a future game build): reuse last base, then scan.
        if *ram_base == 0 && hint != 0 && array_valid(h, hint) { *ram_base = hint; }
        if *ram_base == 0 && allow_find && last_find.elapsed().as_millis() >= 1500 {
            *last_find = std::time::Instant::now();
            *ram_base = find_array(h).unwrap_or(0);
            // find_array is a heavy ~1GB scan. If it came up empty (char-select/loading — the array isn't
            // instantiated yet, but sig-scan fighters linger), back the NEXT attempt off a bit so the scan
            // doesn't thrash, but retry FAST so teams lock within ~1-2s of a round starting (not 5-15s — the
            // "didn't detect the match right away" lag). Once found, array_valid is cheap → no re-scan.
            if *ram_base == 0 { *last_find += std::time::Duration::from_millis(500); }
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
    g1_met: u32, g2_met: u32, last_m1: u8, last_m2: u8, met_init: bool,
    // Games finished BEFORE the side was confirmed — held here (never recorded) and committed the moment the user
    // confirms their side (the "never record a guess" gate). Cleared with the rest on a new opponent.
    pending: Vec<PendingGame> }

// A finished game held until the side is confirmed. winner = the side (1/2) that won; my_side is resolved at commit.
#[derive(Clone)]
struct PendingGame { winner: u8, opp: (String, String), ocv: bool, perfect: bool, comeback: bool, rich: GameRich }

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
    if s.len() < 3 || s.len() > 24 { return false; }
    if s.matches(' ').count() > 2 { return false; }           // gamertags aren't sentences
    if s.chars().any(|c| "<>{}[]|=\\^~`".contains(c)) { return false; }  // symbol junk (e.g. "cjU>") isn't a gamertag
    let low = s.to_lowercase();
    // URL/file fragments AND game/UI/netcode strings the scan keeps grabbing (title, menus, log lines).
    for bad in [".com", ".net", ".org", ".io", ".gg", "http", "www.", "://", ".dll", ".exe", ".dat", "googleapi",
                "marvel", "capcom", "heroes", "new age", "session", "exiting", "waiting", "opponent", "loading",
                "connect", "matchmak", "lobby", "player", "press", "select", "steam"] {
        if low.contains(bad) { return false; }
    }
    s.chars().filter(|c| c.is_ascii_alphanumeric()).count() >= 4   // ≥4 alphanumeric chars (rejects short garbage runs)
}

// A finished game: record the local per-opponent H2H AND report it to the global leaderboard. The rich-stat
// flags (ocv/perfect/comeback) always describe the WINNER — computed symmetrically from both sides' health,
// so we credit them correctly whether we won or lost.
fn on_game_win(winner: u8, opp: &Option<(String, String)>, my_side: u8, ocv: bool, perfect: bool, comeback: bool, rich: &GameRich) {
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
    report_result_server(reporter, winner_id, winner_name, loser_id, loser_name, ocv, perfect, comeback,
        winner_team, loser_team, winner_combo, winner_met,
        my_side, rich.p1_team.clone(), rich.p2_team.clone(), gs);
}

// Fire-and-forget POST of a finished game to the skinsync leaderboard (own thread so the reader never blocks
// on the network). The server dedupes so the same game reported by both players counts once. The server now
// RETURNS the consensus `key` it derived for this result — we reuse that EXACT key to correlate the game-state
// recording (so a recording joins its metadata AND both players' recordings of one game share one match_key).
fn report_result_server(reporter: String, winner: String, winner_name: String, loser: String, loser_name: String,
                        ocv: bool, perfect: bool, comeback: bool,
                        winner_team: Vec<u8>, loser_team: Vec<u8>, biggest_combo: u16, meters_used: u32,
                        // game-state recording context (uploaded only if share_gameplay_data + a recording exists)
                        side: u8, p1_team: Vec<u8>, p2_team: Vec<u8>, gs: Option<GsSnapshot>) {
    std::thread::spawn(move || {
        use std::sync::atomic::Ordering::SeqCst;
        let body = serde_json::json!({
            "reporter": reporter.clone(), "winner": winner.clone(), "loser": loser.clone(),
            "winner_name": winner_name, "loser_name": loser_name,
            "ocv": ocv, "perfect": perfect, "comeback": comeback,
            "winner_team": winner_team, "loser_team": loser_team, "biggest_combo": biggest_combo, "meters_used": meters_used,
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
        spool_gamestate(&key, &reporter, side, &p1_team, &p2_team, &winner, &loser, &gs);
        trace(&format!("[gamestate] spooled {} frames as {}_{} (uploads between matches)", gs.frames.len(), key, reporter));
    });
}

// Record a finished game now if the side is confirmed, else BUFFER it (the "never record a guess" gate).
fn commit_or_buffer(st: &mut ScoreState, winner: u8, opp: &Option<(String, String)>, confirmed: bool, my_side: u8,
                    ocv: bool, perfect: bool, comeback: bool, rich: GameRich) {
    if confirmed { on_game_win(winner, opp, my_side, ocv, perfect, comeback, &rich); }
    else if let Some(o) = opp { st.pending.push(PendingGame { winner, opp: o.clone(), ocv, perfect, comeback, rich }); }
}

fn update_score(st: &mut ScoreState, game: &Option<GameSt>, opp: &Option<(String, String)>, my_side: u8, confirmed: bool) {
    let cur = opp.as_ref().map(|o| o.0.clone());
    // Reset the set ONLY for a genuinely different, present opponent. A transient None (opponent momentarily
    // undetected between games / long char-select) must NOT wipe the set score — hold it until a real,
    // different SteamID actually appears.
    if let Some(cur_id) = cur {
        if st.set_opp.as_deref() != Some(cur_id.as_str()) { *st = ScoreState { set_opp: Some(cur_id), ..Default::default() }; }
    }
    // Side just got confirmed → flush the games we buffered this set, in order, with the now-known side.
    if confirmed && !st.pending.is_empty() {
        for pg in std::mem::take(&mut st.pending) {
            on_game_win(pg.winner, &Some(pg.opp), my_side, pg.ocv, pg.perfect, pg.comeback, &pg.rich);
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
                        let (o, p, c) = (alive_ct(2) == 3, !st.g2_dmg, st.g2_low);
                        commit_or_buffer(st, 2, opp, confirmed, my_side, o, p, c, r);
                    } else if st.la2 && !a2 && a1 {
                        st.p1 += 1; st.judged = true; let r = rich_of(st);
                        let (o, p, c) = (alive_ct(1) == 3, !st.g1_dmg, st.g1_low);
                        commit_or_buffer(st, 1, opp, confirmed, my_side, o, p, c, r);
                    }
                }
                st.la1 = a1; st.la2 = a2; st.was_in = true;
            } else if st.was_in && !st.judged && st.saw_both { // match ended before the KO edge (contested game only)
                if st.la1 && !st.la2 { st.p1 += 1; st.judged = true; let r = rich_of(st); let (p, c) = (!st.g1_dmg, st.g1_low); commit_or_buffer(st, 1, opp, confirmed, my_side, false, p, c, r); }
                else if st.la2 && !st.la1 { st.p2 += 1; st.judged = true; let r = rich_of(st); let (p, c) = (!st.g2_dmg, st.g2_low); commit_or_buffer(st, 2, opp, confirmed, my_side, false, p, c, r); }
                st.was_in = false; st.saw_both = false;
            } else { st.was_in = g.in_match == 1; if g.in_match != 1 { st.saw_both = false; } }
        }
        None => {   // game data gone (liveness gate / match over): judge from the LAST-known alive states
            if st.was_in && !st.judged && st.saw_both {
                if st.la1 && !st.la2 { st.p1 += 1; st.judged = true; let r = rich_of(st); let (p, c) = (!st.g1_dmg, st.g1_low); commit_or_buffer(st, 1, opp, confirmed, my_side, false, p, c, r); }
                else if st.la2 && !st.la1 { st.p2 += 1; st.judged = true; let r = rich_of(st); let (p, c) = (!st.g2_dmg, st.g2_low); commit_or_buffer(st, 2, opp, confirmed, my_side, false, p, c, r); }
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
pub fn leaderboard(tab: String, period: Option<String>, limit: Option<u32>) -> Result<serde_json::Value, String> {
    let lim = limit.unwrap_or(10).min(50);
    let period = period.unwrap_or_else(|| "all".into());
    ureq::get(&format!("{}/leaderboard?tab={}&period={}&limit={}", SKINSYNC, tab, period, lim))
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

/// Matchup intel between two SteamIDs: { my_elo, opp_elo, my_rank, opp_rank, win_chance, elo_expected,
/// h2h:{wins,losses}, best_team_vs_them:{team,wins}, their_kryptonite:{team,losses} }. Backend fetch (no CORS/CSP).
#[tauri::command]
pub fn matchup(me: String, opp: String) -> Result<serde_json::Value, String> {
    ureq::get(&format!("{}/matchup?me={}&opp={}", SKINSYNC, me, opp))
        .timeout(std::time::Duration::from_secs(6))
        .call().map_err(|e| e.to_string())?
        .into_json::<serde_json::Value>().map_err(|e| e.to_string())
}

/// The app's real release version, baked in at compile time from Cargo.toml — so the UI always shows the
/// exact version the user is running (single source of truth; no separate build tag to keep in sync).
#[tauri::command]
pub fn app_version() -> String { env!("CARGO_PKG_VERSION").to_string() }

/// Central changelog (nobd.net/skinsync/update/changelog.json) — fetched by the "What's New" modal so it can
/// be updated without shipping a new build. The frontend keeps a bundled fallback if this is unreachable.
#[tauri::command]
pub fn fetch_changelog() -> Result<serde_json::Value, String> {
    ureq::get("https://nobd.net/skinsync/update/changelog.json")
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
// ★ localPlayerNum — flycast's own P1/P2 side global (0 = P1, 1 = P2), found by DIFFERENTIAL capture (sidehunt):
// it read 0 in a live P1 match and 1 across 3 live P2 matches, right next to kcode. DETERMINISTIC side, one read.
const LOCALPLAYER_OFF: usize = 0xac7230;

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

// ── Anchor persistence ── the heap-located addresses (fighter-array base, opponent session region, roster
// region) are ASLR'd PER GAME-LAUNCH but stable for the game's whole run. Persisting them means an APP restart
// (game still running) skips every cold scan → instant. All loads are VALIDATED downstream (array_valid / the
// WARM pairing scan / the roster re-scan), so a stale file after a game relaunch just falls back to one scan.
fn save_anchors(pid: u32, ram: usize, opp: Option<(usize, usize)>, work: Option<(usize, usize)>) {
    let (ob, os) = opp.unwrap_or((0, 0)); let (wl, wh) = work.unwrap_or((0, 0));
    let _ = std::fs::write("C:\\g\\mvc_anchors.txt", format!("{:x} {:x} {:x} {:x} {:x} {:x}", pid, ram, ob, os, wl, wh));
}
fn load_anchors() -> (u32, usize, Option<(usize, usize)>, Option<(usize, usize)>) {
    let s = std::fs::read_to_string("C:\\g\\mvc_anchors.txt").unwrap_or_default();
    let v: Vec<usize> = s.split_whitespace().filter_map(|x| usize::from_str_radix(x, 16).ok()).collect();
    if v.len() >= 6 {
        (v[0] as u32, v[1], if v[2] != 0 && v[3] != 0 { Some((v[2], v[3])) } else { None },
                            if v[4] != 0 && v[5] != 0 { Some((v[4], v[5])) } else { None })
    } else { (0, 0, None, None) }
}

// ── DETERMINISTIC SIDE via Input_DEC (per-player input register) ────────────────────────────────────
// The game's per-player input register (Input_DEC), offset validated live: the input is Input_DEC in
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
    // NOTE: the old input-correlation side detectors (start_side_detector = churn, start_inputdec_detector =
    // +0x4fc render field) are DISABLED — the +0x4fc field is side-agnostic so inputdec always locked P1, which
    // is what inverted the stats. Side now comes DETERMINISTICALLY from the session-struct pairing (P1's SteamID
    // is stored above P2's), set in the reader loop. Kept for reference; do not re-enable without a real fix.
    // start_side_detector();
    // start_inputdec_detector();
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
        let mut injected_pid: u32 = 0;   // gs-75: auto-inject the render hook once per game session (pid)
        let mut side_seen: u8 = 0;       // gs-77: localPlayerNum debounce — last side value read
        let mut side_stable: u32 = 0;    // consecutive reads of the SAME side; confirm only when stable (kills the stale-read first-match flash)
        let mut handle: Option<HANDLE> = None;
        let mut roster: Vec<Found> = Vec::new();
        let mut stable: u32 = 0;
        let mut work: Option<(usize, usize)> = None; // located team region (cheap-tracked between relocates)
        let mut empty_streak: u32 = 0;               // consecutive empty track cycles before a wide relocate
        let mut opp: Option<(String, String)> = None;
        let mut opp_backoff: i32 = 0;
        let mut opp_pending: Option<String> = None;  // a DIFFERENT candidate id; must persist 2 scans to swap (anti-flip)
        let mut opp_addr: Option<(usize, u8, String)> = None; // cached (session-slot, side, name) → instant re-reads
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
            // (re)acquire the process handle; drop it if the game is gone
            match find_game_pid() {
                Some(p) => {
                    if p != cur_pid || handle.is_none() {
                        if let Some(old) = handle.take() { unsafe { let _ = CloseHandle(old); } }
                        handle = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, p).ok() };
                        cur_pid = p; roster.clear(); work = None; opp = None; opp_addr = None; opp_region = None; in_session = false; opp_lost = None; sess_key.clear(); ram_base = 0; exe_base = game_exe_base(p);
                        // SAME game as our persisted anchors → restore them (skip cold scans on an app restart)
                        if p == anchor_pid { ram_base = anchor_ram; opp_region = anchor_opp; work = anchor_work; }
                        last_good_base = ram_base;   // sticky base = restored anchor (same game) or 0 (new game)
                    }
                    // gs-75: AUTO-INJECT the render-layer palette hook once for this game session (off-thread so
                    // it never blocks the reader). The hook self-guards a double-inject, so this is safe.
                    if p != injected_pid {
                        injected_pid = p;
                        trace(&format!("[inject] game pid {} detected → auto-inject render hook", p));
                        std::thread::spawn(move || { let _ = do_inject_hook(); });
                    }
                }
                None => {
                    if let Some(old) = handle.take() { unsafe { let _ = CloseHandle(old); } }
                    cur_pid = 0; injected_pid = 0; roster.clear(); work = None; opp = None; opp_addr = None; opp_region = None; in_session = false; opp_lost = None; ss = ScoreState::default();
                    { let mut s = snapshot().lock().unwrap(); s.state = "game_off".into(); s.roster.clear(); s.opponent = None; s.game = None; s.score = (0, 0); s.paint_slots.clear(); }
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
            // ★ FAST roster (no scan): during a fight the anchored array's six char_ids ARE the roster. This
            // deletes the ~1GB `rpm_occurrences` wide relocate from the hot path (the last heavy scan). The
            // signature scan below is now ONLY the character-select fallback, before fighters spawn.
            let mut team = unsafe { anchor_roster(h) };
            if !team.is_empty() { empty_streak = 0; }
            else {
                team = if let Some((lo, hi)) = work { pick_working(unsafe { rpm_occurrences(h, lo, hi) }) } else { Vec::new() };
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
                match find_opponent_netplay(cur_pid, my_id, &mut opp_addr, &mut opp_region) {
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

            // ★ DETERMINISTIC SIDE — flycast's localPlayerNum global (0 = P1, 1 = P2), one read, no scan. Only while
            // in a live netplay SESSION, and never over a manual override. AUTO-CONFIRMS the side so stats record
            // correctly with zero user action (retires the manual "set your side" gate).
            if exe_base == 0 && cur_pid != 0 { exe_base = game_exe_base(cur_pid); }   // retry if the first resolve missed
            // gs-77 — TIE THE SIDE TO THE SESSION, not the early n>0 sig-scan: that fired at select/loading before the
            // game refreshed localPlayerNum for THIS match, so it read the PREVIOUS match's stale value → the P1→P2
            // first-match flash. Require in_session AND the value STABLE for 2 reads before confirming, so a single
            // transient/stale read can never lock the wrong side.
            if in_session && exe_base != 0 {
                if let Some(pn) = unsafe { rpm_u32(h, exe_base + LOCALPLAYER_OFF) } {
                    let side = match pn { 0 => 1u8, 1 => 2u8, _ => 0u8 };
                    if side != 0 && side == side_seen { side_stable = side_stable.saturating_add(1); }
                    else { side_seen = side; side_stable = if side != 0 { 1 } else { 0 }; }
                    if side_stable >= 2 {
                        let mut s = snapshot().lock().unwrap();
                        if s.manual_side == 0 && !(s.side_confirmed && s.local_side == side) {
                            s.local_side = side; s.side_confirmed = true;
                            drop(s);
                            trace(&format!("[side] AUTO = P{} (localPlayerNum={}, stable)", side, pn));
                        }
                    }
                }
            } else if !in_session { side_seen = 0; side_stable = 0; }   // between sessions → fresh debounce for the next match

            // Game state: auto-find + read the reversed player array via read-only RPM. The heavy find is
            // attempted only when fighters are loaded (n>0) and throttled; once found, the volatile base is
            // re-validated & read cheaply.
            let raw_game = read_gamestate_rpm(cur_pid, &mut ram_base, &mut last_find, n > 0, last_good_base);
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
            let game = match raw_game {
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
            // Hold the opponent while EITHER the game reads live OR fighters are present (sig-scan roster n) —
            // robust to a flaky reversed-struct read so we never drop + re-hunt the opponent mid-set. Drop
            // only after a sustained gone stretch (set over / menus).
            let active = game.as_ref().map(|g| g.in_match == 1).unwrap_or(false) || n > 0 || in_session;
            if active { last_active = std::time::Instant::now(); }
            else if opp.is_some() && last_active.elapsed().as_secs() > OUT_TIMEOUT { opp = None; opp_addr = None; }
            let (side_for_stats, side_ok) = { let s = snapshot().lock().unwrap(); (effective_side(&s), s.side_confirmed) };  // manual override wins; gate on confirmation
            update_score(&mut ss, &game, &opp, side_for_stats, side_ok);
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
                s.in_session = in_session;
                s.ram_base = last_good_base;   // gs-74: publish the located array base so paint_live paints the REAL array (it relocates off the anchor per match)
            }

            // adaptive cadence: fast cheap region-tracking when we have the team; back off at menus
            // (where the wide relocate runs) so idle scanning stays light
            // Fast cadence whenever we have a team OR a live netplay session (populate/track quickly); back off
            // only when truly idle at menus. (Was 2000ms idle → a match entered mid-sleep waited up to 2s.)
            // persist the anchors whenever they change, keyed to the game pid → next app restart skips the scans
            { let cur = (ram_base, opp_region, work); if cur != saved_anchors { save_anchors(cur_pid, ram_base, opp_region, work); saved_anchors = cur; } }
            std::thread::sleep(std::time::Duration::from_millis(if !roster.is_empty() || in_session { 350 } else { 500 }));
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
    // exact per-fighter render-palette pointers for the paint path (NOT liveness-gated → present at match start)
    let paint_slots: Vec<serde_json::Value> = s.paint_slots.iter().map(|(pl, cid, dp)| serde_json::json!({
        "player": pl, "cid": cid, "datpal": format!("{:x}", dp)
    })).collect();
    let mut out = serde_json::json!({ "state": s.state, "count": s.roster.len(), "changed": false, "p1": to_json(&p1), "p2": to_json(&p2), "has_game": false,
        "score": { "p1": s.score.0, "p2": s.score.1 }, "local_side": s.local_side, "in_session": s.in_session,
        "manual_side": s.manual_side, "side_confirmed": s.side_confirmed, "paint_slots": paint_slots });
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

/// O(1) read of the on-screen fighters' live palettes (used by capture_live). Fast path: the RPM-read slot
/// palettes from the located fighter array. FALLBACK (array not located yet — e.g. the ~1s at match start
/// before it locks): the palettes paint_signatures' working-buffer scan last saw. Array-free, so capture —
/// and therefore skin application — happens the moment fighters render, not after the first hit/move.
pub fn live_palettes() -> Vec<String> {
    {
        let s = snapshot().lock().unwrap();
        if let Some(g) = s.game.as_ref() {
            if !g.slots.is_empty() {
                let mut out = Vec::new();
                let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
                for sl in &g.slots {
                    let sig = pal_sig(&sl.pal);
                    if !sig.is_empty() && seen.insert(sig.clone()) { out.push(sig); }
                }
                return out;
            }
        }
    }
    last_wb_pals().lock().unwrap().clone()          // array-free: whatever the base-paint scan last saw on screen
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

// The distinct on-screen palette sigs the last paint_signatures scan saw in the working buffer. This is an
// ARRAY-FREE capture source: it lets capture_live/live_palettes hand the frontend the REAL live palettes the
// instant fighters render — no waiting for the fighter array to lock (which only happens once the fight
// animates, i.e. the first hit/move). That was the "skins don't colour until I get hit" delay.
fn last_wb_pals() -> &'static Mutex<Vec<String>> {
    static P: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(Vec::new()))
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
    let (mut n_applied, mut n_stale, mut n_norows, mut n_notwb) = (0usize, 0usize, 0usize, 0usize);
    for t in &targets {
        let dp = usize::from_str_radix(t.datpal.trim_start_matches("0x"), 16).unwrap_or(0);
        if dp == 0 || t.colors.len() < 16 || !is_wb(dp as u32) { n_notwb += 1; continue; }
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
        if offsets.is_empty() { n_norows += 1; continue; }
        // ── SAFETY GATE (prevents crashing the game) ──────────────────────────────────────────────────
        // The DatPal base is VOLATILE per match; a cached/relocated address can end up pointing at unrelated
        // game memory. Writing there corrupts the process and crashes it. So we NEVER write blind: read the
        // head row first and require it to STILL be a live palette. If it's unreadable or no longer
        // palette-shaped, the address is stale → drop the cache entry and skip entirely (re-scan fresh next
        // tick). If it already equals our skin, the skin is still on → skip the writes.
        match unsafe { read_at(h, dp + offsets[0], 32) } {
            Some(cur) if is_real_row(&cur) => { if cur.as_slice() == &row[..] { n_applied += 1; continue; } } // still live & applied
            _ => { row_cache().lock().unwrap().remove(&dp); n_stale += 1; continue; }            // stale/invalid → do NOT write
        }
        for off in offsets {
            let mut w = 0usize;
            unsafe { let _ = WriteProcessMemory(h, (dp + off) as *const c_void, row.as_ptr() as *const c_void, 32, Some(&mut w)); }
            if w == 32 { rows += 1; }
        }
    }
    unsafe { let _ = CloseHandle(h); }
    trace(&format!("[paintpal] tgt={} rows={} applied_skip={} stale_skip={} norows_skip={} notwb_skip={} dps=[{}]",
        targets.len(), rows, n_applied, n_stale, n_norows, n_notwb,
        targets.iter().map(|t| t.datpal.clone()).collect::<Vec<_>>().join(",")));
    Ok(rows.to_string())
}

#[derive(serde::Deserialize)]
pub struct LiveTarget { pub cid: u8, pub player: u8, pub colors: Vec<u32> }

/// REAL-TIME paint (gs-72). Reads the CURRENT fighter array off the anchor and resolves each on-screen slot's
/// LIVE DatPal at write-time. This is the fix for "renders round 1 but not round 2 / paints P2 not P1":
/// the DatPal pointer RELOCATES every round under rollback, and paint_palettes trusted pointers from a
/// ~400ms-lagged frontend snapshot, so after a relocation it wrote stale memory and nothing rendered.
/// Live-proven: writing a fighter's DatPal DOES render (both sides turned a test colour); the only bug was
/// staleness. Frontend passes {cid, player, colors}; we match each of the 6 slots by (cid, side-parity) and
/// write the skin into every real palette row of that slot's fresh DatPal block.
#[tauri::command]
pub fn paint_live(targets: Vec<LiveTarget>) -> Result<String, String> {
    if targets.is_empty() { return Ok("0".into()); }
    let pid = find_game_pid().ok_or("game not found")?;
    let h = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, FALSE, pid) }
        .map_err(|e| e.to_string())?;
    // Use the reader's LOCATED array (it tracks the real location via anchor OR find_array — the array is NOT
    // always at the anchor; it relocates per match). Validate it; fall back to the anchor if none published yet.
    let base = {
        let rb = snapshot().lock().unwrap().ram_base;
        if rb != 0 && unsafe { array_valid(h, rb) } { rb }
        else { match unsafe { anchor_array(h) } { Some(a) => a, None => { unsafe { let _ = CloseHandle(h); } return Ok("0".into()); } } }
    };
    let mut rows = 0usize;
    for i in 0..6 {
        let cl = base + i * STRIDE;
        let cid = unsafe { rpm_u8(h, cl + OFF_CHARID) }.unwrap_or(255);
        if cid > MAX_CID { continue; }
        let player = if i % 2 == 0 { 1u8 } else { 2u8 };
        let tgt = match targets.iter().find(|t| t.cid == cid && t.player == player && t.colors.len() >= 16) {
            Some(t) => t, None => continue,
        };
        let dp = unsafe { rpm_u32(h, cl + OFF_DATPAL) }.unwrap_or(0) as usize;
        if dp == 0 || !is_wb(dp as u32) { continue; }
        let row = skin_row(&tgt.colors);
        // one 8 KB read of the DatPal block, then write every REAL palette row in-place (no cache — it relocates)
        if let Some(block) = unsafe { read_at(h, dp, 0x2000) } {
            let mut off = 0usize;
            while off + 32 <= block.len() {
                let cur = &block[off..off + 32];
                if is_real_row(cur) && cur != &row[..] {
                    let mut w = 0usize;
                    unsafe { let _ = WriteProcessMemory(h, (dp + off) as *const c_void, row.as_ptr() as *const c_void, 32, Some(&mut w)); }
                    if w == 32 { rows += 1; }
                }
                off += 0x20;
            }
        }
    }
    unsafe { let _ = CloseHandle(h); }
    Ok(rows.to_string())
}

// ── ONE-SHOT HOOK INJECTION (an in-render palette hook) ───────────────────────────────────────────
// Loads d3dhook.dll into the game (CreateRemoteThread + LoadLibraryW). The hook intercepts D3D11 palette
// COPY/COPYSUB and repaints skins.dat AT THE RENDER LAYER, so skins show at ROUND START (RPM paint_live is
// the fallback for when the hook isn't injected). The hook self-guards double-injection ("install skipped
// (already hooked)"), so this is safe to call again; the frontend fires it once per session on game-detect.
// The render-layer palette hook, EMBEDDED in the app binary (the original ship design) so the injector never
// depends on a loose file on disk. Staged to a stable temp path on inject.
const HOOK_DLL: &[u8] = include_bytes!("../../hook/d3dhook.dll");
fn stage_hook_dll() -> Option<String> {
    let dir = std::env::temp_dir().join("mvc-live-skins");
    let _ = std::fs::create_dir_all(&dir);
    let path = dir.join("d3dhook.dll");
    // INTEGRITY (anti-DLL-plant / TOCTOU-hardening): (re)write unless the on-disk bytes EXACTLY match the
    // embedded, trusted DLL. The old size-only check let a same-size planted DLL survive and get injected;
    // a full byte-compare closes that. We skip the write only when the file is already byte-identical (e.g.
    // already mapped into the running game), so we still never needlessly clobber a mapped copy.
    let matches = std::fs::read(&path).map(|b| b.as_slice() == HOOK_DLL).unwrap_or(false);
    if !matches {
        if std::fs::write(&path, HOOK_DLL).is_err() {
            // Write failed — most likely the DLL is already mapped+locked by the game. Only proceed if what's
            // on disk is verifiably our trusted copy; otherwise refuse to inject an unverified file.
            let trusted = std::fs::read(&path).map(|b| b.as_slice() == HOOK_DLL).unwrap_or(false);
            if !trusted { trace("[inject] staged d3dhook.dll failed integrity check — refusing to inject"); return None; }
        }
    }
    if path.exists() { Some(path.to_string_lossy().into_owned()) } else { None }
}

/// Inject the render-layer palette hook into the running game (once per session). Returns "injected"/"already"
/// or an error. Reuses the proven CreateRemoteThread+LoadLibraryW loader.
#[tauri::command]
pub fn inject_hook() -> Result<String, String> { do_inject_hook() }

fn do_inject_hook() -> Result<String, String> {
    trace("[inject] do_inject_hook");
    let dll = match stage_hook_dll() { Some(d) => d, None => { trace("[inject] could not stage embedded d3dhook.dll"); return Err("could not stage embedded d3dhook.dll".into()); } };
    trace(&format!("[inject] dll={}", dll));
    if find_game_pid().is_none() { trace("[inject] game not running"); return Err("game not running".into()); }
    const PS: &str = r#"$dll = "__DLL__"
$proc = Get-Process MarvelVsCapcomFightingCollection -ErrorAction SilentlyContinue
if(-not $proc){ Write-Host "GAME_NOT_RUNNING"; exit 1 }
$pid2 = $proc.Id
$sig = @'
using System; using System.Runtime.InteropServices;
public class Inj {
 [DllImport("kernel32")] public static extern IntPtr OpenProcess(uint a,bool b,int p);
 [DllImport("kernel32")] public static extern IntPtr VirtualAllocEx(IntPtr h,IntPtr a,uint s,uint t,uint p);
 [DllImport("kernel32")] public static extern bool WriteProcessMemory(IntPtr h,IntPtr a,byte[] b,uint s,out uint w);
 [DllImport("kernel32")] public static extern IntPtr GetModuleHandle(string m);
 [DllImport("kernel32")] public static extern IntPtr GetProcAddress(IntPtr h,string n);
 [DllImport("kernel32")] public static extern IntPtr CreateRemoteThread(IntPtr h,IntPtr a,uint s,IntPtr f,IntPtr p,uint fl,IntPtr t);
 [DllImport("kernel32")] public static extern uint WaitForSingleObject(IntPtr h,uint ms);
}
'@
Add-Type $sig
$h = [Inj]::OpenProcess(0x43A,$false,$pid2)
if($h -eq [IntPtr]::Zero){ Write-Host "OPENPROCESS_FAILED"; exit 1 }
$bytes = [System.Text.Encoding]::Unicode.GetBytes($dll + "`0")
$mem = [Inj]::VirtualAllocEx($h,[IntPtr]::Zero,[uint32]$bytes.Length,0x3000,0x40)
[Inj]::WriteProcessMemory($h,$mem,$bytes,[uint32]$bytes.Length,[ref]([uint32]0)) | Out-Null
$k = [Inj]::GetModuleHandle("kernel32.dll")
$load = [Inj]::GetProcAddress($k,"LoadLibraryW")
$t = [Inj]::CreateRemoteThread($h,[IntPtr]::Zero,0,$load,$mem,0,[IntPtr]::Zero)
if($t -eq [IntPtr]::Zero){ Write-Host "CREATETHREAD_FAILED"; exit 1 }
[Inj]::WaitForSingleObject($t,5000) | Out-Null
Write-Host "INJECTED""#;
    let script = PS.replace("__DLL__", &dll);
    let tmp = std::env::temp_dir().join("mvc_inject_hook.ps1");
    std::fs::write(&tmp, script).map_err(|e| e.to_string())?;
    let out = std::process::Command::new("powershell")
        .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]).arg(&tmp)
        .output().map_err(|e| e.to_string())?;
    let s = String::from_utf8_lossy(&out.stdout);
    trace(&format!("[inject] ps result: {}", s.trim()));
    if s.contains("INJECTED") { Ok(format!("injected: {dll}")) } else { Err(format!("inject failed: {}", s.trim())) }
}

// ── APP-SIDE SIGNATURE PAINT (the "hook", without injection) ──────────────────────────────────────
// The DC palettes flycast uploads live in the FIXED working-buffer window (WB_LO..WB_HI, a known
// address — never ASLR'd). So instead of an injected DLL watching skins.dat, WE scan that window for
// palette rows matching a saved skin's signature and WriteProcessMemory the skin straight in. This is
// detection-INDEPENDENT: it needs no fighter-array find (works even when ram_base=0 between games) and
// no injection. Same reliability profile as the hook, minus the hook. Per-side (same-colour mirror)
// stays the paint_palettes refinement above.
// Matching is on the palette's 4-bit-per-channel NIBBLES of colours 1..15 — that IS the DC palette's
// real precision (ARGB4444), so this is exact, not fuzzy, and false hits on non-palette memory are
// astronomically unlikely once is_real_row has already vouched for the row's shape.
fn row_nib(pal: &[u8; 32]) -> [u8; 45] {
    let mut o = [0u8; 45];
    for i in 1..16 {
        let v = (pal[i * 2] as u16) | ((pal[i * 2 + 1] as u16) << 8);
        o[(i - 1) * 3] = ((v >> 8) & 0xF) as u8;
        o[(i - 1) * 3 + 1] = ((v >> 4) & 0xF) as u8;
        o[(i - 1) * 3 + 2] = (v & 0xF) as u8;
    }
    o
}
fn hexhi(c: u8) -> Option<u8> { let d = (c as char).to_digit(16)? as u8; Some(d) }   // value of ONE hex digit (the high nibble of an 8-bit channel)
fn sig_nib(hex: &str) -> Option<[u8; 45]> {
    let b = hex.as_bytes(); if b.len() < 128 { return None; }
    let mut o = [0u8; 45];
    for i in 1..16 { for k in 0..3 { o[(i - 1) * 3 + k] = hexhi(b[i * 8 + k * 2])?; } }
    Some(o)
}
fn hexbyte(hi: u8, lo: u8) -> Option<u8> { Some((hexhi(hi)? << 4) | hexhi(lo)?) }
fn row_from_hex(hex: &str) -> Option<[u8; 32]> {
    let b = hex.as_bytes(); if b.len() < 128 { return None; }
    let mut row = [0u8; 32];
    for i in 0..16 {
        let o = i * 8;
        let (r, g, bl, a) = (hexbyte(b[o], b[o + 1])?, hexbyte(b[o + 2], b[o + 3])?, hexbyte(b[o + 4], b[o + 5])?, hexbyte(b[o + 6], b[o + 7])?);
        let v: u16 = (((a >> 4) as u16) << 12) | (((r >> 4) as u16) << 8) | (((g >> 4) as u16) << 4) | ((bl >> 4) as u16);
        row[i * 2] = (v & 0xff) as u8; row[i * 2 + 1] = (v >> 8) as u8;
    }
    Some(row)
}

/// Read skins.dat (the sig:replacement lines apply_multi already writes) and paint every matching palette
/// row found in the fixed working-buffer window. No fighter-array find, no injection. Returns rows painted.
#[tauri::command]
pub fn paint_signatures() -> Result<String, String> {
    let dat = std::fs::read_to_string("C:\\g\\skins.dat").unwrap_or_default();
    // target: (nibble-key of the sig to match, 32-byte ARGB4444 skin row to write)
    let mut targets: Vec<([u8; 45], [u8; 32])> = Vec::new();
    for line in dat.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') { continue; }
        if let Some((sig, rep)) = line.split_once(':') {
            if let (Some(k), Some(row)) = (sig_nib(sig.trim()), row_from_hex(rep.trim())) { targets.push((k, row)); }
        }
    }
    if targets.is_empty() { return Ok("0".into()); }
    let pid = find_game_pid().ok_or("game not found")?;
    let h = unsafe { OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION | PROCESS_QUERY_INFORMATION, FALSE, pid) }
        .map_err(|e| e.to_string())?;
    let mut painted = 0usize;
    let mut pals: Vec<String> = Vec::new();                        // every distinct on-screen palette this scan sees
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    let (lo, hi) = (WB_LO as usize, WB_HI as usize);
    // Walk only COMMITTED readable regions (VirtualQueryEx) — skip uncommitted gaps instantly instead of
    // blindly ReadProcessMemory-ing dead address space. Same region-walk rpm_occurrences uses.
    let mut addr = lo;
    while addr < hi {
        let mut mbi = MEMORY_BASIC_INFORMATION::default();
        if unsafe { VirtualQueryEx(h, Some(addr as *const c_void), &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) } == 0 { break; }
        let rbase = mbi.BaseAddress as usize; let rsize = mbi.RegionSize;
        if rsize == 0 { break; }
        let prot = mbi.Protect.0;
        let readable = mbi.State == MEM_COMMIT && (prot & PAGE_GUARD.0) == 0 && (prot & PAGE_NOACCESS.0) == 0 && (prot & 0xEE) != 0;
        if readable && rbase < hi && rbase + rsize > lo {
            let a = rbase.max(lo); let b = (rbase + rsize).min(hi);
            let mut cbase = a;
            while cbase < b {
                let n = (b - cbase).min(0x80_0000);                 // 8 MB chunks → bounded memory
                if let Some(buf) = unsafe { read_at(h, cbase, n) } {
                    let mut i = 0usize;
                    while i + 32 <= buf.len() {
                        // cheap pre-reject: colour0 must be transparent (top nibble 0) — kills ~all non-palette rows.
                        if (((buf[i + 1] as u16) << 8 | buf[i] as u16) >> 12) == 0 && is_real_row(&buf[i..i + 32]) {
                            let mut r = [0u8; 32]; r.copy_from_slice(&buf[i..i + 32]);
                            if pals.len() < 128 { let sig = pal_sig(&r); if seen.insert(sig.clone()) { pals.push(sig); } }  // array-free capture source
                            let key = row_nib(&r);
                            for (tk, trow) in &targets {
                                if &key == tk {
                                    if &r != trow {                 // skip if the skin is already applied
                                        let waddr = cbase + i; let mut w = 0usize;
                                        unsafe { let _ = WriteProcessMemory(h, waddr as *const c_void, trow.as_ptr() as *const c_void, 32, Some(&mut w)); }
                                        if w == 32 { painted += 1; }
                                    }
                                    break;
                                }
                            }
                        }
                        i += 0x10;                                  // 16-byte stride (palette rows are >=16-aligned)
                    }
                }
                cbase += n;
            }
        }
        addr = rbase + rsize;
        if addr <= rbase { break; }
    }
    unsafe { let _ = CloseHandle(h); }
    if !pals.is_empty() { *last_wb_pals().lock().unwrap() = pals; }  // hand these to capture_live (array-free live sigs)
    Ok(painted.to_string())
}

