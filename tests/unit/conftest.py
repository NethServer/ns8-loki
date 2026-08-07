#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import importlib.machinery
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "imageroot" / "bin" / "insights-collector"

# The collector library ships at imageroot/pypkg, which maps to %E/pypkg in
# the installed module. The entrypoint puts it on sys.path relative to its own
# location; tests do the same so the package imports identically in both.
sys.path.insert(0, str(ROOT / "imageroot" / "pypkg"))


def _load():
    loader = importlib.machinery.SourceFileLoader("insights_collector", str(SCRIPT))
    spec = importlib.util.spec_from_loader("insights_collector", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def collector():
    """The insights-collector script loaded as a module.

    The file has no .py extension, so it cannot be imported normally.
    Loading it must not perform I/O nor import the `agent` SDK.
    """
    return _load()
