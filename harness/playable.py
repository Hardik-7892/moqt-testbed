"""Playable copies of received artifacts (I9 / "see the video on sub").

Raw captures are the measurement contract (completion polling, delivered
bytes, integrity) and are left untouched. This module derives a cleaned,
double-clickable copy per subscriber next to the raw artifact:

  copy        -- moxygen: the client already writes a real .flv
  strip_ansi  -- moq-rs: media + ANSI-timestamped log lines on stdout
                 (same cleaning the integrity check uses, verify.media_bytes)
  hex_decode  -- imquic (-t hex): metadata lines interleaved with hex-encoded
                 object payloads. No real payload capture exists yet (every
                 imquic sub run so far died before objects flowed), so the
                 parser is deliberately wording-independent: any whitespace-
                 stripped line that is pure hex of even length is decoded and
                 concatenated; everything else is ignored. VALIDATED ONLY ON
                 SYNTHETIC CAPTURES until an imquic row receives objects.

The transform per implementation is declared in registry.json under
sub_output.playable = {"transform": ..., "ext": ...}.
"""
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HEX_LINE = re.compile(r"[0-9a-fA-F]+")


def transform_copy(data: bytes) -> bytes:
    return data


def transform_strip_ansi(data: bytes) -> bytes:
    from harness.verify import media_bytes
    return media_bytes(data, logs_on_stdout=True)


def transform_hex_decode(data: bytes) -> bytes:
    out = bytearray()
    text = data.decode("latin1", "replace")
    for line in text.splitlines():
        s = "".join(line.split())
        if len(s) >= 2 and len(s) % 2 == 0 and _HEX_LINE.fullmatch(s):
            try:
                out += bytes.fromhex(s)
            except ValueError:
                pass
    return bytes(out)


TRANSFORMS = {
    "copy": transform_copy,
    "strip_ansi": transform_strip_ansi,
    "hex_decode": transform_hex_decode,
}


def reconstruct_from_mlog(artifact_data: bytes,
                          objects: List[Tuple[int, int, int]],
                          out_path: Path) -> dict:
    """Rebuild a sequential media file from an arrival-order capture.

    moq-rs draft-18 serves a track over multiple concurrent subgroup
    streams, so the subscriber's stdout capture is the concatenation of
    object payloads in ARRIVAL order (B37): verbatim bytes, permuted
    groups -- neither byte-comparable to the source nor playable.

    The relay mlog records that same object sequence as
    (group_id, object_id, payload_length). This function:
      1. slices the capture by those lengths in arrival order (the layout
         the subscriber actually wrote),
      2. re-sorts the pieces by (group_id, object_id),
      3. writes the concatenation -- a sequential fMP4 whose fragments are
         byte-identical to what was delivered, in play order.

    A capture truncated mid-object excludes that partial tail object.
    Returns stats; never raises on short data."""
    pos = 0
    pieces: List[Tuple[Tuple[int, int], bytes]] = []
    truncated_at = None
    for g, o, ln in objects:
        if pos >= len(artifact_data):
            truncated_at = (g, o, 0)
            break
        chunk = artifact_data[pos:pos + ln]
        pos += len(chunk)
        pieces.append(((g, o), chunk))
        if len(chunk) < ln:
            truncated_at = (g, o, len(chunk))
            break
    pieces.sort(key=lambda p: p[0])
    blob = b"".join(c for _, c in pieces)
    written = None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if blob:
            out_path.write_bytes(blob)
            written = out_path
    except OSError:
        pass
    delivered_groups = {g for (g, _), _ in pieces}
    return {
        "reconstructed_path": str(written) if written else None,
        "reconstructed_bytes": len(blob),
        "objects_total": len(objects),
        "objects_recovered": len(pieces),
        "groups_missing": sorted({g for g, _, _ in objects}
                                 - delivered_groups),
        "capture_truncated_at": truncated_at,
    }


def export_playable(groups: Dict[str, List[Path]],
                    hint: Optional[dict],
                    base_dirs: Dict[str, Path],
                    stream_name: str) -> List[Path]:
    """Write {stream}.{role}.{ext} into each subscriber's output folder.

    groups/base_dirs are keyed by subscriber role. Best-effort by contract:
    missing hints, empty captures or unwritable paths are skipped, never
    raised -- an export failure must never affect a run's status.
    """
    written: List[Path] = []
    if not hint:
        return written
    transform = TRANSFORMS.get(hint.get("transform"))
    ext = hint.get("ext")
    if not transform or not ext:
        return written
    for role, paths in groups.items():
        existing = [Path(p) for p in paths if Path(p).exists()]
        base = base_dirs.get(role)
        if not existing or base is None:
            continue
        try:
            data = b"".join(p.read_bytes() for p in existing)
            blob = transform(data)
            if not blob:
                continue
            out = Path(base) / f"{stream_name}.{role}.{ext}"
            out.write_bytes(blob)
            written.append(out)
        except OSError:
            continue
    return written
