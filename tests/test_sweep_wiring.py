"""Phase 2 (P0-1/P0-2): bottleneck placement + topology selection guards.

Docker-free: validates loaded YAML dicts + link-param mapping only.

Background:
- The runner resolves topology purely from run['topology'] (plan default when
  absent; harness/runner.py:138,194). A nominal "chain" row without
  topology: chain silently runs as basic with relay_a/relay_b ignored; a
  nominal "fanout" row without topology: fanout silently runs as basic with
  network.num_subscribers ignored.
- Chain sweep rows must constrain the inter-relay link via
  network.devices.relay_a (topologies/chain.py:84-86); top-level bw/loss/delay
  alone hits the sub wire only.
- Fanout devices.sub{i} rows are independent last-mile shapers; the shared
  bottleneck approximation is devices.relay (fairness.yaml).
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.plan_validation import validate_testplan  # noqa: E402
from harness.runner import MoQTestRun  # noqa: E402

TESTPLANS = Path(__file__).resolve().parent.parent / "testplans"

SWEEPS = ["bandwidth-sweep.yaml", "latency-sweep.yaml", "loss-sweep.yaml",
          "queue-sweep.yaml"]


def load(name):
    with open(TESTPLANS / name) as f:
        return yaml.safe_load(f)


def effective_topology(plan, run):
    return run.get("topology", plan.get("topology", "basic"))


def test_sweep_chain_rows_build_a_chain():
    """Every nominal chain row in the sweeps must resolve to chain topology."""
    for name in SWEEPS:
        plan = load(name)
        chain_rows = [r for r in plan["runs"]
                      if "relay_a" in r or r.get("id", "").endswith("-chain")]
        assert chain_rows, f"{name}: expected chain rows"
        for run in chain_rows:
            assert effective_topology(plan, run) == "chain", (
                f"{name}/{run.get('id')}: relay_a present but topology "
                f"resolves to '{effective_topology(plan, run)}'")


def test_sweep_fanout_rows_build_fanout():
    """Every nominal fanout row in the sweeps must resolve to fanout."""
    for name in SWEEPS:
        plan = load(name)
        fan_rows = [r for r in plan["runs"]
                    if (r.get("network", {}) or {}).get("num_subscribers")
                    or "fanout" in r.get("id", "")]
        assert fan_rows, f"{name}: expected fanout rows"
        for run in fan_rows:
            assert effective_topology(plan, run) == "fanout", (
                f"{name}/{run.get('id')}: num_subscribers present but "
                f"topology resolves to '{effective_topology(plan, run)}'")


def test_chain_rows_with_impairments_constrain_inter_relay():
    """Chain rows that set bw/loss/delay must carry devices.relay_a.

    Queue-only chain rows are exempt: max_queue_size never reaches the
    inter-relay link (runner.py:1277), documented in queue-sweep.yaml.
    Baseline rows without a network: block are exempt (defaults apply).
    """
    for name in SWEEPS + ["chain.yaml"]:
        plan = load(name)
        for run in plan["runs"]:
            if effective_topology(plan, run) != "chain":
                continue
            net = run.get("network", {}) or {}
            if not any(k in net for k in ("bw", "loss", "delay")):
                continue
            if all(net.get(k) in (None, 0, "0ms")
                   for k in ("bw", "loss", "delay") if k in net):
                continue
            devices = net.get("devices", {}) or {}
            assert "relay_a" in devices, (
                f"{name}/{run.get('id')}: chain impairment without "
                f"devices.relay_a would hit the sub wire only (P0-1)")


def test_fairness_shared_egress_rows():
    plan = load("fairness.yaml")
    egress = [r for r in plan["runs"] if "shared-egress" in r.get("id", "")]
    assert len(egress) == 2
    for run in egress:
        devices = run["network"]["devices"]
        assert "relay" in devices, "shared-egress must shape devices.relay"
        assert not any(k.startswith("sub") for k in devices), (
            "shared-egress isolates relay scheduling: subs stay CLEAN")


def test_validator_rejects_topology_mismatch():
    base = {"pub": {"impl": "m"}, "relay": {"impl": "m"},
            "sub": {"impl": "m"}, "network": {"bw": 10}}
    # relay_a without chain topology
    run = dict(base, id="x", relay_a={"impl": "m"})
    with pytest.raises(ValueError, match="topology mismatch"):
        validate_testplan({"name": "t", "topology": "basic",
                           "runs": [run]}, plan_name="t")
    # num_subscribers without fanout topology
    run2 = dict(base, id="y",
                network={"bw": 10, "num_subscribers": 3})
    with pytest.raises(ValueError, match="topology mismatch"):
        validate_testplan({"name": "t", "topology": "basic",
                           "runs": [run2]}, plan_name="t")
    # correct pairings pass
    run3 = dict(base, id="z", topology="chain",
                relay_a={"impl": "m"}, relay_b={"impl": "m"})
    validate_testplan({"name": "t", "topology": "basic", "runs": [run3]},
                      plan_name="t")


def _make_run(batch_dir, topology, network, run_id="p2-probe"):
    run_config = {
        "id": run_id,
        "topology": topology,
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "network": network,
    }
    return MoQTestRun(run_config, {"bw": 100, "delay": "10ms", "loss": 0},
                      batch_dir, default_test_duration=15)


def test_fanout_shared_egress_link_params(tmp_path):
    """devices.relay impairs the relay wire; unlisted subs go CLEAN."""
    run = _make_run(tmp_path / "batch", "fanout",
                    {"bw": 100, "delay": "10ms", "loss": 0,
                     "num_subscribers": 3, "devices": {"relay": {"bw": 10}}})
    assert run.link_params_for_role("relay") == {"bw": 10, "delay": "10ms",
                                                 "loss": 0}
    assert run.link_params_for_role("sub1") == run.CLEAN_LINK
    assert run._impaired_host_names() == {"relay"}


def test_chain_devices_relay_a_shapes_inter_relay(tmp_path):
    """End-to-end check of a Phase-2 chain row's resolved params."""
    run_config = {
        "id": "bw-10mbps-chain",
        "topology": "chain",
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay_a": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "relay_b": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "network": {"bw": 10, "delay": "20ms", "loss": 0,
                    "devices": {"relay_a": {"bw": 10}}},
    }
    run = MoQTestRun(run_config, {"bw": 100, "delay": "10ms", "loss": 0},
                     tmp_path / "batch", default_test_duration=15)
    assert run._inter_relay_link_params() == {"bw": 10, "delay": "20ms",
                                              "loss": 0}
    assert run.link_params_for_role("sub") == run.CLEAN_LINK
    assert "relay_a" in run._impaired_host_names()
