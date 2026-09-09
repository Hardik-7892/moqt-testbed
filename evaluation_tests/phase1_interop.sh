#!/bin/bash
# Phase 1 — Smoke + interop core -> Table 6.2, confusion matrix, Fig 6.1 baseline.
# Runs: test-quick x3 (aggregated), test-moqrs-self, test-mismatch, test-built,
#   test-full, test-cross-impl.
# Usage: ./phase1_interop.sh   (or REPEATS_QUICK=1 ./phase1_interop.sh for a fast pass)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
REPEATS_QUICK="${REPEATS_QUICK:-3}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase1_${STAMP}.log") 2>&1

run_plan() {  # $1=make target, $2=repeats, $3=csv stub
    local target=$1 repeats=$2 stub=$3
    local batches=()
    for i in $(seq 1 "$repeats"); do
        echo "===== [$STAMP] $target repeat $i/$repeats ====="
        if make "$target" FAST_IO="$FAST_IO"; then
            batches+=("$(cat artifacts/runs/.latest)")
        else
            echo "WARN: $target repeat $i FAILED (continuing with next)"
        fi
    done
    if [ "${#batches[@]}" -ge 1 ]; then
        local min_r=1; [ "${#batches[@]}" -ge 2 ] && min_r=3
        python3 analysis/aggregate.py "${batches[@]}" \
            --out "artifacts/reports/${stub}_agg_${STAMP}.csv" --min-repeats "$min_r"
    fi
    make report || echo "WARN: make report failed"
}

echo "===== PHASE 1 START $STAMP ====="
run_plan test-quick "$REPEATS_QUICK" interop-quick
run_plan test-moqrs-self 1 moqrs-self
run_plan test-mismatch 1 interop-mismatch
run_plan test-built 1 interop-built
run_plan test-full 1 interop-full
run_plan test-cross-impl 1 cross-impl
echo "===== PHASE 1 DONE ====="
