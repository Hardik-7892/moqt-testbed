#!/bin/bash
# Convert testdata/bbb.mp4 (H.264/AAC MP4) into testdata/bbb.flv.
#
# moxygen's media pipeline is FLV-only: MoQFlvStreamerClient reads an FLV
# (h264 + AAC-LC) and MoQFlvReceiverClient writes an FLV. The mp4 used by
# moq-rs (raw byte transport) won't feed the moxygen streamer, so we remux.
#
#   Usage: bash scripts/fetch-flv.sh
#   Prereq: make fetch-bbb  (or testdata/bbb.mp4 present)

set -e

OUTPUT_DIR="$(dirname "$0")/../testdata"
INPUT="$OUTPUT_DIR/bbb.mp4"
OUTPUT="$OUTPUT_DIR/bbb.flv"

if [ ! -f "$INPUT" ]; then
    echo "ERROR: $INPUT not found. Run 'make fetch-bbb' first." >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ERROR: ffmpeg not found. Install it (sudo apt-get install -y ffmpeg)." >&2
    exit 1
fi

echo "Converting $INPUT -> $OUTPUT (stream copy)..."
ffmpeg -y -i "$INPUT" -c copy "$OUTPUT" >/dev/null 2>&1

if [ ! -s "$OUTPUT" ]; then
    echo "ERROR: conversion produced an empty file" >&2
    exit 1
fi

echo "Done:"
ls -lh "$OUTPUT"
