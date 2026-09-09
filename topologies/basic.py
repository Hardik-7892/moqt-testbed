"""Basic Topology: Pub -> Relay -> Sub (3 hosts, 1 switch).

Network impairments applied symmetrically on pub and sub access links.
Relay is on a fast link.
"""
from typing import Any, Dict, List, Set

from .base import Topology


class BasicTopology(Topology):
    name = "basic"

    def roles(self, network: Dict[str, Any]) -> List[str]:
        return ["pub", "relay", "sub"]

    def switch_ids(self) -> List[str]:
        return ["s1"]

    def links(self) -> List[tuple]:
        return [
            ("pub", "s1", "pub"),
            ("relay", "s1", "relay"),
            ("sub", "s1", "sub"),
        ]
