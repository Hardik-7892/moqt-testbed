"""Chain Topology: Pub -> RelayA -> RelayB -> Sub (4 hosts, 2 switches).

RelayA and RelayB are connected by a link with configurable impairments.
This tests relay-to-relay interop across implementations.
"""
from typing import Any, Dict, List, Set

from .base import Topology, CLEAN_LINK


class ChainTopology(Topology):
    name = "chain"

    def roles(self, network: Dict[str, Any]) -> List[str]:
        base = ["pub", "relay_a", "relay_b", "sub"]
        # D6 late-join: chain can also have late_sub* for late-join tests
        # (see B39c fix). Reads late_sub_count from network (testplans/join-leave-dynamics.yaml)
        late_subs = network.get("late_sub_count", 0)
        # Also support explicit late_joins list (per-sub delay entries)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        if not late_subs and network.get("late_join_delay_s"):
            # fallback for legacy configs that set delay without count
            pass
        if late_subs:
            base += [f"late_sub{i}" for i in range(1, late_subs + 1)]
        return base

    def config_key(self, role: str) -> str:
        if role.startswith("late_sub"):
            return "sub"
        return role

    def switch_ids(self) -> List[str]:
        return ["s1", "s2"]

    def links(self) -> List[tuple]:
        return [
            ("pub", "s1", "pub"),
            ("relay_a", "s1", "__clean__"),
            ("relay_a", "s2", "__inter_relay__"),
            ("relay_b", "s2", "relay_b"),
            ("sub", "s2", "sub"),
        ]

    def extra_links(self, network: Dict[str, Any]) -> List[tuple]:
        """Additional links for dynamic late_sub* roles (late-join tests).
        Called by runner after links()."""
        late_subs = network.get("late_sub_count", 0)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        if late_subs:
            return [(f"late_sub{i}", "s2", f"late_sub{i}") for i in range(1, late_subs + 1)]
        return []

    def default_impaired_roles(self, network: Dict[str, Any]) -> Set[str]:
        base: Set[str] = {"sub"}
        late_subs = network.get("late_sub_count", 0)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        if late_subs:
            base = set(base) | {f"late_sub{i}" for i in range(1, late_subs + 1)}
        return base

    def config_keys(self, network: Dict[str, Any]) -> Dict[str, str]:
        mapping = {r: r for r in self.roles(network)}
        for role in list(mapping.keys()):
            if role.startswith("late_sub"):
                mapping[role] = "sub"
        return mapping

    def link_params_for_role(self, role: str, network: Dict[str, Any]) -> Dict[str, Any]:
        if role == "__clean__":
            return dict(CLEAN_LINK)
        if role == "__inter_relay__":
            return self.inter_relay_link_params(network)
        return super().link_params_for_role(role, network)

    def inter_relay_link_params(self, network: Dict[str, Any]) -> Dict[str, Any]:
        """Params for the chain's inter-relay wire (ra->s2), the measurement
        link: it carries relay_delay on an otherwise clean link UNLESS relay_a
        is explicitly listed in network.devices (then its merged params apply).
        """
        devices = network.get("devices") or {}
        if "relay_a" in devices:
            return self.link_params_for_role("relay_a", network)
        return {**CLEAN_LINK,
                "delay": network.get("relay_delay", "20ms")}

    def client_roles(self) -> Set[str]:
        return {"pub", "sub"} | {f"late_sub{i}" for i in range(1, 100)}

    def relay_port_binding(self, role: str, base_port: int) -> int:
        if role == "relay_b":
            return base_port + 1
        return base_port
