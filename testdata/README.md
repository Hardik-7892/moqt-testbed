# Test Data

## sample.mp4
A short H.264+AAC video used for quick smoke tests. Run
`scripts/generate-test-data.sh` (requires ffmpeg) to generate one automatically,
or place any short MP4 file here.

## bbb.mp4 — Big Buck Bunny (640x360, ~10 min, ~115 MB)
Used for real-content interop/impairment tests. Fetched from the official Blender
mirror: `scripts/fetch-bbb.sh` (or `make fetch-bbb`).

- **Source:** `https://download.blender.org/peach/bigbuckbunny_movies/BigBuckBunny_640x360.m4v.zip`
- **License:** CC BY 3.0 — Blender Foundation. Attribution: **"Blender Foundation |
  www.blender.org"** (required by the license; include it in the thesis/presentations).
- **Note:** use the Blender mirror, NOT the archive.org copy (that one is tagged
  ND-4.0 and cannot be reused the same way).
- **SHA-256:** `738E2F999860553D056DD79C952F58F63CBB73892A57C72342CE9E5330D9D2D7`
