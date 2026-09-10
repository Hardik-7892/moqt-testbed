"""Teardown-probe knobs: env parsing for drain timing + kill order.

Covers harness.runner._env_float and _teardown_order (pure functions).
The teardown paths themselves need Docker and are exercised on the VM
via testplans/sha-single.yaml (single row, ~30 s wall).
"""
from harness.runner import _env_float, _teardown_order, _launch_order

def test_env_float_default_when_unset(monkeypatch):
    monkeypatch.delenv("MOQ_STOP_GRACE_S", raising=False)
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 3.0


def test_env_float_parses_valid(monkeypatch):
    monkeypatch.setenv("MOQ_STOP_GRACE_S", "6")
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 6.0
    monkeypatch.setenv("MOQ_STOP_GRACE_S", "2.5")
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 2.5


def test_env_float_rejects_garbage_and_nonpositive(monkeypatch, capsys):
    monkeypatch.setenv("MOQ_STOP_GRACE_S", "soon")
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 3.0
    monkeypatch.setenv("MOQ_STOP_GRACE_S", "-1")
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 3.0
    monkeypatch.setenv("MOQ_STOP_GRACE_S", "0")
    assert _env_float("MOQ_STOP_GRACE_S", 3.0) == 3.0
    assert "WARN" in capsys.readouterr().out


def test_teardown_order_default_and_valid(monkeypatch):
    monkeypatch.delenv("MOQ_TEARDOWN_ORDER", raising=False)
    assert _teardown_order() == "pub-first"
    monkeypatch.setenv("MOQ_TEARDOWN_ORDER", "relay-first")
    assert _teardown_order() == "relay-first"


def test_teardown_order_unknown_falls_back_loud(monkeypatch, capsys):
    monkeypatch.setenv("MOQ_TEARDOWN_ORDER", "nuke-first")
    assert _teardown_order() == "pub-first"
    assert "WARN" in capsys.readouterr().out


def test_class_defaults_frozen():
    # The historic defaults must never drift: comparability with every
    # batch run before the probe depends on it.
    from harness.runner import MoQTestRun
    assert MoQTestRun.STOP_GRACE_S == 3.0
    assert MoQTestRun.STOP_DRAIN_S == 12.0


def _minimal_run(tmp_path, monkeypatch, **env):
    """Instantiate MoQTestRun without Docker (init is container-free)."""
    from harness.runner import MoQTestRun
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    run_config = {
        "id": "probe-unit",
        "pub": {"impl": "moq-rs", "draft": 18},
        "relay": {"impl": "moq-rs", "draft": 18},
        "sub": {"impl": "moq-rs", "draft": 18},
        "network": {},
    }
    return MoQTestRun(run_config, {}, tmp_path, "sample.mp4", 15, False)


def test_num_streams_bound_before_any_launch_path(tmp_path, monkeypatch):
    # Regression for the moxygen-30s-subfirst NameError: the sub-first
    # branch referenced num_streams before the publisher block assigned
    # it. Hoisted to __init__ so every order sees it bound.
    for env in ({}, {"MOQ_SUB_FIRST": "1"}):
        run = _minimal_run(tmp_path, monkeypatch, **env)
        assert run.num_streams == 1
        assert run.launch_order == ("sub-first" if env else "pub-first")


def test_num_streams_parses_and_clamps(tmp_path, monkeypatch):
    run = _minimal_run(tmp_path, monkeypatch)
    assert run.num_streams == 1
    import harness.runner as R
    run2 = R.MoQTestRun(
        {"id": "x", "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
         "sub": {"impl": "moq-rs"}, "streams": 3, "network": {}},
        {}, tmp_path, "sample.mp4", 15, False)
    assert run2.num_streams == 3
    run3 = R.MoQTestRun(
        {"id": "y", "pub": {"impl": "moq-rs"}, "relay": {"impl": "moq-rs"},
         "sub": {"impl": "moq-rs"}, "streams": "many", "network": {}},
        {}, tmp_path, "sample.mp4", 15, False)
    assert run3.num_streams == 1


def test_launch_helper_signature_matches_call_sites():
    # Both launch-order branches must pass what _launch_subscribers takes;
    # arg drift here is a VM-only crash, so pin it here.
    import inspect
    from harness.runner import MoQTestRun
    params = list(inspect.signature(MoQTestRun._launch_subscribers).parameters)
    assert params == ["self", "stream_name", "media_path", "last_relay_ip",
                      "last_relay_port", "last_relay_path", "num_streams"]


def test_launch_order_default_and_sub_first(monkeypatch):
    monkeypatch.delenv("MOQ_SUB_FIRST", raising=False)
    assert _launch_order() == "pub-first"
    monkeypatch.setenv("MOQ_SUB_FIRST", "1")
    assert _launch_order() == "sub-first"


def test_launch_order_garbage_falls_back_loud(monkeypatch, capsys):
    monkeypatch.setenv("MOQ_SUB_FIRST", "yes-please")
    assert _launch_order() == "pub-first"
    assert "WARN" in capsys.readouterr().out
    monkeypatch.setenv("MOQ_SUB_FIRST", "0")
    assert _launch_order() == "pub-first"


def test_pub_delay_bound_on_instance(tmp_path, monkeypatch):
    from harness.runner import MoQTestRun
    run_config = {
        "id": "probe-delay",
        "pub": {"impl": "moxygen", "draft": 18},
        "relay": {"impl": "moxygen", "draft": 18},
        "sub": {"impl": "moxygen", "draft": 18},
        "network": {},
    }
    monkeypatch.delenv("MOQ_PUB_DELAY_S", raising=False)
    assert MoQTestRun(run_config, {}, tmp_path,
                      "sample.flv", 15, False).pub_delay_s == 0.0
    monkeypatch.setenv("MOQ_PUB_DELAY_S", "10")
    run = MoQTestRun(run_config, {}, tmp_path, "sample.flv", 15, False)
    assert run.pub_delay_s == 10.0
    assert run.launch_order == "pub-first"  # delay alone changes no order
