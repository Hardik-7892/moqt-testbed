#!/bin/bash
# Phase 2 — Impairment sweeps -> Fig 6.1 (loss/latency/bandwidth curves), Fig 6.4 (queue/bufferbloat).
# Runs (1x each, ~2h total): test-loss, test-queue, test-bufferbloat,
#   test-latency, test-bandwidth, test-impairments.
# Usage: ./phase2_sweeps.sh   (or ONLY="test-loss test-queue" ./phase2_sweeps.sh for a subset)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
PLANS="${ONLY:-test-loss test-queue test-bufferbloat test-latency test-bandwidth test-impairments}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase2_${STAMP}.log") 2>&1

echo "===== PHASE 2 START $STAMP ====="
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
echo "===== PHASE 2 DONE ====="
