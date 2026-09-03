#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for TemplateStore, the bounded aggregator the tail loop feeds."""
import pytest


def _word(n):
    """A distinct, digit-free token per n: mask() folds digits to <NUM>, so
    numbering these would make every line one template."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    out = ""
    n += 1
    while n:
        n, remainder = divmod(n - 1, 26)
        out = letters[remainder] + out
    return out


def _line(n, module_id="loki1", priority=6, category=""):
    return (100 + n, "<{0}> [unit] event {1}".format(priority, _word(n)),
            module_id, category)


def _ingest(store, lines):
    for ts, text, module_id, category in lines:
        store.ingest(ts, text, module_id, category)
    return store


# --------------------------------------------------------------------------
# Folding: same masking, same dedup key, same sample convention as the
# group_templates() this replaced.
# --------------------------------------------------------------------------

def test_identical_lines_fold_into_one_counted_entry(collector):
    store = collector.TemplateStore()
    for _ in range(5):
        store.ingest(100, "<6> [sshd] session opened", "loki1", "")
    entries, observed, seen, evicted = store.drain()

    assert len(entries) == 1
    assert entries[0]["count"] == 5
    assert seen == 5
    assert evicted == 0
    assert observed == {("loki1", 6): 5}


def test_two_instances_of_one_family_collapse(collector):
    """The 82 pam_unix(cron:session) lines: keyed per instance they could
    never meet, keyed per family they are one template."""
    store = collector.TemplateStore()
    for n in range(82):
        store.ingest(100 + n, "<6> [CRON] session closed for user root",
                     "nethvoice{0}".format(n + 1), "")
    entries, observed, _seen, _evicted = store.drain()

    assert len(entries) == 1
    assert entries[0]["count"] == 82
    assert entries[0]["module_id"] == "nethvoice"
    # observed[] stays per instance: one flooding sibling must stay visible.
    assert len(observed) == 82


def test_two_families_with_the_same_text_stay_apart(collector):
    """The family is part of the key, not just a field on the entry: the
    old per-family group_templates() call could never merge these, and
    neither may this."""
    store = collector.TemplateStore()
    store.ingest(100, "<6> [unit] the very same words", "nethvoice1", "")
    store.ingest(101, "<6> [unit] the very same words", "openldap1", "")
    entries, _observed, _seen, _evicted = store.drain()

    assert len(entries) == 2
    assert {entry["module_id"] for entry in entries} == {"nethvoice", "openldap"}


def test_priority_and_category_are_part_of_the_key(collector):
    store = collector.TemplateStore()
    store.ingest(100, "<3> [unit] same words", "loki1", "")
    store.ingest(101, "<6> [unit] same words", "loki1", "")
    store.ingest(102, "<6> [unit] same words", "loki1", "security")
    entries, _observed, _seen, _evicted = store.drain()
    assert len(entries) == 3


def test_missing_priority_marker_defaults_to_six(collector):
    store = collector.TemplateStore()
    store.ingest(100, "no priority marker here", "loki1", "")
    entries, observed, _seen, _evicted = store.drain()
    assert entries[0]["priority"] == 6
    assert observed == {("loki1", 6): 1}


def test_first_and_last_seen_widen_and_samples_keep_both_ends(collector):
    store = collector.TemplateStore()
    # All three mask to "<6> [unit] value <NUM>", so this is one entry
    # whose samples must still bracket the window.
    store.ingest(500, "<6> [unit] value 111", "loki1", "")
    store.ingest(100, "<6> [unit] value 222", "loki1", "")
    store.ingest(900, "<6> [unit] value 333", "loki1", "")
    entries, _observed, _seen, _evicted = store.drain()

    entry = entries[0]
    assert entry["first_seen"] == 100
    assert entry["last_seen"] == 900
    # First sample seen is kept; the second slot holds the most recent.
    assert len(entry["samples"]) == 2
    assert entry["samples"][0].endswith("111")
    assert entry["samples"][1].endswith("333")


def test_samples_are_truncated(collector):
    store = collector.TemplateStore()
    store.ingest(100, "<6> [unit] " + "x" * 4000, "loki1", "")
    entries, _observed, _seen, _evicted = store.drain()
    for sample in entries[0]["samples"]:
        assert len(sample) <= collector.SAMPLE_MAX_CHARS


def test_samples_are_scrubbed_before_being_stored(collector):
    """sanitize_line() runs on the way in, so a secret is never held in
    memory for a whole window, let alone shipped."""
    store = collector.TemplateStore()
    store.ingest(100, "<3> [unit] Authorization: Bearer sekrit-value-here",
                 "loki1", "")
    entries, _observed, _seen, _evicted = store.drain()
    assert "sekrit-value-here" not in entries[0]["samples"][0]


# --------------------------------------------------------------------------
# The bound: LRU on last-seen.
# --------------------------------------------------------------------------

def test_never_exceeds_the_cap(collector):
    store = collector.TemplateStore(max_templates=10)
    _ingest(store, [_line(n) for n in range(500)])
    entries, _observed, seen, evicted = store.drain()

    assert len(entries) == 10
    assert seen == 500
    assert evicted == 490


def test_evicts_the_coldest_entry_and_only_that_one(collector):
    store = collector.TemplateStore(max_templates=3)
    _ingest(store, [_line(0), _line(1), _line(2)])
    store.ingest(*_line(3))  # over the cap: _line(0) is the coldest

    entries, _observed, _seen, evicted = store.drain()
    assert evicted == 1
    surviving = {entry["template"] for entry in entries}
    assert "<6> [unit] event {0}".format(_word(0)) not in surviving
    for n in (1, 2, 3):
        assert "<6> [unit] event {0}".format(_word(n)) in surviving


def test_a_hit_refreshes_recency(collector):
    """A template that keeps recurring must not be evicted just because it
    was first seen early in the window."""
    store = collector.TemplateStore(max_templates=3)
    _ingest(store, [_line(0), _line(1), _line(2)])
    store.ingest(*_line(0))   # refresh the oldest; _line(1) is now coldest
    store.ingest(*_line(3))

    entries, _observed, _seen, _evicted = store.drain()
    surviving = {entry["template"] for entry in entries}
    assert "<6> [unit] event {0}".format(_word(0)) in surviving
    assert "<6> [unit] event {0}".format(_word(1)) not in surviving


def test_eviction_never_loses_a_count(collector):
    """observed[] is not evicted, so the digest the server's deviation gate
    reads stays complete even when the templates behind it are gone."""
    store = collector.TemplateStore(max_templates=2)
    _ingest(store, [_line(n) for n in range(50)])
    _entries, observed, seen, evicted = store.drain()

    assert observed[("loki1", 6)] == 50
    assert seen == 50
    assert evicted == 48


# --------------------------------------------------------------------------
# drain()
# --------------------------------------------------------------------------

def test_drain_resets_everything(collector):
    store = collector.TemplateStore(max_templates=2)
    _ingest(store, [_line(n) for n in range(10)])
    store.drain()

    entries, observed, seen, evicted = store.drain()
    assert entries == []
    assert observed == {}
    assert seen == 0
    assert evicted == 0


def test_drain_hands_over_ownership(collector):
    """The caller mutates the entries it gets (cluster_templates pops the
    empty category key), so the store must not still be holding them."""
    store = collector.TemplateStore()
    store.ingest(*_line(0))
    entries, _observed, _seen, _evicted = store.drain()
    entries[0]["count"] = 999

    store.ingest(*_line(0))
    again, _observed, _seen, _evicted = store.drain()
    assert again[0]["count"] == 1


# --------------------------------------------------------------------------
# The persisted cursor.
# --------------------------------------------------------------------------

def test_cursor_round_trips(collector, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    collector.write_cursor(1757000000123456789)
    assert collector.read_cursor() == 1757000000123456789


def test_cursor_missing_file_is_the_normal_first_start(collector, tmp_path,
                                                       monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert collector.read_cursor() is None
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("content", ["", "not-a-number", "12.5\n34"])
def test_cursor_garbage_is_reported_and_ignored(collector, tmp_path,
                                                monkeypatch, capsys, content):
    """A bad cursor must cost the gap it describes, never the daemon."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / collector.STREAM_CURSOR_FILE).write_text(content)
    assert collector.read_cursor() is None
    assert collector.STREAM_CURSOR_FILE in capsys.readouterr().err


def test_write_cursor_survives_an_unwritable_directory(collector, tmp_path,
                                                       monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / collector.STREAM_CURSOR_FILE).mkdir()
    collector.write_cursor(42)  # must not raise
    assert "could not write" in capsys.readouterr().err


def test_ns_and_ns_to_datetime_round_trip(collector):
    import datetime
    when = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)
    assert collector.ns_to_datetime(collector.ns(when)) == when
