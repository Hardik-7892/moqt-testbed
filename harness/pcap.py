#!/usr/bin/env python3
"""PCAP analysis for wire-level metrics (I13).

Uses tshark to extract packet counts, bytes, RTT, and QUIC metrics from pcaps.
With SSLKEYLOGFILE, can decrypt QUIC and extract MoQ-level information.
"""
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def tshark_available() -> bool:
    """Check if tshark is installed."""
    try:
        subprocess.run(["tshark", "-v"], capture_output=True, timeout=5, check=False)
        return True
    except FileNotFoundError:
        return False


def analyze_pcap(pcap_path: Path, sslkeylog_path: Optional[Path] = None) -> Dict[str, Any]:
    """Run tshark on a pcap and extract wire-level metrics.

    Returns dict with:
    - total_packets
    - total_bytes
    - quic_packets
    - quic_bytes
    - avg_packet_size
    - rtt_estimate_ms (from QUIC)
    - packet_loss_estimate (from QUIC ack frames)
    - decryption_success (bool)
    - error (str if failed)
    """
    if not tshark_available():
        return {"error": "tshark not installed"}

    if not pcap_path.exists():
        return {"error": f"pcap not found: {pcap_path}"}

    # Build tshark command
    cmd = [
        "tshark", "-r", str(pcap_path),
        "-T", "json",
        "-Y", "quic",  # Only QUIC packets
    ]

    if sslkeylog_path and sslkeylog_path.exists():
        cmd.extend(["-o", f"tls.keylog_file:{sslkeylog_path}"])

    # AppArmor/DAC (see found-bugs.md): tshark on Ubuntu is confined and may be
    # unable to read pcaps under /mnt/... even as root ("You don't have
    # permission to read the file"). Fall back to analyzing a copy staged under
    # a fresh /tmp dir, which the tshark profile allows.
    tmpdir: Optional[str] = None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if (result.returncode != 0 and "permission" in result.stderr.lower()):
            import shutil
            import tempfile
            tmpdir = tempfile.mkdtemp(prefix="moq-pcap-")
            target = Path(tmpdir) / pcap_path.name
            shutil.copy2(pcap_path, target)
            cmd = ["tshark", "-r", str(target), "-T", "json", "-Y", "quic"]
            if sslkeylog_path and sslkeylog_path.exists():
                cmd.extend(["-o", f"tls.keylog_file:{sslkeylog_path}"])
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=60)
        if result.returncode != 0:
            return {"error": f"tshark failed: {result.stderr[:200]}"}
        packets = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"error": "tshark timeout"}
    except json.JSONDecodeError:
        return {"error": "tshark output not valid JSON"}
    except Exception as e:
        return {"error": f"tshark error: {e}"}
    finally:
        if tmpdir is not None:
            import shutil as _shutil
            _shutil.rmtree(tmpdir, ignore_errors=True)

    # Analyze packets
    total_pkts = 0
    total_bytes = 0
    quic_pkts = 0
    quic_bytes = 0
    rtt_samples: List[float] = []

    for pkt in packets:
        total_pkts += 1
        layers = pkt.get("_source", {}).get("layers", {})
        frame = layers.get("frame", {})
        if isinstance(frame, list):
            frame = frame[0]
        # Frame length
        frame_len = frame.get("frame.len")
        if frame_len:
            try:
                total_bytes += int(frame_len)
            except (ValueError, TypeError):
                pass

        # QUIC layer
        quic = layers.get("quic", {})
        if isinstance(quic, list):
            quic = quic[0]
        if quic:
            quic_pkts += 1
            quic_len = quic.get("quic.packet_length")
            if quic_len:
                try:
                    quic_bytes += int(quic_len)
                except (ValueError, TypeError):
                    pass
            # RTT from QUIC ACK frames
            ack = quic.get("quic.ack", {})
            if isinstance(ack, list):
                ack = ack[0]
            if ack:
                rtt_str = ack.get("quic.ack.rtt")
                if rtt_str:
                    try:
                        rtt_samples.append(float(rtt_str) * 1000)  # Convert to ms
                    except (ValueError, TypeError):
                        pass

    return {
        "total_packets": total_pkts,
        "total_bytes": total_bytes,
        "quic_packets": quic_pkts,
        "quic_bytes": quic_bytes,
        "avg_packet_size": total_bytes / total_pkts if total_pkts else 0,
        "avg_quic_packet_size": quic_bytes / quic_pkts if quic_pkts else 0,
        "rtt_estimate_ms": rtt_samples[-1] if rtt_samples else None,
        "rtt_samples": rtt_samples,
        "rtt_min_ms": min(rtt_samples) if rtt_samples else None,
        "rtt_max_ms": max(rtt_samples) if rtt_samples else None,
        # Only report success when ACK-frame decryption actually produced RTT
        # samples (and thus evidence of 1RTT decryption). Note (B42): on this
        # tshark 4.6.4 build the quic.ack.rtt pseudo-field never materializes
        # for either picoquic's or quinn's keylogs ("Secrets are not
        # available"), so this stays False there.
        "decryption_success": bool(rtt_samples),
    }


def analyze_run_pcaps(run_dir: Path, sslkeylog_path: Optional[Path] = None) -> Dict[str, Any]:
    """Analyze all pcaps in a run directory.

    Returns per-host metrics and aggregate.
    """
    pcap_dir = run_dir / "pcaps"
    if not pcap_dir.exists():
        return {"error": "pcaps directory not found"}

    hosts = {}
    for pcap in pcap_dir.glob("*.pcap"):
        host = pcap.stem
        hosts[host] = analyze_pcap(pcap, sslkeylog_path)

    # Aggregate
    total_pkts = sum(h.get("total_packets", 0) for h in hosts.values())
    total_bytes = sum(h.get("total_bytes", 0) for h in hosts.values())
    quic_pkts = sum(h.get("quic_packets", 0) for h in hosts.values())
    quic_bytes = sum(h.get("quic_bytes", 0) for h in hosts.values())
    all_rtt = []
    for h in hosts.values():
        if h.get("rtt_samples"):
            all_rtt.extend(h["rtt_samples"])

    return {
        "per_host": hosts,
        "aggregate": {
            "total_packets": total_pkts,
            "total_bytes": total_bytes,
            "quic_packets": quic_pkts,
            "quic_bytes": quic_bytes,
            "rtt_estimate_ms": all_rtt[-1] if all_rtt else None,
            "rtt_min_ms": min(all_rtt) if all_rtt else None,
            "rtt_max_ms": max(all_rtt) if all_rtt else None,
        }
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python harness/pcap.py <run_dir> [sslkeylog_path]")
        sys.exit(1)
    run_dir = Path(sys.argv[1])
    sslkeylog = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    result = analyze_run_pcaps(run_dir, sslkeylog)
    print(json.dumps(result, indent=2))