#!/usr/bin/env python3
"""extract.py -- replay a TTD trace headless (cdb -z + extract.js) and emit per-frame READ-SET data.

  python extract.py --run <runs/<ts> dir | trace.run> [--frames 3] [--first-frame 1] [--boundary clock|walker|dispatcher|rva:0x620f10]
                    [--all-funcs] [--dcram-detail] [--dcram-mb 16] [--no-dump] [--synthetic cfg.json]

Per frame k (frame = [boundary_k, boundary_k+1); default boundary = writes to the engine frame clock blk+0x3CC8):
  extract/frame_<k>.json   {"calls":[{t,fn,rva,ret_rva,tid,name,sh4,role}], "blk":[{off,size,rw,fn,name,n,value}], "dcram":[{fn,name,dc_lo,dc_hi,n}]}
  extract/summary.csv      frame,fn,name,sh4,role,ncalls,blk_reads,blk_writes,dcram_reads
  extract/readset.csv      fn,name,sh4,off,size,rw,count,frames   (the READ SET: which blk offsets each function touched)
  dcram.bin / ctx.bin / blk.bin   memory images AT the first window boundary: trace-known pages, holes filled
                                  from pre/ (dump_live.py); *.merge.json says which pages came from where.
Function names: RVA -> FUN_14xxxxxxx via d3dcap/replay/re_map/steam_funcs.jsonl (body ranges); SH4 pair + role via
docs/steam_sh4_map.csv (CONFIRMED/INFERRED tiers carried through). join_kb.py adds the live graph and writes the seed.

Replay engine: cdbX64.exe from the winget Microsoft.WinDbg package (TTDReplay.dll sits beside it). The .idx index is
built on first open (minutes for multi-GB traces) and cached next to the .run.
"""
import argparse
import bisect
import csv
import glob
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
GHIDRA_BASE = 0x140000000
GAME_LO, GAME_HI = 0x140600000, 0x1408E0000          # docs/STEAM-SH4-FUNCTION-MAP.md s2 (game range)
MEGA_BLOBS = {0x14006A3F0, 0x1406415E0}               # switch blobs excluded by the map (s1.3)
BOUNDARIES = {"clock": "clock", "walker": "calls:%x", "dispatcher": "calls:%x", "tick": "calls:%x", "advance_frame": "calls:%x"}
BOUNDARY_RVA = {"walker": 0x620F10, "dispatcher": 0x620960, "tick": 0x118950, "advance_frame": 0x118F00}
FUNCS_JSONL = os.path.join(HERE, "..", "replay", "re_map", "steam_funcs.jsonl")
MAP_CSV = os.path.join(HERE, "..", "..", "docs", "steam_sh4_map.csv")


def find_cdb():
    c = [os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\WindowsApps\cdbX64.exe")]
    for d in glob.glob(r"C:\Program Files\WindowsApps\Microsoft.WinDbg_*_x64*"):
        c.append(os.path.join(d, "amd64", "cdb.exe"))
    for p in c:
        if os.path.exists(p):
            return p
    raise SystemExit("cdb not found; install: winget install --id Microsoft.WinDbg --exact --accept-package-agreements --accept-source-agreements")


def latest_run():
    ds = sorted(d for d in glob.glob(os.path.join(RUNS, "*")) if os.path.isdir(d))
    if not ds:
        raise SystemExit("no runs under %s" % RUNS)
    return ds[-1]


class Names:
    """RVA -> function (by body containment) + SH4 pair/role from the map csv. Offline; no server needed."""

    def __init__(self, funcs_jsonl, map_csv, live_base):
        self.starts, self.ends, self.names = [], [], []
        self.delta = live_base - GHIDRA_BASE
        if os.path.exists(funcs_jsonl):
            rows = []
            with open(funcs_jsonl, encoding="utf-8") as f:
                for line in f:
                    j = json.loads(line)
                    rows.append((j["body"][0], j["body"][1], j["name"]))
            rows.sort()
            for s, e, n in rows:
                self.starts.append(s); self.ends.append(e); self.names.append(n)
        self.map = {}
        if os.path.exists(map_csv):
            with open(map_csv, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    a = int(r["steam_addr"], 16)
                    self.map.setdefault(a, []).append(r)

    def game_funcs(self, all_funcs=False):
        out = []
        for s in self.starts:
            if s in MEGA_BLOBS:
                continue
            if all_funcs or GAME_LO <= s < GAME_HI:
                out.append(s - GHIDRA_BASE)
        return out

    def lookup_rva(self, rva):
        a = rva + GHIDRA_BASE
        i = bisect.bisect_right(self.starts, a) - 1
        if i >= 0 and self.starts[i] <= a < self.ends[i]:
            return self.starts[i], self.names[i]
        return a, "FUN_%x" % a

    def annotate(self, rva):
        fa, name = self.lookup_rva(rva)
        rows = self.map.get(fa, [])
        prim = rows[0] if rows else None
        return {"fn": "0x%x" % fa, "name": name,
                "sh4": prim["sh4_label"] if prim else None, "sh4_conf": prim["confidence"] if prim else None,
                "role": prim["sh4_role"] if prim and prim["sh4_role"] else None,
                "inlined": [r["sh4_label"] for r in rows[1:]] if len(rows) > 1 else None}


def read_jsonl(p):
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def merge_dump(run, ext, k, tag, size):
    """trace dump at boundary (+unknown pages) over the live pre-snapshot -> run/<tag>.bin"""
    src_bin = os.path.join(ext, "dump_f%d_%s.bin" % (k, tag))
    src_hex = src_bin + ".hex"
    pre = os.path.join(run, "pre", tag + ".bin")
    info = {"tag": tag, "frame": k, "trace_dump": None, "pre": pre if os.path.exists(pre) else None, "unknown_pages_filled": 0}
    data = None
    if os.path.exists(src_bin):
        data = bytearray(open(src_bin, "rb").read()); info["trace_dump"] = src_bin
    elif os.path.exists(src_hex):
        data = bytearray(); info["trace_dump"] = src_hex
        with open(src_hex) as f:
            for line in f:
                data += bytes.fromhex(line.strip())
    dj = os.path.join(ext, "dump_f%d.json" % k)
    unknown = []
    if os.path.exists(dj):
        d = json.load(open(dj)).get("dumps", {}).get(tag, {})
        unknown = d.get("unknown", []); info["unknown_pages"] = d.get("unknown_pages")
    if data is None and info["pre"]:
        data = bytearray(open(pre, "rb").read()); info["source"] = "pre only (no trace dump)"
    elif data is not None and info["pre"] and unknown:
        pre_b = open(pre, "rb").read()
        # the JS lists absolute unknown page addresses; translate via the pre meta pointer
        meta = json.load(open(os.path.join(run, "pre", "meta.json")))
        b0 = int(meta[tag], 16) if tag in meta and meta[tag] else None
        if b0 is not None:
            for a in unknown:
                off = int(a, 16) - b0
                if 0 <= off < len(data):
                    data[off:off + 0x1000] = pre_b[off:off + 0x1000]; info["unknown_pages_filled"] += 1
        info["source"] = "trace dump, holes from pre"
    elif data is not None:
        info["source"] = "trace dump"
    if data is None:
        info["source"] = "NONE"
    else:
        if size and len(data) > size:
            data = data[:size]
        open(os.path.join(run, tag + ".bin"), "wb").write(data); info["bytes"] = len(data)
    json.dump(info, open(os.path.join(run, tag + ".merge.json"), "w"), indent=1)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="", help="runs/<ts> directory or a .run file (default: latest run)")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--first-frame", type=int, default=1, help="skip frame 0 (partial: starts at attach)")
    ap.add_argument("--boundary", default="clock", help="clock | walker | dispatcher | tick | advance_frame | rva:0x...")
    ap.add_argument("--all-funcs", action="store_true", help="track all 29678 functions, not just the game range")
    ap.add_argument("--calls-chunk", type=int, default=64)
    ap.add_argument("--dcram-detail", action="store_true", help="exact DC addresses instead of 4 KB pages")
    ap.add_argument("--dcram-mb", type=int, default=16)
    ap.add_argument("--no-dump", action="store_true")
    ap.add_argument("--no-calls", action="store_true")
    ap.add_argument("--max-events", type=int, default=0)
    ap.add_argument("--synthetic", default="", help="cfg json for a non-game trace (module/clock_addr/funcs_sym); skips the game maps")
    ap.add_argument("--cdb", default="")
    ap.add_argument("--timeout", type=int, default=6 * 3600)
    ap.add_argument("--skip-replay", action="store_true", help="only post-process an existing extract/")
    a = ap.parse_args()

    run = a.run or latest_run()
    if run.lower().endswith(".run"):
        trace, run = run, os.path.dirname(run)
    else:
        rs = glob.glob(os.path.join(run, "*.run"))
        if not rs:
            raise SystemExit("no .run in %s" % run)
        trace = rs[0]
    ext = os.path.join(run, "extract")
    os.makedirs(ext, exist_ok=True)
    meta_p = os.path.join(run, "pre", "meta.json")
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}

    if a.synthetic:
        cfg = json.load(open(a.synthetic))
        live_base = int(cfg.get("live_base", "0x0"), 16)
        names = None
    else:
        if not meta:
            raise SystemExit("pre/meta.json missing (record.ps1 -NoDump?) -- cannot resolve blk/dcram; pass --synthetic")
        live_base = int(meta["exe_base"], 16)
        names = Names(FUNCS_JSONL, MAP_CSV, live_base)
        bnd = a.boundary
        if bnd in BOUNDARY_RVA:
            bnd = "calls:%x" % (live_base + BOUNDARY_RVA[bnd])
        elif bnd.startswith("rva:"):
            bnd = "calls:%x" % (live_base + int(bnd[4:], 16))
        cfg = {
            "module": meta["module"], "ghidra_base": hex(GHIDRA_BASE),
            "clock_addr": meta["clock_addr"], "clock_size": 4, "boundary": bnd,
            "blk": meta["blk"], "blk_size": meta["blk_size"],
            "dcram": meta["dcram"], "dcram_size": hex(a.dcram_mb << 20),
            "ctx": meta["ctx"], "ctx_size": meta["ctx_size"], "game_state": meta["game_state"],
            "funcs_rva": names.game_funcs(a.all_funcs), "funcs_sym": [],
            "probe_call_target": hex(0x620F10), "probe_call_target_is_rva": True,
            "anchors_rva": [0x620960, 0x620F10, 0x118950, 0x118F00],   # dispatcher, walker, sim tick, advance_frame cb
        }
    cfg.setdefault("anchors_rva", [])
    cfg.update({"out": ext, "first_frame": a.first_frame, "frames": a.frames, "calls_chunk": a.calls_chunk,
                "dcram_detail": a.dcram_detail, "dump": not a.no_dump, "do_calls": not a.no_calls, "max_events": a.max_events})
    cfg_p = os.path.join(ext, "cfg.json")
    json.dump(cfg, open(cfg_p, "w"), indent=1)

    if not a.skip_replay:
        cdb = a.cdb or find_cdb()
        js = os.path.join(HERE, "extract.js")
        # dx string literals use C-style escapes (a backslash-U sequence would be an escape): pass forward-slash paths
        cmd = '.scriptload %s; dx @$scriptContents.run("%s"); q' % (js.replace("\\", "/"), cfg_p.replace("\\", "/"))
        argv = [cdb, "-z", trace, "-c", cmd]
        print("[extract] %s" % " ".join('"%s"' % x if " " in x else x for x in argv))
        t0 = time.time()
        with open(os.path.join(ext, "cdb_stdout.txt"), "w", encoding="utf-8", errors="replace") as so:
            rc = subprocess.call(argv, stdout=so, stderr=subprocess.STDOUT, timeout=a.timeout)
        print("[extract] cdb exit %d in %.0f s; log: %s" % (rc, time.time() - t0, os.path.join(ext, "extract_log.txt")))
        lp = os.path.join(ext, "extract_log.txt")
        if os.path.exists(lp):
            for line in open(lp, encoding="utf-8", errors="replace").read().splitlines()[-12:]:
                print("   " + line)

    # ---------------------------------------------------------------- post-process
    wp = os.path.join(ext, "windows.json")
    if not os.path.exists(wp):
        raise SystemExit("extract.js produced no windows.json -- see %s" % os.path.join(ext, "cdb_stdout.txt"))
    windows = json.load(open(wp))["windows"]
    frames = json.load(open(os.path.join(ext, "frames.json")))
    ann_cache = {}

    def ann(rec):
        """rec has rva (module-relative hex or None when the IP is outside the module), fn (abs hex), optional sym"""
        rva_hex, fn_hex, sym = rec.get("rva"), rec.get("fn") or rec.get("ip"), rec.get("sym")
        if names is None or not rva_hex:
            return {"fn": fn_hex, "name": sym or fn_hex, "sh4": None, "sh4_conf": None, "role": None, "inlined": None}
        if rva_hex not in ann_cache:
            ann_cache[rva_hex] = names.annotate(int(rva_hex, 16))
        return ann_cache[rva_hex]

    summary_rows, readset = [], {}
    for w in windows:
        k = w["k"]
        calls = read_jsonl(os.path.join(ext, "calls_f%d.jsonl" % k))
        blk = read_jsonl(os.path.join(ext, "blk_f%d.jsonl" % k))
        dcr = read_jsonl(os.path.join(ext, "dcram_f%d.jsonl" % k))
        calls.sort(key=lambda c: tuple(int(x, 16) for x in c["t"].split(":")))
        per = {}
        for c in calls:
            c.update(ann(c))
            per.setdefault(c["fn"], {"ncalls": 0, "blk_reads": 0, "blk_writes": 0, "dcram_reads": 0, **{x: c[x] for x in ("name", "sh4", "role")}})["ncalls"] += 1
        for m in blk:
            m.update(ann(m))
            p = per.setdefault(m["fn"], {"ncalls": 0, "blk_reads": 0, "blk_writes": 0, "dcram_reads": 0, **{x: m[x] for x in ("name", "sh4", "role")}})
            p["blk_reads" if m["rw"] == "r" else "blk_writes"] += m["n"]
            key = (m["fn"], m["off"], m["size"], m["rw"])
            r = readset.setdefault(key, {"count": 0, "frames": set(), "name": m["name"], "sh4": m["sh4"]})
            r["count"] += m["n"]; r["frames"].add(k)
        for d in dcr:
            d.update(ann(d))
            d["dc_lo"] = "0x%x" % (0x0C000000 + int(d["lo"], 16)); d["dc_hi"] = "0x%x" % (0x0C000000 + int(d["hi"], 16))
            per.setdefault(d["fn"], {"ncalls": 0, "blk_reads": 0, "blk_writes": 0, "dcram_reads": 0, **{x: d[x] for x in ("name", "sh4", "role")}})["dcram_reads"] += d["n"]
        boundary = frames["boundaries"][k] if k < len(frames["boundaries"]) else {}
        json.dump({"frame": k, "t0": w["t0"], "t1": w["t1"], "clock_value": boundary.get("value"), "boundary": frames["boundary"],
                   "n_calls": len(calls), "n_blk_records": len(blk), "n_dcram_records": len(dcr),
                   "calls": calls, "blk": blk, "dcram": dcr},
                  open(os.path.join(ext, "frame_%d.json" % k), "w"), indent=0)
        for fn, p in per.items():
            summary_rows.append([k, fn, p["name"], p["sh4"] or "", p["role"] or "", p["ncalls"], p["blk_reads"], p["blk_writes"], p["dcram_reads"]])
        print("[extract] frame %d: %d calls, %d blk records, %d dcram records, %d functions" % (k, len(calls), len(blk), len(dcr), len(per)))

    with open(os.path.join(ext, "summary.csv"), "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f); cw.writerow(["frame", "fn", "name", "sh4", "role", "ncalls", "blk_reads", "blk_writes", "dcram_reads"]); cw.writerows(summary_rows)
    with open(os.path.join(ext, "readset.csv"), "w", newline="", encoding="utf-8") as f:
        cw = csv.writer(f); cw.writerow(["fn", "name", "sh4", "off", "size", "rw", "count", "frames"])
        for (fn, off, size, rw), r in sorted(readset.items(), key=lambda kv: (kv[0][0], int(kv[0][1], 16))):
            cw.writerow([fn, r["name"], r["sh4"] or "", off, size, rw, r["count"], " ".join(str(x) for x in sorted(r["frames"]))])
    print("[extract] wrote %s and %s" % (os.path.join(ext, "summary.csv"), os.path.join(ext, "readset.csv")))

    if windows and not a.no_dump and not a.synthetic:
        k = windows[0]["k"]
        for tag, size in (("blk", int(meta["blk_size"], 16)), ("ctx", int(meta["ctx_size"], 16)), ("dcram", a.dcram_mb << 20)):
            info = merge_dump(run, ext, k, tag, size)
            print("[extract] %s.bin: %s (%s bytes, %s holes filled)" % (tag, info.get("source"), info.get("bytes"), info.get("unknown_pages_filled")))


if __name__ == "__main__":
    main()
