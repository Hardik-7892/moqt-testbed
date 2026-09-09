import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ============================================================================
# DEAD CODE (B8, see found-bugs.md) — commented out 2026-08-04.
# The runner builds networks imperatively in harness/runner.py
# (_create_basic_network / _create_chain_network / _create_fanout_network),
# NOT via topology.yaml + scenarios.yaml. Nothing imports this module anymore.
#
# FUTURE: re-enable if/when the config-driven topology path is actually wired
# into the runner. To re-enable: uncomment everything below, then restore the
# import in harness/runner.py.
# ============================================================================

# BASE_DIR = Path(__file__).parent.parent.resolve()
# REGISTRY_PATH = BASE_DIR / "registry.json"
# TOPOLOGY_PATH = BASE_DIR / "topology.yaml"
# SCENARIOS_PATH = BASE_DIR / "scenarios.yaml"
#
#
# class TopologyBuilder:
#     """Config-driven topology builder (topology.yaml + scenarios.yaml).
#
#     B8 (see found-bugs.md): DEAD CODE — never used by the runner. The runner
#     builds networks imperatively in runner.py (_create_basic_network etc.).
#     Keeping for reference only.
#     """
#
#     def __init__(self, topology_path: Optional[Path] = None,
#                  registry_path: Optional[Path] = None,
#                  scenarios_path: Optional[Path] = None):
#         self.topology_path = topology_path or TOPOLOGY_PATH
#         self.registry_path = registry_path or REGISTRY_PATH
#         self.scenarios_path = scenarios_path or SCENARIOS_PATH
#
#         self.registry = self._load_json(self.registry_path)
#         self.impls = {i["name"]: i for i in self.registry["implementations"]}
#         self.scenarios = self._load_yaml(self.scenarios_path).get("profiles", {})
#
#     def _load_json(self, path: Path) -> dict:
#         with open(path) as f:
#             return json.load(f)
#
#     def _load_yaml(self, path: Path) -> dict:
#         with open(path) as f:
#             return yaml.safe_load(f) or {}
#
#     def load_topology(self, path: Optional[Path] = None) -> dict:
#         path = path or self.topology_path
#         return self._load_yaml(path)
#
#     def get_impl_config(self, impl_name: str) -> dict:
#         impl = self.impls.get(impl_name)
#         if not impl:
#             raise ValueError(f"Implementation '{impl_name}' not found in registry")
#         return impl
#
#     def get_scenario(self, name: str) -> dict:
#         scenario = self.scenarios.get(name)
#         if not scenario:
#             raise ValueError(f"Scenario '{name}' not found in scenarios.yaml")
#         return scenario
#
#     def resolve_network_params(self, topology: dict) -> Dict[str, Any]:
#         defaults = {"bw": 100, "delay": "10ms", "loss": 0, "max_queue_size": 1000}
#         for link in topology.get("links", []):
#             impairment_name = link.get("impairment", "clean")
#             profile = self.scenarios.get(impairment_name, {})
#             link["params"] = {**defaults, **profile}
#         return topology
