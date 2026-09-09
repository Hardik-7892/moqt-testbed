#!/usr/bin/env python3
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


class MetricsCollector:
    """
    Collects and computes MoQT performance metrics from log files and the
    received artifact. Follows the draft-evens-moq-bench metric vocabulary.

    B11 (see found-bugs.md): the old pipeline was a stub — it matched phrases
    implementations never print and looked for qlogs that never existed, so
    every metric came back null/0. This version:
      - counts what implementations actually log (moq-rs pub.log "segment:"
        lines for objects_published),
      - derives throughput / delivered_bytes / delivered_fraction from the
        received artifact size and the real run duration (runner passes them
        in via ctx),
      - parses real qlog files (moq-rs relay --qlog-dir) for rtt/packet stats,
      - parses pcap files (tshark) for wire-level QUIC metrics (I13),
      - keeps the best-effort regexes for setup/first-object timing.
    """

    # moq-rs moq-pub logs one line per published object:
    #   timestamp: 11345600 segment: 191:0 priority: 127
    MOQRS_SEGMENT_RE = re.compile(r"\bsegment:\s*\d+:\d+\b")

    def collect(self, run_dir: Path,
                ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ctx = ctx or {}
        metrics = {
            "setup_time_ms": self._setup_time(run_dir),
            "time_to_first_object_ms": self._time_to_first_object(run_dir),
            "objects_published": None,
            "objects_received": None,
            "object_loss_rate": None,
            "throughput_bps": None,
            "jitter_ms": None,
        }
        # Multi-stream: pub logs are pub_s0.log, pub_s1.log, etc.
        pub_logs = sorted((run_dir / "logs").glob("pub*.log"))
        pub_log = pub_logs[0] if pub_logs else run_dir / "logs" / "pub.log"
        sub_log = run_dir / "logs" / "sub.log"

        if pub_log.exists():
            metrics["objects_published"] = self._objects_published(
                pub_log, ctx.get("pub_impl"))
        if sub_log.exists():
            metrics["objects_received"] = self._objects_received(
                sub_log, ctx.get("sub_impl"))

        pub_count = metrics["objects_published"]
        sub_count = metrics["objects_received"]
        if pub_count is not None and sub_count is not None and pub_count > 0:
            metrics["object_loss_rate"] = round((pub_count - sub_count) / pub_count, 6)

        metrics.update(self._parse_qlog(run_dir / "qlogs"))

        # I15: TTFO from mlog (first object timestamp - pub start time)
        ttfo = self._ttfo_from_mlog(run_dir, ctx.get("pub_start_time"))
        if ttfo is not None:
            metrics["time_to_first_object_ms"] = ttfo

        # I13: pcap/wire-level metrics (tshark)
        metrics.update(self._parse_pcap(run_dir))

        delivered = ctx.get("delivered_bytes")
        duration = ctx.get("run_duration_s")
        if delivered is not None and duration:
            metrics["throughput_bps"] = int(delivered * 8 / duration)
        metrics["delivered_bytes"] = delivered
        original = ctx.get("original_bytes")
        metrics["delivered_fraction"] = (
            round(delivered / original, 6)
            if delivered is not None and original else None
        )

        return metrics

    def _setup_time(self, run_dir: Path) -> Optional[float]:
        sub_log = run_dir / "logs" / "sub.log"
        if not sub_log.exists():
            return None
        text = sub_log.read_text(errors="replace")
        matches = re.findall(r"SETUP.*?(\d+\.?\d*)ms", text, re.IGNORECASE)
        return float(matches[0]) if matches else None

    def _time_to_first_object(self, run_dir: Path) -> Optional[float]:
        sub_log = run_dir / "logs" / "sub.log"
        if not sub_log.exists():
            return None
        text = sub_log.read_text(errors="replace")
        matches = re.findall(r"(?:first.object|time.to.first).*?(\d+\.?\d*)ms",
                             text, re.IGNORECASE)
        return float(matches[0]) if matches else None

    def _ttfo_from_mlog(self, run_dir: Path, pub_start_time: Optional[str]) -> Optional[float]:
        """I15: Compute TTFO from mlog first_object_ts - pub_start_time.

        Args:
            run_dir: Path to run directory containing qlogs
            pub_start_time: ISO format timestamp string from ctx["pub_start_time"]

        Returns:
            TTFO in milliseconds, or None if not computable.
        """
        if not pub_start_time:
            return None
        try:
            from harness.verify import mlog_subscriber_connections
            conns = mlog_subscriber_connections(run_dir / "qlogs")
            if not conns:
                return None
            # Use the earliest first_object_ts across all subscriber connections
            first_ts = min(c.get("first_object_ts", float("inf")) for c in conns
                           if c.get("first_object_ts") is not None)
            if first_ts == float("inf"):
                return None
            # pub_start_time is ISO format, first_ts is ms since epoch
            import datetime
            pub_dt = datetime.datetime.fromisoformat(pub_start_time.replace('Z', '+00:00'))
            pub_ts = pub_dt.timestamp() * 1000  # Convert to ms
            ttfo = first_ts - pub_ts
            return round(ttfo, 2) if ttfo >= 0 else None
        except Exception:
            return None

    def _objects_published(self, pub_log: Path, impl: Optional[str]) -> Optional[int]:
        if impl == "moq-rs":
            return self._count_moqrs_objects(pub_log)
        return self._parse_app_log(pub_log).get("objects_published")

    def _objects_received(self, sub_log: Path, impl: Optional[str]) -> Optional[int]:
        if impl == "moq-rs":
            # moq-rs writes received media to stdout (the artifact), not to
            # sub.log, so received-object counts are not recoverable from logs.
            return None
        return self._parse_app_log(sub_log).get("objects_received")

    def _count_moqrs_objects(self, log_path: Path) -> int:
        """B31 (see found-bugs.md): moq-rs publishes an INIT object plus one
        object per segment; the log only prints 'segment:' lines, so any run
        with >=1 segment delivered exactly one init object before them.
        Zero segment lines means nothing was confirmed published."""
        text = log_path.read_text(errors="replace")
        segments = len(self.MOQRS_SEGMENT_RE.findall(text))
        return segments + 1 if segments else 0

    def _parse_app_log(self, log_path: Path) -> Dict[str, Any]:
        metrics = {"objects_published": None, "objects_received": None, "errors": []}
        text = log_path.read_text(errors="replace")
        obj_pub = re.findall(r"published\s+(\d+)\s+objects?", text, re.IGNORECASE)
        if obj_pub:
            metrics["objects_published"] = sum(int(x) for x in obj_pub)
        obj_recv = re.findall(r"received\s+(\d+)\s+objects?", text, re.IGNORECASE)
        if obj_recv:
            metrics["objects_received"] = sum(int(x) for x in obj_recv)
        error_lines = re.findall(r"(ERROR|Error|FAIL|fail).*", text)
        metrics["errors"] = error_lines[:20]
        return metrics

    def _parse_qlog(self, qlog_dir: Path) -> Dict[str, Any]:
        """Parse real qlog files (moq-rs relay `--qlog-dir` and imquic `-Q`,
        one file per connection, .sqlog/.qlog/.json) for RTT and packet stats.

        Handles the qlog "JSON-SEQ" format (moq-rs): every line is a separate
        JSON record prefixed by the record separator (0x1e), NOT one JSON
        document. Plain whole-file JSON (imquic/picoquic, one pretty-printed
        doc per connection) is also accepted as a fallback.

        RTT unit handling: moq-rs (quinn) emits qlog-spec seconds; imquic's
        picoquic emits MICROSECONDS. A 'picoquic' marker in the file selects
        µs; everything else is treated as seconds.
        """
        metrics = {"rtt_estimate_ms": None, "rtt_min_ms": None,
                   "rtt_max_ms": None,
                   "packets_sent": 0, "packets_received": 0,
                   "packets_lost": 0, "packet_loss_rate": None}
        if not qlog_dir.exists():
            return metrics
        files: List[Path] = [
            p for p in qlog_dir.iterdir()
            if p.is_file() and p.suffix.lower() in (".sqlog", ".qlog", ".json")
        ]
        if not files:
            return metrics

        rtt_samples: List[Tuple[str, float]] = []
        min_rtt_ms = None
        packets_sent = 0
        packets_received = 0
        packets_lost = 0
        for fp in sorted(files):
            text = self._read_text(fp)
            if not text:
                continue
            is_picoquic = "picoquic" in text
            for record in self._qlog_nodes_text(text):
                for ev_name, ev_data in self._qlog_events(record):
                    if "packet_lost" in ev_name:
                        packets_lost += 1
                    elif "packet_sent" in ev_name:
                        packets_sent += 1
                    elif "packet_received" in ev_name:
                        packets_received += 1
                    for key in ("smoothed_rtt", "latest_rtt",
                                "rtt", "estimated_rtt"):
                        if key in ev_data and isinstance(ev_data[key],
                                                         (int, float)):
                            rtt_samples.append((
                                key, self._rtt_to_ms(ev_data[key],
                                                     is_picoquic)))
                    mkey = ev_data.get("min_rtt")
                    if isinstance(mkey, (int, float)):
                        val = self._rtt_to_ms(mkey, is_picoquic)
                        min_rtt_ms = (val if min_rtt_ms is None
                                      else min(min_rtt_ms, val))

        estimate = self._rtt_estimate(rtt_samples)
        if estimate is not None:
            metrics["rtt_estimate_ms"] = estimate
        if rtt_samples:
            vals = [v for _, v in rtt_samples if v >= 0]
            if vals:
                metrics["rtt_max_ms"] = round(max(vals), 2)
        if min_rtt_ms is not None:
            metrics["rtt_min_ms"] = round(min_rtt_ms, 2)
        metrics["packets_sent"] = packets_sent
        metrics["packets_received"] = packets_received
        metrics["packets_lost"] = packets_lost
        if packets_sent > 0:
            metrics["packet_loss_rate"] = round(packets_lost / packets_sent, 6)
        return metrics

    @staticmethod
    def _rtt_to_ms(value: float, picoquic: bool) -> float:
        """picoquic/imquic qlogs report RTT in microseconds; qlog-spec
        (moq-rs/quinn) in seconds. Convert either to milliseconds."""
        if picoquic:
            return round(float(value) / 1000.0, 4)
        return round(float(value) * 1000.0, 4)

    @staticmethod
    def _rtt_estimate(rtt_samples: List[Tuple[str, float]]) -> Optional[float]:
        """Return the millisecond RTT estimate from (key, ms) samples.

        Prefer the most recent smoothed_rtt; fall back through latest_rtt then
        generic rtt/estimated_rtt. Samples are in chronological order, so the
        highest (grade, index) wins.
        """
        if not rtt_samples:
            return None
        grades = {"smoothed_rtt": 3, "latest_rtt": 2,
                  "rtt": 1, "estimated_rtt": 1}
        best: Optional[Tuple[int, int, float]] = None
        for idx, (key, value) in enumerate(rtt_samples):
            cand = (grades.get(key, 0), idx, value)
            if best is None or cand[:2] > best[:2]:
                best = cand
        return best[2] if best is not None else None

    def _qlog_events(self, record: Any):
        """Yield (event_name, data dict) pairs from a qlog record.

        Handles the three shapes found in the wild:
          - moq-rs JSON-SEQ line: {"event": {"name": "metrics:x", "data": {...}}}
          - whole-doc with traces: {"traces": [{"events": [...]}]}
          - picoquic event arrays: [time, category, "name", {...data...}]
        """
        if isinstance(record, dict):
            event = record.get("event")
            if isinstance(event, dict):
                name = event.get("name")
                if name is not None:
                    data = event.get("data")
                    yield str(name), (data if isinstance(data, dict) else {})
                return
            name = record.get("name")
            if name is not None:
                data = record.get("data")
                yield str(name), (data if isinstance(data, dict) else {})
            for trace in list(record.get("traces") or []) + \
                    ([record["trace"]] if isinstance(record.get("trace"), dict)
                     else []):
                if not isinstance(trace, dict):
                    continue
                for ev in (trace.get("events") or []):
                    yield from self._qlog_events(ev)
        elif (isinstance(record, list) and len(record) >= 3
              and isinstance(record[2], str)):
            data = record[3] if len(record) > 3 else {}
            yield record[2], (data if isinstance(data, dict) else {})

    @staticmethod
    def _read_text(fp: Path) -> str:
        try:
            return fp.read_text(errors="replace")
        except OSError:
            return ""

    def _qlog_nodes_text(self, text: str) -> List[Any]:
        """Return every JSON record (event line) in qlog text.

        JSON-SEQ: strip the leading record separator (0x1e) / any bytes before
        the first '{', then json.loads each non-empty line. Fall back to
        parsing the whole file as one JSON document.
        """
        nodes: List[Any] = []
        lines = text.splitlines()
        records = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line[0] != "{":
                idx = line.find("{")
                if idx < 0:
                    continue
                line = line[idx:]
            try:
                nodes.append(json.loads(line))
                records += 1
            except json.JSONDecodeError:
                continue
        if records == 0:
            try:
                data = json.loads(text)
            except (json.JSONDecodeError):
                return nodes
            if isinstance(data, dict):
                nodes.append(data)
        return nodes

    def _parse_pcap(self, run_dir: Path) -> Dict[str, Any]:
        """Parse pcap files for wire-level QUIC metrics (I13).

        Uses tshark if available. Requires SSLKEYLOGFILE for QUIC decryption.
        Returns dict with wire_* prefixed metrics.
        """
        from harness.pcap import analyze_run_pcaps, tshark_available
        metrics = {
            "wire_total_packets": None,
            "wire_total_bytes": None,
            "wire_quic_packets": None,
            "wire_quic_bytes": None,
            "wire_rtt_estimate_ms": None,
            "wire_rtt_min_ms": None,
            "wire_rtt_max_ms": None,
            "wire_decryption_success": False,
            "wire_error": None,
        }
        if not tshark_available():
            metrics["wire_error"] = "tshark not installed"
            return metrics

        sslkeylog = run_dir / "keys" / "sslkeys.log"
        if not sslkeylog.exists():
            metrics["wire_error"] = "SSLKEYLOGFILE not found"
            return metrics

        pcap_dir = run_dir / "pcaps"
        if not pcap_dir.exists():
            metrics["wire_error"] = "pcaps directory not found"
            return metrics

        try:
            # analyze_run_pcaps() expects the RUN dir, not the pcaps dir (it
            # appends /pcaps itself).
            result = analyze_run_pcaps(run_dir, sslkeylog)
        except Exception as e:
            metrics["wire_error"] = f"pcap analysis failed: {e}"
            return metrics

        if "error" in result:
            metrics["wire_error"] = result["error"]
            return metrics

        agg = result.get("aggregate", {})
        metrics["wire_total_packets"] = agg.get("total_packets")
        metrics["wire_total_bytes"] = agg.get("total_bytes")
        metrics["wire_quic_packets"] = agg.get("quic_packets")
        metrics["wire_quic_bytes"] = agg.get("quic_bytes")
        metrics["wire_rtt_estimate_ms"] = agg.get("rtt_estimate_ms")
        metrics["wire_rtt_min_ms"] = agg.get("rtt_min_ms")
        metrics["wire_rtt_max_ms"] = agg.get("rtt_max_ms")
        metrics["wire_decryption_success"] = any(
            h.get("decryption_success", False)
            for h in result.get("per_host", {}).values()
        )
        if (metrics["wire_quic_packets"] and metrics["wire_rtt_estimate_ms"] is None
                and not metrics["wire_error"]):
            metrics["wire_error"] = (
                "QUIC ACK RTT unavailable: tshark would not ingest the "
                "picoquic/quinn keylogs (see found-bugs.md B42); qlog RTT is "
                "the RTT source for this plan."
            )
        return metrics
