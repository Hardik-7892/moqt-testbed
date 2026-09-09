"""Tests for the playable-copy export (harness/playable.py)."""
from pathlib import Path

import pytest

from harness.playable import (
    export_playable,
    transform_copy,
    transform_hex_decode,
    transform_strip_ansi,
)


def test_hex_decode_ignores_metadata_and_noise():
    capture = (
        "imquic version 0.0.2/alpha\n"
        "[moq-sub/1] Subscribing to '.2f--x' (hex), using ID 0\n"
        "6674797069736f6d\n"          # pure hex line -> decoded
        "[moq-sub/1] Incoming object (id=0)\n"
        "DEADBEEF\n"                   # uppercase hex -> decoded
        "\n"
        "not-hex because of spaces and words\n"
        "abc\n"                        # odd length -> skipped
        "7 7\n"                        # whitespace-stripped -> 0x77
    ).encode("latin1")
    out = transform_hex_decode(capture)
    assert out == bytes.fromhex("6674797069736f6d") + b"\xde\xad\xbe\xef" + b"\x77"


def test_hex_decode_empty_capture_returns_empty():
    assert transform_hex_decode(b"") == b""
    assert transform_hex_decode("no payload here\n".encode()) == b""


def test_strip_ansi_removes_log_lines_keeps_media():
    log = b"\x1b[2m2026-08-25T22:00:00.000000Z\x1b[0m INFO moq_sub: hi\n"
    media = b"\x00\x00\x00\x18ftypisom"
    assert transform_strip_ansi(log + media + log) == media


def test_copy_is_passthrough():
    blob = b"\x46\x4c\x56\x01video-bytes"
    assert transform_copy(blob) == blob


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_export_writes_per_role_named_copies(tmp_path):
    groups = {
        "sub1": [_write(tmp_path / "out" / "sub1" / "stream", b"\x01\x02media1")],
        "sub2": [_write(tmp_path / "out" / "sub2" / "stream", b"\x03\x04media2")],
    }
    base_dirs = {"sub1": tmp_path / "out" / "sub1",
                 "sub2": tmp_path / "out" / "sub2"}
    written = export_playable(groups, {"transform": "copy", "ext": "flv"},
                              base_dirs, "run-x")
    assert [p.name for p in written] == ["run-x.sub1.flv", "run-x.sub2.flv"]
    assert (base_dirs["sub1"] / "run-x.sub1.flv").read_bytes() == b"\x01\x02media1"


def test_export_missing_hint_or_transform_skips(tmp_path):
    groups = {"sub": [_write(tmp_path / "o" / "s", b"data")]}
    base = {"sub": tmp_path / "o"}
    assert export_playable(groups, None, base, "r") == []
    assert export_playable(groups, {}, base, "r") == []
    assert export_playable(groups, {"transform": "nope", "ext": "mp4"},
                           base, "r") == []
    assert export_playable(groups, {"transform": "copy"}, base, "r") == []


def test_export_never_raises_on_unreadable_paths(tmp_path):
    missing = tmp_path / "gone" / "artifact"
    groups = {"sub": [missing]}
    base = {"sub": tmp_path / "gone"}
    assert export_playable(groups, {"transform": "copy", "ext": "bin"},
                           base, "r") == []


def test_export_skips_roles_with_no_base_dir(tmp_path):
    p = _write(tmp_path / "o" / "s", b"data")
    groups = {"sub": [p], "sub9": [p]}
    base = {"sub": tmp_path / "o"}  # sub9 unmapped (defensive)
    written = export_playable(groups, {"transform": "copy", "ext": "bin"},
                              base, "r")
    assert [w.name for w in written] == ["r.sub.bin"]


@pytest.mark.parametrize("blob,min_len", [(b"", 0)])
def test_export_skips_empty_results(tmp_path, blob, min_len):
    p = _write(tmp_path / "o" / "s", b"only-log-lines, no hex payload!\n")
    written = export_playable(groups={"sub": [p]},
                              hint={"transform": "hex_decode", "ext": "mp4"},
                              base_dirs={"sub": tmp_path / "o"},
                              stream_name="r")
    assert written == []


# --- reconstruct_from_mlog (B37 subgroup-permutation fix) ---

from harness.playable import reconstruct_from_mlog


def test_reconstruct_reorders_arrival_into_group_order(tmp_path):
    # arrival order: group0(4B), group2(2B), group1(3B) -> artifact layout
    objects = [(0, 0, 4), (2, 0, 2), (1, 0, 3)]
    data = b"AAAA" + b"CC" + b"BBB"
    out = tmp_path / "rec.mp4"
    stats = reconstruct_from_mlog(data, objects, out)
    assert out.read_bytes() == b"AAAABBBCC"   # sorted by (group, object)
    assert stats["objects_recovered"] == 3
    assert stats["groups_missing"] == []


def test_reconstruct_flags_truncated_tail_object(tmp_path):
    objects = [(0, 0, 4), (1, 0, 6)]
    data = b"AAAA" + b"BB"          # second object cut short
    out = tmp_path / "rec.mp4"
    stats = reconstruct_from_mlog(data, objects, out)
    # New behavior: truncated chunk IS included in output
    assert out.read_bytes() == b"AAAABB"
    assert stats["objects_recovered"] == 2
    assert stats["capture_truncated_at"] == (1, 0, 2)


def test_reconstruct_empty_capture_writes_nothing(tmp_path):
    out = tmp_path / "rec.mp4"
    stats = reconstruct_from_mlog(b"", [(0, 0, 10)], out)
    assert stats["reconstructed_path"] is None
    assert not out.exists()


def test_reconstruct_reports_missing_groups(tmp_path):
    # group 3's payload extends past the capture -> partially recovered, truncated
    objects = [(0, 0, 2), (3, 0, 50)]
    stats = reconstruct_from_mlog(b"XYZ", objects, tmp_path / "r.bin")
    # New behavior: truncated chunk IS included, so group 3 is recovered (partially)
    assert stats["groups_missing"] == []
    assert stats["objects_recovered"] == 2
    assert stats["capture_truncated_at"] == (3, 0, 1)
