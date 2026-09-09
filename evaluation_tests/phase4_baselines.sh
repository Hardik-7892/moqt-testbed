#!/bin/bash
# Phase 4 — Baselines + headline -> H2/H3 baselines, Fig 6.7 (MoQ vs H2 vs H3, x3 aggregated).
# Runs: test-lldash-h2, test-lldash-h3, test-lldash (1x each), test-moq-vs-lldash x3.
# NOTE (B36): re-tags local moq-rs pin onto Hub tags BEFORE the headline rows,
#   else all 6 MoQ rows fail on tag skew.
# Usage: ./phase4_baselines.sh   (or REPEATS_HEADLINE=1 ./phase4_baselines.sh for a fast pass)
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
REPEATS_HEADLINE="${REPEATS_HEADLINE:-3}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase4_${STAMP}.log") 2>&1

run_once() {  # $1=make target
    echo "===== [$STAMP] $1 ====="
    if make "$1" FAST_IO="$FAST_IO"; then
        batch="$(cat artifacts/runs/.latest)"
        python3 analysis/aggregate.py "$batch" \
            --out "artifacts/reports/${1#test-}_agg_${STAMP}.csv" --min-repeats 1
    else
        echo "WARN: $1 FAILED (continuing with next)"
    fi
    make report || echo "WARN: make report failed"
}

echo "===== PHASE 4 START $STAMP ====="
run_once test-lldash-h2
run_once test-lldash-h3
run_once test-lldash

echo "===== [$STAMP] B36 re-tag (Hub tags -> local pin) ====="
sudo docker tag moq-rs/relay:18 0hardikpandey/moq-rs-relay:18 \
  && sudo docker tag moq-rs/client:18 0hardikpandey/moq-rs-client:18 \
  && echo "re-tag OK" || echo "WARN: re-tag failed — headline MoQ rows may fail on tag skew"

batches=()
for i in $(seq 1 "$REPEATS_HEADLINE"); do
    echo "===== [$STAMP] test-moq-vs-lldash repeat $i/$REPEATS_HEADLINE ====="
    if make test-moq-vs-lldash FAST_IO="$FAST_IO"; then
        batches+=("$(cat artifacts/runs/.latest)")
    else
        echo "WARN: test-moq-vs-lldash repeat $i FAILED (continuing with next)"
    fi
done
if [ "${#batches[@]}" -ge 1 ]; then
    min_r=1; [ "${#batches[@]}" -ge 2 ] && min_r=3
    python3 analysis/aggregate.py "${batches[@]}" \
        --out "artifacts/reports/moq-vs-lldash_agg_${STAMP}.csv" --min-repeats "$min_r"
fi
make report || echo "WARN: make report failed"
echo "===== PHASE 4 DONE ====="
