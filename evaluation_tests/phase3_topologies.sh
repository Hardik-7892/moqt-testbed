#!/bin/bash
# Phase 3 — Topologies -> Fig 6.3 (Jain sharing/fairness), Fig 6.6 (1->N fan-out), Sec 6.4 (chain).
# Runs (1x each, ~40 min total): test-fanout, test-fairness, test-chain, test-chainfanout.
# Usage: ./phase3_topologies.sh   (or ONLY="test-fanout test-chainfanout" ./phase3_topologies.sh)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
PLANS="${ONLY:-test-fanout test-fairness test-chain test-chainfanout}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase3_${STAMP}.log") 2>&1

echo "===== PHASE 3 START $STAMP ====="
for target in $PLANS; do
    echo "===== [$STAMP] $target ====="
    if make "$target" FAST_IO="$FAST_IO"; then
        batch="$(cat artifacts/runs/.latest)"
        python3 analysis/aggregate.py "$batch" \
            --out "artifacts/reports/${target#test-}_agg_${STAMP}.csv" --min-repeats 1
    else
        echo "WARN: $target FAILED (continuing with next)"
    fi
    make report || echo "WARN: make report failed"
done
echo "===== PHASE 3 DONE ====="
