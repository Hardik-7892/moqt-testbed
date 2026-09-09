"""Phase 4: analysis/aggregate.py unit tests (Docker-free)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.aggregate import aggregate, jain, percentile  # noqa: E402


def test_percentile():
    assert percentile([], 50) is None
    assert percentile([7], 50) == 7.0
    assert percentile([10, None, 20], 50) == 15.0
    assert percentile([0, 100], 95) == 95.0
    assert percentile([1, 2, 3, 4], 50) == 2.5


def test_jain():
    assert jain([]) is None
    assert jain([10]) is None
    assert jain([10, 10, 10]) == 1.0
    assert abs(jain([5, 15]) - 0.8) < 1e-9
    assert 0.0 < jain([11517, 11517, 11241]) <= 1.0


def _batch(tmp_path, name, results):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps({
        "plan": "fairness", "results": results}))
    return str(d)


def _result(rid, status="partial", verdict="mismatch", thr=2299, rtt=30.0,
            ttfo=None, dfrac=0.32, subs=(11517, 11517, 11517),
            mlog_sum=None, duration=120.0):
    per_sub = {f"sub{i+1}": {"artifact_bytes": b}
               for i, b in enumerate(subs)}
    return {
        "run_id": rid, "status": status,
        "metrics": {"throughput_bps": thr, "rtt_estimate_ms": rtt,
                    "time_to_first_object_ms": ttfo,
                    "delivered_fraction": dfrac},
        "evaluation": {"stats": {
            "run_duration_s": duration,
            "delivered_bytes": (mlog_sum if mlog_sum is not None
                                else sum(subs)),
            "integrity": {"verdict": verdict, "per_sub": per_sub}}},
    }


def test_aggregate_pools_repeats(tmp_path):
    b1 = _batch(tmp_path, "run_A", [_result("r1", thr=2000, rtt=20.0)])
    b2 = _batch(tmp_path, "run_B", [_result("r1", thr=3000, rtt=40.0)])
    rows, warnings = aggregate([b1, b2], min_repeats=3)
    assert len(warnings) == 1  # only 2 repeats, want 3
    (row,) = rows
    assert row["n"] == 2
    assert row["throughput_p50"] == 2500.0
    assert row["rtt_p50"] == 30.0
    assert row["ttfo_n_null"] == 2  # honestly counted, not hidden
    assert row["jain_min"] == 1.0 and row["jain_p50"] == 1.0


def test_aggregate_jain_per_repeat_not_pooled(tmp_path):
    # Repeat 1 equal subs (J=1.0), repeat 2 skewed (J<1.0): min must catch it.
    # (A single live sub yields Jain None by design — fairness needs >=2.)
    b1 = _batch(tmp_path, "run_A", [_result("r1", subs=(10, 10, 10))])
    b2 = _batch(tmp_path, "run_B", [_result("r1", subs=(30, 10, 10))])
    rows, _ = aggregate([b1, b2])
    (row,) = rows
    assert row["jain_min"] < 1.0
    assert row["jain_p50"] is not None
    assert row["jain_n"] == 2


def test_aggregate_single_live_sub_jain_none(tmp_path):
    b1 = _batch(tmp_path, "run_A", [_result("r1", subs=(30, 0, 0))])
    rows, _ = aggregate([b1])
    (row,) = rows
    assert row["jain_min"] is None
    assert row["jain_n"] == 0


def test_aggregate_artifact_throughput_restart_proof(tmp_path):
    # Same artifacts, mlog inflated 12x in repeat 2 (B38 restart shape):
    # artifact throughput stable, mlog divergence warns.
    b1 = _batch(tmp_path, "run_A",
                [_result("r1", subs=(11241, 11241, 11241), mlog_sum=34551,
                         duration=20.0)])
    b2 = _batch(tmp_path, "run_B",
                [_result("r1", subs=(11241, 11241, 11241), mlog_sum=138204,
                         duration=20.0)])
    rows, warnings = aggregate([b1, b2])
    (row,) = rows
    expect_thr = 3 * 11241 * 8 / 20.0
    assert row["artifact_thr_p50"] == expect_thr
    assert row["artifact_thr_p95"] == expect_thr
    assert row["artifact_thr_n"] == 2
    assert any("diverge" in w and "r1" in w for w in warnings)


def test_aggregate_no_divergence_no_warning(tmp_path):
    b1 = _batch(tmp_path, "run_A", [_result("r1")])
    _, warnings = aggregate([b1])
    assert not [w for w in warnings if "diverge" in w]


def test_aggregate_mixed_plans_warns(tmp_path):
    b1 = _batch(tmp_path, "run_A", [_result("r1")])
    d = Path(b1)
    s = json.loads((d / "summary.json").read_text())
    s["plan"] = "other"
    (d / "summary.json").write_text(json.dumps(s))
    b2 = _batch(tmp_path, "run_B", [_result("r1")])
    _, warnings = aggregate([b1, b2])
    assert any("mix plans" in w for w in warnings)
