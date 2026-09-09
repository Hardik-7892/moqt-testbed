"""B36 guard: Docker-tag family consistency across citable plans.

B36 (found-bugs.md): Hub tags (0hardikpandey/moq-rs-*:18) held a stale
pre-repin image while local tags (moq-rs/*:18) were current; mixed revisions
are wire-incompatible, so handshakes died with 0 bytes — batch
run_20260906_224353 failed all 6 MoQ rows on exactly this skew.

Docker-free: asserts plan YAMLs never mix tag families within one plan per
impl (the mistake that hides skew), and that any plan using Hub tags carries
the VM re-tag instruction in its description (the operational half of the
fix, which no code can check — `docker inspect` only exists on the VM).
"""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TESTPLANS = Path(__file__).resolve().parent.parent / "testplans"
ROLES = ("pub", "relay", "relay_a", "relay_b", "sub",
         "sub1", "sub2", "sub3", "sub4", "sub5", "sub6", "sub7", "sub8")


def _load(name):
    with open(TESTPLANS / name) as f:
        return yaml.safe_load(f)


def _families(plan):
    fams = {}
    for run in plan.get("runs", []):
        for role in ROLES:
            cfg = run.get(role, {}) or {}
            tag = str(cfg.get("tag", ""))
            impl = str(cfg.get("impl", "?"))
            if tag and tag != "unknown":
                fam = tag.split("/")[0] if "/" in tag else "(bare)"
                fams.setdefault(impl, set()).add(fam)
    return fams


def test_citable_plans_single_tag_family_per_impl():
    plans = sorted(p.name for p in TESTPLANS.glob("*.yaml"))
    assert plans, "no citable plans found"
    for name in plans:
        for impl, fams in _families(_load(name)).items():
            assert len(fams) == 1, (
                f"{name}: impl '{impl}' mixes tag families {sorted(fams)} "
                f"(B36 skew risk — use one family per plan)")


def test_hub_tag_plans_carry_retag_instruction():
    # Narrowed to moq-rs Hub tags: lldash/imquic/moxygen Hub tags are built
    # directly under their Hub names (no local shadow tag to drift from),
    # but 0hardikpandey/moq-rs-*:18 shadows the local moq-rs/*:18 rebuilds —
    # that is the exact B36 skew pair.
    for name in sorted(p.name for p in TESTPLANS.glob("*.yaml")):
        plan = _load(name)
        uses_moqrs_hub = any("0hardikpandey/moq-rs-" in t
                             for run in plan.get("runs", [])
                             for role in ROLES
                             for t in [str((run.get(role, {}) or {}).get("tag", ""))])
        if uses_moqrs_hub:
            desc = str(plan.get("description", ""))
            assert "docker tag" in desc and "B36" in desc, (
                f"{name}: uses moq-rs Hub tags but description lacks the VM "
                f"re-tag instruction (B36)")


def test_moq_vs_lldash_moq_rows_expect_partial():
    # Batch run_20260906_232716: all 6 MoQ rows honestly partial (B25
    # ceiling), so the confusion matrix must expect partial, not pass.
    plan = _load("moq-vs-lldash.yaml")
    moq_rows = [r for r in plan["runs"]
                if str(r.get("id", "")).startswith("moq-")]
    assert len(moq_rows) == 6
    for run in moq_rows:
        assert run.get("expect") == "partial", (
            f"moq-vs-lldash/{run.get('id')}: MoQ row must expect partial")
