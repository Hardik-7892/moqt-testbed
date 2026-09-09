"""B11 (found-bugs.md): real metrics extraction tests.

Covers the moq-rs segment-line counting, the throughput / delivered-fraction
derivation from ctx, the None-when-unmeasurable behavior for moq-rs received
objects, loss-rate gating, and the defensive qlog parser.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.measure import MetricsCollector  # noqa: E402


def test_moqrs_objects_published_counts_segment_lines(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    pub_log = logs / "pub.log"
    pub_log.write_text(
        "timestamp: 1000 segment: 0:0 priority: 127\n"
        "timestamp: 2000 segment: 0:1 priority: 127\n"
        "timestamp: 3000 segment: 1:0 priority: 127\n"
        "some noise with no object\n"
    )
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path, ctx={"pub_impl": "moq-rs"})
    # B31: moq-rs publishes an init object BEFORE the segments, so the
    # metric is init(1) + segment lines(3).
    assert metrics["objects_published"] == 4


def test_moqrs_objects_received_is_none(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "sub.log").write_text("connected with CID: abc\n")
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path, ctx={"sub_impl": "moq-rs"})
    assert metrics["objects_received"] is None
    assert metrics["object_loss_rate"] is None


def test_throughput_and_delivered_fraction_from_ctx(tmp_path):
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path, ctx={
        "delivered_bytes": 1_000_000,
        "original_bytes": 2_000_000,
        "run_duration_s": 10.0,
    })
    assert metrics["throughput_bps"] == 800_000
    assert metrics["delivered_fraction"] == 0.5


def test_no_ctx_leaves_derived_metrics_null(tmp_path):
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path)
    assert metrics["throughput_bps"] is None
    assert metrics["delivered_bytes"] is None
    assert metrics["delivered_fraction"] is None


def test_loss_rate_only_when_both_counts_real(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    pub_log = logs / "pub.log"
    pub_log.write_text("published 100 objects\n")
    sub_log = logs / "sub.log"
    sub_log.write_text("received 95 objects\n")
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path, ctx={"pub_impl": "other", "sub_impl": "other"})
    assert metrics["objects_published"] == 100
    assert metrics["objects_received"] == 95
    assert metrics["object_loss_rate"] == 0.05


def test_qlog_parses_rtt_and_packet_counts(tmp_path):
    qlogs = tmp_path / "qlogs"
    qlogs.mkdir()
    fixture = {
        "qlog_version": "0.3",
        "trace": {
            "events": [
                {"name": "transport:packet_sent", "data": {"packet_type": "1RTT"}},
                {"name": "transport:packet_sent", "data": {"packet_type": "1RTT"}},
                {"name": "transport:packet_received", "data": {"packet_type": "1RTT"}},
                {"name": "transport:packet_lost", "data": {}},
                {"name": "recovery:metrics_updated",
                 "data": {"latest_rtt": 0.0125}},
            ]
        },
    }
    (qlogs / "sub.sqlog").write_text(json.dumps(fixture))
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path)
    assert metrics["rtt_estimate_ms"] == 12.5
    assert metrics["packets_sent"] == 2
    assert metrics["packets_received"] == 1
    assert metrics["packets_lost"] == 1
    assert metrics["packet_loss_rate"] == 0.5


def test_qlog_parses_json_seq_format(tmp_path):
    # moq-rs writes qlog in JSON-SEQ: each line is a separate JSON record
    # prefixed by the record separator 0x1e (see run_20260818_181221).
    qlogs = tmp_path / "qlogs"
    qlogs.mkdir()
    lines = [
        '{"qlog_version":"0.3","qlog_format":"JSON-SEQ"}',
        '{"time":0.0,"name":"transport:packet_received",'
        '"data":{"header":{"packet_type":"initial"}}}',
        '{"time":0.0,"name":"recovery:metrics_updated",'
        '"data":{"min_rtt":0.000333,"latest_rtt":0.000333}}',
        '{"time":1.0,"name":"transport:packet_sent",'
        '"data":{"header":{"packet_type":"1RTT","packet_number":0}}}',
        '{"time":1.0,"name":"transport:packet_sent",'
        '"data":{"header":{"packet_type":"1RTT","packet_number":1}}}',
        '{"time":2.0,"name":"recovery:metrics_updated",'
        '"data":{"min_rtt":0.0253,"latest_rtt":0.0253}}',
    ]
    (qlogs / "sub_server.qlog").write_text(
        "\x1e" + "\n\x1e".join(lines) + "\n")
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path)
    assert metrics["packets_sent"] == 2
    assert metrics["packets_received"] == 1
    # seconds -> ms, and the LAST rtt estimate wins
    assert metrics["rtt_estimate_ms"] == 25.3
    assert metrics["packets_lost"] == 0


def test_qlog_missing_or_garbage_is_tolerated(tmp_path):
    qlogs = tmp_path / "qlogs"
    qlogs.mkdir()
    (qlogs / "bad.sqlog").write_text("not json{")
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path)
    assert metrics["rtt_estimate_ms"] is None
    assert metrics["packets_sent"] == 0
    assert metrics["packets_lost"] == 0
    assert metrics["packet_loss_rate"] is None


def test_no_qlog_dir_returns_empty_defaults(tmp_path):
    coll = MetricsCollector()
    metrics = coll.collect(tmp_path)
    assert metrics["rtt_estimate_ms"] is None
    assert metrics["packets_sent"] == 0
    assert metrics["packet_loss_rate"] is None
