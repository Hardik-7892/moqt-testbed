"""B13 (found-bugs.md) / I3 (improvements.md): completion-detection tests.

These exercise _poll_artifact_completion, _total_artifact_bytes,
_completion_artifact_paths and _wait_for_completion without Docker, following
the pattern set by the B18 extraction (_sub_launch_redirect).
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.runner import MoQTestRun  # noqa: E402

TOP = {"bw": 100, "delay": "10ms", "loss": 0}


def make_run(batch_dir, topology="basic", network=None, run_id="test-run-1",
             sub_impl="moq-rs", media="sample.mp4"):
    net = dict(TOP)
    if network:
        net.update(network)
    run_config = {
        "id": run_id,
        "topology": topology,
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": sub_impl, "draft": 18, "tag": "moq-rs/client:18"},
        "network": net,
    }
    if topology == "chain":
        run_config["relay_a"] = run_config["relay"]
        run_config["relay_b"] = run_config["relay"]
    return MoQTestRun(run_config, TOP, batch_dir, media_file=media,
                      default_test_duration=15)


def test_total_artifact_bytes_counts_existing_files(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_bytes(b"x" * 10)
    assert MoQTestRun._total_artifact_bytes([a, b]) == 10


def test_poll_times_out_on_empty_file(tmp_path):
    p = tmp_path / "empty"
    p.write_bytes(b"")
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=0.5, poll_interval=0.1, quiet_polls=2)
    assert completed is False
    assert reason == "time limit reached"
    assert final == 0


def test_poll_returns_quiesced_after_growth_stops(tmp_path):
    p = tmp_path / "growing"
    p.write_bytes(b"")
    stop = time.time() + 0.4

    def grow():
        while time.time() < stop:
            with p.open("ab") as f:
                f.write(b"x" * 100)
            time.sleep(0.05)

    t = threading.Thread(target=grow)
    t.start()
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=5.0, poll_interval=0.1, quiet_polls=3)
    t.join()
    assert completed is True
    assert reason == "delivery quiesced"
    assert final > 0


def test_poll_never_quiesces_below_min_bytes(tmp_path):
    # B13 v2: a pause below min_bytes is a mid-transfer stall, not completion.
    p = tmp_path / "stalled"
    p.write_bytes(b"x" * 100)
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=1.0, poll_interval=0.1, quiet_polls=2, min_bytes=500)
    assert completed is False
    assert reason == "time limit reached"


def test_poll_quiesces_above_min_bytes(tmp_path):
    p = tmp_path / "done"
    p.write_bytes(b"x" * 600)
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=5.0, poll_interval=0.1, quiet_polls=2, min_bytes=500)
    assert completed is True
    assert reason == "delivery quiesced"
    assert final == 600


def test_poll_min_bytes_none_keeps_old_behavior(tmp_path):
    # Without min_bytes a no-growth pause still counts as completion.
    p = tmp_path / "done"
    p.write_bytes(b"x" * 50)
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=5.0, poll_interval=0.1, quiet_polls=2)
    assert completed is True
    assert reason == "delivery quiesced"


def test_poll_quiesces_never_fires_for_zero_bytes(tmp_path):
    p = tmp_path / "stays-zero"
    p.write_bytes(b"")
    completed, reason, final = MoQTestRun._poll_artifact_completion(
        [p], duration=0.5, poll_interval=0.1, quiet_polls=1)
    assert completed is False


def test_completion_paths_basic_uses_artifact_contract(tmp_path):
    run = make_run(tmp_path / "batch")
    paths = run._completion_artifact_paths()
    assert paths == [run.output_dir / "test-run-1"]


def test_completion_paths_fanout_per_sub(tmp_path):
    run = make_run(tmp_path / "batch", topology="fanout",
                   network={"num_subscribers": 2})
    paths = run._completion_artifact_paths()
    assert paths == [run.output_dir / "sub1" / "test-run-1",
                     run.output_dir / "sub2" / "test-run-1"]


def test_wait_for_completion_marks_completed(tmp_path):
    run = make_run(tmp_path / "batch", network={"quiet_period": 2})
    run.output_dir.mkdir(parents=True, exist_ok=True)
    # Full delivery: write >=0.95*source size (handles both 7885 and 107971 Timer variants)
    src = Path(__file__).resolve().parent.parent / "testdata" / "sample.mp4"
    expected = src.stat().st_size if src.exists() else 7885
    size = int(expected * 0.95) + 10
    (run.output_dir / "test-run-1").write_bytes(b"x" * size)
    run._wait_for_completion()
    assert run.completed is True
    assert run.completion_reason == "delivery quiesced"
    assert run.run_duration_s is not None
    assert run.run_duration_s < 10


def test_wait_for_completion_time_limit_below_threshold(tmp_path):
    # B13 v2: a run whose artifact never reaches completion_coverage of the
    # source runs to the cap even if it stops growing -- no false completion.
    run = make_run(tmp_path / "batch", network={"quiet_period": 2})
    run.output_dir.mkdir(parents=True, exist_ok=True)
    (run.output_dir / "test-run-1").write_bytes(b"x" * 100)
    run.test_duration = 1
    run._wait_for_completion()
    assert run.completed is False
    assert run.completion_reason == "time limit reached"
    assert run.run_duration_s >= 1


def test_wait_for_completion_respects_completion_coverage(tmp_path):
    run = make_run(tmp_path / "batch",
                   network={"quiet_period": 2, "completion_coverage": 0.5})
    run.output_dir.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve().parent.parent / "testdata" / "sample.mp4"
    expected = src.stat().st_size if src.exists() else 7885
    size = int(expected * 0.5) + 10
    (run.output_dir / "test-run-1").write_bytes(b"x" * size)
    run._wait_for_completion()
    assert run.completed is True
    assert run.completion_reason == "delivery quiesced"
    assert run.run_duration_s < 10


def test_wait_for_completion_no_source_keeps_old_behavior(tmp_path):
    # No local media source -> min_bytes None -> no-growth still completes.
    run = make_run(tmp_path / "batch", network={"quiet_period": 2},
                   media="does-not-exist.mp4")
    run.output_dir.mkdir(parents=True, exist_ok=True)
    (run.output_dir / "test-run-1").write_bytes(b"x" * 100)
    run._wait_for_completion()
    assert run.completed is True
    assert run.completion_reason == "delivery quiesced"


def test_wait_for_completion_respects_time_limit(tmp_path):
    run = make_run(tmp_path / "batch", network={"quiet_period": 2})
    run.output_dir.mkdir(parents=True, exist_ok=True)
    (run.output_dir / "test-run-1").write_bytes(b"")
    run.test_duration = 1
    run._wait_for_completion()
    assert run.completed is False
    assert run.completion_reason == "time limit reached"
    assert run.run_duration_s >= 1


def test_evaluate_stats_include_completion_flag(tmp_path):
    run = make_run(tmp_path / "batch")
    run.logs_dir.mkdir(parents=True, exist_ok=True)
    run.output_dir.mkdir(parents=True, exist_ok=True)
    (run.output_dir / "test-run-1").write_bytes(b"FLV")
    for name in ("pub.log", "sub.log", "relay.log"):
        (run.logs_dir / name).write_text("ok\n")
    run.completed = True
    run.completion_reason = "delivery quiesced"
    run.run_duration_s = 3.5
    result = run.evaluate()
    assert result["stats"]["completed"] is True
    assert result["stats"]["completion_reason"] == "delivery quiesced"
    assert result["stats"]["run_duration_s"] == 3.5
    assert result["stats"]["delivered_bytes"] == 3


def _write_run(tmp_path, media="sample.mp4", size=3, completed=False,
               network=None):
    run = make_run(tmp_path / "batch", media=media, network=network)
    run.logs_dir.mkdir(parents=True, exist_ok=True)
    run.output_dir.mkdir(parents=True, exist_ok=True)
    (run.output_dir / "test-run-1").write_bytes(b"FLV" * (size // 3))
    for name in ("pub.log", "sub.log", "relay.log"):
        (run.logs_dir / name).write_text("ok\n")
    run.completed = completed
    run.completion_reason = "delivery quiesced" if completed else "time limit reached"
    run.run_duration_s = 3.0 if completed else 15.0
    return run


def test_evaluate_partial_below_coverage(tmp_path):
    # B24: real media that only reached 3/7885 (0.04%) must be 'partial'.
    run = _write_run(tmp_path)
    result = run.evaluate()
    assert result["status"] == "partial"
    assert result["stats"]["delivered_full"] is False
    assert result["checks"]["sub_received_data"] is True


def test_evaluate_pass_at_coverage(tmp_path):
    src = Path(__file__).resolve().parent.parent / "testdata" / "sample.mp4"
    expected = src.stat().st_size if src.exists() else 7885
    size = int(expected * 0.95) + 10
    run = _write_run(tmp_path, size=size)
    result = run.evaluate()
    assert result["status"] == "pass"
    assert result["stats"]["delivered_full"] is True


def test_evaluate_pass_with_no_source_to_compare(tmp_path):
    # No local source -> coverage None -> cannot judge fullness -> pass.
    run = _write_run(tmp_path, media="does-not-exist.mp4")
    result = run.evaluate()
    assert result["stats"]["coverage_pct"] is None
    assert result["stats"]["delivered_full"] is True
    assert result["status"] == "pass"


def test_evaluate_fail_with_no_media(tmp_path):
    run = _write_run(tmp_path)
    (run.output_dir / "test-run-1").write_text("Error: timed out\n")
    result = run.evaluate()
    assert result["checks"]["sub_received_data"] is False
    assert result["status"] == "fail"

# --- Worst-subscriber rule (fanout/chainfanout, MoQ): run_20260910_113155 ---
# The moq-rs relay serves 1 of N subscribers while the rest sit at 0 B, yet
# the row read pass on SUM-based coverage. Status must follow the WORST
# subscriber: zero-byte worst reads fail, short-but-correct worst reads
# partial, all full reads pass. Single-subscriber rows keep legacy behavior
# (covered by the B24 tests above).


def _write_fanout_run(tmp_path, per_sub_sizes, media="sample.mp4"):
    """Fanout run with N subscribers holding the given artifact sizes.

    sub artifacts carry FLV magic so they count as real media; a zero size
    writes an empty file (starved viewer). Returns the MoQTestRun.
    """
    n = len(per_sub_sizes)
    net = dict(TOP, num_subscribers=n)
    run_config = {
        "id": "test-fanout-1",
        "topology": "fanout",
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "network": net,
    }
    run = MoQTestRun(run_config, TOP, tmp_path / "batch", media_file=media,
                     default_test_duration=15)
    run.logs_dir.mkdir(parents=True, exist_ok=True)
    run.output_dir.mkdir(parents=True, exist_ok=True)
    for i, size in enumerate(per_sub_sizes, start=1):
        role_dir = run.output_dir / f"sub{i}"
        role_dir.mkdir(parents=True, exist_ok=True)
        if size > 0:
            (role_dir / "test-fanout-1").write_bytes(b"FLV" + b"x" * size)
        else:
            (role_dir / "test-fanout-1").write_bytes(b"")
        (run.logs_dir / f"sub{i}_s0.log").write_text("ok\n")
    for name in ("pub.log", "relay.log"):
        (run.logs_dir / name).write_text("ok\n")
    run.completed = True
    run.completion_reason = "delivery quiesced"
    run.run_duration_s = 3.0
    return run


def _full_size():
    src = Path(__file__).resolve().parent.parent / "testdata" / "sample.mp4"
    expected = src.stat().st_size if src.exists() else 7885
    return int(expected * 0.95) + 10


def test_evaluate_fanout_starved_worst_reads_fail(tmp_path):
    # 1 of 2 served (the run_20260910_113155 shape): fail, not pass.
    run = _write_fanout_run(tmp_path, [_full_size(), 0])
    result = run.evaluate()
    assert result["status"] == "fail"
    assert result["stats"]["delivered_full"] is False
    assert result["checks"]["all_subs_served"] is False
    assert result["stats"]["worst_sub_role"] == "sub2"


# --- B37 addendum: publisher first-segment join gate ---
    assert result["stats"]["worst_sub_coverage_pct"] == 0


def test_evaluate_fanout_all_served_passes(tmp_path):
    run = _write_fanout_run(tmp_path, [_full_size(), _full_size()])
    result = run.evaluate()
    assert result["status"] == "pass"
    assert result["stats"]["delivered_full"] is True
    assert result["checks"]["all_subs_served"] is True


def test_evaluate_fanout_short_worst_reads_partial(tmp_path):
    # Worst viewer short-but-correct (real bytes below bar): partial.
    run = _write_fanout_run(tmp_path, [_full_size(), 60])
    result = run.evaluate()
    assert result["status"] == "partial"
    assert result["stats"]["delivered_full"] is False
    assert result["checks"]["all_subs_served"] is True
    assert result["stats"]["worst_sub_role"] == "sub2"

class TestPubSegmentGate:
    """_wait_for_pub_ready must gate the sub join on the publisher's own
    first-segment evidence (moq-rs). Without it, BBB-scale media raced:
    subs joined pre-group -> "Track not found" death or late joins that
    skipped groups (run_20260825_235302 / _235753)."""

    def test_segment_line_detected(self):
        log = ("2026-08-25T23:22:56Z INFO moq_pub::media: catalog: {...}\n"
               "timestamp: 0 segment: 0:0 priority: 127\n")
        assert MoQTestRun._pub_saw_first_segment(log) is True

    def test_catalog_only_is_not_enough(self):
        log = "INFO moq_pub::media: catalog: { ...tracks... }\n"
        assert MoQTestRun._pub_saw_first_segment(log) is False

    def test_empty_or_missing_log(self):
        assert MoQTestRun._pub_saw_first_segment("") is False

    def test_gate_impls_constant(self):
        assert "moq-rs" in MoQTestRun.PUB_SEGMENT_LOG_IMPLS
        assert "imquic" not in MoQTestRun.PUB_SEGMENT_LOG_IMPLS


# --- B38: subscriber join-death detection ---

class TestSubJoinDeath:
    def test_moqrs_track_not_found(self):
        log = ("WARN moq_sub::media: failed to subscribe to init track: "
               "Closed(16)\nError: media error\n")
        assert MoQTestRun._sub_join_failed(log) is True

    def test_imquic_subscribe_error(self):
        assert MoQTestRun._sub_join_failed(
            "Got an error subscribing via ID 0: error 16") is True

    def test_healthy_join_not_flagged(self):
        log = ("INFO moq_sub::media: found track 1.m4s\n"
               "INFO moq_sub::media: playing 1 tracks\n")
        assert MoQTestRun._sub_join_failed(log) is False

    def test_normal_shutdown_not_flagged(self):
        assert MoQTestRun._sub_join_failed("Bye!\n") is False

    def test_empty_log(self):
        assert MoQTestRun._sub_join_failed("") is False
