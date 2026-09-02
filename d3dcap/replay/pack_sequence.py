#!/usr/bin/env python3
"""Pack a BURST of consecutive captured frames into one playable .seq.

    python pack_sequence.py                 # find the longest consecutive run and pack it
    python pack_sequence.py 4360 4449        # pack an explicit inclusive range
    python pack_sequence.py -o match.seq

WHY THIS DELEGATES TO pack_replay.py INSTEAD OF REIMPLEMENTING IT.
pack_replay.py carries every gate that makes a frame trustworthy: the strip->list conversion with
D3D's odd-triangle swap, the byte-offset vertex binding, the per-frame texture lookup, the shader
classification from disassembly, the 100%-texture-coverage assertion and the BORDER-address refusal.
A second packer would drift from it, and the drift would show up as a subtly wrong replay months
later. So this runs the real packer once per frame and MERGES the results.

The merge is where a sequence gets cheap. Frames share almost everything -- the stage pages, the
palettes, the shaders, the input layouts, most constant buffers -- so every payload is deduped by
content hash across the whole burst. Only what actually changed between frames is stored twice.

FORMAT
    "RRSQ" u32:headLen  head(JSON utf-8)  <blob pool>
    head = { "frames": [ <one pack_replay head per frame, blob offsets rewritten> ], ... }
Each frame's head is byte-for-byte the head pack_replay.py produced, with every {off,len} rewritten
to point into the shared pool. That means the player can hand a frame straight to the same
createResources() the single-frame viewer uses -- no second code path to keep correct.
"""
import argparse
import glob
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile

CAP = os.path.join(os.environ.get("TEMP", "."), "rrcap")
HERE = os.path.dirname(os.path.abspath(__file__))


def captured_frames():
    out = []
    for f in glob.glob(os.path.join(CAP, "frame_*.ndjson")):
        if os.path.getsize(f) == 0:
            continue
        try:
            out.append(int(os.path.basename(f)[6:-7]))
        except ValueError:
            pass
    return sorted(out)


def longest_run(ids):
    """The longest run of CONSECUTIVE frame numbers. A burst is consecutive by construction; the
    8-second singles from a normal capture are not, so this picks the burst out on its own."""
    best = cur = []
    for i in ids:
        cur = cur + [i] if cur and i == cur[-1] + 1 else [i]
        if len(cur) > len(best):
            best = cur
    return best


def load_pack(path):
    b = open(path, "rb").read()
    if b[:4] != b"RRPK":
        raise SystemExit(f"{path} is not a .pack")
    n = struct.unpack_from("<I", b, 4)[0]
    return json.loads(b[8:8 + n].decode("utf-8")), b[8 + n:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("first", nargs="?", type=int)
    ap.add_argument("last", nargs="?", type=int)
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()

    ids = captured_frames()
    if not ids:
        sys.exit("no captured frames in %s" % CAP)
    if a.first and a.last:
        frames = [i for i in range(a.first, a.last + 1) if i in ids]
    else:
        frames = longest_run(ids)
    if len(frames) < 2:
        sys.exit("found no run of consecutive frames -- capture with: collect.ps1 -Burst 90\n"
                 "  (frames on disk: %s)" % (ids[:12] if len(ids) < 13 else str(ids[:12]) + " ..."))
    gaps = sum(1 for x, y in zip(frames, frames[1:]) if y != x + 1)
    print("sequence: frames %d..%d (%d frames%s)"
          % (frames[0], frames[-1], len(frames),
             "" if not gaps else ", %d GAP(S) -- this will not play back smoothly" % gaps))

    tmp = tempfile.mkdtemp(prefix="rrseq_")
    heads, blobs = [], []
    pool, pool_index = [], {}          # deduped payloads, keyed by content hash
    total_raw = 0
    dropped = []

    def intern(payload):
        """-> {off,len} in the shared pool, storing the bytes only once."""
        nonlocal total_raw
        total_raw += len(payload)
        h = hashlib.sha256(payload).digest()
        hit = pool_index.get(h)
        if hit is None:
            off = sum(len(p) for p in pool)
            hit = {"off": off, "len": len(payload)}
            pool_index[h] = hit
            pool.append(payload)
        return dict(hit)

    for n, fr in enumerate(frames):
        out = os.path.join(tmp, "f%d.pack" % fr)
        r = subprocess.run([sys.executable, os.path.join(HERE, "pack_replay.py"), str(fr), "-o", out],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        if r.returncode != 0 or not os.path.exists(out):
            # One bad frame must not sink the sequence, but it must be VISIBLE -- a silently dropped
            # frame is a playback that stutters for a reason nobody can find later.
            why = (r.stdout + r.stderr).strip().splitlines()
            dropped.append((fr, why[-1] if why else "pack_replay failed"))
            continue
        head, payload = load_pack(out)

        # rewrite every blob reference in this frame's head to point into the shared pool
        head["vb"] = intern(payload[head["vb"]["off"]: head["vb"]["off"] + head["vb"]["len"]])
        head["ib"] = intern(payload[head["ib"]["off"]: head["ib"]["off"] + head["ib"]["len"]])
        for key, rec in head["textures"].items():
            body = payload[rec["off"]: rec["off"] + rec["len"]]
            rec.update(intern(body))
        for key, rec in head["constantBuffers"].items():
            body = payload[rec["off"]: rec["off"] + rec["len"]]
            rec.update(intern(body))
        heads.append(head)
        sys.stdout.write("\r  packed %d/%d" % (n + 1, len(frames)))
        sys.stdout.flush()
    print()

    if dropped:
        print("  ⚠ %d frame(s) dropped:" % len(dropped))
        for fr, why in dropped[:6]:
            print("      %d: %s" % (fr, why))
    if len(heads) < 2:
        sys.exit("fewer than 2 frames packed -- nothing to play back")

    # The ground truth exists for the FIRST frame of a burst only (an 8 MB BMP per frame is not
    # worth it), so hoist it to the sequence and clear it on the others rather than leaving every
    # frame claiming a file that is not there.
    truth = next((h.get("sceneRTFile") for h in heads if h.get("sceneRTFile")), None)
    for h in heads:
        h["sceneRTFile"] = None
    manifest = {
        "frames": heads,
        "first": frames[0],
        "count": len(heads),
        "truthFrame": frames[0] if truth else None,
        "sceneRTFile": truth,
        "note": "each entry is a pack_replay head with blob offsets rewritten into a shared pool",
    }
    out = a.out or os.path.join(HERE, "seq_%d_%d.seq" % (frames[0], frames[-1]))
    head_bytes = json.dumps(manifest).encode("utf-8")
    with open(out, "wb") as f:
        f.write(b"RRSQ")
        f.write(struct.pack("<I", len(head_bytes)))
        f.write(head_bytes)
        for p in pool:
            f.write(p)

    size = os.path.getsize(out)
    draws = sum(len(h["draws"]) for h in heads)
    print("\n%d frames, %d draws, %d distinct payloads" % (len(heads), draws, len(pool)))
    print("dedupe: %.1f MB of payloads -> %.1f MB stored (%.0f%% shared between frames)"
          % (total_raw / 1048576.0, sum(len(p) for p in pool) / 1048576.0,
             100.0 * (1 - sum(len(p) for p in pool) / max(1, total_raw))))
    print("wrote %s  (%.1f MB)" % (out, size / 1048576.0))
    # The viewer cannot list the directory: serve.py answers "/" with index.html, not an index of
    # files. So publish what exists, newest first, and let the player default to the top one.
    seqs = sorted(glob.glob(os.path.join(HERE, "*.seq")), key=os.path.getmtime, reverse=True)
    with open(os.path.join(HERE, "sequences.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": os.path.basename(x), "mb": round(os.path.getsize(x) / 1048576.0, 1)}
                   for x in seqs], f)

    print("\n  open http://localhost:8099/player.html and load  %s" % os.path.basename(out))


if __name__ == "__main__":
    main()
