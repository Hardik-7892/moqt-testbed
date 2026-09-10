#!/bin/bash
# Phase 8 — Pin-verdict depth: make every load-bearing fanout number n=3.
# Runs (all sudo, workers=1, sequential):
#   draft16-probe x2  (plus existing run_20260910_180504 -> n=3 shared-fate)
#   d18-1seg-fanout x1 (fourth corner: same easy media on d18, predicts 1/2)
#   fanout-verify x2  (plus existing run_20260910_172052 -> n=3 full-window)
# No headline/interop/sweep plans touched. ~25 min total.
# Usage (on VM, NOT Windows):
#   chmod +x evaluation_tests/phase8_verify_depth.sh
#   sudo ./evaluation_tests/phase8_verify_depth.sh
#   tail -f artifacts/reports/phase8_*.log
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase8_${STAMP}.log") 2>&1

echo "===== PHASE 8 START $STAMP (MOQ_FAST_IO=$MOQ_FAST_IO) ====="
date
sudo -v || echo "WARN: sudo -v failed — subsequent sudo steps may prompt"

cleanup_mn() {
  sudo docker rm -f mn.pub mn.relay mn.sub mn.s1 2>/dev/null || true
  sudo docker ps -aq --filter "name=mn." 2>/dev/null | xargs -r sudo docker rm -f 2>/dev/null || true
}

# run_planfile_times <plan> <stub> <times> [extra_batch_dir ...]
# Runs the plan <times>, then aggregates ALL listed batches (old + new).
run_planfile_times() {
  local plan=$1 stub=$2 times=$3
  shift 3
  local batches=("$@") # pre-existing batches (may be empty)
  for b in "${batches[@]}"; do
    [ -d "$b" ] || echo "WARN: expected prior batch missing: $b"
  done
  for i in $(seq 1 "$times"); do
    echo "===== [$STAMP] $plan run $i/$times ====="
    date
    cleanup_mn
    if sudo MOQ_FAST_IO="$MOQ_FAST_IO" python3 run_testbed.py --plan "$plan" --workers 1; then
      batch="$(cat artifacts/runs/.latest)"
      echo "new batch: $batch"
      batches+=("$batch")
      python3 analysis/aggregate.py "$batch" \
        --out "artifacts/reports/${stub}_agg_${STAMP}_r${i}.csv" --min-repeats 1 \
        || echo "WARN: per-run aggregate failed ($stub r$i)"
    else
      echo "WARN: $plan run $i FAILED (continuing)"
    fi
    make report 2>/dev/null || sudo make report 2>/dev/null \
      || echo "WARN: make report failed after $stub run $i"
  done
  # keep only dirs that exist (a missing prior batch must not kill the aggregate)
  local have=()
  for b in "${batches[@]}"; do
    [ -d "$b" ] && have+=("$b") || echo "WARN: skipping missing batch $b"
  done
  if [ "${#have[@]}" -ge 1 ]; then
    local min_r=1; [ "${#have[@]}" -ge 3 ] && min_r=3
    python3 analysis/aggregate.py "${have[@]}" \
      --out "artifacts/reports/${stub}_agg_${STAMP}_n${#have[@]}.csv" --min-repeats "$min_r" \
      || echo "WARN: final aggregate failed ($stub)"
  else
    echo "WARN: $stub produced zero batches — nothing to aggregate"
  fi
}

# 1. d16 shared-fate to n=3 (two more onto the 180504 batch)
run_planfile_times testplans/draft16-probe.yaml draft16-probe 2 \
  artifacts/runs/run_20260910_180504

# 2. Fourth corner once (d18, easy media, full window)
run_planfile_times testplans/d18-1seg-fanout.yaml d18-1seg-fanout 1

# 3. Full-window referee check to n=3 (two more onto the 172052 batch)
run_planfile_times testplans/fanout-verify.yaml fanout-verify 2 \
  artifacts/runs/run_20260910_172052

echo "===== PHASE 8 DONE $STAMP ====="
date
echo "--- new aggregates ---"
ls -lh artifacts/reports/*"${STAMP}"*.csv 2>/dev/null || echo "no CSVs for STAMP $STAMP"
echo "--- latest batch ---"
cat artifacts/runs/.latest 2>/dev/null || echo "no .latest"
echo "--- log ---"
echo "artifacts/reports/phase8_${STAMP}.log"
echo "Paste back: the 3 *_n*.csv filenames + any WARN lines + the summary.txt blocks if anything reads unexpected (pass where fail was predicted, or vice versa)."
