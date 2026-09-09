"""Structural topology descriptors for the MoQ testbed.

Each topology owns:
- the ordered list of roles
- which run-config key feeds each role
- the switch set and link wiring (which role's wire connects to which switch,
  and whose params a given wire carries)
- the default-impair policy and the link-param merge logic (moved from the
  runner)

Containernet uses an imperative API (addDocker/addSwitch/addLink), so these
are plain descriptors, NOT mininet Topo subclasses.
"""
from typing import Any, Dict, List, Set, Tuple


# Default clean link: fast, negligible delay, no loss.
CLEAN_LINK: Dict[str, Any] = {"bw": 1000, "delay": "1ms", "loss": 0}


class Topology:
    """Base class for structural topology descriptors."""

    name: str = ""

    def roles(self, network: Dict[str, Any]) -> List[str]:
        """Ordered list of host roles in this topology."""
        raise NotImplementedError

    def config_key(self, role: str) -> str:
        """Run-config key that feeds this role (e.g. 'relay_a', 'sub')."""
        return role

    def switch_ids(self) -> List[str]:
        """Ordered list of switch IDs to create."""
        raise NotImplementedError

    def links(self) -> List[Tuple[str, str, str]]:
        """Link triples: (node_a, node_b, param_role).

        param_role determines which role's impairment params apply to the wire.
        Use ``__clean__`` for always-clean wires (e.g. relay access links).
        Use ``__inter_relay__`` for the chain's inter-relay measurement link.
        """
        raise NotImplementedError

    def default_impaired_roles(self, network: Dict[str, Any]) -> Set[str]:
        """Roles impaired when ``network.devices`` is absent.

        Default: subscriber wire(s) only — the pub/relay wires stay clean.
        """
        return {"sub"}

    def link_params_for_role(self, role: str, network: Dict[str, Any]) -> Dict[str, Any]:
        """TCLink params for one role's wire.

        With ``network.devices`` (role -> {bw, delay, loss} override): listed
        roles get the top-level values merged with their override; unlisted
        roles get a clean link. Without it, only ``default_impaired_roles()``
        get the top-level values; everyone else is clean.
        """
        devices = network.get("devices")
        top_level = {
            "bw": network.get("bw", 100),
            "delay": network.get("delay", "10ms"),
            "loss": network.get("loss", 0),
        }
        if devices is not None:
            if role in devices:
                return {**top_level, **devices[role]}
            return dict(CLEAN_LINK)
        if role in self.default_impaired_roles(network):
            return top_level
        return dict(CLEAN_LINK)

    def client_roles(self) -> Set[str]:
        """Roles whose wire gets ``max_queue_size`` (pub/sub, not relays)."""
        return {"pub", "sub"}

    def relay_port_binding(self, role: str, base_port: int) -> int:
        """Host port binding for a relay role. Override for chain topology."""
        return base_port

    def config_keys(self, network: Dict[str, Any]) -> Dict[str, str]:
        """Mapping of role -> run-config key for all roles.

        Default: every role maps to itself. Override when config keys differ
        from role names (e.g. chain maps relay_a/relay_b to relay_a/relay_b).
        """
        return {r: r for r in self.roles(network)}
