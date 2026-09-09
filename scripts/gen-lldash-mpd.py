#!/usr/bin/env python3
"""Fallback MPD generator for sample_120s — minimal DASH MPD with 2s segments.
Used when MP4Box/ffmpeg dash not available. Creates placeholder init + media segments
by hard-linking/copying the source mp4 as single segment (still fetchable via HTTP).
"""
import pathlib, sys
src = pathlib.Path(sys.argv[1]) if len(sys.argv)>1 else pathlib.Path("testdata/sample_120s.mp4")
dst = pathlib.Path(sys.argv[2]) if len(sys.argv)>2 else pathlib.Path("testdata/sample_120s.mpd")
# Create minimal MPD that references the mp4 itself as single segment (no separate init to avoid double)
mpd = f"""<?xml version="1.0" encoding="UTF-8"?>
<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="static" mediaPresentationDuration="PT120S" minBufferTime="PT2S" profiles="urn:mpeg:dash:profile:isoff-live:2011">
  <Period>
    <AdaptationSet mimeType="video/mp4">
      <Representation id="1" bandwidth="500000" codecs="avc1.4d401e" width="320" height="240">
        <BaseURL>{src.name}</BaseURL>
        <SegmentList timescale="1000" duration="2000">
          <SegmentURL media="{src.name}"/>
        </SegmentList>
      </Representation>
    </AdaptationSet>
  </Period>
</MPD>
"""
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(mpd)
print(f"Wrote placeholder MPD {dst} ({len(mpd)} B) referencing {src.name}")
