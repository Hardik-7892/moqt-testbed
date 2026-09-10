#!/bin/bash
# Phase 9 — Corner depth: d18-1seg-fanout x2, pooled with run_20260910_202206.
# Closes the last n=1 among load-bearing rows (pin-vs-media square -> n=3).
# Predicted: fail+fail+fail, [full 1/2] each. A pass or [full 2/2] anywhere
# contradicts two datasets at once: the script flags it LOUD and stops
# aggregating further meaning into it (no auto-promotion).
# No other plans touched. ~10 min total. Sleep-safe: no prompts when the
# whole script is launched under sudo (inner sudos become no-ops).
# Usage (on VM, NOT Windows):
#   chmod +x evaluation_tests/phase9_corner_depth.sh
#   sudo ./evaluation_tests/phase9_corner_depth.sh
#   tail -f artifacts/reports/phase9_*.log
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
PRIOR_BATCH="artifacts/runs/run_20260910_202206"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase9_${STAMP}.log") 2>&1

echo "===== PHASE 9 START $STAMP (MOQ_FAST_IO=$MOQ_FAST_IO) ====="
date
sudo -v || echo "WARN: sudo -v failed — subsequent sudo steps may prompt"
[ -d "$PRIOR_BATCH" ] || echo "WARN: prior corner batch missing: $PRIOR_BATCH"

cleanup_mn() {
  sudo docker rm -f mn.pub mn.relay mn.sub mn.s1 2>/dev/null || true
  sudo docker ps -aq --filter "name=mn." 2>/dev/null | xargs -r sudo docker rm -f 2>/dev/null || true
}

batches=()
if [ -d "$PRIOR_BATCH" ]; then
  batches+=("$PRIOR_BATCH")
fi
for i in 1 2; do
  echo "===== [$STAMP] d18-1seg-fanout run $i/2 ====="
  date
  cleanup_mn
  if sudo MOQ_FAST_IO="$MOQ_FAST_IO" python3 run_testbed.py --plan testplans/d18-1seg-fanout.yaml --workers 1; then
    batch="$(cat artifacts/runs/.latest)"
    echo "new batch: $batch"
    batches+=("$batch")
    python3 analysis/aggregate.py "$batch" \
      --out "artifacts/reports/d18-1seg-fanout_agg_${STAMP}_r${i}.csv" --min-repeats 1 \
      || echo "WARN: per-run aggregate failed (r$i)"
  else
    echo "WARN: d18-1seg-fanout run $i FAILED (continuing)"
  fi
  make report 2>/dev/null || sudo make report 2>/dev/null \
    || echo "WARN: make report failed after run $i"
done

have=()
for b in "${batches[@]}"; do
  [ -d "$b" ] && have+=("$b") || echo "WARN: skipping missing batch $b"
done
OUT="artifacts/reports/d18-1seg-fanout_agg_${STAMP}_n${#have[@]}.csv"
if [ "${#have[@]}" -ge 1 ]; then
  min_r=1; [ "${#have[@]}" -ge 3 ] && min_r=3
  python3 analysis/aggregate.py "${have[@]}" --out "$OUT" --min-repeats "$min_r" \
    || echo "WARN: final aggregate failed"
else
  echo "WARN: zero batches — nothing to aggregate"
fi

echo "===== VERDICT CHECK ====="
if [ -f "$OUT" ]; then
  cat "$OUT"
  if grep -q "d18-fanout-2sub-1seg,3,pass" "$OUT"; then
    echo "!!! FLAG: corner reads PASS — contradicts d18 starvation data, do NOT promote, investigate first"
  elif grep -q "d18-fanout-2sub-1seg,3,fail" "$OUT"; then
    echo "OK: corner reads fail x3 as predicted — square closed, safe to upgrade the n-labels"
  else
    echo "??? UNEXPECTED shape (partial/mixed or n<3) — paste this CSV back before any doc edit"
  fi
else
  echo "??? no aggregate produced — paste the log tail back"
fi

echo "===== PHASE 9 DONE $STAMP ====="
date
echo "--- latest batch ---"
cat artifacts/runs/.latest 2>/dev/null || echo "no .latest"
echo "--- log ---"
echo "artifacts/reports/phase9_${STAMP}.log"
