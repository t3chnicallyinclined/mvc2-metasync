#!/usr/bin/env bash
# Full-match replay -> mp4, chunked so the disk never holds more than ~2 chunks of .seq (1.5 GB each).
#   bash fullmatch/run_rest.sh <tape.json.gz> <total_frames> <first_chunk> [chunk=900]
# For each chunk: emit .seq (tape_to_seq) -> capture to .mp4 (capture_video.mjs, real GPU, headless Chrome)
# -> delete the .seq. Then concat every cNN.mp4 into full.mp4 (stream copy, no re-encode).
set -euo pipefail
cd "$(dirname "$0")/.."
TAPE="$1"; TOTAL="$2"; FROM="${3:-0}"; CH="${4:-900}"
N=$(( (TOTAL + CH - 1) / CH ))
for ((k=FROM; k<N; k++)); do
  start=$((k*CH)); cnt=$CH; if (( start + cnt > TOTAL )); then cnt=$((TOTAL - start)); fi
  tag=$(printf 'c%02d' "$k")
  if [ ! -s "fullmatch/$tag.mp4" ]; then
    if [ ! -s "fullmatch/$tag.seq" ]; then
      echo "[$(date +%T)] emit $tag frames $start..$((start+cnt-1))"
      python tape_to_seq.py "$TAPE" --start "$start" --count "$cnt" --out "fullmatch/$tag.seq" 2>&1 | grep -a "frames,\|HELD\|Traceback\|Error" || true
    fi
    echo "[$(date +%T)] capture $tag"
    node capture_video.mjs "fullmatch/$tag.seq" "fullmatch/$tag.mp4" 2>&1 | grep -v "^\[capture\] [0-9]*/" || true
  fi
  [ -s "fullmatch/$tag.mp4" ] && rm -f "fullmatch/$tag.seq"
done
ls fullmatch/c*.mp4 | sed "s|^|file '|; s|$|'|" | sed 's|fullmatch/||' > fullmatch/concat.txt
( cd fullmatch && ffmpeg -y -loglevel error -f concat -safe 0 -i concat.txt -c copy full.mp4 )
ls -la fullmatch/full.mp4
