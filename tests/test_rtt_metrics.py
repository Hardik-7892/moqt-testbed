import json
from pathlib import Path

from harness.measure import MetricsCollector


def _write(d, name, data):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(data)
    return d


def _picoquic_qlog(events):
    return json.dumps({
        "qlog_version": "0.3",
        "title": "picoquic",
        "traces": [{
            "vantage_point": {"name": "relay", "type": "server"},
            "events": events,
        }],
    })


def test_picoquic_qlog_rtt_microseconds(tmp_path):
    events = [
        [4200, "recovery", "metrics_updated",
         {"cwnd": 15360, "smoothed_rtt": 20910, "min_rtt": 18900,
          "latest_rtt": 19100}],
        [4500, "recovery", "metrics_updated",
         {"bytes_in_flight": 0, "smoothed_rtt": 20770, "min_rtt": 18300,
          "latest_rtt": 18300}],
        [4600, "recovery", "packet_lost",
         {"packet_type": "1RTT", "packet_number": 14, "trigger":
          "reordering_threshold"}],
        [4700, "transport", "packet_sent",
         {"packet_type": "1RTT", "packet_number": 15}],
        [4800, "transport", "packet_received",
         {"packet_type": "1RTT", "packet_number": 16}],
    ]
    d = _write(tmp_path, "a1b2.server.qlog", _picoquic_qlog(events))

    m = MetricsCollector()._parse_qlog(d)

    assert m["rtt_estimate_ms"] == 20.77
    assert m["rtt_min_ms"] == 18.3
    assert m["rtt_max_ms"] == 20.91
    assert m["packets_lost"] == 1
    assert m["packets_sent"] == 1
    assert m["packets_received"] == 1


def test_picoquic_latest_rtt_fallback_when_no_smoothed(tmp_path):
    events = [
        [1000, "recovery", "metrics_updated",
         {"latest_rtt": 25000}],
        [1200, "recovery", "metrics_updated",
         {"latest_rtt": 24000}],
    ]
    d = _write(tmp_path, "c3d4.server.qlog", _picoquic_qlog(events))

    m = MetricsCollector()._parse_qlog(d)

    assert m["rtt_estimate_ms"] == 24.0


def test_moqrs_sqlog_rtt_seconds(tmp_path):
    records = [
        "\x1e" + json.dumps({"time": 0, "event": {"name":
            "metrics:smoothed_rtt", "data": {"min_rtt": 0.0102,
            "smoothed_rtt": 0.0204, "latest_rtt": 0.0204,
            "rtt_variance": 0.0001}}}),
        "\x1e" + json.dumps({"time": 1, "event": {"name":
            "metrics:latest_rtt", "data": {"latest_rtt": 0.0198}}}),
    ]
    d = _write(tmp_path, "e5f6.sqlog", "\n".join(records))

    m = MetricsCollector()._parse_qlog(d)

    assert m["rtt_estimate_ms"] == 20.4
    assert m["rtt_min_ms"] == 10.2
    assert m["rtt_max_ms"] == 20.4


def test_prefers_later_smoothed_over_later_latest(tmp_path):
    samples = [
        ("smoothed_rtt", 20.0),
        ("smoothed_rtt", 19.0),
        ("latest_rtt", 500.0),
    ]
    est = MetricsCollector._rtt_estimate(samples)
    assert est == 19.0


def test_missing_qlog_dir_returns_defaults(tmp_path):
    m = MetricsCollector()._parse_qlog(tmp_path / "nope")
    assert m["rtt_estimate_ms"] is None
    assert m["rtt_min_ms"] is None
    assert m["packets_sent"] == 0


def test_truncated_picoquic_json_tolerated(tmp_path):
    bad = _picoquic_qlog([])[:80]
    d = _write(tmp_path, "trunc.server.qlog", bad)

    m = MetricsCollector()._parse_qlog(d)

    assert m["rtt_estimate_ms"] is None
    assert m["rtt_min_ms"] is None