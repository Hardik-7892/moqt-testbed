"""D10/D11 (decisions.md): LL-DASH streaming verification tests.

Covers harness/verify.py _parse_mpd_segments + verify_lldash_streaming
without Docker: per-segment VALUE checks against testdata origin files,
join-delay skip math, and MPD-set isolation (10s sample10-* vs 120s
chunk-stream0-* must never mix).
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.verify import (  # noqa: E402
    _parse_mpd_segments,
    verify_lldash_streaming,
)

TESTDATA = Path(__file__).resolve().parent.parent / "testdata"


def _sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _build_run(tmp_path, role, seg_names, init_name, join_delay, skipped):
    """Write artifact (init + segs from testdata) + sidecar manifest."""
    role_dir = tmp_path / role
    role_dir.mkdir(parents=True, exist_ok=True)
    artifact = role_dir / "t10s.mp4"
    blob = b""
    if init_name:
        blob += (TESTDATA / init_name).read_bytes()
    for n in seg_names:
        blob += (TESTDATA / n).read_bytes()
    artifact.write_bytes(blob)
    manifest = {
        "protocol": "h2",
        "join_delay_s": join_delay,
        "segment_duration_s": 2.0,
        "mpd": "sample.mpd",
        "init": None,
        "total_segments": 5,
        "skipped": skipped,
        "skipped_names": [],
        "segments": [],
        "fetched": len(seg_names),
        "fetch_protos": {"HTTP/2": len(seg_names) + 1},
    }
    if init_name:
        ib = (TESTDATA / init_name).read_bytes()
        manifest["init"] = {"name": init_name, "bytes": len(ib),
                            "sha256": _sha_bytes(ib)}
    for n in seg_names:
        b = (TESTDATA / n).read_bytes()
        manifest["segments"].append({"name": n, "bytes": len(b),
                                     "sha256": _sha_bytes(b)})
    (role_dir / "t10s.segments.json").write_text(json.dumps(manifest))
    return [artifact]


def test_parse_10s_mpd(tmp_path):
    init, segs, dur = _parse_mpd_segments(TESTDATA / "sample.mpd")
    assert init == "sample10-init.m4s"
    assert len(segs) == 5
    assert segs[0] == "sample10-chunk-00001.m4s"
    assert dur == 2.0


def test_parse_120s_mpd(tmp_path):
    init, segs, dur = _parse_mpd_segments(TESTDATA / "sample_120s.mpd")
    assert init == "init-stream0.m4s"
    assert len(segs) == 60
    assert dur == 2.0


def test_streaming_full_exact(tmp_path):
    segs = [f"sample10-chunk-{i:05d}.m4s" for i in range(1, 6)]
    groups = {"sub": _build_run(tmp_path, "sub", segs, "sample10-init.m4s", 0.0, 0)}
    res = verify_lldash_streaming(groups, TESTDATA, mpd_name="sample.mpd")
    assert res["verdict"] == "exact"
    ps = res["per_sub"]["sub"]
    assert ps["segments_fetched"] == 5
    assert ps["segments_matching"] == 5
    assert ps["seg_match_pct"] == 100.0


def test_streaming_late_good(tmp_path):
    # join 4s at 2s segs -> skip 2, fetch last 3
    segs = [f"sample10-chunk-{i:05d}.m4s" for i in range(3, 6)]
    groups = {"late": _build_run(tmp_path, "late", segs, "sample10-init.m4s", 4.0, 2)}
    res = verify_lldash_streaming(groups, TESTDATA, mpd_name="sample.mpd")
    assert res["per_sub"]["late"]["verdict"] == "good"
    assert res["per_sub"]["late"]["segments_fetched"] == 3
    assert res["per_sub"]["late"]["segments_expected"] == 3


def test_streaming_one_byte_corruption_mismatch(tmp_path):
    segs = [f"sample10-chunk-{i:05d}.m4s" for i in range(1, 6)]
    paths = _build_run(tmp_path, "sub", segs, "sample10-init.m4s", 0.0, 0)
    data = bytearray(paths[0].read_bytes())
    data[1000] ^= 0xFF
    paths[0].write_bytes(bytes(data))
    res = verify_lldash_streaming({"sub": paths}, TESTDATA, mpd_name="sample.mpd")
    assert res["per_sub"]["sub"]["verdict"] == "mismatch"


def test_streaming_mpd_sets_do_not_mix(tmp_path):
    # 10s manifest verified against the 120s MPD must mismatch (wrong set),
    # against sample.mpd must be exact.
    segs = [f"sample10-chunk-{i:05d}.m4s" for i in range(1, 6)]
    groups = {"sub": _build_run(tmp_path, "sub", segs, "sample10-init.m4s", 0.0, 0)}
    wrong = verify_lldash_streaming(groups, TESTDATA, mpd_name="sample_120s.mpd")
    assert wrong["per_sub"]["sub"]["verdict"] == "mismatch"
    right = verify_lldash_streaming(groups, TESTDATA, mpd_name="sample.mpd")
    assert right["per_sub"]["sub"]["verdict"] == "exact"


def test_streaming_no_manifest_leaves_legacy_untouched(tmp_path):
    d = tmp_path / "sub"
    d.mkdir(parents=True, exist_ok=True)
    art = d / "t10s.mp4"
    art.write_bytes(b"x" * 100)
    res = verify_lldash_streaming({"sub": [art]}, TESTDATA, mpd_name="sample.mpd")
    assert res["per_sub"]["sub"]["verdict"] is None
    assert res["verdict"] is None


def test_streaming_propagates_transport_label(tmp_path):
    # Phase 3 (D13): fetch_protos/protocol must survive verification so an h3
    # row served over TCP fallback cannot read as a QUIC result.
    segs = [f"sample10-chunk-{i:05d}.m4s" for i in range(1, 6)]
    groups = {"sub": _build_run(tmp_path, "sub", segs, "sample10-init.m4s", 0.0, 0)}
    mani_path = tmp_path / "sub" / "t10s.segments.json"
    mani = json.loads(mani_path.read_text())
    mani["protocol"] = "h3"
    mani["fetch_protos"] = {"h3": 4, "tcp-fallback": 2}
    mani_path.write_text(json.dumps(mani))
    res = verify_lldash_streaming(groups, TESTDATA, mpd_name="sample.mpd")
    ps = res["per_sub"]["sub"]
    assert ps["verdict"] == "exact"
    assert ps["fetch_protocol"] == "h3"
    assert ps["fetch_protos"] == {"h3": 4, "tcp-fallback": 2}


def test_streaming_transport_defaults_empty_without_manifest(tmp_path):
    d = tmp_path / "sub"
    d.mkdir(parents=True, exist_ok=True)
    art = d / "t10s.mp4"
    art.write_bytes(b"x" * 100)
    res = verify_lldash_streaming({"sub": [art]}, TESTDATA, mpd_name="sample.mpd")
    assert res["per_sub"]["sub"]["fetch_protocol"] is None
    assert res["per_sub"]["sub"]["fetch_protos"] == {}
