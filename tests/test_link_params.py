"""B12 (found-bugs.md): per-device impairment tests.

These exercise link_params_for_role() and friends WITHOUT Docker/Containernet,
following the pattern set by _sub_launch_redirect (B18). The logic is the
single source of truth for every TCLink's bw/delay/loss.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.runner import MoQTestRun  # noqa: E402

TOP = {"bw": 100, "delay": "10ms", "loss": 0}


def make_run(batch_dir, topology="basic", network=None, run_id="test-run-1"):
    net = dict(TOP)
    if network:
        net.update(network)
    run_config = {
        "id": run_id,
        "topology": topology,
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "network": net,
    }
    if topology == "chain":
        run_config["relay_a"] = run_config["relay"]
        run_config["relay_b"] = run_config["relay"]
    return MoQTestRun(run_config, TOP, batch_dir, default_test_duration=15)


def test_basic_default_impairs_sub_only(tmp_path):
    run = make_run(tmp_path / "batch")
    assert run.link_params_for_role("pub") == run.CLEAN_LINK
    assert run.link_params_for_role("relay") == run.CLEAN_LINK
    assert run.link_params_for_role("sub") == TOP
    assert run._impaired_host_names() == {"sub"}


def test_basic_devices_opt_in(tmp_path):
    run = make_run(tmp_path / "batch", network={"devices": {"pub": {"loss": 5}}})
    assert run.link_params_for_role("pub") == {"bw": 100, "delay": "10ms", "loss": 5}
    assert run.link_params_for_role("relay") == run.CLEAN_LINK
    # devices present => unlisted roles (even the default subscriber) go clean
    assert run.link_params_for_role("sub") == run.CLEAN_LINK
    assert run._impaired_host_names() == {"pub"}


def test_basic_devices_override_merges_over_top_level(tmp_path):
    run = make_run(tmp_path / "batch", network={"devices": {"sub": {"delay": "30ms"}}})
    assert run.link_params_for_role("sub") == {"bw": 100, "delay": "30ms", "loss": 0}
    assert run.link_params_for_role("pub") == run.CLEAN_LINK


def test_basic_devices_can_impair_relay(tmp_path):
    run = make_run(tmp_path / "batch", network={"devices": {"relay": {"bw": 10}}})
    assert run.link_params_for_role("relay") == {"bw": 10, "delay": "10ms", "loss": 0}
    assert run.link_params_for_role("sub") == run.CLEAN_LINK


def test_fanout_default_impairs_all_subs(tmp_path):
    run = make_run(tmp_path / "batch", topology="fanout",
                   network={"num_subscribers": 2})
    assert run.link_params_for_role("pub") == run.CLEAN_LINK
    assert run.link_params_for_role("relay") == run.CLEAN_LINK
    assert run.link_params_for_role("sub1") == TOP
    assert run.link_params_for_role("sub2") == TOP
    assert run._impaired_host_names() == {"sub1", "sub2"}


def test_fanout_per_sub_override(tmp_path):
    run = make_run(tmp_path / "batch", topology="fanout",
                   network={"num_subscribers": 2,
                            "devices": {"sub1": {"loss": 2}}})
    assert run.link_params_for_role("sub1") == {"bw": 100, "delay": "10ms", "loss": 2}
    assert run.link_params_for_role("sub2") == run.CLEAN_LINK


def test_chain_default_inter_relay_carries_relay_delay(tmp_path):
    run = make_run(tmp_path / "batch", topology="chain",
                   network={"relay_delay": "20ms"})
    assert run.link_params_for_role("pub") == run.CLEAN_LINK
    assert run.link_params_for_role("sub") == TOP
    assert run.link_params_for_role("relay_b") == run.CLEAN_LINK
    assert run._inter_relay_link_params() == {"bw": 1000, "delay": "20ms", "loss": 0}


def test_chain_relay_a_in_devices_uses_merged_params(tmp_path):
    run = make_run(tmp_path / "batch", topology="chain",
                   network={"relay_delay": "20ms",
                            "devices": {"relay_a": {"loss": 2}}})
    assert run._inter_relay_link_params() == {"bw": 100, "delay": "10ms", "loss": 2}


def test_is_impaired(tmp_path):
    run = make_run(tmp_path / "batch")
    assert run._is_impaired({"bw": 100, "delay": "10ms", "loss": 1}) is True
    assert run._is_impaired({"bw": 1000, "delay": "1ms", "loss": 0}) is False
    assert run._is_impaired({"bw": 100, "delay": "1ms", "loss": 0}) is True


def test_chain_inter_relay_impairment_verified(tmp_path):
    # Default: inter-relay has relay_delay=20ms, so it IS impaired
    # and should be included in _impaired_host_names() -> relay_a
    run = make_run(tmp_path / "batch", topology="chain",
                   network={"relay_delay": "20ms"})
    impaired = run._impaired_host_names()
    assert "relay_a" in impaired, "chain inter-relay impaired -> relay_a should be in impaired set"
    assert "sub" in impaired, "sub should also be impaired by default"

    # If relay_delay is clean (1ms), inter-relay is NOT impaired
    run_clean = make_run(tmp_path / "batch", topology="chain",
                         network={"relay_delay": "1ms"})
    impaired_clean = run_clean._impaired_host_names()
    assert "relay_a" not in impaired_clean, "clean inter-relay -> relay_a should NOT be in impaired set"

    # devices override: if relay_a in devices, use merged params
    run_dev = make_run(tmp_path / "batch", topology="chain",
                       network={"relay_delay": "20ms",
                                "devices": {"relay_a": {"loss": 2}}})
    impaired_dev = run_dev._impaired_host_names()
    assert "relay_a" in impaired_dev, "devices override -> relay_a should be in impaired set"