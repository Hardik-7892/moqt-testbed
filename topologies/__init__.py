from .base import Topology, CLEAN_LINK
from .basic import BasicTopology
from .chain import ChainTopology
from .chainfanout import ChainFanoutTopology
from .fanout import FanoutTopology

TOPOLOGIES = {
    "basic": BasicTopology,
    "chain": ChainTopology,
    "chainfanout": ChainFanoutTopology,
    "fanout": FanoutTopology,
}

__all__ = [
    "Topology", "CLEAN_LINK",
    "BasicTopology", "ChainTopology", "ChainFanoutTopology", "FanoutTopology",
    "TOPOLOGIES",
]
