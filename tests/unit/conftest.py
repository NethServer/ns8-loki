#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
import datetime
import importlib.machinery
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "imageroot" / "bin" / "insights-collector"


def _load():
    loader = importlib.machinery.SourceFileLoader("insights_collector", str(SCRIPT))
    spec = importlib.util.spec_from_loader("insights_collector", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def collector():
    """Load imageroot/bin/insights-collector as a module named `insights_collector`.

    The collector has no `.py` extension, so it cannot be imported with a
    plain `import` statement -- it has to be loaded from its source path via
    importlib.machinery.SourceFileLoader instead. Session-scoped because
    loading (executing the module body) must not perform any I/O: the
    collector defers `import agent` to inside read_identity() specifically
    so that importing the module at collection time is safe with no NS8
    `agent` SDK installed and no Redis or Loki reachable.
    """
    return _load()


class FakeLokiClient:
    """Enough of Client to drive drain_range() and flush(), with no HTTP.

    `pages` is a list of tail() results, handed out one per call, so a test
    can make a page exactly TAIL_LIMIT long and watch drain_range keep
    reading. `baseline` and `digest` stand in for the two queries flush()
    still makes; both default to {} the way a failing real one would.
    """

    def __init__(self, pages=(), baseline=None, digest=None):
        self.pages = [list(page) for page in pages]
        self.tail_calls = []
        self._baseline = dict(baseline or {})
        self._digest = dict(digest or {})

    def tail(self, since_ns, until_ns, denylist, self_identifier, limit=None):
        self.tail_calls.append((since_ns, until_ns))
        return self.pages.pop(0) if self.pages else []

    def digest(self, at, range_seconds, denylist, self_identifier):
        return dict(self._digest)

    def baseline_series(self, at, range_seconds, step_seconds, denylist,
                        self_identifier):
        return dict(self._baseline)


WINDOW = (datetime.datetime(2026, 9, 1, 9, 45, tzinfo=datetime.timezone.utc),
          datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc))


@pytest.fixture
def flush_lines(collector):
    """Ingest (ts_ms, text, module_id, category) rows and return the bundle.

    With a single module family, allocate()'s degrade branch makes the
    family's share exactly `max_lines`, so `max_lines` is how these tests
    pin a share the way they used to pass one to group_templates().
    """
    def run(lines, max_lines=collector.DEFAULT_MAX_LINES, client=None,
            store=None):
        store = store if store is not None else collector.TemplateStore()
        for ts_ms, text, module_id, category in lines:
            store.ingest(ts_ms, text, module_id, category)
        return collector.flush(client or FakeLokiClient(), store, WINDOW,
                               max_lines, "self-id", "system-123")
    return run
