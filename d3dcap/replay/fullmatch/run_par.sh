#!/usr/bin/env bash
# Full match -> mp4 with 300-frame chunks (the browser player cannot load a >1 GB .seq: "Unexpected end of
# JSON input" on a 1.5 GB file; 300 frames = ~500 MB loads fine). Emission runs EMIT_PAR chunks in parallel
# (single-threaded Python each), capture runs CAP_PAR headless Chromes on the GPU. Chunks are deleted as
# soon as their mp4 exists, so the disk holds at most ~EMIT_PAR+CAP_PAR chunks.
#   bash fullmatch/run_par.sh <tape.json.gz> <total_frames> [chunk=300] [EMIT_PAR=8] [CAP_PAR=3]
set -uo pipefail
cd "$(dirname "$0")/.."
TAPE="$1"; TOTAL="$2"; CH="${3:-300}"; EP="${4:-8}"; CP="${5:-3}"
N=$(( (TOTAL + CH - 1) / CH ))
emit() { k=$1; s=$((k*CH)); c=$CH; (( s + c > TOTAL )) && c=$((TOTAL - s)); tag=$(printf 'c%03d' "$k")
  [ -s "fullmatch/$tag.mp4" ] && return 0; [ -s "fullmatch/$tag.seq" ] && return 0
  python tape_to_seq.py "$TAPE" --start "$s" --count "$c" --out "fullmatch/$tag.seq" > "fullmatch/$tag.log" 2>&1; echo "[$(date +%T)] emitted $tag"; }
cap() { k=$1; tag=$(printf 'c%03d' "$k"); [ -s "fullmatch/$tag.mp4" ] && return 0
  node capture_video.mjs "fullmatch/$tag.seq" "fullmatch/$tag.mp4" > "fullmatch/$tag.cap.log" 2>&1
  if [ -s "fullmatch/$tag.mp4" ]; then rm -f "fullmatch/$tag.seq"; echo "[$(date +%T)] captured $tag"; else echo "[$(date +%T)] CAPTURE FAILED $tag (see fullmatch/$tag.cap.log)"; fi; }
export -f emit cap; export TAPE TOTAL CH
# pipeline: emit in waves of EP, capture each wave in groups of CP
for ((w=0; w<N; w+=EP)); do
  pids=(); for ((k=w; k<w+EP && k<N; k++)); do emit "$k" & pids+=($!); done; wait "${pids[@]}"
  for ((k=w; k<w+EP && k<N; k+=CP)); do cpids=(); for ((j=k; j<k+CP && j<w+EP && j<N; j++)); do cap "$j" & cpids+=($!); done; wait "${cpids[@]}"; done
done
ls fullmatch/c*.mp4 | sed 's|fullmatch/||' | sed "s|^|file '|; s|$|'|" > fullmatch/concat.txt
( cd fullmatch && ffmpeg -y -loglevel error -f concat -safe 0 -i concat.txt -c copy full.mp4 )
ls -la fullmatch/full.mp4; echo "[$(date +%T)] FULL DONE"
