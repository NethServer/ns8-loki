#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for cluster_templates() and the flush() pipeline in insights-collector."""
import random

import pytest


def _entry(template, count=1, module_id="mod1", priority=3, category="metrics",
          first_seen=100, last_seen=100, samples=None):
    return {
        "template": template,
        "count": count,
        "module_id": module_id,
        "priority": priority,
        "category": category,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "samples": samples if samples is not None else [template],
    }


# --------------------------------------------------------------------------
# cluster_templates()
# --------------------------------------------------------------------------

DELETING_OBSOLETE_BLOCK = [
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=eu duration=5s'),
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=us duration=7s'),
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=ap duration=9s'),
]

WRITE_BLOCK = [
    _entry('<3> [prometheus] msg="write block" ooo=false size=100mb'),
    _entry('<3> [prometheus] msg="write block" ooo=false size=200mb'),
]


def test_cluster_deleting_obsolete_block_variants_fold_into_one(collector):
    out = collector.cluster_templates(DELETING_OBSOLETE_BLOCK)
    assert len(out) == 1
    assert 'msg="Deleting obsolete block"' in out[0]["template"]
    assert out[0]["variants"] == 3
    assert out[0]["count"] == 3


def test_cluster_write_block_variants_fold_keeping_ooo_false(collector):
    out = collector.cluster_templates(WRITE_BLOCK)
    assert len(out) == 1
    assert 'msg="write block"' in out[0]["template"]
    assert "ooo=false" in out[0]["template"]
    assert out[0]["variants"] == 2


def test_cluster_two_families_together_yield_two_clusters(collector):
    out = collector.cluster_templates(DELETING_OBSOLETE_BLOCK + WRITE_BLOCK)
    assert len(out) == 2
    templates = [entry["template"] for entry in out]
    assert any('msg="Deleting obsolete block"' in t for t in templates)
    assert any('msg="write block"' in t for t in templates)


def test_cluster_wildcards_only_the_varying_position(collector):
    out = collector.cluster_templates(DELETING_OBSOLETE_BLOCK)
    tokens = out[0]["template"].split()
    # '<3> [prometheus] msg="Deleting obsolete block" component=X durationYs'
    # tokenises to 7 positions; component (index 5) and duration (index 6)
    # both vary across the family, every other position stays literal.
    assert tokens[0] == "<3>"
    assert tokens[1] == "[prometheus]"
    assert tokens[3] == "obsolete"
    assert tokens[4] == 'block"'
    assert tokens[5] == "<*>"
    assert tokens[6] == "<*>"
    assert out[0]["variants"] == len(DELETING_OBSOLETE_BLOCK)
    assert out[0]["count"] == sum(e["count"] for e in DELETING_OBSOLETE_BLOCK)


def test_cluster_different_token_counts_never_merge(collector):
    entries = [
        _entry("<3> [prometheus] short line"),
        _entry("<3> [prometheus] a much longer line here"),
    ]
    out = collector.cluster_templates(entries)
    assert len(out) == 2


def test_cluster_different_priorities_never_merge(collector):
    entries = [
        _entry("<3> [prometheus] same shape token", priority=3),
        _entry("<3> [prometheus] same shape token", priority=6),
    ]
    out = collector.cluster_templates(entries)
    assert len(out) == 2


def test_cluster_different_categories_never_merge(collector):
    entries = [
        _entry("<3> [prometheus] same shape token", category="metrics"),
        _entry("<3> [prometheus] same shape token", category="security"),
    ]
    out = collector.cluster_templates(entries)
    assert len(out) == 2


def test_cluster_position_zero_never_wildcarded(collector):
    # Same bucket (priority/category/token count) but the literal text at
    # position 0 differs between the two entries -- it must never be
    # rewritten to <*>, only positions 1..n are ever eligible.
    entries = [
        _entry("<3> [prometheus] same shape alpha", priority=3),
        _entry("<9> [prometheus] same shape alpha", priority=3),
    ]
    out = collector.cluster_templates(entries)
    assert len(out) == 1
    tokens = out[0]["template"].split()
    assert tokens[0] in ("<3>", "<9>")
    assert tokens[0] != "<*>"


def test_cluster_deterministic_under_shuffled_input(collector):
    family = [
        _entry('<3> [x] msg="event" tag=alpha n=1', count=5),
        _entry('<3> [x] msg="event" tag=beta n=2', count=1),
        _entry('<3> [x] msg="event" tag=gamma n=3', count=3),
        _entry('<3> [x] msg="event" tag=delta n=4', count=2),
        _entry('<3> [x] msg="event" tag=epsilon n=5', count=4),
    ]
    baseline = collector.cluster_templates(list(family))
    for seed in (1, 2, 3, 42):
        shuffled = list(family)
        random.Random(seed).shuffle(shuffled)
        result = collector.cluster_templates(shuffled)
        assert result == baseline


def test_cluster_single_entry_no_variants_key(collector):
    out = collector.cluster_templates([_entry("<3> [x] lone event")])
    assert len(out) == 1
    assert "variants" not in out[0]


def test_cluster_empty_template_does_not_raise(collector):
    entries = [_entry(""), _entry("")]
    out = collector.cluster_templates(entries)
    assert len(out) == 2
    for entry in out:
        assert "variants" not in entry


def test_cluster_empty_input(collector):
    assert collector.cluster_templates([]) == []


# --------------------------------------------------------------------------
# flush(): the cluster-then-sort-then-truncate-to-share pipeline that used
# to be the tail of group_templates().
# --------------------------------------------------------------------------

DELETING_LINES = [
    (100, '<3> [prometheus] msg="Deleting obsolete block" region=eu', "modx", "metrics"),
    (101, '<3> [prometheus] msg="Deleting obsolete block" region=us', "modx", "metrics"),
    (102, '<3> [prometheus] msg="Deleting obsolete block" region=ap', "modx", "metrics"),
]

SSHD_LINES = [
    (200, '<6> [sshd] Accepted publickey for alice', "modx", ""),
    (201, '<6> [sshd] Accepted publickey for bob', "modx", ""),
]


def test_flush_clusters_before_truncating(flush_lines):
    """5 raw lines fold (via masking + clustering) to 2 distinct template
    shapes. A share of 2 must keep both -- if truncation ran on the raw,
    pre-cluster count (5), a share of 2 could arbitrarily drop one whole
    family instead."""
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=2)
    templates = bundle["templates"]
    assert bundle["budget"]["lines_seen"] == 5
    assert len(templates) == 2
    assert bundle["budget"]["lines_kept"] == sum(t["count"] for t in templates)
    assert bundle["budget"]["lines_kept"] == 5


def test_flush_most_frequent_first(flush_lines):
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=10)  # 3 vs 2
    templates = bundle["templates"]
    assert len(templates) == 2
    assert templates[0]["count"] >= templates[1]["count"]
    assert 'msg="Deleting obsolete block"' in templates[0]["template"]


def test_flush_empty_category_dropped_non_empty_kept(flush_lines):
    templates = flush_lines(DELETING_LINES + SSHD_LINES,
                            max_lines=10)["templates"]
    deleting = next(t for t in templates
                    if 'msg="Deleting obsolete block"' in t["template"])
    sshd = next(t for t in templates if "Accepted publickey" in t["template"])
    assert deleting.get("category") == "metrics"
    assert "category" not in sshd


def test_flush_truncated_to_share(flush_lines):
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=1)
    templates = bundle["templates"]
    assert len(templates) == 1
    assert 'msg="Deleting obsolete block"' in templates[0]["template"]
    assert bundle["budget"]["lines_kept"] == templates[0]["count"]


def test_flush_records_the_truncation(flush_lines):
    """A family that lost shapes to its share must say so, or the server
    reads a partial picture as a complete one."""
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=1)
    truncated = bundle["budget"]["truncated_modules"]
    assert [row["module_id"] for row in truncated] == ["modx"]
    assert truncated[0]["truncated"] is True
    # 5 lines seen, 3 kept in the one surviving shape.
    assert truncated[0]["dropped"] == 2


def test_flush_no_truncation_key_when_everything_fits(flush_lines):
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=10)
    assert "truncated_modules" not in bundle["budget"]


def test_flush_empty_input(flush_lines):
    bundle = flush_lines([], max_lines=10)
    assert bundle["templates"] == []
    assert bundle["digest"] == []
    assert bundle["budget"]["lines_kept"] == 0
    assert bundle["budget"]["lines_seen"] == 0


# --------------------------------------------------------------------------
# CLUSTER_SIMILARITY itself.
#
# The two evidence families above are also separated by their differing
# token counts, so they would stay apart even with the threshold set to
# almost zero -- they pin the wildcarding, not the threshold. These two
# tests pin the threshold from both sides, using entries deliberately built
# to share a priority, a category AND a token count, so the match ratio is
# the only thing left that can decide the outcome.
# --------------------------------------------------------------------------

# Six tokens each, agreeing only on the two-token scaffolding: 2/6 = 0.33,
# below the 0.5 threshold, so these must stay apart. Lowering the threshold
# far enough would merge two genuinely distinct conditions into one shape
# and lose both.
_SAME_LENGTH_DISTINCT = [
    _entry('<3> [prometheus] level=info msg=deleting_obsolete_block '
           'component=tsdb block=<HEX>', count=65),
    _entry('<3> [prometheus] level=warn msg=write_block mint=<HEX> '
           'maxt=<HEX>', count=53),
]


def test_distinct_conditions_of_equal_length_do_not_merge(collector):
    out = collector.cluster_templates(list(_SAME_LENGTH_DISTINCT))
    assert len(out) == 2, [entry["template"] for entry in out]
    assert any("deleting_obsolete_block" in entry["template"] for entry in out)
    assert any("write_block" in entry["template"] for entry in out)
    # Neither kept a wildcard: nothing was folded, so nothing was lost.
    assert all("<*>" not in entry["template"] for entry in out)


def test_near_duplicates_of_equal_length_still_merge(collector):
    # Five tokens differing in exactly one position: 4/5 = 0.8, comfortably
    # above the threshold. Raising the threshold past that would stop the
    # collector collapsing the near-duplicates it exists to collapse.
    family = [_entry('<3> [prometheus] msg=compaction shard=%d done' % shard)
              for shard in range(4)]
    out = collector.cluster_templates(family)
    assert len(out) == 1
    assert out[0]["template"] == '<3> [prometheus] msg=compaction <*> done'
    assert out[0]["variants"] == 4


# --------------------------------------------------------------------------
# Family-scoped grouping: the 82 byte-identical pam_unix(cron:session)
# templates of 82 nethvoice instances. Keyed per instance they each formed
# a cluster of one and all 82 shipped; keyed per family the raw dedup in
# TemplateStore collapses them before clustering even runs.
# --------------------------------------------------------------------------

CRON_LINE = "<6> [CRON] pam_unix(cron:session): session closed for user root"


def test_flush_collapses_identical_lines_across_a_family(flush_lines):
    """The 82 lines come from 82 DIFFERENT instances, as they really do."""
    lines = [(100 + i, CRON_LINE, "nethvoice{0}".format(i + 1), "")
             for i in range(82)]
    bundle = flush_lines(lines, max_lines=20)
    templates = bundle["templates"]

    assert bundle["budget"]["lines_seen"] == 82
    assert len(templates) == 1
    assert templates[0]["count"] == 82
    assert templates[0]["module_id"] == "nethvoice"
    assert bundle["budget"]["lines_kept"] == 82
    # Collapsed by the raw (template, priority, category) dedup, not by
    # clustering, so there is exactly one variant and no `variants` key.
    assert "variants" not in templates[0]


def test_cluster_82_identical_entries_report_variants(collector):
    """cluster_templates() on its own, fed 82 separate entries as it would
    be if the dedup key still carried the instance."""
    entries = [_entry(CRON_LINE, count=1, module_id="nethvoice")
               for _ in range(82)]
    out = collector.cluster_templates(entries)

    assert len(out) == 1
    assert out[0]["variants"] == 82
    assert out[0]["count"] == 82


def test_cluster_two_families_same_token_count_do_not_merge(collector):
    """Bucketing is by (priority, category, token count), so the caller
    being family-scoped is what keeps two families apart. Same token
    count, no shared tokens after position 0 -- below CLUSTER_SIMILARITY."""
    nethvoice = _entry("<3> [nethvoice] aaa bbb ccc ddd", module_id="nethvoice")
    openldap = _entry("<3> [openldap] eee fff ggg hhh", module_id="openldap")
    assert len(nethvoice["template"].split()) == len(openldap["template"].split())

    out = collector.cluster_templates([nethvoice, openldap])
    assert len(out) == 2
    assert all("variants" not in entry for entry in out)
