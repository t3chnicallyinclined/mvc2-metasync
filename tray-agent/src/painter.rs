// Skin painter — ported VERBATIM from src-tauri/src/sync.rs (frozen v0.2.5) + web/index.html's paint loop. T3.
//
// This is the write half of the app: given the reader's exact per-fighter render-palette pointers
// (`paint_slots` = cl+0x4c) and the located fighter array (`ram_base`), it writes skin palettes straight into
// the game's render palette OUT-OF-PROCESS via RPM (WriteProcessMemory), write-last-wins, every frame. There
// is NO injected D3D hook here and NO `C:\g\skins.dat` hook — RPM paint only.
//
// The RE is byte-identical to the app. Copied WITHOUT change:
//   • the palette-write path — `paint_live` (sync.rs:4138): resolve each on-screen slot's LIVE DatPal off the
//     array at write-time, skin ONLY the 6 base button-colour groups `[0, 0x600)` (PAL_BASE_REGION), regenerate
//     the DERIVED effect rows (skin + learned stock delta) and PRESERVE the INDEPENDENT effect rows.
//   • the effect-safe recipe learner — `classify_stock` / `get_or_learn_recipe` (sync.rs:3995 / 4034), the
//     per-character copy/lum/tint recovered straight from the game's own stock block.
//   • the ARRAY-FREE signature paint — `paint_signatures` (sync.rs:4325): read skins.dat's sig:replacement
//     lines and WriteProcessMemory every matching palette row in the fixed working-buffer window. No array
//     find, no side, no injection — the base layer that paints the instant fighters render.
//   • the row codecs — skin_row / skin_row_delta / is_real_row / decode_row4 / row_nib / sig_nib / row_from_hex.
//   • the skin resolution — `build_paint_targets` (web/index.html buildPaintTargets): mirror-safe, side-aware
//     (your skins → your fighter; a same-char mirror splits per-side once the side locks; opponent skins layer
//     onto their side once known). The mirror/side logic is byte-identical.
//   • the local-store → skins.dat writer — sigs_lines / apply_multi (lib.rs:250 / 280).
//
// ONLY the TRIGGER changes (the decouple). The app drove painting from the webview: the user picked a skin and
// a JS `setInterval` (paintTick 100ms / baseTick 1200ms) called the `#[tauri::command]` paint functions. There
// is no webview here, so `start_painter()` runs the SAME two cadences on a sibling thread, reads the reader's
// `PaintView` (paint_slots / ram_base / side / state) each tick, and auto-applies the user's LOCAL skins
// (local-first) — see the trigger section at the bottom. The "change a skin from your phone" push path is T5;
// its merge point is marked `TODO(T5)`.
//
// SKIPPED (out of T3 scope, see the task): the injected D3D hook (do_inject_hook / stage_hook_dll — RPM only),
// the arcade host-driver (T4), and the legacy `paint_palettes` (sync.rs:4080) — a pointer-lagged path the
// frontend RETIRED in favour of paint_live (buildPaintTargets → paint_live), so it is never on the active loop.

use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::mem;
// Shared memory primitives + the MvC2 offset table, reused from the reader's verbatim RE (exposed pub(crate)
// there — visibility only, no logic change) so the painter builds on the SAME anchor/offsets, never a copy.
use crate::reader::{
    self, anchor_array, array_valid, is_wb, pal_sig, read_at, rpm_u32, rpm_u8, MAX_CID, OFF_CHARID, OFF_DATPAL,
    PAL_BASE_REGION, STRIDE, WB_HI, WB_LO,
};

// Painter's own trace (copy of reader::trace) → the same suite_trace.log. Kept local so the painter is
// self-contained; concurrent appends from the reader + painter threads are independent append handles.
fn trace(msg: &str) {
    use std::io::Write;
    let path = crate::runtime_dir().join("suite_trace.log");
    if std::fs::metadata(&path).map(|m| m.len() > 1_000_000).unwrap_or(false) {
        let _ = std::fs::write(&path, b"");
    }
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs_f64())
            .unwrap_or(0.0);
        let _ = writeln!(f, "{:.3} {}", t, msg);
    }
}

// ════════════════════════════════════════════════════════════════════════════════════════════════════════
// ▼▼▼ VERBATIM PORT FROM sync.rs — do NOT edit the RE (palette offsets / [0,0x600) window / write cadence). ▼▼▼
// ════════════════════════════════════════════════════════════════════════════════════════════════════════

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
// ── PHASE 2: effect-safe skin regeneration (learn from the game's OWN stock palettes) ────────────────
// A character's DatPal block = 6 base costume groups [0,0x600) + a shared Status-Effects block + Extras
// (grenade / lightning / hyper-armor / body-tint frames). Some Extras are DERIVED from the base (a copy or a
// mild luminance/tint of it); others are INDEPENDENT authored palettes. We recolor the DERIVED ones to follow
// the skin (so the body stays skinned through attacks) but PRESERVE the INDEPENDENT ones. Learned per character
// straight from the game data — no per-character tables. See sync.rs for the full rationale.
struct PalRecipe { deltas: Vec<(usize, [[i8; 3]; 16])> }   // (effect-row offset, per-colour 4-bit RGB delta)
fn pal_recipes() -> &'static Mutex<HashMap<u8, std::sync::Arc<PalRecipe>>> {
    static R: OnceLock<Mutex<HashMap<u8, std::sync::Arc<PalRecipe>>>> = OnceLock::new();
    R.get_or_init(|| Mutex::new(HashMap::new()))
}
/// Reset learned recipes (called on new match/select — in case a char's block was captured mid-paint, the
/// next stock sighting re-learns cleanly). Mirrors the frontend clearing on game-detect / new select.
pub(crate) fn clear_pal_recipes() { pal_recipes().lock().unwrap().clear(); }
// A 32-byte ARGB4444 row → 16 × [r,g,b] in the native 4-bit channel space (0..15).
fn decode_row4(b: &[u8]) -> [[u8; 3]; 16] {
    let mut out = [[0u8; 3]; 16];
    for i in 0..16 {
        let v = (b[i * 2] as u16) | ((b[i * 2 + 1] as u16) << 8);
        out[i] = [((v >> 8) & 0xf) as u8, ((v >> 4) & 0xf) as u8, (v & 0xf) as u8];
    }
    out
}
const PAL_DERIVE_THRESHOLD: i32 = 150;  // max Σ|Δ| (over 15 colours × 3 chans, each 0..15; max 675) to call a row DERIVED
const PAL_EFFECT_DISTINCT:  i32 = 20;   // a row Σ|Δ| above this from every base = a genuinely different palette
/// Classify a STOCK block into a recipe, or None if the block doesn't look stock.
fn classify_stock(block: &[u8]) -> Option<PalRecipe> {
    let mut bases: Vec<[[u8; 3]; 16]> = Vec::new();
    let mut off = 0usize;
    while off < PAL_BASE_REGION && off + 32 <= block.len() {
        let r = &block[off..off + 32];
        if is_real_row(r) { bases.push(decode_row4(r)); }
        off += 0x20;
    }
    if bases.len() < 3 { return None; }   // a stock block has the 6 costume palettes; too few = not stock
    if bases.iter().all(|b| b == &bases[0]) { return None; }   // uniform base = already painted, not a stock ref
    let mut deltas = Vec::new();
    let mut n_distinct = 0i32;
    off = PAL_BASE_REGION;
    while off + 32 <= block.len() {
        let r = &block[off..off + 32];
        if is_real_row(r) {
            let e = decode_row4(r);
            let mut best = i32::MAX;
            let mut best_delta = [[0i8; 3]; 16];
            for b in &bases {
                let mut sum = 0i32;
                let mut d = [[0i8; 3]; 16];
                for i in 1..16 {                     // colour 0 is transparent — skip
                    for c in 0..3 {
                        let diff = e[i][c] as i32 - b[i][c] as i32;
                        sum += diff.abs();
                        d[i][c] = diff as i8;
                    }
                }
                if sum < best { best = sum; best_delta = d; }
            }
            if best > PAL_EFFECT_DISTINCT { n_distinct += 1; }        // genuinely differs from every base
            if best <= PAL_DERIVE_THRESHOLD { deltas.push((off, best_delta)); }  // close to a base → DERIVED
        }
        off += 0x20;
    }
    if n_distinct < 3 { return None; }   // no real effect structure → uniform/painted, not a stock reference
    Some(PalRecipe { deltas })
}
fn get_or_learn_recipe(cid: u8, block: &[u8]) -> Option<std::sync::Arc<PalRecipe>> {
    if let Some(r) = pal_recipes().lock().unwrap().get(&cid) { return Some(r.clone()); }
    let r = std::sync::Arc::new(classify_stock(block)?);   // None (don't cache) unless the block is genuinely stock
    pal_recipes().lock().unwrap().insert(cid, r.clone());
    Some(r)
}
// The skin row with a per-colour delta applied (for regenerating a DERIVED effect row from the skin).
fn skin_row_delta(colors: &[u32], delta: &[[i8; 3]; 16]) -> [u8; 32] {
    let mut row = [0u8; 32];
    let cl = |x: i32| x.clamp(0, 15) as u16;
    for i in 1..16 {
        let c = colors.get(i).copied().unwrap_or(0);
        let (r, g, b) = (((c >> 16) & 0xff) as i32 >> 4, ((c >> 8) & 0xff) as i32 >> 4, (c & 0xff) as i32 >> 4);
        let (dr, dg, db) = (delta[i][0] as i32, delta[i][1] as i32, delta[i][2] as i32);
        let v: u16 = 0xf000 | (cl(r + dr) << 8) | (cl(g + dg) << 4) | cl(b + db);
        row[i * 2] = (v & 0xff) as u8; row[i * 2 + 1] = (v >> 8) as u8;
    }
    row
}

/// One on-screen fighter that should be skinned, already resolved to the correct side. (sync.rs LiveTarget,
/// minus serde — nothing deserializes it here; the reader-driven resolver constructs it directly.)
struct LiveTarget { cid: u8, player: u8, colors: Vec<u32> }

/// REAL-TIME paint (gs-72), VERBATIM write path from sync.rs:4138. The ONLY change is the trigger glue: the
/// `#[tauri::command]` opened the process + read `snapshot().ram_base` itself; here the caller opens the proc
/// ONCE per tick and hands in `h` + the reader's already-located `base` (see paint_live_apply). Everything
/// below — the per-slot char/side match, the LIVE DatPal re-resolve, the `[0,0x600)` base write, the recipe
/// regen of DERIVED rows, the write-last-wins skip-if-equal — is byte-identical to the app. Returns rows written.
fn paint_live(h: &mem::Proc, base: usize, targets: &[LiveTarget]) -> usize {
    if targets.is_empty() { return 0; }
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
        // PHASE 2: read the FULL block; skin the base costume palettes [0, 0x600); REGENERATE the DERIVED effect
        // rows (skin + their stock delta, so the body stays skinned through attacks); LEAVE the INDEPENDENT
        // effect rows (grenade / lightning / status tints) untouched. Falls back to base-only until a stock block
        // has been seen (classify_stock returns None → recipe None).
        if let Some(block) = unsafe { read_at(h, dp, 0x2000) } {
            let recipe = get_or_learn_recipe(cid, &block);
            // 1) BASE region → the skin.
            let mut off = 0usize;
            while off < PAL_BASE_REGION && off + 32 <= block.len() {
                let cur = &block[off..off + 32];
                if is_real_row(cur) && cur != &row[..] {
                    if h.write(dp + off, &row) { rows += 1; }
                }
                off += 0x20;
            }
            // 2) DERIVED effect rows → skin + stock delta. 3) INDEPENDENT rows → not in the recipe → preserved.
            if let Some(rec) = recipe {
                for (eoff, delta) in &rec.deltas {
                    if *eoff + 32 > block.len() { continue; }
                    let drow = skin_row_delta(&tgt.colors, delta);
                    if &block[*eoff..*eoff + 32] != &drow[..] {
                        if h.write(dp + *eoff, &drow) { rows += 1; }
                    }
                }
            }
        }
    }
    rows
}

/// Base-selection glue lifted VERBATIM out of the `#[tauri::command]` head of sync.rs paint_live: prefer the
/// reader's LOCATED array (it tracks the real per-match location), validate it, else fall back to the anchor.
/// In-process the reader publishes `ram_base` on the same cycle, so this is authoritative (no webview lag).
fn paint_live_apply(h: &mem::Proc, ram_base: usize, targets: &[LiveTarget]) -> usize {
    if targets.is_empty() { return 0; }
    let base = if ram_base != 0 && unsafe { array_valid(h, ram_base) } {
        ram_base
    } else {
        match unsafe { anchor_array(h) } { Some(a) => a, None => return 0 }
    };
    paint_live(h, base, targets)
}

// ── APP-SIDE SIGNATURE PAINT (the "hook", without injection) — VERBATIM from sync.rs:4292+ ─────────────
// The DC palettes flycast uploads live in the FIXED working-buffer window (WB_LO..WB_HI, never ASLR'd). Scan
// that window for palette rows matching a saved skin's signature and WriteProcessMemory the skin straight in.
// Detection-INDEPENDENT: no fighter-array find (works even when ram_base=0), no injection. Exact nibble match.
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
fn hexhi(c: u8) -> Option<u8> { let d = (c as char).to_digit(16)? as u8; Some(d) }   // value of ONE hex digit
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

// The distinct on-screen palette sigs the last paint_signatures scan saw (the array-free capture source in the
// app). Kept for verbatim fidelity; the tray has no capture_live consumer, so it is written-not-read here.
fn last_wb_pals() -> &'static Mutex<Vec<String>> {
    static P: OnceLock<Mutex<Vec<String>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(Vec::new()))
}

/// Read skins.dat (the sig:replacement lines) and paint every matching palette row found in the fixed
/// working-buffer window. No fighter-array find, no injection. VERBATIM from sync.rs:4325 — the only trigger
/// change is that the caller supplies the already-opened proc `h` (was find_game_pid + open_rw inline).
/// Returns rows painted.
fn paint_signatures(h: &mem::Proc) -> usize {
    let dat = std::fs::read_to_string(crate::runtime_dir().join("skins.dat")).unwrap_or_default();
    // target: (nibble-key of the sig to match, 32-byte ARGB4444 skin row to write)
    let mut targets: Vec<([u8; 45], [u8; 32])> = Vec::new();
    for line in dat.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') { continue; }
        if let Some((sig, rep)) = line.split_once(':') {
            if let (Some(k), Some(row)) = (sig_nib(sig.trim()), row_from_hex(rep.trim())) { targets.push((k, row)); }
        }
    }
    if targets.is_empty() { return 0; }
    let mut painted = 0usize;
    let mut pals: Vec<String> = Vec::new();                        // every distinct on-screen palette this scan sees
    let mut seen: HashSet<String> = HashSet::new();
    let (lo, hi) = (WB_LO as usize, WB_HI as usize);
    for r in h.regions() {
        let rbase = r.base; let rsize = r.size;
        if r.readable && rbase < hi && rbase + rsize > lo {
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
                            if pals.len() < 128 { let sig = pal_sig(&r); if seen.insert(sig.clone()) { pals.push(sig); } }
                            let key = row_nib(&r);
                            for (tk, trow) in &targets {
                                if &key == tk {
                                    if &r != trow {                 // skip if the skin is already applied
                                        if h.write(cbase + i, trow) { painted += 1; }
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
    }
    if !pals.is_empty() { *last_wb_pals().lock().unwrap() = pals; }
    painted
}

// ── local-store → skins.dat writer (VERBATIM from lib.rs sigs_lines:250 / apply_multi:280) ────────────
fn lum(r: u8, g: u8, b: u8) -> f32 { 0.299 * r as f32 + 0.587 * g as f32 + 0.114 * b as f32 }
// parse "rrggbbaa..." (16 colours) → Vec<(r,g,b,a)>
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

// ════════════════════════════════════════════════════════════════════════════════════════════════════════
// ▲▲▲ END VERBATIM PORT. Below is the T3 tray-decouple glue (replaces the webview's paint trigger). ▲▲▲
// ════════════════════════════════════════════════════════════════════════════════════════════════════════

// ── LOCAL SKIN STORE ──────────────────────────────────────────────────────────────────────────────────
// The app kept per-character skins in browser localStorage (`mvcskin_<cid>` → activeSkins[cid]) and only the
// DERIVED skins.dat (sig:replacement) lived as a Rust-side FILE. The tray has no webview/localStorage, so the
// per-character store is a FILE under runtime_dir(): `skins.json`, the same shape as activeSkins / the cloud
// vault. One entry per character:
//   { "<cid>": { "colors":[16 ints, 0xRRGGBB], "sigs":["<128hex>"…]?, "author":"…"?, "name":"…"? } }
// `colors` is the READY-TO-PAINT 16-colour body palette (what the app computed via pal16For before calling
// paint_live). It is stored ready because pal16For needs the per-character stock bank0 (idleData) — a large
// ROM-derived asset that lives ONLY in the web frontend, not the agent. So the ONE faithful adaptation vs the
// app is WHERE the pal48→pal16 conversion happens: the app did it at paint-time (it has idleData); the tray
// consumes the already-converted `colors` from whoever wrote the store (the web app / Studio / T5's phone push,
// all of which have idleData). The mirror/side RESOLUTION below is byte-identical either way.
#[derive(serde::Deserialize, Default, Clone)]
struct LocalSkin {
    #[serde(default)] colors: Vec<u32>,   // 16 × 0xRRGGBB, ready for skin_row / paint_live
    #[serde(default)] sigs: Vec<String>,  // optional stock signatures → lets this skin also feed the base layer
    #[serde(default)] author: String,
    #[serde(default)] name: String,
}
fn skins_json_path() -> std::path::PathBuf { crate::runtime_dir().join("skins.json") }

/// Load the user's local per-character skins from runtime_dir()/skins.json. Empty (safe no-op) if the file is
/// absent/blank/malformed — the painter simply paints nothing until skins exist.
fn load_local_skins() -> HashMap<u8, LocalSkin> {
    let raw = std::fs::read_to_string(skins_json_path()).unwrap_or_default();
    if raw.trim().is_empty() { return HashMap::new(); }
    let map: HashMap<String, LocalSkin> = serde_json::from_str(&raw).unwrap_or_default();
    map.into_iter()
        .filter_map(|(k, v)| k.parse::<u8>().ok().map(|cid| (cid, v)))
        .filter(|(_, v)| v.colors.len() >= 16)
        .collect()
}

/// Cheap change-detector for skins.json (len:mtime) so we only reload + regen skins.dat when it actually changes.
fn skins_fingerprint() -> String {
    match std::fs::metadata(skins_json_path()) {
        Ok(m) => {
            let mt = m.modified().ok()
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_millis()).unwrap_or(0);
            format!("{}:{}", m.len(), mt)
        }
        Err(_) => String::new(),
    }
}

/// Regenerate skins.dat from the local per-character store — the base-layer (paint_signatures) source. Mirrors
/// the app's writeAll(mine) → apply_multi: every skin that carries BOTH stock sigs and a palette contributes its
/// sig:replacement rows. Colours-only skins (no sigs) are paint_live-only (per-side) and add nothing here. The
/// opponent layer (writeAll's `theirs`, from /peers) merges in the same way once a peer store is populated (T5).
fn regen_skins_dat(skins: &HashMap<u8, LocalSkin>) {
    let mut out = String::from("# live skins\n");
    for m in skins.values() {
        if m.sigs.is_empty() || m.colors.len() < 16 { continue; }
        out.push_str(&sigs_lines(&m.sigs, &m.colors));
    }
    let _ = std::fs::write(crate::runtime_dir().join("skins.dat"), out);
}

// ── OPPONENT SKINS (resolution structure ported; source pending sync/T5) ──────────────────────────────
// oppSkinFor(cid) in the app returned the opponent's effective skin: their synced /peers skin (THEIRS wins when
// they run the app), else your manual pick / per-match random. Those three sources are all webview/network
// state. For T3 (local-first, no webview) the peer store below is populated by nothing yet, so opp_skin_for
// returns None → opponent fighters stay STOCK (correct + safe). The resolution BRANCH that consumes it is
// ported verbatim in build_paint_targets, so wiring the source later (a /peers fetch keyed on the reader's
// detected opponent, or a T5 phone push) needs no change to the mirror/side logic.
// NOTE the tray-specific constraint: /peers returns pal48 (needs the idleData bank0 to make paint_live `colors`),
// which the agent lacks — so synced OPPONENT skins are expected to ride the base layer (skins.dat via sigs_lines,
// which needs no bank0), while paint_live per-side owns YOUR skins (ready `colors`). See the module header.
fn peer_skins() -> &'static Mutex<HashMap<u8, Vec<u32>>> {   // cid → ready 16-colour palette (empty in T3)
    static P: OnceLock<Mutex<HashMap<u8, Vec<u32>>>> = OnceLock::new();
    P.get_or_init(|| Mutex::new(HashMap::new()))
}
// opponentHasApp() in the app: true when the opponent appears in the /peers fetch → THEY control their look.
// Kept as the ported resolution vocabulary; unused in T3 (no peer source yet — see the note above). Do NOT
// call it while holding the peer_skins lock (std Mutex is non-reentrant).
fn opponent_has_app() -> bool { !peer_skins().lock().unwrap().is_empty() }
fn opp_skin_for(cid: u8) -> Option<Vec<u32>> {
    // opponentHasApp: THEIRS wins (synced) where skinned, else STOCK — never your random/manual. The no-app case
    // (your manual > per-match random) has no local-first source in T3, so both branches collapse to the peer
    // lookup: a synced opponent skin if present, else None (STOCK).
    peer_skins().lock().unwrap().get(&cid).filter(|c| c.len() >= 16).cloned()
}

// ── RESOLUTION — VERBATIM from web/index.html buildPaintTargets (mirror-safe, side-aware) ──────────────
// For each on-screen slot (the reader's paint_slots = player,cid,datpal): your skin paints on any fighter of
// that char; a MIRROR char (same cid on BOTH sides) is WITHHELD until the side locks, then painted onto YOUR
// copy only; an opponent-only skin layers onto their side once the side is known. Byte-identical logic; the
// only substitution is `mine.colors` (ready) where the app used `pal16For(cid, mine.palette)`.
fn build_paint_targets(view: &reader::PaintView, mine: &HashMap<u8, LocalSkin>) -> Vec<LiveTarget> {
    let slots = &view.paint_slots;                     // (player, cid, datpal) — reader's exact render-palette pointers
    if slots.is_empty() { return Vec::new(); }
    let me_num: u8 = if view.side_confirmed { if view.local_side == 2 { 2 } else { 1 } } else { 0 };  // 0 = side not resolved yet
    // MIRROR-SAFE: a character on BOTH sides can't be told apart by char-id.
    let mut p1c: HashSet<u8> = HashSet::new();
    let mut p2c: HashSet<u8> = HashSet::new();
    for &(player, cid, _dp) in slots {
        if player == 1 { p1c.insert(cid); } else if player == 2 { p2c.insert(cid); }
    }
    let mirror: HashSet<u8> = p1c.intersection(&p2c).copied().collect();
    let mut out = Vec::new();
    for &(player, cid, dp) in slots {
        if dp == 0 { continue; }
        let mut colors: Option<Vec<u32>> = None;
        // YOUR skin: paints on any fighter of that char; for a MIRROR char, WITHHELD until the side locks, then
        // YOUR copy only (never both). Painting a mirror before the side resolves is what flashed your skin onto
        // the opponent at match start — withholding for that brief deterministic window shows only the right side.
        if let Some(m) = mine.get(&cid) {
            if m.colors.len() >= 16 && (!mirror.contains(&cid) || (me_num != 0 && player == me_num)) {
                colors = Some(m.colors.clone());
            }
        }
        // opponent-only skin, applied to THEIR side once known.
        if colors.is_none() && me_num != 0 && player != me_num {
            if let Some(os) = opp_skin_for(cid) { colors = Some(os); }
        }
        let colors = match colors { Some(c) if c.len() >= 16 => c, _ => continue };
        out.push(LiveTarget { cid, player, colors });
    }
    out
}

// ── TRIGGER (reader-driven, local-first) — replaces the webview paintTick/baseTick setInterval loop ────
// The app fired paintTick (100 ms) + baseTick (1200 ms) from JS whenever the user had skins + a match was up.
// The tray has no webview, so this sibling thread runs the SAME two cadences off the reader's PaintView:
//   • fast (every tick ~100 ms): per-side paint_live of YOUR local skins onto YOUR fighters — the primary
//     local-first apply. Needs paint_slots live (they are, at match start, via the reader's pointer-follow).
//   • slow (~1200 ms): the array-free base layer (paint_signatures over skins.dat) — the robust fallback that
//     paints even before the array/side locks, or for sig-only skins that carry no ready `colors`. Gated to run
//     ONLY when per-side produced nothing this tick (mirrors gs-73: don't run the heavy WB scan while per-side
//     already covers the fighters — that scan was the app's freeze).
// Painting is confined to select/match (never menus / app-start) and requires a fighter to actually be present.
struct PainterState {
    skins: HashMap<u8, LocalSkin>,   // effective per-character store = local skins.json ∪ web loadout (web wins)
    skin_fp: String,                 // last skins.json fingerprint
    last_loadout_ver: u64,           // last web-loadout version merged (bumps when the web picker changes it)
    last_state: String,              // reader state, to detect new-match/select transitions (cache reset)
    last_base: Instant,              // throttle for the heavy base-layer scan
}

// ── TRAY control flag (drives the "Apply my skins" toggle; see tray.rs) ────────────────────────────────
/// "Apply my skins" (tray, PERSISTED to runtime_dir()/prefs.json, default ON). While false the painter writes
/// NOTHING (painter_tick returns before any RPM). main.rs restores the persisted value into this flag BEFORE
/// start_painter(); the tray flips it (and re-persists) live. Detection/reporting are unaffected.
pub(crate) static SKINS_ENABLED: AtomicBool = AtomicBool::new(true);

// ── Phase 3: WEB-DRIVEN LOADOUT (server is the picker) ─────────────────────────────────────────────────
// A background thread polls GET /skinsync/loadout (our own, auth-bound) and mirrors it into this in-memory
// map — the painter merges it OVER the local skins.json store (a char set on the web wins; chars we didn't
// set fall back to local). Purely in-memory on the hot path: painter_tick only rebuilds st.skins when the
// version bumps (a real change), never reads a file per tick. sigs is empty (palette-only ⟹ paint_live path).
fn server_loadout() -> &'static Mutex<HashMap<u8, LocalSkin>> {
    static S: OnceLock<Mutex<HashMap<u8, LocalSkin>>> = OnceLock::new();
    S.get_or_init(|| Mutex::new(HashMap::new()))
}
static LOADOUT_VER: AtomicU64 = AtomicU64::new(0);
fn loadout_version() -> u64 { LOADOUT_VER.load(Ordering::Relaxed) }

/// True if the freshly-fetched loadout differs from what we hold (by cid set + per-cid colours).
fn loadout_differs(cur: &HashMap<u8, LocalSkin>, next: &HashMap<u8, LocalSkin>) -> bool {
    if cur.len() != next.len() { return true; }
    next.iter().any(|(cid, ls)| cur.get(cid).map(|o| o.colors != ls.colors).unwrap_or(true))
}

/// Poll our web loadout every few seconds and publish changes (bumps LOADOUT_VER so the painter re-merges).
/// Runs regardless of a game being open — a change made on the web while idle is ready by the next match.
pub(crate) fn start_loadout_sync() {
    let _ = std::thread::Builder::new().name("loadout-sync".into()).spawn(|| loop {
        if let Some(pairs) = crate::reader::fetch_loadout() {
            let next: HashMap<u8, LocalSkin> = pairs
                .into_iter()
                .map(|(cid, colors)| (cid, LocalSkin { colors, sigs: Vec::new(), author: "web".into(), name: "loadout".into() }))
                .collect();
            let mut cur = server_loadout().lock().unwrap();
            if loadout_differs(&cur, &next) {
                *cur = next;
                LOADOUT_VER.fetch_add(1, Ordering::Relaxed);
            }
        }
        std::thread::sleep(Duration::from_secs(6));
    });
}

fn painter_tick(st: &mut PainterState) {
    // "Apply my skins" off → paint nothing this tick (no reload/regen, no RPM). When re-enabled the next tick
    // resumes normally (the skins.json fingerprint check re-picks up any change made while disabled).
    if !SKINS_ENABLED.load(Ordering::Relaxed) {
        return;
    }

    // 1) rebuild the effective store when EITHER the local skins.json OR the web loadout changes → the web
    //    loadout (poll thread, in-memory) is merged OVER the local store so a char picked on the web wins.
    //    Then regen skins.dat + drop learned recipes (a changed skin invalidates them). No per-tick file read
    //    when nothing changed — just a cheap fingerprint stat + an atomic load.
    let fp = skins_fingerprint();
    let lver = loadout_version();
    if fp != st.skin_fp || lver != st.last_loadout_ver {
        st.skin_fp = fp;
        st.last_loadout_ver = lver;
        let mut merged = load_local_skins();
        for (cid, ls) in server_loadout().lock().unwrap().iter() {
            merged.insert(*cid, ls.clone()); // web loadout wins per-cid
        }
        st.skins = merged;
        regen_skins_dat(&st.skins);
        clear_pal_recipes();
        trace(&format!("[painter] skins rebuilt ({} char(s); loadout v{})", st.skins.len(), lver));
    }

    let view = reader::paint_view();

    // 2) new match/select → drop learned recipes (DatPals relocate per match; a block captured mid-paint would
    //    teach a bad recipe). Mirrors the frontend's reset_hook_regions on game-detect / new select.
    if view.state != st.last_state {
        if view.state == "select" || view.state == "menu" { clear_pal_recipes(); }
        st.last_state = view.state.clone();
    }

    // 3) paint ONLY in select/match, and only when a fighter is actually present (kills idle menu scans).
    if view.state != "match" && view.state != "select" { return; }
    if view.paint_slots.is_empty() && view.ram_base == 0 { return; }

    // 4) open the game process read/WRITE once for this tick.
    let pid = match crate::mem::find_game_pid() { Some(p) => p, None => return };
    let proc = match crate::mem::Proc::open_rw(pid) { Some(p) => p, None => return };
    let h = &proc;

    // 5) PER-SIDE (fast): auto-apply YOUR local skins to YOUR fighters — the local-first core.
    let targets = build_paint_targets(&view, &st.skins);
    let per_side_active = !targets.is_empty();
    if per_side_active {
        // rows==0 = "already applied" (write-last-wins, skip-if-equal) — NOT a failure. No base-layer fallback
        // here when per-side is active (gs-73: the redundant WB scan was the freeze).
        let _rows = paint_live_apply(h, view.ram_base, &targets);
    }

    // 6) BASE LAYER (slow, throttled): the array-free signature paint — the fallback when per-side covered
    //    nothing this tick (no ready-colour skin matched an on-screen fighter, or the array hasn't locked yet).
    if !per_side_active && st.last_base.elapsed() >= Duration::from_millis(1200) {
        st.last_base = Instant::now();
        let _painted = paint_signatures(h);
    }
}

/// Start the reader-driven skin painter. Spawns one sibling thread that ticks ~10×/s, reads the reader's
/// PaintView + the local skin store, and applies skins via RPM (per-side paint_live + the array-free base
/// layer). Contains panics per-tick (one bad frame logs + continues, like the reader). Returns immediately.
pub(crate) fn start_painter() {
    std::thread::Builder::new()
        .name("painter".into())
        .spawn(|| {
            let mut st = PainterState {
                skins: HashMap::new(),
                skin_fp: String::new(),
                last_loadout_ver: u64::MAX, // force a first merge even when the web loadout is empty (v0)
                last_state: String::new(),
                last_base: Instant::now() - Duration::from_secs(10),
            };
            trace("[painter] started (reader-driven local-first RPM paint)");
            loop {
                let cycle = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| painter_tick(&mut st)));
                if cycle.is_err() {
                    trace("[painter] cycle panicked — recovering, continuing");
                    std::thread::sleep(Duration::from_millis(500));   // avoid a hot-spin on repeated panics
                }
                std::thread::sleep(Duration::from_millis(100));       // fast cadence → win the round-intro palette reload
            }
        })
        .ok();
}
