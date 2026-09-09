#!/bin/bash
# Generate a short test video for MoQ publishing
# Requires ffmpeg

set -e

OUTPUT_DIR="$(dirname "$0")/../testdata"
mkdir -p "$OUTPUT_DIR"

# Generate a 10-second H.264+AAC test video
# Simple color bars with a timer overlay
ffmpeg -y \
    -f lavfi -i "color=c=blue:s=1280x720:d=10:r=30" \
    -f lavfi -i "anullsrc=r=44100:cl=stereo" \
    -vf "drawtext=text='MoQ Test %{pts\:hms}':fontsize=48:fontcolor=white:x=100:y=100" \
    -c:v libx264 -preset ultrafast -crf 28 \
    -c:a aac -b:a 128k \
    -movflags cmaf+separate_moof+delay_moov+skip_trailer+frag_every_frame \
    "$OUTPUT_DIR/sample.mp4"

echo "Generated: $OUTPUT_DIR/sample.mp4"
ls -lh "$OUTPUT_DIR/sample.mp4"
