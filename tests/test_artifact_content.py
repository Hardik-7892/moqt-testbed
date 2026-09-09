"""B21 (found-bugs.md) / B2 content-check tests.

Regression coverage for the false pass found in run_20260818_141038: imquic's
stdout diagnostics (version banner, [moq-sub connection logs, "Bye!") must NOT
count as received media. The fixtures below are copies of the real captured
artifacts so the check is tested against ground truth.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.runner import MoQTestRun  # noqa: E402


class FakeRun:
    """_artifact_has_content/_log_ok only touch these two class constants."""
    _FAILURE_TEXT = MoQTestRun._FAILURE_TEXT
    _LOG_TEXT = MoQTestRun._LOG_TEXT


IMQUIC_LOG_ONLY_ARTIFACT = (
    "imquic version 0.0.2/alpha\n"
    "  -- 1f4cbf8a638b80ef40f251fe9787b29f192b0cee (commit hash)\n"
    "  -- Wed Aug 12 00:27:20 UTC 2026 (build time)\n"
    "\n"
    "Using a SUBSCRIBE for the subscription\n"
    "Using namespace '.2f' (1 tuples)\n"
    "Using 'SUBSCRIBE' as the Largest Object filter type\n"
    "\n"
    "[moq-sub] Connecting to remote endpoint\n"
    "[moq-sub/1] Connection established (ALPN=h3)\n"
    "[moq-sub/1] MoQ connection ready\n"
    "[moq-sub/1]   -- draft-ietf-moq-transport-19\n"
    "[moq-sub/1][MoQ]   -- Getting rid of SUBSCRIBE '0'\n"
    "[moq-sub] Shutting down client\n"
    "[moq-sub/1] MoQ connection gone\n"
    "Bye!\n"
)


def test_imquic_log_only_artifact_is_rejected(tmp_path):
    p = tmp_path / "artifact"
    p.write_text(IMQUIC_LOG_ONLY_ARTIFACT, encoding="utf-8")
    assert MoQTestRun._artifact_has_content(FakeRun, p) is False


def test_imquic_banner_alone_is_rejected(tmp_path):
    p = tmp_path / "artifact"
    p.write_text("imquic version 0.0.2/alpha\nBye!\n", encoding="utf-8")
    assert MoQTestRun._artifact_has_content(FakeRun, p) is False


def test_moqrs_ansi_log_plus_media_still_passes(tmp_path):
    # Media magic is checked BEFORE the log-text filters, so a moq-rs artifact
    # that interleaves ANSI tracing with real payload must still pass.
    p = tmp_path / "artifact"
    p.write_bytes(b"\x1b[2m INFO \x1b[0m tracing line\n" + b"\x00\x00\x00\x18ftyp" * 4)
    assert MoQTestRun._artifact_has_content(FakeRun, p) is True


def test_imquic_hex_payload_with_logging_still_passes(tmp_path):
    # imquic with -t hex interleaves metadata + hex payload; the hex magic
    # 66747970 ('ftyp') must win over the log signatures.
    p = tmp_path / "artifact"
    p.write_text("Incoming object: 1\n667479706d6f6f76\n", encoding="utf-8")
    assert MoQTestRun._artifact_has_content(FakeRun, p) is True


def test_real_captured_imquic_relay_sub_artifact_is_rejected(tmp_path):
    # Ground truth: the actual artifact from run_20260818_141038 that false-
    # passed (1035 bytes, zero media).
    src = (Path(__file__).resolve().parent.parent /
           "artifacts/runs/run_20260818_141038/imquic-relay-sub-d18-baseline/"
           "output/imquic-relay-sub-d18-baseline")
    if not src.exists():
        return  # artifacts not shipped with the repo; fixture above covers it
    p = tmp_path / "artifact"
    p.write_bytes(src.read_bytes())
    assert MoQTestRun._artifact_has_content(FakeRun, p) is False
    assert b"ftyp" not in src.read_bytes()
    assert b"FLV" not in src.read_bytes()


def test_imquic_relay_log_bye_does_not_fail_relay(tmp_path):
    # "Bye!" moved into _LOG_TEXT must NOT affect the relay-log check, which
    # only consults _FAILURE_TEXT.
    p = tmp_path / "relay.log"
    p.write_text("imquic relay shutting down\nBye!\n", encoding="utf-8")
    assert MoQTestRun._log_ok(FakeRun, p) is True