#!/bin/bash
# Phase 7 — Depth unattended: n=1 -> n=3 repeats + fanout N=5 then N=8.
# Goal: run it, walk away, check in a few hours. Continues past failures (WARN, never exit).
# What it does:
#   1. B36 re-tag check (local pin -> Hub tags, you already did this, kept as guard)
#   2. test-loss x REPEATS (default 3) -> loss_agg_<STAMP>_n3.csv
#   3. test-fanout x REPEATS -> fanout_agg_<STAMP>_n3.csv
#   4. test-fairness x REPEATS -> fairness_agg_<STAMP>_n3.csv
#   5. fanout-n5n8.yaml x REPEATS -> fanout-n5n8_agg_<STAMP>_n3.csv (N=5 + N=8 + loss1 + H3 control)
#   6. make report after each stage + final summary
# Usage (on VM, NOT Windows):
#   chmod +x evaluation_tests/phase7_depth_unattended.sh
#   sudo ./evaluation_tests/phase7_depth_unattended.sh
#   # custom repeats: sudo env REPEATS_DEPTH=2 ./evaluation_tests/phase7_depth_unattended.sh
#   # subset: sudo env ONLY="test-fanout test-fairness" ./evaluation_tests/phase7_depth_unattended.sh
#   # background: sudo nohup ./evaluation_tests/phase7_depth_unattended.sh > /tmp/phase7_nohup.log 2>&1 &
#   # follow: tail -f artifacts/reports/phase7_*.log
# NOTE 2026-09-10: make targets MUST run as root (Containernet says
# "Mininet must run as root" otherwise). run_make_repeats now uses
# "sudo make"; either invoke the whole script with sudo or leave the
# in-script sudo (needs one password prompt at most).
cd "$(dirname "$0")/.."

set -u
export MOQ_FAST_IO="${MOQ_FAST_IO:-1}"
FAST_IO="${FAST_IO:-1}"
REPEATS="${REPEATS_DEPTH:-3}"
PLANS="${ONLY:-test-loss test-fanout test-fairness fanout-n5n8}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p artifacts/reports
exec > >(tee -a "artifacts/reports/phase7_${STAMP}.log") 2>&1

echo "===== PHASE 7 DEPTH START $STAMP ====="
echo "REPEATS=$REPEATS PLANS='$PLANS' FAST_IO=$FAST_IO MOQ_FAST_IO=$MOQ_FAST_IO"
date
sudo -v || echo "WARN: sudo -v failed — docker/make steps may prompt later"

echo "===== [$STAMP] B36 re-tag guard (Hub tags -> local pin) ====="
sudo docker tag moq-rs/relay:18 0hardikpandey/moq-rs-relay:18 \
  && sudo docker tag moq-rs/client:18 0hardikpandey/moq-rs-client:18 \
  && echo "re-tag OK" || echo "WARN: re-tag failed — Hub-tag rows (H3 control uses Hub lldash, MoQ-N5N8 uses local so OK)"

cleanup_mn() {
  # Runner already purges mn.* itself (harness/runner.py); this is belt-and-braces
  # so a dead container never blocks the next repeat with 409 Conflict.
  sudo docker rm -f mn.pub mn.relay mn.sub mn.s1 2>/dev/null || true
  sudo docker ps -aq --filter "name=mn." 2>/dev/null | xargs -r sudo docker rm -f 2>/dev/null || true
}

run_make_repeats() {  # $1=make target, $2=csv stub
  # NOTE: Containernet/Mininet must run as root, so the run itself goes via
  # sudo. Aggregate/report are plain reads/writes and stay unsudoed so the
  # CSVs keep your ownership on the shared folder.
  local target=$1 stub=$2
  local batches=()
  for i in $(seq 1 "$REPEATS"); do
    echo "===== [$STAMP] $target repeat $i/$REPEATS ====="
    date
    cleanup_mn
    if sudo make "$target" FAST_IO="$FAST_IO"; then
      batch="$(cat artifacts/runs/.latest)"
      echo "repeat $i batch: $batch"
      batches+=("$batch")
      python3 analysis/aggregate.py "$batch" \
        --out "artifacts/reports/${stub}_agg_${STAMP}_r${i}.csv" --min-repeats 1 || echo "WARN: per-repeat aggregate failed ($target r$i)"
    else
      echo "WARN: $target repeat $i FAILED (continuing)"
    fi
    make report 2>/dev/null || sudo make report 2>/dev/null || echo "WARN: make report failed after $target r$i"
  done
  if [ "${#batches[@]}" -ge 1 ]; then
    local min_r=1; [ "${#batches[@]}" -ge 2 ] && min_r=3
    # Cap min_r at actual batch count so a 2/3 run still aggregates honestly
    if [ "${#batches[@]}" -lt "$min_r" ]; then min_r="${#batches[@]}"; fi
    python3 analysis/aggregate.py "${batches[@]}" \
      --out "artifacts/reports/${stub}_agg_${STAMP}_n${#batches[@]}.csv" --min-repeats "$min_r" \
      || echo "WARN: final aggregate failed ($stub)"
  else
    echo "WARN: $target produced zero batches — nothing to aggregate"
  fi
}

run_planfile_repeats() {  # $1=plan path, $2=csv stub
  local plan=$1 stub=$2
  local batches=()
  for i in $(seq 1 "$REPEATS"); do
    echo "===== [$STAMP] $plan repeat $i/$REPEATS ====="
    date
    cleanup_mn
    if sudo MOQ_FAST_IO="$MOQ_FAST_IO" python3 run_testbed.py --plan "$plan" --workers 1; then
      batch="$(cat artifacts/runs/.latest)"
      echo "repeat $i batch: $batch"
      batches+=("$batch")
      python3 analysis/aggregate.py "$batch" \
        --out "artifacts/reports/${stub}_agg_${STAMP}_r${i}.csv" --min-repeats 1 || echo "WARN: per-repeat aggregate failed ($stub r$i)"
    else
      echo "WARN: $plan repeat $i FAILED (continuing)"
    fi
    make report 2>/dev/null || sudo make report 2>/dev/null || echo "WARN: make report failed after $stub r$i"
  done
  if [ "${#batches[@]}" -ge 1 ]; then
    local min_r=1; [ "${#batches[@]}" -ge 2 ] && min_r=3
    if [ "${#batches[@]}" -lt "$min_r" ]; then min_r="${#batches[@]}"; fi
    python3 analysis/aggregate.py "${batches[@]}" \
      --out "artifacts/reports/${stub}_agg_${STAMP}_n${#batches[@]}.csv" --min-repeats "$min_r" \
      || echo "WARN: final aggregate failed ($stub)"
  else
    echo "WARN: $plan produced zero batches — nothing to aggregate"
  fi
}

for target in $PLANS; do
  case "$target" in
    test-loss)     run_make_repeats test-loss loss-depth ;;
    test-fanout)   run_make_repeats test-fanout fanout-depth ;;
    test-fairness) run_make_repeats test-fairness fairness-depth ;;
    fanout-n5n8)   run_planfile_repeats testplans/fanout-n5n8.yaml fanout-n5n8 ;;
    *) echo "WARN: unknown plan '$target' (want: test-loss test-fanout test-fairness fanout-n5n8) — skipping" ;;
  esac
done

echo "===== PHASE 7 DONE $STAMP ====="
date
echo "--- new aggregates ---"
ls -lh artifacts/reports/*"${STAMP}"*.csv 2>/dev/null || echo "no CSVs for STAMP $STAMP"
echo "--- latest batch ---"
cat artifacts/runs/.latest 2>/dev/null || echo "no .latest"
echo "--- log ---"
echo "artifacts/reports/phase7_${STAMP}.log"
echo "Next: copy these 4 CSV names + the log tail into chat for the thesis wiring (E3/E4 + Fig 6.1/6.2)."
