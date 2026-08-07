#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Turn collected lines into the wire bundle."""

import collections
import re

from . import select
from .masking import MASKING_VERSION, mask
from .scrub import sanitize_line

SCHEMA_VERSION = 1

# The identifier is carried in the rendered line; the priority prefix is
# parsed back out so templates can be grouped by it.
PRIORITY_RE = re.compile(r'^<(\d+)>')


def group_templates(lines, module_id, share):
    """Deduplicate raw lines into counted templates.

    `lines` is [(ts_ms, text, category)]. Returns (templates, kept, fetched).
    Templates are emitted most-frequent-first and truncated to `share`, so a
    module's budget buys distinct events rather than repetitions of one.
    """
    groups = collections.OrderedDict()
    for ts, raw, category in lines:
        clean = sanitize_line(raw)
        template = mask(clean)
        match = PRIORITY_RE.match(clean)
        priority = int(match.group(1)) if match else 6
        key = (template, priority, category)
        entry = groups.get(key)
        if entry is None:
            groups[key] = {
                "template": template, "count": 1,
                "module_id": module_id, "priority": priority,
                "category": category,
                "first_seen": ts, "last_seen": ts,
                "samples": [clean],
            }
        else:
            entry["count"] += 1
            entry["first_seen"] = min(entry["first_seen"], ts)
            entry["last_seen"] = max(entry["last_seen"], ts)
            # Keep the first and last raw line only; the server caps at 2.
            if len(entry["samples"]) == 1:
                entry["samples"].append(clean)
            else:
                entry["samples"][1] = clean

    ordered = sorted(groups.values(), key=lambda t: (-t["count"], t["template"]))
    kept = ordered[:share]
    for entry in kept:
        if not entry.get("category"):
            entry.pop("category", None)
    return kept, sum(t["count"] for t in kept), len(lines)


def sample_ends(forward, backward, limit):
    """Merge a forward and a backward page, keeping both ends of the window.

    A pure first-N page lets an early burst hide a late-developing incident.
    """
    seen = set()
    merged = []
    for row in list(forward) + list(backward):
        key = (row[0], row[1])
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    merged.sort()
    if len(merged) <= limit:
        return merged
    half = limit // 2
    return merged[:half] + merged[-(limit - half):]


def build(system_id, collector_version, window, digest_rows, templates, budget):
    """Assemble the wire payload."""
    return {
        "schema_version": SCHEMA_VERSION,
        "system_id": system_id,
        "collector_version": collector_version,
        "masking_version": MASKING_VERSION,
        "window": {"start": window[0], "end": window[1]},
        "digest": digest_rows,
        "templates": templates,
        "budget": budget,
    }
