// ROM filesystem I/O for the merged MvC2 Skin Studio editor (Studio tab).
//
// The editor's decode + palette/pixel edit + byte-faithful bake all run in JS
// (web/studio/rom-reader.mjs / rom-bake.mjs). The only thing the WebView can't do is real
// filesystem I/O on the user's ~1.2 GB track03.bin ROM. These five commands provide exactly that
// as positioned range reads/writes, so the huge file is never read or rewritten whole.
// web/studio/platform.mjs duck-types the File System Access API over them, so the editor is unchanged.
//
// Lifted verbatim from mvc2-skin-studio/src-tauri/src/lib.rs (BYOR — ships no game data).

use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::ipc::Response;

// Inflating the ~112 MB `mvsc2` payload out of game_50.arc costs ~1 s, and the Studio pulls one char's
// DAT after another, so we cache the last-inflated payload keyed on (resolved path, file len, mtime secs).
// bake_palette clears it after a write so a re-extract always sees the freshly-baked bytes.
static MVSC2_CACHE: Mutex<Option<(String, u64, u64, Vec<u8>)>> = Mutex::new(None);

fn file_stamp(path: &str) -> (u64, u64) {
    let md = match std::fs::metadata(path) { Ok(m) => m, Err(_) => return (0, 0) };
    let mtime = md.modified().ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_secs()).unwrap_or(0);
    (md.len(), mtime)
}

fn clear_mvsc2_cache() { if let Ok(mut g) = MVSC2_CACHE.lock() { *g = None; } }

// A Dreamcast GDI data track: raw 2352-byte sectors; the ISO-9660 PVD's "CD001" sits at 16*2352+16.
const PVD_CD001_OFFSET: u64 = 16 * 2352 + 16;

/// Size of the ROM in bytes (the FS-Access `File.size` equivalent).
#[tauri::command]
pub fn rom_size(path: String) -> Result<u64, String> {
    std::fs::metadata(&path).map(|m| m.len()).map_err(|e| e.to_string())
}

/// Read `length` bytes at `offset`, returned as a raw binary IPC body (→ ArrayBuffer in JS).
/// `length` is clamped to the bytes actually available (matches browser `Blob.slice`).
#[tauri::command]
pub fn rom_read(path: String, offset: u64, length: u64) -> Result<Response, String> {
    let mut f = File::open(&path).map_err(|e| e.to_string())?;
    let size = f.metadata().map_err(|e| e.to_string())?.len();
    let avail = size.saturating_sub(offset);
    let len = length.min(avail) as usize;
    f.seek(SeekFrom::Start(offset)).map_err(|e| e.to_string())?;
    let mut buf = vec![0u8; len];
    f.read_exact(&mut buf).map_err(|e| e.to_string())?;
    Ok(Response::new(buf))
}

/// Write `data` at `position`, in place (read+write, no truncate/create) so the huge file is preserved.
#[tauri::command]
pub fn rom_write(path: String, position: u64, data: Vec<u8>) -> Result<(), String> {
    let mut f = OpenOptions::new().read(true).write(true).open(&path).map_err(|e| e.to_string())?;
    f.seek(SeekFrom::Start(position)).map_err(|e| e.to_string())?;
    f.write_all(&data).map_err(|e| e.to_string())?;
    Ok(())
}

/// Create `<path>.bak` if it doesn't already exist. Returns true if a new backup was made.
#[tauri::command]
pub fn rom_backup(path: String) -> Result<bool, String> {
    let bak = format!("{path}.bak");
    if Path::new(&bak).exists() { return Ok(false); }
    std::fs::copy(&path, &bak).map_err(|e| e.to_string())?;
    Ok(true)
}

/// True if `p` looks like a MvC2 GDI data track (the ISO PVD's "CD001" is where it should be).
fn is_data_track(p: &Path) -> bool {
    let Ok(mut f) = File::open(p) else { return false };
    if f.seek(SeekFrom::Start(PVD_CD001_OFFSET)).is_err() { return false; }
    let mut b = [0u8; 6];
    f.read_exact(&mut b).is_ok() && &b[1..6] == b"CD001"
}

/// Recursively find the data track: prefer `track03.bin`, else the largest valid `.bin/.iso/.img`.
fn find_data_track(dir: &Path) -> Option<String> {
    let mut best: Option<(u64, PathBuf)> = None;
    let mut named: Option<PathBuf> = None;
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        let Ok(rd) = std::fs::read_dir(&d) else { continue };
        for entry in rd.flatten() {
            let path = entry.path();
            if path.is_dir() { stack.push(path); continue; }
            let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
            if !matches!(ext.as_str(), "bin" | "iso" | "img") || !is_data_track(&path) { continue; }
            let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("").to_lowercase();
            if name == "track03.bin" { named = Some(path.clone()); }
            let size = entry.metadata().map(|m| m.len()).unwrap_or(0);
            if best.as_ref().map(|(s, _)| size > *s).unwrap_or(true) { best = Some((size, path)); }
        }
    }
    named.or(best.map(|(_, p)| p)).map(|p| p.to_string_lossy().into_owned())
}

fn zip_extract_dir(zip: &Path) -> PathBuf {
    let stem = zip.file_stem().and_then(|s| s.to_str()).unwrap_or("rom");
    zip.parent().unwrap_or_else(|| Path::new(".")).join(format!("{stem}_extracted"))
}

fn extract_zip(zip: &Path, out: &Path) -> Result<(), String> {
    let f = File::open(zip).map_err(|e| e.to_string())?;
    let mut archive = zip::ZipArchive::new(f).map_err(|e| e.to_string())?;
    for i in 0..archive.len() {
        let mut entry = archive.by_index(i).map_err(|e| e.to_string())?;
        let Some(rel) = entry.enclosed_name() else { continue };
        let dest = out.join(rel);
        if entry.is_dir() { std::fs::create_dir_all(&dest).ok(); continue; }
        if let Some(parent) = dest.parent() { std::fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
        let mut outf = File::create(&dest).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut outf).map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ── Steam Collection PALETTE BAKE — make a Studio/live palette skin permanent in game_50.arc ──
// Ports the proven Python repack: parse ARC v7 → zlib-inflate the single `bin\mvsc2` payload → the
// embedded Sega AFS at 0x40 → char DAT = AFS entry 209+cid → the DAT's 16-colour bank-0 palette at
// dat+u32(dat,8), ARGB4444 LE → overwrite it → zlib-deflate → rebuild the ARC (same-size keeps the
// decomp-size field byte-exact, so the game inflates a byte-identical container). Always writes a .bak
// first. `colors` = 16 packed 0xRRGGBB values (index 0 forced transparent).
fn u16le(a: &[u8], o: usize) -> u16 { a[o] as u16 | ((a[o + 1] as u16) << 8) }
fn u32le(a: &[u8], o: usize) -> u32 { a[o] as u32 | ((a[o+1] as u32)<<8) | ((a[o+2] as u32)<<16) | ((a[o+3] as u32)<<24) }

// resolve a folder / install path / .arc to the actual game_50.arc
fn resolve_arc(p: &str) -> String {
    let path = Path::new(p);
    if path.is_file() && p.to_lowercase().ends_with(".arc") { return p.to_string(); }
    let base = if path.is_dir() { path.to_path_buf() } else { path.parent().map(|x| x.to_path_buf()).unwrap_or_default() };
    for cand in [base.join("nativeDX11x64").join("arc").join("pc").join("game_50.arc"), base.join("game_50.arc")] {
        if cand.exists() { return cand.to_string_lossy().into_owned(); }
    }
    p.to_string()
}

// Locate a character's 16-colour bank-0 palette inside an inflated `mvsc2` payload:
// AFS entry 209+cid = the char DAT; the DAT's palette sits at dat + u32(dat,8). Returns its absolute
// byte offset. Shared read-half of bake_palette (write) and read_char_palette (read).
fn char_pal_offset(mvsc2: &[u8], char_id: u32) -> Result<usize, String> {
    let afs = 0x40usize;
    if mvsc2.len() < afs + 8 { return Err("mvsc2 too small".into()); }
    let acount = u32le(mvsc2, afs + 4) as usize;
    let idx = 209 + char_id as usize;
    if idx >= acount { return Err(format!("char {char_id} (AFS {idx}) out of {acount} entries")); }
    let eoff = u32le(mvsc2, afs + 8 + idx * 8) as usize;
    let dat = afs + eoff;
    if dat + 12 > mvsc2.len() { return Err("DAT header out of range".into()); }
    let pal_abs = dat + u32le(mvsc2, dat + 8) as usize;
    if pal_abs + 32 > mvsc2.len() { return Err("palette out of range".into()); }
    Ok(pal_abs)
}

// Decode the 16 ARGB4444-LE colours at a char's palette offset into 16 packed 0xRRGGBB values
// (index 0 = 0 / transparent). Each 4-bit channel is expanded ×17 (0xF → 0xFF) — the exact inverse of
// bake_palette's write, so an unbaked char round-trips to its stock palette.
fn read_pal_from(mvsc2: &[u8], char_id: u32) -> Result<Vec<u32>, String> {
    let pal_abs = char_pal_offset(mvsc2, char_id)?;
    let mut out = Vec::with_capacity(16);
    for i in 0..16 {
        if i == 0 { out.push(0); continue; }
        let v = u16le(mvsc2, pal_abs + i * 2);
        let r = (((v >> 8) & 0xF) * 17) as u32;
        let g = (((v >> 4) & 0xF) * 17) as u32;
        let b = ((v & 0xF) * 17) as u32;
        out.push((r << 16) | (g << 8) | b);
    }
    Ok(out)
}

#[tauri::command]
pub fn bake_palette(arc_path: String, char_id: u32, colors: Vec<u32>) -> Result<String, String> {
    use std::io::{Read, Write};
    let arc_path = resolve_arc(&arc_path);
    let orig = std::fs::read(&arc_path).map_err(|e| format!("read arc: {e}"))?;
    if orig.len() < 88 || &orig[0..4] != b"ARC\0" { return Err("not a Capcom ARC (game_50.arc)".into()); }
    if u16le(&orig, 4) != 7 || u16le(&orig, 6) != 1 { return Err("unexpected ARC version/count".into()); }
    let toc = 8usize;
    let exth = u32le(&orig, toc + 64);
    let csize = u32le(&orig, toc + 68) as usize;
    let dsize_raw = u32le(&orig, toc + 72);
    let doff = u32le(&orig, toc + 76) as usize;
    if doff + csize > orig.len() { return Err("ARC payload out of range".into()); }

    // inflate the mvsc2 payload
    let mut mvsc2 = Vec::new();
    flate2::read::ZlibDecoder::new(&orig[doff..doff + csize]).read_to_end(&mut mvsc2).map_err(|e| format!("inflate: {e}"))?;
    let orig_decomp = mvsc2.len();

    // AFS → char DAT → 16-colour bank-0 palette (shared read-half with read_char_palette)
    let pal_abs = char_pal_offset(&mvsc2, char_id)?;

    // write 16 ARGB4444 colours (index 0 transparent)
    for i in 0..16 {
        let (a, r, g, b) = if i == 0 { (0u16, 0u16, 0u16, 0u16) } else {
            let c = colors.get(i).copied().unwrap_or(0);
            let q = |x: u32| (((x as f32) / 17.0).round() as u16) & 0xF;
            (0xF, q((c >> 16) & 0xff), q((c >> 8) & 0xff), q(c & 0xff))
        };
        let v = (a << 12) | (r << 8) | (g << 4) | b;
        mvsc2[pal_abs + i * 2] = (v & 0xff) as u8;
        mvsc2[pal_abs + i * 2 + 1] = (v >> 8) as u8;
    }

    // deflate + rebuild ARC (same-size → keep the decomp-size field byte-exact)
    let mut enc = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::new(9));
    enc.write_all(&mvsc2).map_err(|e| e.to_string())?;
    let comp = enc.finish().map_err(|e| e.to_string())?;
    let dsz = if mvsc2.len() == orig_decomp { dsize_raw } else { (dsize_raw & 0xE000_0000) | (mvsc2.len() as u32 & 0x1FFF_FFFF) };
    let mut out = Vec::with_capacity(doff + comp.len());
    out.extend_from_slice(b"ARC\0");
    out.extend_from_slice(&7u16.to_le_bytes());
    out.extend_from_slice(&1u16.to_le_bytes());
    out.extend_from_slice(&orig[toc..toc + 64]);           // keep the entry name bytes
    out.extend_from_slice(&exth.to_le_bytes());
    out.extend_from_slice(&(comp.len() as u32).to_le_bytes());
    out.extend_from_slice(&dsz.to_le_bytes());
    out.extend_from_slice(&(doff as u32).to_le_bytes());
    if out.len() > doff { return Err("ARC header larger than payload offset".into()); }
    out.resize(doff, 0);
    out.extend_from_slice(&comp);

    // safety: verify our container inflates back to the edited bytes before we touch the real file
    let mut check = Vec::new();
    flate2::read::ZlibDecoder::new(&out[doff..]).read_to_end(&mut check).map_err(|e| format!("verify: {e}"))?;
    if check != mvsc2 { return Err("round-trip verify failed — not writing".into()); }

    let bak = format!("{arc_path}.bak");
    if !Path::new(&bak).exists() { std::fs::copy(&arc_path, &bak).map_err(|e| format!("backup: {e}"))?; }
    std::fs::write(&arc_path, &out).map_err(|e| format!("write arc: {e}"))?;
    clear_mvsc2_cache(); // the on-disk arc changed — force a re-inflate on the next extract
    Ok(format!("baked char {char_id} palette · {} bytes · .bak {}", out.len(), if Path::new(&bak).exists() { "ready" } else { "?" }))
}

/// Read a character's CURRENT bank-0 palette from game_50.arc as 16 packed 0xRRGGBB values
/// (index 0 transparent). The inverse of `bake_palette`, so an unbaked char returns its stock palette and
/// a baked one returns the baked colours — letting the app diff against the character's stock palette to
/// detect a pre-existing custom bake (baked outside this session) and share its full palette.
#[tauri::command]
pub fn read_char_palette(arc_path: String, char_id: u32) -> Result<Vec<u32>, String> {
    let arc_path = resolve_arc(&arc_path);
    // Fast path: read straight out of the cached inflated payload — no 112 MB clone per character.
    let (len, mtime) = file_stamp(&arc_path);
    if let Ok(g) = MVSC2_CACHE.lock() {
        if let Some((p, l, m, bytes)) = g.as_ref() {
            if p == &arc_path && *l == len && *m == mtime { return read_pal_from(bytes, char_id); }
        }
    }
    // Cold: inflate + cache once (the next char reads hit the fast path above), then decode.
    let mvsc2 = load_mvsc2(&arc_path)?;
    read_pal_from(&mvsc2, char_id)
}

// ── Full character DAT extraction — feeds the Studio's *all-animation* decode (not just idle) ──
// Inflate game_50.arc's `mvsc2` payload (cached) and return the raw DAT bytes for AFS entry 209+cid.
// The DAT carries every sprite bank, part assembly and animation group for the character; the frontend
// (web/studio/rom-bake.mjs decoders) turns these bytes into the full animation set + parts-based editing.
fn load_mvsc2(arc_path: &str) -> Result<Vec<u8>, String> {
    let (len, mtime) = file_stamp(arc_path);
    if let Ok(g) = MVSC2_CACHE.lock() {
        if let Some((p, l, m, bytes)) = g.as_ref() {
            if p == arc_path && *l == len && *m == mtime { return Ok(bytes.clone()); }
        }
    }
    let orig = std::fs::read(arc_path).map_err(|e| format!("read arc: {e}"))?;
    if orig.len() < 88 || &orig[0..4] != b"ARC\0" { return Err("not a Capcom ARC (game_50.arc)".into()); }
    if u16le(&orig, 4) != 7 || u16le(&orig, 6) != 1 { return Err("unexpected ARC version/count".into()); }
    let toc = 8usize;
    let csize = u32le(&orig, toc + 68) as usize;
    let doff = u32le(&orig, toc + 76) as usize;
    if doff + csize > orig.len() { return Err("ARC payload out of range".into()); }
    let mut mvsc2 = Vec::new();
    flate2::read::ZlibDecoder::new(&orig[doff..doff + csize]).read_to_end(&mut mvsc2).map_err(|e| format!("inflate: {e}"))?;
    if let Ok(mut g) = MVSC2_CACHE.lock() { *g = Some((arc_path.to_string(), len, mtime, mvsc2.clone())); }
    Ok(mvsc2)
}

#[tauri::command]
pub fn extract_char_dat(arc_path: String, char_id: u32) -> Result<Response, String> {
    let arc_path = resolve_arc(&arc_path);
    let mvsc2 = load_mvsc2(&arc_path)?;
    let afs = 0x40usize;
    if mvsc2.len() < afs + 8 { return Err("mvsc2 too small".into()); }
    let acount = u32le(&mvsc2, afs + 4) as usize;
    let idx = 209 + char_id as usize;
    if idx >= acount { return Err(format!("char {char_id} (AFS {idx}) out of {acount} entries")); }
    let ent = afs + 8 + idx * 8;
    if ent + 8 > mvsc2.len() { return Err("AFS TOC entry out of range".into()); }
    let eoff = u32le(&mvsc2, ent) as usize;
    let esz = u32le(&mvsc2, ent + 4) as usize;
    let dat = afs + eoff;
    if dat + esz > mvsc2.len() || esz == 0 { return Err(format!("DAT slice out of range (off {eoff} sz {esz})")); }
    Ok(Response::new(mvsc2[dat..dat + esz].to_vec()))
}

/// Resolve whatever the user picked — a `.zip`, a `.gdi/.bin/.iso`, or a folder — to the data-track path.
#[tauri::command]
pub fn rom_prepare(path: String) -> Result<String, String> {
    let p = Path::new(&path);
    let ext = p.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
    if ext == "zip" {
        let out = zip_extract_dir(p);
        if find_data_track(&out).is_none() { extract_zip(p, &out)?; }
        return find_data_track(&out)
            .ok_or_else(|| "That zip didn't contain a MvC2 GDI data track (track03.bin).".to_string());
    }
    if p.is_file() && is_data_track(p) { return Ok(path); }
    let dir = if p.is_dir() { p.to_path_buf() } else { p.parent().map(|x| x.to_path_buf()).unwrap_or_default() };
    find_data_track(&dir)
        .ok_or_else(|| "Couldn't find a MvC2 GDI data track (track03.bin) in that file or folder.".to_string())
}
