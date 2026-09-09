#!/usr/bin/env python3
import json

from harness.report import ReportGenerator, _integrity_badge, _transport_label


def _summary() -> dict:
    integrity = {
        "expected_objects": [{"kind": "init", "bytes": 786},
                             {"kind": "segment", "bytes": 7032}],
        "received_objects": [{"group": 0, "object": 0, "bytes": 786},
                             {"group": 0, "object": 1, "bytes": 7000}],
        "per_object_match": False,
        "delivered_bytes": 7818, "expected_bytes": 7818,
        "sha256_expected": "e" * 64, "sha256_delivered": "d" * 64,
        "sha256_match": False, "byte_identical_bytes": 7786,
        "byte_identical_pct": 99.59, "verdict": "good",
    }
    return {
        "plan": "smoke", "timestamp": "2026-08-18T00:00:00", "total": 1,
        "passed": 1, "partial": 0, "failed": 0,
        "results": [{
            "run_id": "r1",
            "config": {"pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
                       "sub": {"impl": "moq-rs"},
                       "network": {"bw": 100, "delay": "0ms", "loss": 0}},
            "metrics": {},
            "evaluation": {
                "status": "pass",
                "stats": {"coverage_pct": 99.15, "integrity": integrity},
                "metrics": {
                    "objects_published": 1, "rtt_estimate_ms": 24.86,
                    "throughput_bps": 21910,
                },
            },
        }],
    }


def test_report_reads_metrics_from_evaluation(tmp_path):
    # B11 metrics live in evaluation.metrics; the report must not read the
    # top-level metrics dict (which run() leaves empty).
    (tmp_path / "summary.json").write_text(json.dumps(_summary()))
    html = ReportGenerator(tmp_path).generate_html_report()
    assert ">1/" in html or ">1" in html
    assert "24.86" in html
    assert "0.02 Mbps" in html


def test_report_shows_good_verdict(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps(_summary()))
    html = ReportGenerator(tmp_path).generate_html_report()
    assert "good 99.59%" in html
    assert "init=786+seg=7032" in html


def test_report_confusion_matrix_counts(tmp_path):
    # B43 expectations live in evaluation.confusion; the dashboard must render
    # the I1 matrix from there (was silently 0/0/0/0 when read from top level).
    summary = _summary()
    summary["results"] = [
        {"run_id": "a", "config": {}, "evaluation": {"status": "pass", "expected": "pass", "confusion": "TP"}},
        {"run_id": "b", "config": {}, "evaluation": {"status": "fail", "expected": "fail", "confusion": "TN"}},
        {"run_id": "c", "config": {}, "evaluation": {"status": "fail", "expected": "pass", "confusion": "FN"}},
        {"run_id": "d", "config": {}, "evaluation": {"status": "fail", "expected": "fail", "confusion": "TN"}},
        {"run_id": "e", "config": {}, "evaluation": {"status": "fail", "expected": "fail", "confusion": "TN"}},
    ]
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    html = ReportGenerator(tmp_path).generate_html_report()
    assert ">1 TP<" in html
    assert ">3 TN<" in html
    assert ">0 FP<" in html
    assert ">1 FN<" in html


def test_report_confusion_from_top_level_fallback(tmp_path):
    summary = _summary()
    summary["results"] = [{
        "run_id": "a", "config": {},
        "confusion": "TN",
        "evaluation": {"status": "fail", "expected": "fail"},
    }]
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    html = ReportGenerator(tmp_path).generate_html_report()
    assert ">1 TN<" in html


def test_legacy_report_confusion_matrix(tmp_path):
    summary = _summary()
    summary["results"] = [{
        "run_id": "a", "config": {},
        "evaluation": {"status": "fail", "expected": "fail", "confusion": "TN"},
    }]
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    legacy = ReportGenerator(tmp_path)._generate_legacy_report()
    assert "Confusion Matrix (I1)" in legacy
    assert "TN" in legacy and "1 TN" in legacy


def test_transport_label_collects_protos():
    # Phase 3 (D13): distinct protos across subs joined, legacy-safe empty.
    assert _transport_label({}) == ""
    assert _transport_label({"s": {"fetch_protos": {}}}) == ""
    assert _transport_label({"s": {}}) == ""
    per_sub = {"s1": {"fetch_protos": {"h3": 60}},
               "s2": {"fetch_protos": {"h3": 58, "tcp-fallback": 2}}}
    assert _transport_label(per_sub) == "h3+tcp-fallback"


def test_streaming_badge_shows_transport():
    # Phase 3 (D13): an h3 row served over TCP fallback must say so.
    integrity = {
        "verdict": "exact", "streaming": True, "byte_identical_pct": 100.0,
        "per_sub": {"sub": {"segments_fetched": 60, "segments_expected": 60,
                            "fetch_protos": {"tcp-fallback": 61}}},
    }
    html = _integrity_badge(integrity)
    assert "via tcp-fallback" in html
    # Legacy integrity dicts without the label render unchanged.
    legacy = {
        "verdict": "exact", "streaming": True, "byte_identical_pct": 100.0,
        "per_sub": {"sub": {"segments_fetched": 60,
                            "segments_expected": 60}},
    }
    assert "via " not in _integrity_badge(legacy)