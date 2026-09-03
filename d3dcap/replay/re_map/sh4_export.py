#!/usr/bin/env python3
"""sh4_export.py -- per-function fingerprints from the marvelous2 SH4 disassembly.

    python sh4_export.py            # writes sh4_funcs.jsonl next to this script

Input: C:/Users/trist/projects/_marv_re/build/bank*.asm (+ memory/work.asm, memory/pl_mem.asm for #symbol).
`loc_8cXXXXXX` label == PC.  Function boundaries: a label that follows a `;=====` separator, is a
`bsr` target, or is a code label held in a literal pool (function pointer) and sits at a
"clean" boundary (after rts/jmp/bra delay slot, a pool, or a separator).  Everything up to the next
function start belongs to the function; literal-pool values are attributed by REFERENCE
(`mov.l/mov.w/mova @(label,PC)`), not by textual position.

Fingerprint fields (per function; same domains as steam_funcs.jsonl):
  pc, bank, label, ninsn, end
  callees    : bsr targets + code pointers loaded from the pool (jsr targets) + out-of-function bra
  consts     : 32-bit literal-pool values (u32) EXCLUDING code pointers / in-block globals
  woffs      : 16-bit pool values (mov.w) -- struct or block offsets
  floats     : pool values that were consumed through `mova ... fmov @r0` (bit patterns, as u32)
  blk_offs   : in-block global accesses converted to Steam blk offsets (GameGlobalPointer+off idiom,
               absolute 0x8C26xxxx pool addresses, +disp)
  blk_reads / blk_writes : the same, split by direction
  dcaddrs    : DC data addresses outside the block (masked & 0x1FFFFFFF), e.g. 0x0D82D000 files
  dcglobals  : out-of-block 0x8C1/0x8C2/0x8C3 globals (raw)
  strings    : "..." pool strings
  disps      : @(disp,Rn) displacements and mov.w offsets used with non-G registers (struct fields)
  disps_steam: disps mapped through the fighter-field delta ladder (INFERRED for non-fighter structs)
"""
import os, re, json, glob, struct
from blkmap import dc_to_blk, gg_off_to_blk, dc_field_to_steam, GG_START

BUILD = r"C:/Users/trist/projects/_marv_re/build"
MEM = r"C:/Users/trist/projects/_marv_re/memory"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "sh4_funcs.jsonl")

LBL = re.compile(r"^(loc_8[cC][0-9a-fA-F]{6}):")
SEP = re.compile(r"^;=====")
POOLREF = re.compile(r"@\((loc_8[cC][0-9a-fA-F]{6}),PC\)")
DISPREF = re.compile(r"@\((0x[0-9a-fA-F]+),(r\d+)\)")
IDXREF = re.compile(r"@\(r0,(r\d+)\)")
INDREF = re.compile(r"@(r\d+)")
CALLER_SAVED = {"r0", "r1", "r2", "r3", "r4", "r5", "r6", "r7"}


def load_symbols():
    syms = {}
    for fn in ("work.asm", "pl_mem.asm"):
        with open(os.path.join(MEM, fn), "r", errors="replace") as f:
            for ln in f:
                m = re.match(r"^#symbol\s+(\S+)\s+(0x[0-9a-fA-F]+)", ln.strip())
                if m:
                    syms[m.group(1).lower()] = int(m.group(2), 16)
    return syms


def parse_banks():
    """returns list of (bank, lines) and global label tables."""
    banks = []
    for f in sorted(glob.glob(os.path.join(BUILD, "bank*.asm"))):
        bank = os.path.basename(f).replace(".asm", "")
        with open(f, "r", errors="replace") as fh:
            banks.append((bank, fh.read().split("\n")))
    return banks


def main():
    syms = load_symbols()
    banks = parse_banks()
    # pass 1: labels, pool data, code/data classification
    label_pos = {}     # label -> (bank_idx, line_idx)
    pool = {}          # data label -> list of raw tokens
    is_code = {}       # label -> bool
    for bi, (bank, lines) in enumerate(banks):
        i = 0
        n = len(lines)
        while i < n:
            s = lines[i].strip()
            m = LBL.match(s)
            if m:
                lbl = m.group(1).lower()
                label_pos[lbl] = (bi, i)
                # look at next non-empty, non-comment line
                j = i + 1
                while j < n and (lines[j].strip() == "" or lines[j].strip().startswith(";")):
                    j += 1
                nxt = lines[j].strip() if j < n else ""
                if nxt.startswith("#data"):
                    toks = nxt[5:].strip()
                    # strings keep quotes; else split by whitespace
                    if toks.startswith('"'):
                        pool[lbl] = [toks]
                    else:
                        pool[lbl] = toks.split()
                    is_code[lbl] = False
                elif nxt.startswith("#align") or nxt == "":
                    is_code[lbl] = False
                else:
                    is_code[lbl] = True
            i += 1

    def resolve_data(tok):
        """pool token -> ('code', label) | ('sym', addr) | ('num', u32) | ('str', s) | ('datalbl', label) | ('unk', tok)"""
        t = tok.strip()
        if t.startswith('"'):
            return ("str", t.strip('"'))
        m = re.match(r"^(?:bank[0-9a-fA-F]+\.)?(loc_8[cC][0-9a-fA-F]{6})$", t)
        if m:
            l = m.group(1).lower()
            if is_code.get(l, False):
                return ("code", l)
            return ("datalbl", l)
        m = re.match(r"^(?:work|pl_mem)\.(\w+)$", t)
        if m:
            a = syms.get(m.group(1).lower())
            return ("sym", a) if a is not None else ("unk", t)
        m = re.match(r"^-?0x[0-9a-fA-F]+$", t)
        if m:
            v = int(t, 16) & 0xFFFFFFFF
            return ("num", v)
        return ("unk", t)

    # pass 2: function starts
    starts = set()
    bsr_targets = set()
    ptr_targets = set()
    for bi, (bank, lines) in enumerate(banks):
        for i, ln in enumerate(lines):
            s = ln.split(";")[0].strip()
            if not s:
                continue
            if SEP.match(ln.strip()):
                j = i + 1
                while j < len(lines) and (lines[j].strip() == "" or lines[j].strip().startswith(";")):
                    j += 1
                if j < len(lines):
                    m = LBL.match(lines[j].strip())
                    if m and is_code.get(m.group(1).lower()):
                        starts.add(m.group(1).lower())
            m = re.match(r"^bsr\s+(?:bank[0-9a-fA-F]+\.)?(loc_8[cC][0-9a-fA-F]{6})", s)
            if m:
                bsr_targets.add(m.group(1).lower())
    for lbl, toks in pool.items():
        for t in toks:
            k, v = resolve_data(t)
            if k == "code":
                ptr_targets.add(v)
    starts |= bsr_targets

    def clean_boundary(lbl):
        bi, li = label_pos[lbl]
        lines = banks[bi][1]
        # previous 3 non-empty lines
        prev = []
        j = li - 1
        while j >= 0 and len(prev) < 3:
            s = lines[j].strip()
            if s:
                prev.append(s)
            j -= 1
        if not prev:
            return True
        p0 = prev[0].split(";")[0].strip()
        if p0.startswith("#data") or p0.startswith("#align") or prev[0].startswith(";") or LBL.match(p0):
            return True
        if len(prev) > 1:
            p1 = prev[1].split(";")[0].strip()
            if re.match(r"^(rts|jmp|bra|rte)\b", p1):
                return True
        return False

    for l in ptr_targets:
        if l in label_pos and clean_boundary(l):
            starts.add(l)

    # pass 3: per-bank ordered label list -> function extents
    funcs = []
    for bi, (bank, lines) in enumerate(banks):
        fstarts = sorted([(label_pos[l][1], l) for l in starts if label_pos.get(l, (None,))[0] == bi])
        for k, (li, lbl) in enumerate(fstarts):
            end_li = fstarts[k + 1][0] if k + 1 < len(fstarts) else len(lines)
            funcs.append((bank, lbl, bi, li, end_li))

    out = open(OUT, "w", encoding="utf-8")
    nfun = 0
    for bank, lbl, bi, li, end_li in funcs:
        lines = banks[bi][1]
        pc = int(lbl[4:], 16)
        fp = {"pc": pc, "label": lbl, "bank": bank, "callees": [], "consts": [], "woffs": [], "floats": [],
              "blk_offs": [], "blk_reads": [], "blk_writes": [], "dcaddrs": [], "dcglobals": [], "strings": [],
              "disps": [], "disps_steam": [], "ninsn": 0, "end": None, "poolptrs": [], "dcabs": []}
        taint = {}   # reg -> ("GPP",) | ("G",) | ("ABS", addr) | ("K", value)

        def rec_dc(a, is_write=None):
            """record an in-block DC absolute address (and its Steam blk offset); out-of-block -> dcglobals"""
            bo = dc_to_blk(a) if 0x8C000000 <= a < 0x8D000000 else None
            if bo is None:
                if 0x8C000000 <= a < 0x8D000000:
                    fp["dcglobals"].append(a)
                return False
            fp["blk_offs"].append(bo)
            fp["dcabs"].append(a)
            if is_write is True:
                fp["blk_writes"].append(bo)
            elif is_write is False:
                fp["blk_reads"].append(bo)
            return True
        last_pc = pc
        for i in range(li, end_li):
            raw = lines[i]
            s = raw.split(";")[0].strip()
            if not s:
                continue
            m = LBL.match(s)
            if m:
                last_pc = int(m.group(1)[4:], 16)
                continue
            if s.startswith("#"):
                continue
            fp["ninsn"] += 1
            parts = s.split(None, 1)
            op = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            opnds = [a.strip() for a in re.split(r",(?![^()]*\))", args)] if args else []
            dst = opnds[-1] if opnds else None
            # ---- calls / branches
            if op == "bsr":
                mm = re.match(r"^(?:bank[0-9a-fA-F]+\.)?(loc_8[cC][0-9a-fA-F]{6})", args)
                if mm:
                    fp["callees"].append(int(mm.group(1)[4:], 16))
                for r in CALLER_SAVED:
                    taint.pop(r, None)
                continue
            if op == "bra":
                mm = re.match(r"^(?:bank[0-9a-fA-F]+\.)?(loc_8[cC][0-9a-fA-F]{6})", args)
                if mm:
                    t = mm.group(1).lower()
                    if t in starts and t != lbl:
                        fp["callees"].append(int(t[4:], 16))
                continue
            if op in ("jsr", "jmp"):
                mm = INDREF.match(args)
                if mm:
                    t = taint.get(mm.group(1))
                    if t and t[0] == "CODE":
                        fp["callees"].append(t[1])
                if op == "jsr":
                    for r in CALLER_SAVED:
                        taint.pop(r, None)
                continue
            # ---- pool references
            pm = POOLREF.search(args)
            if pm:
                plbl = pm.group(1).lower()
                toks = pool.get(plbl, [])
                vals = [resolve_data(t) for t in toks]
                first = vals[0] if vals else ("unk", None)
                if op == "mova":
                    # r0 = address of pool entry; typical consumer fmov @r0 (float const) or a table
                    for k, v in vals:
                        if k == "num":
                            fp["floats"].append(v)
                            fp["consts"].append(v)
                    taint["r0"] = ("POOLADDR", plbl)
                    continue
                k, v = first
                if op == "mov.w":
                    if k == "num":
                        v &= 0xFFFF
                        if v >= 0x8000:
                            v -= 0x10000
                        fp["woffs"].append(v & 0xFFFF)
                        if dst:
                            taint[dst] = ("K", v)
                    continue
                # mov.l
                if k == "code":
                    fp["callees"].append(int(v[4:], 16))
                    fp["poolptrs"].append(int(v[4:], 16))
                    if dst:
                        taint[dst] = ("CODE", int(v[4:], 16))
                elif k == "datalbl":
                    fp["consts"].append(int(v[4:], 16))
                    if dst:
                        taint[dst] = ("ABS", int(v[4:], 16))
                elif k == "str":
                    fp["strings"].append(v)
                elif k == "sym":
                    if v == 0x8C26823C:  # GameGlobalPointer
                        if dst:
                            taint[dst] = ("GPP",)
                    else:
                        if not rec_dc(v):
                            if 0x0C000000 <= v < 0x10000000 or 0x8D000000 <= v < 0x90000000:
                                fp["dcaddrs"].append(v & 0x1FFFFFFF)
                        if dst:
                            taint[dst] = ("ABS", v)
                elif k == "num":
                    if v == 0x8C26823C:
                        if dst:
                            taint[dst] = ("GPP",)
                        continue
                    if 0x8C000000 <= v < 0x8D000000:
                        rec_dc(v)
                        if dst:
                            taint[dst] = ("ABS", v)
                    elif 0xAC000000 <= v < 0xAD000000:
                        fp["dcglobals"].append(v)
                        if dst:
                            taint[dst] = ("ABS", v)
                    elif (0x0C000000 <= v < 0x10000000) or (0x8C000000 <= v < 0x90000000) or (0xAC000000 <= v < 0xB0000000):
                        fp["dcaddrs"].append(v & 0x1FFFFFFF)
                        fp["consts"].append(v)
                        if dst:
                            taint[dst] = ("ABS", v)
                    else:
                        fp["consts"].append(v)
                        if dst:
                            taint[dst] = ("K", v)
                continue
            # ---- memory operands: G-relative / absolute globals / struct disps
            if op.startswith("mov") or op.startswith("fmov"):
                is_write = dst is not None and dst.startswith("@")
                for o in opnds:
                    if not o.startswith("@"):
                        continue
                    base = None; off = 0; kind = None
                    mm = DISPREF.match(o)
                    if mm:
                        off = int(mm.group(1), 16); base = mm.group(2); kind = "disp"
                    else:
                        mm = IDXREF.match(o)
                        if mm:
                            base = mm.group(1); kind = "idx"
                            t0 = taint.get("r0")
                            off = t0[1] if t0 and t0[0] == "K" else None
                        else:
                            mm = re.match(r"^@(r\d+)$", o)
                            if mm:
                                base = mm.group(1); kind = "ind"; off = 0
                    if base is None:
                        continue
                    t = taint.get(base)
                    tb = taint.get("r0") if kind == "idx" else None
                    # @(r0,rN) with r0 = G and rN = K, or rN = G and r0 = K
                    if kind == "idx" and t and t[0] == "K" and tb and tb[0] in ("G", "BLK", "ABS"):
                        t, off = tb, t[1]
                    if t and t[0] == "G" and off is not None:
                        rec_dc(GG_START + off, is_write)
                        continue
                    if t and t[0] == "ABS" and off is not None:
                        rec_dc(t[1] + off, is_write)
                        continue
                    if kind == "disp" and off >= 4 and base not in ("r15",):
                        fp["disps"].append(off)
                    elif kind == "idx" and off is not None and off >= 4 and base not in ("r15",):
                        fp["disps"].append(off)
                # taint propagation for the destination register
                if dst and re.match(r"^r\d+$", dst):
                    src = opnds[0] if len(opnds) > 1 else None
                    newt = None
                    if src == "@" + "r15+" or src is None:
                        newt = None
                    elif src and src.startswith("@"):
                        mm = re.match(r"^@(r\d+)$", src)
                        mm2 = DISPREF.match(src)
                        b = mm.group(1) if mm else (mm2.group(2) if mm2 else None)
                        d = 0 if mm else (int(mm2.group(1), 16) if mm2 else 0)
                        t = taint.get(b) if b else None
                        if t and t[0] == "GPP" and d == 0:
                            newt = ("G",)
                    elif src and re.match(r"^r\d+$", src):
                        newt = taint.get(src)
                    elif src and re.match(r"^-?0x[0-9a-fA-F]+$", src) and op == "mov":
                        v = int(src, 16)
                        if v >= 0x80:
                            v -= 0x100
                        newt = ("K", v)
                    if newt:
                        taint[dst] = newt
                    else:
                        taint.pop(dst, None)
                continue
            # other ALU ops: invalidate destination register
            if dst and re.match(r"^r\d+$", dst):
                if op == "add" and len(opnds) == 2 and re.match(r"^-?0x", opnds[0]):
                    t = taint.get(dst)
                    v = int(opnds[0], 16)
                    if v >= 0x80:
                        v -= 0x100
                    if t and t[0] in ("ABS", "K"):
                        taint[dst] = (t[0], t[1] + v)
                    else:
                        taint.pop(dst, None)
                elif op == "add" and len(opnds) == 2 and re.match(r"^r\d+$", opnds[0]):
                    t = taint.get(dst); u = taint.get(opnds[0])
                    if t and u and t[0] == "K" and u[0] == "ABS":
                        taint[dst] = ("ABS", u[1] + t[1])
                    elif t and u and u[0] == "K" and t[0] == "ABS":
                        taint[dst] = ("ABS", t[1] + u[1])
                    elif t and u and t[0] == "K" and u[0] == "G":
                        taint[dst] = ("ABS", GG_START + t[1])
                    elif t and u and u[0] == "K" and t[0] == "G":
                        taint[dst] = ("ABS", GG_START + u[1])
                    else:
                        taint.pop(dst, None)
                else:
                    taint.pop(dst, None)
        fp["end"] = last_pc
        for k in ("consts", "woffs", "floats", "blk_offs", "blk_reads", "blk_writes", "dcaddrs", "dcglobals",
                  "strings", "disps", "poolptrs", "dcabs"):
            fp[k] = sorted(set(fp[k]))
        fp["disps_steam"] = sorted(set(dc_field_to_steam(d) for d in fp["disps"]))
        if fp["ninsn"] == 0:
            continue
        out.write(json.dumps(fp) + "\n")
        nfun += 1
    out.close()
    print("functions:", nfun, "labels:", len(label_pos), "starts:", len(starts), "->", OUT)


if __name__ == "__main__":
    main()
