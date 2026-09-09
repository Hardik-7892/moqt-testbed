#!/usr/bin/env python3
"""
Parse test run artifacts and extract metrics from qlogs and application logs.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_qlog(qlog_path: Path) -> Dict[str, Any]:
    """Extract key metrics from a qlog file."""
    metrics = {
        "connection_time_ms": None,
        "total_packets_sent": 0,
        "total_packets_lost": 0,
        "rtt_estimate_ms": None,
        "cwnd_bytes": None,
        "events": [],
    }

    if not qlog_path.exists():
        return metrics

    try:
        with open(qlog_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return metrics

    traces = data.get("traces", [data])
    for trace in traces:
        events = trace.get("events", [])
        for event in events:
            if isinstance(event, list) and len(event) >= 3:
                metrics["events"].append(event)

    return metrics


def parse_app_log(log_path: Path) -> Dict[str, Any]:
    """Parse application stdout/stderr for MoQ-specific metrics."""
    metrics = {
        "objects_published": 0,
        "objects_received": 0,
        "errors": [],
    }

    if not log_path.exists():
        return metrics

    text = log_path.read_text()

    obj_pub = re.findall(r"published\s+(\d+)\s+objects?", text, re.IGNORECASE)
    if obj_pub:
        metrics["objects_published"] = sum(int(x) for x in obj_pub)

    obj_recv = re.findall(r"received\s+(\d+)\s+objects?", text, re.IGNORECASE)
    if obj_recv:
        metrics["objects_received"] = sum(int(x) for x in obj_recv)

    error_lines = re.findall(r"(ERROR|Error|error|FAIL|fail).*", text)
    metrics["errors"] = error_lines[:20]

    return metrics


def parse_summary(summary_path: Path) -> Dict[str, Any]:
    """Parse the summary.json from a test run batch."""
    with open(summary_path) as f:
        return json.load(f)


def generate_matrix(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an interop matrix from summary results."""
    matrix = {}
    for result in summary.get("results", []):
        config = result.get("config", {})
        pub = config.get("pub", {})
        relay = config.get("relay", {})
        sub = config.get("sub", {})

        pub_key = f"{pub.get('impl','?')}-d{pub.get('draft','?')}"
        relay_key = f"{relay.get('impl','?')}-d{relay.get('draft','?')}"
        sub_key = f"{sub.get('impl','?')}-d{sub.get('draft','?')}"

        if relay_key not in matrix:
            matrix[relay_key] = {}

        status = result.get("evaluation", {}).get("status", "unknown")
        matrix[relay_key][f"{pub_key} -> {sub_key}"] = status

    return matrix


def format_matrix_html(matrix: Dict[str, Any]) -> str:
    """Render interop matrix as an HTML table."""
    rows = []
    all_keys = sorted(set(
        k for inner in matrix.values() for k in inner
    ))

    html = "<table border='1'><tr><th>Relay</th>"
    for key in all_keys:
        html += f"<th>{key}</th>"
    html += "</tr>"

    for relay_key, combos in sorted(matrix.items()):
        html += f"<tr><td><b>{relay_key}</b></td>"
        for key in all_keys:
            status = combos.get(key, "-")
            color = "green" if status == "pass" else "red" if status == "fail" else "gray"
            html += f"<td style='background:{color};color:white'>{status}</td>"
        html += "</tr>"

    html += "</table>"
    return html
