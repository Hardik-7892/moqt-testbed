#!/bin/bash
# Phase 6 — Missed P0/P1 cases from dissertation_research/14 audit + subgroup-drop
#   mechanism pilot (file 16 §16.2).
# P0 (file testplans/missed-p0.yaml, 9 rows): H3-fallback knee at loss 5%,
#   late-join 30s on 120s media, imquic -M 18 vs -M 16 pin proof, FLV parity.
# P1 (file testplans/missed-p1.yaml, 8 rows): queue x loss collapse regime,
#   chain inter-relay-only vs sub-only separation, fanout N=8 + delay skew.
# Mechanism (file testplans/missed-subgroup-drop.yaml, 8 rows): subgroup
#   drop-to-latest under pressure on single-track bbb-video.mp4 (dodges B37
#   interleave); read groups_missing + prefix + artifact_thr (file 16 §16.2).
# Deliberately excluded (needs code/pin first, see file 14 §B7/B8/B10):
#   datagram-vs-stream `mode` (unwired key), 0-RTT/FILL, BBR/AQM, multi-pub,
#   BBB at n=3. All rows use wired keys only (harness/plan_validation.py).
# Results are n=1 PILOT (appendix-only) unless REPEATS>=3 is set.
# Usage: ./phase6_missed.sh   (or ONLY="missed-p0" ./phase6_missed.sh)
#        REPEATS=3 ./phase6_missed.sh   (citable: 3 sequential batches)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
REPEATS="${REPEATS:-1}"
PLANS="${ONLY:-missed-p0 missed-p1 missed-subgroup-drop}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase6_${STAMP}.log") 2>&1

echo "===== PHASE 6 START $STAMP (REPEATS=$REPEATS) ====="
for f in testdata/sample_120s.mp4 testdata/sample.flv testdata/sample.mp4 testdata/bbb-video.mp4; do
    [ -f "$f" ] || echo "WARN: $f missing — run: make $f (see Makefile:219-270)"
done
python3 -c "
from harness.plan_validation import validate_testplan
import yaml
for stub in '$PLANS'.split():
    p = yaml.safe_load(open(f'testplans/{stub}.yaml'))
    validate_testplan(p, stub)
    print(f'{stub}: VALID', len(p['runs']), 'rows')
" || { echo "FATAL: plan validation failed (see harness/plan_validation.py)"; exit 1; }

for stub in $PLANS; do
    batches=()
    for i in $(seq 1 "$REPEATS"); do
        echo "===== [$STAMP] $stub repeat $i/$REPEATS ====="
        if sudo MOQ_FAST_IO="$FAST_IO" python3 run_testbed.py --plan "testplans/${stub}.yaml" --workers 1; then
            batches+=("$(cat artifacts/runs/.latest)")
        else
            echo "WARN: $stub repeat $i FAILED (continuing with next)"
        fi
    done
    if [ "${#batches[@]}" -ge 1 ]; then
        min_r=1; [ "${#batches[@]}" -ge 3 ] && min_r=3
        python3 analysis/aggregate.py "${batches[@]}" \
            --out "artifacts/reports/${stub}_agg_${STAMP}.csv" --min-repeats "$min_r"
    fi
    make report || echo "WARN: make report failed"
done
echo "===== PHASE 6 DONE ====="
echo "CSVs: artifacts/reports/missed-*_agg_${STAMP}.csv | Log: artifacts/reports/phase6_${STAMP}.log"
echo "NOTE: REPEATS=1 output is appendix-only (p50==p95, no variance); REPEATS=3 is citable."
