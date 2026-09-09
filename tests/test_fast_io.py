"""MOQ_FAST_IO staging: hot dirs on VM-local disk, copied back post-run."""
from harness.runner import MoQTestRun


def _make(tmp_path, monkeypatch, fast: bool) -> MoQTestRun:
    if fast:
        monkeypatch.setenv("MOQ_FAST_IO", "1")
        monkeypatch.setenv("MOQ_STAGE_ROOT", str(tmp_path / "stage"))
    else:
        monkeypatch.delenv("MOQ_FAST_IO", raising=False)
    return MoQTestRun({"id": "t1"}, {}, tmp_path / "batch")


def test_default_dirs_live_in_run_dir(tmp_path, monkeypatch):
    r = _make(tmp_path, monkeypatch, fast=False)
    assert r.output_dir == r.run_dir / "output"
    assert r.qlogs_dir == r.run_dir / "qlogs"
    assert r._stage_back == []


def test_fast_io_stages_only_hot_dirs(tmp_path, monkeypatch):
    r = _make(tmp_path, monkeypatch, fast=True)
    stage = tmp_path / "stage" / "t1"
    assert r.output_dir == stage / "output_dir"
    assert r.qlogs_dir == stage / "qlogs_dir"
    assert r.pcaps_dir == stage / "pcaps_dir"
    # cold dirs stay on the shared path
    assert r.logs_dir == r.run_dir / "logs"
    assert r.cert_dir == r.run_dir / "certs"
    assert {real.name for _, real in r._stage_back} == {
        "output", "qlogs", "pcaps"}


def test_copy_stage_back_brings_files_home(tmp_path, monkeypatch):
    r = _make(tmp_path, monkeypatch, fast=True)
    r.output_dir.mkdir(parents=True, exist_ok=True)
    r.qlogs_dir.mkdir(parents=True, exist_ok=True)
    (r.output_dir / "artifact.bin").write_bytes(b"hello")
    (r.qlogs_dir / "conn_server.mlog").write_text("\x1e{}")
    r._copy_stage_back()
    assert (r.run_dir / "output" / "artifact.bin").read_bytes() == b"hello"
    assert (r.run_dir / "qlogs" / "conn_server.mlog").exists()


def test_copy_stage_back_noop_without_fast_io(tmp_path, monkeypatch):
    r = _make(tmp_path, monkeypatch, fast=False)
    r.output_dir.mkdir(parents=True, exist_ok=True)
    before = r.output_dir
    r._copy_stage_back()          # must not raise and must not move anything
    assert r.output_dir == before
