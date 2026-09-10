"""Phase 1 — fail fast on unwired (silent no-op) plan keys.

Quarantined keys are documented in ``2_weeks/01-future-work-quarantine.md``.
They appear in ``testplans/future/*.yaml`` but are NEVER read by
``harness/runner.py`` or ``topologies/*.py`` — running them would produce
identical rows that look like comparisons (examiner hazard, P0-3).

``validate_testplan`` raises ``ValueError`` with an actionable message so a
run errors instead of passing silently. Called from
``TestbedRunner.__init__`` (plan-load path).
"""
from typing import Any, Dict, List
import re

# Run-level keys (siblings of ``network:``) that no code reads.
# Evidence: grep '"key"' harness/ topologies/ == 0 hits (audit 2026-09-06).
UNWIRED_RUN_KEYS = frozenset({
    "aqm",            # aqm-sweep.yaml x9 — tc AQM never applied
    "mode",           # datagram-vs-stream.yaml x6 — no datagram knob
    "cc_algos",       # bbr-cubic-fairness.yaml x13 — no CC flags
    "impl_pairs",     # same file x13 — no multi-impl pairing
    "publishers",     # multi-pub-sub.yaml — no N-pub orchestration
    "tracks_per_pub",  # same — always 1 stream (runner.py:938)
    "subscribers",    # same — use network.num_subscribers instead
    "tracks",         # same — no track lists
    "track_sharing",  # same
    "tracks_per_sub",  # same
    "start_group",    # same + track-priority.yaml
    "relays",         # congestion-cascade / join-leave / multi-pub-sub — chain hard-codes 2 relays
    "leave_rejoin",   # join-leave-dynamics.yaml — no live rejoin orchestration
    "filter_type",    # multi-pub-sub / track-priority — no SUBSCRIBE filter plumbing
    "group_order",    # same — no GROUP_ORDER plumbing
    "priority",       # same — no priority scheduling
    "filter",         # generic guard
})

# Misplaced variants of WIRED keys: only the network.* form is read.
# - devices: only network.devices (topologies/base.py:62)
# - num_subscribers: only network.num_subscribers (fanout.py:15, runner.py:1371)
MISPLACED_RUN_KEYS = {
    "devices": "network.devices",
    "num_subscribers": "network.num_subscribers",
}

# network.* keys that are wired (everything else inside network: errors).
# - quiet_period: consecutive no-growth polls before quiescence
#   (harness/runner.py _wait_for_completion; tests/test_completion.py).
WIRED_NETWORK_KEYS = frozenset({
    "bw", "delay", "loss", "max_queue_size", "relay_delay",
    "devices", "num_subscribers", "late_sub_count", "late_join_delay_s",
    "late_joins", "capture", "quiet_period",
})

# Plan-level keys that are wired or pure documentation (metrics: is docs-only).
WIRED_PLAN_KEYS = frozenset({
    "name", "description", "topology", "network_defaults", "test_duration",
    "media", "runs", "require_integrity", "integrity_threshold",
    "data_check", "min_objects", "require_draft", "capture", "metrics",
})

# Role keys that resolve to container images.
WIRED_ROLE_KEYS = frozenset({
    "pub", "relay", "relay_a", "relay_b", "sub",
    "sub1", "sub2", "sub3", "sub4", "sub5", "sub6", "sub7", "sub8",
})

WIRED_RUN_KEYS = frozenset({
    "id", "topology", "network", "media", "test_duration", "expect",
    "reason",
    "require_integrity", "integrity_threshold", "data_check", "min_objects",
    "require_draft", "capture", "late_joins", "late_join_delay_s",
    "late_sub_count", "num_subscribers_docs_only",
}) | WIRED_ROLE_KEYS


def validate_testplan(plan: Dict[str, Any], plan_name: str = "<plan>") -> List[str]:
    """Validate one loaded plan dict. Returns warnings, raises on error.

    Raises:
        ValueError: on any unwired or misplaced key — the run must NOT start.
    """
    warnings: List[str] = []
    for key in plan:
        if key not in WIRED_PLAN_KEYS:
            raise ValueError(
                f"unwired plan-level key '{key}' in {plan_name} — "
                f"no code reads it (see 2_weeks/01-future-work-quarantine.md)")
    for run in plan.get("runs", []):
        rid = run.get("id") or "<no-id>"
        for key in run:
            if key in UNWIRED_RUN_KEYS:
                raise ValueError(
                    f"unwired key '{key}' in run '{rid}' ({plan_name}) — "
                    f"quarantined to testplans/future/, see "
                    f"2_weeks/01-future-work-quarantine.md")
            if key in MISPLACED_RUN_KEYS:
                raise ValueError(
                    f"misplaced key '{key}' in run '{rid}' ({plan_name}) — "
                    f"only '{MISPLACED_RUN_KEYS[key]}' is read; "
                    f"move it under network: (see topologies/base.py)")
        # reason is docs-only (like num_subscribers_docs_only): no code
        # reads it, but it documents the predicted outcome next to expect:.
        if key == "reason" and not isinstance(run.get(key), str):
            raise ValueError(
                f"run-level key 'reason' in run '{rid}' ({plan_name}) — "
                f"must be a short string, not {type(run.get(key)).__name__}")
        if key not in WIRED_RUN_KEYS:
            raise ValueError(
                f"unknown run-level key '{key}' in run '{rid}' "
                f"({plan_name}) — add it to harness/plan_validation.py "
                f"with reader evidence or quarantine it")
        network = run.get("network", {}) or {}
        for key in network:
            if key not in WIRED_NETWORK_KEYS:
                raise ValueError(
                    f"unknown network key '{key}' in run '{rid}' "
                    f"({plan_name}) — wired keys: "
                    f"{sorted(WIRED_NETWORK_KEYS)}")
        # Phase 2: topology/role cross-check. The runner resolves topology
        # purely from run['topology'] (plan default when absent;
        # harness/runner.py:138,194) — a "chain" row without
        # topology: chain silently runs as basic with relay_a/relay_b ignored,
        # and a "fanout" row without topology: fanout silently runs as basic
        # with num_subscribers ignored. Fail fast instead.
        effective = run.get("topology", plan.get("topology", "basic"))
        if ("relay_a" in run or "relay_b" in run) and effective not in ("chain", "chainfanout"):
            raise ValueError(
                f"topology mismatch in run '{rid}' ({plan_name}) — "
                f"relay_a/relay_b present but topology is '{effective}', "
                f"so relay configs would be silently ignored; set "
                f"topology: chain or topology: chainfanout")
        if "num_subscribers" in network and effective not in ("fanout", "chainfanout"):
            raise ValueError(
                f"topology mismatch in run '{rid}' ({plan_name}) — "
                f"network.num_subscribers present but topology is "
                f"'{effective}', so it would be silently ignored; set "
                f"topology: fanout or topology: chainfanout")
        sub_overrides = [k for k in run
                         if re.match(r"^sub[1-9][0-9]*$", k or "")]
        if sub_overrides and effective not in ("fanout", "chainfanout"):
            raise ValueError(
                f"topology mismatch in run '{rid}' ({plan_name}) — "
                f"per-subscriber overrides {sorted(sub_overrides)} present but "
                f"topology is '{effective}', so they would be silently "
                f"ignored; set topology: fanout or topology: chainfanout")
    return warnings
