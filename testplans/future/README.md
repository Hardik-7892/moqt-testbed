# QUARANTINED (Phase 1, 2026-09-06) — see 2_weeks/01-future-work-quarantine.md.
#
# This plan uses keys the runner never reads (listed below), so running it
# would produce identical rows that look like a comparison. It fails fast via
# harness/plan_validation.py instead of passing silently.
#
# Unwired keys in this file: <see 2_weeks/01-future-work-quarantine.md table>.
# Re-admission rule: wire the keys in harness/runner.py or topologies/*.py +
# Docker-free unit test + one VM batch with tc_*.log evidence per row.
