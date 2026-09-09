"""ChainFanout Topology: Pub -> RelayA -> RelayB -> Sub1..SubN (3+N hosts).

Relay chain (two switches, inter-relay measurement link like chain.py)
feeding a multi-subscriber fan-out off the downstream relay (like
fanout.py). Tests relay-to-relay propagation AND per-subscriber delivery
in one run. Per-subscriber impl overrides (sub1..subN config keys) allow
mixed-impl fan-out; roles without an override fall back to "sub".
"""
from typing import Any, Dict, List, Set

from .base import Topology, CLEAN_LINK


class ChainFanoutTopology(Topology):
    name = "chainfanout"

    def roles(self, network: Dict[str, Any]) -> List[str]:
        n_subs = network.get("num_subscribers", 3)
        base = ["pub", "relay_a", "relay_b"] + [f"sub{i}" for i in range(1, n_subs + 1)]
        late_subs = network.get("late_sub_count", 0)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        if late_subs:
            base += [f"late_sub{i}" for i in range(1, late_subs + 1)]
        return base

    def config_key(self, role: str) -> str:
        """sub{i} resolves to its own config key so mixed-impl fan-out is
        possible; the runner falls back to "sub" when no override exists.
        late_sub{i} keeps the shared "sub" config."""
        if role.startswith("late_sub"):
            return "sub"
        return role

    def switch_ids(self) -> List[str]:
        return ["s1", "s2"]

    def links(self) -> List[tuple]:
        # s2 is shared by relay_b and all subs (as in chain.py the sub
        # hangs off the downstream relay's switch), so relay_b keeps a
        # single interface and no extra-IP fixup is needed.
        return [
            ("pub", "s1", "pub"),
            ("relay_a", "s1", "__clean__"),
            ("relay_a", "s2", "__inter_relay__"),
            ("relay_b", "s2", "relay_b"),
        ]

    def fanout_sub_links(self, network: Dict[str, Any]) -> List[tuple]:
        """Subscriber wires off the downstream relay's switch (s2). Reuses
        the runner's fanout_sub_links hook so no runner link-code changes
        are needed."""
        n_subs = network.get("num_subscribers", 3)
        late_subs = network.get("late_sub_count", 0)
        links = [(f"sub{i}", "s2", f"sub{i}") for i in range(1, n_subs + 1)]
        if late_subs > 0:
            links += [(f"late_sub{i}", "s2", f"late_sub{i}") for i in range(1, late_subs + 1)]
        return links

    def extra_links(self, network: Dict[str, Any]) -> List[tuple]:
        """Late-join subscribers from an explicit late_joins list. Only fires
        when late_sub_count is unset — otherwise fanout_sub_links() already
        wired those roles and a duplicate link would fail."""
        late_subs = network.get("late_sub_count", 0)
        if late_subs:
            return []
        if network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        if late_subs:
            return [(f"late_sub{i}", "s2", f"late_sub{i}") for i in range(1, late_subs + 1)]
        return []

    def default_impaired_roles(self, network: Dict[str, Any]) -> Set[str]:
        n_subs = network.get("num_subscribers", 3)
        late_subs = network.get("late_sub_count", 0)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        roles = {f"sub{i}" for i in range(1, n_subs + 1)}
        if late_subs:
            roles |= {f"late_sub{i}" for i in range(1, late_subs + 1)}
        return roles

    def link_params_for_role(self, role: str, network: Dict[str, Any]) -> Dict[str, Any]:
        if role == "__clean__":
            return dict(CLEAN_LINK)
        if role == "__inter_relay__":
            return self.inter_relay_link_params(network)
        return super().link_params_for_role(role, network)

    def inter_relay_link_params(self, network: Dict[str, Any]) -> Dict[str, Any]:
        """Same contract as chain.py: relay_delay on a clean link unless
        devices.relay_a overrides."""
        devices = network.get("devices") or {}
        if "relay_a" in devices:
            return self.link_params_for_role("relay_a", network)
        return {**CLEAN_LINK,
                "delay": network.get("relay_delay", "20ms")}

    def client_roles(self) -> Set[str]:
        return {"pub"} | {f"sub{i}" for i in range(1, 100)} | {f"late_sub{i}" for i in range(1, 100)}

    def relay_port_binding(self, role: str, base_port: int) -> int:
        if role == "relay_b":
            return base_port + 1
        return base_port

    def config_keys(self, network: Dict[str, Any]) -> Dict[str, str]:
        n_subs = network.get("num_subscribers", 3)
        late_subs = network.get("late_sub_count", 0)
        if not late_subs and network.get("late_joins"):
            late_subs = len(network.get("late_joins") or [])
        keys = {"pub": "pub", "relay_a": "relay_a", "relay_b": "relay_b"}
        for i in range(1, n_subs + 1):
            keys[f"sub{i}"] = f"sub{i}"
        for i in range(1, late_subs + 1):
            keys[f"late_sub{i}"] = "sub"
        return keys
