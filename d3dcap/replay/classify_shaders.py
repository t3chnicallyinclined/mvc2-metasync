#!/usr/bin/env python3
"""Classify every captured shader by DISASSEMBLING it, and emit shader-map.json.

    python classify_shaders.py <frame_number>

Why this exists: the replayer's first attempt picked a shader variant from the SHAPE of what a draw
bound ("something in slot 1 means it is a character"). Measured on frame 4261 that selected 214 draws
spanning FIVE pixel shaders and THREE vertex shaders -- including the HUD bank and stage pages -- and
forced them all through the indexed-character path with a pass-through vertex shader. Draws whose VS
actually transforms by world x view-projection were treated as pre-transformed NDC, which puts their
geometry in the wrong place. Hence: classify from the bytecode, never from a heuristic.

Keyed by CONTENT HASH, never by the runtime ID3D11* pointer -- pointers are per-launch and a
checked-in map keyed on one would silently select the wrong shader on the next capture.

Classification rules, each read directly out of the fxc disassembly:
  VERTEX
    transforms  : declares a constant buffer (dcl_constantbuffer) -> world x viewProj  -> vs_world
    passthrough : declares none; positions are already in NDC                          -> vs_flat
  PIXEL
    indexed     : samples t1 as well as t0 -> index tile + palette lookup      -> fs_character
    ignoreTexA  : 'mov r0.w, l(1.000000)' after the sample = pp_IgnoreTexA,
                  i.e. texture alpha forced to 1                               -> fs_stage_opaque
    texalpha    : keeps the sampled alpha                                      -> fs_stage_texalpha
    (a shader with no fog constant buffer is the HUD; it shares fs_stage_texalpha's maths, so it is
     reported separately for visibility but mapped to the same entry point)
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")
FXC = glob.glob(r"C:\Program Files (x86)\Windows Kits\10\bin\*\x64\fxc.exe")


def sha8(b):
    return hashlib.sha256(b).hexdigest()[:16]


def disasm(path):
    if not FXC:
        sys.exit("fxc.exe not found in the Windows SDK")
    out = os.path.join(os.environ.get("TEMP", "."), "_dis.asm")
    subprocess.run([FXC[-1], "/nologo", "/dumpbin", path, "/Fc", out],
                   capture_output=True, check=False)
    return open(out, encoding="utf-8", errors="replace").read() if os.path.exists(out) else ""


def classify_vs(asm):
    # A vertex shader that declares no constant buffer cannot transform: its positions are already
    # in clip space. That is the character/HUD path.
    return "vs_world" if "dcl_constantbuffer" in asm else "vs_flat"


def classify_ps(asm):
    body = asm[asm.find("ps_5_0"):] if "ps_5_0" in asm else asm
    # ⚠ the real mnemonic is `sample_indexable(texture2d)(float,float,float,float) r0.xyz, ...` --
    # a '(' follows the opcode, not whitespace. An earlier `sample\w*\s` matched NOTHING, so every
    # shader fell through to the non-indexed branches and the palette path vanished from the map.
    # That contradicted what we already know from the flycast macro matrix and the captured 256x1
    # tables, which is what caught it.
    samples = [l for l in body.splitlines() if re.match(r"\s*sample", l)]
    uses_t1 = any(re.search(r"\bt1\b", s) for s in samples)
    has_fog = "cb2[" in body
    # A CLASS, not an entry point. The entry point also depends on which VERTEX shader the draw pairs
    # with, because WebGPU requires the fragment input signature to match the vertex output signature
    # and the two vertex shaders emit different varying counts. The replayer resolves (vs, class).
    if uses_t1:
        return "indexed", has_fog, "t0 index tile + t1 palette"
    if re.search(r"mov\s+r\d+\.w,\s*l\(1\.000000\)", body):
        return "opaque", has_fog, "IgnoreTexA (texture alpha forced to 1)"
    return "texalpha", has_fog, ("texture alpha kept" if has_fog else "texture alpha kept, NO FOG")


def main(frame):
    path = os.path.join(CAP, "frame_%s.ndjson" % frame)
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    draws = [r for r in rows if not r.get("kind", "").startswith("Clear")
             and r.get("retmod", "game") == "game"]
    scene = [d for d in draws if d.get("rt") and d["rt"]["w"] == 2048]

    out = {"vs": {}, "ps": {}}
    counts = {}

    for kind, key, pat in (("vs", "vs", "vs_%s.cso"), ("ps", "ps", "ps_%s.cso")):
        seen = {}
        for d in scene:
            ptr = d.get(key)
            if not ptr or ptr in seen:
                if ptr:
                    seen[ptr]["n"] += 1
                continue
            f = os.path.join(CAP, pat % ptr)
            if not os.path.exists(f):
                continue
            data = open(f, "rb").read()
            asm = disasm(f)
            if kind == "vs":
                variant, has_fog, note = classify_vs(asm), False, ""
            else:
                variant, has_fog, note = classify_ps(asm)
            seen[ptr] = {"hash": sha8(data), "variant": variant, "fog": has_fog,
                         "note": note, "n": 1}
        counts[kind] = seen
        for ptr, v in seen.items():
            out[kind][v["hash"]] = {"variant": v["variant"], "fog": v["fog"], "note": v["note"]}

    print("=" * 76)
    print("SHADER CLASSIFICATION — frame %s, %d scene draws" % (frame, len(scene)))
    print("=" * 76)
    for kind in ("vs", "ps"):
        print("\n%s (%d distinct):" % (kind.upper(), len(counts[kind])))
        for ptr, v in sorted(counts[kind].items(), key=lambda kv: -kv[1]["n"]):
            print("   %s  %-20s %5d draws   %s" % (v["hash"], v["variant"], v["n"], v["note"]))

    # Cross-check: how many draws land on each (vs,ps) variant pair?
    pair = {}
    for d in scene:
        v = counts["vs"].get(d.get("vs"), {}).get("variant", "?")
        p = counts["ps"].get(d.get("ps"), {}).get("variant", "?")
        pair[(v, p)] = pair.get((v, p), 0) + 1
    print("\nDRAWS BY (vertex, fragment) PAIR:")
    for (v, p), n in sorted(pair.items(), key=lambda kv: -kv[1]):
        flag = ""
        if p == "indexed" and v != "vs_flat":
            flag = "   <- indexed path on a TRANSFORMING vs (contradicts the flycast model)"
        print("   %-10s + %-20s %5d draws%s" % (v, p, n, flag))

    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shader-map.json")
    json.dump(out, open(dst, "w"), indent=1)
    print("\nwrote %s (%d VS, %d PS, keyed by content hash)"
          % (dst, len(out["vs"]), len(out["ps"])))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
