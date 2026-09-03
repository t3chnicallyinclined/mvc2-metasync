#!/usr/bin/env python3
"""match.py -- pair Steam x86-64 functions (steam_funcs.jsonl) with SH4 routines (sh4_funcs.jsonl).

    python match.py [--seeds seeds.json] [--no-seeds] [--out match_result.json]

Method (each round only touches still-unmatched functions):
  1. token overlap weighted by rarity (IDF over BOTH sides):
       c: exact constants (u32 immediates, float bit patterns, DC data addresses masked & 0x1FFFFFFF)
       b: blk offsets (SH4 side converted through blkmap; Steam side blk/G displacements AND bare
          immediates inside the blk range when the function touches blk at all)
       s: strings      d: struct displacements (SH4 side through the fighter delta ladder; low weight, capped)
     The SH4 token set of a routine is EXPANDED with the strong tokens of its small, rarely-called direct
     callees (<=200 insns, <=3 callers) because the recompile inlines those; the callee is then reported
     as 'inlined' into the same Steam function by the absorb pass (step 4).
  2. call-graph propagation: every accepted pair P emits 'k:P#i' (i-th distinct callee, from the front),
     'kl:P#-j' (from the back), 'ko:P' onto its callees on both sides, and 'r:P' onto its callers.
  3. mutual-best with margin + size-ratio sanity gate.
  4. absorb pass: an unmatched SH4 routine whose caller is matched to Steam function s, where s calls
     nothing matched to the routine and s's token set contains >=60% of the routine's strong tokens, is
     recorded as inlined into s (method 'inlined').
Ghidra "functions" with > MEGA_INSN instructions are switch blobs / mis-bounded and are excluded.
Confidence tiers: confirmed (seed, both sides read by a human) > high > medium > low.  Every non-seed
pair is INFERRED (fingerprint only).  The runner-up on each side is recorded for transparency.
"""
import sys, os, json, math, struct, collections, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
IMG_LO, IMG_HI = 0x140000000, 0x1440e8000
BLK_LO, BLK_HI = 0x3C66, 0x33B18
DOMW = {"c": 1.0, "b": 1.2, "s": 1.5, "d": 0.35, "k": 1.0, "kl": 0.8, "ko": 0.5, "r": 0.6, "sw": 1.0}
MIN_SCORE = 3.0
MARGIN = 1.15
MAX_ROUNDS = 30
RARE_DF = 160
MAX_PAIRS_PER_TOKEN = 20000
MEGA_INSN = 20000
D_CAP = 8.0
EXPAND_CALLEE_MAX_INSN = 200
EXPAND_CALLEE_MAX_CALLERS = 3


def is_dc(v):
    return (0x0C000000 <= v < 0x10000000) or (0x8C000000 <= v < 0x90000000) or (0xAC000000 <= v < 0xB0000000)


def f32bits(x):
    try:
        return struct.unpack("<I", struct.pack("<f", x))[0]
    except (OverflowError, struct.error):
        return None


def steam_tokens(f):
    T = set()
    touches_blk = bool(f["blk_offs"] or f["g_offs"])
    for v in f["imms"]:
        if IMG_LO <= v < IMG_HI:
            continue
        T.add(("c", v & 0x1FFFFFFF if is_dc(v) else v))
        if touches_blk and BLK_LO <= v < BLK_HI:
            T.add(("b", v))
    for x in f["floats"]:
        b = f32bits(x)
        if b is not None and b not in (0, 0x3f800000, 0x80000000):
            T.add(("c", b))
    for v in f["dcaddrs"]:
        T.add(("c", v & 0x1FFFFFFF))
    for v in f["blk_offs"] + f["g_offs"]:
        T.add(("b", v))
    for s in f["strings"]:
        T.add(("s", s))
    for v in f["disps"]:
        if 0x10 <= v < 0x10000:
            T.add(("d", v))
    return T


def sh4_tokens(f):
    T = set()
    for v in f["consts"]:
        if v < 0x100 or v in (0x3f800000,):
            continue
        T.add(("c", v & 0x1FFFFFFF if is_dc(v) else v))
    for v in f["dcaddrs"]:
        T.add(("c", v & 0x1FFFFFFF))
    for v in f["woffs"]:
        if v >= 0x100:
            T.add(("c", v))
    for v in f["blk_offs"]:
        T.add(("b", v))
    for s in f["strings"]:
        T.add(("s", s))
    for v in set(f["disps"]) | set(f["disps_steam"]):
        if 0x10 <= v < 0x10000:
            T.add(("d", v))
    return T


def tokstr(t):
    d, v = t
    return "%s:%x" % (d, v) if isinstance(v, int) else "%s:%s" % (d, v)


STRONG = ("c", "b", "s", "k", "kl", "sw")


class Side:
    def __init__(self, funcs, key, tokfn):
        self.funcs = {f[key]: f for f in funcs}
        self.tok = {k: tokfn(f) for k, f in self.funcs.items()}
        self.own = {k: set(T) for k, T in self.tok.items()}
        self.callees = {k: list(f["callees"]) for k, f in self.funcs.items()}
        self.callers = collections.defaultdict(set)
        for k, cs in self.callees.items():
            for c in set(cs):
                self.callers[c].add(k)
        self.ninsn = {k: f["ninsn"] for k, f in self.funcs.items()}
        self.excluded = {k for k, n in self.ninsn.items() if n > MEGA_INSN}

    def expand_with_callees(self):
        """SH4 side: add strong tokens of small, rarely-called callees (inlining candidates)."""
        self.expanded_from = collections.defaultdict(set)
        for k in list(self.tok):
            for c in set(self.callees[k]):
                if c == k or c not in self.tok:
                    continue
                if self.ninsn[c] <= EXPAND_CALLEE_MAX_INSN and len(self.callers[c]) <= EXPAND_CALLEE_MAX_CALLERS:
                    add = {t for t in self.own[c] if t[0] in ("c", "b", "s")}
                    if add:
                        self.tok[k] |= add
                        self.expanded_from[k].add(c)


def build_df(S_tok, D_tok):
    dfs = collections.Counter()
    for T in S_tok.values():
        dfs.update(T)
    dfd = collections.Counter()
    for T in D_tok.values():
        dfd.update(T)
    return dfs, dfd


def score_pair(common, weight):
    sc = 0.0
    dsc = 0.0
    for t in common:
        w = weight.get(t, 0.0)
        if t[0] == "d":
            dsc += w
        else:
            sc += w
    return sc + min(dsc, D_CAP)


def one_round(S, D, S_tok, D_tok, tag, min_score=MIN_SCORE, margin=MARGIN):
    dfs, dfd = build_df(S_tok, D_tok)
    N = len(S_tok) + len(D_tok)
    weight = {t: math.log(N / (dfs[t] + dfd[t])) * DOMW[t[0]] for t in set(dfs) & set(dfd)}
    inv_s = collections.defaultdict(list)
    for k, T in S_tok.items():
        for t in T:
            if t in weight and (dfs[t] + dfd[t] <= RARE_DF or t[0] in ("k", "kl", "r", "ko", "sw")):
                inv_s[t].append(k)
    inv_d = collections.defaultdict(list)
    for k, T in D_tok.items():
        for t in T:
            if t in inv_s:
                inv_d[t].append(k)
    cand = set()
    for t, ds in inv_d.items():
        ss = inv_s[t]
        if len(ss) * len(ds) > MAX_PAIRS_PER_TOKEN:
            continue
        for s in ss:
            for d in ds:
                cand.add((s, d))
    scores, shared = {}, {}
    for (s, d) in cand:
        common = S_tok[s] & D_tok[d]
        sc = score_pair(common, weight)
        ns, nd = S.ninsn.get(s, 1) or 1, D.ninsn.get(d, 1) or 1
        ratio = ns / nd
        if ratio < 0.2 or ratio > 12:
            sc *= 0.5
        scores[(s, d)] = sc
        shared[(s, d)] = common
    best_s, best_d = {}, {}
    for (s, d), sc in scores.items():
        b = best_s.get(s)
        if b is None or sc > b[0]:
            best_s[s] = (sc, d, b[0] if b else 0.0, b[1] if b else None)
        elif sc > b[2]:
            best_s[s] = (b[0], b[1], sc, d)
        b = best_d.get(d)
        if b is None or sc > b[0]:
            best_d[d] = (sc, s, b[0] if b else 0.0, b[1] if b else None)
        elif sc > b[2]:
            best_d[d] = (b[0], b[1], sc, s)
    accepted = []
    for s, (sc, d, sc2, d2) in best_s.items():
        if sc < min_score:
            continue
        bd = best_d.get(d)
        if bd is None or bd[1] != s:
            continue
        if sc < margin * sc2 or sc < margin * bd[2]:
            continue
        common = shared[(s, d)]
        strong = [t for t in common if t[0] in STRONG]
        nstrong = len(strong)
        # evidence gate: a single ordinal/graph token or a single common constant cannot carry a pair
        specific = [t for t in common if t[0] in ("c", "b", "s") and weight[t] >= 6.5]
        graph_src = {t[1].split("#")[0] for t in common if t[0] in ("k", "kl", "ko", "r", "sw")}
        has_front = any(t[0] == "k" for t in common)
        has_sw = any(t[0] == "sw" for t in common)
        if not (len(specific) >= 2 or (len(specific) >= 1 and graph_src) or len(graph_src) >= 2
                or (has_front and sc >= 9.0 and len(graph_src) >= 1 and nstrong >= 2)
                or (has_sw and sc >= 9.0)):
            continue
        marg = min(sc / max(sc2, 0.01), sc / max(bd[2], 0.01))
        if sc >= 20 and nstrong >= 3 and marg >= 1.3:
            tier = "high"
        elif sc >= 8 and nstrong >= 2 and marg >= 1.2:
            tier = "medium"
        else:
            tier = "low"
        ev = sorted(((weight[t], tokstr(t)) for t in common), reverse=True)
        evs = " ".join("%s(%.1f)" % (n, w) for w, n in ev[:8])
        runner = "runner-up: sh4 %s(%.1f) / steam %s(%.1f)" % (
            ("0x%x" % d2) if d2 else "-", sc2, ("0x%x" % bd[3]) if bd[3] else "-", bd[2])
        accepted.append((s, d, tier, tag, evs, sc, runner, strong))
    return accepted


def run(S, D, seeds, log=print):
    matched_s = {}   # steam -> dict
    matched_d = {}   # sh4 -> steam
    pair_id = {}
    inlined = []     # (steam, sh4, tier, method, evidence)

    def add_graph_tokens(sa, dp):
        P = pair_id[(sa, dp)]
        for side, k in ((S, sa), (D, dp)):
            seen = []
            for c in side.callees[k]:
                if c not in seen and c != k:
                    seen.append(c)
            n = len(seen)
            for i, c in enumerate(seen):
                if c in side.tok:
                    side.tok[c].add(("k", "%d#%d" % (P, i)))
                    side.tok[c].add(("kl", "%d#-%d" % (P, n - i)))
                    side.tok[c].add(("ko", str(P)))
            for c in side.callers.get(k, ()):
                if c in side.tok:
                    side.tok[c].add(("r", str(P)))

    for sa, dp, note, inl in seeds:
        if sa in S.funcs and dp in D.funcs:
            matched_s[sa] = {"sh4": dp, "tier": "confirmed", "method": "seed", "evidence": note, "score": 999.0,
                             "runner": ""}
            matched_d[dp] = sa
            pair_id[(sa, dp)] = len(pair_id)
            add_graph_tokens(sa, dp)
            for ip, inote in inl:
                if ip in D.funcs:
                    inlined.append((sa, ip, "confirmed", "seed-inlined", inote))
                    matched_d[ip] = sa
        else:
            log("seed not found:", hex(sa), hex(dp))

    def sandwich_tokens():
        """call-sequence alignment: between two matched callee anchors, 1:1 unmatched callees pair up"""
        sw_s, sw_d = collections.defaultdict(set), collections.defaultdict(set)
        for (sa, dp), P in pair_id.items():
            seqS, seqD = [], []
            for c in S.callees[sa]:
                if c not in seqS and c != sa and c in S.tok:
                    seqS.append(c)
            for c in D.callees[dp]:
                if c not in seqD and c != dp and c in D.tok:
                    seqD.append(c)
            # anchors: monotonic matched pairs
            anchors = []
            j0 = 0
            for i, c in enumerate(seqS):
                m = matched_s.get(c)
                if m is None:
                    continue
                if m["sh4"] in seqD[j0:]:
                    j = seqD.index(m["sh4"], j0)
                    anchors.append((i, j))
                    j0 = j + 1
            bounds = [(-1, -1)] + anchors + [(len(seqS), len(seqD))]
            for g in range(len(bounds) - 1):
                (i0, j0_), (i1, j1) = bounds[g], bounds[g + 1]
                gapS = [c for c in seqS[i0 + 1:i1] if c not in matched_s]
                gapD = [c for c in seqD[j0_ + 1:j1] if c not in matched_d]
                if gapS and len(gapS) == len(gapD):
                    for k, (cs, cd) in enumerate(zip(gapS, gapD)):
                        tok = ("sw", "%d#%d#%d" % (P, g, k))
                        sw_s[cs].add(tok)
                        sw_d[cd].add(tok)
        return sw_s, sw_d

    rnd = 0
    while rnd < MAX_ROUNDS:
        rnd += 1
        sw_s, sw_d = sandwich_tokens()
        S_tok = {k: (T | sw_s.get(k, set())) for k, T in S.tok.items() if k not in matched_s and k not in S.excluded}
        D_tok = {k: (T | sw_d.get(k, set())) for k, T in D.tok.items() if k not in matched_d and k not in D.excluded}
        acc = one_round(S, D, S_tok, D_tok, "fingerprint" if rnd == 1 else "fingerprint+callgraph")
        if not acc:
            break
        for s, d, tier, tag, ev, sc, runner, strong in acc:
            matched_s[s] = {"sh4": d, "tier": tier, "method": tag, "evidence": ev, "score": sc, "runner": runner}
            matched_d[d] = s
            pair_id[(s, d)] = len(pair_id)
            add_graph_tokens(s, d)
        log("round %d: +%d pairs (total %d)" % (rnd, len(acc), len(matched_s)))

    # absorb pass: inlined SH4 leaves
    dfs, dfd = build_df(S.tok, D.tok)
    N = len(S.tok) + len(D.tok)
    weight = {t: math.log(N / (dfs[t] + dfd[t])) * DOMW[t[0]] for t in set(dfs) & set(dfd)}
    for d in D.tok:
        if d in matched_d or d in D.excluded or D.ninsn[d] > 400:
            continue
        cands = set()
        for c in D.callers.get(d, ()):
            if c in matched_d:
                cands.add(matched_d[c])
        for c in set(D.callees[d]):
            if c in matched_d:
                cands.add(matched_d[c])
        strong_d = [t for t in D.own[d] if t[0] in ("c", "b", "s") and t in weight]
        if not strong_d:
            continue
        tot = sum(weight[t] for t in strong_d)
        best = None
        for s in cands:
            if any(matched_s.get(c, {}).get("sh4") == d for c in S.callees[s]):
                continue
            common = [t for t in strong_d if t in S.own[s]]
            cov = sum(weight[t] for t in common) / tot if tot else 0
            if cov >= 0.6 and len(common) >= 1 and (best is None or cov > best[0]):
                best = (cov, s, common)
        if best:
            cov, s, common = best
            tier = "medium" if (cov >= 0.85 and len(common) >= 3) else "low"
            ev = "inlined into %s (covers %.0f%% of strong tokens): " % (S.funcs[s]["name"], cov * 100) + \
                 " ".join(sorted(tokstr(t) for t in common)[:8])
            inlined.append((s, d, tier, "inlined", ev))
            matched_d[d] = s
    log("absorb pass: +%d inlined routines" % len(inlined))
    return matched_s, inlined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default=os.path.join(HERE, "seeds.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "match_result.json"))
    ap.add_argument("--no-seeds", action="store_true")
    a = ap.parse_args()
    steam = [json.loads(l) for l in open(os.path.join(HERE, "steam_funcs.jsonl"), encoding="utf-8")]
    sh4 = [json.loads(l) for l in open(os.path.join(HERE, "sh4_funcs.jsonl"), encoding="utf-8")]
    S = Side(steam, "addr", steam_tokens)
    D = Side(sh4, "pc", sh4_tokens)
    D.expand_with_callees()
    print("excluded mega functions: steam", ["%s(%d)" % (S.funcs[k]["name"], S.ninsn[k]) for k in sorted(S.excluded)],
          "sh4", ["0x%x(%d)" % (k, D.ninsn[k]) for k in sorted(D.excluded)])
    seeds = []
    if not a.no_seeds and os.path.exists(a.seeds):
        for e in json.load(open(a.seeds, encoding="utf-8")):
            inl = [(int(x["sh4"], 16), x.get("note", "")) for x in e.get("inlined", [])]
            seeds.append((int(e["steam"], 16), int(e["sh4"], 16), e.get("note", ""), inl))
    res, inlined = run(S, D, seeds)
    out = []
    for s, m in sorted(res.items()):
        d = m["sh4"]
        out.append({"steam": "0x%x" % s, "steam_name": S.funcs[s]["name"], "sh4": "0x%x" % d,
                    "sh4_label": D.funcs[d]["label"], "bank": D.funcs[d]["bank"], "confidence": m["tier"],
                    "method": m["method"], "evidence": m["evidence"], "score": round(m["score"], 2),
                    "runner_up": m["runner"], "steam_ninsn": S.ninsn[s], "sh4_ninsn": D.ninsn[d]})
    for s, d, tier, method, ev in inlined:
        out.append({"steam": "0x%x" % s, "steam_name": S.funcs[s]["name"], "sh4": "0x%x" % d,
                    "sh4_label": D.funcs[d]["label"], "bank": D.funcs[d]["bank"], "confidence": tier,
                    "method": method, "evidence": ev, "score": 0, "runner_up": "", "steam_ninsn": S.ninsn[s],
                    "sh4_ninsn": D.ninsn[d]})
    json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)
    tiers = collections.Counter(o["confidence"] for o in out)
    game = sum(1 for f in steam if 0x140600000 <= f["addr"] < 0x1408e0000)
    print("rows:", len(out), dict(tiers), "| distinct steam:", len(set(o["steam"] for o in out)),
          "| steam game-range funcs:", game, "| sh4 funcs:", len(sh4))


if __name__ == "__main__":
    main()
