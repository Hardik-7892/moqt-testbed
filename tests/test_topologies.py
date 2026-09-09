"""Tests for topology descriptors and runner delegators."""
import pytest
from topologies import TOPOLOGIES, CLEAN_LINK
from topologies.chainfanout import ChainFanoutTopology
from topologies.basic import BasicTopology
from topologies.chain import ChainTopology
from topologies.fanout import FanoutTopology


# --- BasicTopology ---

class TestBasicTopology:
    def setup_method(self):
        self.topo = BasicTopology()
        self.net = {}

    def test_roles(self):
        assert self.topo.roles(self.net) == ["pub", "relay", "sub"]

    def test_switch_ids(self):
        assert self.topo.switch_ids() == ["s1"]

    def test_links(self):
        links = self.topo.links()
        assert len(links) == 3
        assert ("pub", "s1", "pub") in links
        assert ("relay", "s1", "relay") in links
        assert ("sub", "s1", "sub") in links

    def test_default_impaired_roles(self):
        assert self.topo.default_impaired_roles(self.net) == {"sub"}

    def test_link_params_clean(self):
        params = self.topo.link_params_for_role("relay", self.net)
        assert params == CLEAN_LINK

    def test_link_params_impaired_default(self):
        params = self.topo.link_params_for_role("sub", self.net)
        assert params["bw"] == 100
        assert params["delay"] == "10ms"
        assert params["loss"] == 0

    def test_link_params_with_devices(self):
        net = {"devices": {"pub": {"bw": 50}}}
        pub_params = self.topo.link_params_for_role("pub", net)
        assert pub_params["bw"] == 50
        sub_params = self.topo.link_params_for_role("sub", net)
        assert sub_params == CLEAN_LINK

    def test_client_roles(self):
        assert self.topo.client_roles() == {"pub", "sub"}

    def test_config_keys(self):
        assert self.topo.config_keys(self.net) == {"pub": "pub", "relay": "relay", "sub": "sub"}


# --- ChainTopology ---

class TestChainTopology:
    def setup_method(self):
        self.topo = ChainTopology()
        self.net = {}

    def test_roles(self):
        assert self.topo.roles(self.net) == ["pub", "relay_a", "relay_b", "sub"]

    def test_switch_ids(self):
        assert self.topo.switch_ids() == ["s1", "s2"]

    def test_links(self):
        links = self.topo.links()
        assert len(links) == 5
        assert ("pub", "s1", "pub") in links
        assert ("relay_a", "s1", "__clean__") in links
        assert ("relay_a", "s2", "__inter_relay__") in links
        assert ("relay_b", "s2", "relay_b") in links
        assert ("sub", "s2", "sub") in links

    def test_inter_relay_default(self):
        params = self.topo.inter_relay_link_params(self.net)
        assert params["delay"] == "20ms"
        assert params["bw"] == 1000

    def test_inter_relay_with_devices(self):
        net = {"devices": {"relay_a": {"delay": "50ms"}}}
        params = self.topo.inter_relay_link_params(net)
        assert params["delay"] == "50ms"

    def test_relay_port_binding(self):
        assert self.topo.relay_port_binding("relay_a", 4443) == 4443
        assert self.topo.relay_port_binding("relay_b", 4443) == 4444

    def test_clean_link_role(self):
        params = self.topo.link_params_for_role("__clean__", self.net)
        assert params == CLEAN_LINK


# --- FanoutTopology ---

class TestFanoutTopology:
    def setup_method(self):
        self.topo = FanoutTopology()
        self.net = {"num_subscribers": 3}

    def test_roles(self):
        roles = self.topo.roles(self.net)
        assert roles == ["pub", "relay", "sub1", "sub2", "sub3"]

    def test_roles_default(self):
        topo = FanoutTopology()
        roles = topo.roles({})
        assert len(roles) == 6
        assert "sub1" in roles
        assert "sub4" in roles

    def test_switch_ids(self):
        assert self.topo.switch_ids() == ["s1"]

    def test_links(self):
        links = self.topo.links()
        assert len(links) == 2
        assert ("pub", "s1", "pub") in links
        assert ("relay", "s1", "relay") in links

    def test_fanout_sub_links(self):
        sub_links = self.topo.fanout_sub_links(self.net)
        assert len(sub_links) == 3
        assert ("sub1", "s1", "sub1") in sub_links
        assert ("sub3", "s1", "sub3") in sub_links

    def test_default_impaired_roles(self):
        impaired = self.topo.default_impaired_roles(self.net)
        assert impaired == {"sub1", "sub2", "sub3"}

    def test_config_keys(self):
        keys = self.topo.config_keys(self.net)
        assert keys["pub"] == "pub"
        assert keys["relay"] == "relay"
        assert keys["sub1"] == "sub1"
        assert keys["sub3"] == "sub3"

    def test_config_key_singular(self):
        """The runner resolves images via singular config_key(role); sub{i}
        maps to its own key so mixed-impl fan-out is possible (the runner
        falls back to "sub" when no per-role override exists)."""
        assert self.topo.config_key("sub1") == "sub1"
        assert self.topo.config_key("sub3") == "sub3"
        assert self.topo.config_key("late_sub1") == "sub"
        assert self.topo.config_key("pub") == "pub"
        assert self.topo.config_key("relay") == "relay"


# --- ChainFanoutTopology ---

class TestChainFanoutTopology:
    def setup_method(self):
        self.topo = ChainFanoutTopology()
        self.net = {"num_subscribers": 3}

    def test_roles(self):
        roles = self.topo.roles(self.net)
        assert roles == ["pub", "relay_a", "relay_b", "sub1", "sub2", "sub3"]

    def test_roles_default(self):
        roles = ChainFanoutTopology().roles({})
        assert roles == ["pub", "relay_a", "relay_b", "sub1", "sub2", "sub3"]

    def test_roles_late_subs(self):
        roles = self.topo.roles({"num_subscribers": 2, "late_sub_count": 1})
        assert roles == ["pub", "relay_a", "relay_b", "sub1", "sub2", "late_sub1"]

    def test_switch_ids(self):
        assert self.topo.switch_ids() == ["s1", "s2"]

    def test_links(self):
        links = self.topo.links()
        assert ("pub", "s1", "pub") in links
        assert ("relay_a", "s1", "__clean__") in links
        assert ("relay_a", "s2", "__inter_relay__") in links
        assert ("relay_b", "s2", "relay_b") in links

    def test_fanout_sub_links_off_downstream_switch(self):
        sub_links = self.topo.fanout_sub_links(self.net)
        assert len(sub_links) == 3
        assert ("sub1", "s2", "sub1") in sub_links
        assert ("sub3", "s2", "sub3") in sub_links

    def test_no_duplicate_late_links(self):
        """fanout_sub_links and extra_links must never wire the same role
        twice (duplicate Mininet links fail the run)."""
        net = {"num_subscribers": 2, "late_sub_count": 1}
        seen = [n for n, _, _ in self.topo.fanout_sub_links(net)]
        seen += [n for n, _, _ in self.topo.extra_links(net)]
        assert len(seen) == len(set(seen))

    def test_inter_relay_honours_devices(self):
        params = self.topo.link_params_for_role("__inter_relay__", self.net)
        assert params["delay"] == "20ms"
        net = dict(self.net, relay_delay="50ms",
                   devices={"relay_a": {"loss": 2}})
        params = self.topo.link_params_for_role("__inter_relay__", net)
        assert params["loss"] == 2

    def test_default_impaired_roles(self):
        assert self.topo.default_impaired_roles(self.net) == {"sub1", "sub2", "sub3"}

    def test_relay_b_port_binding(self):
        assert self.topo.relay_port_binding("relay_b", 4443) == 4444
        assert self.topo.relay_port_binding("relay_a", 4443) == 4443

    def test_config_key_mixed_subs(self):
        assert self.topo.config_key("sub2") == "sub2"
        assert self.topo.config_key("late_sub1") == "sub"
        assert self.topo.config_key("relay_a") == "relay_a"


# --- Singular/plural config-key contract (runner vs descriptors) ---

class TestConfigKeyContract:
    """The runner creates each container with the image from config[
    topo.config_key(role)] (singular form); descriptors declare their
    mappings via config_keys(network) (plural form). Regression: fanout
    only implemented the plural form, so sub{i} resolved to config key
    "sub1" -> empty config -> image "unknown:latest" (404 at create)."""

    CASES = [
        (BasicTopology, {}),
        (ChainTopology, {}),
        (FanoutTopology, {"num_subscribers": 3}),
        (ChainFanoutTopology, {"num_subscribers": 3}),
    ]

    def test_singular_matches_plural_for_every_role(self):
        for cls, net in self.CASES:
            topo = cls()
            mapping = topo.config_keys(net)
            for role in topo.roles(net):
                assert role in mapping, (
                    f"{cls.__name__}: config_keys() missing role {role!r}")
                assert topo.config_key(role) == mapping[role], (
                    f"{cls.__name__}: singular config_key({role!r})="
                    f"{topo.config_key(role)!r} disagrees with "
                    f"config_keys()={mapping[role]!r}")

    def test_every_role_resolves_a_tag(self):
        """Simulate the runner's image lookup (per-role key with fallback
        to "sub"): no role may fall through to an empty config (the
        'unknown:latest' failure mode)."""
        run_configs = [
            {"pub": {"tag": "p"}, "relay": {"tag": "r"}, "sub": {"tag": "s"}},
            {"pub": {"tag": "p"}, "relay_a": {"tag": "ra"},
             "relay_b": {"tag": "rb"}, "sub": {"tag": "s"}},
            {"pub": {"tag": "p"}, "relay": {"tag": "r"}, "sub": {"tag": "s"}},
            {"pub": {"tag": "p"}, "relay_a": {"tag": "ra"},
             "relay_b": {"tag": "rb"}, "sub": {"tag": "s"}},
        ]
        for (cls, net), cfg in zip(self.CASES, run_configs):
            topo = cls()
            for role in topo.roles(net):
                impl_cfg = cfg.get(topo.config_key(role), {}) or {}
                if not impl_cfg.get("tag") and (
                        role.startswith("sub") or role.startswith("late_sub")):
                    impl_cfg = cfg.get("sub", {})
                assert impl_cfg.get("tag"), (
                    f"{cls.__name__}: role {role!r} would create a container "
                    f"with no image tag")

    def test_mixed_sub_override_resolves(self):
        """A per-role sub3 override wins; sub1/sub2 fall back to sub."""
        topo = FanoutTopology()
        cfg = {"pub": {"tag": "p"}, "relay": {"tag": "r"},
               "sub": {"tag": "s"}, "sub3": {"tag": "s3"}}
        resolved = {}
        for role in topo.roles({"num_subscribers": 3}):
            impl_cfg = cfg.get(topo.config_key(role), {}) or {}
            if not impl_cfg.get("tag") and role.startswith("sub"):
                impl_cfg = cfg.get("sub", {})
            resolved[role] = impl_cfg.get("tag")
        assert resolved == {"pub": "p", "relay": "r", "sub1": "s",
                            "sub2": "s", "sub3": "s3"}


# --- TOPOLOGIES registry ---

class TestRegistry:
    def test_all_present(self):
        assert "basic" in TOPOLOGIES
        assert "chain" in TOPOLOGIES
        assert "chainfanout" in TOPOLOGIES
        assert "fanout" in TOPOLOGIES

    def test_instantiation(self):
        for cls in TOPOLOGIES.values():
            topo = cls()
            assert hasattr(topo, "roles")
            assert hasattr(topo, "links")


# --- Runner delegators (import from runner without Docker) ---

class TestRunnerDelegators:
    """Test that runner methods correctly delegate to topology instances."""

    def test_basic_role_names(self):
        from topologies.basic import BasicTopology
        topo = BasicTopology()
        assert set(topo.roles({})) == {"pub", "relay", "sub"}

    def test_chain_role_names(self):
        from topologies.chain import ChainTopology
        topo = ChainTopology()
        assert set(topo.roles({})) == {"pub", "relay_a", "relay_b", "sub"}

    def test_fanout_role_names(self):
        from topologies.fanout import FanoutTopology
        topo = FanoutTopology()
        roles = set(topo.roles({"num_subscribers": 2}))
        assert roles == {"pub", "relay", "sub1", "sub2"}

    def test_link_params_matches_runner(self):
        """Verify topology link_params_for_role produces same results as the
        old runner methods for basic topology."""
        from topologies.basic import BasicTopology
        topo = BasicTopology()
        net = {"bw": 50, "delay": "5ms", "loss": 1}
        # sub gets impaired (default impaired role)
        sub = topo.link_params_for_role("sub", net)
        assert sub["bw"] == 50
        assert sub["delay"] == "5ms"
        assert sub["loss"] == 1
        # relay gets clean (not in default impaired roles)
        relay = topo.link_params_for_role("relay", net)
        assert relay == CLEAN_LINK
