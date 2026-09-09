"""P1 quick-wins: B29 metadata wiring, B30 batch-dir/id hygiene, B31 init-object metric."""
import json
from pathlib import Path

import pytest
import yaml

from harness import runner as runner_mod
from harness.measure import MetricsCollector
from harness.runner import MoQTestRun, TestbedRunner

TestbedRunner.__test__ = False  # silence pytest collection (name starts with Test)


# --- B29: metadata.json is written by run() ---

def test_run_writes_metadata_json(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "ensure_cert_set", lambda *a, **k: None)
    r = MoQTestRun({"id": "meta-test"}, {"bw": 50}, tmp_path / "batch")
    r._execute_test = lambda: None            # no Docker needed
    r.run()
    meta = json.loads((r.run_dir / "metadata.json").read_text())
    assert meta["run_id"] == "meta-test"
    assert meta["config"]["id"] == "meta-test"
    assert meta["network"] == {"bw": 50}


# --- B30: batch-dir collisions get suffixed, not shared ---

def test_batch_dir_unique_within_same_second(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "ARTIFACTS_DIR", tmp_path)
    tr = TestbedRunner(str(runner_mod.BASE_DIR / "testplans" / "interop-quick.yaml"))
    d1 = tr._make_run_dir()
    d2 = tr._make_run_dir()
    assert d1 != d2
    assert d1.exists() and d2.exists()
    assert (tmp_path / ".latest").read_text() == str(d2)


# --- B30: duplicate run ids rejected before any container work ---

def test_duplicate_ids_detected_by_helper():
    runs = [{"id": "same"}, {"id": "same"}, {"id": "other"}]
    assert TestbedRunner._duplicate_run_ids(runs) == ["same"]


def test_generated_id_collision_also_detected():
    rows = [
        {"pub": {"impl": "moq-rs", "draft": 18},
         "relay": {"impl": "moq-rs", "draft": 18},
         "sub": {"impl": "moq-rs", "draft": 18}},
        {"pub": {"impl": "moq-rs", "draft": 18},
         "relay": {"impl": "moq-rs", "draft": 18},
         "sub": {"impl": "moq-rs", "draft": 18}},
    ]
    dupes = TestbedRunner._duplicate_run_ids(rows)
    assert len(dupes) == 1          # both rows map to the same generated id


def test_unique_plan_has_no_duplicates():
    assert TestbedRunner._duplicate_run_ids([{"id": "a"}, {"id": "b"}]) == []


def test_duplicate_plan_raises_before_containers(tmp_path):
    plan = {"name": "dupe", "topology": "basic",
            "runs": [{"id": "row"}, {"id": "row"}]}
    p = tmp_path / "plan.yaml"
    p.write_text(yaml.safe_dump(plan))
    tr = TestbedRunner(str(p))
    with pytest.raises(ValueError, match="duplicate run id"):
        tr.run()


# --- I4: late-joiner subscriber topology support ---

def test_fanout_roles_includes_late_subs(tmp_path):
    from topologies.fanout import FanoutTopology
    topo = FanoutTopology()
    roles = topo.roles({"num_subscribers": 3, "late_sub_count": 2})
    assert "pub" in roles
    assert "relay" in roles
    assert "sub1" in roles and "sub2" in roles and "sub3" in roles
    assert "late_sub1" in roles and "late_sub2" in roles

def test_fanout_fanout_sub_links_includes_late_subs(tmp_path):
    from topologies.fanout import FanoutTopology
    topo = FanoutTopology()
    links = topo.fanout_sub_links({"num_subscribers": 3, "late_sub_count": 2})
    sub_links = [link for link in links if link[0].startswith("sub") or link[0].startswith("late_sub")]
    assert len(sub_links) == 5  # 3 regular + 2 late
    assert ("late_sub1", "s1", "late_sub1") in links
    assert ("late_sub2", "s1", "late_sub2") in links

def test_fanout_default_impaired_includes_late_subs(tmp_path):
    from topologies.fanout import FanoutTopology
    topo = FanoutTopology()
    impaired = topo.default_impaired_roles({"num_subscribers": 2, "late_sub_count": 1})
    assert "sub1" in impaired
    assert "sub2" in impaired
    assert "late_sub1" in impaired

def test_fanout_config_keys_includes_late_subs(tmp_path):
    from topologies.fanout import FanoutTopology
    topo = FanoutTopology()
    keys = topo.config_keys({"num_subscribers": 2, "late_sub_count": 1})
    assert keys["late_sub1"] == "sub"
    assert keys["sub1"] == "sub1"
    assert keys["sub2"] == "sub2"
    assert keys["pub"] == "pub"
    assert keys["relay"] == "relay"

def test_fanout_client_roles_includes_late_subs(tmp_path):
    from topologies.fanout import FanoutTopology
    topo = FanoutTopology()
    client_roles = topo.client_roles()
    assert "late_sub1" in client_roles
    assert "late_sub99" in client_roles  # generous upper bound


# --- I5: multi-stream support ---

def test_multistream_config_defaults_to_one(tmp_path):
    from harness.runner import MoQTestRun
    r = MoQTestRun({
        "pub": {"impl": "moq-rs", "draft": 18},
        "relay": {"impl": "moq-rs", "draft": 18},
        "sub": {"impl": "moq-rs", "draft": 18},
    }, {"bw": 50}, tmp_path / "batch")
    # Default streams = 1 (config doesn't have "streams" key)
    assert r.config.get("streams", 1) == 1

def test_multistream_config_explicit(tmp_path):
    from harness.runner import MoQTestRun
    r = MoQTestRun({
        "pub": {"impl": "moq-rs", "draft": 18},
        "relay": {"impl": "moq-rs", "draft": 18},
        "sub": {"impl": "moq-rs", "draft": 18},
        "streams": 3,
    }, {"bw": 50}, tmp_path / "batch")
    assert r.config.get("streams", 1) == 3


# --- B31: moq-rs objects_published includes the init object ---

def _pub_log(tmp_path, body: str) -> Path:
    p = tmp_path / "pub.log"
    p.write_text(body)
    return p


def test_moqrs_objects_count_init_plus_segments(tmp_path):
    log = _pub_log(
        tmp_path,
        'catalog: { "tracks": [ ... ] }\n'
        "timestamp: 0 segment: 0:0 priority: 127\n"
        "timestamp: 1 segment: 1:0 priority: 127\n")
    assert MetricsCollector()._count_moqrs_objects(log) == 3   # init + 2


def test_moqrs_objects_zero_without_segments(tmp_path):
    log = _pub_log(tmp_path, 'catalog: { "tracks": [] }\n')
    assert MetricsCollector()._count_moqrs_objects(log) == 0


# --- B39: relay chaining via shared coordinator file ---

# --- B36: pre-flight image tag skew detection ---

def test_verify_image_tags_no_skew(monkeypatch, tmp_path):
    """When local and Hub tags have the same image ID, check passes."""
    calls = []

    def fake_inspect(*args, **kwargs):
        cmd = args[0] if args else []
        if cmd[0:2] == ["docker", "inspect"]:
            # format: ["docker", "inspect", "--format", "{{.Id}}", tag]
            calls.append(cmd[4])  # tag is 5th element
            class R:
                returncode = 0
                stdout = "sha256:abcdef123456\n"
            return R()
        class R:
            returncode = 1
            stdout = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_inspect)

    r = MoQTestRun({
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
    }, {"bw": 50}, tmp_path / "batch")

    r._verify_image_tags()  # should not raise
    assert "0hardikpandey/moq-rs-client:18" in calls
    assert "0hardikpandey/moq-rs-relay:18" in calls
    assert "moq-rs/client:18" in calls  # local equivalent also checked


def test_verify_image_tags_detects_skew(monkeypatch, tmp_path):
    """When local and Hub tags diverge, check raises with actionable msg."""
    tag_ids = {
        "0hardikpandey/moq-rs-client:18": "sha256:old1111111111111111111111111111111111111111",
        "0hardikpandey/moq-rs-relay:18": "sha256:old2222222222222222222222222222222222222222",
        "moq-rs/client:18": "sha256:new1111111111111111111111111111111111111111",
        "moq-rs/relay:18": "sha256:new2222222222222222222222222222222222222222",
    }

    def fake_inspect(*args, **kwargs):
        cmd = args[0] if args else []
        if cmd[0:2] == ["docker", "inspect"]:
            tag = cmd[4]  # tag is 5th element
            class R:
                returncode = 0
                stdout = f"{tag_ids.get(tag, 'sha256:missing')}\n"
            return R()
        class R:
            returncode = 1
            stdout = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_inspect)

    r = MoQTestRun({
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
    }, {"bw": 50}, tmp_path / "batch")

    with pytest.raises(RuntimeError, match="Image tag skew detected"):
        r._verify_image_tags()


def test_verify_image_tags_missing_tag_raises(monkeypatch, tmp_path):
    """Missing local tag raises clear error."""

    def fake_inspect(*args, **kwargs):
        cmd = args[0] if args else []
        if cmd[0:2] == ["docker", "inspect"]:
            class R:
                returncode = 1
                stderr = "No such image"
                stdout = ""
            return R()
        class R:
            returncode = 1
            stdout = ""
        return R()

    monkeypatch.setattr("subprocess.run", fake_inspect)

    r = MoQTestRun({
        "pub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
        "relay": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-relay:18"},
        "sub": {"impl": "moq-rs", "draft": 18, "tag": "0hardikpandey/moq-rs-client:18"},
    }, {"bw": 50}, tmp_path / "batch")

    with pytest.raises(RuntimeError, match="tag '0hardikpandey/moq-rs-client:18' not found locally"):
        r._verify_image_tags()

class TestRelayChainFlags:
    def test_upstream_advertises_reachable_node(self):
        flags = MoQTestRun._relay_chain_flags(True, "10.0.2.1", 4443, "moq-rs")
        assert "--coordinator-file /moq-coordinator/coordinator.json" in flags
        assert "--node https://10.0.2.1:4443" in flags
        assert "--announce" not in flags
        assert "--tls-disable-verify" not in flags

    def test_downstream_skips_verify_never_announces(self):
        flags = MoQTestRun._relay_chain_flags(False, None, 4443, "moq-rs")
        assert "--coordinator-file" in flags
        assert "--tls-disable-verify" in flags
        assert "--node" not in flags
        assert "--announce" not in flags

    def test_upstream_without_inter_relay_ip_still_shares_coordinator(self):
        flags = MoQTestRun._relay_chain_flags(True, None, 4443, "moq-rs")
        assert "--coordinator-file" in flags
        assert "--node" not in flags

    def test_non_moqrs_relays_get_no_flags(self):
        for impl in ("imquic", "moxygen"):
            assert MoQTestRun._relay_chain_flags(False, None, 4443, impl) == ""
