"use strict";
// extract.js -- WinDbg JsProvider script that replays a TTD trace headless and emits, per game frame:
//   (a) every call into the configured function set (ordered, with positions)            -> calls_f<k>.jsonl
//   (b) every read/write inside blk[lo..hi) as (offset,size,rw,ip,count,first position)  -> blk_f<k>.jsonl
//   (c) reads of the DC-RAM host image, per (ip, 4 KB page) [+exact addresses if detail] -> dcram_f<k>.jsonl
//   plus the frame boundary list (frames.json), a memory dump at the first window boundary (dump_f<k>_*.bin),
//   and probe.json (the property names the TTD objects actually expose, for diagnosing API drift).
//
// Driven by extract.py:
//   cdbX64.exe -z <trace.run> -c ".scriptload <this>; dx @$scriptContents.run(\"<cfg.json>\"); q"
// TTD data-model API used (documented under "Time Travel Debugging - JavaScript Automation"):
//   host.currentSession.TTD.Memory(lo, hi, "rw"|"r"|"w")   -> {TimeStart, TimeEnd, AccessType, IP, Address, Size, Value, ThreadId}
//   host.currentSession.TTD.Calls(addr | "mod!sym", ...)    -> {TimeStart, TimeEnd, Function, FunctionAddress, ReturnAddress, ReturnValue, ThreadId, Parameters}
//   <position>.SeekTo(), host.memory.readMemoryValues(addr, count, size)
//   host.namespace.Debugger.Utility.FileSystem.{CreateFile, OpenFile, CreateTextWriter, CreateTextReader}
// Frame boundary (cfg.boundary): "clock" = writes to cfg.clock_addr (blk+0x3CC8, the engine frame clock,
// docs/TAPE-V3-SPEC.md:43) or "calls:<hex addr>" = each call to that address (e.g. FUN_140620f10, once per frame).
// Frame k = [boundary_k, boundary_k+1).  NOTE the clock write sits INSIDE the tick, so a clock-bounded frame holds
// the tail of tick k, the render of frame k and the head of tick k+1; use calls:<tick> once the tick's caller is known.

const FS = () => host.namespace.Debugger.Utility.FileSystem;
let LOG = null;
function log(s) {
    const line = "[extract.js] " + s;
    try { host.diagnostics.debugLog(line + "\n"); } catch (e) {}
    if (LOG) { try { LOG.WriteLine(line); } catch (e) {} }
}
function num(v) {
    if (v === null || v === undefined) return 0;
    if (typeof v === "number") return v;
    if (typeof v === "object" && typeof v.asNumber === "function") return v.asNumber();
    return Number(v);
}
function hex(v) { return "0x" + num(v).toString(16); }
function pos(p) { return [num(p.Sequence), num(p.Steps)]; }
function posStr(p) { return num(p.Sequence).toString(16) + ":" + num(p.Steps).toString(16); }
function cmp(a, b) { return a[0] !== b[0] ? (a[0] < b[0] ? -1 : 1) : (a[1] === b[1] ? 0 : (a[1] < b[1] ? -1 : 1)); }
function inWin(p, w) { return cmp(p, w.lo) >= 0 && cmp(p, w.hi) < 0; }

function readText(path) {
    const f = FS().OpenFile(path);
    const r = FS().CreateTextReader(f, "Utf8");
    let s = "";
    for (const line of r.ReadLineContents()) s += line + "\n";
    f.Close();
    return s;
}
function openWriter(path) {
    const f = FS().CreateFile(path, "CreateAlways");
    const w = FS().CreateTextWriter(f, "Utf8");
    return { f: f, w: w, WriteLine: (s) => w.WriteLine(s), Close: () => f.Close() };
}
function propNames(o) {
    const names = [];
    try { for (const k in o) names.push(k); } catch (e) {}
    try { for (const k of Object.getOwnPropertyNames(o)) if (names.indexOf(k) < 0) names.push(k); } catch (e) {}
    return names;
}
function modBase(path) { const n = String(path); const i = Math.max(n.lastIndexOf(String.fromCharCode(92)), n.lastIndexOf("/")); return n.substring(i + 1); }
function findModule(name) {
    // exact basename match first (python -> python.exe, NOT python3.DLL); substring fallback
    const want = String(name).toLowerCase();
    let sub = null;
    for (const m of host.currentProcess.Modules) {
        const b = modBase(m.Name).toLowerCase();
        const stem = b.replace(/[.](exe|dll)$/, "");
        const rec = { name: String(m.Name), base: num(m.BaseAddress), size: num(m.Size) };
        if (b === want || stem === want) return rec;
        if (!sub && b.indexOf(want) >= 0) sub = rec;
    }
    return sub;
}
function inMod(ip, mod) { return ip >= mod.base && ip < mod.base + mod.size; }
function rvaOf(ip, mod) { return inMod(ip, mod) ? hex(ip - mod.base) : null; }
function resolveSym(sym) {
    // "mod!sym" -> absolute address via the symbol provider (exports suffice; no PDB needed). null if unknown.
    const i = sym.indexOf("!");
    if (i < 0) return null;
    try { return num(host.getModuleSymbolAddress(sym.substring(0, i), sym.substring(i + 1))); } catch (e) { return null; }
}
function callsQuery(addrs) {
    // addrs: array of absolute addresses (numbers). Always numeric (the game exe has no symbols); host.Int64 per arg.
    return host.currentSession.TTD.Calls(...addrs.map(a => host.Int64(a)));
}

// --------------------------------------------------------------------------- stages
function stageProbe(cfg, out) {
    const probe = { modules: [], memory_event_props: [], call_event_props: [], position_props: [] };
    for (const m of host.currentProcess.Modules) probe.modules.push({ name: String(m.Name), base: hex(m.BaseAddress), size: hex(m.Size) });
    try {
        const lt = host.currentProcess.TTD.Lifetime;
        probe.lifetime = { min: posStr(lt.MinPosition), max: posStr(lt.MaxPosition) };
        probe.position_props = propNames(lt.MinPosition);
    } catch (e) { probe.lifetime_error = String(e); }
    try {
        const evts = host.currentSession.TTD.Memory(cfg.clock_addr, cfg.clock_addr + cfg.clock_size, "w");
        for (const e of evts) { probe.memory_event_props = propNames(e); probe.memory_event_sample = { t: posStr(e.TimeStart), ip: hex(e.IP), addr: hex(e.Address), size: num(e.Size), type: String(e.AccessType), value: hex(e.Value) }; break; }
    } catch (e) { probe.memory_probe_error = String(e); }
    try {
        const tg = cfg.probe_call_target;
        if (tg !== undefined && tg !== null) {
            const cs = callsQuery([typeof tg === "string" ? resolveSym(tg) : tg]);
            for (const c of cs) { probe.call_event_props = propNames(c); probe.call_event_sample = { t: posStr(c.TimeStart), fn: hex(c.FunctionAddress), ret: hex(c.ReturnAddress), tid: num(c.ThreadId) }; break; }
        }
    } catch (e) { probe.call_probe_error = String(e); }
    const w = openWriter(out + "\\probe.json"); w.WriteLine(JSON.stringify(probe, null, 1)); w.Close();
    log("probe written; modules=" + probe.modules.length + " lifetime=" + JSON.stringify(probe.lifetime));
}

function stageBoundaries(cfg, out) {
    const b = [];
    if (cfg.boundary.indexOf("calls:") === 0) {
        const addr = parseInt(cfg.boundary.substring(6), 16);
        log("boundaries = calls to " + hex(addr));
        for (const c of callsQuery([addr])) b.push({ pos: pos(c.TimeStart), t: posStr(c.TimeStart), tid: num(c.ThreadId), value: null, ip: hex(c.ReturnAddress) });
    } else {
        log("boundaries = writes to clock " + hex(cfg.clock_addr));
        for (const e of host.currentSession.TTD.Memory(cfg.clock_addr, cfg.clock_addr + cfg.clock_size, "w"))
            b.push({ pos: pos(e.TimeStart), t: posStr(e.TimeStart), tid: num(e.ThreadId), value: num(e.Value), ip: hex(e.IP) });
    }
    b.sort((x, y) => cmp(x.pos, y.pos));
    const w = openWriter(out + "\\frames.json");
    w.WriteLine(JSON.stringify({ boundary: cfg.boundary, count: b.length, boundaries: b.map((x, i) => ({ i: i, t: x.t, tid: x.tid, value: x.value, ip: x.ip })) }, null, 1));
    w.Close();
    log("boundaries: " + b.length);
    return b;
}

function stageCalls(cfg, out, windows, mod) {
    const SEP = String.fromCharCode(92);
    const names = new Map();     // addr -> label for symbol targets
    const targets = [];
    for (const r of (cfg.anchors_rva || [])) targets.push(mod.base + r);           // per-frame gate anchors FIRST
    for (const s of (cfg.funcs_sym || [])) { const a = resolveSym(s); if (a) { targets.push(a); names.set(a, s); log("symbol " + s + " = " + hex(a)); } else log("symbol not resolved: " + s); }
    for (const r of (cfg.funcs_rva || [])) { const a = mod.base + r; if (targets.indexOf(a) < 0 || targets.length > 64) targets.push(a); }
    const uniq = Array.from(new Set(targets));
    log("calls: " + uniq.length + " numeric targets (" + (cfg.anchors_rva || []).length + " anchors, " + names.size + " symbols)");
    const chunk = cfg.calls_chunk || 64;
    const writers = windows.map(w => openWriter(out + SEP + "calls_f" + w.k + ".jsonl"));
    const counts = windows.map(() => 0);
    let total = 0;
    for (let i = 0; i < uniq.length; i += chunk) {
        const part = uniq.slice(i, i + chunk);
        let calls;
        try { calls = callsQuery(part); } catch (e) { log("Calls chunk " + i + " failed: " + e); continue; }
        for (const c of calls) {
            const p = pos(c.TimeStart);
            for (let wi = 0; wi < windows.length; wi++) {
                if (!inWin(p, windows[wi])) continue;
                let ret = 0, fa = 0, tid = 0, te = "";
                try { fa = num(c.FunctionAddress); } catch (e) {}
                try { ret = num(c.ReturnAddress); } catch (e) {}
                try { tid = num(c.ThreadId); } catch (e) {}
                try { te = posStr(c.TimeEnd); } catch (e) {}
                writers[wi].WriteLine(JSON.stringify({ t: posStr(c.TimeStart), te: te, fn: hex(fa), rva: rvaOf(fa, mod), sym: names.get(fa) || null, ret: hex(ret), ret_rva: rvaOf(ret, mod), tid: tid }));
                counts[wi]++; total++;
                break;
            }
        }
        log("calls: chunk " + (Math.floor(i / chunk) + 1) + "/" + Math.ceil(uniq.length / chunk) + " done, in-window so far " + total);
    }
    writers.forEach(w => w.Close());
    return counts;
}

function stageMemory(cfg, out, windows, mod, lo, hi, mode, tag, detail) {
    // aggregate per window: key = ip|addr|size|rw (blk) or ip|page (dcram, unless detail)
    const agg = windows.map(() => new Map());
    let seen = 0, kept = 0;
    let evts;
    try { evts = host.currentSession.TTD.Memory(lo, hi, mode); }
    catch (e) { log("Memory(" + tag + ") failed: " + e); return [0]; }
    for (const e of evts) {
        seen++;
        const p = pos(e.TimeStart);
        for (let wi = 0; wi < windows.length; wi++) {
            if (!inWin(p, windows[wi])) continue;
            const ip = num(e.IP), addr = num(e.Address), size = num(e.Size);
            const rw = String(e.AccessType).charAt(0).toLowerCase();  // r / w / e
            let key;
            if (tag === "blk" || detail) key = ip + "|" + addr + "|" + size + "|" + rw;
            else key = ip + "|" + (addr >>> 12) + "|" + rw;
            const m = agg[wi];
            let rec = m.get(key);
            if (!rec) {
                rec = { ip: ip, rva: rvaOf(ip, mod), addr: addr, lo: addr, hi: addr + size, size: size, rw: rw, n: 0, first: posStr(e.TimeStart), value: null };
                if (tag === "blk" && size <= 8) { try { rec.value = hex(e.Value); } catch (x) {} }
                m.set(key, rec);
            }
            rec.n++;
            if (addr < rec.lo) rec.lo = addr;
            if (addr + size > rec.hi) rec.hi = addr + size;
            kept++;
            break;
        }
        if (cfg.max_events && seen >= cfg.max_events) { log(tag + ": max_events reached"); break; }
        if (seen % 1000000 === 0) log(tag + ": " + seen + " events scanned, " + kept + " in window");
    }
    for (let wi = 0; wi < windows.length; wi++) {
        const w = openWriter(out + "\\" + tag + "_f" + windows[wi].k + ".jsonl");
        for (const rec of agg[wi].values()) {
            if (tag === "blk") w.WriteLine(JSON.stringify({ off: hex(rec.addr - lo), size: rec.size, rw: rec.rw, ip: hex(rec.ip), rva: rec.rva, n: rec.n, first: rec.first, value: rec.value }));
            else w.WriteLine(JSON.stringify({ ip: hex(rec.ip), rva: rec.rva, lo: hex(rec.lo - lo), hi: hex(rec.hi - lo), page: hex((rec.lo - lo) >>> 12 << 12), size: rec.size, rw: rec.rw, n: rec.n, first: rec.first }));
        }
        w.Close();
    }
    log(tag + ": scanned " + seen + " events, kept " + kept);
    return [seen, kept];
}

function dumpRange(path, addr, size) {
    // page-wise; unknown pages (never touched in the trace) -> zero + listed.  Binary via WriteBytes when
    // available, else hex text (extract.py accepts both).
    const PAGE = 4096;
    const unknown = [];
    let f = null, binary = true, w = null;
    try { f = FS().CreateFile(path, "CreateAlways"); if (typeof f.WriteBytes !== "function") { binary = false; } }
    catch (e) { binary = false; }
    if (!binary) { if (f) { try { f.Close(); } catch (e) {} } w = openWriter(path + ".hex"); }
    const HEX = []; for (let i = 0; i < 256; i++) HEX.push((i < 16 ? "0" : "") + i.toString(16));
    for (let off = 0; off < size; off += PAGE) {
        const ln = Math.min(PAGE, size - off);
        let bytes = null;
        try { bytes = host.memory.readMemoryValues(addr + off, ln, 1); } catch (e) { bytes = null; }
        if (bytes === null) { unknown.push(hex(addr + off)); bytes = new Array(ln).fill(0); }
        if (binary) { f.WriteBytes(bytes); }
        else { let s = ""; for (let i = 0; i < ln; i++) s += HEX[bytes[i] & 0xff]; w.WriteLine(s); }
    }
    if (binary) f.Close(); else w.Close();
    return { path: binary ? path : path + ".hex", binary: binary, unknown_pages: unknown.length, unknown: unknown.slice(0, 64) };
}

function stageDump(cfg, out, boundary, k) {
    const res = { at: boundary.t, frame: k, dumps: {} };
    try { boundary.raw.SeekTo(); } catch (e) { res.seek_error = String(e); log("SeekTo failed: " + e); return res; }
    const jobs = [["blk", cfg.blk, cfg.blk_size], ["ctx", cfg.ctx, cfg.ctx_size], ["dcram", cfg.dcram, cfg.dcram_size]];
    if (cfg.game_state) jobs.push(["game_state", cfg.game_state, 0x1000]);
    for (const j of jobs) {
        if (!j[1] || !j[2]) continue;
        try { res.dumps[j[0]] = dumpRange(out + "\\dump_f" + k + "_" + j[0] + ".bin", j[1], j[2]); log("dump " + j[0] + ": " + JSON.stringify(res.dumps[j[0]])); }
        catch (e) { res.dumps[j[0]] = { error: String(e) }; log("dump " + j[0] + " failed: " + e); }
    }
    const w = openWriter(out + "\\dump_f" + k + ".json"); w.WriteLine(JSON.stringify(res, null, 1)); w.Close();
    return res;
}

// --------------------------------------------------------------------------- entry
function run(cfgPath) {
    const cfg = JSON.parse(readText(cfgPath));
    const out = cfg.out;
    const H = (s) => (s === null || s === undefined) ? 0 : (typeof s === "number" ? s : parseInt(s, 16));
    if (typeof cfg.probe_call_target === "string" && cfg.probe_call_target.indexOf("!") >= 0) { cfg.probe_call_target_sym = cfg.probe_call_target; cfg.probe_call_target_is_rva = false; }
    for (const k of ["clock_addr", "blk", "blk_size", "dcram", "dcram_size", "ctx", "ctx_size", "game_state", "probe_call_target"]) cfg[k] = H(cfg[k]);
    cfg.clock_size = cfg.clock_size || 4;
    LOG = openWriter(out + "\\extract_log.txt");
    const t0 = Date.now();
    try {
        const mod = findModule(cfg.module);
        if (!mod) throw new Error("module '" + cfg.module + "' not in trace");
        log("module " + mod.name + " base " + hex(mod.base) + " size " + hex(mod.size));
        if (cfg.ghidra_base) log("aslr delta vs ghidra base " + hex(cfg.ghidra_base) + " = " + hex(mod.base - H(cfg.ghidra_base)));
        cfg.probe_call_target = cfg.probe_call_target_is_rva ? (cfg.probe_call_target ? mod.base + cfg.probe_call_target : null) : (cfg.probe_call_target_sym || null);
        stageProbe(cfg, out);
        const b = stageBoundaries(cfg, out);
        // frames k = [b[k], b[k+1]); window = first_frame .. first_frame+frames-1 (needs b[k+1])
        const windows = [];
        const first = cfg.first_frame || 0, n = cfg.frames || 1;
        for (let k = first; k < first + n && k + 1 < b.length; k++) windows.push({ k: k, lo: b[k].pos, hi: b[k + 1].pos, t0: b[k].t, t1: b[k + 1].t });
        const w = openWriter(out + "\\windows.json"); w.WriteLine(JSON.stringify({ module: mod, windows: windows.map(x => ({ k: x.k, t0: x.t0, t1: x.t1 })) }, null, 1)); w.Close();
        log("windows: " + JSON.stringify(windows.map(x => x.k)) + " of " + b.length + " boundaries");
        if (windows.length === 0) throw new Error("no complete frame in trace (boundaries=" + b.length + ")");
        const summary = { module: mod, boundaries: b.length, windows: windows.length };
        if (cfg.do_calls !== false) summary.calls = stageCalls(cfg, out, windows, mod);
        if (cfg.blk && cfg.blk_size) summary.blk = stageMemory(cfg, out, windows, mod, cfg.blk, cfg.blk + cfg.blk_size, "rw", "blk", true);
        if (cfg.dcram && cfg.dcram_size) summary.dcram = stageMemory(cfg, out, windows, mod, cfg.dcram, cfg.dcram + cfg.dcram_size, cfg.dcram_mode || "r", "dcram", !!cfg.dcram_detail);
        if (cfg.dump !== false) {
            // re-fetch the boundary object to seek (positions from Memory/Calls events carry SeekTo)
            const k = windows[0].k;
            let raw = null;
            if (cfg.boundary.indexOf("calls:") === 0) { let i = 0; for (const c of callsQuery([parseInt(cfg.boundary.substring(6), 16)])) { if (i++ === k) { raw = c.TimeStart; break; } } }
            else { let i = 0; for (const e of host.currentSession.TTD.Memory(cfg.clock_addr, cfg.clock_addr + cfg.clock_size, "w")) { if (i++ === k) { raw = e.TimeStart; break; } } }
            if (raw) summary.dump = stageDump(cfg, out, { t: windows[0].t0, raw: raw }, k);
        }
        summary.seconds = (Date.now() - t0) / 1000;
        const s = openWriter(out + "\\summary.json"); s.WriteLine(JSON.stringify(summary, null, 1)); s.Close();
        log("DONE in " + summary.seconds + " s");
        return "ok";
    } catch (e) {
        log("FATAL: " + e + (e.stack ? "\n" + e.stack : ""));
        return "error: " + e;
    } finally { try { LOG.Close(); } catch (e) {} LOG = null; }
}

// selftest: no trace needed (any live target). Proves JsProvider + FileSystem text/binary + JSON + module enumeration.
function selftest(outDir) {
    const res = { fs_text: false, fs_binary: false, modules: 0, json: false, evaluate: null, ttd: null };
    try { const w = openWriter(outDir + "\selftest.txt"); w.WriteLine("hello"); w.Close(); res.fs_text = readText(outDir + "\selftest.txt").trim() === "hello"; } catch (e) { res.fs_text = String(e); }
    try { const f = FS().CreateFile(outDir + "\selftest.bin", "CreateAlways"); res.fs_binary = typeof f.WriteBytes === "function"; if (res.fs_binary) f.WriteBytes([1, 2, 3, 4]); f.Close(); } catch (e) { res.fs_binary = String(e); }
    try { for (const m of host.currentProcess.Modules) res.modules++; } catch (e) { res.modules = String(e); }
    try { res.json = JSON.parse(JSON.stringify({ a: [1, "x"] })).a[1] === "x"; } catch (e) { res.json = String(e); }
    try { res.evaluate = String(host.evaluateExpression("1+1")); } catch (e) { res.evaluate = "err " + e; }
    try { res.ttd = host.currentSession.TTD ? "present" : "absent"; } catch (e) { res.ttd = "absent: " + e; }
    try { const b = host.memory.readMemoryValues(num(host.currentProcess.Modules.First().BaseAddress), 4, 1); res.readmem = b.length === 4 && b[0] === 0x4d && b[1] === 0x5a; } catch (e) { res.readmem = String(e); }
    const w = openWriter(outDir + "\selftest.json"); w.WriteLine(JSON.stringify(res)); w.Close();
    return JSON.stringify(res);
}

function initializeScript() { return [new host.apiVersionSupport(1, 7)]; }
