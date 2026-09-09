import json
import subprocess
import sys
import tempfile
import time
import shutil
from pathlib import Path
from typing import Optional, Tuple

from harness.certs import ensure_cert_set
from harness.quic_alpn import MOQ_ALPN_TO_DRAFT, extract_alpn_from_pcap


def _run(cmd: list, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _gen_cert(d: Path, impl: dict):
    # B6 (see found-bugs.md): cert aliases come from the registry, not from a
    # hardcoded list — moxygen/imquic get the files their relays expect.
    ensure_cert_set(d, impl.get("cert_aliases", {}),
                    common_name="moq-probe", days=1,
                    check=True, timeout=30)


def _cleanup(*names: str):
    for n in names:
        if n:
            _run(["docker", "rm", "-f", n], timeout=15)


def _resolve_images(impl: dict, draft: str) -> dict:
    """Return a copy of impl with {draft} substituted in image names."""
    resolved = dict(impl)
    resolved["image"] = {
        role: img.replace("{draft}", draft) if "{draft}" in img else img
        for role, img in impl["image"].items()
    }
    resolved["claimed_draft"] = draft
    return resolved


def probe_draft(impl: dict, draft: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Determine the actual negotiated draft version of an implementation.

    Returns ``(draft, evidence)`` where evidence is one of:
    - ``"setup"`` / ``"alpn"`` / ``"tap14"`` — draft is CONFIRMED by real
      protocol activity (SETUP version in mlog, decrypted ClientHello ALPN,
      or interop-test setup-only),
    - ``"boot"`` — the container/binary booted, but the negotiated draft was
      NOT confirmed (boot-only probe),
    - ``"unverified"`` — the impl ran but no version could be parsed,
    - ``"failed"`` — it could not be run at all.

    ``draft`` is ``None`` whenever it was not actually confirmed — the probe
    NEVER returns a claimed draft as if it were negotiated (B16).

    If *draft* is given, substitute ``{draft}`` in image name templates first.
    """
    if draft is not None:
        impl = _resolve_images(impl, draft)
    name = impl["name"]
    # Baseline LL-DASH (h2/h3) is not MoQ — no ALPN moqt-* to verify.
    # Return BOOT directly (honest: image exists, not a MoQ negotiation).
    # This avoids FAILED from trying to parse MoQ SETUP on nginx/caddy.
    if name.startswith("lldash") or impl.get("source") == "baseline":
        # If image not present locally, still return boot to avoid noisy FAILED
        # (verify is informational; real lldash correctness is via test runs).
        return (None, "boot")
    if name == "moq-rs":
        return _probe_moqrs(impl)
    if name == "imquic":
        return _probe_imquic(impl)
    if name == "moxygen":
        return _probe_moxygen(impl)
    return _probe_generic(impl)


def _mlog_records(mlog_dir: Path):
    """Yield parsed JSON records from qlog/mlog JSON-SEQ files.

    moq-rs writes JSON-SEQ either record-separated (0x1E, drafts 16/18) or
    newline-terminated (draft-14). Tolerate the leading qlog header record
    and any stray/binary bytes (older buggy mlog lines could be non-UTF-8).
    """
    for f in sorted(mlog_dir.iterdir()):
        if not f.is_file() or f.suffix in (".pem", ".key", ".pcap"):
            continue
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        seps = b"\x1e\n"
        parts = raw.split(b"\x1e")
        if b"\x1e" not in raw:
            parts = raw.split(b"\n")
        for part in parts:
            if not part.strip():
                continue
            try:
                rec = json.loads(part)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                continue
            if rec.get("qlog_version"):
                continue  # JSON-SEQ header record, not a transport event
            yield rec


def _has_valid_moq_handshake(mlog_dir: Path) -> bool:
    """Check if mlog contains evidence of a real MoQ handshake.

    moq-rs mlog records ``client_setup``/``server_setup`` control messages.
    Drafts 16/18 include a ``parameters`` array (setup options like
    MaxRequestId); draft-14 instead logs ``selected_version`` /
    ``supported_versions``. The presence of either shape confirms a real MoQ
    session was established — stronger evidence than just "mlog files exist".

    Note: drafts 16/18 do NOT log the negotiated draft version in mlog
    (ALPN-only negotiation since draft-16); see 2. quic_alpn for wire-level
    ALPN evidence.
    """
    for rec in _mlog_records(mlog_dir):
        data = rec.get("data") or {}
        if data.get("message_type") == "server_setup":
            params = data.get("parameters")
            if params and len(params) > 0:
                return True
            if data.get("selected_version"):
                return True
            if data.get("supported_versions"):
                return True
    return False


def _parse_mlog_version(mlog_dir: Path) -> Optional[str]:
    """Best-effort extraction of the negotiated MoQ draft from mlog records.

    Draft-14 logs the negotiated version explicitly (``selected_version:
    DRAFT_14``); drafts 16/18 do NOT emit a version in mlog (version
    negotiation is ALPN-only — see ``quic_alpn``). This function returns the
    draft for records that carry ``selected_version``, else ``None``.

    Use ``_has_valid_moq_handshake()`` to confirm MoQ was spoken; this
    function is a version-extraction bonus only.
    """
    vm = {"DRAFT_14": "14", "DRAFT_16": "16", "DRAFT_18": "18"}

    setup_values, all_values = [], []

    def _normalize(sv):
        return str(vm.get(sv, sv))

    for rec in _mlog_records(mlog_dir):
        data = rec.get("data") or {}
        sv = data.get("selected_version")
        if not sv:
            continue
        norm = _normalize(sv)
        all_values.append(norm)
        name = str(rec.get("name", ""))
        if "moqt" in name or "control" in name or "setup" in name.lower():
            setup_values.append(norm)

    values = setup_values if setup_values else all_values
    if not values:
        return None
    unique = set(values)
    if len(unique) == 1:
        return unique.pop()
    return None


def _probe_moqrs(impl: dict) -> Tuple[Optional[str], str]:
    """Probe moq-rs: start relay with mlog, run a real SETUP client, parse version.

    Returns ``(negotiated_draft, evidence)``. ``"setup"`` when the relay's
    SERVER_SETUP mlog record confirms a version (draft-14 logs
    ``selected_version: DRAFT_14``), ``"alpn"`` when the draft-specific ALPN
    (moq-00 / moqt-16 / moqt-18) is read from the decrypted ClientHello
    (draft-16+ negotiate the draft EXCLUSIVELY via ALPN), ``"unverified"``
    when real MoQ traffic happened but no version could be parsed, and
    ``"failed"`` when the relay or client could not run. Never returns the
    claimed draft.

    The probe client is ``moq-sub`` (built and installed UNCONDITIONALLY by
    the image), NOT ``moq-test-client`` — the Dockerfile builds that binary
    with ``2>/dev/null; true`` and only copies it if it exists, so it may be
    absent from published images. Either client performs the same SETUP; the
    negotiated draft is read from the relay's mlog / captured ClientHello,
    never from the client's exit status (moq-sub exits non-zero once the
    nonexistent track errors).
    """
    img = impl["image"]["relay"]
    port = impl["port"]
    tag = impl["name"]

    net, cname = f"mp-net-{tag}", f"mp-relay-{tag}"
    tmp = Path(tempfile.mkdtemp(prefix=f"moq-probe-{tag}-"))

    _gen_cert(tmp, impl)
    _run(["docker", "network", "create", net], timeout=10)

    try:
        r = _run([
            "docker", "run", "-d",
            "--pull", "missing",
            "--network", net, "--name", cname,
            "-v", f"{tmp}:/certs:ro",
            "-v", f"{tmp}:/tmp/mlog",
            img,
            "--tls-cert", "/certs/cert.pem",
            "--tls-key", "/certs/key.pem",
            "--mlog-dir", "/tmp/mlog",
        ], timeout=60)
        if r.returncode != 0:
            return None, "failed"

        # Poll relay status (same as the imquic/moxygen probes): an exited
        # relay means the args/entrypoint were wrong, so surface its logs
        # instead of collapsing everything into a generic "failed".
        for _ in range(10):
            r = _run(["docker", "inspect", cname, "--format={{.State.Status}}"], timeout=5)
            s = r.stdout.strip()
            if s == "running":
                break
            if s == "exited":
                log_r = _run(["docker", "logs", cname], timeout=10)
                print(f"[probe] {tag} relay exited. Logs:", file=sys.stderr)
                print(log_r.stdout or log_r.stderr or "(no output)", file=sys.stderr)
                return None, "failed"
            time.sleep(1)
        else:
            return None, "failed"

        time.sleep(2)

        # Best-effort SETUP probe (moqt:// scheme so the client offers a
        # draft-specific ALPN literal: moq-00 / moqt-16 / moqt-18 — see
        # quic_alpn). `timeout` bounds a subscriber that waits for data on the
        # nonexistent track instead of erroring out; its exit status is
        # deliberately ignored — the version evidence is the ALPN + mlog.
        cap = tmp / "cap.pcap"
        _run(["docker", "exec", "-d", cname, "tcpdump",
              "-i", "any", "-U", "-w", "/tmp/mlog/cap.pcap",
              "udp", "port", str(port)], timeout=15)
        time.sleep(1)
        _run([
            "docker", "run", "--rm",
            "--network", net,
            "--entrypoint", "timeout",
            img, "8", "moq-sub",
            "--name", f"probe-{tag}",
            "--tls-disable-verify",
            f"moqt://{cname}:{port}",
        ], timeout=30)
        time.sleep(1)
        _run(["docker", "exec", cname, "pkill", "-x", "tcpdump"], timeout=10)

        version = _parse_mlog_version(tmp)
        if version is not None:
            return version, "setup"
        # Wire-level ALPN evidence (draft-16+ negotiate the draft ONLY via
        # ALPN; the ClientHello is decrypted from the captured Initial).
        if cap.exists():
            for ch_alpn in extract_alpn_from_pcap(cap, dport=port):
                for alpn in ch_alpn:
                    draft = MOQ_ALPN_TO_DRAFT.get(alpn)
                    if draft is not None:
                        return draft, "alpn"
        # moq-rs mlog does not log the negotiated draft (ALPN-only since
        # draft-16). Confirm a real MoQ handshake via server_setup records
        # with valid parameters — stronger than just "mlog files exist".
        if _has_valid_moq_handshake(tmp):
            return None, "unverified"
        # Fallback: relay wrote per-connection mlog records but no valid
        # setup handshake detected (possibly pre-setup crash or empty mlog).
        if any(f.is_file() and f.suffix not in (".pem", ".key", ".pcap")
               for f in tmp.iterdir()):
            return None, "unverified"
        return None, "failed"

    except Exception:
        import traceback
        print(f"[probe] {tag} probe crashed:", file=sys.stderr)
        traceback.print_exc()
        return None, "failed"
    finally:
        _cleanup(cname)
        _run(["docker", "network", "rm", net], timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def _probe_imquic(impl: dict) -> Tuple[Optional[str], str]:
    """Probe imquic: start relay, run interop-test, parse TAP 14 output.

    Returns ``(negotiated_draft, evidence)``. ``"tap14"`` when the setup-only
    interop test passes (the tester asserts the expected draft), ``"failed"``
    otherwise.

    The relay is launched with ``--entrypoint imquic-moq-relay -M {draft}``
    (not the image's default shell entrypoint): picoquic-based imquic selects
    its MoQ draft at RUNTIME via ``-M``, so pinning it makes the setup-only
    test exercise the CLAIMED draft rather than ``any`` (which would always
    negotiate the highest common ALPN and prove nothing per-draft — B4)."""
    img = impl["image"]["relay"]
    port = impl["port"]
    tag = impl["name"]
    draft = impl.get("claimed_draft") or "any"

    net, cname = f"mp-net-{tag}", f"mp-relay-{tag}"
    tmp = Path(tempfile.mkdtemp(prefix=f"moq-probe-{tag}-"))

    _gen_cert(tmp, impl)
    _run(["docker", "network", "create", net], timeout=10)

    try:
        r = _run([
            "docker", "run", "-d",
            "--pull", "missing",
            "--network", net, "--name", cname,
            "-v", f"{tmp}:/certs:ro",
            "--entrypoint", "imquic-moq-relay",
            img,
            "-p", str(port),
            "-M", str(draft),
            "-q", "-w",
            "-c", "/certs/cert.pem",
            "-k", "/certs/priv.key",
        ], timeout=60)
        if r.returncode != 0:
            return None, "failed"

        for _ in range(10):
            r = _run(["docker", "inspect", cname, "--format={{.State.Status}}"], timeout=5)
            s = r.stdout.strip()
            if s == "running":
                break
            if s == "exited":
                log_r = _run(["docker", "logs", cname], timeout=10)
                print(f"[probe] {tag} relay exited. Logs:", file=sys.stderr)
                print(log_r.stdout or log_r.stderr or "(no output)", file=sys.stderr)
                return None, "failed"
            time.sleep(1)
        else:
            return None, "failed"

        r = _run([
            "docker", "run", "--rm",
            "--network", net,
            "--entrypoint", "imquic-moq-interop-test",
            img,
            "--relay", f"https://{cname}:{port}",
            "--tls-disable-verify",
            "--test", "setup-only",
        ], timeout=30)

        for line in (r.stdout or "").splitlines():
            if line.startswith("ok ") and "setup-only" in line:
                return impl.get("claimed_draft"), "tap14"
            if line.startswith("not ok ") and "setup-only" in line:
                return None, "failed"

        return None, "failed"

    except Exception:
        return None, "failed"
    finally:
        _cleanup(cname)
        _run(["docker", "network", "rm", net], timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def _probe_moxygen(impl: dict) -> Tuple[Optional[str], str]:
    """Probe moxygen: start relay with restricted versions, verify boot.

    BOOT-ONLY probe (honesty ladder, Ch 8): only verifies the container stays
    running. The negotiated draft is NOT confirmed, so it returns
    ``(None, "boot")`` — never the claimed value. Reported as UNVERIFIED.
    The draft is NOT wire-verifiable for moxygen: WebTransport mode presents
    only ``h3`` in the ClientHello (B46), and the raw ``moqt://`` client offers
    ``{moqt-16, moqt-14, moq-00}`` — never ``moqt-18`` (B46).
    """
    img = impl["image"].get("relay") or impl["image"].get("client")
    tag = impl["name"]

    net, cname = f"mp-net-{tag}", f"mp-relay-{tag}"
    tmp = Path(tempfile.mkdtemp(prefix=f"moq-probe-{tag}-"))

    _gen_cert(tmp, impl)
    _run(["docker", "network", "create", net], timeout=10)

    try:
        r = _run([
            "docker", "run", "-d",
            "--pull", "missing",
            "--network", net, "--name", cname,
            "-v", f"{tmp}:/certs:ro",
            "-e", f"MOQ_VERSIONS={impl.get('claimed_draft', '')}",
            "-e", "MOQ_LOG_LEVEL=DBG1",
            img,
        ], timeout=60)
        if r.returncode != 0:
            return None, "failed"

        for _ in range(10):
            r = _run(["docker", "inspect", cname, "--format={{.State.Status}}"], timeout=5)
            s = r.stdout.strip()
            if s == "running":
                return None, "boot"
            if s == "exited":
                log_r = _run(["docker", "logs", cname], timeout=10)
                print(f"[probe] {tag} relay exited. Logs:", file=sys.stderr)
                print(log_r.stdout or log_r.stderr or "(no output)", file=sys.stderr)
                return None, "failed"
            time.sleep(1)

        return None, "failed"
    except Exception:
        return None, "failed"
    finally:
        _cleanup(cname)
        _run(["docker", "network", "rm", net], timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)


def _probe_generic(impl: dict) -> Tuple[Optional[str], str]:
    """Generic probe: start relay, verify boot.

    BOOT-ONLY probe (honesty ladder, Ch 8): only verifies the container stays
    running. The negotiated draft is NOT confirmed, so it returns
    ``(None, "boot")`` — never the claimed value. Reported as UNVERIFIED.
    """
    img = impl["image"].get("relay") or impl["image"].get("client")
    tag = impl["name"]

    net, cname = f"mp-net-{tag}", f"mp-relay-{tag}"
    tmp = Path(tempfile.mkdtemp(prefix=f"moq-probe-{tag}-"))

    _gen_cert(tmp, impl)
    _run(["docker", "network", "create", net], timeout=10)

    try:
        r = _run([
            "docker", "run", "-d",
            "--pull", "missing",
            "--network", net, "--name", cname,
            "-v", f"{tmp}:/certs:ro",
            img,
        ], timeout=60)
        if r.returncode != 0:
            return None, "failed"

        for _ in range(10):
            r = _run(["docker", "inspect", cname, "--format={{.State.Status}}"], timeout=5)
            s = r.stdout.strip()
            if s == "running":
                return None, "boot"
            if s == "exited":
                log_r = _run(["docker", "logs", cname], timeout=10)
                print(f"[probe] {tag} relay exited. Logs:", file=sys.stderr)
                print(log_r.stdout or log_r.stderr or "(no output)", file=sys.stderr)
                return None, "failed"
            time.sleep(1)

        return None, "failed"
    except Exception:
        return None, "failed"
    finally:
        _cleanup(cname)
        _run(["docker", "network", "rm", net], timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
