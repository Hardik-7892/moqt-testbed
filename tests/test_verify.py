#!/usr/bin/env python3
import json

from harness.verify import (
    expected_media_bytes,
    expected_objects,
    media_bytes,
    mlog_delivered_bytes,
    mlog_subscriber_connections,
    parse_mlog_files,
    verify_groups,
    verify_run,
)


def _box(typ: str, payload: bytes) -> bytes:
    size = 8 + len(payload)
    return size.to_bytes(4, "big") + typ.encode() + payload


def _sample_source() -> bytes:
    init = _box("ftyp", b"isom" * 3) + _box("moov", b"X" * 750)
    segment = _box("moof", b"M" * 2000) + _box("mdat", b"m" * 5000)
    mfra = _box("mfra", b"R" * 67)
    return init + segment + mfra


def _json_seq_line(name: str, data: dict) -> str:
    return "\x1e" + json.dumps({"name": name, "data": data})


def test_expected_objects_fragmented_mp4():
    source = _sample_source()
    init_len = 20 + 758  # ftyp box + moov box
    seg_len = 2008 + 5008  # moof box + mdat box
    objects = expected_objects(source)
    assert objects == [("init", init_len), ("segment", seg_len)]
    assert expected_media_bytes(source) == source[:init_len + seg_len]


def test_expected_objects_non_fragmented_falls_back_to_whole_file():
    data = _box("ftyp", b"avc1" * 4) + _box("mdat", b"v" * 1000)
    assert expected_objects(data) == [("init", len(data))]
    assert expected_media_bytes(data) == data


def test_mlog_roles_and_delivered_bytes(tmp_path):
    qlogs = tmp_path / "qlogs"
    qlogs.mkdir()
    pub = qlogs / "aa_pub.mlog"
    pub.write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_parsed",
                           {"message_type": "client_setup"}),
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "request_ok",
                            "request_kind": "publish_namespace"}),
            _json_seq_line("moqt:subgroup_object_parsed",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 786}),
            _json_seq_line("moqt:subgroup_object_parsed",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7032}),
        ]) + "\n")
    sub = qlogs / "bb_sub.mlog"
    sub.write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_parsed",
                           {"message_type": "client_setup"}),
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 786}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7032}),
        ]) + "\n")

    conns = parse_mlog_files(qlogs)
    roles = {c["file"]: c["role"] for c in conns}
    assert roles["aa_pub.mlog"] == "publisher"
    assert roles["bb_sub.mlog"] == "subscriber"

    delivered = mlog_delivered_bytes(qlogs)
    assert delivered["total"] == 7818
    assert [b for _, _, b in delivered["objects"]] == [786, 7032]


def test_verify_run_clean_delivery(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    (out / "media.mp4").write_bytes(expected_media_bytes(source))
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7016}),
        ]) + "\n")

    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["delivered_bytes"] == 7794
    assert v["expected_bytes"] == 7794
    assert v["sha256_match"] is True
    assert v["per_object_match"] is True
    assert v["byte_identical_pct"] == 100.0


def test_verify_run_truncated_tail_reports_honestly(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    expected = expected_media_bytes(source)
    # client drops the last 32 bytes of the final object (moq-rs quirk)
    (out / "media.mp4").write_bytes(expected[:-32])
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7016}),
        ]) + "\n")

    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["delivered_bytes"] == 7794  # mlog: everything reached the sub
    assert v["sha256_match"] is False
    assert v["byte_identical_bytes"] == 7794 - 32
    assert v["byte_identical_pct"] == round(100.0 * (7794 - 32) / 7794, 2)


def test_media_bytes_strips_inline_ansi_logs():
    source = _sample_source()
    expected = expected_media_bytes(source)
    log = b"\x1b[2m2026-08-18T18:12:34.781040Z\x1b[0m INFO\x1b[2m moq_sub::media: playing 1 tracks\n"
    contaminated = log + expected[:20] + log + expected[20:]
    stripped = media_bytes(contaminated, logs_on_stdout=True)
    assert stripped == expected


def test_media_bytes_passthrough_when_not_logging_to_stdout():
    source = _sample_source()
    assert media_bytes(source, logs_on_stdout=False) == source


def test_verify_run_missing_source_never_throws(tmp_path):
    run_dir = tmp_path / "run"
    v = verify_run(run_dir, tmp_path / "nope.mp4", [])
    assert v["sha256_match"] is None
    assert v["delivered_bytes"] is None
    assert v["verdict"] is None


def test_verify_run_verdict_exact(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    (out / "media.mp4").write_bytes(expected_media_bytes(source))
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7016}),
        ]) + "\n")
    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["verdict"] == "exact"


def test_verify_run_verdict_good_on_tail_loss(tmp_path):
    # complete via mlog + high identical-prefix -> "good", not "mismatch"
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    expected = expected_media_bytes(source)
    (out / "media.mp4").write_bytes(expected[:-32])
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7016}),
        ]) + "\n")
    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["sha256_match"] is False
    assert v["delivered_bytes"] == v["expected_bytes"] == 7794
    assert v["verdict"] == "good"
    assert v["byte_identical_pct"] >= 90.0


def test_verify_run_verdict_good_respects_threshold(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    expected = expected_media_bytes(source)
    (out / "media.mp4").write_bytes(expected[:-700])
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 7016}),
        ]) + "\n")
    # mlog says complete, prefix only ~91%; default 90% threshold -> good
    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["verdict"] == "good"
    # stricter plan threshold -> mismatch
    v2 = verify_run(run_dir, src, [out / "media.mp4"], good_threshold=99.0)
    assert v2["verdict"] == "mismatch"


def test_verify_run_verdict_mismatch_on_missing_bytes(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    expected = expected_media_bytes(source)
    # subscriber genuinely did not receive the whole object stream
    (out / "media.mp4").write_bytes(expected[:-32])
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    (qlogs / "sub.mlog").write_text(
        "\n".join([
            _json_seq_line("moqt:control_message_created",
                           {"message_type": "subscribe_ok"}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 0,
                            "object_payload_length": 778}),
            _json_seq_line("moqt:subgroup_object_created",
                           {"group_id": 0, "object_id": 1,
                            "object_payload_length": 6000}),
        ]) + "\n")
    v = verify_run(run_dir, src, [out / "media.mp4"])
    assert v["delivered_bytes"] == 6778
    assert v["expected_bytes"] == 7794
    assert v["verdict"] == "mismatch"

# --- verify_groups: per-subscriber verification (B17/I9) ---

def _sub_mlog(path, total_objects):
    """Write a subscriber-role mlog whose object payloads sum to total."""
    lines = [_json_seq_line("moqt:control_message_created",
                            {"message_type": "subscribe_ok"})]
    remaining = total_objects
    for i in range(len(total_objects)):
        lines.append(_json_seq_line(
            "moqt:subgroup_object_created",
            {"group_id": 0, "object_id": i,
             "object_payload_length": total_objects[i]}))
    path.write_text("\n".join(lines) + "\n")


def _setup_multi(tmp_path, captures):
    """captures: {role: bytes}. Returns (run_dir, source_path, groups)."""
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    expected = expected_media_bytes(source)
    groups = {}
    for i, (role, data) in enumerate(captures.items()):
        d = out / role
        d.mkdir(parents=True, exist_ok=True)
        (d / role).write_bytes(data if data is not None else expected)
        groups[role] = [d / role]
    return run_dir, src, groups, expected


def test_verify_groups_single_group_matches_verify_run(tmp_path):
    source = _sample_source()
    src = tmp_path / "media.mp4"
    src.write_bytes(source)
    run_dir = tmp_path / "run"
    out = run_dir / "output"
    out.mkdir(parents=True)
    artifact = out / "media.mp4"
    artifact.write_bytes(expected_media_bytes(source))
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    _sub_mlog(qlogs / "cid_server.mlog", [778, 7016])

    g = verify_groups(run_dir, src, {"sub": [artifact]})
    v = verify_run(run_dir, src, [artifact])
    for key in ("expected_bytes", "delivered_bytes", "sha256_match",
                "byte_identical_pct", "verdict"):
        assert g[key] == v[key], key
    assert list(g["per_sub"]) == ["sub"]
    assert g["per_sub"]["sub"]["verdict"] == "exact"


def test_verify_groups_fanout_sums_mlogs_and_pairs_subs(tmp_path):
    source = _sample_source()
    expected = expected_media_bytes(source)
    captures = {
        "sub1": expected[:-32] + b"\n\x1b[2m2026-08-25T22:00:00Z\x1b[0m INFO x\n",  # tail loss + log noise
        "sub2": None,   # full clean copy
        "sub3": b"",    # received nothing
    }
    run_dir, src, groups, expected = _setup_multi(tmp_path, captures)
    qlogs = run_dir / "qlogs"
    qlogs.mkdir()
    # relay logged three subscriber connections, all complete (7794 each);
    # CID-named so pairing to roles is by descending size.
    for name in ("aa_server.mlog", "bb_server.mlog", "cc_server.mlog"):
        _sub_mlog(qlogs / name, [778, 7016])

    g = verify_groups(run_dir, src, groups)

    assert len(g["per_sub"]) == 3
    assert g["delivered_bytes"] == 3 * 7794  # SUM over all sub connections
    assert g["sha256_delivered"] is None     # concat of N subs is not a stream
    assert g["sha256_match"] is None
    # worst tier wins; sub3 received nothing -> mismatch overall
    assert g["verdict"] == "mismatch"
    assert g["per_sub"]["sub2"]["verdict"] == "exact"
    assert g["per_sub"]["sub1"]["verdict"] == "good"   # mlog-complete + high prefix
    assert g["per_sub"]["sub3"]["verdict"] == "mismatch"
    pcts = [g["per_sub"][r]["byte_identical_pct"] for r in ("sub1", "sub2", "sub3")]
    assert g["byte_identical_pct"] == min(pct for pct in pcts if pct is not None)


def test_verify_groups_without_mlogs_caps_at_exact_or_mismatch(tmp_path):
    captures = {"sub1": None, "sub2": None}
    run_dir, src, groups, expected = _setup_multi(tmp_path, captures)
    (run_dir / "qlogs").mkdir()  # no mlogs at all (non-moq-rs impls)
    g = verify_groups(run_dir, src, groups)
    assert g["delivered_bytes"] == 2 * len(expected)
    assert g["verdict"] == "exact"
    for ps in g["per_sub"].values():
        assert ps["mlog_delivered_bytes"] is None


def test_verify_groups_missing_source_returns_skeleton(tmp_path):
    g = verify_groups(tmp_path, tmp_path / "nope.mp4",
                      {"sub1": [], "sub2": []})
    assert g["verdict"] is None
    assert g["per_sub"] == {}
    assert g["delivered_bytes"] is None


def test_mlog_subscriber_connections_lists_all_conns(tmp_path):
    qlogs = tmp_path / "qlogs"
    qlogs.mkdir()
    _sub_mlog(qlogs / "a_server.mlog", [100, 200])
    _sub_mlog(qlogs / "b_server.mlog", [300])
    conns = mlog_subscriber_connections(qlogs)
    assert sorted(c["total"] for c in conns) == [300, 300]
