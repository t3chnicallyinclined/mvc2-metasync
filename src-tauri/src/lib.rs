// MvC Collection Live Skins — Tauri v2 backend.
//
// The heavy lifting lives in a D3D11 hook DLL injected into the Steam game (embedded here via
// include_bytes!). This backend does three things:
//   1) apply_skin  — pair a community skin's palette blocks to the character's stock palette lines
//                    (by luminance) and write C:\g\skins.dat, which the hook watches + repaints live.
//   2) inject_hook — write the embedded DLL to temp and inject it into the running game.
//   3) hook_status — report whether the game is running and the hook is installed.
use std::fs;

pub mod mem; // cross-platform process-memory layer (Windows: Win32 APIs; Linux: /proc + process_vm_*)
pub mod sync;
mod rom; // ROM filesystem I/O for the merged Skin Studio editor (Studio tab)

const CHARS_JSON: &str = include_str!("../chars.json");

// Cross-platform runtime data dir. On WINDOWS this MUST stay exactly C:\g — the injected D3D hook DLL is
// compiled to watch C:\g\skins.dat, so changing it breaks Windows skins. On Linux there is no hook (skins
// paint directly via process_vm_writev, reading the same skins.dat), so this is just a persistent, writable
// per-user data dir ($XDG_DATA_HOME/mvc-live-skins or ~/.local/share/mvc-live-skins).
pub(crate) fn runtime_dir() -> std::path::PathBuf {
    #[cfg(windows)] { std::path::PathBuf::from("C:\\g") }
    #[cfg(not(windows))] {
        let base = std::env::var_os("XDG_DATA_HOME").map(std::path::PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| std::path::PathBuf::from(h).join(".local/share")))
            .unwrap_or_else(std::env::temp_dir);
        base.join("mvc-live-skins")
    }
}
fn skins_dat() -> std::path::PathBuf { runtime_dir().join("skins.dat") }
fn chars_runtime() -> std::path::PathBuf { runtime_dir().join("chars.json") }

fn lum(r: u8, g: u8, b: u8) -> f32 { 0.299 * r as f32 + 0.587 * g as f32 + 0.114 * b as f32 }

// character stock signatures; prefer the writable runtime file so P1/P2 + new chars can be added
// without recompiling, fall back to the embedded default.
fn load_chars() -> serde_json::Value {
    if let Ok(s) = fs::read_to_string(chars_runtime()) {
        if let Ok(v) = serde_json::from_str::<serde_json::Value>(&s) { return v; }
    }
    serde_json::from_str(CHARS_JSON).unwrap_or(serde_json::Value::Null)
}

// parse "rrggbbaa..." (16 colors) -> Vec<(r,g,b,a)>
fn parse_line(hex: &str) -> Vec<(u8, u8, u8, u8)> {
    let mut v = Vec::new();
    let mut i = 0;
    let byte = |h: &str, o: usize| u8::from_str_radix(&h[o..o + 2], 16).unwrap_or(0);
    while i + 8 <= hex.len() {
        let s = &hex[i..i + 8];
        v.push((byte(s, 0), byte(s, 2), byte(s, 4), byte(s, 6)));
        i += 8;
    }
    v
}

// parse a captured "PAL256" bank0 (first 128 hex) into 16 RGBA8 colors
fn parse_cap_line(hex: &str) -> Option<[(u8, u8, u8, u8); 16]> {
    if hex.len() < 128 { return None; }
    let mut out = [(0u8, 0u8, 0u8, 0u8); 16];
    for i in 0..16 {
        let o = i * 8;
        let b = |k: usize| u8::from_str_radix(&hex[o + k..o + k + 2], 16).ok();
        out[i] = (b(0)?, b(2)?, b(4)?, b(6)?);
    }
    Some(out)
}
// a character palette line: index0 transparent + several opaque colors
fn is_char_line(p: &[(u8, u8, u8, u8); 16]) -> bool {
    p[0].3 == 0 && p[1..].iter().filter(|c| c.3 == 255).count() >= 8
}

fn permutations(v: &[usize]) -> Vec<Vec<usize>> {
    if v.len() <= 1 { return vec![v.to_vec()]; }
    let mut out = Vec::new();
    for i in 0..v.len() {
        let mut rest = v.to_vec();
        let x = rest.remove(i);
        for mut p in permutations(&rest) { p.insert(0, x); out.push(p); }
    }
    out
}

/// Pair the skin's N palette blocks (16 colors each, 0xRRGGBB) to the character's N stock lines by
/// luminance, then write skins.dat. `palette` = N*16 packed RGB values.
#[tauri::command]
fn apply_skin(character: String, palette: Vec<u32>) -> Result<String, String> {
    let chars = load_chars();
    let c = chars.get(&character).ok_or_else(|| format!("unknown character '{}'", character))?;
    let stock_hexes: Vec<String> = c["stock_lines"].as_array().ok_or("no stock_lines")?
        .iter().map(|x| x.as_str().unwrap_or("").to_string()).collect();
    let stock: Vec<Vec<(u8, u8, u8, u8)>> = stock_hexes.iter().map(|h| parse_line(h)).collect();
    let n = stock.len();
    if palette.len() < n * 16 { return Err(format!("palette has {} colors, need {}", palette.len(), n * 16)); }

    let blocks: Vec<Vec<(u8, u8, u8)>> = (0..n).map(|bi| {
        (0..16).map(|i| { let v = palette[bi * 16 + i]; (((v >> 16) & 0xff) as u8, ((v >> 8) & 0xff) as u8, (v & 0xff) as u8) }).collect()
    }).collect();

    let idx: Vec<usize> = (0..n).collect();
    let mut best = (f32::MAX, idx.clone());
    for p in permutations(&idx) {
        let mut cost = 0.0;
        for bi in 0..n {
            let li = p[bi];
            for k in 0..16 {
                let (br, bg, bb) = blocks[bi][k];
                let (sr, sg, sb, _) = stock[li][k];
                cost += (lum(br, bg, bb) - lum(sr, sg, sb)).abs();
            }
        }
        if cost < best.0 { best = (cost, p); }
    }
    let perm = best.1;

    let mut out = format!("# {} live skin\n", character);
    for bi in 0..n {
        let li = perm[bi];
        let sig: String = stock[li].iter().map(|(r, g, b, a)| format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a)).collect();
        let rep: String = (0..16).map(|i| { let (r, g, b) = blocks[bi][i]; let a = stock[li][i].3; format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a) }).collect();
        out.push_str(&format!("{}:{}\n", sig, rep));
    }
    fs::create_dir_all(runtime_dir()).ok();
    fs::write(skins_dat(), out).map_err(|e| e.to_string())?;
    Ok(format!("applied {} ({} lines)", character, n))
}

#[tauri::command]
fn clear_skin() -> Result<String, String> {
    fs::create_dir_all(runtime_dir()).ok();
    fs::write(skins_dat(), "# no skin\n").map_err(|e| e.to_string())?;
    Ok("cleared".into())
}

// Auto-learn a character's stock palette lines from the LIVE game: enable the hook's palette dump,
// capture what the on-screen character uploads, then match a reference skin's 3 blocks to the
// captured lines by luminance. Saves signatures to the runtime chars.json so apply_skin then works.
#[tauri::command]
fn learn_character(character: String, palette: Vec<u32>) -> Result<String, String> {
    let ref_palette = palette;
    if ref_palette.len() < 48 { return Err("need a reference skin".into()); }
    fs::create_dir_all(runtime_dir()).ok();
    // Sample the on-screen palettes via direct RPM (no hook, no file) over ~2.2s while the character moves,
    // collecting distinct character-palette lines from the reader's snapshot.
    let mut caps: Vec<[(u8, u8, u8, u8); 16]> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for _ in 0..11 {
        for line in sync::live_palettes() {
            if let Some(p) = parse_cap_line(&line) {
                if is_char_line(&p) {
                    let key: String = p.iter().map(|c| format!("{:02x}{:02x}{:02x}", c.0, c.1, c.2)).collect();
                    if seen.insert(key) { caps.push(p); }
                }
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(200));
    }
    if caps.len() < 3 {
        return Err(format!("only {} palettes captured — make sure {} is on screen and MOVING (walk + a couple attacks), then Learn again", caps.len(), character));
    }
    let blocks: Vec<[(u8, u8, u8); 16]> = (0..3).map(|bi| {
        let mut b = [(0u8, 0u8, 0u8); 16];
        for i in 0..16 { let v = ref_palette[bi * 16 + i]; b[i] = (((v >> 16) & 0xff) as u8, ((v >> 8) & 0xff) as u8, (v & 0xff) as u8); }
        b
    }).collect();
    let lum = |r: u8, g: u8, b: u8| 0.299 * r as f32 + 0.587 * g as f32 + 0.114 * b as f32;
    let mut pairs: Vec<(f32, usize, usize)> = Vec::new();
    for bi in 0..3 {
        for (ci, cap) in caps.iter().enumerate() {
            let mut cost = 0.0;
            for k in 1..16 { cost += (lum(blocks[bi][k].0, blocks[bi][k].1, blocks[bi][k].2) - lum(cap[k].0, cap[k].1, cap[k].2)).abs(); }
            pairs.push((cost, bi, ci));
        }
    }
    pairs.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap());
    let mut chosen: [Option<usize>; 3] = [None, None, None];
    let mut used = std::collections::HashSet::new();
    for (_, bi, ci) in pairs {
        if chosen[bi].is_none() && !used.contains(&ci) { chosen[bi] = Some(ci); used.insert(ci); }
    }
    let lines: Vec<String> = (0..3).map(|bi| {
        caps[chosen[bi].unwrap()].iter().map(|c| format!("{:02x}{:02x}{:02x}{:02x}", c.0, c.1, c.2, c.3)).collect()
    }).collect();
    let mut chars = load_chars();
    if !chars.is_object() { chars = serde_json::json!({}); }
    chars[&character] = serde_json::json!({ "stock_lines": lines });
    fs::write(chars_runtime(), serde_json::to_string_pretty(&chars).unwrap_or_default()).map_err(|e| e.to_string())?;
    Ok(format!("learned {} from {} captured palettes", character, caps.len()))
}

// Capture the live on-screen palettes: toggle the hook's dump, wait, return distinct bank0 hexes.
// The frontend identifies each character by matching against the ROM stock palettes.
#[tauri::command]
fn capture_live() -> Result<Vec<String>, String> {
    // O(1): the reader thread parses the hook's palette dump continuously; just return its snapshot.
    Ok(sync::live_palettes())
}

#[allow(dead_code)]
fn capture_live_legacy() -> Result<Vec<String>, String> {
    fs::create_dir_all(runtime_dir()).ok();
    fs::write(runtime_dir().join("dump.txt"), "1").ok();
    let dump = fs::read_to_string(runtime_dir().join("pal_dump.txt")).unwrap_or_default();
    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for line in dump.lines() {
        if let Some(rest) = line.strip_prefix("PAL256 rgba=") {
            if rest.len() >= 128 {
                let bank0 = rest[..128].to_string();
                // char-line: index0 transparent (alpha 00) + at least a few opaque colors
                if &bank0[6..8] == "00" && seen.insert(bank0.clone()) { out.push(bank0); }
            }
        }
    }
    Ok(out)
}

// Apply a skin to EXACT target palette lines (a detected character's captured lines). Pairs the skin's
// blocks to each target line by luminance. Writes skins.dat -> only those palettes recolor.
#[tauri::command]
fn apply_sigs(sigs: Vec<String>, palette: Vec<u32>) -> Result<String, String> {
    if sigs.is_empty() { return Err("no target palettes".into()); }
    if palette.len() < 16 { return Err("bad skin".into()); }
    let stock: Vec<Vec<(u8, u8, u8, u8)>> = sigs.iter().map(|h| parse_line(h)).collect();
    let nblk = palette.len() / 16;
    let blocks: Vec<Vec<(u8, u8, u8)>> = (0..nblk).map(|bi| {
        (0..16).map(|i| { let v = palette[bi * 16 + i]; (((v >> 16) & 0xff) as u8, ((v >> 8) & 0xff) as u8, (v & 0xff) as u8) }).collect()
    }).collect();
    let mut out = String::from("# detected-character skin\n");
    for line in &stock {
        if line.len() < 16 { continue; }
        // best skin block for this line by luminance
        let mut best = (f32::MAX, 0usize);
        for (bi, blk) in blocks.iter().enumerate() {
            let mut c = 0.0;
            for i in 1..16 { c += (lum(blk[i].0, blk[i].1, blk[i].2) - lum(line[i].0, line[i].1, line[i].2)).abs(); }
            if c < best.0 { best = (c, bi); }
        }
        let blk = &blocks[best.1];
        let sig: String = line.iter().map(|(r, g, b, a)| format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a)).collect();
        let rep: String = (0..16).map(|i| { let (r, g, b) = blk[i]; let a = line[i].3; format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a) }).collect();
        out.push_str(&format!("{}:{}\n", sig, rep));
    }
    fs::create_dir_all(runtime_dir()).ok();
    fs::write(skins_dat(), out).map_err(|e| e.to_string())?;
    Ok(format!("applied to {} palette line(s)", stock.len()))
}

// build skins.dat lines for one target: pair the skin's blocks to each captured line by luminance
fn sigs_lines(sigs: &[String], palette: &[u32]) -> String {
    let stock: Vec<Vec<(u8, u8, u8, u8)>> = sigs.iter().map(|h| parse_line(h)).collect();
    let nblk = palette.len() / 16;
    let blocks: Vec<Vec<(u8, u8, u8)>> = (0..nblk).map(|bi| {
        (0..16).map(|i| { let v = palette[bi * 16 + i]; (((v >> 16) & 0xff) as u8, ((v >> 8) & 0xff) as u8, (v & 0xff) as u8) }).collect()
    }).collect();
    let mut out = String::new();
    for line in &stock {
        if line.len() < 16 || blocks.is_empty() { continue; }
        let mut best = (f32::MAX, 0usize);
        for (bi, blk) in blocks.iter().enumerate() {
            let mut c = 0.0;
            for i in 1..16 { c += (lum(blk[i].0, blk[i].1, blk[i].2) - lum(line[i].0, line[i].1, line[i].2)).abs(); }
            if c < best.0 { best = (c, bi); }
        }
        let blk = &blocks[best.1];
        let sig: String = line.iter().map(|(r, g, b, a)| format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a)).collect();
        let rep: String = (0..16).map(|i| { let (r, g, b) = blk[i]; let a = line[i].3; format!("{:02x}{:02x}{:02x}{:02x}", r, g, b, a) }).collect();
        out.push_str(&format!("{}:{}\n", sig, rep));
    }
    out
}

#[derive(serde::Deserialize)]
struct SkinEntry { sigs: Vec<String>, palette: Vec<u32> }
// Apply MANY targeted skins at once (each character keeps its skin). Replaces skins.dat wholesale.
// `entries` is taken as a lenient Value: the Linux/WebKitGTK IPC can hand an EMPTY array through as the string
// "" (Tauri serialization quirk), which a strict `Vec<SkinEntry>` param rejects with "invalid type string".
// So we accept any JSON: an array parses to entries; anything else (""/null) means "no skins" → clear skins.dat.
#[tauri::command]
fn apply_multi(entries: serde_json::Value) -> Result<String, String> {
    let list: Vec<SkinEntry> = if entries.is_array() {
        serde_json::from_value(entries).unwrap_or_default()
    } else {
        Vec::new()
    };
    fs::create_dir_all(runtime_dir()).ok();
    let mut out = String::from("# live skins\n");
    for e in &list { if e.palette.len() >= 16 { out.push_str(&sigs_lines(&e.sigs, &e.palette)); } }
    fs::write(skins_dat(), out).map_err(|e| e.to_string())?;
    Ok(format!("{} skin(s) active", list.len()))
}

// Drop the direct-paint per-DatPal row cache on each new match/select — the DatPals relocate per match, so
// the next Live Paint re-scans fresh instead of trusting stale offsets. (Was: signalling the retired hook.)
#[tauri::command]
fn reset_hook_regions() -> Result<(), String> {
    sync::clear_row_cache();
    Ok(())
}

// Universal reset: clear all skins + effects -> back to stock.
#[tauri::command]
fn reset_all() -> Result<String, String> {
    fs::create_dir_all(runtime_dir()).ok();
    let _ = fs::write(skins_dat(), "# no skin\n");
    let _ = fs::write(runtime_dir().join("effect.txt"), "0 80");
    let _ = fs::write(runtime_dir().join("effect_targets.txt"), "");
    Ok("reset to stock".into())
}

// live effect: mode (0=off 1=rainbow 2=spread 3=acid 4=strobe 5=pulse) + speed (deg/sec)
#[tauri::command]
fn set_effect(mode: u8, speed: i32) -> Result<String, String> {
    fs::create_dir_all(runtime_dir()).ok();
    fs::write(runtime_dir().join("effect.txt"), format!("{} {}", mode, speed)).map_err(|e| e.to_string())?;
    Ok(format!("effect {}", mode))
}

// Restrict effects to one character's palettes (empty = all sprites). Writes that character's
// signatures to effect_targets.txt, which the hook uses to gate the effect.
#[tauri::command]
fn set_effect_target(character: String) -> Result<String, String> {
    fs::create_dir_all(runtime_dir()).ok();
    if character.is_empty() {
        let _ = fs::write(runtime_dir().join("effect_targets.txt"), "");
        return Ok("effects: all sprites".into());
    }
    let chars = load_chars();
    let c = chars.get(&character).ok_or_else(|| format!("no signatures for {} yet — Learn it first", character))?;
    let lines: Vec<String> = c["stock_lines"].as_array().ok_or("no stock_lines")?
        .iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect();
    if lines.is_empty() { return Err("no signatures".into()); }
    fs::write(runtime_dir().join("effect_targets.txt"), lines.join("\n")).map_err(|e| e.to_string())?;
    Ok(format!("effects: {} only", character))
}

// Auto-detect the Steam install of the MvC Fighting Collection (app 2634890) and locate game_50.arc.
#[cfg(windows)]
#[tauri::command]
fn detect_rom() -> Result<String, String> {
    let ps = r#"
$steam = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -Name SteamPath -ErrorAction SilentlyContinue).SteamPath
if(-not $steam){ Write-Output 'NOSTEAM'; exit }
$libs = New-Object System.Collections.Generic.List[string]
$libs.Add($steam)
$vdf = Join-Path $steam 'steamapps\libraryfolders.vdf'
if(Test-Path $vdf){ Get-Content $vdf | Select-String '"path"\s+"(.+?)"' | ForEach-Object { $libs.Add($_.Matches.Groups[1].Value.Replace('\\','\')) } }
foreach($lib in $libs){
  $common = Join-Path $lib 'steamapps\common'
  if(Test-Path $common){
    $arc = Get-ChildItem $common -Recurse -Filter game_50.arc -ErrorAction SilentlyContinue | Select-Object -First 1
    if($arc){ Write-Output $arc.FullName; exit }
  }
}
Write-Output 'NOTFOUND'
"#;
    let out = std::process::Command::new("powershell").args(["-ExecutionPolicy", "Bypass", "-Command", ps]).output().map_err(|e| e.to_string())?;
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    match s.as_str() {
        "NOSTEAM" => Err("Steam not found in registry".into()),
        "NOTFOUND" | "" => Err("game_50.arc not found in any Steam library — set the folder manually".into()),
        p => { fs::create_dir_all(runtime_dir()).ok(); let _ = fs::write(runtime_dir().join("rom_path.txt"), p); Ok(p.to_string()) }
    }
}

// Auto-detect the Steam install of the MvC Fighting Collection on Linux (Bazzite/Steam Deck/desktop). No
// registry here, so we probe the known Steam roots (native + Flatpak) and parse each root's
// libraryfolders.vdf for extra library "path" entries (games can live on other drives), then look for the
// ROM at <lib>/steamapps/common/MARVEL vs. CAPCOM Fighting Collection/nativeDX11x64/arc/pc/game_50.arc.
#[cfg(not(windows))]
#[tauri::command]
fn detect_rom() -> Result<String, String> {
    let home = std::env::var_os("HOME").map(std::path::PathBuf::from);
    // Steam root candidates (first that exists wins for its own library; all are scanned).
    let mut roots: Vec<std::path::PathBuf> = Vec::new();
    if let Some(h) = &home {
        roots.push(h.join(".local/share/Steam"));
        roots.push(h.join(".steam/steam"));
        roots.push(h.join(".steam/root"));
        roots.push(h.join(".var/app/com.valvesoftware.Steam/.local/share/Steam")); // Flatpak Steam
    }
    // Build the full library list: each existing Steam root + every "path" entry in its libraryfolders.vdf.
    let mut libs: Vec<std::path::PathBuf> = Vec::new();
    let mut push_lib = |libs: &mut Vec<std::path::PathBuf>, p: std::path::PathBuf| {
        if !libs.iter().any(|l| l == &p) { libs.push(p); }
    };
    for root in &roots {
        if !root.exists() { continue; }
        push_lib(&mut libs, root.clone());
        let vdf = root.join("steamapps/libraryfolders.vdf");
        if let Ok(txt) = fs::read_to_string(&vdf) {
            for line in txt.lines() {
                // format: \t\t"path"\t\t"/path/to/library"  — scan for "path" then the next quoted value.
                let t = line.trim();
                if let Some(rest) = t.strip_prefix("\"path\"") {
                    if let Some(a) = rest.find('"') {
                        if let Some(b) = rest[a + 1..].find('"') {
                            let val = &rest[a + 1..a + 1 + b];
                            if !val.is_empty() { push_lib(&mut libs, std::path::PathBuf::from(val)); }
                        }
                    }
                }
            }
        }
    }
    let rel = "steamapps/common/MARVEL vs. CAPCOM Fighting Collection/nativeDX11x64/arc/pc/game_50.arc";
    for lib in &libs {
        let cand = lib.join(rel);
        if cand.exists() {
            let s = cand.to_string_lossy().to_string();
            fs::create_dir_all(runtime_dir()).ok();
            let _ = fs::write(runtime_dir().join("rom_path.txt"), &s); // persist, same as set_rom_path
            return Ok(s);
        }
    }
    Err("game_50.arc not found in any Steam library — set the folder manually".into())
}

// Manually set / verify the ROM path (accepts the game_50.arc file or its folder).
#[tauri::command]
fn set_rom_path(path: String) -> Result<String, String> {
    let p = std::path::Path::new(&path);
    let arc = if p.is_dir() {
        let cand = p.join("nativeDX11x64").join("arc").join("pc").join("game_50.arc");
        if cand.exists() { cand } else {
            // fallback: search under the folder
            walk_for_arc(p).ok_or("game_50.arc not found under that folder")?
        }
    } else { p.to_path_buf() };
    if !arc.exists() { return Err("game_50.arc not found".into()); }
    fs::create_dir_all(runtime_dir()).ok();
    let s = arc.to_string_lossy().to_string();
    let _ = fs::write(runtime_dir().join("rom_path.txt"), &s);
    Ok(s)
}

fn walk_for_arc(dir: &std::path::Path) -> Option<std::path::PathBuf> {
    let mut stack = vec![dir.to_path_buf()];
    let mut budget = 20000;
    while let Some(d) = stack.pop() {
        if budget == 0 { break; } budget -= 1;
        if let Ok(rd) = fs::read_dir(&d) {
            for e in rd.flatten() {
                let p = e.path();
                if p.is_dir() { stack.push(p); }
                else if p.file_name().map(|n| n == "game_50.arc").unwrap_or(false) { return Some(p); }
            }
        }
    }
    None
}

#[tauri::command]
fn get_rom_path() -> String { fs::read_to_string(runtime_dir().join("rom_path.txt")).unwrap_or_default().trim().to_string() }

// ── Auto-update (tauri-plugin-updater) — driven from Rust so it works under withGlobalTauri (no JS bundler).
//    The frontend just prompts: check_update returns the pending version/notes (or null), install_update
//    downloads the SIGNED package, installs it, and relaunches.
#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<Option<serde_json::Value>, String> {
    use tauri_plugin_updater::UpdaterExt;
    match app.updater().map_err(|e| e.to_string())?.check().await {
        Ok(Some(u)) => Ok(Some(serde_json::json!({ "version": u.version, "notes": u.body }))),
        Ok(None) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<String, String> {
    // WINDOWS: seamless NSIS in-place install + relaunch (app.restart diverges -> !).
    #[cfg(target_os = "windows")]
    {
        use tauri_plugin_updater::UpdaterExt;
        let update = app.updater().map_err(|e| e.to_string())?
            .check().await.map_err(|e| e.to_string())?
            .ok_or_else(|| "no update available".to_string())?;
        update.download_and_install(|_downloaded, _total| {}, || {}).await.map_err(|e| e.to_string())?;
        app.restart();   // relaunch into the freshly installed version
    }
    // LINUX (AppImage): tauri's in-place AppImage swap is unreliable on immutable distros (Bazzite/Steam Deck)
    // and has crashed on update. Open the releases page for a manual download (which works reliably) instead.
    #[cfg(not(target_os = "windows"))]
    {
        let _ = &app;
        const REL: &str = "https://github.com/t3chnicallyinclined/mvc2-metasync/releases/latest";
        std::process::Command::new("xdg-open").arg(REL).spawn().map_err(|e| e.to_string())?;
        Ok("opened_release".into())
    }
}

pub fn run() {
    // Linux/Proton: WebKitGTK's DMABUF renderer blanks/exits the window on some GPU+Mesa combos (and headless);
    // disabling it is the standard Tauri-on-Linux fix and keeps GPU compositing. No-op if the user set it.
    #[cfg(not(windows))]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    sync::kill_other_instances(); // an in-place update can leave the old instance running → two readers/recorders. Kill stale copies first.
    sync::start_reader(); // single background thread owns all game-memory reads (keeps the UI unblockable)
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init()) // ROM file picker for the Studio tab
        .plugin(tauri_plugin_updater::Builder::new().build()) // signed auto-update from nobd.net
        .invoke_handler(tauri::generate_handler![apply_skin, clear_skin, learn_character, capture_live, apply_sigs, apply_multi, reset_all, reset_hook_regions, set_effect, set_effect_target, detect_rom, set_rom_path, get_rom_path,
            check_update, install_update,
            sync::sync_self, sync::detect_opponent, sync::sync_publish, sync::set_location, sync::search_cities, sync::sync_unpublish, sync::sync_fetch_peers,
            sync::detect_state, sync::sync_heartbeat, sync::sync_presence, sync::paint_palettes, sync::paint_live, sync::paint_signatures, sync::inject_hook, sync::get_record, sync::leaderboard, sync::coins, sync::wager_offer, sync::wager_respond, sync::wager_cancel, sync::wager_heartbeat, sync::wager_state, sync::wager_open, sync::profile, sync::session_stats, sync::matchup, sync::playerstats, sync::tierlist, sync::regions, sync::app_version, sync::set_manual_side, sync::capture_start, sync::capture_stop, sync::capture_status,
            sync::get_share_gameplay, sync::set_share_gameplay, sync::record_consent, sync::suggest_stat, sync::ensure_registered, sync::fetch_changelog,
            sync::contest_match, sync::confirm_match, sync::result_notifications,
            sync::backup_skins, sync::restore_skins, sync::fetch_defaults, sync::read_my_lobby,
            sync::rt_subscribe, sync::rt_unsubscribe, sync::report_live_match,
            sync::names, sync::tourney_list, sync::tourney_get, sync::tourney_subscribe, sync::tourney_unsubscribe, sync::tourney_create, sync::tourney_update, sync::tourney_register,
            sync::tourney_unregister, sync::tourney_checkin, sync::tourney_seed, sync::tourney_start, sync::tourney_report,
            sync::tourney_add_entrant, sync::tourney_match_reset, sync::tourney_match_run, sync::tourney_checkin_ctl, sync::tourney_entrant_dq, sync::tourney_entrant_update, sync::tourney_delete,
            sync::tourney_host_add, sync::tourney_host_remove, sync::tourney_host_assign, sync::tourney_host_heartbeat,
            sync::tourney_set_score, sync::tourney_match_read, sync::tourney_lobby_report, sync::open_external,
            sync::skins_save, sync::skins_list, sync::skins_delete,
            rom::rom_size, rom::rom_read, rom::rom_write, rom::rom_backup, rom::backup_rom, rom::rom_prepare, rom::bake_palette, rom::read_char_palette, rom::extract_char_dat])
        .run(tauri::generate_context!())
        .expect("error while running MvC Collection Live Skins");
}
