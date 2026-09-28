#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for rank_templates() and the flush() pipeline in insights-collector."""
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


def _templates(entries):
    return [entry["template"] for entry in entries]


# --------------------------------------------------------------------------
# rank_templates()
# --------------------------------------------------------------------------

DELETING_OBSOLETE_BLOCK = [
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=eu duration=5s', count=5),
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=us duration=7s', count=4),
    _entry('<3> [prometheus] msg="Deleting obsolete block" component=ap duration=9s', count=3),
]

WRITE_BLOCK = [
    _entry('<3> [prometheus] msg="write block" ooo=false size=100mb', count=2),
    _entry('<3> [prometheus] msg="write block" ooo=false size=200mb', count=1),
]


def test_rank_never_rewrites_merges_or_drops_an_entry(collector):
    """The whole of masking version 6's fix: the entries that come out are
    the entries that went in, text untouched and no <*> anywhere."""
    family = DELETING_OBSOLETE_BLOCK + WRITE_BLOCK
    before = [dict(entry) for entry in family]
    out = collector.rank_templates(list(family))

    assert all("<*>" not in entry["template"] for entry in out)
    assert all("variants" not in entry for entry in out)
    assert sorted(out, key=lambda e: e["template"]) == \
        sorted(before, key=lambda e: e["template"])


def test_rank_puts_every_shape_before_a_second_spelling(collector):
    out = collector.rank_templates(DELETING_OBSOLETE_BLOCK + WRITE_BLOCK)
    # Rank 0, busiest first: the busiest spelling of each of the two shapes.
    assert _templates(out[:2]) == [
        DELETING_OBSOLETE_BLOCK[0]["template"],
        WRITE_BLOCK[0]["template"],
    ]
    # Rank 1: each shape's second spelling. Rank 2: the one left.
    assert _templates(out[2:4]) == [
        DELETING_OBSOLETE_BLOCK[1]["template"],
        WRITE_BLOCK[1]["template"],
    ]
    assert _templates(out[4:]) == [DELETING_OBSOLETE_BLOCK[2]["template"]]


def test_rank_a_rare_distinct_line_beats_a_busy_near_duplicate(collector):
    """What the ranking is for: capped by count alone, a share of two would
    go to two spellings of the Deleting line and the one-off would be
    truncated away."""
    rare = _entry("<3> [prometheus] level=error msg=corruption detected in wal", count=1)
    out = collector.rank_templates(DELETING_OBSOLETE_BLOCK + [rare])
    assert rare["template"] in _templates(out[:2])


def test_rank_different_token_counts_are_different_shapes(collector):
    entries = [
        _entry("<3> [prometheus] short line", count=5),
        _entry("<3> [prometheus] short line two", count=4),
        _entry("<3> [prometheus] short other", count=1),
    ]
    out = collector.rank_templates(entries)
    # "short line two" has a token count of its own, so it is a rank-0 shape
    # and outranks the lower-count second spelling of "short line".
    assert _templates(out) == [
        "<3> [prometheus] short line",
        "<3> [prometheus] short line two",
        "<3> [prometheus] short other",
    ]


@pytest.mark.parametrize("field,values", [
    ("priority", (3, 6)),
    ("category", ("metrics", "security")),
])
def test_rank_different_priorities_and_categories_are_different_shapes(
        collector, field, values):
    first = _entry("<3> [prometheus] same shape token", count=5)
    near = _entry("<3> [prometheus] same shape other", count=4)
    apart = _entry("<3> [prometheus] same shape token", count=1)
    first[field], near[field], apart[field] = values[0], values[0], values[1]
    out = collector.rank_templates([first, near, apart])
    assert out == [first, apart, near]


def test_rank_deterministic_under_shuffled_input(collector):
    family = [
        _entry('<3> [x] msg="event" tag=alpha n=1', count=5),
        _entry('<3> [x] msg="event" tag=beta n=2', count=1),
        _entry('<3> [x] msg="event" tag=gamma n=3', count=3),
        _entry('<3> [x] msg="other" code=delta', count=2),
        _entry('<3> [x] msg="event" tag=epsilon n=5', count=4),
        _entry('<3> [x] msg="event" tag=alpha n=1', count=1, category="security"),
    ]
    baseline = collector.rank_templates(list(family))
    for seed in (1, 2, 3, 42):
        shuffled = list(family)
        random.Random(seed).shuffle(shuffled)
        assert collector.rank_templates(shuffled) == baseline


def test_rank_empty_template_does_not_raise(collector):
    entries = [_entry(""), _entry("", category="security")]
    out = collector.rank_templates(entries)
    assert len(out) == 2


def test_rank_empty_input(collector):
    assert collector.rank_templates([]) == []


# --------------------------------------------------------------------------
# CLUSTER_SIMILARITY itself.
#
# These pin the threshold from both sides, using entries deliberately built
# to share a priority, a category AND a token count, so the match ratio is
# the only thing left that can decide whether two templates are one shape.
# --------------------------------------------------------------------------

# Six tokens each; the warn line agrees with the other two only on the
# two-token scaffolding: 2/6 = 0.33, below the 0.5 threshold, so it is a
# shape of its own. Lowering the threshold far enough would rank it behind
# every spelling of the deleting line.
_SAME_LENGTH_DISTINCT = [
    _entry('<3> [prometheus] level=info msg=deleting_obsolete_block '
           'component=tsdb block=<HEX>', count=65),
    _entry('<3> [prometheus] level=info msg=deleting_obsolete_block '
           'component=head block=<HEX>', count=60),
    _entry('<3> [prometheus] level=warn msg=write_block mint=<HEX> '
           'maxt=<HEX>', count=53),
]


def test_distinct_conditions_of_equal_length_are_two_shapes(collector):
    out = collector.rank_templates(list(_SAME_LENGTH_DISTINCT))
    assert "write_block" in out[1]["template"], _templates(out)


def test_near_duplicates_of_equal_length_are_one_shape(collector):
    # Five tokens differing in exactly one position: 4/5 = 0.8, comfortably
    # above the threshold. Raising the threshold past that would let the
    # near-duplicates crowd the distinct line out of a share of two.
    family = [_entry('<3> [prometheus] msg=compaction shard=%d done' % shard,
                     count=10 - shard)
              for shard in range(4)]
    distinct = _entry('<3> [prometheus] msg=reload failed badly', count=1)
    out = collector.rank_templates(family + [distinct])
    assert out[1] is distinct


def test_two_families_same_token_count_are_two_shapes(collector):
    """Same token count, no shared tokens after position 0 -- below
    CLUSTER_SIMILARITY."""
    nethvoice = _entry("<3> [nethvoice] aaa bbb ccc ddd", module_id="nethvoice")
    openldap = _entry("<3> [openldap] eee fff ggg hhh", module_id="openldap")
    near = _entry("<3> [nethvoice] aaa bbb ccc zzz", count=5, module_id="nethvoice")

    out = collector.rank_templates([nethvoice, openldap, near])
    assert out == [near, openldap, nethvoice]


# --------------------------------------------------------------------------
# flush(): rank, truncate to the share, ship busiest first.
# --------------------------------------------------------------------------

DELETING_LINES = (
    [(100, '<3> [prometheus] msg="Deleting obsolete block" region=eu', "modx", "metrics")] * 3
    + [(101, '<3> [prometheus] msg="Deleting obsolete block" region=us', "modx", "metrics")] * 2
    + [(102, '<3> [prometheus] msg="Deleting obsolete block" region=ap', "modx", "metrics")]
)

SSHD_LINES = [
    (200, '<6> [sshd] Accepted publickey for alice', "modx", ""),
    (201, '<6> [sshd] Accepted publickey for bob', "modx", ""),
]


def test_flush_ranks_before_truncating(flush_lines):
    """Six Deleting lines in three spellings and two sshd lines. A share of
    two must keep one of each condition -- by count alone it would keep two
    spellings of the Deleting line and drop sshd entirely."""
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=2)
    templates = bundle["templates"]
    assert bundle["budget"]["lines_seen"] == 8
    assert len(templates) == 2
    assert 'region=eu' in templates[0]["template"]
    assert "Accepted publickey" in templates[1]["template"]
    assert bundle["budget"]["lines_kept"] == 4


def test_flush_most_frequent_first(flush_lines):
    templates = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=10)["templates"]
    assert len(templates) == 5
    counts = [t["count"] for t in templates]
    assert counts == sorted(counts, reverse=True)
    assert 'region=eu' in templates[0]["template"]


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
    assert 'region=eu' in templates[0]["template"]
    assert bundle["budget"]["lines_kept"] == templates[0]["count"] == 3


def test_flush_records_the_truncation(flush_lines):
    """A family that lost shapes to its share must say so, or the server
    reads a partial picture as a complete one."""
    bundle = flush_lines(DELETING_LINES + SSHD_LINES, max_lines=1)
    truncated = bundle["budget"]["truncated_modules"]
    assert [row["module_id"] for row in truncated] == ["modx"]
    assert truncated[0]["truncated"] is True
    # 8 lines seen, 3 kept in the one surviving template.
    assert truncated[0]["dropped"] == 5


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
# The template is a function of the line, not of the window.
#
# Masking versions 3 to 5 wildcarded every position where two templates of
# one window differed, so the same line shipped as a different template in
# different windows -- literal when alone, and with a <*> wherever its
# neighbours of the moment disagreed with it. The dev fleet's
# system_templates held 733 such rows on 2026-09-28, and each looked novel
# to the server's gate once.
# --------------------------------------------------------------------------

NETHCTI_LINE = ("<3> [nethvoice4] 2026-09-28T10:00:00.123Z - warn: [com_nethcti_ws] "
                "ws disconnected undefined - reason: transport close (user: alessandro)")

NETHCTI_NEIGHBOURS = [
    # Differs in one token: v5 shipped both as "transport <*>".
    ("<3> [nethvoice4] 2026-09-28T10:00:01.456Z - warn: [com_nethcti_ws] "
     "ws disconnected undefined - reason: transport error (user: alessandro)"),
    # Differs in another: v5 shipped both as "ws disconnected <*>".
    ("<3> [nethvoice4] 2026-09-28T10:00:02.789Z - warn: [com_nethcti_ws] "
     "ws disconnected 10.0.0.9 - reason: transport close (user: alessandro)"),
]


@pytest.mark.parametrize("neighbours", [
    [],
    NETHCTI_NEIGHBOURS[:1],
    NETHCTI_NEIGHBOURS[1:],
    NETHCTI_NEIGHBOURS,
    NETHCTI_NEIGHBOURS * 5,
])
def test_a_line_ships_the_same_template_whatever_else_is_in_the_window(
        collector, flush_lines, neighbours):
    want = collector.mask(collector.sanitize_line(NETHCTI_LINE))
    lines = [(100 + i, text, "nethvoice4", "")
             for i, text in enumerate([NETHCTI_LINE] + neighbours)]

    templates = flush_lines(lines, max_lines=10)["templates"]

    assert want in [t["template"] for t in templates]
    assert all("<*>" not in t["template"] for t in templates)


def test_neighbours_ship_as_their_own_templates(flush_lines):
    lines = [(100 + i, text, "nethvoice4", "")
             for i, text in enumerate([NETHCTI_LINE] + NETHCTI_NEIGHBOURS)]
    templates = flush_lines(lines, max_lines=10)["templates"]
    assert len(templates) == 3
    assert all(t["count"] == 1 for t in templates)


# --------------------------------------------------------------------------
# Family-scoped grouping: the 82 byte-identical pam_unix(cron:session)
# templates of 82 nethvoice instances. Keyed per instance they each shipped;
# keyed per family the raw dedup in TemplateStore collapses them.
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
    assert "variants" not in templates[0]
