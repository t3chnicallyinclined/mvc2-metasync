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


# Fields that are identical across almost every draw. Measured on a 246-frame sequence: 167,214
# draws carry only 13 distinct combinations of these, at 482 bytes of JSON each -- about 80 MB of
# pure repetition in a 218 MB file. The manifest is parsed in the browser, so this is not just disk.
STATE_FIELDS = ("blend", "bfactor", "smask", "depth", "raster", "vp", "scissor")
# The shader triple and the variant flags derived from it: also a handful of combinations.
SHADER_FIELDS = ("vs", "ps", "il", "vsVariant", "psVariant", "psFog")


class Interner:
    """Assign a small integer to each distinct value, preserving first-seen order."""

    def __init__(self):
        self.items, self.index = [], {}

    def __call__(self, value):
        key = json.dumps(value, sort_keys=True)
        hit = self.index.get(key)
        if hit is None:
            hit = len(self.items)
            self.index[key] = hit
            self.items.append(value)
        return hit


def compact_draw(d, states, shaders, samplers, hashes, texkeys):
    """The same draw with its repeated parts replaced by table indices."""
    return {
        "i": d["i"], "f": d["firstIndex"], "n": d["indexCount"],
        "s": d["stride"], "o": d["voff"],
        "st": states({k: d.get(k) for k in STATE_FIELDS}),
        "sh": shaders({k: d.get(k) for k in SHADER_FIELDS}),
        "sm": samplers(d.get("samp")),
        "t": [texkeys(x) if x else -1 for x in (d.get("tex") or [])],
        "v": [hashes(x) for x in (d.get("vscbHash") or [])],
        "p": [hashes(x) for x in (d.get("pscbHash") or [])],
    }


def rehydrate(c, states, shaders, samplers, hashes, texkeys):
    """Rebuild the original draw record. The packer asserts this round-trips before writing, and
    player.mjs mirrors it -- a sequence whose draws come back subtly different renders subtly wrong,
    which is the hardest kind of bug to see."""
    d = {"i": c["i"], "firstIndex": c["f"], "indexCount": c["n"],
         "stride": c["s"], "voff": c["o"]}
    d.update(states[c["st"]])
    d.update(shaders[c["sh"]])
    d["samp"] = samplers[c["sm"]]
    d["tex"] = [texkeys[x] if x >= 0 else None for x in c["t"]]
    d["vscbHash"] = [hashes[x] for x in c["v"]]
    d["pscbHash"] = [hashes[x] for x in c["p"]]
    return d


def pool_bytes(pool, rec):
    """The bytes a {off,len} record points at, without concatenating the whole pool."""
    at = 0
    for chunk in pool:
        if at == rec["off"]:
            return chunk[:rec["len"]]
        at += len(chunk)
    raise SystemExit("pool offset %d does not start a chunk -- the merge is inconsistent" % rec["off"])


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

    pool_end = 0                       # running total: `sum(len(p) for p in pool)` per new payload was O(n^2)

    def intern(payload):
        """-> {off,len} in the shared pool, storing the bytes only once."""
        nonlocal total_raw, pool_end
        total_raw += len(payload)
        h = hashlib.sha256(payload).digest()
        hit = pool_index.get(h)
        if hit is None:
            hit = {"off": pool_end, "len": len(payload)}
            pool_index[h] = hit
            pool.append(payload)
            pool_end += len(payload)
        return dict(hit)

    # ⚠ PER-FRAME PACKS RUN IN PARALLEL. Each frame is independent (pack_replay reads only its own
    # files); the merge below stays sequential so the pool layout is deterministic. Measured before:
    # 180 frames one at a time, each a python start-up plus directory scans, minutes per step.
    def pack_one(fr):
        out = os.path.join(tmp, "f%d.pack" % fr)
        r = subprocess.run([sys.executable, os.path.join(HERE, "pack_replay.py"), str(fr), "-o", out],
                           capture_output=True, text=True,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        ok = r.returncode == 0 and os.path.exists(out)
        why = (r.stdout + r.stderr).strip().splitlines()
        return fr, out, ok, (why[-1] if why else "pack_replay failed")

    from concurrent.futures import ThreadPoolExecutor
    workers = max(2, min(12, (os.cpu_count() or 4) - 1))
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for fr, out, ok, why in ex.map(pack_one, frames):
            results[fr] = (out, ok, why)
            sys.stdout.write("\r  packing %d/%d (%d workers)" % (len(results), len(frames), workers))
            sys.stdout.flush()
    print()

    for n, fr in enumerate(frames):
        out, ok, why = results[fr]
        if not ok:
            dropped.append((fr, why))
            continue
        head, payload = load_pack(out)

        # rewrite every blob reference in this frame's head to point into the shared pool
        head["vb"] = intern(payload[head["vb"]["off"]: head["vb"]["off"] + head["vb"]["len"]])
        head["ib"] = intern(payload[head["ib"]["off"]: head["ib"]["off"] + head["ib"]["len"]])
        # ⚠⚠ RE-KEY TEXTURES BY CONTENT, NOT BY POINTER.
        # A frame's texture key is "pointer#generation", which is a content identity WITHIN one
        # frame and nowhere else: the same pointer with #0 in two frames is two different bitmaps.
        # Carrying those keys into a sequence let the player's shared texture map -- and its
        # bind-group cache -- hand frame N's pixels to frame N+1, which drew clean frames and
        # garbled ones alternately depending on which pointers happened to repeat. Same class of bug
        # as the `tex_*` glob that matched every captured frame; this is the sequence's version of it.
        # The pool offset IS a content identity, because intern() dedupes on sha256 of the bytes.
        rekey = {}
        textures = {}
        for key, rec in head["textures"].items():
            body = payload[rec["off"]: rec["off"] + rec["len"]]
            rec.update(intern(body))
            newkey = "t%d" % rec["off"]
            rekey[key] = newkey
            textures[newkey] = rec
        head["textures"] = textures
        for d in head["draws"]:
            d["tex"] = [rekey.get(t) if t else None for t in (d.get("tex") or [])]
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

    # ── factor the manifest ──────────────────────────────────────────────────────────────────────
    states, shaders, samplers = Interner(), Interner(), Interner()
    hashes, texkeys = Interner(), Interner()
    for h in heads:
        compacted = [compact_draw(d, states, shaders, samplers, hashes, texkeys)
                     for d in h["draws"]]
        # GATE: the compaction must be exactly reversible. It is applied to 167k draw records and a
        # single dropped field renders wrong rather than failing, so prove it here.
        for orig, c in zip(h["draws"], compacted):
            back = rehydrate(c, states.items, shaders.items, samplers.items,
                             hashes.items, texkeys.items)
            if json.dumps(back, sort_keys=True) != json.dumps(orig, sort_keys=True):
                sys.exit("draw %d of frame %s does not survive compaction:\n  was %s\n  got %s"
                         % (orig["i"], h["frame"], json.dumps(orig, sort_keys=True),
                            json.dumps(back, sort_keys=True)))
        h["draws"] = compacted
    print("manifest: %d states, %d shader sets, %d sampler sets, %d cb hashes, %d texture keys"
          % (len(states.items), len(shaders.items), len(samplers.items),
             len(hashes.items), len(texkeys.items)))

    # The ground truth exists for the FIRST frame of a burst only (an 8 MB BMP per frame is not
    # worth it), so hoist it to the sequence and clear it on the others rather than leaving every
    # frame claiming a file that is not there.
    truth = next((h.get("sceneRTFile") for h in heads if h.get("sceneRTFile")), None)
    for h in heads:
        h["sceneRTFile"] = None
    manifest = {
        "tables": {"states": states.items, "shaders": shaders.items, "samplers": samplers.items,
                   "hashes": hashes.items, "texKeys": texkeys.items},
        "frames": heads,
        "first": frames[0],
        "count": len(heads),
        "truthFrame": frames[0] if truth else None,
        "sceneRTFile": truth,
        "note": "each entry is a pack_replay head with blob offsets rewritten into a shared pool",
    }
    # GATE: the invariant the player depends on -- one texture key means one bitmap, everywhere in
    # the sequence. Carrying the per-frame "pointer#generation" keys into a sequence broke this for
    # 175 of 317 keys and handed frame N's pixels to frame N+1. Assert it here rather than discover
    # it as "some frames look garbled".
    seen, clashes = {}, 0
    # offset -> chunk, built once; pool_bytes() walked the whole pool per lookup (5k keys x 6k chunks)
    pool_at, _off = {}, 0
    for chunk in pool:
        pool_at[_off] = chunk
        _off += len(chunk)
    for h in heads:
        for key, rec in h["textures"].items():
            digest = hashlib.sha256(pool_at[rec["off"]][:rec["len"]]).hexdigest()
            if seen.setdefault(key, digest) != digest:
                clashes += 1
    refs = {texkeys.items[x] for h in heads for d in h["draws"] for x in d["t"] if x >= 0}
    if clashes:
        sys.exit("%d texture keys mean different pixels in different frames -- the player's shared "
                 "texture map would hand one frame's art to another" % clashes)
    missing = refs - set(seen)
    if missing:
        sys.exit("%d draw texture references resolve to nothing: %s"
                 % (len(missing), sorted(missing)[:5]))
    print("gate: %d texture keys, one bitmap each, %d draw references all resolve"
          % (len(seen), len(refs)))

    out = a.out or os.path.join(HERE, "seq_%d_%d.seq" % (frames[0], frames[-1]))
    head_bytes = json.dumps(manifest).encode("utf-8")
    with open(out, "wb") as f:
        f.write(b"RRSQ")
        f.write(struct.pack("<I", len(head_bytes)))
        f.write(head_bytes)
        for p in pool:
            f.write(p)

    # Write a gzipped sibling for the server to hand over instead. Measured: 89% smaller, and the
    # browser decompresses it transparently, so the player needs no changes at all.
    import gzip as _gzip
    with open(out, "rb") as src, _gzip.open(out + ".gz", "wb", compresslevel=6) as dst:
        while True:
            chunk = src.read(1 << 22)
            if not chunk:
                break
            dst.write(chunk)

    size = os.path.getsize(out)
    draws = sum(len(h["draws"]) for h in heads)
    print("\n%d frames, %d draws, %d distinct payloads" % (len(heads), draws, len(pool)))
    print("dedupe: %.1f MB of payloads -> %.1f MB stored (%.0f%% shared between frames)"
          % (total_raw / 1048576.0, sum(len(p) for p in pool) / 1048576.0,
             100.0 * (1 - sum(len(p) for p in pool) / max(1, total_raw))))
    gz = os.path.getsize(out + ".gz")
    print("wrote %s  (%.1f MB, %.1f MB gzipped -- %.0f KB per frame on the wire)"
          % (out, size / 1048576.0, gz / 1048576.0, gz / len(heads) / 1024.0))
    # The viewer cannot list the directory: serve.py answers "/" with index.html, not an index of
    # files. So publish what exists, newest first, and let the player default to the top one.
    seqs = sorted(glob.glob(os.path.join(HERE, "*.seq")), key=os.path.getmtime, reverse=True)
    with open(os.path.join(HERE, "sequences.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": os.path.basename(x), "mb": round(os.path.getsize(x) / 1048576.0, 1)}
                   for x in seqs], f)

    print("\n  open http://localhost:8099/player.html and load  %s" % os.path.basename(out))


if __name__ == "__main__":
    main()
