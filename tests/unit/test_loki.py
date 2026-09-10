#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for _filter_stages() and the Loki Client in insights-collector.

No network calls: a Client is built with a fake base URL and its _get()
method is monkeypatched to return canned payloads and record what it was
called with.
"""
import datetime

import pytest

UTC = datetime.timezone.utc


def make_client(collector):
    return collector.Client("http://loki.example", "user", "pass")


# --------------------------------------------------------------------------
# _filter_stages()
# --------------------------------------------------------------------------

def test_filter_stages_basic(collector):
    stages = collector._filter_stages([], "loki1/insights-collector")
    assert stages == [
        '| json priority="PRIORITY", identifier="SYSLOG_IDENTIFIER"',
        '| identifier != "loki1/insights-collector"',
        '| priority < 5 or category="security"',
    ]


def test_filter_stages_denylist_appended_only_when_non_empty(collector):
    stages = collector._filter_stages(["a", "b"], "id")
    assert stages[-1] == '!~ "a|b"'
    assert len(stages) == 4

    stages_empty = collector._filter_stages([], "id")
    assert not any(stage.startswith("!~") for stage in stages_empty)


def test_filter_stages_include_message(collector):
    without = collector._filter_stages([], "id", include_message=False)
    with_msg = collector._filter_stages([], "id", include_message=True)
    assert 'message="MESSAGE"' not in without[0]
    assert 'message="MESSAGE"' in with_msg[0]


# --------------------------------------------------------------------------
# digest() / tail() parity -- the defect fixed on this branch.
# --------------------------------------------------------------------------

def test_digest_and_tail_build_same_filter_stages(collector, monkeypatch):
    """digest() and tail() must build their filter stages (json,
    identifier exclusion, priority-or-category filter, denylist) from the
    same _filter_stages() call, in the same order. Pull the stages out of
    the recorded query strings rather than trusting it by eyeball."""
    calls = []

    def fake_get(path, params):
        calls.append((path, params))
        return {"data": {"result": []}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)

    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    denylist = ["Head GC completed", "write block"]
    self_id = "loki1/insights-collector"

    client.digest(at, 900, denylist, self_id)
    client.tail(1_000_000_000, 2_000_000_000, denylist, self_id)

    digest_query = calls[0][1]["query"]
    tail_query = calls[1][1]["query"]

    expected_digest_stages = collector._filter_stages(denylist, self_id)
    expected_tail_stages = collector._filter_stages(
        denylist, self_id, include_message=True)

    for stage in expected_digest_stages:
        assert stage in digest_query
    for stage in expected_tail_stages:
        assert stage in tail_query

    def stage_positions(query, stages):
        return [query.index(stage) for stage in stages]

    digest_positions = stage_positions(digest_query, expected_digest_stages)
    tail_positions = stage_positions(tail_query, expected_tail_stages)

    assert digest_positions == sorted(digest_positions)
    assert tail_positions == sorted(tail_positions)


# --------------------------------------------------------------------------
# Client.digest()
# --------------------------------------------------------------------------

def test_digest_parses_result(collector, monkeypatch):
    def fake_get(path, params):
        assert path == "/loki/api/v1/query"
        return {"data": {"result": [
            {"metric": {"module_id": "loki1", "priority": "3"}, "value": [1234, "5"]},
            {"metric": {"module_id": "", "priority": "6"}, "value": [1234, "2"]},
        ]}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    result = client.digest(at, 900, [], "self-id")
    assert result == {("loki1", 3): 5.0, ("", 6): 2.0}


def test_digest_skips_malformed_entries(collector, monkeypatch):
    def fake_get(path, params):
        return {"data": {"result": [
            {"metric": {"module_id": "a", "priority": "not-a-number"}, "value": [1, "5"]},
            {"metric": {"module_id": "b", "priority": "3"}},  # no "value" key
            {"metric": {"module_id": "c", "priority": "3"}, "value": [1, "7"]},
        ]}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    result = client.digest(at, 900, [], "self-id")
    assert result == {("c", 3): 7.0}


def test_digest_returns_empty_dict_on_loki_error(collector, monkeypatch):
    def fake_get(path, params):
        raise collector.LokiError("boom")

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    assert client.digest(at, 900, [], "self-id") == {}


# --------------------------------------------------------------------------
# Client.baseline_series()
# --------------------------------------------------------------------------

def test_baseline_series_sets_range_and_step_to_same_value(collector, monkeypatch):
    recorded = {}

    def fake_get(path, params):
        recorded["path"] = path
        recorded["params"] = params
        return {"data": {"result": []}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    client.baseline_series(at, 3600 * 168, 900, [], "self-id")

    assert recorded["path"] == "/loki/api/v1/query_range"
    assert recorded["params"]["step"] == "900"
    assert "[900s]" in recorded["params"]["query"]


def test_baseline_series_parses_values_array(collector, monkeypatch):
    def fake_get(path, params):
        return {"data": {"result": [
            {"metric": {"module_id": "loki1", "priority": "3"},
             "values": [["1704067200", "5"], ["1704068100", "7"]]},
        ]}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    result = client.baseline_series(at, 900, 900, [], "self-id")
    assert result == {("loki1", 3): [(1704067200, 5.0), (1704068100, 7.0)]}


def test_baseline_series_skips_malformed_pairs_keeps_valid_ones(collector, monkeypatch):
    def fake_get(path, params):
        return {"data": {"result": [
            {"metric": {"module_id": "loki1", "priority": "3"},
             "values": [["100"], ["200", "5"]]},  # first pair malformed
        ]}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    result = client.baseline_series(at, 900, 900, [], "self-id")
    assert result == {("loki1", 3): [(200, 5.0)]}


def test_baseline_series_skips_series_with_bad_priority(collector, monkeypatch):
    def fake_get(path, params):
        return {"data": {"result": [
            {"metric": {"module_id": "loki1", "priority": "nope"},
             "values": [["100", "5"]]},
        ]}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    assert client.baseline_series(at, 900, 900, [], "self-id") == {}


def test_baseline_series_returns_empty_dict_on_loki_error(collector, monkeypatch):
    def fake_get(path, params):
        raise collector.LokiError("boom")

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    at = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    assert client.baseline_series(at, 900, 900, [], "self-id") == {}


# --------------------------------------------------------------------------
# Client.tail()
# --------------------------------------------------------------------------

def _record_tail(collector, monkeypatch, result=()):
    recorded = {}

    def fake_get(path, params):
        recorded["path"] = path
        recorded["params"] = params
        return {"data": {"result": list(result)}}

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    out = client.tail(1_000_000, 3_000_000, [], "self-id")
    return recorded, out


def test_tail_reads_module_id_and_category_and_sorts(collector, monkeypatch):
    _, out = _record_tail(collector, monkeypatch, [
        {"stream": {"module_id": "loki1", "category": "security"},
         "values": [["3000000", "first"], ["1000000", "second"]]},
        {"stream": {"module_id": "traefik1"},
         "values": [["2000000", "third"]]},
    ])
    assert out == [
        (1000000, "second", "loki1", "security"),
        (2000000, "third", "traefik1", ""),
        (3000000, "first", "loki1", "security"),
    ]


def test_tail_keeps_nanoseconds(collector, monkeypatch):
    """The cursor is nanosecond-exact, so tail() must not round to
    milliseconds the way the old per-family lines() did."""
    _, out = _record_tail(collector, monkeypatch, [
        {"stream": {"module_id": "loki1"},
         "values": [["1757000000123456789", "line"]]},
    ])
    assert out[0][0] == 1757000000123456789


def test_tail_missing_module_id_label_is_the_host_bucket(collector, monkeypatch):
    """Host records (sshd, systemd, runagent) carry no module_id label at
    all, and they are the majority of security-relevant traffic."""
    _, out = _record_tail(collector, monkeypatch, [
        {"stream": {}, "values": [["1000000", "sshd line"]]},
    ])
    assert out[0][2] == collector.HOST_BUCKET


def test_tail_selector_carries_no_module_matcher(collector, monkeypatch):
    """One query for every module and the host bucket: a module matcher
    here would put the per-family fan-out back."""
    recorded, _ = _record_tail(collector, monkeypatch)
    query = recorded["params"]["query"]
    assert query.startswith('{node_id=~".+"}')
    assert "module_id" not in query.split("|")[0]


def test_tail_renders_the_same_line_format_as_before(collector, monkeypatch):
    """mask() must keep seeing byte-identical text, or every template on
    the fleet goes novel at once."""
    recorded, _ = _record_tail(collector, monkeypatch)
    assert recorded["params"]["query"].endswith(
        '| line_format "<{{.priority}}> [{{.identifier}}] {{.message}}"')


def test_tail_request_is_a_forward_bounded_page(collector, monkeypatch):
    recorded, _ = _record_tail(collector, monkeypatch)
    assert recorded["path"] == "/loki/api/v1/query_range"
    assert recorded["params"]["direction"] == "forward"
    assert recorded["params"]["start"] == "1000000"
    assert recorded["params"]["end"] == "3000000"
    assert recorded["params"]["limit"] == str(collector.TAIL_LIMIT)


def test_tail_propagates_loki_errors(collector, monkeypatch):
    """Unlike digest() and baseline_series(), a failed tail must NOT look
    like an empty one: the caller has to leave its cursor where it was."""
    def fake_get(path, params):
        raise collector.LokiError("boom")

    client = make_client(collector)
    monkeypatch.setattr(client, "_get", fake_get)
    with pytest.raises(collector.LokiError):
        client.tail(0, 1, [], "self-id")
