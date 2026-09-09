#!/usr/bin/env python3
import argparse
import datetime
import fnmatch
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def to_vm_path(path: Path) -> str:
    """Convert a Windows path to the VM's shared folder path.
    
    When running from Windows, the testdata/artifacts directories are accessed
    via the VM's shared folder mount at /mnt/moq-testbed.
    """
    path_str = str(path.resolve())
    if platform.system() == "Windows":
        # Convert C:\projects\moq-testbed\... to /mnt/moq-testbed/...
        # Handle both forward and backslashes
        path_str = path_str.replace("\\", "/")
        if path_str.startswith("C:/projects/moq-testbed/"):
            return path_str.replace("C:/projects/moq-testbed/", "/mnt/moq-testbed/")
        if path_str.startswith("C:\\projects\\moq-testbed\\"):
            return path_str.replace("C:\\projects\\moq-testbed\\", "/mnt/moq-testbed/")
    return str(path.resolve())

# B8 (see found-bugs.md): TopologyBuilder / ScenarioApplier are DEAD CODE
# (config-driven topology never wired into the runner). Commented out 2026-08-04
# so the codebase doesn't mislead us. Re-enable when/if topology.yaml + scenarios.yaml
# are actually used. See harness/topology.py and harness/scenarios.py for the
# commented-out implementations.
# from harness.topology import TopologyBuilder
# from harness.scenarios import ScenarioApplier
from harness.certs import ensure_cert_set
from harness.measure import MetricsCollector
from harness.playable import export_playable
from harness.report import ReportGenerator
from harness.verify import verify_groups, media_bytes
from topologies import TOPOLOGIES, CLEAN_LINK


BASE_DIR = Path(__file__).parent.parent.resolve()
ARTIFACTS_DIR = BASE_DIR / "artifacts" / "runs"
REGISTRY_PATH = BASE_DIR / "registry.json"
TOPOLOGY_PATH = BASE_DIR / "topology.yaml"
SCENARIOS_PATH = BASE_DIR / "scenarios.yaml"
TESTDATA_DIR = BASE_DIR / "testdata"

CONTAINER_RELAY_PORT = 4443


def _env_float(name: str, default: float) -> float:
    """Read a positive float env override, falling back to default.

    Follows the MOQ_FAST_IO precedent: env-gated experiment knobs that
    leave historic defaults frozen (comparability with old batches).
    Unparseable/non-positive values fall back to default (loud at use).
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        val = float(raw)
    except ValueError:
        print(f"WARN: {name}={raw!r} unparseable, using default {default}")
        return default
    if val <= 0:
        print(f"WARN: {name}={raw!r} not positive, using default {default}")
        return default
    return val


def _teardown_order() -> str:
    """Teardown kill order probe (see MoQTestRun teardown).

    Default pub-first is B37 (kill pub, relay drains, sub exits on stream
    end). relay-first kills the RELAY instead so the subscriber sees
    connection-close and -- hypothesis -- exits cleanly with full stdout
    flush. Unknown values fall back to pub-first (loud).
    """
    order = os.environ.get("MOQ_TEARDOWN_ORDER", "pub-first").strip()
    if order not in ("pub-first", "relay-first"):
        print(f"WARN: MOQ_TEARDOWN_ORDER={order!r} unknown, using pub-first")
        return "pub-first"
    return order


def load_testplan(path: str) -> Dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def make_run_id(run: Dict[str, Any]) -> str:
    pub = run.get("pub", {})
    relay = run.get("relay", {})
    sub = run.get("sub", {})
    net = run.get("network", {})
    loss = net.get("loss", 0)
    delay = net.get("delay", "0ms")
    bw = net.get("bw", 100)
    run_id = (
        f"pub-{pub.get('impl','?')}d{pub.get('draft','?')}_"
        f"rel-{relay.get('impl','?')}d{relay.get('draft','?')}_"
        f"sub-{sub.get('impl','?')}d{sub.get('draft','?')}_"
        f"b{bw}_d{delay}_l{loss}"
    )
    run_id = run_id.replace(":", "-").replace("/", "-").replace(".", "-")
    return run_id


def sanitize_dirname(name: str) -> str:
    """Turn a run_id into a safe filesystem folder name."""
    return "".join(c if (c.isalnum() or c in "-_") else "-" for c in name)


class MoQTestRun:
    # Seconds between SIGINT to subscribers and the hard cleanup. Long enough
    # for a tokio ctrl-c handler to exit and flush stdout (B26 tail-loss
    # experiment), short enough not to drag out every batch.
    STOP_GRACE_S = 3.0

    # Publishers whose log announces object progress ("segment: N") — used by
    # _wait_for_pub_ready to gate the subscriber join on real servable data
    # (B37 addendum: namespace registration alone races ahead of groups).
    PUB_SEGMENT_LOG_IMPLS = {"moq-rs"}

    # Seconds to keep collecting after the publisher is stopped at teardown:
    # the relay drains its queue and the subscriber hits stream-end, exits
    # NORMALLY, and Rust flushes stdout -- recovering every byte the sub
    # actually received but hadn't flushed when SIGINT alone failed to make
    # it flush (B37: 29 MB died in the buffer at kill time).
    STOP_DRAIN_S = 12.0

    # B38: moq-rs subscribers send SUBSCRIBE once and die permanently on
    # "Track not found" (relay holds the namespace before its track state is
    # servable). Detect the death signature early and relaunch -- evidence
    # logs are rotated per attempt so the failure stays inspectable.
    SUB_DEATH_SIGS = (
        "Track not found",
        "media error",
        "error subscribing",
        "Closed(16)",
        "Invalid QUIC server address",
    )
    MAX_SUB_RESTARTS = 2

    def __init__(self, run_config: Dict[str, Any], network_defaults: Dict[str, Any],
                 batch_dir: Path, media_file: str = "sample.mp4",
                 default_test_duration: int = 15, capture: bool = False):
        self.config = run_config
        self.network = {**network_defaults, **run_config.get("network", {})}
        self.media_file = media_file
        self.default_test_duration = default_test_duration
        # B3 (see found-bugs.md): per-container tcpdump is OPT-IN. pcap files
        # are large (a full 82 MB delivery is ~100 MB+ per host), so capture
        # only runs when the plan says so: plan top-level `capture: true`,
        # network_defaults.capture, or a per-run `capture: true`.
        self.capture = bool(run_config.get("capture", capture)
                            or self.network.get("capture", False))
        self.run_id = run_config.get("id") or make_run_id(run_config)
        # B1 (see found-bugs.md): each run gets its OWN folder inside the batch
        # (batch_dir/<run_id>), so logs don't clobber and outputs don't
        # accumulate across runs in the same batch.
        self.run_dir = batch_dir / sanitize_dirname(self.run_id)
        self.topology_type = run_config.get("topology", "basic")
        # B: per-run test_duration overrides the plan-level default. Previously
        # the plan-level test_duration (e.g. bbb.yaml's 30s) never reached this
        # object, so every run silently fell back to 15s. The runner now passes
        # the plan value in; this keeps the per-run escape hatch.
        self.test_duration = run_config.get("test_duration", self.default_test_duration)

        self.pcaps_dir = self.run_dir / "pcaps"
        self.qlogs_dir = self.run_dir / "qlogs"
        self.logs_dir = self.run_dir / "logs"
        self.keys_dir = self.run_dir / "keys"
        self.output_dir = self.run_dir / "output"
        self.cert_dir = self.run_dir / "certs"
        # B39: shared coordinator file for chain topology (all relays point
        # at the same file so namespace registrations are visible to peers).
        self.coordinator_dir = self.run_dir / "coordinator"
        self.cert_file = self.cert_dir / "cert.pem"
        self.key_file = self.cert_dir / "key.pem"

        # B37 addendum 4 (MOQ_FAST_IO): the artifacts tree lives on the
        # host<->VM shared folder, and per-write sync there throttled BBB
        # runs progressively (31 -> 4.3 -> 2.2 -> 1.08 Mbps across identical
        # runs while the relay silently skipped up to 132/194 groups). When
        # MOQ_FAST_IO=1, the three HOT directories (subscriber output,
        # relay qlogs/mlogs, pcaps) are staged on VM-LOCAL disk for the
        # duration of the run and copied back into run_dir afterwards --
        # evaluation, exports and reports read the same final paths.
        self._stage_back: List[Tuple[Path, Path]] = []
        if os.environ.get("MOQ_FAST_IO") == "1":
            stage_root = Path(os.environ.get(
                "MOQ_STAGE_ROOT", "/tmp/moq-stage")) / sanitize_dirname(
                self.run_id)
            for attr in ("pcaps_dir", "qlogs_dir", "output_dir"):
                real = getattr(self, attr)
                staged = stage_root / attr
                self._stage_back.append((staged, real))
                setattr(self, attr, staged)
            # Loud by design: a silent miss (e.g. sudo dropping the env var)
            # previously made unstaged runs look like staged ones.
            self._log(f"FAST_IO staging active -> {stage_root}")

        self.hosts: Dict[str, Any] = {}
        self.processes: List[Any] = []
        self.result: Dict[str, Any] = {}
        self._stop_event = threading.Event()
        # SHA-exactness drain probe (Step 4): env overrides for teardown
        # timing so the class-level defaults (STOP_GRACE_S/STOP_DRAIN_S)
        # stay frozen for every other plan. MOQ_STOP_GRACE_S (default 3.0),
        # MOQ_STOP_DRAIN_S (default 12.0). Loud when active (FAST_IO rule:
        # a silent miss, e.g. sudo dropping env, must never look staged).
        self.stop_grace_s = _env_float("MOQ_STOP_GRACE_S", self.STOP_GRACE_S)
        self.stop_drain_s = _env_float("MOQ_STOP_DRAIN_S", self.STOP_DRAIN_S)
        self.teardown_order = _teardown_order()
        if (self.stop_grace_s != self.STOP_GRACE_S
                or self.stop_drain_s != self.STOP_DRAIN_S
                or self.teardown_order != "pub-first"):
            # Loud by design (see FAST_IO above): default timing must be
            # distinguishable from probe timing in every log.
            self._log(f"DRAIN-PROBE timing active: grace={self.stop_grace_s}s "
                      f"(default {self.STOP_GRACE_S}s), "
                      f"drain={self.stop_drain_s}s "
                      f"(default {self.STOP_DRAIN_S}s), "
                      f"order={self.teardown_order} (default pub-first)")
        # B13 (see found-bugs.md): completion detection. Set by
        # _wait_for_completion: completed=True when the received artifact
        # stopped growing before the test_duration cap; completion_reason says
        # how it ended; run_duration_s is the actual run length.
        self.completed = False
        self.completion_reason = ""
        self.run_duration_s = None

        # B8: dead-code instantiations removed (TopologyBuilder / ScenarioApplier).
        self.metrics_collector = MetricsCollector()
        self._topology = TOPOLOGIES.get(self.topology_type, TOPOLOGIES["basic"])()

    def setup_dirs(self):
        for d in [self.pcaps_dir, self.qlogs_dir, self.logs_dir,
                  self.keys_dir, self.output_dir, self.cert_dir,
                  getattr(self, "coordinator_dir", self.run_dir / "coordinator")]:
            d.mkdir(parents=True, exist_ok=True)
        # B39: ensure coordinator directory has cache subdirectories for relay
        # namespace/track storage (B39: relay fails with ENOENT on PUBLISH_NAMESPACE
        # when cache/namespace/tracks directories don't exist).
        coordinator_cache = getattr(self, "coordinator_dir", self.run_dir / "coordinator") / "cache"
        coordinator_cache.mkdir(parents=True, exist_ok=True)
        # Also create namespace-specific subdirectory that the relay expects
        (self.run_dir / "coordinator" / "cache" / "namespaces").mkdir(parents=True, exist_ok=True)
        # Also create tracks subdirectory for track caching
        (self.run_dir / "coordinator" / "cache" / "tracks").mkdir(parents=True, exist_ok=True)
        # Also create namespaces directory directly under coordinator (some relays expect this)
        (self.run_dir / "coordinator" / "namespaces").mkdir(parents=True, exist_ok=True)
        # Also create tracks directory directly under coordinator
        (self.run_dir / "coordinator" / "tracks").mkdir(parents=True, exist_ok=True)
        # B6 (see found-bugs.md): generate the base cert pair plus any
        # per-implementation aliases (e.g. moxygen's certificate.pem/.key,
        # imquic's priv.key) declared as cert_aliases in registry.json.
        ensure_cert_set(self.cert_dir, self._relay_cert_aliases())

    def _relay_cert_aliases(self) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for role in self._topology.roles(self.network):
            if role.startswith("relay"):
                impl_name = self.config.get(role, {}).get("impl")
                if impl_name:
                    aliases.update(self._get_impl_config(impl_name).get("cert_aliases", {}))
        return aliases

    def start_capture(self, host_name: str) -> str:
        # B3 (see found-bugs.md): previously the pcap path and the stderr log
        # path were HOST paths (not mounted into the container) and the device
        # was `{host}-eth0` (the HOST-side veth name). Inside the container the
        # interface is eth0, and /pcaps + /logs are bind-mounted by the
        # topology builders, so tcpdump now actually runs and its output lands
        # on the host.
        # B40 (see found-bugs.md): on this Containernet setup the in-host link
        # is named `{host}-eth0` (pub-eth0 / relay-eth0 / sub-eth0), NOT eth0:
        # `-i eth0` captured only default-bridge multicast noise and never any
        # QUIC, so every wire_* metric up to this fix was empty.
        log_path = f"/logs/tcpdump_{host_name}.log"
        return (f"tcpdump -i {host_name}-eth0 -U "
                f"-w /pcaps/{host_name}.pcap 2>{log_path} &")

    def _tcpdump_available(self, host) -> bool:
        # Some images (pulled third-party bases like moqdev/moq-*) can't be
        # rebuilt with tcpdump; probe and skip rather than fail the run.
        try:
            return bool(host.cmd("command -v tcpdump 2>/dev/null").strip())
        except Exception:
            return False

    def run(self) -> Dict[str, Any]:
        self.setup_dirs()
        # B29 (see found-bugs.md): write per-run metadata.json -- it was
        # defined but never called, so only batch-level summary carried config.
        self.save_metadata()
        result = {
            "run_id": self.run_id,
            "config": self.config,
            "network": self.network,
            "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "status": "unknown",
            "errors": [],
            "metrics": {},
        }
        try:
            self._execute_test()
            # B5 (see found-bugs.md): don't decide pass/fail here.
            # evaluate() is the single source of truth; the worker syncs
            # result["status"] from it afterwards.
        except Exception as e:
            result["status"] = "error"
            result["errors"].append(str(e))
            self._log(f"Test failed: {e}")
        finally:
            # MOQ_FAST_IO: bring VM-locally staged hot directories back into
            # run_dir BEFORE evaluate()/exports read them.
            self._copy_stage_back()
        result["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return result

    def _copy_stage_back(self) -> None:
        if not self._stage_back:
            return
        import shutil
        for staged, real in self._stage_back:
            try:
                real.mkdir(parents=True, exist_ok=True)
                if staged.exists():
                    shutil.copytree(staged, real, dirs_exist_ok=True)
                    self._log(f"Staged dir copied back: {real.name} "
                              f"({sum(1 for _ in staged.rglob('*'))} entries)")
            except Exception as exc:
                self._log(f"WARNING: stage-back failed for {staged}: {exc}")

    # B12 (see found-bugs.md): per-device impairments. Every wire's TCLink
    # params come from link_params_for_role(); a role NOT listed in
    # network.devices gets a clean link, so an impairment is never doubled by
    # landing on both the pub and sub wires.
    CLEAN_LINK: Dict[str, Any] = {"bw": 1000, "delay": "1ms", "loss": 0}

    def _top_level_impair(self) -> Dict[str, Any]:
        return {
            "bw": self.network.get("bw", 100),
            "delay": self.network.get("delay", "10ms"),
            "loss": self.network.get("loss", 0),
        }

    def _role_names(self) -> set:
        return set(self._topology.roles(self.network))

    def _default_impaired_roles(self) -> set:
        """Roles impaired when `network.devices` is absent: the subscriber
        wire(s) only -- the pub/relay wires stay clean (B12)."""
        return self._topology.default_impaired_roles(self.network)

    def link_params_for_role(self, role: str) -> Dict[str, Any]:
        """TCLink params for one role's wire.

        With `network.devices` (role -> {bw, delay, loss} override): listed
        roles get the top-level values merged with their override; unlisted
        roles get a clean link. Without it, only `_default_impaired_roles()`
        get the top-level values; everyone else is clean.
        """
        return self._topology.link_params_for_role(role, self.network)

    @staticmethod
    def _is_impaired(params: Dict[str, Any]) -> bool:
        return not (params.get("bw", 1000) == 1000
                    and params.get("delay", "1ms") == "1ms"
                    and params.get("loss", 0) == 0)

    def _impaired_host_names(self) -> set:
        """Host names whose links carry a real impairment, used to scope
        _verify_impairments so a clean relay/pub doesn't need a shaping qdisc."""
        impaired = {role for role in self._role_names()
                    if self._is_impaired(self.link_params_for_role(role))}
        # Chain topology: inter-relay link is on relay_a's s2 interface
        # If __inter_relay__ is impaired, we must verify it on relay_a
        if self.topology_type == "chain":
            inter_relay_params = self._topology.link_params_for_role("__inter_relay__", self.network)
            if self._is_impaired(inter_relay_params):
                impaired.add("relay_a")
        return impaired

    def _verify_impairments(self, net) -> None:
        """Fail loudly when Containernet could not apply link impairments.

        Containernet configures TCLink bw/delay/loss by running `tc` INSIDE
        each container (docker exec). If the image lacks iproute2, the qdisc
        install fails with ``bash: tc: command not found`` and the link runs
        UNCONSTRAINED -- silently, so a 1%-loss or 10 Mbps run would measure a
        clean channel.

        Probe with `tc` itself (Docker.cmd passes the command string as argv,
        so a shell builtin like `command -v` never resolves): pass only when a
        REAL shaping qdisc (htb/tbf/netem) is installed on some interface. A
        bare `tc qdisc show` prints ``qdisc noqueue ...`` even when nothing is
        shaped, so matching "qdisc" is NOT sufficient. Raise otherwise so the
        run cannot pass.
        """
        problems: List[str] = []
        impaired = self._impaired_host_names()
        for host in net.hosts:
            name = getattr(host, "name", str(host))
            qdiscs = host.cmd("tc qdisc show 2>&1 || true")
            # B12 evidence: persist every host's qdisc state so impairment
            # placement (sub wire shaped, pub/relay clean) is auditable from
            # the run artifacts, not just the console.
            # Phase 2 follow-up: `tc qdisc show` prints the qdisc KIND but not
            # the htb RATE (5M vs 10M invisible) — also persist `tc class
            # show` so configured rates are auditable per run.
            classes = host.cmd("tc class show 2>&1 || true")
            try:
                (self.logs_dir / f"tc_{name}.log").write_text(
                    qdiscs + "\n--- tc class show ---\n" + classes)
            except OSError:
                pass
            if name not in impaired:
                continue
            if not any(q in qdiscs for q in ("htb", "tbf", "netem")):
                if not qdiscs.strip() or "not found" in qdiscs:
                    problems.append(f"{name}: `tc` not found in container "
                                    "(iproute2 missing from the image)")
                else:
                    problems.append(f"{name}: no shaping qdisc (htb/tbf/netem) "
                                    "on any interface "
                                    "(TCLink bw/delay/loss was NOT applied)")
        if problems:
            raise RuntimeError("Impairment check failed:\n  " + "\n  ".join(problems))

    def _network_diag(self, net) -> None:
        """Log L2 evidence (OVS flows, ARP tables, per-link counters) so a
        connectivity failure is diagnosable from the run log instead of 60s of
        silent timeouts."""
        try:
            flows = subprocess.run(
                ["ovs-ofctl", "dump-flows", "s1"],
                capture_output=True, text=True, timeout=10,
            )
            out = (flows.stdout or flows.stderr or "").strip()
            self._log(f"[diag] OVS flows on s1 (rc={flows.returncode}):\n{out}")
        except Exception as e:
            self._log(f"[diag] ovs-ofctl failed: {e}")
        for host in net.hosts:
            name = getattr(host, "name", str(host))
            link = host.cmd(f"ip -s link show {name}-eth0 2>&1 || true")
            arp = host.cmd("cat /proc/net/arp 2>&1 || true")
            self._log(f"[diag] {name} link counters:\n{link.strip()}")
            self._log(f"[diag] {name} ARP table:\n{arp.strip()}")

    def _fix_ovs_switching(self, net) -> None:
        """Containernet creates OVS switches in fail_mode=secure with an EMPTY
        flow table and no controller, so the switch DROPS everything (seen as
        incomplete ARP: `10.0.0.2 -> 00:00:00:00:00:00` and 60s of client
        timeouts). Fall back to standalone L2 switching and install a catch-all
        NORMAL flow so the bridge behaves like a plain learning switch."""
        for sw in net.switches:
            name = getattr(sw, "name", str(sw))
            for cmd in (
                ["ovs-vsctl", "set-fail-mode", name, "standalone"],
                ["ovs-ofctl", "add-flow", name, "priority=0,actions=normal"],
            ):
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       timeout=10, check=False)
                    if r.returncode != 0:
                        self._log(f"[ovs] {' '.join(cmd)} rc={r.returncode}: "
                                  f"{(r.stderr or r.stdout).strip()}")
                except Exception as e:
                    self._log(f"[ovs] {' '.join(cmd)} failed: {e}")

    def _wait_for_pub_ready(self, timeout: float = 10.0, floor: float = 4.0,
                            segment_timeout: float = 10.0) -> None:
        """Wait until the *last* relay has registered the publisher's namespace,
        so the subscriber doesn't race ahead and die with `Track not found`
        (moq-rs sub exits; it does not retry).  Polls the last relay's log
        for moq-rs markers; relays that log something else
        (imquic/moxygen/moqtail/moq-dev) fall back to the `floor` delay
        instead of the full `timeout`, so runs don't stall 20s AND don't miss
        the pub window on tiny media (a moq-rs pub on sample.mp4 idle-times
        out ~12s after connecting).

        For chain topology the last relay is relay_b, which only sees the
        namespace marker after the upstream registration propagates through
        the shared coordinator file."""
        markers = ("registering namespace", "serving PUBLISH_NAMESPACE")
        # Collect all relay log files; pick the LAST one (by name sort).
        # basic/fanout: [relay.log]  chain: [relay_a.log, relay_b.log]
        relay_logs = sorted(self.logs_dir.glob("relay*.log"))
        if not relay_logs:
            relay_logs = [self.logs_dir / "relay.log"]
        last_relay_log = relay_logs[-1]
        start = time.time()
        no_marker_bail = start + floor
        deadline = start + timeout
        found = False
        while time.time() < deadline:
            try:
                text = last_relay_log.read_text(
                    encoding="utf-8", errors="replace")
                if any(m in text for m in markers):
                    found = True
                    break
            except FileNotFoundError:
                pass
            if time.time() >= no_marker_bail:
                break
            time.sleep(0.5)
        if found:
            self._log(f"Publisher registered on relay "
                      f"({last_relay_log.name} saw namespace marker)")
        else:
            self._log(f"WARNING: no publisher namespace marker in "
                      f"{last_relay_log.name} within {timeout:.0f}s "
                      f"(floor {floor:.0f}s)")

        # B37 addendum (run_20260825_235302 / _235753): the namespace marker
        # only proves ANNOUNCEMENT. On slow-publishing media (bbb) the sub
        # could still join before the first group was servable: moq-rs then
        # either answers "Track not found" (sub exits, no retry -> init-only
        # stall) or serves a late join starting at group N>0 (permuted,
        # incomplete captures). Gate on the PUBLISHER's own first-segment
        # evidence for pubs whose log announces object progress.
        pub_impl = self.config.get("pub", {}).get("impl", "")
        if pub_impl in self.PUB_SEGMENT_LOG_IMPLS:
            # B44: logs are pub_s0.log (num_streams x, one per stream), NOT
            # pub.log — a stale single-name read made the gate burn its full
            # 10s deadline on FileNotFound every run, so the sub joined AFTER
            # the (fast) publisher had finished and the relay only had the
            # first/last objects left to replay (moq-rs rows stuck at ~11 KB).
            pub_logs = sorted(self.logs_dir.glob("pub*.log"))
            if not pub_logs:
                pub_logs = [self.logs_dir / "pub.log"]
            gate_deadline = time.time() + segment_timeout
            while time.time() < gate_deadline:
                try:
                    if any(self._pub_saw_first_segment(
                            pl.read_text(encoding="utf-8",
                                         errors="replace"))
                           for pl in pub_logs):
                        self._log("Publisher pushed its first segment -- "
                                  "sub join is deterministic")
                        return
                except FileNotFoundError:
                    pass
                time.sleep(0.25)
            self._log(f"WARNING: no first-segment line from publisher within "
                      f"{segment_timeout:.0f}s -- launching subscriber anyway")

    @staticmethod
    def _pub_saw_first_segment(log_text: str) -> bool:
        """True when a moq-rs publisher log shows its first object push."""
        return bool(re.search(r"segment:\s*\d+", log_text))

    COORDINATOR_CONTAINER_PATH = "/moq-coordinator/coordinator.json"

    @staticmethod
    def _relay_chain_flags(is_first: bool,
                           inter_relay_ip: Optional[str],
                           port: int,
                           impl: str) -> str:
        """B39: extra flags for relay chaining via moq-rs's shared
        coordinator file (moq-relay-ietf --coordinator-file).

        Upstream relay (--node): advertises a REACHABLE address; the default
        derives from the [::]:4443 bind and registers as https://[::]:4443/,
        which no peer can dial.
        Downstream relay (--tls-disable-verify): its internal client dials
        the upstream's self-signed cert; the flag's own docs bless this for
        'between relays'.

        Non-moq-rs relays get nothing (no coordinator/client support here).
        --announce is deliberately NOT used: it forwards incoming
        PUBLISH_NAMESPACE to an auth server, it is not discovery."""
        if impl != "moq-rs":
            return ""
        flags = f" --coordinator-file {MoQTestRun.COORDINATOR_CONTAINER_PATH}"
        if is_first:
            if inter_relay_ip:
                flags += f" --node https://{inter_relay_ip}:{port}"
        else:
            flags += " --tls-disable-verify"
        return flags

    @staticmethod
    def _sub_join_failed(log_text: str) -> bool:
        """True when a subscriber log shows the permanent early-death
        signature (B38: 'Track not found' etc. -- the sub never retries)."""
        return any(sig in log_text for sig in MoQTestRun.SUB_DEATH_SIGS)

    def _supervise_sub_joins(self, specs) -> None:
        """Watch freshly launched subscribers for two join-race tells and
        relaunch (bounded):

        - sub-side death signature (_sub_join_failed: moq-rs dies
          permanently on 'Track not found'), and
        - relay-side 'Not found: track' -- the SILENT variant (B38):
          the sub survives but joins past the first served groups, which
          no sub-side signal ever reveals. The relay's own warning is the
          only tell.

        Relaunch rotates each dead sub's log to `<role>.attempt<N>.log`
        so the failure evidence survives."""
        relay_logs = sorted(self.logs_dir.glob("relay*.log")) or [
            self.logs_dir / "relay.log"]
        deadline = time.time() + 15.0
        restarts = 0
        while time.time() < deadline and restarts < self.MAX_SUB_RESTARTS:
            time.sleep(1.5)
            dead = []
            for role, host, cmd in specs:
                try:
                    text = (self.logs_dir / f"{role}.log").read_text(
                        encoding="utf-8", errors="replace")
                except FileNotFoundError:
                    continue
                reason = None
                if self._sub_join_failed(text):
                    reason = "subscriber died on join"
                else:
                    for rl in relay_logs:
                        try:
                            rtext = rl.read_text(
                                encoding="utf-8", errors="replace")
                        except FileNotFoundError:
                            continue
                        if "Not found: trac" in rtext:
                            reason = f"{rl.name} answered Not found"
                            break
                if reason:
                    dead.append((role, host, cmd, reason))
            if not dead:
                return
            restarts += 1
            names = ", ".join(f"{r} ({why})" for r, _, _, why in dead)
            self._log(f"Subscriber join race detected ({names}) -- "
                      f"relaunching (attempt {restarts}/"
                      f"{self.MAX_SUB_RESTARTS})")
            for role, host, _, _ in dead:
                host.cmd("pkill -INT -f 'moq-sub|imquic-moq-sub|"
                         "moqflvreceiver' 2>/dev/null || true")
            time.sleep(1.0)
            for role, host, cmd, _ in dead:
                host.cmd(f"mv /logs/{role}.log /logs/{role}.attempt"
                         f"{restarts}.log 2>/dev/null || true")
                host.cmd(cmd)
        # Final sweep: if a death appeared on the last allowed attempt,
        # leave it to evaluate() -- the artifact/content checks will fail
        # the run honestly.

    def _cleanup_stale_containers(self) -> None:
        """Remove leftover `mn.*` containers before a run. When a container
        fails to START (e.g. image without a shell), Containernet leaves it
        behind and net.stop() can't remove it — every subsequent run then dies
        with `409 Conflict: /mn.pub is already in use`."""
        try:
            r = subprocess.run(
                ["docker", "ps", "-aq", "--filter", "name=mn."],
                capture_output=True, text=True, timeout=15,
            )
            stale = r.stdout.split()
            if stale:
                subprocess.run(["docker", "rm", "-f", *stale],
                               capture_output=True, text=True, timeout=30)
                self._log(f"Removed stale containers: {' '.join(stale)}")
        except Exception as e:
            self._log(f"WARNING: stale-container cleanup failed: {e}")

    def _verify_image_tags(self) -> None:
        """Pre-flight check: ensure the Docker image IDs for pub/relay/sub
        match the tags declared in the run config. This prevents B36-style
        tag skew where Hub tags (0hardikpandey/*) point to stale images while
        local tags (moq-rs/*) are rebuilt. If a mismatch is found, fail fast
        with an actionable message instead of wasting a run on wire-incompatible
        binaries."""
        import subprocess
        mismatches = []
        for role in ("pub", "relay", "sub"):
            cfg = self.config.get(role) or self.config.get(f"{role}_a")
            if not cfg:
                continue
            tag = cfg.get("tag", "")
            if not tag or tag == "unknown":
                continue
            try:
                r = subprocess.run(
                    ["docker", "inspect", "--format", "{{.Id}}", tag],
                    capture_output=True, text=True, timeout=10, check=False
                )
                if r.returncode != 0:
                    mismatches.append(f"{role}: tag '{tag}' not found locally (docker inspect failed)")
                    continue
                img_id = r.stdout.strip()
                # Also check the local tag equivalent (e.g. moq-rs/client:18 vs 0hardikpandey/moq-rs-client:18)
                # Hub tag: 0hardikpandey/moq-rs-<role>:<draft> -> local: moq-rs/<role>:<draft>
                local_tag = tag
                if tag.startswith("0hardikpandey/moq-rs-"):
                    # Extract role and draft: 0hardikpandey/moq-rs-client:18 -> client:18
                    rest = tag[len("0hardikpandey/moq-rs-"):]  # "client:18" or "relay:18"
                    local_tag = f"moq-rs/{rest}"
                if local_tag != tag:
                    try:
                        r2 = subprocess.run(
                            ["docker", "inspect", "--format", "{{.Id}}", local_tag],
                            capture_output=True, text=True, timeout=10, check=False
                        )
                        if r2.returncode == 0:
                            local_id = r2.stdout.strip()
                            if img_id != local_id:
                                mismatches.append(
                                    f"{role}: tag '{tag}' (ID {img_id[:12]}) != local '{local_tag}' (ID {local_id[:12]}) -- "
                                    f"rebuild or re-tag to align (B36 tag skew)")
                    except Exception:
                        pass
            except Exception as e:
                self._log(f"WARNING: image tag check failed for {role} '{tag}': {e}")
        if mismatches:
            raise RuntimeError("Image tag skew detected (B36):\n  " + "\n  ".join(mismatches))

    def _drain_artifact(self, paths, logs_on_stdout, last, bytes_at_stop,
                        tag):
        """Shared post-kill drain loop for both teardown orders.

        Polls the artifact until it stops growing or stop_drain_s elapses.
        Returns the final byte count. Identical semantics for pub-first and
        relay-first; only the triggering kill (and hence the tag) differs.
        """
        drain_deadline = time.time() + self.stop_drain_s
        while time.time() < drain_deadline:
            time.sleep(1.0)
            cur = MoQTestRun._total_media_bytes(paths, logs_on_stdout)
            if cur == last:
                break
            last = cur
            self._log(f"{tag} drain: artifact at {last} B")
        recovered = last - bytes_at_stop
        if recovered > 0:
            self._log(f"Teardown recovered {recovered} byte(s) "
                      f"post-quiesce (final {last} B) [{tag}]")
        return last

    def _execute_test(self):
        self._cleanup_stale_containers()
        self._verify_image_tags()
        self._log("Starting Containernet topology...")
        net = self._create_network()
        try:
            net.start()
            # Containernet TCLink leaves the Docker host veth DOWN (seen as
            # "<name>-eth0 ... state DOWN" with no 10.0.0.0/8 route inside the
            # container), so the OVS path is unroutable and clients black-hole
            # via docker0 (default route). Bring each host's OVS link UP so the
            # kernel installs the 10.0.0.0/8 link route; the TC qdisc survives
            # and impairments stay honored.
            # B7-chain: for chain topology relay_a has TWO interfaces
            # (relay_a-eth0 on s1, relay_a-eth1 on s2).  Bring ALL
            # veth interfaces UP so inter-relay routing works.
            for host in net.hosts:
                # Prefer Mininet's authoritative interface list; fall back to
                # sysfs only if needed. Both sources are filtered strictly to
                # avoid spurious entries like "2004h"/"2004l" seen in
                # run_20260826_213624 where `grep eth` was too loose and an
                # ifindex leaked into `ip link set` ("Cannot find device").
                try:
                    candidates = list(host.intfNames())
                except Exception:
                    candidates = []
                raw = []
                if not candidates:
                    raw = host.cmd(
                        "ls -1 /sys/class/net 2>/dev/null || true"
                    ).split()
                else:
                    raw = candidates
                ifaces = []
                for name in raw:
                    name = name.strip()
                    if not name:
                        continue
                    if "eth" not in name:
                        continue
                    if not name[0].isalpha():
                        self._log(f"WARNING: skipping invalid interface name "
                                  f"'{name}' on {host.name} (looks like an ifindex)")
                        continue
                    ifaces.append(name)
                for iface in ifaces:
                    out = host.cmd(
                        f"ip link set {iface} up 2>&1 || true")
                    self._log(f"link up {host.name}-{iface}: "
                              f"{out.strip() or 'ok'}")
            # B7-chain: Mininet only configures eth0; extra interfaces
            # (relay_a-eth1 on s2) have NO IP, so relay-to-relay traffic
            # black-holes via docker0.  Assign an explicit IP to each
            # inter-relay interface and remember it for --node.
            # links() yields inter-relay wires with param_role
            # "__inter_relay__"; the relay's LAST eth iface is that wire
            # (links are added in order).
            self._inter_relay_ips = {}
            _ir_index = 0
            for node_a, _sw_b, param_role in self._topology.links():
                if param_role != "__inter_relay__":
                    continue
                host_a = self.hosts[node_a]
                # intfNames() returns FULL netns names ("relay_a-eth0"),
                # not bare "eth0" -- match by substring (B39 follow-up:
                # startswith('eth') never matched, so --node never got a
                # reachable IP and the coordinator advertised [::]:4443).
                eth_ifaces = [i for i in host_a.intfNames() if "eth" in i]
                if not eth_ifaces:
                    self._log(f"WARNING: {node_a} has no eth interface "
                              f"for the inter-relay address")
                    continue
                iface = eth_ifaces[-1]
                ir_ip = f"10.250.{_ir_index}.10"
                _ir_index += 1
                host_a.cmd(f"ip addr add {ir_ip}/24 dev {iface}"
                           f" 2>&1 || true")
                host_a.cmd(f"ip link set {iface} up 2>&1 || true")
                self._inter_relay_ips[node_a] = ir_ip
                self._log(f"inter-relay addr {node_a}:{iface} -> {ir_ip}")
            self._fix_ovs_switching(net)
            self._verify_impairments(net)

            pub_host = self.hosts["pub"]

            if self.capture:
                self._log("Starting tcpdump on all hosts (capture enabled)...")
                for host in net.hosts:
                    if not self._tcpdump_available(host):
                        self._log(f"WARNING: tcpdump not found in {host.name}; "
                                  f"skipping capture for it")
                        continue
                    host.cmd(self.start_capture(host.name))
                # B37: verify tcpdump is actually running and writing pcaps
                time.sleep(1.5)
                for host in net.hosts:
                    name = host.name
                    pcap_path = f"/pcaps/{name}.pcap"
                    if not self._tcpdump_available(host):
                        continue
                    # Check tcpdump process exists
                    ps = host.cmd(f"ps aux | grep -v grep | grep -c 'tcpdump.*{name}\\.pcap' 2>/dev/null || echo 0")
                    if ps.strip() == "0":
                        self._log(f"WARNING: tcpdump not running for {name} (process missing)")
                    # Check pcap file exists and has data (> header ~2.3KB)
                    ls = host.cmd(f"ls -la {pcap_path} 2>/dev/null || echo 'MISSING'")
                    self._log(f"pcap {name}: {ls.strip()}")
            else:
                self._log("Capture disabled (set 'capture: true' in the plan "
                          "to enable per-container tcpdump).")

            # Discover all relay roles in deterministic order.
            # basic/fanout: ["relay"]  chain: ["relay_a", "relay_b"]
            relay_roles = sorted(r for r in self.hosts if r.startswith("relay"))

# B39 follow-up: DOWNSTREAM relays need their own address on the
            # inter-relay subnet AND must dial with it as source. Otherwise
            # relay_b dials 10.250.0.10 from 10.0.0.x; relay_a's replies to
            # 10.0.0.x route out its PUB-facing leg (connected subnet on s1)
            # where relay_b does not exist -> asymmetric-routing blackhole
            # (observed: 'connecting to remote relay' -> connect timed out).
            for i, relay_role in enumerate(relay_roles):
                if i == 0 or relay_role in self._inter_relay_ips:
                    continue
                h = self.hosts[relay_role]
                ifaces = [x for x in h.intfNames() if "eth" in x]
                if not ifaces:
                    self._log(f"WARNING: {relay_role} has no eth interface "
                              f"for the inter-relay address")
                    continue
                ifc = ifaces[-1]
                ip_b = f"10.250.0.{10 + i}"
                # Explicit error checking - no silent failure!
                result = h.cmd(f"ip addr add {ip_b}/24 dev {ifc} 2>&1")
                if "Error" in result or "RTNETLINK" in result:
                    self._log(f"WARNING: failed to add IP {ip_b} to {ifc}: {result}")
                else:
                    self._log(f"inter-relay addr {relay_role}:{ifc} -> {ip_b}")
                h.cmd(f"ip link set {ifc} up 2>&1 || true")
                self._inter_relay_ips[relay_role] = ip_b

            first_relay_host = self.hosts[relay_roles[0]]
            last_relay_host = self.hosts[relay_roles[-1]]
            first_relay_ip = first_relay_host.IP()
            last_relay_ip = last_relay_host.IP()

            # Resolve the relay port from the first relay's implementation config.
            first_relay_cfg = (self.config.get(relay_roles[0])
                               or self.config.get("relay", {}))
            relay_port = str(self._get_impl_config(
                first_relay_cfg.get("impl", "")
            ).get("port", CONTAINER_RELAY_PORT))
            # For chain topology, the sub connects to the LAST relay,
            # which may have a different port (e.g. moxygen:9448 vs
            # moq-rs:4443).  Resolve last relay port separately.
            last_relay_cfg = (self.config.get(relay_roles[-1])
                              or self.config.get("relay", {}))
            last_relay_port = str(self._get_impl_config(
                last_relay_cfg.get("impl", "")
            ).get("port", CONTAINER_RELAY_PORT))

            # Relay-specific WebTransport path for moq-rs (https://) clients:
            # moxygen's relay only serves CONNECT at its configured endpoint
            # (/moq) — hitting the bare root returns HTTP 404 (see B43).
            first_relay_path = self._get_impl_config(
                first_relay_cfg.get("impl", "")
            ).get("client_path", "")
            last_relay_path = self._get_impl_config(
                last_relay_cfg.get("impl", "")
            ).get("client_path", "")

            # Smoke check: fail loudly if the pub cannot reach the first relay
            # on the OVS network, instead of 60s of silent timeouts.
            route = pub_host.cmd(f"ip route get {first_relay_ip} 2>&1 || true")
            if f"dev {pub_host.name}-eth0" in route:
                self._log(f"Smoke check OK: pub routes {first_relay_ip} "
                          f"via {pub_host.name}-eth0")
            else:
                self._log(f"WARNING: pub route to {first_relay_ip} is not via "
                          f"{pub_host.name}-eth0:")
                for line in route.strip().splitlines():
                    self._log(f"  {line}")

            stream_name = self.run_id
            media_path = f"/data/{self.media_file}"

            # Start relays in order.  B39: moq-rs relay-to-relay chaining
            # works via a SHARED COORDINATOR FILE (--coordinator-file, all
            # relays same path) -- the upstream relay registers namespaces
            # there under its advertised URL (--node), and the downstream
            # relay resolves misses through the coordinator and dials that
            # URL.  --announce is NOT chaining: it forwards incoming
            # PUBLISH_NAMESPACE messages to an auth/routing server.
            for i, relay_role in enumerate(relay_roles):
                r_cfg = (self.config.get(relay_role)
                         or self.config.get("relay", {}))
                r_impl = r_cfg.get("impl", "")
                r_port = str(self._get_impl_config(r_impl).get(
                    "port", CONTAINER_RELAY_PORT))
                r_host = self.hosts[relay_role]

                self._log(f"Starting {relay_role} ({r_impl})...")
                r_entry = self._get_entrypoint(r_impl, "relay")
                if r_entry:
                    # Note: imquic's RELAY is intentionally left unpinned (no
                    # -M): pinning it changes the advertised WebTransport
                    # protocol to a single draft, which makes imquic-moq-relay
                    # reject moq-rs clients with 'Unsupported WebTransport
                    # protocol(s)'. The SUB is pinned instead so imquic does
                    # not silently negotiate the highest draft (B4).
                    r_cmd = self._fill_entrypoint(r_entry, {
                        "port": r_port,
                    })
                    if i > 0 and r_impl == "moq-rs":
                        # Downstream relay must reach the upstream on the
                        # inter-relay link (s2), not the docker0 default --
                        # and must use its OWN inter-relay address as source
                        # so replies come back over s2 (symmetric path).
                        upstream_role = relay_roles[i - 1]
                        upstream_ip = getattr(
                            self, "_inter_relay_ips", {}).get(upstream_role)
                        if upstream_ip:
                            first_if = (r_host.intfNames()[0]
                                        if r_host.intfNames() else "eth0")
                            own_ip = getattr(
                                self, "_inter_relay_ips", {}).get(relay_role)
                            src = f" src {own_ip}" if own_ip else ""
                            r_host.cmd(
                                f"ip route replace {upstream_ip}/32"
                                f" dev {first_if}{src} 2>&1 || true")
                    chain_flags = ""
                    if self.topology_type == "chain":
                        chain_flags = self._relay_chain_flags(
                            is_first=(i == 0),
                            inter_relay_ip=(getattr(
                                self, "_inter_relay_ips", {}).get(relay_role)
                                if i == 0 else None),
                            port=r_port,
                            impl=r_impl)
                    if chain_flags:
                        r_cmd += chain_flags
                        if i == 0:
                            self._log(f"{relay_role} advertises "
                                      f"--node address for coordinator "
                                      f"discovery")
                    elif i > 0 and self.topology_type == "chain":
                        self._log(
                            f"NOTE: {r_impl} relay has no coordinator/"
                            f"client support in this harness; {relay_role} "
                            f"won't discover upstream tracks")
                    log_path = f"/logs/{relay_role}.log"
                    r_host.cmd(f"{r_cmd} > {log_path} 2>&1 &")
                time.sleep(2)

            self._log("Starting publisher...")
            pub_entry = self._get_entrypoint(self.config["pub"]["impl"], "pub")
            num_streams = self.config.get("streams", 1)
            if pub_entry:
                for s_idx in range(num_streams):
                    stream_name_s = f"{stream_name}_s{s_idx}" if num_streams > 1 else stream_name
                    pub_cmd = self._fill_entrypoint(pub_entry, {
                        "relay": first_relay_ip, "stream": stream_name_s,
                        "port": relay_port, "dir": "/output", "file": media_path,
                        "draft": self.config.get("pub", {}).get("draft") or "any",
                        "path": first_relay_path,
                    })
                    pub_host.cmd(f"{pub_cmd} < {media_path} > /logs/pub_s{s_idx}.log 2>&1 &")

            # B20 (see found-bugs.md): sub must join AFTER the pub announces,
            # or moq-rs sub dies instantly with `Track not found`.
            self._wait_for_pub_ready()

            # B7 fix: launch all subscriber roles (sub for basic/chain,
            # sub1..subN for fanout/chainfanout). Each role resolves its own
            # impl (mixed-impl fan-out via sub1..subN overrides, falling back
            # to "sub") and its own output redirect.
            sub_roles = [r for r in self.hosts if r.startswith("sub")]
            self._log(f"Starting {len(sub_roles)} subscriber(s)...")
            sub_specs = []
            for sub_role in sub_roles:
                role_cfg = self._sub_role_cfg(sub_role)
                role_entry = self._get_entrypoint(role_cfg.get("impl", ""), "sub")
                if not role_entry:
                    continue
                role_output_cfg = self._get_impl_config(role_cfg.get("impl", "")).get("sub_output", {})
                sub_host = self.hosts[sub_role]
                for s_idx in range(num_streams):
                    stream_name_s = f"{stream_name}_s{s_idx}" if num_streams > 1 else stream_name
                    sub_cmd = self._fill_entrypoint(role_entry, {
                        "relay": last_relay_ip, "stream": stream_name_s,
                        "port": last_relay_port, "dir": "/output", "file": media_path,
                        "draft": role_cfg.get("draft") or "any",
                        # Streaming baselines (lldash) skip aired segments
                        # for late joiners; early subs join at 0.
                        "join_delay": "0",
                        "path": last_relay_path,
                    })
                    sub_redirect = self._sub_launch_redirect(role_output_cfg, stream_name_s, media_path)
                    full = f"{sub_cmd} {sub_redirect} 2>/logs/{sub_role}_s{s_idx}.log &"
                    sub_host.cmd(full)
                    sub_specs.append((f"{sub_role}_s{s_idx}", sub_host, full))
            # B38: moq-rs subs die permanently on an early "Track not
            # found" (relay track state lags namespace registration).
            # Supervise the join: on a death signature, rotate the log,
            # relaunch, and give the relay another chance -- bounded.
            self._supervise_sub_joins(sub_specs)

            # I4 / D6: late-joiner subscribers - launch additional subs after a delay
            # B39a-d fix: read from both network and config, support late_joins[] staggered list
            # and single count+delay fallback. Records late_join_wallclock per late_sub for metrics.
            def _parse_delay(v) -> float:
                if v is None:
                    return 0.0
                if isinstance(v, (int, float)):
                    return float(v)
                s = str(v).strip().lower()
                if s.endswith("s"):
                    s = s[:-1]
                try:
                    return float(s)
                except ValueError:
                    return 0.0
            # Unified late-join spec: prefer explicit late_joins list, else count+delay
            late_joins_list = self.config.get("late_joins") or self.network.get("late_joins")
            late_join_delay = self.network.get("late_join_delay_s", self.config.get("late_join_delay_s", 0))
            late_sub_count = self.network.get("late_sub_count", self.config.get("late_sub_count", 0))
            # If late_joins list present, it defines the plan (staggered)
            if late_joins_list and isinstance(late_joins_list, list):
                # Normalize entries like {sub: late_sub1, delay: 5s} or {sub: sub3, delay: 5s}
                self._late_join_times = getattr(self, "_late_join_times", {})
                late_sub_specs = []
                # Sort by delay to launch in staggered order; sleep incrementally
                # so entry delays are absolute join offsets (not cumulative).
                lj_start = time.time()
                def _lj_delay(e):
                    return _parse_delay(e.get("delay", 0) if isinstance(e, dict) else 0)
                for entry in sorted(late_joins_list, key=_lj_delay):
                    if not isinstance(entry, dict):
                        continue
                    # entry may use "sub": "sub3" or "late_sub1" — map generic subX to late_subY if needed
                    raw_role = entry.get("sub") or entry.get("role") or ""
                    delay = _parse_delay(entry.get("delay", late_join_delay))
                    # Map any sub* naming to actual late_sub* hosts if late_sub* exists
                    late_role = raw_role if raw_role in self.hosts else None
                    if late_role is None:
                        # Fallback: treat as late_sub sequential
                        # e.g. sub3 in fanout with num_subscribers=3 late_sub_count=1 -> late_sub1
                        # Find next unused late_sub host
                        for cand in [f"late_sub{i}" for i in range(1, 10)]:
                            if cand in self.hosts and cand not in [r for r, _, _ in late_sub_specs]:
                                # use if not already scheduled with different delay grouping
                                late_role = cand
                                break
                        if late_role is None:
                            raw_role2 = raw_role
                            if raw_role2 not in self.hosts:
                                self._log(f"WARNING: late_joins entry sub={raw_role2} not in topology, skipping")
                                continue
                            late_role = raw_role2
                    wait = delay - (time.time() - lj_start)
                    if wait > 0:
                        self._log(f"Waiting {wait:.1f}s before launching late-joiner {late_role} (join at +{delay:.1f}s)...")
                        time.sleep(wait)
                    late_host = self.hosts[late_role]
                    # Record wallclock for metrics (B39d)
                    join_ts = time.time()
                    self._late_join_times[late_role] = join_ts
                    late_cfg = self._sub_role_cfg(late_role)
                    late_entry = self._get_entrypoint(late_cfg.get("impl", ""), "sub")
                    late_output_cfg = self._get_impl_config(late_cfg.get("impl", "")).get("sub_output", {})
                    for s_idx in range(num_streams):
                        stream_name_s = f"{stream_name}_s{s_idx}" if num_streams > 1 else stream_name
                        late_cmd = self._fill_entrypoint(late_entry, {
                            "relay": last_relay_ip, "stream": stream_name_s,
                            "port": last_relay_port, "dir": "/output", "file": media_path,
                            "draft": late_cfg.get("draft") or "any",
                            # Streaming baselines skip segments aired before join.
                            "join_delay": f"{delay:.1f}",
                            "path": last_relay_path,
                        })
                        late_redirect = self._sub_launch_redirect(late_output_cfg, stream_name_s, media_path)
                        full = f"{late_cmd} {late_redirect} 2>/logs/{late_role}_s{s_idx}.log &"
                        late_host.cmd(full)
                        late_sub_specs.append((f"{late_role}_s{s_idx}", late_host, full))
                if late_sub_specs:
                    self._supervise_sub_joins(late_sub_specs)
            elif _parse_delay(late_join_delay) > 0 and int(late_sub_count or 0) > 0:
                delay = _parse_delay(late_join_delay)
                count = int(late_sub_count)
                self._log(f"Waiting {delay:.1f}s before launching {count} late-joiner subscriber(s)...")
                time.sleep(delay)
                self._late_join_times = getattr(self, "_late_join_times", {})
                late_sub_specs = []
                for i in range(1, count + 1):
                    late_role = f"late_sub{i}"
                    if late_role not in self.hosts:
                        self._log(f"WARNING: {late_role} not in topology, skipping")
                        continue
                    late_host = self.hosts[late_role]
                    self._late_join_times[late_role] = time.time()
                    late_cfg = self._sub_role_cfg(late_role)
                    late_entry = self._get_entrypoint(late_cfg.get("impl", ""), "sub")
                    late_output_cfg = self._get_impl_config(late_cfg.get("impl", "")).get("sub_output", {})
                    for s_idx in range(num_streams):
                        stream_name_s = f"{stream_name}_s{s_idx}" if num_streams > 1 else stream_name
                        late_cmd = self._fill_entrypoint(late_entry, {
                            "relay": last_relay_ip, "stream": stream_name_s,
                            "port": last_relay_port, "dir": "/output", "file": media_path,
                            "draft": late_cfg.get("draft") or "any",
                            # Streaming baselines skip segments aired before join.
                            "join_delay": f"{delay:.1f}",
                            "path": last_relay_path,
                        })
                        late_redirect = self._sub_launch_redirect(late_output_cfg, stream_name_s, media_path)
                        full = f"{late_cmd} {late_redirect} 2>/logs/{late_role}_s{s_idx}.log &"
                        late_host.cmd(full)
                        late_sub_specs.append((f"{late_role}_s{s_idx}", late_host, full))
                if late_sub_specs:
                    self._supervise_sub_joins(late_sub_specs)
            time.sleep(3)
            self._network_diag(net)

            self._log(f"Running for up to {self.test_duration}s "
                      f"(stops early when delivery quiesces)...")
            # B13 (see found-bugs.md): fixed sleep + unconditional kill chopped
            # long videos. Now we wait for the received artifact to stop
            # growing (publisher finished AND relay drained), with
            # test_duration as a hard cap. _wait_for_completion records
            # completed / completion_reason / run_duration_s.
            self._wait_for_completion()

            self._log("Stopping all processes...")
            self._network_diag(net)
            # B26 tail-loss experiment: subscribers get SIGINT first (tokio's
            # ctrl-c path exits cleanly and FLUSHES stdout) with a short grace
            # window, while the artifact-byte delta across that window is
            # logged as evidence. A plain pkill/SIGTERM gives a Rust process
            # no chance to flush its line-buffered stdout, which is the
            # leading suspect for the deterministic 32-byte tail loss.
            # B32: use media_bytes (strip ANSI) for consistent measurement
            paths = self._completion_artifact_paths()
            sub_impl = self.config.get("sub", {}).get("impl", "")
            sub_output = self._get_impl_config(sub_impl).get("sub_output", {})
            logs_on_stdout = sub_output.get("logs_on_stdout") == "ansi_timestamp"
            bytes_at_stop = MoQTestRun._total_media_bytes(paths, logs_on_stdout)
            sub_pats = "moq-sub|imquic-moq-sub|moqflvreceiver"
            for host in net.hosts:
                if str(getattr(host, "name", "")).startswith("sub"):
                    host.cmd(f"pkill -INT -f '{sub_pats}' 2>/dev/null || true")
            time.sleep(self.stop_grace_s)
            bytes_after_grace = MoQTestRun._total_media_bytes(paths, logs_on_stdout)
            delta = bytes_after_grace - bytes_at_stop
            if delta > 0:
                self._log(f"Graceful sub stop flushed {delta} extra byte(s) "
                          f"({bytes_at_stop} -> {bytes_after_grace}) -- tail "
                          f"loss was kill-timing, not upstream")
            else:
                self._log(f"No artifact growth across graceful-stop grace "
                          f"window ({bytes_after_grace} B) -- tail loss is "
                          f"inherent to this pin's capture path")
            # B37: stop the PUBLISHER next and give the relay+sub a drain
            # window -- stream end should make the subscriber exit normally
            # (full stdout flush) instead of being murdered mid-buffer.
            # MOQ_TEARDOWN_ORDER=relay-first probe: kill the RELAY instead,
            # so the subscriber sees connection-close/stream-end and --
            # hypothesis -- exits cleanly with full flush. The drain loop is
            # shared; only which process dies first changes.
            if self.teardown_order == "relay-first":
                for host in net.hosts:
                    if str(getattr(host, "name", "")).startswith("relay"):
                        host.cmd("pkill -f 'moq-relay|moqrelay|imquic-moq-relay'"
                                 " 2>/dev/null || true")
                self._log("relay-first teardown: relay stopped, waiting "
                          "for clean sub exit + flush ...")
                last = self._drain_artifact(paths, logs_on_stdout,
                                            bytes_after_grace, bytes_at_stop,
                                            "relay-close")
                pub_host = self.hosts.get("pub")
                if pub_host is not None:
                    pub_host.cmd("pkill -f 'moq-pub|imquic-moq-pub|"
                                 "moqflvstreamer' 2>/dev/null || true")
            else:
                pub_host = self.hosts.get("pub")
                if pub_host is not None:
                    pub_host.cmd("pkill -f 'moq-pub|imquic-moq-pub|"
                                 "moqflvstreamer' 2>/dev/null || true")
                    last = self._drain_artifact(paths, logs_on_stdout,
                                                bytes_after_grace,
                                                bytes_at_stop, "post-pub")
            for host in net.hosts:
                host.cmd("pkill -f tcpdump 2>/dev/null || true")
                host.cmd("pkill -f moq-relay 2>/dev/null || true")
                host.cmd("pkill -f moq-pub 2>/dev/null || true")
                host.cmd("pkill -f moq-sub 2>/dev/null || true")
                host.cmd("pkill -f moqrelay 2>/dev/null || true")
                host.cmd("pkill -f moqflv 2>/dev/null || true")
                host.cmd("pkill -f moq_interop 2>/dev/null || true")
                host.cmd("pkill -f imquic 2>/dev/null || true")
            time.sleep(1)
        finally:
            self._log("Stopping network...")
            net.stop()

    def _get_impl_config(self, impl_name: str) -> dict:
        if not hasattr(self, '_registry'):
            with open(REGISTRY_PATH) as f:
                self._registry = json.load(f)
        for impl in self._registry["implementations"]:
            if impl["name"] == impl_name:
                return impl
        return {}

    def _get_entrypoint(self, impl_name: str, role: str) -> str:
        return self._get_impl_config(impl_name).get("entrypoints", {}).get(role, "")

    def _sub_role_cfg(self, role: str) -> dict:
        """Run-config for one subscriber role, with fallback to "sub".

        Mixed-impl fan-out (fanout/chainfanout) lets a plan override single
        subscribers (sub1..subN keys); roles without an override — including
        late_sub* — share the default "sub" config.
        """
        cfg = self.config.get(self._topology.config_key(role), {}) or {}
        if not cfg.get("impl") and (role.startswith("sub") or role.startswith("late_sub")):
            cfg = self.config.get("sub", {}) or {}
        return cfg

    def _fill_entrypoint(self, template: str, values: dict) -> str:
        for key, val in values.items():
            template = template.replace("{" + key + "}", str(val))
        return template

    def _create_network(self):
        try:
            from containernet.net import Containernet
            from containernet.node import Docker
            from mininet.link import TCLink
            from mininet.topo import Topo
        except ImportError:
            from mininet.net import Containernet
            from mininet.node import Docker
            from mininet.link import TCLink
            from mininet.topo import Topo

        net = Containernet(link=TCLink)
        topo = self._topology
        network = self.network
        relay_port = self._get_impl_config(
            self.config.get("relay", self.config.get("relay_a", {})).get("impl", "")
        ).get("port", CONTAINER_RELAY_PORT)

        # Create containers for every role
        for role in topo.roles(network):
            cfg_key = topo.config_key(role)
            impl_cfg = self.config.get(cfg_key, {}) or {}
            if not impl_cfg.get("impl") and (role.startswith("sub") or role.startswith("late_sub")):
                impl_cfg = self.config.get("sub", {}) or {}
            tag = impl_cfg.get("tag", "unknown")
            is_relay = role.startswith("relay")
            is_sub = role.startswith("sub") or role.startswith("late_sub")
            is_pub = role == "pub"

            volumes = [
                f"{self.keys_dir}:/keys",
                f"{self.logs_dir}:/logs",
                f"{self.pcaps_dir}:/pcaps",
            ]
            environment = {"MOQ_ROLE": "relay" if is_relay else ("pub" if is_pub else "sub"),
                           "RUST_LOG": "info",
                           "SSLKEYLOGFILE": "/keys/sslkeys.log"}
            port_bindings = {}

            if is_pub:
                volumes.insert(0, f"{to_vm_path(TESTDATA_DIR)}:/data")
                volumes.append(f"{to_vm_path(self.qlogs_dir)}:/qlogs")
            elif is_relay:
                volumes.insert(0, f"{to_vm_path(self.cert_dir)}:/certs")
                volumes.append(f"{to_vm_path(self.qlogs_dir)}:/qlogs")
                # D8: LL-DASH origin serves testdata/sample_120s.mpd + segments directly
                if str(impl_cfg.get("impl", "")).startswith("lldash"):
                    volumes.insert(0, f"{to_vm_path(TESTDATA_DIR)}:/data")
                    # Also mount html root for nginx/caddy fallback
                    volumes.append(f"{to_vm_path(TESTDATA_DIR)}:/usr/share/nginx/html:ro")
                    volumes.append(f"{to_vm_path(TESTDATA_DIR)}:/usr/share/caddy:ro")
                # B39: chain/chainfanout topologies share ONE coordinator file between
                # all relay containers so namespace registrations propagate.
                if self.topology_type in ("chain", "chainfanout"):
                    self.coordinator_dir.mkdir(parents=True, exist_ok=True)
                    volumes.append(
                        f"{to_vm_path(self.coordinator_dir)}:/moq-coordinator")
                port = topo.relay_port_binding(role, relay_port)
                port_bindings[port] = port
            else:
                # sub roles: per-sub output dir for fanout, shared for basic/chain
                if is_sub and role != "sub":
                    sub_out = self.output_dir / role
                    sub_out.mkdir(parents=True, exist_ok=True)
                    volumes.insert(0, f"{to_vm_path(sub_out)}:/output")
                else:
                    volumes.insert(0, f"{to_vm_path(self.output_dir)}:/output")
                # qlog collection for subscribers (imquic -Q /qlogs, moq-rs)
                volumes.append(f"{to_vm_path(self.qlogs_dir)}:/qlogs")
                # D8: LL-DASH client needs /data for local MPD fallback + certs for https verify=False but still mount
                if str(impl_cfg.get("impl", "")).startswith("lldash"):
                    volumes.insert(0, f"{to_vm_path(TESTDATA_DIR)}:/data:ro")
                    volumes.insert(0, f"{to_vm_path(self.cert_dir)}:/certs:ro")

            host = net.addDocker(
                role,
                dimage=tag,
                entrypoint=["/bin/sh", "-c", "sleep infinity"],
                volumes=volumes,
                environment=environment,
                port_bindings=port_bindings,
            )
            self.hosts[role] = host

        # Create switches
        switches = {}
        for sid in topo.switch_ids():
            switches[sid] = net.addSwitch(sid)

        # Create links from topology descriptor
        for node_a, node_b, param_role in topo.links():
            host_a = self.hosts[node_a]
            switch_b = switches[node_b]
            params = dict(topo.link_params_for_role(param_role, network))
            if param_role in topo.client_roles():
                params["max_queue_size"] = network.get("max_queue_size", 1000)
            net.addLink(host_a, switch_b, **params)

        # Fanout: additional sub links
        if hasattr(topo, "fanout_sub_links"):
            for node_a, node_b, param_role in topo.fanout_sub_links(network):
                host_a = self.hosts[node_a]
                switch_b = switches[node_b]
                params = dict(topo.link_params_for_role(param_role, network))
                params["max_queue_size"] = network.get("max_queue_size", 1000)
                net.addLink(host_a, switch_b, **params)

        # D6/chain: extra_links for late_sub* (late-join tests) — any topology can expose extra_links(network)
        if hasattr(topo, "extra_links"):
            for node_a, node_b, param_role in topo.extra_links(network):
                if node_a not in self.hosts:
                    continue
                host_a = self.hosts[node_a]
                switch_b = switches[node_b]
                params = dict(topo.link_params_for_role(param_role, network))
                params["max_queue_size"] = network.get("max_queue_size", 1000)
                net.addLink(host_a, switch_b, **params)

        return net

    def _inter_relay_link_params(self) -> Dict[str, Any]:
        """Params for the chain's inter-relay wire (ra->s2), the measurement
        link: it carries relay_delay on an otherwise clean link UNLESS relay_a
        is explicitly listed in network.devices (then its merged params apply).
        """
        return self._topology.link_params_for_role("__inter_relay__", self.network)

    def _log(self, msg: str):
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [{self.run_id[:40]}] {msg}", flush=True)

    def save_metadata(self):
        meta = {
            "run_id": self.run_id,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "config": self.config,
            "network": self.network,
            # Provenance for teardown-timing probes: without this, a later
            # reader cannot tell default timing from an env override (the
            # loud DRAIN-PROBE log line lives only on the runner console,
            # which is not archived per-run).
            "teardown": {
                "stop_grace_s": getattr(self, "stop_grace_s",
                                        self.STOP_GRACE_S),
                "stop_grace_default_s": self.STOP_GRACE_S,
                "stop_drain_s": getattr(self, "stop_drain_s",
                                        self.STOP_DRAIN_S),
                "stop_drain_default_s": self.STOP_DRAIN_S,
                "order": getattr(self, "teardown_order", "pub-first"),
            },
        }
        with open(self.run_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

    def _sub_launch_redirect(self, sub_output_cfg: dict, stream_name: str, media_path: str) -> str:
        """Return the stdout-redirect fragment for launching the subscriber.

        B18 (see found-bugs.md): where sub stdout goes depends on the impl's
        sub_output contract. If stdout_is_data, stdout IS the received artifact
        and is redirected to the artifact path; otherwise it is just logging and
        goes to /logs/sub.stdout.log so delivered_bytes never counts logs as
        media. Extracted here so it can be tested without Docker.
        """
        if sub_output_cfg.get("stdout_is_data", True):
            artifact = self._fill_entrypoint(
                sub_output_cfg.get("file", f"/output/{stream_name}"),
                {"stream": stream_name, "dir": "/output", "file": media_path},
            )
            return f"> {artifact}"
        return "> /logs/sub.stdout.log"

    def _artifact_rel(self, sub_output_cfg: dict) -> Optional[str]:
        """Relative path (inside output_dir) of the subscriber's received artifact.

        B18 (see found-bugs.md): derived from the registry's sub_output.file
        contract, which declares where each impl's subscriber puts its received
        bytes (e.g. moxygen -> ``{stream}.flv``, moq-rs/imquic -> ``{stream}``).
        Returns None when the impl has no contract, in which case the caller
        falls back to counting every file in /output (pre-B18 behavior).
        """
        template = sub_output_cfg.get("file")
        if not template:
            return None
        filled = self._fill_entrypoint(
            template,
            {"stream": self.run_id, "dir": "/output", "file": self.media_file},
        )
        rel = filled.replace("/output/", "", 1) if filled.startswith("/output/") else filled
        return rel.strip("/")

    def _completion_artifact_paths(self) -> List[Path]:
        """Host paths to watch for completion (B13).

        Mirrors evaluate()'s artifact scoping: each subscriber role's
        registry sub_output.file contract (mixed-impl fan-out resolves
        per role, falling back to "sub"). Fanout/chainfanout watches each
        sub{i} artifact; without a contract it falls back to every file
        under the output dir (pre-B18 behavior).
        """
        paths: List[Path] = []
        if self.topology_type in ("fanout", "chainfanout"):
            n_subs = self.network.get("num_subscribers", 4)
            for i in range(1, n_subs + 1):
                role = f"sub{i}"
                role_cfg = self._sub_role_cfg(role)
                sub_output = self._get_impl_config(role_cfg.get("impl", "")).get("sub_output", {})
                rel = self._artifact_rel(sub_output)
                if rel:
                    paths.append(self.output_dir / role / rel)
                else:
                    paths.extend(p for p in (self.output_dir / role).rglob("*") if p.is_file())
            return paths
        sub_output = self._get_impl_config(self.config["sub"]["impl"]).get("sub_output", {})
        rel = self._artifact_rel(sub_output)
        if rel:
            return [self.output_dir / rel]
        if self.output_dir.exists():
            return [p for p in self.output_dir.rglob("*") if p.is_file()]
        return []

    @staticmethod
    def _total_artifact_bytes(paths: List[Path]) -> int:
        return sum(p.stat().st_size for p in paths if p.exists())

    @staticmethod
    def _strip_flag(logs_on_stdout, path: Optional[Path] = None) -> bool:
        """Resolve the ANSI-strip flag for one artifact path.

        Accepts the legacy bool (applies to every path) or a mapping of
        str(path) -> bool for mixed-impl runs where only some subscribers
        (moq-rs) interleave logs with media on stdout.
        """
        if isinstance(logs_on_stdout, dict):
            return bool(logs_on_stdout.get(str(path), False))
        return bool(logs_on_stdout)

    @staticmethod
    def _total_media_bytes(paths: List[Path], logs_on_stdout=False) -> int:
        """Sum media bytes across artifact files, stripping ANSI log lines if needed."""
        return sum(len(media_bytes(p.read_bytes(), MoQTestRun._strip_flag(logs_on_stdout, p)))
                   for p in paths if p.exists())

    @staticmethod
    def _poll_artifact_completion(paths: List[Path], duration: float,
                                  logs_on_stdout=False,
                                  poll_interval: float = 1.0,
                                  quiet_polls: int = 3,
                                  min_bytes: Optional[int] = None) -> Tuple[bool, str, int]:
        """Poll a list of artifact paths until they stop growing or the time
        limit expires. Returns (completed, reason, final_bytes).

        completed=True means the byte count held steady for `quiet_polls`
        consecutive polls -- the publisher finished AND the relay drained, so
        the whole deliverable is on disk. Zero-byte files are ignored (a sub
        that never connects must not quiesce into a "completed" run).

        min_bytes (B13 v2 / B24): when set, no-growth only counts toward
        completion once the received bytes have reached it. A pause below the
        threshold is a mid-transfer stall (stdout buffering, slow-start, flow
        control -- see run_20260818_145813's bbb rows quiescing at 67.8% and
        0.003%), not a finished delivery, so it resets the quiet counter and
        the run continues to the cap.

        When logs_on_stdout is True (e.g. moq-rs subscriber), ANSI-timestamp
        log lines are stripped from the artifact before measuring bytes, so the
        completion gate uses actual media bytes instead of raw artifact bytes
        (B32 fix: raw bytes include ANSI logs and can quiesce early). A
        per-path mapping is accepted for mixed-impl runs (only moq-rs
        artifacts are stripped; e.g. moxygen FLV binaries must not be).
        """
        end = time.time() + duration
        last = sum(media_bytes(p.read_bytes(), MoQTestRun._strip_flag(logs_on_stdout, p)).__len__()
                   for p in paths if p.exists())
        quiet = 0
        while time.time() < end:
            time.sleep(poll_interval)
            cur = sum(media_bytes(p.read_bytes(), MoQTestRun._strip_flag(logs_on_stdout, p)).__len__()
                      for p in paths if p.exists())
            if cur == 0:
                quiet = 0
                continue
            if cur == last:
                if min_bytes is None or cur >= min_bytes:
                    quiet += 1
                else:
                    quiet = 0
            else:
                last = cur
                quiet = 0
            if quiet >= quiet_polls:
                return True, "delivery quiesced", cur
        return False, "time limit reached", sum(media_bytes(p.read_bytes(), MoQTestRun._strip_flag(logs_on_stdout, p)).__len__()
                                                for p in paths if p.exists())

    def _wait_for_completion(self) -> None:
        """Block until delivery quiesces (B13/I3) or the test_duration cap hits.

        Sets self.completed / self.completion_reason / self.run_duration_s.
        When the impl has no artifact contract we cannot detect completion, so
        we fall back to the fixed sleep (old B13 behavior) and mark it.
        """
        paths = self._completion_artifact_paths()
        if not paths:
            self._log("No artifact contract; cannot detect completion, "
                      "falling back to fixed time limit")
            time.sleep(self.test_duration)
            self.completed = False
            self.completion_reason = "no artifact contract to detect completion"
            self.run_duration_s = float(self.test_duration)
            return
        # B32: determine per-artifact ANSI stripping (moq-rs logs to stdout).
        # Mixed-impl runs resolve per subscriber role, falling back to "sub".
        if self.topology_type in ("fanout", "chainfanout"):
            strip_map = {}
            watched = self._completion_artifact_paths()
            for i in range(1, self.network.get("num_subscribers", 4) + 1):
                role = f"sub{i}"
                role_cfg = self._sub_role_cfg(role)
                role_out = self._get_impl_config(role_cfg.get("impl", "")).get("sub_output", {})
                flag = role_out.get("logs_on_stdout") == "ansi_timestamp"
                for p in watched:
                    if role in p.parts:
                        strip_map[str(p)] = flag
            logs_on_stdout = strip_map
        else:
            sub_impl = self.config.get("sub", {}).get("impl", "")
            sub_output = self._get_impl_config(sub_impl).get("sub_output", {})
            logs_on_stdout = sub_output.get("logs_on_stdout") == "ansi_timestamp"
        quiet_period = int(self.network.get("quiet_period", 3))
        # B13 v2 / B24: only treat no-growth as completion once the received
        # bytes reach completion_coverage of the source file. Until then a
        # pause is a mid-transfer stall and the run continues to the cap. With
        # no local source to compare against we keep the old behavior (None).
        completion_coverage = float(self.network.get("completion_coverage", 0.95))
        min_bytes = None
        original_path = TESTDATA_DIR / self.media_file
        if original_path.exists():
            min_bytes = int(original_path.stat().st_size * completion_coverage)
        start = time.time()
        completed, reason, final_bytes = self._poll_artifact_completion(
            paths, self.test_duration, logs_on_stdout=logs_on_stdout,
            quiet_polls=quiet_period, min_bytes=min_bytes)
        self.run_duration_s = round(time.time() - start, 2)
        self.completed = completed
        self.completion_reason = reason
        self._log(f"Run ended after {self.run_duration_s}s "
                  f"({reason}, {final_bytes} bytes across {len(paths)} "
                  f"artifact(s), completed={completed})")

    # B2 (see found-bugs.md): pass/fail must mean REAL delivery, not
    # "a log file exists". These signatures catch the ways a process can
    # "leave an artifact" without delivering media:
    #   - CLI usage/help dumped to stdout (imquic positional-args bug),
    #   - QUIC timeouts / invalid-address fatals (moq-rs pub/sub),
    #   - a captured startup log line passed off as received data.
    # Note: "Bye!" is deliberately NOT here — imquic's relay prints it as its
    # normal shutdown banner, so it must not fail the relay check.
    _FAILURE_TEXT = (
        "Usage:",
        "Help Options",
        "Application Options",
        "Error: timed out",
        "[FATAL]",
        "Invalid QUIC server address",
    )
    # Log-line signatures that mean the artifact is a captured log, not
    # received data: an ANSI-escaped tracing line, a " INFO " record
    # (moq-rs tracing), or an imquic object-metadata line. imquic prints an
    # "Incoming object: ..." metadata line PER received object (moq-sub.c
    # imquic_demo_incoming_object), so with -t none the artifact is metadata
    # only. With -t hex the payload is interleaved (%02x text) and media
    # magic wins over these (see _artifact_has_content).
    #
    # B21 (see found-bugs.md): imquic's CLI ALSO logs to stdout (g_print) --
    # a version banner ("imquic version"), connection diagnostics ("[moq-sub",
    # "Using a SUBSCRIBE"), and the normal shutdown banner ("Bye!"). When the
    # sub receives ZERO objects this stdout is the whole artifact, and with no
    # ANSI/" INFO "/"Incoming object:" lines it slipped past the fallback
    # `bool(data.strip())` and passed (false pass on run_20260818_141038's
    # imquic-relay-sub). These signatures reject imquic's own stdout as
    # content. "Bye!" is safe here because _LOG_TEXT only guards the ARTIFACT
    # check; the relay log uses _log_ok / _FAILURE_TEXT and is unaffected.
    _LOG_TEXT = ("\x1b[", " INFO ", "Incoming object:",
                 "imquic version", "[moq-sub", "Using a SUBSCRIBE", "Bye!")

    @staticmethod
    def _clean_cmd(output: str) -> str:
        """Strip ANSI escape sequences from Containernet host.cmd() output.

        Containernet wraps host.cmd() in a pseudo-TTY that emits
        bracket-paste sequences ([?2004l / [?2004h).  The ESC byte
        (\x1b) is often stripped by the TTY layer, leaving the bare
        CSI payload ([?2004h etc.).  Match both forms.
        """
        # Full ESC-prefixed CSI: \x1b[?2004l, \x1b[0m, etc.
        output = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', output)
        # Bare CSI after TTY strips the ESC byte: [?2004l etc.
        output = re.sub(r'\[[?][0-9;]*[a-zA-Z]', '', output)
        # Stray ESC bytes left over from partial stripping
        output = output.replace('\x1b', '')
        return output

    def _log_ok(self, log_path: Path) -> bool:
        """True when the log exists, is non-empty, and shows no failure."""
        if not log_path.exists() or log_path.stat().st_size == 0:
            return False
        try:
            text = log_path.read_text(errors="ignore")
        except OSError:
            return False
        return not any(m in text for m in self._FAILURE_TEXT)

    # imquic relay logs one negotiation line per connection, e.g.:
    #   [moq-relay/2]   -- WebTransport (moqt-18)
    #   [moq-relay/2]   -- draft-ietf-moq-transport-18
    _NEGOTIATED_MOQT_RE = re.compile(r"-- WebTransport \(moqt-(\d+)\)")
    # imquic's sub prints one "Incoming object:" metadata line per received
    # object (moq-sub.c imquic_demo_incoming_object) when -t hex is set.
    _INCOMING_OBJECT_SIG = "Incoming object:"

    def _negotiated_drafts_from_logs(self, relay_logs: List[Path]) -> List[str]:
        """Deduplicated list of drafts the relay actually negotiated with its
        peers (parsed from per-connection `-- WebTransport (moqt-N)` lines)."""
        drafts: List[str] = []
        for rl in relay_logs:
            if not rl.exists():
                continue
            try:
                text = rl.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for m in self._NEGOTIATED_MOQT_RE.finditer(text):
                if m.group(1) not in drafts:
                    drafts.append(m.group(1))
        return drafts

    @staticmethod
    def _count_received_objects(files: List[Path]) -> int:
        """Count '"Incoming object:"' receipt lines across sub output files."""
        received = 0
        for p in files:
            try:
                received += p.read_text(
                    encoding="utf-8", errors="ignore").count(
                        MoQTestRun._INCOMING_OBJECT_SIG)
            except OSError:
                continue
        return received

    def _artifact_has_content(self, path: Path) -> bool:
        """True when a received artifact holds real media bytes.

        B2: the artifact is the one number the testbed is trusted on. A CLI
        usage dump (imquic positional-args bug), a QUIC timeout, or captured
        log lines (moq-rs timed-out stdout; imquic "Incoming object" metadata)
        is NOT received data. Media magic is searched anywhere in the file and
        is definitive: imquic sub with -t hex interleaves its per-object
        metadata lines ahead of the hex-encoded payload, so ftyp/FLV need not
        be at offset 0 or raw. Only when no media magic is present do we apply
        the log/failure filters, so a metadata-only artifact fails and a
        payload-bearing one passes.
        """
        if not path.exists() or path.stat().st_size == 0:
            return False
        try:
            data = path.read_bytes()
        except OSError:
            return False
        # Media magic is definitive. imquic sub (-t hex) renders payload as
        # %02x text, so the hex-encoded signatures (66747970='ftyp',
        # 464c56='FLV') are checked too; real payload elsewhere in the file
        # also passes (metadata lines precede each object's payload).
        if any(m in data for m in (b"ftyp", b"FLV", b"66747970", b"464c56")):
            return True
        if any(m.encode() in data for m in self._FAILURE_TEXT):
            return False
        if any(m.encode() in data for m in self._LOG_TEXT):
            return False
        return bool(data.strip())

    def evaluate(self) -> Dict[str, Any]:
        result = {"run_id": self.run_id, "status": "unknown", "checks": {}}
        # Multi-stream: logs are pub_s0.log, pub_s1.log, etc. Check any.
        pub_logs = sorted(self.logs_dir.glob("pub*.log"))
        if not pub_logs:
            pub_logs = [self.logs_dir / "pub.log"]
        # Multi-stream: subscriber logs are sub_s0.log, sub_s1.log, etc.
        sub_logs = sorted(self.logs_dir.glob("sub*.log"))
        if not sub_logs:
            sub_logs = [self.logs_dir / "sub.log"]
        # For chain topology, relay logs are relay_a.log / relay_b.log.
        # Check ALL relay logs — if any relay failed, flag it.
        relay_logs = sorted(self.logs_dir.glob("relay*.log"))
        if not relay_logs:
            relay_logs = [self.logs_dir / "relay.log"]

        result["checks"]["relay_running"] = all(
            self._log_ok(rl) for rl in relay_logs)
        result["checks"]["pub_started"] = any(
            self._log_ok(pl) for pl in pub_logs)
        # D8: lldash pub is dummy (origin has pre-generated MPD) — don't require its log
        if str(self.config.get("sub", {}).get("impl", "")).startswith("lldash"):
            result["checks"]["pub_started"] = True
        result["checks"]["sub_started"] = any(
            self._log_ok(sl) for sl in sub_logs)
        # I2 (see improvements.md): "X of Y bytes delivered" under the time
        # limit. B1 (per-run folders) means output_dir only holds THIS run's
        # received data, so the byte count is trustworthy.
        # B18: count only the declared received artifact (registry sub_output),
        # never the captured stdout or incidental files in /output.
        # B17/I9: artifacts are grouped PER SUBSCRIBER so delivery and
        # integrity are judged per subscriber -- never summed into one
        # misleading number. basic/chain have the single role "sub"; fanout
        # has sub1..subN, each with its own output folder.
        sub_roles = ([r for r in self._topology.roles(self.network)
                      if r.startswith("sub") or r.startswith("late_sub")] or ["sub"])
        # Per-role artifact contracts (mixed-impl fan-out resolves each role,
        # falling back to "sub"); strip flags follow the same resolution so
        # only moq-rs captures are ANSI-stripped, never FLV binaries.
        role_output_cfg = {role: self._get_impl_config(
            self._sub_role_cfg(role).get("impl", "")).get("sub_output", {})
            for role in sub_roles}
        role_artifact_rel = {role: self._artifact_rel(cfg)
                             for role, cfg in role_output_cfg.items()}
        groups: Dict[str, List[Path]] = {}
        for role in sub_roles:
            # D6: late_sub* and fanout sub{i} have per-role output dirs (output/<role>)
            # basic/chain single sub uses shared output dir
            if role != "sub" and (self.output_dir / role).exists():
                base = self.output_dir / role
            elif self.topology_type in ("fanout", "chainfanout") and role != "sub":
                base = self.output_dir / role
            else:
                base = self.output_dir
            if not base.exists():
                groups[role] = []
                continue
            files = [p for p in base.rglob("*") if p.is_file()]
            artifact_rel = role_artifact_rel[role]
            if artifact_rel:
                files = [
                    p for p in files
                    if (fnmatch.fnmatch(p.relative_to(base).as_posix(), artifact_rel)
                        or fnmatch.fnmatch(p.relative_to(base).as_posix(), f"*/{artifact_rel}"))
                ]
            groups[role] = sorted(files)
        sub_output_files = [p for ps in groups.values() for p in ps]
        artifact_bytes = sum(p.stat().st_size for p in sub_output_files)
        original_bytes = None
        original_path = TESTDATA_DIR / self.media_file
        if original_path.exists():
            original_bytes = original_path.stat().st_size
        # B26 (see found-bugs.md): verify the received media against the
        # source. The relay mlog (when present) gives the authoritative byte
        # count handed to the subscriber -- the artifact-size figure
        # double-counts moq-rs stdout tracing logs. The content SHA and
        # byte-identical-prefix check report integrity honestly even when the
        # client drops a tail (moq-rs at this pin loses a deterministic 32 B).
        # B17/I9: verification is per-subscriber (verify_groups); the
        # aggregate fields keep their legacy meaning for single-sub runs and
        # become fanout-honest (summed mlogs, worst-tier verdict) otherwise.
        verify = verify_groups(
            self.run_dir, original_path, groups,
            logs_on_stdout={role: bool(cfg.get("logs_on_stdout", False))
                            for role, cfg in role_output_cfg.items()},
            good_threshold=float(self.config.get("integrity_threshold", 90.0)))
        # Streaming value check for the LL-DASH baseline (decisions.md D9):
        # lldash clients fetch DASH segments (init + 60x2s chunks), so a
        # whole-file SHA vs the source mp4 is meaningless (and a late
        # joiner's shorter capture could never match). Instead verify
        # per-segment VALUE against the origin chunk files plus the
        # join-adjusted expectation (skip = floor(join_delay / seg_dur)).
        # MoQ impls keep the exact/good/mismatch SHA path above untouched.
        if str(self.config.get("sub", {}).get("impl", "")).startswith("lldash"):
            from harness.verify import verify_lldash_streaming
            # MPD follows the run's media file (sample.mp4 -> sample.mpd),
            # mirroring docker/lldash/client.py mpd_name().
            _mpd = Path(self.media_file).name
            if _mpd.endswith(".mp4"):
                _mpd = _mpd[:-4] + ".mpd"
            stream = verify_lldash_streaming(groups, TESTDATA_DIR, mpd_name=_mpd)
            if stream.get("per_sub"):
                # Only override when at least one role has a streaming manifest;
                # older runs (no sidecar) keep their legacy SHA numbers untouched.
                any_manifest = any(
                    e.get("verdict") for e in stream["per_sub"].values())
                if any_manifest:
                    verify["streaming"] = True
                    verify["total_segments"] = stream.get("total_segments")
                    verify["segment_duration_s"] = stream.get("segment_duration_s")
                    # Whole-file SHA does not apply to streaming captures.
                    verify["sha256_delivered"] = None
                    verify["sha256_match"] = None
                    verify["byte_identical_bytes"] = None
                if stream.get("verdict") and any_manifest:
                    verify["verdict"] = stream["verdict"]
                seg_pcts = []
                for role, sentry in stream["per_sub"].items():
                    if role not in verify.get("per_sub", {}):
                        verify.setdefault("per_sub", {})[role] = {"role": role, **sentry}
                        continue
                    if sentry.get("verdict") is None:
                        # No manifest (predates streaming client): keep legacy.
                        continue
                    ps = verify["per_sub"][role]
                    ps["verdict"] = sentry["verdict"]
                    ps["join_delay_s"] = sentry.get("join_delay_s", 0.0)
                    ps["skipped"] = sentry.get("skipped")
                    ps["segments_fetched"] = sentry.get("segments_fetched")
                    ps["segments_expected"] = sentry.get("segments_expected")
                    ps["segments_matching"] = sentry.get("segments_matching")
                    # Phase 3 (D13): transport actually used (h3 vs TCP
                    # fallback) — without it an h3 row served over TCP would
                    # read as a QUIC result.
                    ps["fetch_protocol"] = sentry.get("fetch_protocol")
                    ps["fetch_protos"] = sentry.get("fetch_protos") or {}
                    ps["byte_identical_pct"] = sentry.get("seg_match_pct")
                    ps["byte_identical_bytes"] = None
                    ps["sha256_delivered"] = None
                    ps["sha256_match"] = None
                    if sentry.get("seg_match_pct") is not None:
                        seg_pcts.append(sentry["seg_match_pct"])
                if seg_pcts:
                    verify["byte_identical_pct"] = min(seg_pcts)
        delivered_bytes = verify.get("delivered_bytes")
        if delivered_bytes is None:
            delivered_bytes = artifact_bytes
        result["stats"] = {
            "delivered_bytes": delivered_bytes,
            "artifact_bytes": artifact_bytes,
            "original_bytes": original_bytes,
            "coverage_pct": (round(100.0 * delivered_bytes / original_bytes, 2)
                             if original_bytes else None),
            # Coverage against the EXPECTED deliverable (init + segments,
            # trailing mfra/free excluded). moq-pub never sends the source's
            # trailing boxes, so coverage vs the raw file caps below 100% BY
            # DESIGN; this is the denominator a perfect delivery scores 100% on.
            "expected_media_bytes": verify.get("expected_bytes"),
            "expected_coverage_pct": (
                round(100.0 * delivered_bytes / verify["expected_bytes"], 2)
                if (delivered_bytes is not None and verify.get("expected_bytes"))
                else None),
            "integrity": verify,
            "per_sub": verify.get("per_sub", {}),
            # B13 (see found-bugs.md): how the run actually ended.
            "completed": self.completed,
            "completion_reason": self.completion_reason,
            "run_duration_s": self.run_duration_s,
        }
        # Informational only: the integrity snapshot lives in stats.integrity
        # (never a gate by default -- moq-rs stdout logs / tail truncation
        # legitimately break the SHA until that impl is re-pinned). Runs opt
        # into failing on a mismatch via `require_integrity: true`.
        result["checks"]["integrity_checked"] = True
        # B2 (see found-bugs.md): `received_data` means a real (non-empty,
        # non-usage-text, non-log) artifact arrived. A leftover file or a CLI
        # usage dump must NOT satisfy the check.
        if self.config.get("data_check") == "object_receipt":
            # Non-media pub (imquic demo moq-pub is a clock generator): its
            # payload never contains ftyp/FLV magic, so the media-magic gate
            # above cannot judge it. Each received object prints an
            # "Incoming object:" metadata line (moq-sub.c
            # imquic_demo_incoming_object), so real delivery == enough of
            # those lines. Count them across ALL sub output artifacts.
            received = self._count_received_objects(sub_output_files)
            result["stats"]["received_object_count"] = received
            min_objects = int(self.config.get("min_objects", 1))
            result["checks"]["sub_received_data"] = received >= min_objects
            # delivered_full is object-based, not byte-coverage-based: the
            # received bytes (hex timestamps) can never cover sample.mp4.
            result["stats"]["delivered_full"] = received >= min_objects
        else:
            real_artifacts = [p for p in sub_output_files if self._artifact_has_content(p)]
            result["checks"]["sub_received_data"] = len(real_artifacts) > 0
            coverage_pct = result["stats"]["coverage_pct"]
            completion_coverage = float(
                self.network.get("completion_coverage", 0.95)) * 100.0
            # B24 (found-bugs.md): real media that never reached the whole
            # file is not a pass -- the status column must mean the full
            # deliverable arrived. coverage_pct is None (no source to
            # compare) when we cannot judge, so those keep the old behavior.
            result["stats"]["delivered_full"] = (
                coverage_pct is None or coverage_pct >= completion_coverage
            )
        # Subscribers can be quiet on stderr (imquic prints nothing on success),
        # so an empty sub.log is NOT a failure — but a log that shows a timeout
        # or usage dump IS. Only the real-artifact check decides delivery.
        result["checks"]["sub_started"] = (
            result["checks"]["sub_received_data"]
            or any(self._log_ok(sl) for sl in sub_logs)
            or any(sl.exists() and sl.stat().st_size == 0 for sl in sub_logs)
        )

        # require_draft (plan-level, for object_receipt plans): assert the
        # run's declared sub draft was actually negotiated on the relay. The
        # imquic relay logs one `-- WebTransport (moqt-N)` line per connection;
        # pub+sub are both pinned to {draft}, so the declared draft MUST appear.
        if self.config.get("require_draft"):
            negotiated = self._negotiated_drafts_from_logs(relay_logs)
            result["stats"]["negotiated_drafts"] = negotiated
            declared = str((self.config.get("sub") or {}).get("draft") or "")
            result["checks"]["negotiated_draft"] = (
                bool(declared) and declared in negotiated
            )

        all_ok = all(result["checks"].values())
        if not all_ok:
            result["status"] = "fail"
        elif not result["stats"]["delivered_full"]:
            result["status"] = "partial"
        elif (self.config.get("require_integrity")
              and verify.get("verdict") == "mismatch"):
            # Opt-in integrity gate: fail unless the received media verifies
            # as "exact" (byte-perfect SHA) or "good" (subscriber received
            # the full object stream AND the identical-prefix is >= the
            # integrity_threshold). See harness/verify.py.
            result["status"] = "fail"
        else:
            result["status"] = "pass"

        # I1: confusion matrix - compare actual vs expected
        expected = self.config.get("expect", "pass")  # default expect pass
        result["expected"] = expected
        if expected == "fail" and result["status"] == "fail":
            result["confusion"] = "TN"  # True Negative: expected fail, got fail
        elif expected == "fail" and result["status"] == "pass":
            result["confusion"] = "FP"  # False Positive: expected fail, got pass
        elif expected == "pass" and result["status"] == "pass":
            result["confusion"] = "TP"  # True Positive: expected pass, got pass
        elif expected == "pass" and result["status"] in ("fail", "partial"):
            result["confusion"] = "FN"  # False Negative: expected pass, got fail/partial
        else:
            result["confusion"] = "?"

        result["metrics"] = self.metrics_collector.collect(
            self.run_dir,
            ctx={
                "pub_impl": self.config.get("pub", {}).get("impl"),
                "sub_impl": self.config.get("sub", {}).get("impl"),
                "relay_impl": ((self.config.get("relay") or {}).get("impl")
                               or (self.config.get("relay_a") or {}).get("impl")),
                "delivered_bytes": result["stats"].get("delivered_bytes"),
                "original_bytes": result["stats"].get("original_bytes"),
                "run_duration_s": self.run_duration_s,
                "pub_start_time": result.get("start_time"),
            },
        )
# I9: best-effort playable copy per subscriber; never affects status.
        self._export_playable_artifacts(groups, role_output_cfg)
        return result

    def _role_base_dir(self, role: str) -> Path:
        """Output folder for one subscriber role (per-role dirs for fanout/
        chainfanout multi-subscriber roles, shared dir otherwise)."""
        if (self.topology_type in ("fanout", "chainfanout") and role != "sub"
                and (self.output_dir / role).exists()):
            return self.output_dir / role
        return self.output_dir

    def _export_playable_artifacts(self, groups: Dict[str, List[Path]],
                                   role_output_cfg: dict):
        """Write a cleaned, double-clickable copy ({stream}.{role}.{ext}) of
        what each subscriber received, next to its raw artifact. Transform is
        declared per implementation in registry.json (sub_output.playable).

        For moq-rs (`reconstruct: true`), additionally rebuild a sequential
        playable file from the arrival-order capture using the relay mlog's
        object table (B37: subgroup concurrency permutes the raw capture)."""
        # Imports at top so both basic/chain and fanout branches can use them
        from harness.playable import export_playable, reconstruct_from_mlog
        from harness.verify import mlog_subscriber_connections

        base_dirs = {role: self._role_base_dir(role) for role in groups}
        # Bucket roles by playable hint so mixed-impl runs export each
        # subscriber with its own transform (single-impl runs bucket into
        # one call, identical to the old behavior).
        buckets: Dict[tuple, dict] = {}
        for role in groups:
            hint = (role_output_cfg.get(role) or {}).get("playable") or {}
            key = (hint.get("transform"), hint.get("ext"), bool(hint.get("reconstruct")))
            entry = buckets.setdefault(key, {"hint": hint, "roles": []})
            entry["roles"].append(role)
        try:
            for key, bucket in buckets.items():
                hint = bucket["hint"]
                if not hint:
                    continue
                sub_groups = {r: groups[r] for r in bucket["roles"]}
                for p in export_playable(sub_groups, hint, base_dirs, self.run_id):
                    self._log(f"Playable copy written: {p.name}")
        except Exception as exc:
            self._log(f"Playable export failed (ignored): {exc}")

        needs_reconstruct = [r for r in groups
                             if ((role_output_cfg.get(r) or {}).get("playable") or {}).get("reconstruct")]
        if not needs_reconstruct:
            return
        if self.topology_type in ("fanout", "chainfanout"):
            # Fanout: pair mlog connections to subscriber roles by descending
            # artifact size (same logic as verify_groups). Then reconstruct per role.
            conns = mlog_subscriber_connections(self.run_dir / "qlogs")
            if not conns:
                self._log("Reconstruct export skipped: no subscriber mlog")
                return
            # Sort reconstruct roles by artifact size descending
            roles_by_size = sorted(
                needs_reconstruct,
                key=lambda r: -sum(p.stat().st_size for p in groups.get(r, []) if p.exists()))
            # Sort conns by total bytes descending
            conns_sorted = sorted(conns, key=lambda c: -c["total"])
            for role, conn in zip(roles_by_size, conns_sorted):
                paths = groups.get(role, [])
                existing = [p for p in paths if p.exists()]
                if not existing:
                    continue
                data = b"".join(p.read_bytes() for p in existing)
                out = base_dirs[role] / f"{self.run_id}.{role}.reconstructed.mp4"
                stats = reconstruct_from_mlog(data, conn["objects"], out)
                if stats["reconstructed_path"]:
                    self._log(
                        f"Reconstructed {out.name}: "
                        f"{stats['objects_recovered']}/{stats['objects_total']} "
                        f"objects, {stats['reconstructed_bytes']} B"
                        + (f", missing groups {stats['groups_missing']}"
                           if stats["groups_missing"] else ""))
            return
        # Basic/chain: single subscriber, use largest mlog connection
        try:
            from harness.verify import mlog_subscriber_connections
            conns = mlog_subscriber_connections(self.run_dir / "qlogs")
            if not conns:
                self._log("Reconstruct export skipped: no subscriber mlog")
                return
            conn = max(conns, key=lambda c: c["total"])
            from harness.playable import reconstruct_from_mlog
            for role in needs_reconstruct:
                paths = groups.get(role, [])
                existing = [p for p in paths if p.exists()]
                if not existing:
                    continue
                data = b"".join(p.read_bytes() for p in existing)
                out = base_dirs[role] / f"{self.run_id}.{role}.reconstructed.mp4"
                stats = reconstruct_from_mlog(data, conn["objects"], out)
                if stats["reconstructed_path"]:
                    self._log(
                        f"Reconstructed {out.name}: "
                        f"{stats['objects_recovered']}/{stats['objects_total']} "
                        f"objects, {stats['reconstructed_bytes']} B"
                        + (f", missing groups {stats['groups_missing']}"
                           if stats["groups_missing"] else ""))
        except Exception as exc:
            self._log(f"Reconstruct export failed (ignored): {exc}")


class TestbedRunner:
    def __init__(self, plan_path: str, workers: int = 1):
        self.plan = load_testplan(plan_path)
        # Phase 1 (P0-3): fail fast on unwired silent no-op keys instead of
        # running identical rows that look like comparisons. Quarantined keys
        # documented in 2_weeks/01-future-work-quarantine.md.
        from harness.plan_validation import validate_testplan
        validate_testplan(self.plan, plan_name=str(plan_path))
        self.workers = workers
        self.network_defaults = self.plan.get("network_defaults", {})
        self.test_duration = self.plan.get("test_duration", 15)
        self.media_file = self.plan.get("media", "sample.mp4")
        # Plan-level strict value gate (harness/verify.py:283): plans set
        # `require_integrity: true` top-level, but MoQTestRun.evaluate only
        # checked per-run `self.config`. Store here and inject per-run below.
        self.require_integrity = self.plan.get("require_integrity", False)
        self.integrity_threshold = self.plan.get("integrity_threshold", 90.0)
        # Plan-level non-media data check (testplans/imquic-self.yaml): when a
        # pub cannot produce real media (imquic's demo moq-pub is a clock
        # generator), `data_check: object_receipt` scores delivery on received
        # object lines ("Incoming object:") instead of byte coverage, and
        # `require_draft` asserts the negotiated draft from relay.log. Both
        # default off so media plans keep the magic/coverage gates untouched.
        self.data_check = self.plan.get("data_check", None)
        self.min_objects = self.plan.get("min_objects", 1)
        self.require_draft = self.plan.get("require_draft", False)
        self.results: List[Dict[str, Any]] = []

    def _make_run_dir(self) -> Path:
        # B30 (see found-bugs.md): second-granularity stamps collided
        # (exist_ok=True silently shared one folder across batches). A
        # collision now gets a _1/_2 suffix and a fresh folder.
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = ARTIFACTS_DIR / f"run_{stamp}"
        run_dir = base
        n = 0
        while run_dir.exists():
            n += 1
            run_dir = ARTIFACTS_DIR / f"run_{stamp}_{n}"
        run_dir.mkdir(parents=True)
        marker = ARTIFACTS_DIR / ".latest"
        marker.write_text(str(run_dir))
        return run_dir

    @staticmethod
    def _duplicate_run_ids(runs: List[dict]) -> List[str]:
        """B30: run ids whose folders would clobber each other (explicit
        duplicate `id`, or configs that make_run_id() maps to the same
        name). Empty list == plan is safe to launch."""
        counts: Dict[str, int] = {}
        for cfg in runs:
            rid = cfg.get("id") or make_run_id(cfg)
            counts[rid] = counts.get(rid, 0) + 1
        return sorted(k for k, v in counts.items() if v > 1)

    def run(self):
        runs = self.plan.get("runs", [])
        dupes = self._duplicate_run_ids(runs)
        if dupes:
            raise ValueError(
                "duplicate run id(s) in plan: "
                f"{', '.join(dupes)} -- give every row a unique 'id' or "
                "differentiate impls/drafts so generated ids differ")
        if self.workers > 1:
            raise RuntimeError(
                "--workers > 1 not supported: parallel runs would collide on "
                "host port bindings (relay 4443, relay_b 4444) and batch dir. "
                "Use workers=1 or implement per-worker port offsets first.")
        batch_dir = self._make_run_dir()
        self._log(f"Starting {len(runs)} test runs with {self.workers} worker(s)")
        lock = threading.Lock()
        completed = [0]

        def worker(run_config: dict):
            try:
                # Inject plan-level topology into each run if not set per-run
                if "topology" not in run_config:
                    run_config["topology"] = self.plan.get("topology", "basic")
                # Inject plan-level strict value gate if not set per-run
                # (fixes run_20260905_173031: top-level require_integrity:true
                # never reached evaluate(), so H3 mismatch still passed)
                if "require_integrity" not in run_config and self.require_integrity:
                    run_config["require_integrity"] = self.require_integrity
                if "integrity_threshold" not in run_config and "integrity_threshold" in self.plan:
                    run_config["integrity_threshold"] = self.plan["integrity_threshold"]
                # Inject plan-level object_receipt data-mode knobs (defaults off)
                if "data_check" not in run_config and self.data_check:
                    run_config["data_check"] = self.data_check
                if "min_objects" not in run_config and "min_objects" in self.plan:
                    run_config["min_objects"] = self.min_objects
                if "require_draft" not in run_config and self.require_draft:
                    run_config["require_draft"] = self.require_draft
                run = MoQTestRun(run_config, self.network_defaults, batch_dir,
                                 run_config.get("media", self.media_file),
                                 default_test_duration=self.test_duration,
                                 capture=self.plan.get("capture",
                                                       self.network_defaults.get("capture", False)))
                result = run.run()
                evaluation = run.evaluate()
                result["evaluation"] = evaluation
                result["status"] = evaluation["status"]
                # evaluate() computes metrics into its local result, but the
                # report/summary readers expect them at the top level. Promote
                # them so rtt/packet/throughput metrics reach every consumer.
                result["metrics"] = evaluation.get("metrics", {})
                with lock:
                    self.results.append(result)
                    completed[0] += 1
                    ok = evaluation.get("status", "fail")
                    self._log(f"[{completed[0]}/{len(runs)}] {run.run_id}: {ok}")
            except Exception as e:
                with lock:
                    self.results.append({
                        "run_id": "error",
                        "config": run_config,
                        "status": "error",
                        "error": str(e),
                    })
                    completed[0] += 1

        if self.workers > 1:
            threads = []
            for run_config in runs:
                t = threading.Thread(target=worker, args=(run_config,))
                threads.append(t)
                t.start()
                if len(threads) >= self.workers:
                    for t in threads:
                        t.join()
                    threads = []
            for t in threads:
                t.join()
        else:
            for run_config in runs:
                worker(run_config)

        self._save_summary(batch_dir)
        self._print_summary()
        report_gen = ReportGenerator(batch_dir)
        report_gen.save_report()

    def _save_summary(self, batch_dir: Path):
        summary = {
            "plan": self.plan.get("name", "unknown"),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total": len(self.results),
            "passed": sum(1 for r in self.results
                          if r.get("evaluation", {}).get("status") == "pass"),
            "partial": sum(1 for r in self.results
                           if r.get("evaluation", {}).get("status") == "partial"),
            "failed": sum(1 for r in self.results
                          if r.get("evaluation", {}).get("status") == "fail"),
            "results": self.results,
        }
        with open(batch_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        with open(batch_dir / "summary.txt", "w") as f:
            f.write(f"Plan: {summary['plan']}\n")
            f.write(f"Total: {summary['total']}\n")
            f.write(f"Pass:  {summary['passed']}\n")
            f.write(f"Partial: {summary['partial']}\n")
            f.write(f"Fail:  {summary['failed']}\n\n")
            f.write(f"{'Run ID':<60} {'Status':<10} {'Delivered':<40} {'Integrity':<22} {'RTT (ms)':<12} {'End':<22}\n")
            f.write("-" * 144 + "\n")
            for r in self.results:
                stats = r.get("evaluation", {}).get("stats", {})
                d = stats.get("delivered_bytes")
                o = stats.get("original_bytes")
                cov = stats.get("coverage_pct")
                if d is not None and o:
                    delivered = f"{d}/{o} ({cov}%)"
                    # Expected-media coverage: a perfect delivery reads
                    # "100% exp" even though the raw file comparison stays
                    # below 100% (publisher excludes trailing mfra/free).
                    ecov = stats.get("expected_coverage_pct")
                    per_sub = (stats.get("integrity") or {}).get("per_sub") or {}
                    if len(per_sub) > 1 and stats.get("expected_media_bytes"):
                        # Fanout: summed delivery vs one stream's expected
                        # size reads N*100% -- meaningless. Show how many
                        # subscribers were served the FULL stream instead.
                        # MoQ: mlog_delivered_bytes == expected; lldash (no mlog):
                        # verdict exact/good or artifact within 5% of expected.
                        exp_b = stats["expected_media_bytes"]
                        full = sum(
                            1 for ps in per_sub.values()
                            if ps.get("mlog_delivered_bytes") == exp_b)
                        if full == 0:
                            full = sum(
                                1 for ps in per_sub.values()
                                if ps.get("verdict") in ("exact", "good"))
                            if full == 0:
                                full = sum(
                                    1 for ps in per_sub.values()
                                    if ps.get("artifact_bytes") and abs(
                                        ps.get("artifact_bytes") - exp_b) / exp_b < 0.05)
                        delivered += f" [full {full}/{len(per_sub)}]"
                    elif (stats.get("expected_media_bytes")
                          and ecov is not None
                          and stats["expected_media_bytes"] != o):
                        delivered += f" [{ecov}% exp]"
                else:
                    delivered = "-"
                integrity = stats.get("integrity", {})
                verdict = integrity.get("verdict")
                identical = integrity.get("byte_identical_pct")
                if verdict == "exact":
                    integrity_text = "sha match"
                elif verdict == "good":
                    integrity_text = (f"good {identical}%"
                                      if identical is not None else "good")
                elif verdict == "mismatch":
                    integrity_text = (f"sha mismatch {identical}% identical"
                                      if identical is not None else "sha mismatch")
                else:
                    integrity_text = "-"
                # B13: distinguish runs that finished delivering (artifact stopped
                # growing after reaching completion_coverage) from runs chopped
                # by the time limit. Labeled "End" (not "Completed") because
                # quiesce can still fire on runs the status column then calls
                # out as partial/fail; the status column is authoritative.
                if "completed" in stats:
                    if stats.get("completed"):
                        completed_text = "quiesced"
                    elif stats.get("completion_reason") == "no artifact contract to detect completion":
                        completed_text = "no contract"
                    else:
                        completed_text = "time limit"
                else:
                    completed_text = "-"
                rtt_m = r.get("metrics", {})
                rtt_val = rtt_m.get("rtt_estimate_ms")
                if rtt_val is None:
                    rtt_val = rtt_m.get("wire_rtt_estimate_ms")
                rtt_text = (f"{rtt_val:.1f}" if rtt_val is not None
                            else "-")
                f.write(f"{r.get('run_id', '?'):<60} "
                        f"{r.get('evaluation', {}).get('status', '?'):<10} "
                        f"{delivered:<26} {integrity_text:<22} "
                        f"{rtt_text:<12} {completed_text:<22}\n")
                # B17/I9: per-subscriber breakdown (fanout). The aggregate row
                # above sums protocol-level delivery; these lines show what
                # EACH subscriber's own capture verifies as.
                per_sub = integrity.get("per_sub", {})
                for role, ps in sorted(per_sub.items()):
                    media = ps.get("media_bytes")
                    mlog = ps.get("mlog_delivered_bytes")
                    pct = ps.get("byte_identical_pct")
                    verdict = ps.get("verdict") or "-"
                    f.write(f"    {role}: artifact={ps.get('artifact_bytes')} B, "
                            f"media={media if media is not None else '-'} B, "
                            f"mlog={mlog if mlog is not None else '-'}, "
                            f"prefix={pct if pct is not None else '-'}%, "
                            f"verdict={verdict}\n")

    def _print_summary(self):
        passed = sum(1 for r in self.results
                     if r.get("evaluation", {}).get("status") == "pass")
        partial = sum(1 for r in self.results
                      if r.get("evaluation", {}).get("status") == "partial")
        failed = sum(1 for r in self.results
                     if r.get("evaluation", {}).get("status") == "fail")
        total = len(self.results)
        print("\n" + "=" * 70)
        print(f"RESULTS: {total} total | {passed} passed | {partial} partial | {failed} failed")
        print("=" * 70)
        for r in self.results:
            run_id = r.get("run_id", "?")
            status = r.get("evaluation", {}).get("status", "?")
            symbol = ("PASS" if status == "pass"
                      else "PARTIAL" if status == "partial" else "FAIL")
            print(f"  [{symbol}] {run_id}")
        print("=" * 70)

    def _log(self, msg: str):
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
        print(f"[{timestamp}] [runner] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser(description="MoQT Interop Testbed Orchestrator")
    parser.add_argument("--plan", required=True, help="Path to test plan YAML")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    parser.add_argument("--verify", action="store_true",
                        help="Run draft verification step before tests")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"Error: plan not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    if args.verify:
        from harness.verify import DraftVerifier
        verifier = DraftVerifier()
        results = verifier.verify_all()
        verifier.print_report(results)

    runner = TestbedRunner(str(plan_path), workers=args.workers)
    try:
        runner.run()
    except ValueError as exc:
        # B30: duplicate run ids in the plan -- fail before any container
        # work with an actionable message.
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
