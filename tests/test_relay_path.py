import json

from harness.runner import MoQTestRun
from harness.runner import REGISTRY_PATH


def _filler():
    return MoQTestRun.__new__(MoQTestRun)


def _impl(name):
    with open(REGISTRY_PATH) as f:
        registry = json.load(f)
    for impl in registry["implementations"]:
        if impl["name"] == name:
            return impl
    raise KeyError(name)


def test_moxygen_declares_client_path():
    assert _impl("moxygen").get("client_path") == "/moq"


def test_moqrs_entrypoint_uses_path_placeholder():
    for role in ("pub", "sub"):
        assert "{path}" in _impl("moq-rs")["entrypoints"][role]


def test_moqrs_url_gains_relay_client_path():
    pub = _impl("moq-rs")["entrypoints"]["pub"]
    sub = _impl("moq-rs")["entrypoints"]["sub"]
    values = {"relay": "10.0.0.2", "port": "9448", "stream": "test/0.mp4",
              "file": "/media/sample.mp4", "dir": "/output", "draft": "18",
              "join_delay": "0", "path": "/moq"}
    runner = _filler()
    assert runner._fill_entrypoint(pub, values).endswith("https://10.0.0.2:9448/moq")
    assert runner._fill_entrypoint(sub, values).startswith(
        "moq-sub --name test/0.mp4 --tls-disable-verify ")
    assert runner._fill_entrypoint(sub, values).endswith("https://10.0.0.2:9448/moq")


def test_moqrs_url_without_path_stays_clean():
    pub = _impl("moq-rs")["entrypoints"]["pub"]
    runner = _filler()
    assert runner._fill_entrypoint(
        pub, {"relay": "10.0.0.2", "port": "4443", "stream": "test/video",
              "file": "/media/sample.mp4", "dir": "/output", "draft": "18",
              "join_delay": "0", "path": ""}
    ).endswith("https://10.0.0.2:4443")