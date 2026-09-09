#!/bin/bash
# Download Big Buck Bunny (CC BY 3.0) into testdata/ for real-content tests.
#
# Source: official Blender mirror. BBB is licensed CC BY 3.0 by the Blender
# Foundation (attribution: "Blender Foundation | www.blender.org"). We use this
# mirror (NOT the archive.org copy, which is tagged ND-4.0 and can't be reused).
#
#   BigBuckBunny_640x360.m4v.zip  (~121 MB)  ->  testdata/bbb.mp4

set -e

OUTPUT_DIR="$(dirname "$0")/../testdata"
TMP_DIR="$(mktemp -d)"
ZIP="$TMP_DIR/bbb.zip"

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

mkdir -p "$OUTPUT_DIR"

URL="https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_640x360.m4v.zip"

echo "Downloading Big Buck Bunny (640x360, CC BY 3.0)..."
echo "  $URL"

if command -v wget >/dev/null 2>&1; then
    wget -O "$ZIP" "$URL"
else
    curl -L -o "$ZIP" "$URL"
fi

echo "Unzipping..."
unzip -o "$ZIP" -d "$TMP_DIR"

# The zip contains BigBuckBunny_640x360.m4v; normalize to bbb.mp4.
# moq-rs's moq-pub only accepts FRAGMENTED MP4 (moof/mdat): the raw M4V gave
# "failed to parse media: hdlr size too small", and a plain stream-copy remux
# gave "missing moof" (run_20260818_144538). Fragment with the SAME flags
# sample.mp4 is built with (Makefile) so the layout moq-rs parses is produced.
VIDEO_FILE=""
find "$TMP_DIR" -type f \( -iname "*.m4v" -o -iname "*.mp4" \) -print -quit > "$TMP_DIR/found"
read -r VIDEO_FILE < "$TMP_DIR/found" || true

if [ -z "$VIDEO_FILE" ] || [ ! -f "$VIDEO_FILE" ]; then
    echo "ERROR: no video file found in the downloaded archive" >&2
    exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "ERROR: ffmpeg not found. Install it (sudo apt-get install -y ffmpeg)." >&2
    exit 1
fi

echo "Remuxing $VIDEO_FILE -> testdata/bbb.mp4 (fragmented stream copy)..."
ffmpeg -y -i "$VIDEO_FILE" -c copy \
    -movflags empty_moov+frag_keyframe+separate_moof "$OUTPUT_DIR/bbb.mp4" >/dev/null 2>&1

if [ ! -s "$OUTPUT_DIR/bbb.mp4" ]; then
    echo "ERROR: remux produced an empty file" >&2
    exit 1
fi

echo "Done:"
ls -lh "$OUTPUT_DIR/bbb.mp4"
