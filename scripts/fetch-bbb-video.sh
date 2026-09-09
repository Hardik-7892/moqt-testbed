#!/usr/bin/env bash
# Derive a VIDEO-ONLY fragmented MP4 from testdata/bbb.mp4.
#
# Why: BBB has separate video (1.m4s) and audio (2.m4s) tracks. moq-rs's
# subscriber writes received objects to stdout in ARRIVAL order, so a
# multi-track stream produces an interleaved capture whose moof data_offsets
# point into the ORIGINAL layout -- the file neither byte-compares to the
# source nor plays (run_20260825_233139). A single-track stream has no
# interleaving: delivery order == byte order, so the captured artifact
# compares cleanly and plays, exactly like sample.mp4 (-an) always did.
set -euo pipefail

SRC="testdata/bbb.mp4"
OUT="testdata/bbb-video.mp4"

command -v ffmpeg >/dev/null 2>&1 || {
  echo "ERROR: ffmpeg not found. Install it (sudo apt-get install -y ffmpeg)." >&2
  exit 1
}
[ -f "$SRC" ] || { echo "ERROR: $SRC missing (run 'make fetch-bbb' first)." >&2; exit 1; }

echo "Remuxing $SRC -> $OUT (video-only fragmented stream copy)..."
ffmpeg -y -i "$SRC" -map 0:v:0 -c:v copy -an \
  -movflags empty_moov+frag_keyframe+separate_moof "$OUT" >/dev/null 2>&1

[ -s "$OUT" ] || { echo "ERROR: remux produced an empty file" >&2; exit 1; }
echo "OK: $OUT ($(stat -c%s "$OUT") bytes, single track)"
