#!/usr/bin/env python3
"""ghidra_export.py -- dump EVERY function's disassembly from the GhidraMCP HTTP bridge (:8080)
into a local cache, then derive per-function fingerprints (steam_funcs.jsonl).

    python ghidra_export.py fetch      # hits the bridge; resumable; writes cache/steam_disasm.jsonl
    python ghidra_export.py finger     # offline; reads the cache + mvc_dump.bin; writes steam_funcs.jsonl

The Ghidra GUI holds the project lock, so everything goes through the bridge exactly as
docs/STAGE-DRAW-GHIDRA.md did: /list_functions, /disassemble_function, /get_function_by_address, /strings.
Nothing is written into the Ghidra project.

Fingerprint fields (per function):
  addr, name, size, ninsn
  callees        : direct CALL targets (list, in order, duplicates kept) + out-of-body JMP (tail calls)
  imms           : immediates >= 0x100 appearing as instruction operands (not displacements)
  floats         : f32 values loaded rip-relative by MOVSS/ADDSS/MULSS/... (read from mvc_dump.bin)
  doubles        : f64 values loaded rip-relative by *SD
  blk_offs       : displacements applied to a register that holds *DAT_142edf560 (blk)  [blk-relative]
  g_offs         : displacements applied to a register holding *DAT_142edf580 (G = blk+0x3CB8), stored
                   ALREADY CONVERTED to blk-relative (+0x3CB8) -- so blk_offs+g_offs is one domain
  dcaddrs        : immediates that look like DC addresses (0x0Cxxxxxx / 0x8Cxxxxxx / 0xACxxxxxx)
  strings        : string literals referenced rip-relative
  datarefs       : other rip-relative data addresses (DAT_ statics), as ints
  disps          : displacements >= 0x10 on non-blk registers (struct field offsets), as a set
"""
import sys, os, json, re, struct, time, urllib.request, concurrent.futures as cf

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
DISASM = os.path.join(CACHE, "steam_disasm.jsonl")
FUNCS_OUT = os.path.join(HERE, "steam_funcs.jsonl")
STRINGS = os.path.join(CACHE, "steam_strings.json")
DUMP = r"C:\Users\trist\ghidra_projects\mvc_dump.bin"
BASE = 0x140000000
BRIDGE = "http://localhost:8080/"
BLK_PTR = 0x142edf560
G_PTR = 0x142edf580
G_OFF = 0x3CB8


def get(path, timeout=60):
    with urllib.request.urlopen(BRIDGE + path, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def list_functions():
    out = []
    txt = get("list_functions?offset=0&limit=200000")
    for ln in txt.splitlines():
        m = re.match(r"^(.*) at ([0-9a-f]+)$", ln.strip())
        if m:
            out.append((int(m.group(2), 16), m.group(1)))
    out.sort()
    return out


def fetch_one(addr, name):
    err = None
    for attempt in range(5):
        try:
            hdr = get("get_function_by_address?address=0x%x" % addr)
            dis = get("disassemble_function?address=0x%x" % addr)
            m = re.search(r"Body: ([0-9a-f]+) - ([0-9a-f]+)", hdr)
            body = (int(m.group(1), 16), int(m.group(2), 16)) if m else (addr, addr)
            return {"addr": addr, "name": name, "body": body, "asm": dis}
        except Exception as e:
            err = e
            time.sleep(0.5 * (attempt + 1))
    return {"addr": addr, "name": name, "body": (addr, addr), "asm": "", "error": str(err)}


def cmd_fetch():
    os.makedirs(CACHE, exist_ok=True)
    funcs = list_functions()
    print("functions:", len(funcs))
    done = set()
    if os.path.exists(DISASM):
        with open(DISASM, "r", encoding="utf-8") as f:
            for ln in f:
                try:
                    done.add(json.loads(ln)["addr"])
                except Exception:
                    pass
    todo = [(a, n) for a, n in funcs if a not in done]
    print("already cached:", len(done), "todo:", len(todo))
    try:
        s = get("strings?offset=0&limit=200000")
        strs = {}
        for ln in s.splitlines():
            m = re.match(r'^([0-9a-f]+): "(.*)"$', ln.rstrip())
            if m:
                strs[int(m.group(1), 16)] = m.group(2)
        with open(STRINGS, "w", encoding="utf-8") as f:
            json.dump({("%x" % k): v for k, v in strs.items()}, f)
        print("strings:", len(strs))
    except Exception as e:
        print("strings fetch failed:", e)
    t0 = time.time()
    with open(DISASM, "a", encoding="utf-8") as out, cf.ThreadPoolExecutor(max_workers=3) as ex:
        for i, rec in enumerate(ex.map(lambda an: fetch_one(*an), todo)):
            out.write(json.dumps(rec) + "\n")
            if i % 500 == 0:
                out.flush()
                print("%d/%d  %.0fs" % (i, len(todo), time.time() - t0), flush=True)
    print("done")


# ---------------------------------------------------------------- fingerprints
INSN = re.compile(r"^([0-9a-f]+): (\S+)\s*(.*)$")
RIP_MEM = re.compile(r"\[(0x[0-9a-f]+)\]")
REG_MEM = re.compile(r"\[([A-Z0-9]+)(?: \+ ([A-Z0-9]+)\*0x[1248])? \+ (-?0x[0-9a-f]+)\]")
IMM = re.compile(r"(?<![\[\w])(-?0x[0-9a-f]+)(?![\]\w])")
FLOAT_OPS = {"MOVSS", "ADDSS", "SUBSS", "MULSS", "DIVSS", "COMISS", "UCOMISS", "MAXSS", "MINSS", "SQRTSS", "CMPSS"}
DOUBLE_OPS = {"MOVSD", "ADDSD", "SUBSD", "MULSD", "DIVSD", "COMISD", "UCOMISD", "MAXSD", "MINSD", "CVTSD2SS"}
REGTBL = {"EAX": "RAX", "AX": "RAX", "AL": "RAX", "AH": "RAX", "EBX": "RBX", "BX": "RBX", "BL": "RBX", "BH": "RBX",
          "ECX": "RCX", "CX": "RCX", "CL": "RCX", "CH": "RCX", "EDX": "RDX", "DX": "RDX", "DL": "RDX", "DH": "RDX",
          "ESI": "RSI", "SI": "RSI", "SIL": "RSI", "EDI": "RDI", "DI": "RDI", "DIL": "RDI",
          "EBP": "RBP", "BP": "RBP", "BPL": "RBP", "ESP": "RSP", "SP": "RSP", "SPL": "RSP"}


def canon(reg):
    r = reg.upper()
    m = re.match(r"^R(\d+)[DWB]$", r)
    if m:
        return "R" + m.group(1)
    return REGTBL.get(r, r)


def is_dcaddr(v):
    return (0x0C000000 <= v < 0x10000000) or (0x8C000000 <= v < 0x90000000) or (0xAC000000 <= v < 0xB0000000)


def fingerprint(rec, dump, strs):
    fp = {"addr": rec["addr"], "name": rec["name"], "body": rec["body"], "callees": [], "imms": [], "floats": [],
          "doubles": [], "blk_offs": [], "g_offs": [], "dcaddrs": [], "strings": [], "datarefs": [], "disps": [],
          "ninsn": 0, "blk_reads": [], "blk_writes": []}
    taint = {}  # reg -> "blk" | "G"
    b0, b1 = rec["body"]
    for ln in rec["asm"].splitlines():
        m = INSN.match(ln.strip())
        if not m:
            continue
        fp["ninsn"] += 1
        op, args = m.group(2), m.group(3)
        if op == "CALL":
            mm = re.match(r"^0x([0-9a-f]+)$", args.strip())
            if mm:
                fp["callees"].append(int(mm.group(1), 16))
            continue
        if op == "JMP":
            mm = re.match(r"^0x([0-9a-f]+)$", args.strip())
            if mm:
                t = int(mm.group(1), 16)
                if not (b0 <= t <= b1):
                    fp["callees"].append(t)  # tail call
            continue
        # rip-relative data refs
        for a in RIP_MEM.findall(args):
            v = int(a, 16)
            if v == BLK_PTR or v == G_PTR:
                continue
            if v in strs:
                fp["strings"].append(strs[v])
                continue
            fp["datarefs"].append(v)
            off = v - BASE
            if 0 <= off + 8 <= len(dump):
                if op in FLOAT_OPS or (op.startswith("CVT") and op.endswith("SS")):
                    fp["floats"].append(struct.unpack_from("<f", dump, off)[0])
                elif op in DOUBLE_OPS:
                    fp["doubles"].append(struct.unpack_from("<d", dump, off)[0])
        parts = args.split(",", 1)
        dst = parts[0].strip() if len(parts) == 2 else None
        dst_is_reg = bool(dst and re.match(r"^[A-Z0-9]+$", dst))
        # taint tracking of blk / G pointer registers
        if op.startswith("MOV") and dst_is_reg:
            src = parts[1]
            if "[0x142edf560]" in src:
                taint[canon(dst)] = "blk"
                continue
            if "[0x142edf580]" in src:
                taint[canon(dst)] = "G"
                continue
            mm = re.match(r"^\s*([A-Z0-9]+)\s*$", src)
            if mm and canon(mm.group(1)) in taint:
                taint[canon(dst)] = taint[canon(mm.group(1))]
                continue
            taint.pop(canon(dst), None)
        elif op == "LEA" and dst_is_reg:
            src = parts[1].strip()
            mm = REG_MEM.match(src)
            base_t = None
            if mm:
                b, idx, disp = mm.group(1), mm.group(2), int(mm.group(3), 16)
                for r in (b, idx):
                    if r and canon(r) in taint:
                        base_t = taint[canon(r)]
                if base_t == "blk":
                    fp["blk_offs"].append(disp)
                elif base_t == "G":
                    fp["g_offs"].append(disp + G_OFF)
            if base_t:
                taint[canon(dst)] = base_t
            else:
                taint.pop(canon(dst), None)
        elif dst_is_reg and op not in ("CMP", "TEST") and canon(dst) in taint:
            if not (op in ("ADD", "SUB") and re.match(r"^\s*0x[0-9a-f]+\s*$", parts[1])):
                taint.pop(canon(dst), None)
        elif op in ("XOR", "POP") and dst_is_reg:
            taint.pop(canon(dst), None)
        # memory operands with tainted base/index
        first_len = len(parts[0]) if len(parts) == 2 else len(args)
        for mm in REG_MEM.finditer(args):
            b, idx, disp = mm.group(1), mm.group(2), int(mm.group(3), 16)
            t = None
            for r in (b, idx):
                if r and canon(r) in taint:
                    t = taint[canon(r)]
            is_dst = mm.start() < first_len and op not in ("CMP", "TEST", "LEA", "PUSH") and not op.startswith("J")
            if t == "blk":
                fp["blk_offs"].append(disp)
                (fp["blk_writes"] if is_dst else fp["blk_reads"]).append(disp)
            elif t == "G":
                fp["g_offs"].append(disp + G_OFF)
                (fp["blk_writes"] if is_dst else fp["blk_reads"]).append(disp + G_OFF)
            elif disp >= 0x10 and canon(b) not in ("RSP", "RBP"):
                fp["disps"].append(disp)
        # immediates (operands not inside [])
        stripped = re.sub(r"\[[^\]]*\]", "[]", args)
        for a in IMM.findall(stripped):
            v = int(a, 16)
            if v < 0:
                v &= 0xFFFFFFFF
            if is_dcaddr(v):
                fp["dcaddrs"].append(v)
            if v >= 0x100:
                fp["imms"].append(v)
    for k in ("imms", "floats", "doubles", "blk_offs", "g_offs", "dcaddrs", "datarefs", "disps", "strings", "blk_reads", "blk_writes"):
        fp[k] = sorted(set(fp[k]))
    fp["size"] = b1 - b0 + 1
    return fp


def cmd_finger():
    with open(DUMP, "rb") as f:
        dump = f.read()
    strs = {}
    if os.path.exists(STRINGS):
        with open(STRINGS, "r", encoding="utf-8") as f:
            strs = {int(k, 16): v for k, v in json.load(f).items()}
    n = 0
    with open(DISASM, "r", encoding="utf-8") as f, open(FUNCS_OUT, "w", encoding="utf-8") as out:
        for ln in f:
            rec = json.loads(ln)
            if not rec.get("asm"):
                continue
            out.write(json.dumps(fingerprint(rec, dump, strs)) + "\n")
            n += 1
    print("fingerprinted", n, "->", FUNCS_OUT)


if __name__ == "__main__":
    {"fetch": cmd_fetch, "finger": cmd_finger}[sys.argv[1]]()
