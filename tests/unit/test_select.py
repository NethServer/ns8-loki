#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for allocate() and module_family() in insights-collector."""
import pytest


# --------------------------------------------------------------------------
# allocate()
# --------------------------------------------------------------------------

def test_allocate_empty_input(collector):
    assert collector.allocate([], 1000) == {}


def test_allocate_total_never_exceeds_max_lines(collector):
    modules = ["a", "b", "c", "d", "e"]
    for max_lines in (10, 50, 100, 500, 1000, 5000):
        shares = collector.allocate(modules, max_lines)
        assert sum(shares.values()) <= max_lines


def test_allocate_every_module_gets_at_least_min_share_when_there_is_room(collector):
    modules = ["a", "b", "c"]
    shares = collector.allocate(modules, 1000)
    for module_id in modules:
        assert shares[module_id] >= collector.MIN_SHARE


def test_allocate_prioritised_modules_get_more(collector):
    modules = ["a", "b", "c"]
    shares = collector.allocate(modules, 1000, prioritised=("a",))
    assert shares["a"] > shares["b"]
    assert shares["a"] > shares["c"]
    assert shares["b"] == shares["c"]


def test_allocate_more_modules_than_floor_space_gives_equal_shares(collector):
    modules = ["m{0}".format(i) for i in range(20)]
    max_lines = 100  # 20 * MIN_SHARE (20*20=400) >= 100
    shares = collector.allocate(modules, max_lines)
    values = set(shares.values())
    assert len(values) == 1
    assert sum(shares.values()) <= max_lines


def test_allocate_more_modules_than_floor_space_still_prioritised_agnostic(collector):
    """In the equal-shares branch there is no room to weight -- prioritised
    modules get the same share as everyone else."""
    modules = ["m{0}".format(i) for i in range(20)]
    shares = collector.allocate(modules, 100, prioritised=("m0",))
    assert len(set(shares.values())) == 1


def test_allocate_equal_shares_at_least_one(collector):
    modules = ["a", "b", "c"]
    shares = collector.allocate(modules, 1)  # far below floor space
    for value in shares.values():
        assert value >= 1


# --------------------------------------------------------------------------
# allocate() over module families rather than instances. The 2026-09-02
# dump: 185 distinct module_ids across 16 families on one hosting node.
# --------------------------------------------------------------------------

def _fleet_instances():
    """185 instance ids across 16 families, shaped like the real dump."""
    sizes = {"nethvoice": 82, "openldap": 71, "traefik": 7, "ldapproxy": 7,
             "nethvoice-proxy": 6, "loki": 2}
    instances = ["{0}{1}".format(family, n)
                 for family, count in sizes.items()
                 for n in range(1, count + 1)]
    # Nine singleton families, each a distinct image name, plus the host
    # bucket -- ten more families, ten more instances.
    # Letter-suffixed so the family name itself carries no digits: a
    # "single0" image name would strip back to "single" like every other.
    instances += ["single{0}1".format(chr(ord("a") + i)) for i in range(9)]
    instances.append("")  # the host bucket
    assert len(instances) == 185
    return instances


def test_allocate_over_families_reaches_the_floor(collector):
    instances = _fleet_instances()
    families = sorted({collector.module_family(m) for m in instances})
    assert len(families) == 16

    shares = collector.allocate(families, collector.DEFAULT_MAX_LINES)
    assert sum(shares.values()) <= collector.DEFAULT_MAX_LINES
    for family, share in shares.items():
        assert share >= collector.MIN_SHARE, family


def test_allocate_over_families_does_not_starve_the_host_bucket(collector):
    instances = _fleet_instances()
    families = sorted({collector.module_family(m) for m in instances})
    shares = collector.allocate(families, collector.DEFAULT_MAX_LINES)
    assert shares[collector.HOST_BUCKET] >= collector.MIN_SHARE


def test_allocate_over_instances_would_starve_everything(collector):
    """Why TemplateStore keys on the family: the same budget handed the
    185 instance ids cannot reach the floor for any of them."""
    instances = _fleet_instances()
    shares = collector.allocate(instances, collector.DEFAULT_MAX_LINES)
    assert max(shares.values()) < collector.MIN_SHARE


def test_allocate_degrade_path_still_reachable_with_families(collector):
    """Families alone can still exceed the floor space -- the equal-share
    branch is not dead code once the caller passes families."""
    families = ["fam{0}".format(i) for i in range(40)]
    shares = collector.allocate(families, collector.DEFAULT_MAX_LINES)
    assert len(set(shares.values())) == 1
    assert sum(shares.values()) <= collector.DEFAULT_MAX_LINES


# --------------------------------------------------------------------------
# module_family()
# --------------------------------------------------------------------------

@pytest.mark.parametrize("module_id,family", [
    ("nethvoice5", "nethvoice"),
    ("nethvoice39", "nethvoice"),
    ("nethvoice-proxy4", "nethvoice-proxy"),
    ("crowdsec1", "crowdsec"),
    ("", ""),
    ("loki", "loki"),
    ("123", "123"),
])
def test_module_family(collector, module_id, family):
    assert collector.module_family(module_id) == family


def test_module_family_is_idempotent(collector):
    for module_id in ["nethvoice5", "nethvoice-proxy4", "", "123", "loki"]:
        once = collector.module_family(module_id)
        assert collector.module_family(once) == once
