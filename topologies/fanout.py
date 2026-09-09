"""Fan-out Topology: Pub -> Relay -> Sub1, Sub2, ... SubN (2+N hosts).

Tests multi-subscriber scenarios including late-join behavior.
Number of subscribers is configurable.
"""
from typing import Any, Dict, List, Set

from .base import Topology


class FanoutTopology(Topology):
    name = "fanout"

    def roles(self, network: Dict[str, Any]) -> List[str]:
        n_subs = network.get("num_subscribers", 4)
        late_subs = network.get("late_sub_count", 0)
        base = ["pub", "relay"] + [f"sub{i}" for i in range(1, n_subs + 1)]
        if late_subs > 0:
            base += [f"late_sub{i}" for i in range(1, late_subs + 1)]
        return base

    def config_key(self, role: str) -> str:
        """sub{i} resolves to its own config key so mixed-impl fan-out is
        possible (the runner falls back to "sub" when no override exists);
        late_sub{i} keeps the shared "sub" config."""
        if role.startswith("late_sub"):
            return "sub"
        if role.startswith("sub"):
            return role
        return role

    def switch_ids(self) -> List[str]:
        return ["s1"]

    def links(self) -> List[tuple]:
        return [
            ("pub", "s1", "pub"),
            ("relay", "s1", "relay"),
        ]

    def fanout_sub_links(self, network: Dict[str, Any]) -> List[tuple]:
        """Sub links are generated separately so the runner can create
        per-sub containers in a loop."""
        n_subs = network.get("num_subscribers", 4)
        late_subs = network.get("late_sub_count", 0)
        links = [(f"sub{i}", "s1", f"sub{i}") for i in range(1, n_subs + 1)]
        if late_subs > 0:
            links += [(f"late_sub{i}", "s1", f"late_sub{i}") for i in range(1, late_subs + 1)]
        return links

    def default_impaired_roles(self, network: Dict[str, Any]) -> Set[str]:
        n_subs = network.get("num_subscribers", 4)
        late_subs = network.get("late_sub_count", 0)
        roles = {f"sub{i}" for i in range(1, n_subs + 1)}
        if late_subs > 0:
            roles |= {f"late_sub{i}" for i in range(1, late_subs + 1)}
        return roles

    def client_roles(self) -> Set[str]:
        return {"pub"} | {f"sub{i}" for i in range(1, 100)} | {f"late_sub{i}" for i in range(1, 100)}

    def config_keys(self, network: Dict[str, Any]) -> Dict[str, str]:
        n_subs = network.get("num_subscribers", 4)
        late_subs = network.get("late_sub_count", 0)
        keys = {"pub": "pub", "relay": "relay"}
        for i in range(1, n_subs + 1):
            keys[f"sub{i}"] = f"sub{i}"
        for i in range(1, late_subs + 1):
            keys[f"late_sub{i}"] = "sub"
        return keys
