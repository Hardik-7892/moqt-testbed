#!/bin/bash
# Phase 5 — Large-file + close-out -> Fig 6.2 (FAST_IO attribution), Fig 6.5 (group-skipping),
#   per-impl self-interop appendix material.
# Runs: test-bbb-smoke (FAST_IO=1, sudo inside Makefile), test-imquic-self, test-moxygen-self.
# Usage: ./phase5_largefile.sh   (or ONLY="test-imquic-self" ./phase5_largefile.sh)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO=1
PLANS="${ONLY:-test-bbb-smoke test-imquic-self test-moxygen-self}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase5_${STAMP}.log") 2>&1

echo "===== PHASE 5 START $STAMP (FAST_IO=1) ====="
for target in $PLANS; do
    echo "===== [$STAMP] $target ====="
    if make "$target" FAST_IO=1; then
        batch="$(cat artifacts/runs/.latest)"
        python3 analysis/aggregate.py "$batch" \
            --out "artifacts/reports/${target#test-}_agg_${STAMP}.csv" --min-repeats 1
    else
        echo "WARN: $target FAILED (continuing with next)"
    fi
    make report || echo "WARN: make report failed"
done
echo "===== PHASE 5 DONE ====="
echo "CSVs: artifacts/reports/*_agg_${STAMP}.csv | Reports: <batch>/report.html | Log: artifacts/reports/phase5_${STAMP}.log"
