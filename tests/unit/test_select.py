#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

from insights import select


class TestAllocate:
    def test_equal_shares_when_nothing_deviates(self):
        shares = select.allocate(["a", "b", "c", "d"], 500)
        assert len(set(shares.values())) == 1

    def test_total_never_exceeds_the_budget(self):
        for count in (1, 3, 7, 12, 24):
            modules = ["m%d" % i for i in range(count)]
            assert sum(select.allocate(modules, 500).values()) <= 500

    def test_every_module_gets_the_floor(self):
        # The whole point: a crash-looping module cannot starve the others.
        shares = select.allocate(["quiet", "noisy"], 500, prioritised=["noisy"])
        assert shares["quiet"] >= select.MIN_SHARE

    def test_deviating_modules_get_more(self):
        shares = select.allocate(["quiet", "noisy"], 500, prioritised=["noisy"])
        assert shares["noisy"] > shares["quiet"]

    def test_floor_is_abandoned_when_there_is_no_room(self):
        # 40 modules x 20 floor = 800 > 500. Equal shares instead, and the
        # budget still holds.
        modules = ["m%d" % i for i in range(40)]
        shares = select.allocate(modules, 500)
        assert sum(shares.values()) <= 500
        assert min(shares.values()) >= 1

    def test_no_modules(self):
        assert select.allocate([], 500) == {}

    def test_host_bucket_is_allocated_like_any_module(self):
        # Host-level logs carry no module_id label; the empty-string bucket
        # must not be silently skipped.
        shares = select.allocate(["", "traefik1"], 500)
        assert shares[""] >= select.MIN_SHARE


class TestFetchLimit:
    def test_overfetches_so_dedup_has_room(self):
        assert select.fetch_limit(100) == 100 * select.OVERFETCH

    def test_is_capped(self):
        assert select.fetch_limit(10000) == select.OVERFETCH_CEILING
