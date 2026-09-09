"""Mixed-impl fan-out: per-subscriber role resolution without Docker.

Covers MoQTestRun._sub_role_cfg fallback, per-path ANSI-strip flags
(_strip_flag), per-role base dirs (_role_base_dir), and dict strip flags
in verify_groups. Docker-free: constructs MoQTestRun without running.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import runner as runner_mod
from harness.runner import MoQTestRun


def _run(config, network, tmp_path, topology="fanout"):
    run = MoQTestRun.__new__(MoQTestRun)
    run.config = config
    run.network = network
    run.topology_type = topology
    from topologies import TOPOLOGIES
    run._topology = TOPOLOGIES[topology]()
    run.run_id = config.get("id", "test")
    run.run_dir = tmp_path
    run.output_dir = tmp_path / "output"
    run.media_file = config.get("media", "sample.mp4")
    return run


def test_sub_role_cfg_falls_back_to_sub(tmp_path):
    run = _run({"id": "t", "sub": {"impl": "moq-rs", "draft": 18}}, {}, tmp_path)
    assert run._sub_role_cfg("sub1") == {"impl": "moq-rs", "draft": 18}
    assert run._sub_role_cfg("late_sub1") == {"impl": "moq-rs", "draft": 18}


def test_sub_role_cfg_override_wins(tmp_path):
    run = _run({"id": "t", "sub": {"impl": "moq-rs"},
                "sub3": {"impl": "imquic", "draft": 18}}, {}, tmp_path)
    assert run._sub_role_cfg("sub3") == {"impl": "imquic", "draft": 18}
    assert run._sub_role_cfg("sub1") == {"impl": "moq-rs"}


def test_strip_flag_bool_and_dict(tmp_path):
    p = tmp_path / "a"
    assert MoQTestRun._strip_flag(True, p) is True
    assert MoQTestRun._strip_flag(False, p) is False
    assert MoQTestRun._strip_flag({str(p): True}, p) is True
    assert MoQTestRun._strip_flag({}, p) is False


def test_role_base_dir(tmp_path):
    run = _run({"id": "t"}, {}, tmp_path)
    (tmp_path / "output" / "sub1").mkdir(parents=True)
    assert run._role_base_dir("sub1") == tmp_path / "output" / "sub1"
    run_basic = _run({"id": "t"}, {}, tmp_path, topology="basic")
    assert run_basic._role_base_dir("sub") == tmp_path / "output"


def test_completion_paths_mixed_impls(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "ensure_cert_set", lambda *a, **k: None)
    config = {"id": "t", "sub": {"impl": "moq-rs"},
              "sub2": {"impl": "moxygen"}}
    run = _run(config, {"num_subscribers": 2}, tmp_path)
    paths = run._completion_artifact_paths()
    names = sorted(p.name for p in paths)
    assert len(paths) == 2
    assert any(n.endswith(".flv") for n in names), names
    assert any(not n.endswith(".flv") for n in names), names


def test_verify_groups_dict_strip_flags(tmp_path):
    from harness.verify import verify_groups
    src = tmp_path / "src.mp4"
    src.write_bytes(b"")
    groups = {"sub1": [], "sub2": []}
    out = verify_groups(tmp_path, src, groups,
                        logs_on_stdout={"sub1": True, "sub2": False})
    assert out["verdict"] is None
    assert set(out["per_sub"]) == set()
