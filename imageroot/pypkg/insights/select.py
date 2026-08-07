#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Divide the line budget between modules, fairly."""

# Every module is guaranteed this many lines before any weighting applies.
# This is what actually fixes starvation: a crash-looping module can no
# longer consume the whole budget, because every other module's floor is
# reserved first.
MIN_SHARE = 20

# Deviating or security-carrying modules get this much of the remainder
# relative to a quiet one.
PRIORITY_WEIGHT = 3.0

# Lines are fetched at OVERFETCH times a module's share, then deduplicated
# down to that share's worth of distinct templates. Without this, "dedup
# before capping" is impossible: Loki applies the cap at query time, before
# the collector sees a line, so one repeated line would still consume the
# whole allocation.
OVERFETCH = 4
OVERFETCH_CEILING = 2000


def allocate(module_ids, max_lines, prioritised=()):
    """Return {module_id: share}. The total never exceeds max_lines."""
    modules = list(module_ids)
    if not modules:
        return {}

    count = len(modules)
    if count * MIN_SHARE >= max_lines:
        # More modules than floor space. Equal shares, floor unreachable.
        share = max(1, max_lines // count)
        return {m: share for m in modules}

    prioritised = set(prioritised)
    weights = {m: (PRIORITY_WEIGHT if m in prioritised else 1.0) for m in modules}
    total_weight = sum(weights.values())
    remainder = max_lines - count * MIN_SHARE

    return {m: MIN_SHARE + int(remainder * weights[m] / total_weight)
            for m in modules}


def fetch_limit(share):
    """How many raw lines to pull so dedup has something to work with."""
    return min(OVERFETCH_CEILING, max(share, share * OVERFETCH))
