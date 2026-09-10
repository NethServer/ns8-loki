#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Tests for bundle assembly and the digest/deviation logic in
insights-collector: row_deviates, is_quiet, build_bundle, compute_window,
ms, seasonal_baseline and _hour_of_week."""
import datetime

import pytest

from conftest import WINDOW, FakeLokiClient

UTC = datetime.timezone.utc


# --------------------------------------------------------------------------
# ms()
# --------------------------------------------------------------------------

def test_ms(collector):
    when = datetime.datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)
    assert collector.ms(when) == 1000


# --------------------------------------------------------------------------
# compute_window()
# --------------------------------------------------------------------------

def test_compute_window_snaps_to_15_minute_boundary(collector):
    now = datetime.datetime(2026, 9, 1, 10, 7, 23, 500000, tzinfo=UTC)
    start, end = collector.compute_window(now, minutes=15)
    assert end == datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    assert start == datetime.datetime(2026, 9, 1, 9, 45, 0, tzinfo=UTC)


def test_compute_window_length_is_exactly_minutes(collector):
    now = datetime.datetime(2026, 9, 1, 10, 59, 59, tzinfo=UTC)
    start, end = collector.compute_window(now, minutes=15)
    assert (end - start) == datetime.timedelta(minutes=15)
    assert end.second == 0 and end.microsecond == 0
    assert end.minute % 15 == 0


def test_compute_window_already_on_boundary(collector):
    now = datetime.datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
    start, end = collector.compute_window(now, minutes=15)
    assert end == now
    assert start == now - datetime.timedelta(minutes=15)


# --------------------------------------------------------------------------
# row_deviates()
# --------------------------------------------------------------------------

def test_row_deviates_over_tolerance_no_stddev(collector):
    row = {"observed": 100, "expected": 10}
    assert collector.row_deviates(row) is True


def test_row_deviates_over_tolerance_within_sigma(collector):
    # ratio 100/10 = 10 > DEVIATION_TOLERANCE, but a wide stddev keeps it
    # inside DEVIATION_SIGMA standard deviations of expected.
    row = {"observed": 100, "expected": 10, "expected_stddev": 50}
    assert collector.row_deviates(row) is False


def test_row_deviates_over_tolerance_outside_sigma(collector):
    row = {"observed": 100, "expected": 10, "expected_stddev": 1}
    assert collector.row_deviates(row) is True


def test_row_deviates_under_tolerance(collector):
    row = {"observed": 20, "expected": 10}
    assert collector.row_deviates(row) is False


def test_row_deviates_missing_expected(collector):
    assert collector.row_deviates({"observed": 100}) is False


def test_row_deviates_zero_expected(collector):
    assert collector.row_deviates({"observed": 100, "expected": 0}) is False


def test_row_deviates_negative_expected(collector):
    assert collector.row_deviates({"observed": 100, "expected": -5}) is False


# --------------------------------------------------------------------------
# is_quiet()
# --------------------------------------------------------------------------

def test_is_quiet_true_for_no_templates_and_no_deviation(collector):
    payload = {"templates": [], "digest": [{"observed": 5, "expected": 10}]}
    assert collector.is_quiet(payload) is True


def test_is_quiet_false_when_a_row_deviates(collector):
    payload = {"templates": [], "digest": [{"observed": 100, "expected": 10}]}
    assert collector.is_quiet(payload) is False


def test_is_quiet_false_when_templates_exist(collector):
    payload = {"templates": [{"template": "x", "count": 1}], "digest": []}
    assert collector.is_quiet(payload) is False


def test_is_quiet_agrees_with_row_deviates(collector):
    """is_quiet() and collect()'s prioritisation both read row_deviates() on
    the same row -- pin that a row row_deviates() calls deviating can never
    be judged quiet by is_quiet()."""
    row = {"observed": 999, "expected": 1}
    assert collector.row_deviates(row) is True
    payload = {"templates": [], "digest": [row]}
    assert collector.is_quiet(payload) is False


# --------------------------------------------------------------------------
# build_bundle()
# --------------------------------------------------------------------------

def test_build_bundle_carries_expected_fields(collector):
    digest_rows = [{"module_id": "loki1", "priority": 3, "observed": 5}]
    templates = [{"template": "x", "count": 1}]
    budget = {"max_lines": 500, "lines_seen": 10, "lines_kept": 3}
    bundle = collector.build_bundle(
        "system-123", "2.0.0", (1000, 2000), digest_rows, templates, budget)

    assert bundle["schema_version"] == collector.SCHEMA_VERSION
    assert bundle["masking_version"] == collector.MASKING_VERSION
    assert bundle["system_id"] == "system-123"
    assert bundle["collector_version"] == "2.0.0"
    assert bundle["window"] == {"start": 1000, "end": 2000}
    assert bundle["digest"] is digest_rows
    assert bundle["templates"] is templates
    assert bundle["budget"] is budget


# --------------------------------------------------------------------------
# _hour_of_week()
# --------------------------------------------------------------------------

def test_hour_of_week_monday_midnight_utc_is_zero(collector):
    # 2024-01-01 00:00:00 UTC is a Monday.
    assert collector._hour_of_week(1704067200.0) == 0


def test_hour_of_week_monday_afternoon(collector):
    # 2024-01-01 13:30:00 UTC, same Monday, hour 13.
    assert collector._hour_of_week(1704115800.0) == 13


def test_hour_of_week_wednesday_morning(collector):
    # 2024-01-03 05:00:00 UTC is a Wednesday (weekday 2), hour 5.
    assert collector._hour_of_week(1704258000.0) == 2 * 24 + 5


def test_hour_of_week_range(collector):
    base = 1704067200.0
    for step in range(0, 672):
        value = collector._hour_of_week(base + step * 900)
        assert 0 <= value <= 167


# --------------------------------------------------------------------------
# seasonal_baseline()
# --------------------------------------------------------------------------

MONDAY_MIDNIGHT_UTC = datetime.datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)


def _build_spiky_series(collector, spike_hour_of_week, normal_value, spike_value,
                        step_seconds=900, total_samples=672):
    """A 672-sample series at 900s spacing (exactly BASELINE_HOURS=168h)
    where every sample whose hour-of-week is `spike_hour_of_week` is
    `spike_value`, and every other sample is `normal_value`."""
    samples = []
    for i in range(total_samples):
        ts = MONDAY_MIDNIGHT_UTC.timestamp() + i * step_seconds
        value = spike_value if collector._hour_of_week(ts) == spike_hour_of_week \
            else normal_value
        samples.append((ts, value))
    return samples


def test_seasonal_baseline_reflects_the_spike_the_flat_mean_misses(collector):
    """The core justification for seasonal_baseline(): a recurring
    business-hours-shaped spike must not fire the deviation gate under a
    seasonal baseline, even though the same observed count WOULD have
    fired it under the old flat week-long mean."""
    key = ("loki1", 3)
    spike_bucket = 13  # Monday 13:00
    series = {key: _build_spiky_series(collector, spike_bucket,
                                       normal_value=5, spike_value=50)}
    target_start = MONDAY_MIDNIGHT_UTC + datetime.timedelta(hours=13)

    result = collector.seasonal_baseline(series, target_start)
    expected, stddev, sample_count, seasonal = result[key]

    assert seasonal is True
    assert sample_count == 4
    assert expected == pytest.approx(50.0)

    flat_mean = sum(v for _, v in series[key]) / len(series[key])
    observed = 45

    flat_ratio = observed / flat_mean
    seasonal_ratio = observed / expected

    assert flat_ratio > collector.DEVIATION_TOLERANCE
    assert seasonal_ratio <= collector.DEVIATION_TOLERANCE


def test_seasonal_baseline_falls_back_below_minimum_samples(collector):
    key = ("loki1", 3)
    # Only 2 samples share the target hour-of-week (bucket 0, Monday
    # 00:00-01:00) -- below MIN_BASELINE_SAMPLES (3) -- so this must fall
    # back to the flat mean over every sample instead.
    base = MONDAY_MIDNIGHT_UTC.timestamp()
    samples = [(base, 50), (base + 900, 52)]  # bucket 0, only 2 samples
    for hour in range(1, 9):  # 8 more samples, each its own distinct bucket
        samples.append((base + hour * 3600, 5))
    series = {key: samples}
    target_start = MONDAY_MIDNIGHT_UTC  # hour-of-week 0

    expected, stddev, sample_count, seasonal = collector.seasonal_baseline(
        series, target_start)[key]

    assert seasonal is False
    assert sample_count == len(samples)
    flat_mean = sum(v for _, v in samples) / len(samples)
    assert expected == pytest.approx(flat_mean)


def test_seasonal_baseline_single_sample_stddev_zero(collector):
    key = ("loki1", 3)
    series = {key: [(MONDAY_MIDNIGHT_UTC.timestamp(), 42)]}
    expected, stddev, sample_count, seasonal = collector.seasonal_baseline(
        series, MONDAY_MIDNIGHT_UTC)[key]
    assert expected == 42
    assert stddev == 0.0
    assert sample_count == 1


def test_seasonal_baseline_skips_empty_sample_list(collector):
    key = ("loki1", 3)
    series = {key: []}
    result = collector.seasonal_baseline(series, MONDAY_MIDNIGHT_UTC)
    assert key not in result


# --------------------------------------------------------------------------
# flush(): templates[] carries module families while digest[] still
# carries instances.
# --------------------------------------------------------------------------

FLEET_LINES = [
    (1000, "<3> [{0}] disk full".format(module_id or "sshd"), module_id, "")
    for module_id in ["nethvoice1", "nethvoice2", "nethvoice3",
                      "openldap1", "openldap2", ""]
]


def test_flush_templates_carry_families(flush_lines):
    bundle = flush_lines(FLEET_LINES)
    assert {t["module_id"] for t in bundle["templates"]} == {
        "nethvoice", "openldap", ""}


def test_flush_digest_still_carries_instances(flush_lines):
    """Deliberate asymmetry: the server's module_baselines and its
    deviation gate are per-instance, so one instance flooding stays visible
    instead of being averaged out across its siblings."""
    bundle = flush_lines(FLEET_LINES)
    assert {row["module_id"] for row in bundle["digest"]} == {
        "nethvoice1", "nethvoice2", "nethvoice3",
        "openldap1", "openldap2", ""}


def test_flush_counts_every_ingested_line_in_the_digest(flush_lines):
    bundle = flush_lines(FLEET_LINES)
    assert sum(row["observed"] for row in bundle["digest"]) == len(FLEET_LINES)
    assert bundle["budget"]["lines_seen"] == len(FLEET_LINES)


def test_flush_reads_loki_only_for_the_baseline(flush_lines, collector):
    """The stream is the only source of lines and of counts now: the one
    query left is the 168-hour baseline, which cannot come from a window."""
    client = FakeLokiClient()
    flush_lines(FLEET_LINES, client=client)
    assert client.tail_calls == []


# --------------------------------------------------------------------------
# drain_range(): the catch-up paging loop.
# --------------------------------------------------------------------------

def _page(collector, count, first_ns=1000):
    return [(first_ns + i, "<6> [sshd] line {0}".format(i), "", "")
            for i in range(count)]


def test_drain_range_stops_on_a_short_page(collector):
    client = FakeLokiClient(pages=[_page(collector, 3)])
    store = collector.TemplateStore()
    cursor = collector.drain_range(client, store, 0, 9999, "self-id")
    assert len(client.tail_calls) == 1
    assert cursor == 9999
    assert store.lines_seen == 3


def test_drain_range_keeps_reading_after_a_full_page(collector):
    """A full page means Loki had more to give. Advancing one page per tick
    would leave a busy node permanently behind."""
    full = _page(collector, collector.TAIL_LIMIT, first_ns=1000)
    client = FakeLokiClient(pages=[full, _page(collector, 2, first_ns=90000)])
    store = collector.TemplateStore()
    cursor = collector.drain_range(client, store, 0, 999999, "self-id")

    assert len(client.tail_calls) == 2
    # The second page resumes one nanosecond past the first page's last line.
    assert client.tail_calls[1][0] == full[-1][0] + 1
    assert cursor == 999999
    assert store.lines_seen == collector.TAIL_LIMIT + 2


def test_drain_range_leaves_the_cursor_alone_on_a_loki_error(collector):
    """The caller keeps its cursor, so the next tick re-reads the same
    range: a transient Loki restart costs a duplicate count, not a hole."""
    class Failing(FakeLokiClient):
        def tail(self, *args, **kwargs):
            raise collector.LokiError("boom")

    store = collector.TemplateStore()
    with pytest.raises(collector.LokiError):
        collector.drain_range(Failing(), store, 1234, 9999, "self-id")


def test_drain_range_honours_the_stop_flag(collector):
    full = _page(collector, collector.TAIL_LIMIT)
    client = FakeLokiClient(pages=[full, full])
    store = collector.TemplateStore()
    stop = {"flag": True}
    cursor = collector.drain_range(client, store, 500, 9999, "self-id", stop)
    assert client.tail_calls == []
    assert cursor == 500


# --------------------------------------------------------------------------
# --minutes has to reach the baseline step, or `expected` describes a
# different-sized period than `observed` counts.
# --------------------------------------------------------------------------

class RecordingClient(FakeLokiClient):
    def __init__(self):
        super().__init__()
        self.step_seconds = None

    def baseline_series(self, at, range_seconds, step_seconds, denylist,
                        self_identifier):
        self.step_seconds = step_seconds
        return {}


@pytest.mark.parametrize("minutes", [5, 15, 30])
def test_flush_baseline_step_tracks_the_nominal_window(collector, minutes):
    """A step left at 15 minutes while --minutes is 5 would report an
    `expected` three times the population `observed` counts, and the
    deviation gate would quietly stop firing."""
    client = RecordingClient()
    collector.flush(client, collector.TemplateStore(), WINDOW,
                    collector.DEFAULT_MAX_LINES, "self-id", "sys", minutes)
    assert client.step_seconds == minutes * 60


def test_flush_baseline_step_defaults_to_the_module_window(collector):
    client = RecordingClient()
    collector.flush(client, collector.TemplateStore(), WINDOW,
                    collector.DEFAULT_MAX_LINES, "self-id", "sys")
    assert client.step_seconds == collector.WINDOW_MINUTES * 60


def test_flush_baseline_step_ignores_a_partial_window(collector):
    """The tail loop's first window after a restart is whatever the cursor
    left it. That must not shift the baseline buckets."""
    partial = (WINDOW[1] - datetime.timedelta(minutes=2), WINDOW[1])
    client = RecordingClient()
    collector.flush(client, collector.TemplateStore(), partial,
                    collector.DEFAULT_MAX_LINES, "self-id", "sys", 15)
    assert client.step_seconds == 900
