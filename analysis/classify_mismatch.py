#!/usr/bin/env python3
"""Classify stored SHA-mismatch verdicts into fix-actionable bins (read-only).

Reads batch summary.json files (never touches containers) and bins every
aggregate `mismatch` verdict as one of:
  contaminated  -- artifact LONGER than expected (log bytes survived the
                   ANSI strip; fix = harden MLOG_STDOUT_SIG, Step 2)
  short         -- not delivered_full (coverage gate; value check never the
                   issue; fix = delivery/completion work, out of scope here)
  tail          -- prefix >= 99% but short (teardown flush loss; fix = drain
                   tuning, Step 4, or document residual)
  permuted      -- mlog-complete (delivered == expected) but prefix < 90%,
                   or per_object sizes match while SHA differs (arrival-order
                   permutation; fix = hash the reconstruction, Step 3)
  unknown       -- fields missing; needs a closer look, not a fix

Also flags FLAKE pairs: same run_id with identical artifact_bytes but
divergent verdicts across batches (value flake, B26 tail/ANSI class).

Usage:
  py analysis/classify_mismatch.py <batch_dir>... [--out report.csv]

Step 1 of the SHA-exactness plan. Exit 0 always (analysis, never gates).
"""
import argparse
import csv
import json
import sys
from pathlib import Path


def _get(d, *keys, default=None):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def classify(stats):
    integ = stats.get("integrity") or {}
    if integ.get("verdict") != "mismatch":
        return None
    art = stats.get("artifact_bytes")
    exp = stats.get("expected_media_bytes", integ.get("expected_bytes"))
    delivered = stats.get("delivered_bytes", integ.get("delivered_bytes"))
    exp_total = integ.get("expected_bytes", exp)
    pct = integ.get("byte_identical_pct")
    per_obj = integ.get("per_object_match")
    full = stats.get("delivered_full")

    if art is not None and exp is not None and art > exp:
        return "contaminated"
    if full is False:
        return "short"
    if pct is not None and pct >= 99.0:
        # Full (or gate-unknown) coverage with near-total prefix:
        # truncation (short) or single-tail-byte flake.
        return "tail"
    if delivered is not None and exp_total is not None \
            and delivered == exp_total:
        return "permuted"
    if per_obj is True:
        # Same multiset of object sizes, different bytes: order differs.
        return "permuted"
    if pct is not None and pct < 90.0:
        return "permuted-or-corrupt"
    return "unknown"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batches", nargs="+", help="batch dirs (contain summary.json)")
    ap.add_argument("--out", default=None, help="optional CSV path")
    args = ap.parse_args()

    rows = []
    seen = {}  # (run_id, artifact_bytes) -> set of verdicts (flake detection)
    for b in args.batches:
        summary = json.loads((Path(b) / "summary.json").read_text())
        for r in summary.get("results", []):
            stats = (r.get("evaluation") or {}).get("stats") or {}
            verdict = (stats.get("integrity") or {}).get("verdict")
            seen.setdefault(
                (r.get("run_id"), stats.get("artifact_bytes")),
                set()).add(verdict)
            if verdict != "mismatch":
                continue
            rows.append({
                "batch": Path(b).name,
                "run_id": r.get("run_id"),
                "status": (r.get("evaluation") or {}).get("status"),
                "bin": classify(stats),
                "artifact_bytes": stats.get("artifact_bytes"),
                "expected_media_bytes": stats.get(
                    "expected_media_bytes",
                    (stats.get("integrity") or {}).get("expected_bytes")),
                "delivered_bytes": stats.get("delivered_bytes"),
                "byte_identical_pct": (stats.get("integrity") or {}).get(
                    "byte_identical_pct"),
                "per_object_match": (stats.get("integrity") or {}).get(
                    "per_object_match"),
                "coverage_pct": stats.get("coverage_pct"),
            })

    # FLAKE detection: identical (run_id, artifact_bytes) with divergent
    # verdicts across batches = value flake (B26 tail/ANSI class: same byte
    # count, different SHA). Needs >=2 batches containing the row.
    by_id = {}
    for row in rows:
        by_id.setdefault(row["run_id"], []).append(row)
    for rid, rs in by_id.items():
        arts = {r["artifact_bytes"] for r in rs}
        for r in rs:
            verdicts = seen.get((rid, r["artifact_bytes"]), set())
            if len(verdicts - {"mismatch", None}) > 0:
                r["flake_note"] = "FLAKE-identical-bytes-other-verdict"
            elif len(arts) == 1 and len(rs) > 1:
                r["flake_note"] = "stable-bytes"
            elif len(rs) > 1:
                r["flake_note"] = "varying-bytes"
            else:
                r["flake_note"] = ""

    counts = {}
    for r in rows:
        counts[r["bin"]] = counts.get(r["bin"], 0) + 1
    print(f"{'batch':28} {'run_id':34} {'status':8} {'bin':14} "
          f"{'art':>9} {'exp':>9} {'mlog':>9} {'prefix%':>8} cover")
    for r in rows:
        print(f"{r['batch']:28} {r['run_id']:34} {str(r['status']):8} "
              f"{r['bin']:14} {str(r['artifact_bytes']):>9} "
              f"{str(r['expected_media_bytes']):>9} "
              f"{str(r['delivered_bytes']):>9} "
              f"{str(r['byte_identical_pct']):>8} {r['coverage_pct']} "
              f"{r['flake_note']}")
    print(f"\n{len(rows)} mismatches: " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    if args.out:
        with open(args.out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
