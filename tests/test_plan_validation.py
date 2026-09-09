"""Phase 1 (P0-3): unwired plan keys must fail fast, never run silently.

Covers harness/plan_validation.py wired into TestbedRunner.__init__.
Docker-free: validates loaded YAML dicts only, no containers.
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.plan_validation import validate_testplan  # noqa: E402

TESTPLANS = Path(__file__).resolve().parent.parent / "testplans"
FUTURE = TESTPLANS / "future"

# The 7 quarantined plans + the first unwired key each must trip.
QUARANTINED = {
    "aqm-sweep.yaml": "aqm",
    "bbr-cubic-fairness.yaml": "cc_algos",
    "datagram-vs-stream.yaml": "mode",
    "multi-pub-sub.yaml": "publishers",
    "track-priority.yaml": "filter_type",
    "congestion-cascade.yaml": "relays",
    "join-leave-dynamics.yaml": "leave_rejoin",
}

# Every citable plan must validate clean.
CITABLE = [
    "interop-quick.yaml", "interop-mismatch.yaml", "interop-full.yaml",
    "interop-built.yaml", "fanout.yaml", "chain.yaml", "chainfanout.yaml",
    "impairments.yaml",
    "bufferbloat.yaml", "fairness.yaml", "latency-sweep.yaml",
    "bandwidth-sweep.yaml", "loss-sweep.yaml", "queue-sweep.yaml",
    "cross-impl.yaml", "moq-rs-self.yaml", "moq-vs-lldash.yaml", "lldash-baseline.yaml",
    "lldash-h2.yaml", "lldash-h3.yaml",
]


def load(plan_path):
    with open(plan_path) as f:
        return yaml.safe_load(f)


def test_citable_plans_validate_clean():
    for name in CITABLE:
        plan = load(TESTPLANS / name)
        assert validate_testplan(plan, plan_name=name) == []


def test_quarantined_plans_fail_fast():
    for name, key in QUARANTINED.items():
        plan = load(FUTURE / name)
        with pytest.raises(ValueError, match="unwired key|misplaced key"):
            validate_testplan(plan, plan_name=f"testplans/future/{name}")


def test_each_unwired_key_family_trips():
    base_run = {
        "id": "probe",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "network": {"bw": 10},
    }
    for key in ["aqm", "mode", "cc_algos", "impl_pairs", "publishers",
                "tracks_per_pub", "relays", "leave_rejoin", "filter_type",
                "group_order", "priority"]:
        run = dict(base_run, **{key: "probe"})
        with pytest.raises(ValueError, match=f"'{key}'"):
            validate_testplan({"name": "t", "runs": [run]}, plan_name="t")


def test_misplaced_devices_and_num_subscribers_trip():
    run = {
        "id": "probe",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "devices": {"sub": {"bw": 5}},
        "network": {"bw": 10},
    }
    with pytest.raises(ValueError, match="network.devices"):
        validate_testplan({"name": "t", "runs": [run]}, plan_name="t")
    run2 = {
        "id": "probe2",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "num_subscribers": 3,
        "network": {"bw": 10},
    }
    with pytest.raises(ValueError, match="network.num_subscribers"):
        validate_testplan({"name": "t", "runs": [run2]}, plan_name="t")


def test_unknown_network_key_trips():
    run = {
        "id": "probe",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "network": {"bw": 10, "burst": 100},
    }
    with pytest.raises(ValueError, match="burst"):
        validate_testplan({"name": "t", "runs": [run]}, plan_name="t")


def test_reason_docs_only_string():
    run = {
        "id": "probe",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "network": {"bw": 10},
        "expect": "fail",
        "reason": "B43 framing mismatch",
    }
    assert validate_testplan({"name": "t", "runs": [run]}, plan_name="t") == []
    bad = dict(run, reason={"not": "a string"})
    with pytest.raises(ValueError, match="reason"):
        validate_testplan({"name": "t", "runs": [bad]}, plan_name="t")


def test_per_sub_overrides_need_fanout_topology():
    base = {
        "id": "probe",
        "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "sub3": {"impl": "imquic"},
        "network": {"bw": 10, "num_subscribers": 3},
    }
    with pytest.raises(ValueError, match="topology mismatch"):
        validate_testplan({"name": "t", "runs": [base]}, plan_name="t")
    ok_fanout = dict(base, topology="fanout")
    assert validate_testplan(
        {"name": "t", "runs": [ok_fanout]}, plan_name="t") == []
    ok_cf = dict(base, topology="chainfanout",
                 relay_a={"impl": "moq-rs"}, relay_b={"impl": "moq-rs"})
    del ok_cf["relay"]
    assert validate_testplan(
        {"name": "t", "runs": [ok_cf]}, plan_name="t") == []


def test_chainfanout_accepts_chain_roles():
    run = {
        "id": "probe",
        "topology": "chainfanout",
        "pub": {"impl": "moq-rs"},
        "relay_a": {"impl": "moq-rs"}, "relay_b": {"impl": "moq-rs"},
        "sub": {"impl": "moq-rs"},
        "network": {"num_subscribers": 2},
    }
    assert validate_testplan({"name": "t", "runs": [run]}, plan_name="t") == []
    basic = dict(run, topology="basic")
    with pytest.raises(ValueError, match="topology mismatch"):
        validate_testplan({"name": "t", "runs": [basic]}, plan_name="t")
