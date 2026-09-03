#!/usr/bin/env python3
"""join_kb.py -- join one extracted frame with the re_kb graph and write the READ-SET seed.

  python join_kb.py --run <runs/<ts>> [--frame K] [--seed <path>] [--apply]

Reads   <run>/extract/frame_<K>.json (extract.py)
Queries re_kb (http://127.0.0.1:8001, ns re db kb): steam_routine nodes + ->recompiles->routine pairs
Writes  <run>/extract/readset_f<K>.md   the per-frame READ SET table (function, SH4 pair, blk offsets read/written)
        <seed>                          maplecast-flycast/tools/re_kb/105_ttd_frame_readset.surql (idempotent UPSERT/RELATE)
--apply takes the documented logical backup (tools/re_kb/README.md) then runs apply_seed.py on the seed.

Seed content (all idempotent, explicit edge ids):
  source:ttd_trace_<ts>                       provenance (trace dir, boundary rule, frame)
  finding:ttd_f<K>_frame_<ts>                 the executed-function list of the frame (ordered first-call, counts)
  finding:ttd_readset_<FUN>                   per function: blk offsets read/written + DC-RAM pages, status=confirmed (dynamic evidence)
  RELATE finding->about->steam_routine, finding->cites->source
  UPDATE steam_routine:<FUN> SET ttd_blk_reads/ttd_blk_writes/ttd_frames   (separate from the static crawl fields)
  + the GGPO callback pairs found while building this tool (FUN_140118f00 advance_frame -> FUN_140118950 tick)
"""
import argparse
import base64
import glob
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
MAPLE = os.path.abspath(os.path.join(HERE, "..", "..", "..", "maplecast-flycast"))
SEED_DEFAULT = os.path.join(MAPLE, "tools", "re_kb", "105_ttd_frame_readset.surql")
URL = os.environ.get("REKB_URL", "http://127.0.0.1:8001/sql")
AUTH = os.environ.get("REKB_AUTH", "root:root")


def sql(q):
    req = urllib.request.Request(URL, data=("USE NS re DB kb; " + q).encode("utf-8"), method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read().decode("utf-8"))
    return out[-1].get("result") if out else None


def esc(s):
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def compact(offs):
    """sorted hex offsets -> 'a,b,c' capped"""
    offs = sorted(set(offs))
    s = ",".join("0x%x" % o for o in offs[:200])
    return s + (",...(+%d)" % (len(offs) - 200) if len(offs) > 200 else "")


def static_block():
    """the GGPO callback pairs read while building the tool (Ghidra, 2026-09-02) -- valid without any trace"""
    return [
    "-- ---- GGPO callback pairs read while building the tool (Ghidra decompile of FUN_140118ae0 + callees, 2026-09-02) ----",
    "UPSERT source:ghidra_ggpo_callbacks SET kind='ghidra', strength='code', ref='mvc_dump.bin FUN_140118ae0 (ggpo_start_session caller) 0x140118aff..0x140118b77', note='GGPOSessionCallbacks built on the stack at RSP+0x30: +0 begin_game=FUN_1400365e0 (ret 1), +8 save_game_state=FUN_140119380, +0x10 load_game_state=FUN_140118fa0, +0x18 log_game_state=FUN_1400365e0, +0x20 free_buffer=LAB_140118f90, +0x28 advance_frame=FUN_140118f00, +0x30 on_event=FUN_140119010; passed as arg 2 to FUN_140119950 (ggpo_start_session) with input_size 4, num_players param_2.';",
    "UPSERT steam_routine:FUN_140118f00 SET addr='0x140118f00', name='FUN_140118f00', role='GGPO advance_frame callback: ggpo_synchronize_input(session,&in,0x10,&flags) -> FUN_140118950(&DAT_142d10b90,&in,flags) [sim tick] -> ggpo_advance_frame(session)', note='CONFIRMED by decompile 2026-09-02: FUN_140119a60 = synchronize_input (size 0x10 = 4 players x 4 B), FUN_1401198d0 = advance_frame. Also mirrors DAT_142d10b90 (frame counter) into DAT_142e111a8/b0 every 0x5A frames.', matched=false;",
    "UPSERT steam_routine:FUN_140118950 SET addr='0x140118950', name='FUN_140118950', role='THE SIM TICK: (game=&DAT_142d10b90, inputs[4], disconnect_flags) -> next state; invoked from the advance_frame callback during rollback and (INFERRED) from the main loop offline', note='Caller CONFIRMED (FUN_140118f00). Body not yet read. Offline, *(0x142E10B98)==0 (no session) so the tick is reached from the main loop; the TTD trace names that caller (calls_f<k>.jsonl ret_rva).', matched=false;",
    "UPSERT steam_routine:FUN_140118fa0 SET addr='0x140118fa0', name='FUN_140118fa0', role='GGPO load_game_state: memcpy(&DAT_142d10b90, buf, len) bracketed by FUN_140118270/FUN_140118310 (scatter blk back), then ++*(game_state+0x76c) rollback counter', note='CONFIRMED by decompile 2026-09-02', matched=false;",
    "UPSERT steam_routine:FUN_140119380 SET addr='0x140119380', name='FUN_140119380', role='GGPO save_game_state: *len=0x100004, buf=alloc, FUN_1401188c0(&DAT_142d10b90) gather, memcpy(buf,&DAT_142d10b90,0x100004)', note='CONFIRMED by decompile 2026-09-02. The saved region is 1 MB rooted at 0x142D10B90 (an exe global), NOT blk itself (blk is heap; live 0x17FD1000 on 2026-09-02); FUN_1401188c0/FUN_140118310 gather/scatter registered regions (FUN_140118290 registers blk at game_state+0x1b0/0x1b8).', matched=false;",
    "UPSERT finding:ggpo_advance_frame_callback SET statement='The GGPO advance_frame callback is FUN_140118f00 (callbacks struct +0x28 in FUN_140118ae0). It calls ggpo_synchronize_input then FUN_140118950(&DAT_142d10b90, inputs, flags) -- the game sim tick -- then ggpo_advance_frame. save_game_state (FUN_140119380) copies 0x100004 bytes from 0x142D10B90 after a gather step; blk (0x33B18 B, heap) is one registered region inside that gather.', status='confirmed', confidence='high', date='2026-09-02', kind='ggpo_callbacks';",
    "RELATE finding:ggpo_advance_frame_callback->about:ggpo_cb_f00->steam_routine:FUN_140118f00;",
    "RELATE finding:ggpo_advance_frame_callback->about:ggpo_cb_950->steam_routine:FUN_140118950;",
    "RELATE finding:ggpo_advance_frame_callback->about:ggpo_cb_fa0->steam_routine:FUN_140118fa0;",
    "RELATE finding:ggpo_advance_frame_callback->about:ggpo_cb_380->steam_routine:FUN_140119380;",
    "RELATE finding:ggpo_advance_frame_callback->cites:ggpo_cb_src->source:ghidra_ggpo_callbacks;",
    "RELATE steam_routine:FUN_140118f00->calls:ggpo_cb_f00_950->steam_routine:FUN_140118950;",
    "-- ---- TTD attach is blocked by inline ntdll hooks in the live game process (2026-09-03) ----",
    "UPSERT source:ttd_attach_failures_20260903 SET kind='ttd', strength='reproduction', ref='mvc-live-skins-quarters/d3dcap/ttd/runs/20260903-000941 and 20260903-001536 (*.out); preflight.py byte compare on pids 72816, 63992, 56376', note='TTDInject: Injection by thread was incomplete. Status: 2156436999; RecordVcpu ErrorGettingNtdllApiAddresses: GetNtdllAPIAddresses() failed for NtResumeThread; TTDRecordCPU.dll had been injected. Same failure twice (elevated, offline match, scene 5, ggpo_session 0). Synthetic python target recorded fine minutes earlier with the same setup.';",
    "UPSERT finding:steam_overlay_hooks_block_ttd SET statement='TTD cannot ATTACH to the running Steam MvC2 process: the recorder validates the ntdll syscall stubs it needs and in the game process ntdll!NtResumeThread (plus NtCreateThread, NtQueryInformationProcess, NtMapViewOfSection, NtUnmapViewOfSection, NtClose, NtWaitForSingleObject, NtCreateSection, NtQueryVirtualMemory, NtCreateFile, NtOpenFile, NtDuplicateObject, NtCreateUserProcess, NtDeviceIoControlFile, NtWaitForMultipleObjects, LdrLoadDll) begins with E9 rel32 (JMP) where an unhooked process holds the stub 4C 8B D1 B8 imm32 (CONFIRMED, 16-byte ReadProcessMemory compare, pids 72816 / 63992 / 56376; TTD fails twice with GetNtdllAPIAddresses() failed for NtResumeThread, status 2156436999). OWNERSHIP (CONFIRMED by following the JMPs): LdrLoadDll -> private trampoline -> gameoverlayrenderer64.dll+0xad1a0 (Steam overlay). The 15 Nt* hooks -> one private RWX page (0x7ffc0c490000) of push-ret stubs (sub rsp,8 / mov [rsp],lo / mov [rsp+4],hi / ret) whose 64 return targets ALL lie inside the game image, MarvelVsCapcomFightingCollection.exe+0x311ddf0..+0x3124720, in the unnamed PE section at VA 0x03092000 (characteristics 0xE0000040 = RWX initialized data, vsize 0xCDA000 raw 0x63400, i.e. the packer/runtime layer of the packed retail exe), and the handler code is a normal compiled prologue (55 48 89 E5 48 8D 64 24 C0 ...). So the syscall hooks that break TTD attach belong to the EXE, not the overlay; disabling the overlay removes only the LdrLoadDll hook (INFERRED, falsify with preflight.py after an overlay-off relaunch). Consequence: ttd -attach is impossible on this title; the working path is ttd -launch of the exe directly (record.ps1 -Launch: TTD initialises on a clean ntdll before the runtime layer hooks it; direct launch with SteamAppId=2634890 is proven by d3dcap/launch_suspended.ps1; ring buffer keeps the last seconds).', status='confirmed', confidence='high', date='2026-09-03', kind='tooling_blocker', remedy='Do NOT attach. Quit the game; run record.ps1 -Launch (TTD launches the exe itself, ring buffer), play into an OFFLINE match, press ENTER to snapshot+stop. Overlay-off is still advisable (removes the LdrLoadDll hook) but does not clear NtResumeThread.';",
    "UPSERT source:doc_ttd_frame_trace SET kind='doc', strength='doc', ref='mvc-live-skins-quarters/docs/TTD-FRAME-TRACE.md', note='TTD frame-trace tooling: record.ps1 (pre-flight + elevated attach), dump_live.py, extract.js/py (numeric Calls, per-frame blk/DC-RAM read set), join_kb.py, preflight.py';",
    "RELATE finding:steam_overlay_hooks_block_ttd->cites:overlay_ttd_src->source:ttd_attach_failures_20260903;",
    "RELATE finding:steam_overlay_hooks_block_ttd->cites:overlay_ttd_doc->source:doc_ttd_frame_trace;",
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="")
    ap.add_argument("--frame", type=int, default=-1)
    ap.add_argument("--seed", default=SEED_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-kb", action="store_true", help="offline: skip the graph query, still write md + seed")
    ap.add_argument("--top", type=int, default=400, help="functions kept in the frame finding")
    ap.add_argument("--static-only", action="store_true", help="write/apply only the static GGPO-callback block (no trace needed)")
    a = ap.parse_args()
    if a.static_only:
        L = ["-- 34: TTD frame READ SET seed -- STATIC PART ONLY (no trace yet); generated by d3dcap/ttd/join_kb.py --static-only (%s)" % time.strftime("%Y-%m-%d"),
             "-- Re-run join_kb.py --run <trace> to append the per-frame read-set findings. Idempotent (UPSERT / RELATE with explicit ids).",
             "USE NS re DB kb;", "DEFINE TABLE IF NOT EXISTS steam_routine SCHEMALESS;", "DEFINE TABLE IF NOT EXISTS recompiles SCHEMALESS;", ""] + static_block()
        os.makedirs(os.path.dirname(a.seed), exist_ok=True)
        open(a.seed, "w", encoding="utf-8").write(chr(10).join(L) + chr(10))
        print("[join] wrote static seed %s (%d statements)" % (a.seed, sum(1 for l in L if l.strip() and not l.startswith("--"))))
        if a.apply:
            apply_seed(a.seed)
        return
    runs = os.path.join(HERE, "runs")
    run = a.run or sorted(d for d in glob.glob(os.path.join(runs, "*")) if os.path.isdir(d))[-1]
    ext = os.path.join(run, "extract")
    fr = sorted(glob.glob(os.path.join(ext, "frame_*.json")), key=lambda p: int(os.path.basename(p)[6:-5]))
    if not fr:
        raise SystemExit("no frame_*.json in %s" % ext)
    fp = fr[0] if a.frame < 0 else os.path.join(ext, "frame_%d.json" % a.frame)
    F = json.load(open(fp))
    k = F["frame"]
    ts = os.path.basename(os.path.normpath(run))
    meta_p = os.path.join(run, "pre", "meta.json")
    meta = json.load(open(meta_p)) if os.path.exists(meta_p) else {}

    # per-function aggregation
    fn = {}
    order = []
    for c in F["calls"]:
        d = fn.setdefault(c["fn"], {"name": c["name"], "sh4": c.get("sh4"), "conf": c.get("sh4_conf"), "role": c.get("role"), "ncalls": 0, "reads": set(), "writes": set(), "dc": set(), "first": c["t"]})
        if d["ncalls"] == 0:
            order.append(c["fn"])
        d["ncalls"] += 1
    for m in F["blk"]:
        d = fn.setdefault(m["fn"], {"name": m["name"], "sh4": m.get("sh4"), "conf": m.get("sh4_conf"), "role": m.get("role"), "ncalls": 0, "reads": set(), "writes": set(), "dc": set(), "first": m["first"]})
        (d["reads"] if m["rw"] == "r" else d["writes"]).add(int(m["off"], 16))
    for m in F["dcram"]:
        d = fn.setdefault(m["fn"], {"name": m["name"], "sh4": m.get("sh4"), "conf": m.get("sh4_conf"), "role": m.get("role"), "ncalls": 0, "reads": set(), "writes": set(), "dc": set(), "first": m["first"]})
        d["dc"].add(int(m["page"], 16))
    print("[join] frame %d: %d functions (%d called, %d touching blk)" % (k, len(fn), len(order), sum(1 for d in fn.values() if d["reads"] or d["writes"])))

    # graph join
    kb = {}
    if not a.no_kb:
        ids = ["steam_routine:%s" % d["name"] for d in fn.values() if d["name"].startswith("FUN_")]
        for i in range(0, len(ids), 300):
            part = ids[i:i + 300]
            rows = sql("SELECT id, role, note, ->recompiles.out AS sh4, ->recompiles.confidence AS conf FROM steam_routine WHERE id IN [%s];" % ",".join(part)) or []
            for r in rows:
                kb[str(r["id"]).split(":", 1)[1]] = r
        print("[join] graph: %d of %d functions have steam_routine nodes" % (len(kb), len(ids)))

    # markdown table
    md = [("# TTD READ SET -- frame %d of %s (boundary: %s)" % (k, ts, F.get("boundary"))),
          "", "clock value at boundary: %s; window %s .. %s; %d calls, %d blk records, %d dcram records" % (F.get("clock_value"), F["t0"], F["t1"], F["n_calls"], F["n_blk_records"], F["n_dcram_records"]),
          "", "| # | function | SH4 pair (conf) | role (graph) | calls | blk reads | blk writes | DC-RAM pages |", "|---|---|---|---|---|---|---|---|"]
    for i, f in enumerate(order + [x for x in fn if x not in order]):
        d = fn[f]
        g = kb.get(d["name"], {})
        sh4 = g.get("sh4") or d["sh4"]
        sh4 = ",".join(str(x).replace("routine:", "") for x in sh4) if isinstance(sh4, list) else (sh4 or "")
        conf = g.get("conf") or d["conf"]
        conf = ",".join(str(x) for x in conf) if isinstance(conf, list) else (conf or "")
        role = (g.get("role") or d["role"] or "")[:80]
        md.append("| %d | %s | %s %s | %s | %d | %s | %s | %s |" % (i, d["name"], sh4, ("(%s)" % conf) if conf else "", role.replace("|", "/"), d["ncalls"], compact(d["reads"])[:120], compact(d["writes"])[:120], ",".join("0x%x" % p for p in sorted(d["dc"])[:16])))
    mdp = os.path.join(ext, "readset_f%d.md" % k)
    open(mdp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("[join] wrote %s" % mdp)

    # seed
    src = "ttd_trace_%s" % ts.replace("-", "_")
    L = ["-- 34: TTD frame READ SET -- generated by mvc-live-skins-quarters/d3dcap/ttd/join_kb.py (%s)" % time.strftime("%Y-%m-%d"),
         "-- Trace: %s  frame %d  boundary %s. Apply with tools/re_kb/apply_seed.py (per statement). Idempotent." % (run, k, F.get("boundary")),
         "-- BYOR: this seed holds offsets/addresses/function names only, no trace bytes.",
         "USE NS re DB kb;",
         "DEFINE TABLE IF NOT EXISTS steam_routine SCHEMALESS;",
         "DEFINE TABLE IF NOT EXISTS recompiles SCHEMALESS;",
         "",
         *static_block(),
         "",
         "-- ---- trace provenance ----",
         "UPSERT source:%s SET kind='ttd', strength='dynamic', ref='%s', note='Microsoft TTD time-travel trace of the live Steam MvC2 process (offline match), replayed headless with cdb + extract.js. Frame %d = [%s, %s) by %s. clock=%s exe_base=%s blk=%s dcram=%s. Trace bytes are NOT in the repo (gitignored runs/).';"
         % (src, esc(run), k, F["t0"], F["t1"], esc(F.get("boundary")), F.get("clock_value"), meta.get("exe_base"), meta.get("blk"), meta.get("dcram")),
         ""]
    seq = order[: a.top]
    L.append("-- ---- frame-level finding: executed functions in first-call order ----")
    L.append("UPSERT finding:ttd_f%d_frame_%s SET statement='Frame %d of TTD trace %s executed %d distinct tracked functions (%d calls); first-call order (top %d): %s', status='confirmed', confidence='high', date='%s', kind='ttd_frame', frame=%d, n_calls=%d, functions=[%s];"
             % (k, ts.replace("-", "_"), k, ts, len(order), F["n_calls"], len(seq), esc(" ".join(fn[f]["name"] for f in seq)), time.strftime("%Y-%m-%d"), k, F["n_calls"], ",".join("'%s'" % fn[f]["name"] for f in seq)))
    L.append("RELATE finding:ttd_f%d_frame_%s->cites:ttd_f%d_frame_src->source:%s;" % (k, ts.replace("-", "_"), k, src))
    for f in seq[:64]:
        L.append("RELATE finding:ttd_f%d_frame_%s->about:ttd_f%d_frame_%s->steam_routine:%s;" % (k, ts.replace("-", "_"), k, fn[f]["name"], fn[f]["name"]))
    L.append("")
    L.append("-- ---- per-function READ SET findings (dynamic; blk offsets are blk-relative hex) ----")
    n = 0
    for f, d in fn.items():
        if not d["name"].startswith("FUN_") or not (d["reads"] or d["writes"] or d["dc"]):
            continue
        n += 1
        fid = "ttd_readset_%s" % d["name"]
        stmt = "In TTD frame %d (%s) %s%s read blk offsets [%s] and wrote [%s]%s (%d calls in frame)." % (
            k, ts, d["name"], (" (= SH4 %s, %s)" % (d["sh4"], d["conf"])) if d["sh4"] else "", compact(d["reads"]), compact(d["writes"]),
            (" and read DC-RAM pages [%s]" % ",".join("0x%x" % (0x0C000000 + p) for p in sorted(d["dc"])[:32])) if d["dc"] else "", d["ncalls"])
        L.append("UPSERT finding:%s SET statement='%s', status='confirmed', confidence='high', date='%s', kind='ttd_readset', frame=%d, trace='%s', blk_reads=[%s], blk_writes=[%s], dcram_pages=[%s], ncalls=%d;"
                 % (fid, esc(stmt), time.strftime("%Y-%m-%d"), k, ts, ",".join("'0x%x'" % o for o in sorted(d["reads"])[:400]), ",".join("'0x%x'" % o for o in sorted(d["writes"])[:400]),
                    ",".join("'0x%x'" % (0x0C000000 + p) for p in sorted(d["dc"])[:64]), d["ncalls"]))
        L.append("RELATE finding:%s->about:%s_about->steam_routine:%s;" % (fid, fid, d["name"]))
        L.append("RELATE finding:%s->cites:%s_src->source:%s;" % (fid, fid, src))
        L.append("UPDATE steam_routine:%s SET ttd_blk_reads=[%s], ttd_blk_writes=[%s], ttd_frames=array::union(ttd_frames ?? [], [%d]);"
                 % (d["name"], ",".join("'0x%x'" % o for o in sorted(d["reads"])[:400]), ",".join("'0x%x'" % o for o in sorted(d["writes"])[:400]), k))
    os.makedirs(os.path.dirname(a.seed), exist_ok=True)
    open(a.seed, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("[join] wrote seed %s (%d readset findings, %d statements)" % (a.seed, n, sum(1 for l in L if l.strip() and not l.startswith("--"))))

    if a.apply:
        apply_seed(a.seed)


def apply_seed(seed):
    if True:
        exp = os.path.join(MAPLE, "re_kb_data", "_exports")
        os.makedirs(exp, exist_ok=True)
        bk = os.path.join(exp, "re_kb_%s.surql" % time.strftime("%Y%m%d-%H%M%S"))
        req = urllib.request.Request("http://127.0.0.1:8001/export", data=b"{}", method="POST")
        for h, v in (("surreal-ns", "re"), ("surreal-db", "kb"), ("Content-Type", "application/json"), ("Accept", "application/octet-stream"),
                     ("Authorization", "Basic " + base64.b64encode(AUTH.encode()).decode())):
            req.add_header(h, v)
        with urllib.request.urlopen(req, timeout=300) as r:
            open(bk, "wb").write(r.read())
        print("[join] backup %s (%d bytes)" % (bk, os.path.getsize(bk)))
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        rc = subprocess.call([sys.executable, os.path.join("tools", "re_kb", "apply_seed.py"), os.path.relpath(seed, MAPLE)], cwd=MAPLE, env=env)
        print("[join] apply_seed.py exit %d" % rc)


if __name__ == "__main__":
    main()
