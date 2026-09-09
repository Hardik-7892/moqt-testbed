"""Teardown-probe knobs: env parsing for drain timing + kill order.

Covers harness.runner._env_float and _teardown_order (pure functions).
The teardown paths themselves need Docker and are exercised on the VM
via testplans/sha-single.yaml (single row, ~30 s wall).
"""
from harness.runner import _env_float, _teardown_order

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
