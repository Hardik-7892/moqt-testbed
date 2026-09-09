import subprocess
from typing import Any, Dict


# ============================================================================
# DEAD CODE (B8, see found-bugs.md) — commented out 2026-08-04.
# The runner applies impairments via Containernet TCLink params instead
# (harness/runner.py _create_basic_network). Nothing imports this module anymore.
#
# FUTURE: re-enable if/when the config-driven topology path (topology.yaml +
# scenarios.yaml) is actually wired into the runner. To re-enable: uncomment
# everything below, then restore the import in harness/runner.py.
# ============================================================================

# class ScenarioApplier:
#     """Applies tc/netem impairments to a Containernet host interface.
#
#     B8 (see found-bugs.md): DEAD CODE — never called by the runner. The runner
#     applies impairments via Containernet TCLink params instead (runner.py
#     _create_basic_network). Keeping for reference only.
#     """
#
#     TC = "tc"
#
#     def _qdisc_reset(self, iface: str, host) -> None:
#         host.cmd(f"{self.TC} qdisc del dev {iface} root 2>/dev/null || true")
#
#     def _qdisc_set_netem(self, iface: str, host, loss: float = 0,
#                          delay: str = "0ms") -> None:
#         if loss > 0 or delay != "0ms":
#             netem_args = f"loss {loss}%" if loss > 0 else ""
#             if delay != "0ms":
#                 netem_args = f"delay {delay}" + (f" {netem_args}" if netem_args else "")
#             host.cmd(f"{self.TC} qdisc add dev {iface} root netem {netem_args}")
#
#     def _qdisc_set_tbf(self, iface: str, host, bw: int) -> None:
#         if bw > 0:
#             host.cmd(f"{self.TC} qdisc add dev {iface} root tbf rate {bw}mbit "
#                      f"burst 32kbit latency 400ms")
#
#     def apply(self, iface: str, host, params: Dict[str, Any]) -> None:
#         self._qdisc_reset(iface, host)
#         loss = params.get("loss", 0)
#         delay = params.get("delay", "0ms")
#         bw = params.get("bw", 100)
#         if loss > 0 or delay != "0ms":
#             self._qdisc_set_netem(iface, host, loss, delay)
#         if bw < 1000:
#             self._qdisc_set_tbf(iface, host, bw)
#
#     def clear(self, iface: str, host) -> None:
#         self._qdisc_reset(iface, host)
