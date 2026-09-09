#!/usr/bin/env python3
"""Phase 4: aggregate repeated batches into citable p50/p95 + Jain numbers.

Ch4 (Table 4.3) promises >=3 repetitions with percentiles, never means.
The runner emits one scalar per sub per run; this host-only script pools N
batch dirs (same plan run N times) by run_id and reports:

- n, status/verdict tallies (honest partial/error counting)
- throughput_bps p50/p95, rtt_estimate_ms p50/p95 (non-null samples only,
  with null counts reported — TTFO is honestly null when clocks skew)
- delivered_fraction p50
- Jain fairness index over per-sub bytes (artifact_bytes, falling back to
  media_bytes then mlog_delivered_bytes), computed PER repeat then
  summarised (min/p50) — never pooled across repeats.
- Restart-proof artifact throughput (artifact_thr_p50/p95): mlog-sum
  delivered_bytes inflates across repeats when sub restarts add mlog
  connections (B38), so fanout throughput is cited from artifacts; a WARN
  fires when mlog/artifact diverge >2x in any repeat.

Usage:
    python3 analysis/aggregate.py <batch_dir> [<batch_dir> ...]
        [--out <csv>] [--min-repeats N]

A "repeat" is one full plan batch dir (artifacts/runs/run_*). Run the same
plan 3x sequentially on the VM (never parallel — see 2_weeks notes), then:
    python3 analysis/aggregate.py artifacts/runs/run_A artifacts/runs/run_B \\
        artifacts/runs/run_C --out artifacts/reports/moq-vs-lldash_agg.csv

Stdlib only. Docker-free.
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path


def percentile(xs, q):
    """q in [0,100]; linear interpolation. Returns None for empty input."""
    vals = sorted(x for x in xs if x is not None and not (isinstance(x, float) and math.isnan(x)))
    if not vals:
        return None
    if len(vals) == 1:
        return float(vals[0])
    rank = (q / 100.0) * (len(vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(vals[int(rank)])
    frac = rank - lo
    return float(vals[lo] * (1 - frac) + vals[hi] * frac)


def jain(xs):
    """Jain fairness index over per-sub bytes. None if <2 positive samples."""
    vals = [float(x) for x in xs if x]
    if len(vals) < 2:
        return None
    s = sum(vals)
    sq = sum(v * v for v in vals)
    if sq <= 0:
        return None
    return round((s * s) / (len(vals) * sq), 4)


def _sub_bytes(entry):
    for k in ("artifact_bytes", "media_bytes", "mlog_delivered_bytes"):
        v = entry.get(k)
        if v:
            return v
    return None


def load_batch(batch_dir):
    """Return {run_id: result-dict} for one batch dir."""
    path = Path(batch_dir) / "summary.json"
    with open(path) as f:
        summary = json.load(f)
    out = {}
    for r in summary.get("results", []):
        out[r.get("run_id", "?")] = r
    return summary.get("plan", "?"), out


def aggregate(batch_dirs, min_repeats=1):
    """Pool batches by run_id. Returns (rows, warnings)."""
    plans = set()
    pooled = {}
    for b in batch_dirs:
        plan, results = load_batch(b)
        plans.add(plan)
        for rid, r in results.items():
            pooled.setdefault(rid, []).append((str(b), r))
    warnings = []
    if len(plans) > 1:
        warnings.append(f"batches mix plans {sorted(plans)} — pooling anyway by run_id")
    rows = []
    for rid in sorted(pooled):
        samples = pooled[rid]
        n = len(samples)
        if n < min_repeats:
            warnings.append(f"{rid}: only {n} repeat(s), want >={min_repeats}")
        statuses = [r.get("status", "?") for _, r in samples]
        verdicts = [(r.get("evaluation", {}).get("stats", {}).get("integrity", {}) or {}).get("verdict", "?")
                    for _, r in samples]
        metrics = [r.get("metrics", {}) or {} for _, r in samples]
        thr = [m.get("throughput_bps") for m in metrics]
        rtt = [m.get("rtt_estimate_ms") for m in metrics]
        ttfo = [m.get("time_to_first_object_ms") for m in metrics]
        dfrac = [m.get("delivered_fraction") for m in metrics]
        # Jain per repeat from per-sub bytes, plus restart-proof
        # artifact-based throughput. Rationale (batch run_20260907_001749):
        # mlog-sum delivered_bytes hit 6x/9x/12x the unit across repeats
        # (B38 sub restarts add mlog connections), while per-sub artifacts
        # stayed identical — so mlog-derived throughput is not repeat-stable
        # for fanout rows. Artifact bytes are the trustworthy measure.
        jains = []
        art_thr = []
        for idx, (_, r) in enumerate(samples):
            stats = r.get("evaluation", {}).get("stats", {}) or {}
            per_sub = ((stats.get("integrity", {}) or {}).get("per_sub", {}) or {})
            vals = [_sub_bytes(e) for e in per_sub.values()]
            vals = [v for v in vals if v]
            j = jain(vals) if len(vals) >= 2 else None
            jains.append(j)
            dur = stats.get("run_duration_s")
            if vals and dur:
                art_thr.append(sum(vals) * 8 / dur)
            # Restart-inflation detector: mlog sum vs artifact sum.
            mlog = stats.get("delivered_bytes")
            art = sum(vals) if vals else None
            if mlog and art and (mlog > 2 * art or mlog * 2 < art):
                warnings.append(
                    f"{rid} repeat {idx + 1}: mlog/artifact diverge "
                    f"(mlog={mlog} artifact={art}) — sub-restart inflation? "
                    f"cite artifact columns, not mlog throughput")
        jains_nn = [j for j in jains if j is not None]
        rows.append({
            "run_id": rid,
            "n": n,
            "statuses": "+".join(statuses),
            "verdicts": "+".join(str(v) for v in verdicts),
            "throughput_p50": percentile(thr, 50),
            "throughput_p95": percentile(thr, 95),
            "throughput_n": sum(1 for x in thr if x is not None),
            "rtt_p50": percentile(rtt, 50),
            "rtt_p95": percentile(rtt, 95),
            "rtt_n": sum(1 for x in rtt if x is not None),
            "ttfo_n_null": sum(1 for x in ttfo if x is None),
            "delfrac_p50": percentile(dfrac, 50),
            "jain_min": min(jains_nn) if jains_nn else None,
            "jain_p50": percentile(jains_nn, 50),
            "jain_n": len(jains_nn),
            "artifact_thr_p50": percentile(art_thr, 50),
            "artifact_thr_p95": percentile(art_thr, 95),
            "artifact_thr_n": len(art_thr),
        })
    return rows, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batches", nargs="+", help="batch dirs (artifacts/runs/run_*)")
    ap.add_argument("--out", default=None, help="CSV output path")
    ap.add_argument("--min-repeats", type=int, default=3)
    args = ap.parse_args(argv)
    rows, warnings = aggregate(args.batches, min_repeats=args.min_repeats)
    for w in warnings:
        print(f"WARN: {w}")
    hdr = ["run_id", "n", "statuses", "verdicts", "throughput_p50",
           "throughput_p95", "throughput_n", "rtt_p50", "rtt_p95", "rtt_n",
           "ttfo_n_null", "delfrac_p50", "jain_min", "jain_p50", "jain_n",
           "artifact_thr_p50", "artifact_thr_p95", "artifact_thr_n"]
    print("\t".join(hdr))
    for r in rows:
        print("\t".join("" if r[h] is None else str(r[h]) for h in hdr))
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=hdr)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {out} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
