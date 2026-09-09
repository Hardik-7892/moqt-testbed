#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"

CSS = """
:root {
  --pass: #2e7d32;
  --pass-bg: #e8f5e9;
  --partial: #f57f17;
  --partial-bg: #fff8e1;
  --fail: #c62828;
  --fail-bg: #fbe9e7;
  --text: #1a1a2e;
  --muted: #6b7280;
  --border: #e5e7eb;
  --card-bg: #ffffff;
  --header-bg: #f9fafb;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 24px; background: #f3f4f6; color: var(--text); line-height: 1.5; }
.container { max-width: 1400px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; flex-wrap: wrap; gap: 16px; }
.header h1 { margin: 0; font-size: 1.75rem; font-weight: 600; }
.header .meta { color: var(--muted); font-size: 0.875rem; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
.stat-card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.stat-card .label { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 4px; }
.stat-card .value { font-size: 2rem; font-weight: 700; }
.stat-card.pass .value { color: var(--pass); }
.stat-card.partial .value { color: var(--partial); }
.stat-card.fail .value { color: var(--fail); }
.stat-card.total .value { color: var(--text); }
.card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 24px; overflow: hidden; }
.card-header { padding: 16px 20px; border-bottom: 1px solid var(--border); background: var(--header-bg); font-weight: 600; }
.card-body { padding: 20px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th { background: var(--header-bg); font-weight: 600; color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #fafafa; }
.badge { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 9999px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; }
.badge-pass { background: var(--pass-bg); color: var(--pass); }
.badge-partial { background: var(--partial-bg); color: var(--partial); }
.badge-fail { background: var(--fail-bg); color: var(--fail); }
.badge-unknown { background: var(--border); color: var(--muted); }
.network-badge { display: inline-flex; gap: 8px; font-size: 0.75rem; color: var(--muted); }
.network-badge span { background: var(--header-bg); padding: 2px 8px; border-radius: 4px; font-family: monospace; }
.chart-wrap { height: 300px; position: relative; }
.integrity-bar { height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
.integrity-bar > div { height: 100%; border-radius: 4px; transition: width 0.3s ease; }
.integrity-exact { background: var(--pass); }
.integrity-good { background: var(--partial); }
.integrity-mismatch { background: var(--fail); }
.collapsible { cursor: pointer; user-select: none; }
.collapsible-content { display: none; }
.collapsible.open + .collapsible-content { display: block; animation: fadeIn 0.2s ease; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }
.sub-row { background: #fafafa; }
.sub-row td { padding-left: 40px; font-size: 0.8125rem; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8125rem; }
.empty-state { text-align: center; padding: 40px; color: var(--muted); }
.tooltip { position: relative; }
.tooltip:hover::after { content: attr(data-tip); position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); background: #1a1a2e; color: white; padding: 8px 12px; border-radius: 6px; font-size: 0.75rem; white-space: nowrap; z-index: 10; margin-bottom: 4px; }
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MoQT Test Report - {plan}</title>
<script src="{chart_js}"></script>
<style>{css}</style>
</head>
<body>
<div class="container">
  <header class="header">
    <div>
      <h1>MoQT Test Report</h1>
      <div class="meta">Plan: <strong>{plan}</strong> - Generated: {timestamp}</div>
    </div>
  </header>

  <div class="stats-grid">
    <div class="stat-card total"><div class="label">Total Runs</div><div class="value">{total}</div></div>
    <div class="stat-card pass"><div class="label">Pass</div><div class="value">{passed}</div></div>
    <div class="stat-card partial"><div class="label">Partial</div><div class="value">{partial}</div></div>
    <div class="stat-card fail"><div class="label">Fail</div><div class="value">{failed}</div></div>
  </div>

  <section class="card" style="margin-bottom:24px;">
    <div class="card-header">Overview Charts</div>
    <div class="card-body" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px;">
      <div><canvas id="cov-chart" class="chart-wrap"></canvas></div>
      <div><canvas id="thr-chart" class="chart-wrap"></canvas></div>
      <div><canvas id="rtt-chart" class="chart-wrap"></canvas></div>
    </div>
  </section>

  {confusion_matrix}

  {interop_matrix}

  <section class="card">
    <div class="card-header">Detailed Results</div>
    <div class="card-body">
      <div class="table-wrap">
        <table id="results-table">
          <thead>
            <tr>
              <th>Run ID</th><th>Status</th><th>Expected</th><th>Confusion</th><th>Pub</th><th>Relay</th><th>Sub</th>
              <th>Network</th><th>Delivered</th><th>Integrity</th><th>Objects</th><th>RTT (ms)</th><th>Throughput</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </div>
  </section>

  {per_sub_section}

  {integrity_section}

</div>

<script>
{chart_scripts}
</script>
</body>
</html>"""


def _status_badge(status: str) -> str:
    cls = {"pass": "badge-pass", "partial": "badge-partial", "fail": "badge-fail"}.get(status, "badge-unknown")
    return f'<span class="badge {cls}">{status}</span>'


def _network_badge(net: Dict[str, Any]) -> str:
    parts = []
    if net.get("bw") is not None:
        parts.append(f'<span>bw={net["bw"]} Mbps</span>')
    if net.get("delay"):
        parts.append(f'<span>delay={net["delay"]}</span>')
    if net.get("loss") is not None:
        parts.append(f'<span>loss={net["loss"]}%</span>')
    if net.get("num_subscribers"):
        parts.append(f'<span>subs={net["num_subscribers"]}</span>')
    return f'<div class="network-badge">{"".join(parts)}</div>' if parts else '<span class="mono">-</span>'


def _transport_label(per_sub: Dict[str, Any]) -> str:
    """Short transport label for streaming rows (Phase 3, D13).

    Collects fetch_protos keys across subs, e.g. 'h3', 'HTTP/2',
    'h3+tcp-fallback'. '' when manifests predate the label.
    """
    seen: List[str] = []
    for ps in (per_sub or {}).values():
        for p in (ps.get("fetch_protos") or {}):
            if str(p) not in seen:
                seen.append(str(p))
    return "+".join(seen)


def _integrity_badge(integrity: Dict[str, Any]) -> str:
    verdict = integrity.get("verdict")
    if not verdict:
        return '<span class="mono">-</span>'
    # Streaming baseline (lldash): per-segment value check, no whole-file SHA.
    # Show segments fetched/expected + segment-match bar instead of byte prefix.
    if integrity.get("streaming"):
        per_sub = integrity.get("per_sub", {})
        fetched = sum((ps.get("segments_fetched") or 0) for ps in per_sub.values())
        expected = sum((ps.get("segments_expected") or 0) for ps in per_sub.values())
        n_subs = len(per_sub) or 1
        # Per-sub average for fanout readability (aggregate sums N subs)
        if len(per_sub) > 1 and expected:
            label = f"{verdict} {fetched//n_subs}/{expected//n_subs} segs/sub"
        elif expected:
            label = f"{verdict} {fetched}/{expected} segs"
        else:
            label = verdict
        # Phase 3 (D13): transport actually used — an h3 row served over TCP
        # fallback must not read as a QUIC result.
        t = _transport_label(per_sub)
        if t:
            label += f" via {t}"
        pct = integrity.get("byte_identical_pct")
        cls = {"exact": "integrity-exact", "good": "integrity-good", "mismatch": "integrity-mismatch"}.get(verdict, "")
        bar_pct = min(max(pct if pct is not None else (100 if verdict in ("exact", "good") else 0), 0), 100)
        return f'<div class="integrity-bar" title="{label} (per-segment value check)"><div class="{cls}" style="width: {bar_pct}%"></div></div><div style="margin-top:4px;font-size:0.75rem;">{label}</div>'
    pct = integrity.get("byte_identical_pct")
    # For lldash baseline, 0% with good is dash overhead, not failure — show coverage-based bar
    # If pct is 0 but verdict good and delivered ~ expected, don't show 0% bar
    if verdict == "good" and (pct is None or pct == 0):
        # Try to show coverage-based label instead
        label = "good (playable)"
        bar_pct = 100
        return f'<div class="integrity-bar" title="{label}"><div class="integrity-good" style="width: {bar_pct}%"></div></div><div style="margin-top:4px;font-size:0.75rem;">{label}</div>'
    cls = {"exact": "integrity-exact", "good": "integrity-good", "mismatch": "integrity-mismatch"}.get(verdict, "")
    label = {"exact": "Exact", "good": f"good {pct}%" if pct else "good", "mismatch": f"mismatch {pct}%" if pct else "mismatch"}.get(verdict, verdict)
    # Clamp pct for bar width
    bar_pct = min(max(pct or 0, 0), 100)
    return f'<div class="integrity-bar" title="{label}"><div class="{cls}" style="width: {bar_pct}%"></div></div><div style="margin-top:4px;font-size:0.75rem;">{label}</div>'


def _row_confusion(r: Dict[str, Any]) -> str:
    confusion = r.get("confusion")
    if not confusion:
        confusion = (r.get("evaluation", {}) or {}).get("confusion", "?")
    return confusion or "?"


def _confusion_counts(results: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"TP": 0, "TN": 0, "FP": 0, "FN": 0, "?": 0}
    for r in results:
        confusion = _row_confusion(r)
        counts[confusion if confusion in counts else "?"] += 1
    return counts


def _build_confusion_matrix(results: List[Dict[str, Any]]) -> str:
    c = _confusion_counts(results)
    if c["TP"] + c["TN"] + c["FP"] + c["FN"] == 0:
        return ""
    note = ""
    if c["?"]:
        note = f" Unclassified rows: {c['?']} (no/unknown expectation)."
    return f"""<section class="card"><div class="card-header">Confusion Matrix (I1)</div><div class="card-body">
<div class="table-wrap"><table style="max-width:640px;">
<thead><tr><th></th><th>Expected Pass</th><th>Expected Fail</th></tr></thead>
<tbody>
<tr><th style="background:var(--header-bg)">Actual Pass</th>
<td style="background:#e8f5e9;font-weight:600;">{c['TP']} TP</td>
<td style="background:#fbe9e7;font-weight:600;">{c['FP']} FP</td></tr>
<tr><th style="background:var(--header-bg)">Actual Fail</th>
<td style="background:#fff8e1;font-weight:600;">{c['FN']} FN</td>
<td style="background:#e3f2fd;font-weight:600;">{c['TN']} TN</td></tr>
</tbody></table></div>
<p style="color:var(--muted);font-size:0.8rem;">TP=True Positive, TN=True Negative, FP=False Positive,
FN=False Negative. \"Actual\" = measured status; \"Expected\" = plan's
<code>expect:</code> marker. Partial counts toward Fail.{note}</p>
</div></section>"""


def _build_interop_matrix(results: List[Dict[str, Any]]) -> str:
    combos: Dict[str, Dict[str, str]] = {}
    for r in results:
        config = r.get("config", {})
        pub = config.get("pub", {}).get("impl", "?")
        # Handle chain topology relay_a/relay_b
        relay = config.get("relay", {}).get("impl") or config.get("relay_a", {}).get("impl") or config.get("relay_b", {}).get("impl", "?")
        sub = config.get("sub", {}).get("impl", "?")
        status = r.get("evaluation", {}).get("status", "?")
        key = f"{pub} - {sub}"
        # For lldash baseline, pub==relay==sub, so key is duplicated — make more descriptive with topology
        topology = config.get("topology", "basic")
        if pub == relay == sub and pub.startswith("lldash"):
            key = f"{pub} ({topology})"
        combos.setdefault(relay, {})[key] = status
    if not combos:
        return ""
    all_keys = sorted(set(k for inner in combos.values() for k in inner))
    html = ['<section class="card"><div class="card-header">Interop Matrix</div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>Relay</th>']
    for key in all_keys:
        html.append(f"<th>{key}</th>")
    html.append("</tr></thead><tbody>")
    for relay, pairs in sorted(combos.items()):
        html.append(f"<tr><td><strong>{relay}</strong></td>")
        for key in all_keys:
            status = pairs.get(key, "-")
            badge = _status_badge(status) if status != "-" else '<span class="mono">-</span>'
            html.append(f"<td>{badge}</td>")
        html.append("</tr>")
    html.append("</tbody></table></div></div></section>")
    return "".join(html)


def _build_rows(results: List[Dict[str, Any]]) -> str:
    rows = []
    for r in results:
        config = r.get("config", {})
        ev = r.get("evaluation", {})
        status = ev.get("status", "?")
        pub = config.get("pub", {}).get("impl", "?")
        # Handle chain topology where relay is relay_a/relay_b
        relay = config.get("relay", {}).get("impl") or config.get("relay_a", {}).get("impl") or config.get("relay_b", {}).get("impl", "?")
        sub = config.get("sub", {}).get("impl", "?")
        net = config.get("network", {})
        stats = ev.get("stats", {})
        cov = stats.get("coverage_pct")
        delivered = f"{cov:.1f}%" if cov is not None else "-"
        per_sub = (stats.get("integrity", {}) or {}).get("per_sub", {})
        exp_b = stats.get("expected_media_bytes")
        if cov is not None and len(per_sub) > 1 and exp_b:
            # For MoQ: mlog_delivered_bytes == exp_b ; for lldash baseline (no mlog) use artifact_bytes
            full = sum(1 for ps in per_sub.values() if (ps.get("mlog_delivered_bytes") == exp_b or (ps.get("mlog_delivered_bytes") is None and ps.get("artifact_bytes") == exp_b) or (ps.get("artifact_bytes") and abs(ps.get("artifact_bytes") - exp_b) / exp_b < 0.05)))
            # Also consider byte_identical_pct 100 for lldash good
            if full == 0:
                # Fallback for lldash: count verdict good as full
                full = sum(1 for ps in per_sub.values() if ps.get("verdict") in ("good", "exact"))
            delivered += f' <span class="tooltip" data-tip="Subscribers served the full stream">[full {full}/{len(per_sub)}]</span>'
        else:
            ecov = stats.get("expected_coverage_pct")
            if cov is not None and stats.get("expected_media_bytes") and ecov is not None and stats["expected_media_bytes"] != stats.get("original_bytes"):
                exp_bytes = stats["expected_media_bytes"]
                tip = f"Coverage vs expected media ({exp_bytes} B, trailing boxes excluded)"
                delivered += f' <span class="tooltip" data-tip="{tip}">[{ecov:.1f}% exp]</span>'
        integrity = stats.get("integrity", {})
        integrity_html = _integrity_badge(integrity)
        m = ev.get("metrics", {})
        pub_n = m.get("objects_published")
        recv_n = m.get("objects_received")
        objects = f"{pub_n}/{recv_n}" if pub_n is not None or recv_n is not None else "-"
        rtt = m.get("rtt_estimate_ms")
        if rtt is None:
            rtt = m.get("wire_rtt_estimate_ms")
        rtt_str = f"{rtt:.1f}" if rtt is not None else "-"
        mbps = m.get("throughput_bps")
        # For fanout, throughput is aggregate sum — show per-sub average for fair comparison
        if mbps and len(per_sub) > 1:
            mbps_per_sub = mbps / len(per_sub)
            thr = f"{mbps_per_sub / 1e6:.2f} Mbps <span style='color:var(--muted);font-size:0.7rem;'>(avg per sub, {mbps/1e6:.2f} agg)</span>"
        else:
            thr = f"{mbps / 1e6:.2f} Mbps" if mbps else "-"
        expected = ev.get("expected", "pass")
        confusion = _row_confusion(r)
        conf_cls = {"TP": "badge-pass", "TN": "badge-pass", "FP": "badge-fail", "FN": "badge-fail"}.get(confusion, "badge-unknown")
        row = f'<tr><td class="mono">{r.get("run_id","?")}</td><td>{_status_badge(status)}</td><td class="mono">{expected}</td><td><span class="badge {conf_cls}">{confusion}</span></td><td>{pub}</td><td>{relay}</td><td>{sub}</td><td>{_network_badge(net)}</td><td>{delivered}</td><td>{integrity_html}</td><td class="mono">{objects}</td><td class="mono">{rtt_str}</td><td class="mono">{thr}</td></tr>'
        rows.append(row)
    return "".join(rows)


def _build_per_sub_section(results: List[Dict[str, Any]]) -> str:
    has_per_sub = any(
        (r.get("evaluation", {}).get("stats", {}).get("integrity", {}).get("per_sub"))
        for r in results
    )
    if not has_per_sub:
        return ""
    html = ['<section class="card"><div class="card-header">Per-Subscriber Delivery</div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>Run ID</th><th>Subscriber</th><th>Artifact (B)</th><th>Media (B)</th><th>mlog (B)</th><th>Prefix Identical</th><th>Segments</th><th>Throughput</th><th>Verdict</th></tr></thead><tbody>']
    for r in results:
        per_sub = (r.get("evaluation", {}).get("stats", {}).get("integrity", {}).get("per_sub", {}))
        if not per_sub:
            continue
        # For per-sub throughput, use run_duration_s if available
        run_dur = r.get("evaluation", {}).get("stats", {}).get("run_duration_s") or r.get("evaluation", {}).get("metrics", {}).get("run_duration_s") or 1
        # Fallback to stats run_duration
        if not run_dur:
            run_dur = 1
        for role in sorted(per_sub):
            ps = per_sub[role]
            verdict = ps.get("verdict", "-")
            # Map MoQ verdicts good/exact/mismatch to badge colors pass/partial/fail
            if verdict in ("good", "exact"):
                badge = '<span class="badge badge-pass">good</span>'
            elif verdict == "mismatch":
                badge = '<span class="badge badge-fail">mismatch</span>'
            else:
                badge = _status_badge(verdict) if verdict in ("pass", "partial", "fail") else f'<span class="badge badge-unknown">{verdict}</span>'
            # Per-sub throughput: media_bytes*8 / duration (individual, not aggregate)
            thr = "-"
            mb = ps.get("media_bytes") or ps.get("artifact_bytes")
            if mb and run_dur:
                try:
                    thr_val = mb * 8 / run_dur / 1e6
                    thr = f"{thr_val:.2f} Mbps"
                except:
                    thr = "-"
            # Streaming baseline: prefix col shows per-segment match % instead
            # of whole-file byte prefix (a late joiner's shorter capture can
            # never prefix-match the full file).
            pct = ps.get("byte_identical_pct")
            pct_str = f"{pct}%" if pct is not None else "-"
            if "segments_fetched" in ps and ps.get("segments_expected") is not None:
                pct_str = f"{pct_str} segs" if pct_str != "-" else "-"
            elif verdict == "good" and pct == 0.0:
                pct_str = "100% (playable)"
            elif verdict == "good" and pct == 0:
                pct_str = "100% (playable)"
            # Segments cell: fetched/expected + join delay/skip for streaming
            if ps.get("segments_expected") is not None:
                seg_str = f"{ps.get('segments_fetched', '-')}/{ps.get('segments_expected', '-')}"
                if ps.get("join_delay_s"):
                    seg_str += f" (join +{ps['join_delay_s']:.0f}s, skip {ps.get('skipped', '-')})"
                # Phase 3 (D13): per-sub transport actually used.
                sub_protos = "+".join(ps.get("fetch_protos") or {})
                if sub_protos:
                    seg_str += f" via {sub_protos}"
            else:
                seg_str = "-"
            html.append(f'<tr class="sub-row"><td class="mono">{r.get("run_id","?")}</td><td>{role}</td><td class="mono">{ps.get("artifact_bytes","-")}</td><td class="mono">{ps.get("media_bytes","-")}</td><td class="mono">{ps.get("mlog_delivered_bytes","-")}</td><td>{pct_str}</td><td class="mono">{seg_str}</td><td class="mono">{thr}</td><td>{badge}</td></tr>')
    html.append("</tbody></table></div></div></section>")
    return "".join(html)


def _build_integrity_section(results: List[Dict[str, Any]]) -> str:
    has_integrity = any(
        r.get("evaluation", {}).get("stats", {}).get("integrity", {}).get("expected_objects")
        for r in results
    )
    if not has_integrity:
        return ""
    html = ['<section class="card"><div class="card-header">Integrity Detail</div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>Run ID</th><th>Expected (init/segments)</th><th>Received (mlog)</th><th>Per-object Match</th><th>Delivered (mlog)</th><th>Expected SHA</th><th>Delivered SHA</th></tr></thead><tbody>']
    for r in results:
        integrity = r.get("evaluation", {}).get("stats", {}).get("integrity", {})
        if not integrity.get("expected_objects"):
            continue
        exp = "+".join(f"{'init' if o.get('kind') == 'init' else 'seg'}={o.get('bytes')}" for o in integrity.get("expected_objects", []))
        recv = "+".join(str(o.get("bytes")) for o in integrity.get("received_objects", [])) or "-"
        per_obj = integrity.get("per_object_match")
        per_obj_str = "YES" if per_obj else ("NO" if per_obj is False else "-")
        deliv = integrity.get("delivered_bytes", "-")
        html.append(f'<tr><td class="mono">{r.get("run_id","?")}</td><td class="mono">{exp}</td><td class="mono">{recv}</td><td>{per_obj_str}</td><td class="mono">{deliv}</td><td class="mono">{integrity.get("sha256_expected","-")[:16]}...</td><td class="mono">{(integrity.get("sha256_delivered") or "-")[:16]}...</td></tr>')
    html.append("</tbody></table></div></div></section>")
    return "".join(html)


def _chart_data(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    labels = []
    coverage = []
    throughput = []
    rtt = []
    rtt_wire = []
    statuses = []
    has_rtt = False
    for r in results:
        labels.append(r.get("run_id", "?")[:30])
        stats = r.get("evaluation", {}).get("stats", {})
        cov = stats.get("coverage_pct")
        # For fanout, coverage is aggregate 300% — clamp to 100 for chart readability, keep tooltip as is
        if cov is not None and cov > 100:
            # For fanout aggregate 300%, chart should show per-sub 100% (full)
            per_sub = (stats.get("integrity", {}) or {}).get("per_sub", {})
            if per_sub:
                cov = 100.0 if all(ps.get("verdict") in ("good","exact") for ps in per_sub.values()) else cov / len(per_sub)
            else:
                cov = min(cov, 100)
        coverage.append(cov if cov is not None else 0)
        m = r.get("evaluation", {}).get("metrics", {})
        mbps = m.get("throughput_bps")
        # For fanout, show per-sub average in chart for fair comparison (aggregate would dominate)
        per_sub = (stats.get("integrity", {}) or {}).get("per_sub", {})
        if mbps and per_sub and len(per_sub) > 1:
            mbps = mbps / len(per_sub)
        throughput.append(mbps / 1e6 if mbps else 0)
        rtt_val = m.get("rtt_estimate_ms")
        # For lldash baseline, no qlog rtt, try wire RTT
        if rtt_val is None:
            rtt_val = m.get("wire_rtt_estimate_ms")
        if rtt_val is not None:
            has_rtt = True
            rtt.append(rtt_val)
        else:
            rtt.append(None)
        statuses.append(r.get("evaluation", {}).get("status", "?"))
    # If no RTT at all (e.g., lldash only), keep None to show empty state
    if not has_rtt:
        rtt = [None] * len(labels)
    return {
        "labels": labels,
        "coverage": coverage,
        "throughput": throughput,
        "rtt": rtt,
        "statuses": statuses,
        "has_rtt": has_rtt,
    }


def _chart_scripts(chart_data: Dict[str, Any]) -> str:
    labels = json.dumps(chart_data["labels"])
    coverage = json.dumps(chart_data["coverage"])
    throughput = json.dumps(chart_data["throughput"])
    rtt = json.dumps(chart_data["rtt"])
    statuses = json.dumps(chart_data["statuses"])
    has_rtt = chart_data.get("has_rtt", True)
    colors = json.dumps(["#2e7d32" if s == "pass" else "#f57f17" if s == "partial" else "#c62828" if s == "fail" else "#9e9e9e" for s in chart_data["statuses"]])
    rtt_js = f"""
const rttData = {rtt};
if ({str(has_rtt).lower()}) {{
  new Chart(document.getElementById('rtt-chart'), {{
    type: 'bar',
    data: {{ labels, datasets: [{{ label: 'RTT (ms)', data: rttData, backgroundColor: barColors }}] }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'ms' }} }} }} }}
  }});
}} else {{
  const el = document.getElementById('rtt-chart');
  if (el) el.parentElement.innerHTML = '<div class=\"empty-state\">No RTT data (lldash baseline has no qlog; use MoQ runs for RTT)</div>';
}}
"""
    return f"""
const labels = {labels};
const coverage = {coverage};
const throughput = {throughput};
const barColors = {colors};

new Chart(document.getElementById('cov-chart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ label: 'Coverage %', data: coverage, backgroundColor: barColors }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true, max: 100, title: {{ display: true, text: 'Coverage %' }} }} }} }}
}});

new Chart(document.getElementById('thr-chart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ label: 'Throughput (Mbps)', data: throughput, backgroundColor: barColors }}] }},
  options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ x: {{ beginAtZero: true, title: {{ display: true, text: 'Mbps' }} }} }} }}
}});
{rtt_js}
"""


class ReportGenerator:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.summary = self._load_summary()

    def _load_summary(self) -> dict:
        path = self.run_dir / "summary.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def generate_html_report(self) -> str:
        summary = self.summary
        results = summary.get("results", [])
        chart_data = _chart_data(results)
        chart_scripts = _chart_scripts(chart_data)

        return HTML_TEMPLATE.format(
            plan=summary.get("plan", "?"),
            timestamp=summary.get("timestamp", "?"),
            total=summary.get("total", 0),
            passed=summary.get("passed", 0),
            partial=summary.get("partial", 0),
            failed=summary.get("failed", 0),
            interop_matrix=_build_interop_matrix(results),
            confusion_matrix=_build_confusion_matrix(results),
            rows=_build_rows(results),
            per_sub_section=_build_per_sub_section(results),
            integrity_section=_build_integrity_section(results),
            chart_scripts=chart_scripts,
            css=CSS,
            chart_js=CHART_JS_CDN,
        )

    def save_report(self) -> Path:
        """Generate both legacy and new dashboard reports."""
        # New dashboard report (default report.html)
        html = self.generate_html_report()
        path = self.run_dir / "report.html"
        path.write_text(html, encoding="utf-8")

        # Legacy report (report_legacy.html)
        legacy_html = self._generate_legacy_report()
        legacy_path = self.run_dir / "report_legacy.html"
        legacy_path.write_text(legacy_html, encoding="utf-8")

        return path

    def _generate_legacy_report(self) -> str:
        """Generate the original monospace table-based report."""
        summary = self.summary
        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>MoQT Interop Test Report (Legacy)</title>
<style>
body {{ font-family: monospace; margin: 20px; }}
table {{ border-collapse: collapse; }}
td, th {{ padding: 6px 10px; text-align: center; }}
.pass {{ background: #4caf50; color: white; }}
.fail {{ background: #f44336; color: white; }}
.partial {{ background: #ff9800; color: white; }}
.skip {{ background: #9e9e9e; color: white; }}
.tp {{ background: #2e7d32; color: white; }}
.tn {{ background: #1565c0; color: white; }}
.fp {{ background: #c62828; color: white; }}
.fn {{ background: #ef6c00; color: white; }}
h2 {{ margin-top: 30px; }}
</style>
</head>
<body>
<h1>MoQT Interop Test Report</h1>
<p>Plan: <b>{summary.get('plan', '?')}</b></p>
<p>Timestamp: <b>{summary.get('timestamp', '?')}</b></p>
<p>Total: <b>{summary.get('total', 0)}</b> | Pass: <b style='color:green'>{summary.get('passed', 0)}</b> | Partial: <b style='color:orange'>{summary.get('partial', 0)}</b> | Fail: <b style='color:red'>{summary.get('failed', 0)}</p>
"""
        # I1: Confusion matrix summary
        tp = sum(1 for r in summary.get("results", []) if _row_confusion(r) == "TP")
        tn = sum(1 for r in summary.get("results", []) if _row_confusion(r) == "TN")
        fp = sum(1 for r in summary.get("results", []) if _row_confusion(r) == "FP")
        fn = sum(1 for r in summary.get("results", []) if _row_confusion(r) == "FN")
        if tp + tn + fp + fn > 0:
            html += f"""<h2>Confusion Matrix (I1)</h2>
<table border='1'>
<tr><th></th><th>Predicted Pass</th><th>Predicted Fail</th></tr>
<tr><th>Actual Pass</th><td class='tp'>{tp} TP</td><td class='fn'>{fn} FN</td></tr>
<tr><th>Actual Fail</th><td class='fp'>{fp} FP</td><td class='tn'>{tn} TN</td></tr>
</table>
<p>TP=True Positive, TN=True Negative, FP=False Positive, FN=False Negative</p>
"""
        html += """<h2>Interop Matrix</h2>
"""
        html += self._build_matrix_html()

        html += """<h2>Detailed Results</h2>
<table border='1'>
<tr><th>Run ID</th><th>Status</th><th>Expected</th><th>Confusion</th><th>Pub</th><th>Relay</th><th>Sub</th><th>Network</th><th>Delivered</th><th>Integrity</th><th>Objects pub/recv</th><th>RTT (ms)</th><th>Throughput</th></tr>
"""
        for r in summary.get("results", []):
            config = r.get("config", {})
            ev = r.get("evaluation", {})
            status = ev.get("status", "?")
            css = "pass" if status == "pass" else "partial" if status == "partial" else "fail"
            pub = config.get("pub", {}).get("impl", "?")
            relay = config.get("relay", {}).get("impl", "?")
            sub = config.get("sub", {}).get("impl", "?")
            net = config.get("network", {})
            net_str = f"bw={net.get('bw','?')} d={net.get('delay','?')} l={net.get('loss','?')}%"
            stats = ev.get("stats", {})
            cov = stats.get("coverage_pct")
            delivered = f"{cov}%" if cov is not None else "-"
            per_sub = (stats.get("integrity", {}) or {}).get("per_sub", {})
            exp_b = stats.get("expected_media_bytes")
            if cov is not None and len(per_sub) > 1 and exp_b:
                # For MoQ use mlog, for lldash (no mlog) use artifact_bytes with tolerance
                full = sum(1 for ps in per_sub.values() if ps.get("mlog_delivered_bytes") == exp_b)
                if full == 0:
                    # lldash fallback: count verdict good as full (no mlog)
                    full = sum(1 for ps in per_sub.values() if ps.get("verdict") in ("good", "exact"))
                    if full == 0:
                        # Fallback to artifact vs expected with 5% tolerance
                        full = sum(1 for ps in per_sub.values() if ps.get("artifact_bytes") and abs(ps.get("artifact_bytes") - exp_b) / exp_b < 0.05)
                delivered += f" <span title='subscribers served the full stream'>[full {full}/{len(per_sub)}]</span>"
            else:
                ecov = stats.get("expected_coverage_pct")
                if (cov is not None and stats.get("expected_media_bytes")
                        and ecov is not None
                        and stats["expected_media_bytes"] != stats.get("original_bytes")):
                    delivered += (f" <span title='coverage vs expected media "
                                  f"({stats['expected_media_bytes']} B, trailing "
                                  f"boxes excluded)'>[{ecov}% exp]</span>")
            integrity = stats.get("integrity", {})
            verdict = integrity.get("verdict")
            identical = integrity.get("byte_identical_pct")
            # For lldash, good with 0% is dash overhead, not failure — show playable
            is_lldash = any("lldash" in str(v) for v in [config.get("pub", {}).get("impl",""), config.get("relay",{}).get("impl",""), config.get("sub",{}).get("impl","")])
            if integrity.get("streaming"):
                per_sub_int = integrity.get("per_sub", {})
                sf = sum((ps.get("segments_fetched") or 0) for ps in per_sub_int.values())
                se = sum((ps.get("segments_expected") or 0) for ps in per_sub_int.values())
                nsubs = len(per_sub_int) or 1
                if len(per_sub_int) > 1 and se:
                    int_str = f"{verdict} {sf//nsubs}/{se//nsubs} segs/sub"
                elif se:
                    int_str = f"{verdict} {sf}/{se} segs"
                else:
                    int_str = verdict or "-"
                # Phase 3 (D13): transport actually used.
                t = _transport_label(per_sub_int)
                if t:
                    int_str += f" via {t}"
            elif verdict == "exact":
                int_str = "sha ✓"
            elif verdict == "good":
                if is_lldash and (identical == 0 or identical == 0.0):
                    int_str = "good (playable)"
                else:
                    int_str = (f"good {identical}%" if identical not in (None, 0, 0.0) else "good")
            elif verdict == "mismatch":
                int_str = (f"sha ✗ {identical}% identical"
                           if identical not in (None, 0, 0.0) else "sha ✗")
            else:
                int_str = "-"
            m = r.get("evaluation", {}).get("metrics", {})
            pub_n = m.get("objects_published")
            recv_n = m.get("objects_received")
            objects = f"{pub_n}/{recv_n}" if pub_n is not None or recv_n is not None else "-"
            rtt = m.get("rtt_estimate_ms")
            if rtt is None:
                rtt = m.get("wire_rtt_estimate_ms")
            rtt_str = f"{rtt}" if rtt is not None else "-"
            mbps = m.get("throughput_bps")
            # For fanout, show per-sub average (aggregate would dominate chart)
            if mbps and len(per_sub) > 1:
                mbps = mbps / len(per_sub)
            thr = f"{mbps / 1e6:.2f} Mbps" if mbps else "-"
            confusion = _row_confusion(r)
            conf_css = confusion.lower() if confusion in ("TP", "TN", "FP", "FN") else ""
            expected = r.get("expected", "pass")
            html += (f"<tr><td>{r.get('run_id','?')}</td><td class='{css}'>{status}</td>"
                     f"<td>{expected}</td><td class='{conf_css}'>{confusion}</td>"
                     f"<td>{pub}</td><td>{relay}</td><td>{sub}</td><td>{net_str}</td>"
                     f"<td>{delivered}</td><td>{int_str}</td>"
                     f"<td>{objects}</td><td>{rtt_str}</td><td>{thr}</td></tr>\n")

        html += """</table>
<h2>Per-Subscriber Delivery</h2>
<table border='1'>
<tr><th>Run ID</th><th>Subscriber</th><th>Artifact (B)</th><th>Media (B)</th><th>mlog (B)</th><th>Prefix identical</th><th>Segments</th><th>Verdict</th></tr>
"""
        for r in summary.get("results", []):
            per_sub = (r.get("evaluation", {}).get("stats", {})
                       .get("integrity", {}).get("per_sub", {}))
            if not per_sub:
                continue
            for role in sorted(per_sub):
                ps = per_sub[role]
                if ps.get("segments_expected") is not None:
                    seg_str = f"{ps.get('segments_fetched', '-')}/{ps.get('segments_expected', '-')}"
                    if ps.get("join_delay_s"):
                        seg_str += f" (join +{ps['join_delay_s']:.0f}s)"
                    pct_cell = f"{ps.get('byte_identical_pct','-')}% segs"
                else:
                    seg_str = "-"
                    pct_cell = f"{ps.get('byte_identical_pct','-')}%"
                html += (f"<tr><td>{r.get('run_id','?')}</td><td>{role}</td>"
                         f"<td>{ps.get('artifact_bytes','-')}</td>"
                         f"<td>{ps.get('media_bytes','-')}</td>"
                         f"<td>{ps.get('mlog_delivered_bytes','-')}</td>"
                         f"<td>{pct_cell}</td>"
                         f"<td>{seg_str}</td>"
                         f"<td>{ps.get('verdict','-')}</td></tr>\n")
        html += """</table>
<h2>Integrity Detail</h2>
<table border='1'>
<tr><th>Run ID</th><th>Expected (init/segments)</th><th>Received (mlog)</th><th>Per-object match</th><th>Delivered</th><th>Expected SHA</th><th>Delivered SHA</th></tr>
"""
        for r in summary.get("results", []):
            integrity = r.get("evaluation", {}).get("stats", {}).get("integrity", {})
            if not integrity.get("expected_objects"):
                continue
            exp = "+".join(f"{'init' if o.get('kind') == 'init' else 'seg'}={o.get('bytes')}"
                           for o in integrity.get("expected_objects", []))
            recv = "+".join(str(o.get("bytes"))
                            for o in integrity.get("received_objects", [])) or "-"
            per_obj = ("✓" if integrity.get("per_object_match")
                       else "✗" if integrity.get("per_object_match") is False else "-")
            deliv = integrity.get("delivered_bytes")
            html += (f"<tr><td>{r.get('run_id','?')}</td>"
                     f"<td>{exp}</td><td>{recv}</td><td>{per_obj}</td>"
                     f"<td>{deliv if deliv is not None else '-'}</td>"
                     f"<td>{integrity.get('sha256_expected','-')}</td>"
                     f"<td>{integrity.get('sha256_delivered','-')}</td></tr>\n")
        html += """</table>
</body>
</html>"""
        return html

    def _build_matrix_html(self) -> str:
        results = self.summary.get("results", [])
        combos = {}
        for r in results:
            config = r.get("config", {})
            pub = config.get("pub", {}).get("impl", "?")
            relay = config.get("relay", {}).get("impl") or config.get("relay_a", {}).get("impl") or config.get("relay_b", {}).get("impl", "?")
            sub = config.get("sub", {}).get("impl", "?")
            status = r.get("evaluation", {}).get("status", "?")
            key = f"{pub} → {sub}"
            if relay not in combos:
                combos[relay] = {}
            combos[relay][key] = status

        all_keys = sorted(set(k for inner in combos.values() for k in inner))
        html = "<table border='1'><tr><th>Relay</th>"
        for key in all_keys:
            html += f"<th>{key}</th>"
        html += "</tr>"
        for relay, pairs in sorted(combos.items()):
            html += f"<tr><td><b>{relay}</b></td>"
            for key in all_keys:
                status = pairs.get(key, "-")
                css = ("pass" if status == "pass"
                       else "partial" if status == "partial"
                       else "fail" if status == "fail" else "skip")
                html += f"<td class='{css}'>{status}</td>"
            html += "</tr>"
        html += "</table>"
        return html

    def generate_matrix_summary(self) -> Path:
        path = self.run_dir / "interop-matrix.csv"
        results = self.summary.get("results", [])
        with open(path, "w") as f:
            f.write("run_id,pub,relay,sub,status\n")
            for r in results:
                config = r.get("config", {})
                status = r.get("evaluation", {}).get("status", "?")
                f.write(f"{r.get('run_id','?')},{config.get('pub',{{}}).get('impl','?')},{config.get('relay',{{}}).get('impl','?')},{config.get('sub',{{}}).get('impl','?')},{status}\n")
        return path