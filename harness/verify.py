#!/usr/bin/env python3
"""In-harness integrity verification for received MoQT media.

Reusable across impls, media files and draft pins. Everything is input-driven
(run_dir layout, registry sub_output config, plan media path) -- nothing is
hardcoded to a specific implementation or test clip. Three independent pieces:

1. mlog delivered bytes -- the moq-rs relay writes one JSON-SEQ mlog per
   connection ({cid}_server.mlog). Summing `subgroup_object_created` payload
   lengths on the SUBSCRIBER connection gives the authoritative byte count
   handed to the subscriber, independent of how the client writes stdout.
   This is what kills the ">100% delivered" artifact (B26): moq-rs interleaves
   tracing logs with the media on stdout, inflating the captured file size.

2. Expected content model -- the source media is split into the objects a MoQT
   publisher sends: init (everything before the first moof) + one object per
   moof/mdat run, with trailing non-media boxes (mfra/free) excluded. Any
   fragmented MP4 works; non-fragmented/non-MP4 falls back to a single whole
   object so the check still applies.

3. Content hash -- sha256 of the received media bytes (ANSI-timestamp log
   lines stripped only when the impl is known to log to stdout) vs sha256 of
   the expected media, plus a byte-identical-prefix count so a truncated tail
   is reported honestly instead of a bare mismatch.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from harness.probe import probe_draft


def _json_seq_records(path: Path) -> List[Dict[str, Any]]:
    """Parse a JSON-SEQ file (one JSON record per line, 0x1e-prefixed) into
    records; whole-file JSON is accepted as a fallback."""
    records: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return records
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line[0] != "{":
            idx = line.find("{")
            if idx < 0:
                continue
            line = line[idx:]
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not records:
        try:
            data = json.loads(path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            return records
        if isinstance(data, dict):
            records.append(data)
    return records


def _role_from_records(records: List[Dict[str, Any]]) -> Optional[str]:
    """Classify a relay mlog connection as 'subscriber' or 'publisher' from
    the control messages it records (no CID/naming assumptions).

    Publisher wins ties: at the draft-18 pin the relay SUBSCRIBES BACK to the
    publisher's connection (subscribe created / subscribe_ok parsed), so a
    publisher mlog legitimately contains subscribe_ok records -- see
    run_20260825_222511. Only an explicit publish_namespace exchange marks a
    publisher; subgroup-object direction breaks ties when no control
    messages exist (objects created = handed to a subscriber, parsed =
    received from a publisher)."""
    has_publish = False
    has_subscribe = False
    obj_created = obj_parsed = 0
    for rec in records:
        name = str(rec.get("name", ""))
        data = rec.get("data") or {}
        if not isinstance(data, dict):
            continue
        if name.startswith("moqt:") and "control_message" in name:
            msg = data.get("message_type", "")
            if msg == "publish_namespace" or \
                    data.get("request_kind") == "publish_namespace":
                has_publish = True
            if msg == "subscribe_ok":
                has_subscribe = True
        elif name.startswith("moqt:subgroup_object"):
            if name.endswith("_created"):
                obj_created += 1
            elif name.endswith("_parsed"):
                obj_parsed += 1
    if has_publish:
        return "publisher"
    if has_subscribe:
        return "subscriber"
    if obj_created > obj_parsed:
        return "subscriber"
    if obj_parsed > obj_created:
        return "publisher"
    return None


def parse_mlog_files(qlogs_dir: Path) -> List[Dict[str, Any]]:
    """Return {file, role, objects, first_object_ts} for every mlog under qlogs_dir.

    objects: list of (group_id, object_id, payload_length) from
    subgroup_object_created (subscriber side) / parsed (publisher side).
    first_object_ts: timestamp of first subgroup_object_created event (ms since epoch)
                     for subscriber connections, None otherwise.
    """
    if not qlogs_dir.exists():
        return []
    out: List[Dict[str, Any]] = []
    for fp in sorted(qlogs_dir.glob("*.mlog")):
        records = _json_seq_records(fp)
        objects: List[Tuple[int, int, int]] = []
        first_obj_ts = None
        for rec in records:
            data = rec.get("data") or {}
            if not isinstance(data, dict):
                continue
            name = str(rec.get("name", ""))
            if "object_payload_length" in data and name.startswith(
                    "moqt:subgroup_object"):
                objects.append((data.get("group_id", 0), data.get("object_id", 0),
                                int(data["object_payload_length"])))
                if name.endswith("_created") and first_obj_ts is None:
                    # moq-rs mlog uses "time" field for timestamp (ms since epoch)
                    ts = data.get("time")
                    if ts is not None:
                        try:
                            first_obj_ts = float(ts)
                        except (ValueError, TypeError):
                            pass
        out.append({
            "file": fp.name,
            "role": _role_from_records(records),
            "objects": objects,
            "first_object_ts": first_obj_ts,
        })
    return out


def mlog_subscriber_connections(qlogs_dir: Path) -> List[Dict[str, Any]]:
    """Every subscriber-role mlog connection with its delivered total.

    The relay opens one connection per subscriber and names mlogs by CID,
    so a connection CANNOT be mapped to a specific sub{i} role. Callers
    therefore SUM these totals (protocol truth about bytes handed to
    subscribers) instead of picking one 'best' connection.

    Only connections with at least one `subgroup_object_created` event are
    included, because those represent actual objects delivered TO subscribers.
    Connections with only `subgroup_object_parsed` are the publisher->relay
    direction and are excluded.
    """
    conns: List[Dict[str, Any]] = []
    for conn in parse_mlog_files(qlogs_dir):
        if conn["role"] == "subscriber" and conn["objects"]:
            # Check that this connection has actual subscriber-side objects
            # (subgroup_object_created), not just parsed objects from publisher
            has_created = False
            try:
                records = _json_seq_records(qlogs_dir / conn["file"])
                for rec in records:
                    name = str(rec.get("name", ""))
                    if name.startswith("moqt:subgroup_object") and name.endswith("_created"):
                        has_created = True
                        break
            except Exception:
                pass
            if not has_created:
                continue
            conns.append({
                "file": conn["file"],
                "total": sum(n for _, _, n in conn["objects"]),
                "objects": conn["objects"],
                "first_object_ts": conn.get("first_object_ts"),
            })
    return conns


def mlog_delivered_bytes(qlogs_dir: Path) -> Optional[Dict[str, Any]]:
    """Authoritative bytes handed to the subscriber (relay-side), if an mlog
    exists. Returns None when no subscriber connection was logged (non-moq-rs
    impls); callers fall back to artifact bytes. With several subscriber
    connections (fanout), the largest one is reported -- see
    mlog_subscriber_connections for the fanout-aware alternative."""
    best = None
    for conn in mlog_subscriber_connections(qlogs_dir):
        if best is None or conn["total"] >= best["total"]:
            best = {"total": conn["total"], "objects": conn["objects"],
                    "file": conn["file"]}
    return best


def _top_boxes(data: bytes) -> List[Tuple[int, str, int]]:
    out: List[Tuple[int, str, int]] = []
    i = 0
    n = len(data)
    while i + 8 <= n:
        size = int.from_bytes(data[i:i + 4], "big")
        typ = data[i + 4:i + 8].decode("latin1", "replace")
        if size == 0 or size < 8 or i + size > n:
            break
        out.append((i, typ, size))
        i += size
    return out


def expected_objects(data: bytes) -> List[Tuple[str, int]]:
    """Split a source file into the objects a MoQT publisher sends.

    Fragmented MP4: init = bytes before the first moof; one segment object per
    moof/mdat run; boxes after the last mdat (mfra/free) are not media and are
    excluded. Anything else (non-fragmented MP4, non-MP4): a single object of
    the whole file.
    """
    if not data:
        return []
    boxes = _top_boxes(data)
    moofs = [o for o, t, s in boxes if t == "moof"]
    if not moofs:
        return [("init", len(data))]
    init_end = moofs[0]
    mdats = [o for o, t, s in boxes if t == "mdat"]
    last_mdat_end = max(o + s for o, t, s in boxes if t == "mdat") if mdats else init_end
    objects: List[Tuple[str, int]] = [("init", init_end)]
    starts = moofs
    ends = moofs[1:] + [last_mdat_end]
    for s, e in zip(starts, ends):
        objects.append(("segment", e - s))
    return objects


def expected_media_bytes(data: bytes) -> bytes:
    """The exact bytes a publisher should deliver for the source file: init +
    segments, without trailing non-media boxes."""
    if not data:
        return b""
    boxes = _top_boxes(data)
    moofs = [o for o, t, s in boxes if t == "moof"]
    if not moofs:
        return data
    mdats = [o for o, t, s in boxes if t == "mdat"]
    last_mdat_end = max(o + s for o, t, s in boxes if t == "mdat") if mdats else moofs[0]
    return data[:last_mdat_end]


# moq-rs logs to stdout at pins before commit e46309faf4 ("send log output to
# stderr"): one ANSI-escaped tracing line per event. The timestamp signature is
# distinctive enough that binary MP4 payloads are not mistaken for log lines.
# Consume one or more ANSI escape sequences before the timestamp (B34 double-escape).
MLOG_STDOUT_SIG = re.compile(
    rb"(?:\x1b\[[0-9;]*m)+[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")


def media_bytes(data: bytes, logs_on_stdout: bool = False) -> bytes:
    """Received media bytes from a captured artifact.

    When the impl is known to log to stdout, whole ANSI-timestamp log lines
    (including inline ones that do not start at a newline boundary) are
    removed; otherwise the artifact is used as-is."""
    if not logs_on_stdout or not data:
        return data
    out = bytearray(data)
    for m in reversed(list(MLOG_STDOUT_SIG.finditer(data))):
        end = data.find(b"\n", m.start())
        end = len(data) if end == -1 else end
        del out[m.start():end + 1]
    return bytes(out)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_run(run_dir: Path, source_path: Optional[Path],
               artifact_paths: List[Path],
               logs_on_stdout: bool = False,
               good_threshold: float = 90.0) -> Dict[str, Any]:
    """Verify a completed run's received media against the source file.

    Returns a dict with the expected object model, the authoritative
    delivered byte count (mlog when available), the content SHA pair, a
    byte-identical-prefix check and a `verdict`:

      "exact"     -- sha256 of the received media equals the expected media.
      "good"      -- NOT byte-exact, but the subscriber received the full
                     object stream (mlog delivered_bytes == expected_bytes)
                     AND the identical-prefix is >= good_threshold%. This is
                     safe because the two signals are complementary: the mlog
                     proves completeness (nothing missing), the prefix proves
                     the arrived bytes are byte-exact (nothing corrupt). A
                     truncated capture always keeps a high prefix %, which is
                     exactly why "good" requires BOTH.
      "mismatch"  -- otherwise (missing bytes, or the arrived prefix diverges
                     below the threshold).

    All fields degrade to None when the data needed for them does not exist
    (never throws)."""
    result: Dict[str, Any] = {
        "expected_bytes": None,
        "delivered_bytes": None,
        "expected_objects": [],
        "received_objects": [],
        "per_object_match": None,
        "sha256_expected": None,
        "sha256_delivered": None,
        "sha256_match": None,
        "byte_identical_bytes": None,
        "byte_identical_pct": None,
        "verdict": None,
    }
    if source_path is None or not source_path.exists():
        return result
    source = source_path.read_bytes()
    if not source:
        return result

    expected = expected_objects(source)
    expected_media = expected_media_bytes(source)
    result["expected_objects"] = [{"kind": k, "bytes": b} for k, b in expected]
    result["expected_bytes"] = len(expected_media)
    result["sha256_expected"] = _sha256(expected_media)

    artifacts = [p for p in artifact_paths if p.exists()]
    if artifacts:
        captured = b"".join(p.read_bytes() for p in artifacts)
        delivered_media = media_bytes(captured, logs_on_stdout)
        result["sha256_delivered"] = _sha256(delivered_media)
        result["sha256_match"] = result["sha256_expected"] == result["sha256_delivered"]
        n = 0
        for a, b in zip(delivered_media, expected_media):
            if a != b:
                break
            n += 1
        result["byte_identical_bytes"] = n
        if expected_media:
            result["byte_identical_pct"] = round(100.0 * n / len(expected_media), 2)

    mlog = mlog_delivered_bytes(run_dir / "qlogs")
    if mlog is not None:
        result["delivered_bytes"] = mlog["total"]
        result["received_objects"] = [
            {"group": g, "object": o, "bytes": b} for g, o, b in mlog["objects"]
        ]
        expected_sizes = [b for _, b in expected]
        received_sizes = [b for _, _, b in mlog["objects"]]
        result["per_object_match"] = expected_sizes == received_sizes

    if result["sha256_match"]:
        result["verdict"] = "exact"
    elif (result["delivered_bytes"] == result["expected_bytes"]
          and result["byte_identical_pct"] is not None
          and result["byte_identical_pct"] >= good_threshold):
        result["verdict"] = "good"
    elif result["sha256_delivered"] is not None:
        result["verdict"] = "mismatch"
    return result


def _capture_stats(expected_media: bytes, artifacts: List[Path],
                   logs_on_stdout: bool) -> Dict[str, Any]:
    """Artifact-derived integrity fields for ONE subscriber's capture."""
    out: Dict[str, Any] = {
        "artifact_bytes": None, "media_bytes": None,
        "sha256_delivered": None, "sha256_match": None,
        "byte_identical_bytes": None, "byte_identical_pct": None,
    }
    paths = [p for p in artifacts if p.exists()]
    if not expected_media or not paths:
        return out
    captured = b"".join(p.read_bytes() for p in paths)
    out["artifact_bytes"] = sum(p.stat().st_size for p in paths)
    media = media_bytes(captured, logs_on_stdout)
    out["media_bytes"] = len(media)
    sha = _sha256(media)
    out["sha256_delivered"] = sha
    out["sha256_match"] = sha == _sha256(expected_media)
    n = 0
    for a, b in zip(media, expected_media):
        if a != b:
            break
        n += 1
    out["byte_identical_bytes"] = n
    out["byte_identical_pct"] = round(100.0 * n / len(expected_media), 2)
    return out


def _capture_verdict(stats: Dict[str, Any], complete: Optional[bool],
                     good_threshold: float) -> Optional[str]:
    """Verdict tier for one subscriber's capture.

    "exact" needs a byte-perfect SHA. "good" additionally requires proof the
    FULL object stream arrived -- which only a paired mlog connection can give
    (complete=True). Without mlog evidence, an imperfect SHA stays "mismatch":
    we never claim "good" on the artifact alone.
    """
    if stats["sha256_match"]:
        return "exact"
    if (complete and stats["byte_identical_pct"] is not None
            and stats["byte_identical_pct"] >= good_threshold):
        return "good"
    if stats["sha256_delivered"] is not None:
        return "mismatch"
    return None


def verify_groups(run_dir: Path, source_path: Optional[Path],
                  groups: Dict[str, List[Path]],
                  logs_on_stdout=False,
                  good_threshold: float = 90.0) -> Dict[str, Any]:
    """Per-subscriber + aggregate integrity over grouped captures.

    groups maps each subscriber role ("sub", "sub1", ...) to its received
    artifact files. Returns the verify_run() field set PLUS ``per_sub``:

    - Single group: identical to verify_run()'s numbers, plus per_sub with
      that one subscriber's artifact-derived view.
    - Multiple groups (fanout): concatenating N subscribers' captures is NOT
      a stream, so sha256_delivered/match are None; delivered_bytes is the
      SUM over ALL subscriber mlog connections (protocol truth); the prefix
      percentage is the MINIMUM across subscribers; the verdict is the
      worst tier any subscriber reached. mlog connections are CID-named and
      cannot be mapped to roles, so when counts match they are paired by
      descending size to give per-sub completeness ("good" tier).
    """
    result: Dict[str, Any] = {
        "expected_bytes": None,
        "delivered_bytes": None,
        "expected_objects": [],
        "received_objects": [],
        "per_object_match": None,
        "sha256_expected": None,
        "sha256_delivered": None,
        "sha256_match": None,
        "byte_identical_bytes": None,
        "byte_identical_pct": None,
        "verdict": None,
        "per_sub": {},
    }
    if source_path is None or not source_path.exists():
        return result
    source = source_path.read_bytes()
    if not source:
        return result

    expected = expected_objects(source)
    expected_media = expected_media_bytes(source)
    result["expected_objects"] = [{"kind": k, "bytes": b} for k, b in expected]
    result["expected_bytes"] = len(expected_media)
    result["sha256_expected"] = _sha256(expected_media)

    roles = list(groups.keys())

    def _strip_for(role: str) -> bool:
        """ANSI-strip flag for one role. Accepts the legacy bool (every
        role) or a role -> bool mapping for mixed-impl runs."""
        if isinstance(logs_on_stdout, dict):
            return bool(logs_on_stdout.get(role, False))
        return bool(logs_on_stdout)

    if len(roles) <= 1:
        role = roles[0] if roles else "sub"
        flat = groups.get(role, [])
        agg = verify_run(run_dir, source_path, flat,
                         logs_on_stdout=_strip_for(role),
                         good_threshold=good_threshold)
        agg.pop("per_sub", None)
        result.update({k: v for k, v in agg.items()})
        cs = _capture_stats(expected_media, flat, _strip_for(role))
        complete = (agg.get("delivered_bytes") is not None
                    and result["expected_bytes"] is not None
                    and agg["delivered_bytes"] == result["expected_bytes"])
        cs["mlog_delivered_bytes"] = agg.get("delivered_bytes")
        cs["verdict"] = _capture_verdict(cs, complete, good_threshold)
        result["per_sub"][role] = {"role": role, **cs}
        return result

    # --- multi-subscriber (fanout) ---
    per = {role: _capture_stats(expected_media, groups[role], _strip_for(role))
           for role in roles}
    conns = mlog_subscriber_connections(run_dir / "qlogs")
    pairs: Dict[str, int] = {}
    if len(conns) == len(roles):
        by_role = sorted(roles,
                         key=lambda r: -(per[r]["media_bytes"] or 0))
        by_conn = sorted(conns, key=lambda c: -c["total"])
        for role, conn in zip(by_role, by_conn):
            pairs[role] = conn["total"]

    for role in roles:
        cs = dict(per[role])
        cs["mlog_delivered_bytes"] = pairs.get(role)
        complete = (pairs.get(role) is not None
                    and pairs[role] == result["expected_bytes"])
        cs["verdict"] = _capture_verdict(cs, complete, good_threshold)
        result["per_sub"][role] = {"role": role, **cs}

    if conns:
        result["delivered_bytes"] = sum(c["total"] for c in conns)
        biggest = max(conns, key=lambda c: c["total"])
        result["received_objects"] = [
            {"group": g, "object": o, "bytes": b}
            for g, o, b in biggest["objects"]]
        # per-object comparison across N anonymous connections is ambiguous
        result["per_object_match"] = None
    else:
        totals = [per[r]["media_bytes"] for r in roles]
        result["delivered_bytes"] = (
            sum(t for t in totals if t is not None)
            if any(t is not None for t in totals) else None)

    pcts = [per[r]["byte_identical_pct"] for r in roles
            if per[r]["byte_identical_pct"] is not None]
    result["byte_identical_pct"] = min(pcts) if pcts else None

    tiers = [result["per_sub"][r]["verdict"] for r in roles
             if result["per_sub"][r]["verdict"]]
    if not tiers:
        result["verdict"] = None
    elif all(t == "exact" for t in tiers):
        result["verdict"] = "exact"
    elif all(t in ("exact", "good") for t in tiers):
        result["verdict"] = "good"
    else:
        result["verdict"] = "mismatch"
    return result


def _parse_mpd_segments(mpd_path: Path) -> Tuple[Optional[str], List[str], float]:
    """Parse a DASH MPD for (init_name, ordered segment names, segment duration).

    Mirrors docker/lldash/client.py parsing so the harness independently
    audits what the client should have fetched. Falls back to (None, [], 2.0)
    when the MPD is missing or unparsable; callers then fall back to the
    testdata chunk-*.m4s directory listing.
    """
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(mpd_path.read_text(errors="replace"))
    except (OSError, ET.ParseError):
        return None, [], 2.0
    init_url: Optional[str] = None
    segment_urls: List[str] = []
    seg_dur = 2.0
    try:
        for elem in root.iter():
            tag = str(elem.tag)
            if tag.endswith("SegmentTemplate"):
                init = elem.get("initialization")
                media = elem.get("media")
                try:
                    timescale = float(elem.get("timescale") or 0) or None
                except ValueError:
                    timescale = None
                if init and not init_url:
                    init_url = init.replace("$RepresentationID$", "0")
                if media:
                    timeline = None
                    for child in elem:
                        if str(child.tag).endswith("SegmentTimeline"):
                            timeline = child
                            break
                    count = 0
                    if timeline is not None:
                        for s in timeline:
                            if str(s.tag).endswith("S"):
                                try:
                                    d = float(s.get("d") or 0)
                                    if timescale and d > 0:
                                        seg_dur = d / timescale
                                except ValueError:
                                    pass
                                try:
                                    rep = int(s.get("r")) if s.get("r") is not None else 0
                                    count += rep + 1
                                except (ValueError, TypeError):
                                    count += 1
                    if count == 0:
                        count = 60
                    for i in range(1, count + 1):
                        seg = media.replace("$RepresentationID$", "0").replace(
                            "$Number%05d$", f"{i:05d}").replace("$Number$", str(i))
                        segment_urls.append(seg)
            if tag.endswith("Initialization"):
                src = elem.get("sourceURL")
                if src and not init_url:
                    init_url = src
            if tag.endswith("SegmentURL"):
                media = elem.get("media")
                if media:
                    segment_urls.append(media)
    except Exception:
        return init_url, segment_urls, seg_dur
    return init_url, segment_urls, seg_dur


def verify_lldash_streaming(groups: Dict[str, List[Path]],
                            testdata_dir: Path,
                            mpd_name: Optional[str] = None) -> Dict[str, Any]:
    """Streaming value verification for the LL-DASH baseline (decisions.md D9).

    Unlike verify_groups() (whole-file SHA vs the source mp4, which a late
    joiner's shorter capture can never match), this checks per-segment VALUE:
    every fetched segment byte-for-byte against the origin files in
    ``testdata_dir``, plus that the fetched set equals the join-adjusted
    expectation (``skip = floor(join_delay / seg_dur)``).

    Each subscriber's client writes a sidecar ``<artifact>.segments.json``
    manifest (see docker/lldash/client.py). Roles without a manifest fall
    back to ``verdict None`` so legacy SHA numbers are left untouched.

    Verdicts per subscriber:
      "exact"    -- full stream (skip==0), all bytes byte-identical.
      "good"     -- late joiner fetched exactly its expected suffix and all
                    bytes byte-identical (correct partial, not a failure).
      "mismatch" -- wrong segment set or any byte differs (or nothing arrived).
    """
    result: Dict[str, Any] = {
        "streaming": True,
        "verdict": None,
        "total_segments": None,
        "segment_duration_s": None,
        "per_sub": {},
    }
    # Full ordered segment list from the run's testdata MPD (or chunk dir
    # fallback). The MPD is chosen by the run's media file (sample.mp4 ->
    # sample.mpd, sample_120s.mp4 -> sample_120s.mpd) so coexisting sets
    # (chunk-stream0-* for 120s, sample10-chunk-* for 10s) never mix.
    full: List[str] = []
    seg_dur = 2.0
    init_name: Optional[str] = None
    mpd_path: Optional[Path] = None
    if mpd_name:
        cand = testdata_dir / mpd_name
        if cand.exists():
            mpd_path = cand
    if mpd_path is None:
        mpd_cands = sorted(testdata_dir.glob("*.mpd"))
        if mpd_cands:
            mpd_path = mpd_cands[0]
    if mpd_path is not None:
        init_name, full, seg_dur = _parse_mpd_segments(mpd_path)
    if not full:
        # Prefix-aware fallback: match the chunk set to the MPD in use.
        stem = (mpd_path.stem if mpd_path else "")
        if stem.startswith("sample_120s"):
            full = sorted(p.name for p in testdata_dir.glob("chunk-stream0-*.m4s"))
        elif stem == "sample":
            full = sorted(p.name for p in testdata_dir.glob("sample10-chunk-*.m4s"))
        else:
            full = sorted(p.name for p in testdata_dir.glob("chunk-*.m4s"))
    result["total_segments"] = len(full) or None
    result["segment_duration_s"] = seg_dur

    # NOTE: pathlib import is local to avoid touching module imports.
    from pathlib import Path as _P
    for role, paths in groups.items():
        entry: Dict[str, Any] = {
            "role": role,
            "join_delay_s": 0.0,
            "skipped": None,
            "total_segments": len(full) or None,
            "segments_fetched": 0,
            "segments_expected": None,
            "segments_matching": 0,
            "seg_match_pct": None,
            "artifact_bytes": None,
            "verdict": None,
            # Phase 3 (D13): transport actually used per sub. The client tries
            # true QUIC first for h3 then falls back to TCP (client.py
            # _http_get) — without this label an h3 row served over TCP would
            # read as a QUIC result. None/{} for manifest-less legacy runs.
            "fetch_protocol": None,
            "fetch_protos": {},
        }
        existing = [p for p in paths if p.exists()]
        if existing:
            try:
                entry["artifact_bytes"] = sum(p.stat().st_size for p in existing)
            except OSError:
                entry["artifact_bytes"] = None
        # Locate sidecar next to the first artifact.
        manifest: Optional[Dict[str, Any]] = None
        if existing:
            cand = existing[0].parent / (existing[0].stem + ".segments.json")
            if cand.exists():
                try:
                    manifest = json.loads(cand.read_text(errors="replace"))
                except (OSError, json.JSONDecodeError):
                    manifest = None
        if manifest is None:
            # No manifest (e.g. runs predating streaming client): leave the
            # legacy SHA verdict from verify_groups() untouched.
            result["per_sub"][role] = entry
            continue
        try:
            join_delay = float(manifest.get("join_delay_s", 0) or 0)
        except (ValueError, TypeError):
            join_delay = 0.0
        entry["join_delay_s"] = join_delay
        entry["fetch_protocol"] = manifest.get("protocol")
        protos = manifest.get("fetch_protos") or {}
        entry["fetch_protos"] = dict(protos) if isinstance(protos, dict) else {}
        skip_exp = min(int(join_delay // seg_dur) if seg_dur > 0 else 0, len(full))
        expected_names = [(_P(s).name) for s in full[skip_exp:]]
        entry["skipped"] = int(manifest.get("skipped", skip_exp))
        entry["segments_expected"] = len(expected_names)
        got = manifest.get("segments") or []
        got_names = [str(s.get("name")) for s in got if isinstance(s, dict)]
        entry["segments_fetched"] = len(got_names)
        # Names must equal the join-adjusted suffix, in order.
        names_ok = (got_names == expected_names)
        # Value: every fetched segment byte-identical to the origin file AND
        # to the received output slice (init + segments in manifest order).
        matching = 0
        slices_ok = True
        try:
            captured = b"".join(p.read_bytes() for p in existing)
        except OSError:
            captured = b""
        cursor = 0
        # Init slice first (when the manifest records one).
        minit = manifest.get("init") or {}
        if minit.get("name"):
            ipath = testdata_dir / str(minit["name"])
            try:
                origin_init = ipath.read_bytes() if ipath.exists() else None
            except OSError:
                origin_init = None
            init_len = int(minit.get("bytes") or 0)
            part = captured[cursor:cursor + init_len]
            if (origin_init is not None and _sha256(origin_init) == minit.get("sha256")
                    and _sha256(part) == minit.get("sha256")):
                cursor += init_len
            else:
                slices_ok = False
        for seg in got:
            if not isinstance(seg, dict):
                slices_ok = False
                continue
            opath = testdata_dir / str(seg.get("name"))
            try:
                origin_bytes = opath.read_bytes() if opath.exists() else None
            except OSError:
                origin_bytes = None
            seg_len = int(seg.get("bytes") or 0)
            part = captured[cursor:cursor + seg_len]
            if (origin_bytes is not None and len(origin_bytes) == seg_len
                    and _sha256(origin_bytes) == seg.get("sha256")
                    and _sha256(part) == seg.get("sha256")):
                matching += 1
                cursor += seg_len
            else:
                slices_ok = False
                cursor += seg_len
        entry["segments_matching"] = matching
        if got_names:
            entry["seg_match_pct"] = round(100.0 * matching / len(got_names), 2)
        if not got_names:
            entry["verdict"] = "mismatch"
        elif names_ok and slices_ok and len(got_names) == len(expected_names):
            entry["verdict"] = "exact" if skip_exp == 0 else "good"
        else:
            entry["verdict"] = "mismatch"
        result["per_sub"][role] = entry

    tiers = [e["verdict"] for e in result["per_sub"].values() if e["verdict"]]
    if not tiers:
        result["verdict"] = None
    elif all(t == "exact" for t in tiers):
        result["verdict"] = "exact"
    elif all(t in ("exact", "good") for t in tiers):
        result["verdict"] = "good"
    else:
        result["verdict"] = "mismatch"
    return result


# ---------------------------------------------------------------------------
# Draft verification (B28 fix)
# ---------------------------------------------------------------------------


class DraftVerifier:
    """Probe every (implementation, claimed_draft) pair and report what was
    actually negotiated vs what each impl advertises.

    Evidence levels (from probe.py):
      "setup"      — real SETUP exchange confirmed the negotiated draft.
      "alpn"       — draft-specific ALPN (moq-00/moqt-16/moqt-18) read from the
                     decrypted QUIC Initial ClientHello.
      "tap14"      — imquic's interop-test setup-only passed.
      "boot"       — container booted but negotiated draft not confirmed.
      "unverified" — ran but version could not be parsed.
      "failed"     — could not be run at all.
    """

    def __init__(self, registry_path: Optional[Path] = None):
        from harness.runner import REGISTRY_PATH
        path = registry_path or REGISTRY_PATH
        with open(path) as f:
            self.registry = json.load(f)
        self.impls = self.registry.get("implementations", [])

    def verify_all(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for impl in self.impls:
            name = impl["name"]
            claimed = impl.get("claimed_drafts", [])
            if not claimed:
                results.append({
                    "impl": name,
                    "claimed_draft": None,
                    "negotiated_draft": None,
                    "evidence": "no_claimed_drafts",
                })
                continue
            for draft in claimed:
                negotiated, evidence = probe_draft(impl, draft)
                results.append({
                    "impl": name,
                    "claimed_draft": draft,
                    "negotiated_draft": negotiated,
                    "evidence": evidence,
                })
        return results

    def print_report(self, results: List[Dict[str, Any]]):
        print("\n" + "=" * 78)
        print("DRAFT VERIFICATION REPORT")
        print("=" * 78)
        header = f"{'Implementation':<20} {'Claimed':<10} {'Actual':<10} {'Evidence':<12}"
        print(header)
        print("-" * 78)
        for r in results:
            impl = r["impl"]
            claimed = r.get("claimed_draft") or "-"
            actual = r.get("negotiated_draft") or "-"
            evidence = r.get("evidence", "?")
            status = "CONFIRMED" if evidence in ("setup", "tap14", "alpn") else evidence.upper()
            print(f"{impl:<20} {claimed:<10} {actual:<10} {status:<12}")
        confirmed = sum(1 for r in results if r.get("evidence") in ("setup", "tap14", "alpn"))
        total = len(results)
        print("-" * 78)
        print(f"Total: {total}  Confirmed: {confirmed}  Unconfirmed: {total - confirmed}")
        print("=" * 78 + "\n")


if __name__ == "__main__":
    verifier = DraftVerifier()
    results = verifier.verify_all()
    verifier.print_report(results)