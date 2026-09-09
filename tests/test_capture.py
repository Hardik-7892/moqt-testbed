"""B3 (found-bugs.md): per-container tcpdump capture tests.

Exercise start_capture's command shape, the graceful-skip probe, and the
opt-in `capture` flag without Docker (same pattern as test_completion.py).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness.runner import MoQTestRun  # noqa: E402

TOP = {"bw": 100, "delay": "10ms", "loss": 0}


def make_run(batch_dir, network=None, run_id="test-run-1", capture=False,
             run_capture=None, net_capture=None):
    net = dict(TOP)
    if network:
        net.update(network)
    if net_capture is not None:
        net["capture"] = net_capture
    run_config = {
        "id": run_id,
        "topology": "basic",
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "moq-rs/client:18"},
        "network": net,
    }
    if run_capture is not None:
        run_config["capture"] = run_capture
    return MoQTestRun(run_config, TOP, batch_dir, capture=capture)


def test_start_capture_uses_container_interface_and_mounted_paths(tmp_path):
    run = make_run(tmp_path)
    cmd = run.start_capture("pub")
    # B42: the in-host link is named {host}-eth0 on Containernet (the old
    # `-i eth0` only ever saw default-bridge multicast, never the QUIC flows).
    assert "-i pub-eth0" in cmd
    assert "-w /pcaps/pub.pcap" in cmd
    assert "2>/logs/tcpdump_pub.log" in cmd
    # must NOT fall back to bare eth0 or reference host-side paths anymore
    assert "-i eth0" not in cmd
    assert run.pcaps_dir.as_posix() not in cmd


def test_tcpdump_available_probes_container(tmp_path):
    run = make_run(tmp_path)

    class Host:
        def cmd(self, c):
            return "/usr/sbin/tcpdump"

    assert run._tcpdump_available(Host()) is True

    class MissingHost:
        def cmd(self, c):
            return ""

    assert run._tcpdump_available(MissingHost()) is False

    class BoomHost:
        def cmd(self, c):
            raise RuntimeError("container gone")

    assert run._tcpdump_available(BoomHost()) is False


def test_capture_off_by_default(tmp_path):
    run = make_run(tmp_path)
    assert run.capture is False


def test_capture_enabled_via_run_config(tmp_path):
    run = make_run(tmp_path, run_capture=True)
    assert run.capture is True


def test_capture_enabled_via_network(tmp_path):
    run = make_run(tmp_path, net_capture=True)
    assert run.capture is True


def test_capture_enabled_via_constructor(tmp_path):
    run = make_run(tmp_path, capture=True)
    assert run.capture is True


def test_run_config_beats_constructor_off(tmp_path):
    # an explicit per-run `capture: false` must not be overridden by the
    # plan-level default passed through the constructor.
    run = make_run(tmp_path, capture=True, run_capture=False)
    assert run.capture is False
