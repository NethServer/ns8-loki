#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Node attribution: carrying Loki's node_id through to the bundle, and
resolving it to an FQDN from node_exporter."""
import pytest


# --------------------------------------------------------------------------
# TemplateStore: the per-template node set.
# --------------------------------------------------------------------------

def test_store_collects_the_nodes_a_template_was_seen_on(collector):
    store = collector.TemplateStore()
    store.ingest(100, "<6> [sshd] a line", "", "", 1)
    store.ingest(200, "<6> [sshd] a line", "", "", 3)
    entries, _observed, _seen, _evicted = store.drain()

    assert len(entries) == 1
    assert entries[0]["nodes"] == {1, 3}


def test_store_counts_a_node_once_however_often_it_repeats(collector):
    """The same template recurs thousands of times per node in a window;
    the wire wants each node once."""
    store = collector.TemplateStore()
    for _ in range(100):
        store.ingest(100, "<6> [sshd] a line", "", "", 2)
    entries, _o, _s, _e = store.drain()

    assert entries[0]["nodes"] == {2}
    assert entries[0]["count"] == 100


def test_store_tolerates_a_missing_node_id(collector):
    """A line whose stream carried no usable node_id is still collected --
    failing open toward analysis, the same direction the service filter
    takes."""
    store = collector.TemplateStore()
    store.ingest(100, "<6> [sshd] a line", "", "", None)
    entries, _o, _s, _e = store.drain()

    assert entries[0]["nodes"] == set()
    assert entries[0]["count"] == 1


# --------------------------------------------------------------------------
# cluster_templates(): the union across a variant fold.
# --------------------------------------------------------------------------

def _entry(template, nodes, count=1):
    return {
        "template": template, "count": count, "module_id": "mod1",
        "priority": 3, "category": "", "first_seen": 100, "last_seen": 100,
        "samples": [template], "nodes": set(nodes),
    }


def test_clustering_unions_the_nodes_of_folded_variants(collector):
    """The same condition can mask to different variants on different
    nodes. Keeping only the representative's set would blame whichever node
    produced the busiest variant."""
    out = collector.cluster_templates([
        _entry('<3> [prometheus] msg="Deleting obsolete block" component=eu', [1]),
        _entry('<3> [prometheus] msg="Deleting obsolete block" component=us', [3]),
    ])

    assert len(out) == 1
    assert out[0]["nodes"] == {1, 3}


def test_clustering_leaves_a_solo_template_its_own_nodes(collector):
    out = collector.cluster_templates([_entry("<3> [a] only one", [2])])
    assert out[0]["nodes"] == {2}


# --------------------------------------------------------------------------
# _parse_node_id()
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("1", 1), ("12", 12), (3, 3),
    ("0", None), ("-1", None), ("", None), (None, None),
    ("leader", None), ("1.5", None),
])
def test_parse_node_id(collector, raw, want):
    assert collector._parse_node_id(raw) == want


# --------------------------------------------------------------------------
# scrape_node_fqdn(): parsing node_exporter's ns8_node_info.
# --------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, lines):
        self._lines = lines

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# The real shape, byte for byte, as served by node_exporter on rl1.
REAL_METRICS = [
    b"# HELP ns8_node_main_ip_address Main IP address selected by routing table\n",
    b"# TYPE ns8_node_main_ip_address gauge\n",
    b'ns8_node_main_ip_address{address="167.99.210.99",family="ipv4"} 1\n',
    b"# HELP ns8_node_info Node additional information\n",
    b"# TYPE ns8_node_info gauge\n",
    b'ns8_node_info{fqdn="rl1.leader.default.gs.nethserver.net",wg0_port="55820"} 1\n',
]


def _patch_urlopen(collector, monkeypatch, lines=None, raises=None):
    def fake_urlopen(url, timeout=None):
        if raises is not None:
            raise raises
        return _FakeResponse(lines or [])
    monkeypatch.setattr(collector.urllib.request, "urlopen", fake_urlopen)


def test_scrape_reads_the_fqdn(collector, monkeypatch):
    _patch_urlopen(collector, monkeypatch, REAL_METRICS)
    assert collector.scrape_node_fqdn("10.5.4.1") == \
        "rl1.leader.default.gs.nethserver.net"


def test_scrape_returns_none_when_the_metric_is_absent(collector, monkeypatch):
    _patch_urlopen(collector, monkeypatch, REAL_METRICS[:3])
    assert collector.scrape_node_fqdn("10.5.4.1") is None


def test_scrape_returns_none_on_any_failure(collector, monkeypatch):
    """Losing a name must cost attribution names, never the run -- the same
    contract digest() and baseline_series() follow."""
    _patch_urlopen(collector, monkeypatch, raises=OSError("unreachable"))
    assert collector.scrape_node_fqdn("10.5.4.1") is None


# --------------------------------------------------------------------------
# build_roster() and RosterCache.
# --------------------------------------------------------------------------

def test_build_roster_lists_a_node_with_no_name(collector, monkeypatch):
    """The id is the attribution; the name is a convenience on top of it."""
    monkeypatch.setattr(collector, "scrape_node_fqdn",
                        lambda ip, **kw: "a.example.org" if ip == "10.5.4.1" else None)
    roster = collector.build_roster([(1, "10.5.4.1"), (2, "10.5.4.2")])

    assert roster == [
        {"node_id": 1, "fqdn": "a.example.org"},
        {"node_id": 2},
    ]


def test_roster_cache_scrapes_once_within_the_ttl(collector):
    calls = []

    def builder(nodes):
        calls.append(nodes)
        return [{"node_id": 1, "fqdn": "a.example.org"}]

    cache = collector.RosterCache(ttl=3600, reader=lambda: [(1, "10.5.4.1")],
                                  builder=builder)
    assert cache.get(1000) == [{"node_id": 1, "fqdn": "a.example.org"}]
    assert cache.get(2000) == [{"node_id": 1, "fqdn": "a.example.org"}]
    assert len(calls) == 1


def test_roster_cache_refreshes_past_the_ttl(collector):
    results = [[{"node_id": 1, "fqdn": "old.example.org"}],
               [{"node_id": 1, "fqdn": "new.example.org"}]]

    cache = collector.RosterCache(ttl=10, reader=lambda: [],
                                  builder=lambda _n: results.pop(0))
    assert cache.get(1000)[0]["fqdn"] == "old.example.org"
    assert cache.get(1011)[0]["fqdn"] == "new.example.org"


def test_roster_cache_keeps_the_last_good_roster_on_failure(collector):
    """A transient failure must not make the bundle look like a cluster
    that lost its nodes."""
    state = {"fail": False}

    def builder(_nodes):
        if state["fail"]:
            raise RuntimeError("redis down")
        return [{"node_id": 1, "fqdn": "a.example.org"}]

    cache = collector.RosterCache(ttl=10, reader=lambda: [], builder=builder)
    assert cache.get(1000)[0]["fqdn"] == "a.example.org"
    state["fail"] = True
    assert cache.get(2000)[0]["fqdn"] == "a.example.org"


# --------------------------------------------------------------------------
# build_bundle(): the wire shape.
# --------------------------------------------------------------------------

def test_bundle_carries_the_roster(collector):
    bundle = collector.build_bundle(
        "sys-1", "1.0", (0, 100), [], [], {"max_lines": 1},
        nodes=[{"node_id": 1, "fqdn": "a.example.org"}])
    assert bundle["nodes"] == [{"node_id": 1, "fqdn": "a.example.org"}]


def test_bundle_omits_an_empty_roster(collector):
    """An empty list would say 'this cluster has no nodes', which is never
    true; the field is optional on the wire."""
    bundle = collector.build_bundle("sys-1", "1.0", (0, 100), [], [],
                                    {"max_lines": 1}, nodes=[])
    assert "nodes" not in bundle


# --------------------------------------------------------------------------
# flush(): end to end, from ingested lines to the wire shape.
# --------------------------------------------------------------------------

def test_flushed_templates_carry_sorted_node_lists(collector, flush_lines):
    bundle = flush_lines([
        (100, "<6> [sshd] Failed password for root", "", "security", 3),
        (200, "<6> [sshd] Failed password for root", "", "security", 1),
    ], roster=[{"node_id": 1, "fqdn": "a.example.org"},
               {"node_id": 3, "fqdn": "c.example.org"}])

    assert len(bundle["templates"]) == 1
    assert bundle["templates"][0]["nodes"] == [1, 3]
    assert bundle["nodes"] == [{"node_id": 1, "fqdn": "a.example.org"},
                               {"node_id": 3, "fqdn": "c.example.org"}]


def test_a_template_with_no_attribution_omits_the_field(collector, flush_lines):
    """A stream with no usable node_id must produce the same wire shape a
    pre-node collector does, not an empty list."""
    bundle = flush_lines([
        (100, "<6> [sshd] Failed password for root", "", "security"),
    ])

    assert "nodes" not in bundle["templates"][0]
    assert "nodes" not in bundle
