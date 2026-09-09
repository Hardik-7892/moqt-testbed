import time

from harness.runner import MoQTestRun


def _runner(tmp_path, pub_logs, segment_timeout=10.0, floor=4.0):
    runner = MoQTestRun.__new__(MoQTestRun)
    runner.logs_dir = tmp_path
    runner.config = {"pub": {"impl": "moq-rs"}}
    logs = []
    runner._log = logs.append
    for name, text in pub_logs.items():
        (tmp_path / name).write_text(text)
    return runner, logs, segment_timeout, floor


def test_gate_sees_pub_s0_log(tmp_path):
    # B44 regression: pub logs are pub_s0.log, not pub.log. The gate must
    # find the first segment there and let the sub join while the publisher
    # is still live (not burn the deadline then join after publish).
    runner, logs, st, floor = _runner(
        tmp_path,
        {"relay.log": "serving PUBLISH_NAMESPACE: etc",
         "pub_s0.log": "2026-09-06T00:00:34Z timestamp: 0 segment: 0:0 priority: 127"},
        segment_timeout=0.9, floor=0.5,
    )
    t0 = time.time()
    runner._wait_for_pub_ready(timeout=2.0, floor=floor, segment_timeout=st)
    assert time.time() - t0 < 1.0
    assert any("deterministic" in m for m in logs)


def test_gate_times_out_without_segment(tmp_path):
    runner, logs, st, floor = _runner(
        tmp_path,
        {"relay.log": "serving PUBLISH_NAMESPACE: etc",
         "pub_s0.log": "connected with CID: abc (use this to look up qlog/mlog)"},
        segment_timeout=0.6, floor=0.3,
    )
    t0 = time.time()
    runner._wait_for_pub_ready(timeout=2.0, floor=floor, segment_timeout=st)
    assert time.time() - t0 < 2.5
    assert any("no first-segment line" in m for m in logs)
    assert not any("deterministic" in m for m in logs)