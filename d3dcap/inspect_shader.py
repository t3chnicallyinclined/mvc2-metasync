#!/usr/bin/env python3
"""Read a shader's REAL input signature out of its DXBC bytecode.

    python inspect_shader.py vs_00000000XXXXXXXX.cso

Parses the DXBC container's ISGN (input signature) and OSGN (output signature) chunks. The point:
an input layout DECLARES what is fed to the shader, but the signature says what the shader actually
CONSUMES -- including the per-component read mask. A declared field that the shader never reads may
legitimately contain uninitialised garbage (we observed NORMAL0 = (nan,nan) and denormal POSITION.w
in real sprite draws), and a port must not try to reproduce it.

DXBC layout: "DXBC" magic, 16-byte checksum, u32 1, u32 totalSize, u32 chunkCount, then chunkCount
u32 offsets. Each chunk: 4-char tag, u32 size, payload.
ISGN payload: u32 count, u32 8, then count * 24-byte elements:
    u32 nameOffset (relative to payload start), u32 semanticIndex, u32 systemValue,
    u32 componentType, u32 register, u8 mask, u8 readWriteMask, u16 pad
"""
import struct
import sys
import os

COMP = {1: "uint", 2: "int", 3: "float"}


def mask_str(m):
    return "".join(c for c, b in zip("xyzw", (1, 2, 4, 8)) if m & b) or "-"


def chunks(data):
    if data[:4] != b"DXBC":
        raise ValueError("not a DXBC container")
    count = struct.unpack_from("<I", data, 28)[0]
    offs = struct.unpack_from("<%dI" % count, data, 32)
    out = {}
    for o in offs:
        tag = data[o:o + 4].decode("ascii", "replace")
        size = struct.unpack_from("<I", data, o + 4)[0]
        out.setdefault(tag, data[o + 8: o + 8 + size])
    return out


def signature(payload):
    n, _ = struct.unpack_from("<II", payload, 0)
    rows = []
    for i in range(n):
        off = 8 + i * 24
        (nameOff, semIdx, sysVal, compType, reg, ) = struct.unpack_from("<IIIII", payload, off)
        mask, rwMask = struct.unpack_from("<BB", payload, off + 20)
        end = payload.index(b"\0", nameOff)
        name = payload[nameOff:end].decode("ascii", "replace")
        rows.append((name, semIdx, reg, mask, rwMask, compType, sysVal))
    return rows


def main(path):
    data = open(path, "rb").read()
    ch = chunks(data)
    print("=" * 74)
    print(os.path.basename(path), " %d bytes, chunks: %s" % (len(data), ", ".join(sorted(ch))))
    print("=" * 74)

    for tag, label in (("ISGN", "INPUTS  (what the shader actually consumes)"),
                       ("OSGN", "OUTPUTS")):
        if tag not in ch:
            continue
        print("\n[%s] %s" % (tag, label))
        print("    %-12s %-4s %-4s %-9s %-9s %s" % ("semantic", "idx", "reg", "declared", "READ", "type"))
        for name, semIdx, reg, mask, rw, ct, sv in signature(ch[tag]):
            note = ""
            if tag == "ISGN" and rw == 0:
                note = "   <- NEVER READ (may be uninitialised in the buffer)"
            print("    %-12s %-4d %-4d %-9s %-9s %-6s%s"
                  % (name, semIdx, reg, mask_str(mask), mask_str(rw), COMP.get(ct, ct), note))
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    p = sys.argv[1]
    if not os.path.isabs(p):
        p = os.path.join(os.environ.get("TEMP", "."), "rrcap", p)
    sys.exit(main(p))
