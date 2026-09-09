"""object_receipt data-mode tests (testplans/imquic-self.yaml).

Covers the non-media delivery path: imquic's demo moq-pub is a clock generator
whose payload has no ftyp/FLV magic, so evaluate() must score delivery on
"Incoming object:" receipt lines and (with require_draft) assert the negotiated
draft from relay.log. These exercise the pure helpers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.runner import MoQTestRun, load_testplan  # noqa: E402


def test_count_received_objects_counts_lines(tmp_path):
    a = tmp_path / "a"
    a.write_text(
        "Incoming object: 1\n"
        "53756e205365702020352031383a\n"
        "Incoming object: 2\n"
        "53756e205365702020352031383a\n",
        encoding="utf-8")
    b = tmp_path / "b"
    b.write_bytes(b"not an object log")
    assert MoQTestRun._count_received_objects([a, b]) == 2
    assert MoQTestRun._count_received_objects([]) == 0


def test_count_received_objects_ignores_missing_files(tmp_path):
    assert MoQTestRun._count_received_objects([tmp_path / "does-not-exist"]) == 0


def test_negotiated_drafts_parses_per_connection_lines(tmp_path):
    rl = tmp_path / "relay.log"
    rl.write_text(
        "imquic version 0.0.2/alpha\n"
        "WebTransport Protocol(s):\n"
        "  -- moqt-19\n"
        "  -- moqt-18\n"
        "[moq-relay/1]   -- WebTransport (moqt-16)\n"
        "  -- draft-ietf-moq-transport-16\n"
        "[moq-relay/2]   -- WebTransport (moqt-18)\n"
        "  -- draft-ietf-moq-transport-18\n",
        encoding="utf-8")
    drafts = MoQTestRun._negotiated_drafts_from_logs(
        MoQTestRun, [rl])
    assert drafts == ["16", "18"]
    assert "18" in drafts and "16" in drafts
    assert "19" not in drafts  # banner offers don't count


def test_negotiated_drafts_handles_missing_relay_log(tmp_path):
    drafts = MoQTestRun._negotiated_drafts_from_logs(
        MoQTestRun, [tmp_path / "relay.log"])
    assert drafts == []


def test_imquic_self_plan_loads_with_object_receipt_mode():
    plan = load_testplan("testplans/imquic-self.yaml")
    assert plan["data_check"] == "object_receipt"
    assert plan["require_draft"] is True
    assert plan["require_integrity"] is False
    ids = [r["id"] for r in plan["runs"]]
    assert ids == ([f"imquic-self-d{d}" for d in ("16", "17", "18", "19")]
                   + ["imquic-self-d18-loss1pct", "imquic-self-d18-latency100ms"])
    for r in plan["runs"]:
        assert r["pub"]["impl"] == r["relay"]["impl"] == r["sub"]["impl"] == "imquic"
        assert r["pub"]["draft"] == r["sub"]["draft"]