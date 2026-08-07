# Loki Anomaly Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an hourly, opt-in job to `ns8-loki` that sends a scrubbed digest of the cluster's journal to an OpenAI-compatible LLM and writes the findings back into the journal.

**Architecture:** One Python script (`imageroot/bin/anomaly-detector`) driven by a `Type=oneshot` service plus an hourly timer. The script queries Loki (logcli for log lines, the Loki HTTP instant-query API for the rate digest and 7-day baseline), scrubs secrets, renders a prompt, POSTs it to `${ANOMALY_LLM_BASE_URL}/chat/completions`, and prints findings as JSON lines on stdout — which under systemd *is* the journal, so findings round-trip back into Loki and serve as the detector's own memory. A single action (`set-anomaly-detector`) writes config to `state/environment`, secrets to `state/secrets.env`, and enables/disables the timer.

**Tech Stack:** Python 3.11+ (the `runagent` interpreter), `requests` + `urllib3.util.Retry` (already used by `cloud-log-manager-forwarder`), `logcli`, the NS8 `agent` Python SDK, systemd user units, `pytest` (new to this repo), Robot Framework + SSHLibrary.

## Global Constraints

- Every new Python file starts with `#!/usr/bin/env python3` then the exact 4-line header:
  ```
  #
  # Copyright (C) 2026 Nethesis S.r.l.
  # SPDX-License-Identifier: GPL-3.0-or-later
  #
  ```
- Executable bits: scripts under `imageroot/bin/` and action steps (`10set`, `10get`, …) are mode **755**. `*.json` schemas and `imageroot/systemd/user/*` unit files are mode **644**.
- All JSON Schema files use draft-04: `"$schema": "http://json-schema.org/draft-04/schema#"` and `"$id": "http://schema.nethserver.org/loki/<action-dir-name>.json"`.
- Systemd unit files use `%E` (never `%S`) — established by commit `045a6cd`. `%E` is the module's install/config dir; `%E/state` is `AGENT_STATE_DIR`.
- `imageroot/` is added to the image wholesale by `build-images.sh` (`buildah add "${container}" imageroot /imageroot`). **No `build-images.sh` change is needed for any new file.**
- The detector is **disabled by default**. `imageroot/actions/create-module/20systemd` is NOT modified.
- Diagnostics go to **stderr only**. stdout carries findings and the summary line and nothing else, because `identifier="<MODULE_ID>/anomaly-detector"` Loki queries must return findings only.
- Log-line ordering constant used everywhere: the display format is
  `<priority> [node_id:module_id:identifier] message`.
- Secrets (`ANOMALY_LLM_API_KEY`, `ANOMALY_WEBHOOK_TOKEN`) NEVER go through `agent.set_env` — that writes `state/environment`, which is mirrored into the Redis hash `module/<id>/environment`.

## Deviations from the design spec (deliberate, with reasons)

These five points differ from `docs/superpowers/specs/2026-07-29-loki-anomaly-detector-design.md`. They are baked into the tasks below; do not "fix" them back.

1. **The script has a `main()` and an `if __name__ == "__main__":` guard, and `import agent` is lazy** (inside `_read_state_envfile`). The two existing forwarders are bare top-level scripts. The spec requires `scrub`, `build_digest`, `render_prompt` and `parse_findings` to be unit-testable with no I/O; that is impossible if the module body runs on import, and the `agent` SDK is not installed in the test container.
2. **The rate digest and baseline use the Loki HTTP instant-query API (`GET /loki/api/v1/query`) via `requests`, not `logcli`.** The spec says "three `logcli` invocations". `logcli`'s output format for *metric* queries is not a documented machine-stable contract, whereas `/loki/api/v1/query` returns a typed vector. Log *lines* still go through `logcli query --forward -o jsonl`, matching `cloud-log-manager-forwarder`. Both paths use the same address and basic-auth credentials, so nothing extra is configured.
3. **Scrub rule order is: keyword → authorization → email → base64/hex blob.** The spec's table lists the blob rule before email; running blob first turns a long email local-part into `<redacted-blob>` and loses the more informative `<redacted-email>` marker.
4. **The nominal early-exit still prints the summary line to stdout** (with `"llm_called": false`), then exits 0. The spec says only "log `nominal, no LLM call`, exit 0". Emitting unconditionally means every window is recorded in Loki (so "quiet hours" are graphable) and makes the Robot test deterministic — otherwise a quiet test node produces no journal output and the `SyslogIdentifier` assertion has nothing to match.
5. **Unit tests use `pytest` in a container via a new `test-unit.sh`, modelled on this repo's `test-module.sh`, not on `core/agent/test-agent.sh`.** The spec cites `core/agent/test-agent.sh` as the pytest-in-a-container template; that script actually runs Robot Framework, and no pytest harness exists anywhere in ns8-core. `test-module.sh` is the real local precedent for "venv in a cached podman volume".

## Verification on the test node

A live single-node cluster is available for step-by-step verification:

```bash
ssh root@rl1.leader.default.gs.nethserver.net
```

Facts established by probing it on 2026-07-29 (do not re-derive these):

| Fact | Value |
|------|-------|
| Module instance | `loki1`, running (`loki`, `loki-server`, `traefik` all active) |
| `%E` | `/home/loki1/.config` |
| `AGENT_STATE_DIR` (action/`runagent` CWD) | `/home/loki1/.config/state` |
| Unit directory | `/home/loki1/.config/systemd/user/` |
| `LOKI_HTTP_PORT` | `20000` |
| `logcli` | `/usr/local/bin/logcli`, on PATH under `runagent` |
| Python | 3.11.13 |
| Other modules present | `crowdsec1`, `nethvoice2`, `nethvoice-proxy1`, `metrics1`, `samba2`, `traefik1` |

Already verified against this node, so treat these as settled:

- **The instant metric query works.** `GET /loki/api/v1/query` with
  `sum by (module_id, priority) (count_over_time({node_id=~".+"} | json priority="PRIORITY" [3600s]))`
  returns `status: success`, `resultType: vector`, 11 series.
- **Some series have no `module_id`** (host-level logs, e.g. `sshd-session`), so
  the metric label map is `{"priority": "3"}` with no `module_id` key. This is why
  `parse_metric_response` maps a missing label to `"unknown"`.
- **The prefiltered lines query works** through `logcli query --forward -o jsonl`
  with the full pipeline, including the `identifier !=` exclusion and
  `| priority < 5 or category="security"`. Priority-6 `sshd-session` lines are
  correctly returned via the `category="security"` branch.
- **Size reality check:** one hour returned **382 lines / ~36k characters /
  ~9k tokens** for the `LINES` block alone. That is above the spec's 4–6k target
  per window. Keep the documented default of `max_lines: 500` — the spec fixes it
  — but expect ~9k tokens on a node of this size and say so in the final
  verification, so tuning `max_lines` down is an informed operator choice rather
  than a surprise.

### The LLM endpoint used for verification

Real-LLM verification uses OpenRouter. The credentials live in `./open_router` in the
repo root, which is git-ignored — **never commit the key, never paste it into a
report, a test file, or a plan**. Read it at use time:

```bash
ORKEY=$(grep -oE 'sk-or-[A-Za-z0-9._-]+' open_router | head -1)
```

| Setting | Value |
|---------|-------|
| `ANOMALY_LLM_BASE_URL` | `https://openrouter.ai/api/v1` |
| `ANOMALY_LLM_MODEL` | `google/gemma-4-26b-a4b-it:free` |

The base URL is a configured value, never hardcoded: it arrives via the action's
`base_url` field or the `ANOMALY_LLM_BASE_URL` variable, and `ask_llm` appends
`/chat/completions` to it. Any OpenAI-compatible endpoint works unchanged.

Verified against this endpoint on 2026-07-29 with the plan's exact
`RESPONSE_SCHEMA` and a prompt built from real `rl1` log lines:

- **`response_format: {"type": "json_schema", "strict": true}` is honoured.** The
  reply parsed as JSON and matched the schema, including the `severity` and
  `window_assessment` enums.
- **It is load-bearing, not optional.** The identical request *without*
  `response_format` came back wrapped in a ```` ```json ```` fence with an invented
  shape (`{"deviations": [...]}`), which `parse_findings` would correctly reject.
  Never make `response_format` conditional.
- **Prompt quality is real**, not just well-formed: given a `crowdsec1` priority-3
  rate 14× above baseline plus three matching log lines, the model returned one
  `high` finding titled "SSH Brute-Force Attack Detected" naming the offending IP,
  with `window_assessment: degraded`.
- **Known prompt-adherence wrinkle:** the model put a `RATES` row into `evidence`
  even though `SYSTEM_PROMPT` says to quote evidence verbatim from `LINES`.
  `parse_findings` does not verify evidence provenance, and this does not block
  anything — do not add provenance validation, it is out of scope.

CI never touches this endpoint. The Robot suite in Task 9 uses the offline stub, so
tests stay deterministic with no egress and no cost.

### Deploying to the node between tasks

The module is installed, so files can be synced in place instead of rebuilding
the image. Run from the repo root:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
rsync -a --rsync-path='rsync' imageroot/ ${NODE}:/tmp/imageroot-staged/
ssh ${NODE} 'cp -a /tmp/imageroot-staged/. /home/loki1/.config/ \
  && chown -R loki1:loki1 /home/loki1/.config \
  && runagent -m loki1 systemctl --user daemon-reload'
```

For a script-only change, the spec's documented manual path needs no sync at all:

```bash
scp imageroot/bin/anomaly-detector ${NODE}:/tmp/
ssh ${NODE} runagent -m loki1 python3 /tmp/anomaly-detector --dry-run --since 2h
```

Each task below states what to verify on the node. Tasks 1–3 are pure functions
with no node step. Tasks 4, 5, 6, 7 and 8 each end with a node check.

## File Structure

**Create:**

| Path | Responsibility |
|------|----------------|
| `imageroot/bin/anomaly-detector` | the whole job + the CLI; pure helpers at top level, all I/O behind `main()` |
| `imageroot/systemd/user/anomaly-detector.service` | `Type=oneshot`, one window per invocation |
| `imageroot/systemd/user/anomaly-detector.timer` | `OnCalendar=hourly`, `Persistent=true` |
| `imageroot/actions/set-anomaly-detector/validate-input.json` | draft-04 schema, `oneOf` on `active` |
| `imageroot/actions/set-anomaly-detector/10set` | write env + secrets, enable/disable the timer |
| `imageroot/update-module.d/15systemd` | `systemctl --user daemon-reload` so new units land on an already-installed module |
| `tests/unit/conftest.py` | loads the extension-less script as an importable module |
| `tests/unit/requirements.txt` | `pytest`, `requests` |
| `tests/unit/test_anomaly_detector.py` | pytest suite for the pure helpers |
| `test-unit.sh` | runs pytest in a `python:3.11-alpine` container |
| `.github/workflows/test-unit.yml` | runs `./test-unit.sh` on push/PR |
| `tests/llm-stub.py` | canned OpenAI-shaped HTTP server, copied to the node by the Robot test |
| `tests/20__anomaly_detector.robot` | end-to-end test against the stub |

**Modify:**

| Path | Change |
|------|--------|
| `imageroot/actions/get-configuration/10get` | add the `anomaly_detector` object |
| `imageroot/actions/get-configuration/validate-output.json` | declare `anomaly_detector` |
| `imageroot/etc/state-include.conf` | add `state/secrets.env` |
| `README.md` | new `### set-anomaly-detector` API section, manual-run section, privacy statement |

**Function inventory of `imageroot/bin/anomaly-detector`** (built up across Tasks 1–5; every later task's `Interfaces` block repeats the signatures it needs):

```
# pure — unit tested
scrub(line) -> str
sanitize_line(raw) -> str
parse_duration(text) -> timedelta
compute_window(now, since=None) -> (datetime, datetime)
parse_metric_response(payload) -> dict[(str, str), float]
build_digest(rates, baseline) -> list[dict]
is_nominal(lines, digest, tolerance=3.0) -> bool
estimate_tokens(text) -> int
render_prompt(window, digest, recent_findings, lines, truncated) -> str
build_request_body(model, user_prompt) -> dict
extract_content(payload) -> str
parse_findings(body) -> (list[dict], str)
render_findings(findings, assessment, window, truncated, llm_called, pretty) -> list[str]
load_config(args, environ, reader) -> dict

# I/O
_read_state_envfile(path) -> dict
make_session() -> requests.Session
query_metric(session, addr, auth, query, at) -> dict[(str, str), float]
query_lines(session_unused, window, max_lines, module_id) -> (list[dict], bool)
recall_findings(module_id, limit=10) -> list[dict]
ask_llm(session, config, prompt) -> str
post_webhook(session, config, payload) -> None
main(argv=None) -> int
```

---

### Task 1: Unit-test harness and `scrub()`

Creates the script file, its import-safe skeleton, the pytest harness, and the first pure function.

**Files:**
- Create: `imageroot/bin/anomaly-detector`
- Create: `tests/unit/requirements.txt`
- Create: `tests/unit/conftest.py`
- Create: `tests/unit/test_anomaly_detector.py`
- Create: `test-unit.sh`
- Create: `.github/workflows/test-unit.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: `scrub(line) -> str`; `sanitize_line(raw) -> str`; the module-level constant `SCRUB_RULES`; the conftest fixture `ad` (the loaded module object) available to every later test file.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/requirements.txt`:

```
pytest
requests
```

Create `tests/unit/conftest.py`:

```python
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import importlib.machinery
import importlib.util
import pathlib

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "imageroot" / "bin" / "anomaly-detector"


def _load():
    loader = importlib.machinery.SourceFileLoader("anomaly_detector", str(SCRIPT))
    spec = importlib.util.spec_from_loader("anomaly_detector", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def ad():
    """The anomaly-detector script loaded as a module.

    The file has no .py extension, so it cannot be imported normally.
    Loading it must not perform I/O nor import the `agent` SDK.
    """
    return _load()
```

Create `tests/unit/test_anomaly_detector.py`:

```python
#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import pytest


class TestScrub:
    @pytest.mark.parametrize("raw", [
        'login failed password=hunter2',
        'login failed password: hunter2',
        'sent Bearer eyJhbGciOi',
        'using api_key=abc123def',
        'using api-key: abc123def',
        'set SECRET="s3kr1t"',
        'cfg passwd=root pwd=root',
        'token=ghp_0123456789',
    ])
    def test_secret_keywords_are_redacted(self, ad, raw):
        out = ad.scrub(raw)
        assert "<redacted>" in out
        for leaked in ("hunter2", "eyJhbGciOi", "abc123def", "s3kr1t", "ghp_0123456789"):
            assert leaked not in out

    @pytest.mark.parametrize("raw", [
        'password reset requested for user bob',
        'the token bucket is full',
        'secret santa module started',
    ])
    def test_keyword_without_assignment_is_kept(self, ad, raw):
        assert ad.scrub(raw) == raw

    def test_authorization_header_is_redacted(self, ad):
        out = ad.scrub('GET /api Authorization: Basic bG9raTpwYXNz')
        assert out == 'GET /api authorization: <redacted>'

    def test_authorization_word_alone_is_kept(self, ad):
        raw = 'authorization succeeded for node 3'
        assert ad.scrub(raw) == raw

    def test_long_blob_is_redacted(self, ad):
        raw = 'cookie 0123456789abcdef0123456789abcdef0123'
        assert ad.scrub(raw) == 'cookie <redacted-blob>'

    def test_short_hex_is_kept(self, ad):
        raw = 'commit 6417fba failed'
        assert ad.scrub(raw) == raw

    def test_email_is_redacted(self, ad):
        out = ad.scrub('bounce to admin@example.org failed')
        assert out == 'bounce to <redacted-email> failed'

    def test_bare_at_sign_is_kept(self, ad):
        raw = 'resolved loki@cluster to loki1'
        assert ad.scrub(raw) == raw

    def test_signal_carrying_values_survive(self, ad):
        raw = 'nethvoice2: 192.168.1.44 -> rl1.example.com refused for user bob'
        out = ad.scrub(raw)
        assert '192.168.1.44' in out
        assert 'nethvoice2' in out
        assert 'rl1.example.com' in out
        assert 'bob' in out

    def test_email_rule_wins_over_blob_rule(self, ad):
        # A 32+ char local part must still be reported as an email, not a blob.
        out = ad.scrub('mail to abcdefghijabcdefghijabcdefghijabc@example.org')
        assert out == 'mail to <redacted-email>'

    def test_scrub_is_idempotent(self, ad):
        once = ad.scrub('password=hunter2 and admin@example.org')
        assert ad.scrub(once) == once


class TestSanitizeLine:
    def test_embedded_newlines_are_collapsed(self, ad):
        # Observed on a live node: crowdsec messages carry a trailing \n, and a
        # multi-line message would otherwise forge extra lines in the prompt's
        # LINES block.
        raw = '<3> [1:crowdsec1:crowdsec1] alert\nlevel=info msg="x"\n'
        assert ad.sanitize_line(raw) == '<3> [1:crowdsec1:crowdsec1] alert level=info msg="x"'

    def test_carriage_returns_and_tabs_are_collapsed(self, ad):
        assert ad.sanitize_line('a\r\nb\tc') == 'a b c'

    def test_runs_of_whitespace_collapse_to_one_space(self, ad):
        assert ad.sanitize_line('a     b') == 'a b'

    def test_it_also_scrubs(self, ad):
        assert ad.sanitize_line('token=abc\ndef') == 'token=<redacted> def'

    def test_empty_and_blank(self, ad):
        assert ad.sanitize_line('') == ''
        assert ad.sanitize_line('   \n  ') == ''

    def test_a_forged_fence_cannot_escape_the_block(self, ad):
        # A log message must never be able to close the LINES fence.
        out = ad.sanitize_line('boom\n```\nWINDOW\n```')
        assert '\n' not in out
```

Create `test-unit.sh` (mode 755):

```bash
#!/bin/bash

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

# Run the anomaly-detector unit tests in a container.
#
#   ./test-unit.sh [PYTEST ARG]...

set -e

venvroot=/usr/local/venv

exec podman run -i --rm \
    --volume=.:/srv/source:z \
    --volume=pytest-cache:${venvroot}:z \
    --replace --name=pytest-unit \
    --env=venvroot \
    docker.io/python:3.11-alpine \
    ash -l -s -- "${@}" <<'EOF'
set -e
if [ ! -x ${venvroot}/bin/pytest ] ; then
    python3 -mvenv ${venvroot} --upgrade
    ${venvroot}/bin/pip3 install -q -r /srv/source/tests/unit/requirements.txt
fi
cd /srv/source
exec ${venvroot}/bin/pytest -q "${@}" tests/unit/
EOF
```

Create `.github/workflows/test-unit.yml`:

```yaml
name: Unit tests

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run unit tests
        run: ./test-unit.sh
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
chmod +x test-unit.sh
./test-unit.sh
```

Expected: collection error — `FileNotFoundError` / `No such file or directory: '.../imageroot/bin/anomaly-detector'`.

- [ ] **Step 3: Write the minimal implementation**

Create `imageroot/bin/anomaly-detector` (mode 755):

```python
#!/usr/bin/env python3

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

#
# Analyse one hour of NS8 journal logs with a remote LLM and write the
# findings back to the journal. Diagnostics go to stderr; stdout carries
# findings only.
#

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

#-------------------------------- SCRUB ---------------------------------#

# Ordered: keyword assignments, then Authorization headers, then email
# addresses, then long opaque blobs. Email runs before the blob rule so a
# long local part is still reported as an email.
SCRUB_RULES = [
    (
        re.compile(r'(?i)\b(bearer|tokens?|api[-_]?keys?|secrets?|passwords?|passwd|pwd)\b[=:\s"\']+\S+'),
        r'\1=<redacted>',
    ),
    (
        re.compile(r'(?i)\bauthorization:\s*\S+(?:\s+\S+)?'),
        'authorization: <redacted>',
    ),
    (
        re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+\b'),
        '<redacted-email>',
    ),
    (
        re.compile(r'\b[A-Za-z0-9+/]{32,}={0,2}\b'),
        '<redacted-blob>',
    ),
]


WHITESPACE_RUN = re.compile(r'\s+')


def scrub(line):
    """Remove likely secrets from a log line.

    Defence in depth, not a guarantee. IP addresses, hostnames, module IDs
    and usernames are deliberately preserved: they carry the signal.
    """
    for pattern, replacement in SCRUB_RULES:
        line = pattern.sub(replacement, line)
    return line


def sanitize_line(raw):
    """Flatten a collected log line to exactly one prompt line, then scrub.

    Journal messages can contain newlines. Left alone they would break the
    one-record-per-line structure of the prompt's LINES block, letting a log
    message forge additional lines or close the fence.
    """
    return scrub(WHITESPACE_RUN.sub(' ', raw).strip())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./test-unit.sh
```

Expected: all `TestScrub` tests PASS.

If `test_secret_keywords_are_redacted` fails on `'sent Bearer eyJhbGciOi'` because the replacement emits `Bearer=<redacted>` — that is correct and expected; the assertion only checks that `<redacted>` is present and the value is gone.

- [ ] **Step 5: Commit**

```bash
git add imageroot/bin/anomaly-detector tests/unit test-unit.sh .github/workflows/test-unit.yml
git commit -m "feat(anomaly-detector): add script skeleton, scrub() and pytest harness"
```

---

### Task 2: Window arithmetic and the rate digest

**Files:**
- Modify: `imageroot/bin/anomaly-detector` (append after `scrub`)
- Modify: `tests/unit/test_anomaly_detector.py` (append test classes)

**Interfaces:**
- Consumes: nothing from Task 1 beyond the module skeleton.
- Produces:
  - `parse_duration(text) -> timedelta` — accepts `30m`, `6h`, `2d`; raises `ValueError` otherwise.
  - `compute_window(now, since=None) -> (datetime, datetime)`
  - `parse_metric_response(payload) -> dict[(module_id, priority) -> float]`
  - `build_digest(rates, baseline) -> list[dict]` with keys `module_id`, `priority`, `observed`, `expected`, `ratio` (`ratio` is `None` when `expected == 0`).
  - `is_nominal(lines, digest, tolerance=3.0) -> bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_anomaly_detector.py`:

```python
from datetime import datetime, timedelta, timezone


class TestParseDuration:
    @pytest.mark.parametrize("text,expected", [
        ("30m", timedelta(minutes=30)),
        ("6h", timedelta(hours=6)),
        ("2d", timedelta(days=2)),
        (" 1h ", timedelta(hours=1)),
    ])
    def test_valid(self, ad, text, expected):
        assert ad.parse_duration(text) == expected

    @pytest.mark.parametrize("text", ["", "h", "1w", "1.5h", "-1h", "1 h", "abc"])
    def test_invalid(self, ad, text):
        with pytest.raises(ValueError):
            ad.parse_duration(text)


class TestComputeWindow:
    def test_default_is_the_previous_full_hour(self, ad):
        now = datetime(2026, 7, 29, 14, 7, 33, tzinfo=timezone.utc)
        start, end = ad.compute_window(now)
        assert start == datetime(2026, 7, 29, 13, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 7, 29, 14, 0, 0, tzinfo=timezone.utc)

    def test_exactly_on_the_hour(self, ad):
        now = datetime(2026, 7, 29, 14, 0, 0, tzinfo=timezone.utc)
        start, end = ad.compute_window(now)
        assert start == datetime(2026, 7, 29, 13, 0, 0, tzinfo=timezone.utc)
        assert end == now

    def test_since_ends_at_now(self, ad):
        now = datetime(2026, 7, 29, 14, 7, 33, tzinfo=timezone.utc)
        start, end = ad.compute_window(now, since="2h")
        assert end == now
        assert start == datetime(2026, 7, 29, 12, 7, 33, tzinfo=timezone.utc)


class TestParseMetricResponse:
    def test_extracts_labels_and_values(self, ad):
        payload = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {"metric": {"module_id": "nethvoice2", "priority": "6"},
                     "value": [1769000000, "656"]},
                    {"metric": {"module_id": "loki1", "priority": "3"},
                     "value": [1769000000, "4"]},
                ],
            },
        }
        assert ad.parse_metric_response(payload) == {
            ("nethvoice2", "6"): 656.0,
            ("loki1", "3"): 4.0,
        }

    def test_missing_labels_become_unknown(self, ad):
        payload = {"data": {"result": [{"metric": {}, "value": [0, "2"]}]}}
        assert ad.parse_metric_response(payload) == {("unknown", "unknown"): 2.0}

    def test_empty_result(self, ad):
        assert ad.parse_metric_response({"data": {"result": []}}) == {}

    def test_missing_data_key_raises(self, ad):
        with pytest.raises(ValueError):
            ad.parse_metric_response({"status": "error"})


class TestBuildDigest:
    def test_pairs_observed_with_expected(self, ad):
        rates = {("nethvoice2", "6"): 656.0, ("loki1", "3"): 4.0}
        baseline = {("nethvoice2", "6"): 600.0, ("mail1", "4"): 10.0}
        assert ad.build_digest(rates, baseline) == [
            {"module_id": "loki1", "priority": "3",
             "observed": 4.0, "expected": 0.0, "ratio": None},
            {"module_id": "mail1", "priority": "4",
             "observed": 0.0, "expected": 10.0, "ratio": 0.0},
            {"module_id": "nethvoice2", "priority": "6",
             "observed": 656.0, "expected": 600.0, "ratio": 1.09},
        ]

    def test_rounds_to_two_decimals(self, ad):
        rates = {("a", "6"): 1.0 / 3.0}
        baseline = {("a", "6"): 1.0 / 7.0}
        row = ad.build_digest(rates, baseline)[0]
        assert row["observed"] == 0.33
        assert row["expected"] == 0.14
        assert row["ratio"] == 2.33

    def test_empty_inputs(self, ad):
        assert ad.build_digest({}, {}) == []


class TestIsNominal:
    def test_lines_present_is_never_nominal(self, ad):
        assert ad.is_nominal([{"line": "x"}], []) is False

    def test_no_lines_and_rates_on_baseline(self, ad):
        digest = [{"module_id": "a", "priority": "6",
                   "observed": 100.0, "expected": 90.0, "ratio": 1.11}]
        assert ad.is_nominal([], digest) is True

    def test_spike_above_tolerance(self, ad):
        digest = [{"module_id": "a", "priority": "6",
                   "observed": 400.0, "expected": 100.0, "ratio": 4.0}]
        assert ad.is_nominal([], digest) is False

    def test_new_pair_with_no_baseline_is_not_nominal(self, ad):
        digest = [{"module_id": "new1", "priority": "6",
                   "observed": 5.0, "expected": 0.0, "ratio": None}]
        assert ad.is_nominal([], digest) is False

    def test_pair_that_went_silent_is_nominal(self, ad):
        digest = [{"module_id": "a", "priority": "6",
                   "observed": 0.0, "expected": 50.0, "ratio": 0.0}]
        assert ad.is_nominal([], digest) is True

    def test_everything_empty_is_nominal(self, ad):
        assert ad.is_nominal([], []) is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./test-unit.sh tests/unit/test_anomaly_detector.py -k "Duration or Window or Metric or Digest or Nominal"
```

Expected: FAIL with `AttributeError: module 'anomaly_detector' has no attribute 'parse_duration'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `imageroot/bin/anomaly-detector`:

```python
#-------------------------------- WINDOW --------------------------------#

DURATION_UNITS = {'m': 'minutes', 'h': 'hours', 'd': 'days'}
DURATION_RE = re.compile(r'^(\d+)([mhd])$')

# A pair whose observed count exceeds expected by this factor is a spike.
NOMINAL_TOLERANCE = 3.0

# Hours in 7 days: the baseline query divisor.
BASELINE_HOURS = 168


def parse_duration(text):
    """Parse a duration such as 30m, 6h or 2d into a timedelta."""
    match = DURATION_RE.match(text.strip())
    if not match:
        raise ValueError(f"invalid duration {text!r}: expected <int>[mhd]")
    return timedelta(**{DURATION_UNITS[match.group(2)]: int(match.group(1))})


def compute_window(now, since=None):
    """Return the [start, end) window to analyse.

    Default: the previous full hour, derived from the wall clock, so there
    is no cursor file and no drift. With `since`: [now - since, now].
    """
    if since:
        end = now
        start = end - parse_duration(since)
    else:
        end = now.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=1)
    return start, end


def parse_metric_response(payload):
    """Turn a Loki instant-query vector into {(module_id, priority): value}."""
    try:
        result = payload["data"]["result"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"unexpected metric response shape: {exc}") from exc
    rates = {}
    for entry in result:
        metric = entry.get("metric") or {}
        key = (metric.get("module_id") or "unknown", metric.get("priority") or "unknown")
        rates[key] = float(entry["value"][1])
    return rates


def build_digest(rates, baseline):
    """Join observed counts with expected counts, sorted for a stable prompt."""
    rows = []
    for key in sorted(set(rates) | set(baseline)):
        module_id, priority = key
        observed = rates.get(key, 0.0)
        expected = baseline.get(key, 0.0)
        rows.append({
            "module_id": module_id,
            "priority": priority,
            "observed": round(observed, 2),
            "expected": round(expected, 2),
            "ratio": round(observed / expected, 2) if expected > 0 else None,
        })
    return rows


def is_nominal(lines, digest, tolerance=NOMINAL_TOLERANCE):
    """True when the window is not worth an LLM call.

    Requires zero prefiltered lines and no rate pair above tolerance. A
    pair with no baseline at all counts as a deviation if it produced
    anything: it is new behaviour.
    """
    if lines:
        return False
    for row in digest:
        if row["ratio"] is None:
            if row["observed"] > 0:
                return False
        elif row["ratio"] > tolerance:
            return False
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./test-unit.sh
```

Expected: every test PASSES.

- [ ] **Step 5: Commit**

```bash
git add imageroot/bin/anomaly-detector tests/unit/test_anomaly_detector.py
git commit -m "feat(anomaly-detector): add window arithmetic and rate digest"
```

---

### Task 3: Prompt rendering and response parsing

**Files:**
- Modify: `imageroot/bin/anomaly-detector` (append)
- Modify: `tests/unit/test_anomaly_detector.py` (append)

**Interfaces:**
- Consumes: `scrub(line)` (Task 1); `build_digest` output rows (Task 2).
- Produces:
  - `estimate_tokens(text) -> int`
  - `SYSTEM_PROMPT` (str constant)
  - `RESPONSE_SCHEMA` (dict constant)
  - `render_prompt(window, digest, recent_findings, lines, truncated) -> str` — `window` is the `(start, end)` tuple; `recent_findings` is a list of `{"severity", "title"}`; `lines` is a list of already-formatted strings.
  - `build_request_body(model, user_prompt) -> dict`
  - `extract_content(payload) -> str`
  - `parse_findings(body) -> (findings, assessment)`; raises `ValueError` on any schema violation.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_anomaly_detector.py`:

```python
import json


WINDOW = (
    datetime(2026, 7, 29, 13, 0, tzinfo=timezone.utc),
    datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc),
)


class TestEstimateTokens:
    def test_roughly_four_chars_per_token(self, ad):
        assert ad.estimate_tokens("a" * 400) == 100

    def test_empty(self, ad):
        assert ad.estimate_tokens("") == 0


class TestRenderPrompt:
    def _render(self, ad, **kw):
        params = {
            "window": WINDOW,
            "digest": [{"module_id": "nethvoice2", "priority": "3",
                        "observed": 40.0, "expected": 2.0, "ratio": 20.0}],
            "recent_findings": [{"severity": "high", "title": "asterisk restart loop"}],
            "lines": ["<3> [1:nethvoice2:asterisk] registration failed"],
            "truncated": False,
        }
        params.update(kw)
        return ad.render_prompt(**params)

    def test_contains_all_four_blocks(self, ad):
        out = self._render(ad)
        for block in ("WINDOW", "RATES", "RECENT_FINDINGS", "LINES"):
            assert block in out

    def test_window_timestamps_are_iso(self, ad):
        out = self._render(ad)
        assert "2026-07-29T13:00:00+00:00" in out
        assert "2026-07-29T14:00:00+00:00" in out

    def test_rate_row_shows_observed_and_expected(self, ad):
        out = self._render(ad)
        assert "nethvoice2" in out
        assert "40.0" in out
        assert "2.0" in out

    def test_truncation_is_declared(self, ad):
        assert "truncated: yes" in self._render(ad, truncated=True)
        assert "truncated: no" in self._render(ad, truncated=False)

    def test_empty_sections_are_explicit_not_blank(self, ad):
        out = self._render(ad, recent_findings=[], lines=[], digest=[])
        assert "(none)" in out

    def test_recent_finding_titles_are_present(self, ad):
        assert "asterisk restart loop" in self._render(ad)

    def test_prompt_body_is_scrubbed(self, ad):
        out = self._render(ad, recent_findings=[
            {"severity": "high", "title": "leaked api_key=abc123def"}])
        assert "abc123def" not in out


class TestBuildRequestBody:
    def test_shape(self, ad):
        body = ad.build_request_body("gpt-4o-mini", "USER")
        assert body["model"] == "gpt-4o-mini"
        assert body["temperature"] == 0
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1] == {"role": "user", "content": "USER"}
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["schema"] == ad.RESPONSE_SCHEMA


class TestExtractContent:
    def test_reads_the_first_choice(self, ad):
        payload = {"choices": [{"message": {"content": "{}"}}]}
        assert ad.extract_content(payload) == "{}"

    @pytest.mark.parametrize("payload", [
        {}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": {}}]},
    ])
    def test_bad_shapes_raise(self, ad, payload):
        with pytest.raises(ValueError):
            ad.extract_content(payload)


class TestParseFindings:
    def _body(self, **kw):
        payload = {
            "window_assessment": "degraded",
            "findings": [{
                "severity": "high",
                "title": "asterisk registration storm",
                "summary": "40 failures against a baseline of 2",
                "evidence": ["<3> [1:nethvoice2:asterisk] registration failed"],
                "modules": ["nethvoice2"],
                "suggested_action": "check SIP trunk credentials",
            }],
        }
        payload.update(kw)
        return json.dumps(payload)

    def test_valid_response(self, ad):
        findings, assessment = ad.parse_findings(self._body())
        assert assessment == "degraded"
        assert len(findings) == 1
        assert findings[0]["title"] == "asterisk registration storm"

    def test_empty_findings_is_valid(self, ad):
        findings, assessment = ad.parse_findings(
            self._body(findings=[], window_assessment="nominal"))
        assert findings == []
        assert assessment == "nominal"

    @pytest.mark.parametrize("body", [
        "not json",
        "[]",
        '"a string"',
        '{"findings": []}',
        '{"window_assessment": "weird", "findings": []}',
        '{"window_assessment": "nominal", "findings": {}}',
        '{"window_assessment": "nominal", "findings": ["a string"]}',
    ])
    def test_invalid_envelopes_raise(self, ad, body):
        with pytest.raises(ValueError):
            ad.parse_findings(body)

    @pytest.mark.parametrize("bad", [
        {"severity": "catastrophic"},
        {"title": ""},
        {"summary": None},
    ])
    def test_invalid_finding_fields_raise(self, ad, bad):
        finding = {
            "severity": "high", "title": "t", "summary": "s",
            "evidence": [], "modules": [], "suggested_action": "a",
        }
        finding.update(bad)
        with pytest.raises(ValueError):
            ad.parse_findings(json.dumps(
                {"window_assessment": "nominal", "findings": [finding]}))

    def test_missing_optional_lists_default_to_empty(self, ad):
        finding = {"severity": "low", "title": "t", "summary": "s"}
        findings, _ = ad.parse_findings(json.dumps(
            {"window_assessment": "nominal", "findings": [finding]}))
        assert findings[0]["evidence"] == []
        assert findings[0]["modules"] == []
        assert findings[0]["suggested_action"] == ""

    def test_findings_are_scrubbed_again(self, ad):
        finding = {
            "severity": "low", "title": "t",
            "summary": "leaked password=hunter2",
            "evidence": ["password=hunter2"],
        }
        findings, _ = ad.parse_findings(json.dumps(
            {"window_assessment": "nominal", "findings": [finding]}))
        assert "hunter2" not in findings[0]["summary"]
        assert "hunter2" not in findings[0]["evidence"][0]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./test-unit.sh -k "FormatLine or EstimateTokens or RenderPrompt or RequestBody or ExtractContent or ParseFindings"
```

Expected: FAIL with `AttributeError: module 'anomaly_detector' has no attribute 'format_line'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `imageroot/bin/anomaly-detector`:

```python
#-------------------------------- PROMPT --------------------------------#

SEVERITIES = ("critical", "high", "medium", "low")
ASSESSMENTS = ("nominal", "degraded", "incident")

SYSTEM_PROMPT = (
    "You are a log analyst for a NethServer 8 cluster. You judge one hour of "
    "journal logs against the supplied per-module baseline.\n"
    "Report only actionable deviations from that baseline. Routine, expected "
    "and self-healing events are not findings. An empty findings list is the "
    "normal and expected answer.\n"
    "Never restate a finding listed under RECENT_FINDINGS unless it has "
    "clearly escalated; if it has, say so in the summary.\n"
    "Quote evidence verbatim from the LINES block. Never invent a log line.\n"
    "Keep each title short, specific and stable across hours so that repeats "
    "can be deduplicated by title.\n"
    "Answer with JSON matching the supplied schema and nothing else."
)

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "window_assessment"],
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "title", "summary", "evidence",
                             "modules", "suggested_action"],
                "properties": {
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "modules": {"type": "array", "items": {"type": "string"}},
                    "suggested_action": {"type": "string"},
                },
            },
        },
        "window_assessment": {"type": "string", "enum": list(ASSESSMENTS)},
    },
}


def estimate_tokens(text):
    """Rough token count for --dry-run reporting: 4 characters per token."""
    return len(text) // 4


def _block(name, body):
    return f"{name}\n```\n{body or '(none)'}\n```\n"


def render_prompt(window, digest, recent_findings, lines, truncated):
    """Render the user message. Everything here is already scrubbed."""
    start, end = window
    window_body = "\n".join([
        f"start: {start.isoformat()}",
        f"end: {end.isoformat()}",
        f"truncated: {'yes' if truncated else 'no'}",
    ])

    rates_body = "\n".join(
        "{0} priority={1} observed={2} expected={3} ratio={4}".format(
            row["module_id"], row["priority"], row["observed"], row["expected"],
            "n/a" if row["ratio"] is None else row["ratio"],
        )
        for row in digest
    )

    findings_body = "\n".join(
        scrub("{0}: {1}".format(item.get("severity", "?"), item.get("title", "")))
        for item in recent_findings
    )

    return "".join([
        _block("WINDOW", window_body),
        _block("RATES", rates_body),
        _block("RECENT_FINDINGS", findings_body),
        _block("LINES", "\n".join(lines)),
    ])


def build_request_body(model, user_prompt):
    """The OpenAI-compatible chat completions request."""
    return {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "anomaly_report",
                "strict": True,
                "schema": RESPONSE_SCHEMA,
            },
        },
    }


def extract_content(payload):
    """Pull the assistant message out of a chat completions response."""
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"unexpected completion shape: {exc}") from exc
    if not isinstance(content, str):
        raise ValueError("completion content is not a string")
    return content


def _require_str(finding, key, allow_empty=False):
    value = finding.get(key, "" if allow_empty else None)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError(f"finding field {key!r} is invalid: {value!r}")
    return scrub(value)


def _require_str_list(finding, key):
    value = finding.get(key, [])
    if not isinstance(value, list) or not all(isinstance(i, str) for i in value):
        raise ValueError(f"finding field {key!r} is not a list of strings")
    return [scrub(item) for item in value]


def parse_findings(body):
    """Validate the LLM answer. Raise ValueError rather than emit a partial."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"response is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("response is not a JSON object")

    assessment = payload.get("window_assessment")
    if assessment not in ASSESSMENTS:
        raise ValueError(f"invalid window_assessment: {assessment!r}")

    raw_findings = payload.get("findings")
    if not isinstance(raw_findings, list):
        raise ValueError("findings is not a list")

    findings = []
    for item in raw_findings:
        if not isinstance(item, dict):
            raise ValueError("finding is not an object")
        severity = item.get("severity")
        if severity not in SEVERITIES:
            raise ValueError(f"invalid severity: {severity!r}")
        findings.append({
            "severity": severity,
            "title": _require_str(item, "title"),
            "summary": _require_str(item, "summary"),
            "evidence": _require_str_list(item, "evidence"),
            "modules": _require_str_list(item, "modules"),
            "suggested_action": _require_str(item, "suggested_action", allow_empty=True),
        })
    return findings, assessment
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./test-unit.sh
```

Expected: every test PASSES.

- [ ] **Step 5: Commit**

```bash
git add imageroot/bin/anomaly-detector tests/unit/test_anomaly_detector.py
git commit -m "feat(anomaly-detector): render the prompt and validate the response"
```

---

### Task 4: Loki collection

**Files:**
- Modify: `imageroot/bin/anomaly-detector` (append)
- Modify: `tests/unit/test_anomaly_detector.py` (append)

**Interfaces:**
- Consumes: `parse_metric_response` (Task 2), `scrub` (Task 1).
- Produces:
  - `LINE_FORMAT` (str constant) — the LogQL `line_format` stage that renders
    `<priority> [node_id:module_id:identifier] message` server-side. This is the
    single definition of the display format; nothing renders lines in Python.
  - `logql_duration(delta) -> str` — a timedelta as LogQL seconds, e.g. `3600s`.
  - `build_metric_query(range_text) -> str`
  - `build_lines_query(module_id) -> str`
  - `build_recall_query(module_id) -> str`
  - `run_logcli(argv, timeout=LOGCLI_TIMEOUT) -> str` — raises `RuntimeError` on non-zero exit or timeout.
  - `parse_jsonl_records(stdout) -> list[dict]` — one dict per `logcli -o jsonl` line, with keys `priority`, `node_id`, `module_id`, `identifier`, `message`.
  - `query_metric(session, addr, auth, query, at) -> dict`
  - `query_lines(window, max_lines, module_id) -> (records, truncated)`
  - `recall_findings(window_end, module_id, limit=10) -> list[dict]` of `{"severity", "title"}`
  - `loki_env() -> (addr, (username, password))` — also sets `LOKI_ADDR`/`LOKI_USERNAME`/`LOKI_PASSWORD` in `os.environ` for `logcli`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_anomaly_detector.py`:

```python
import subprocess


class TestLogqlDuration:
    def test_hour(self, ad):
        assert ad.logql_duration(timedelta(hours=1)) == "3600s"

    def test_seven_days(self, ad):
        assert ad.logql_duration(timedelta(days=7)) == "604800s"

    def test_sub_minute_rounds_up_to_one_second(self, ad):
        assert ad.logql_duration(timedelta(milliseconds=1)) == "1s"


class TestQueryBuilders:
    def test_line_format_is_the_single_display_format_definition(self, ad):
        assert ad.LINE_FORMAT == (
            '| line_format "<{{.priority}}> '
            '[{{.node_id}}:{{.module_id}}:{{.identifier}}] {{.message}}"'
        )

    def test_metric_query(self, ad):
        query = ad.build_metric_query("3600s")
        assert query == (
            'sum by (module_id, priority) '
            '(count_over_time({node_id=~".+"} | json priority="PRIORITY" [3600s]))'
        )

    def test_lines_query_excludes_own_identifier(self, ad):
        query = ad.build_lines_query("loki1")
        assert '| identifier != "loki1/anomaly-detector"' in query
        assert 'priority < 5 or category="security"' in query
        assert 'line_format' in query
        # the exclusion must precede the priority filter, or the detector
        # would feed on its own PRIORITY=3 diagnostics
        assert query.index('identifier != ') < query.index('priority < 5')

    def test_recall_query_selects_only_own_output(self, ad):
        query = ad.build_recall_query("loki1")
        assert '{module_id="loki1"}' in query
        assert '| identifier="loki1/anomaly-detector"' in query


class TestRunLogcli:
    def test_returns_stdout(self, ad, monkeypatch):
        def fake_run(argv, **kwargs):
            assert argv[0] == "logcli"
            return subprocess.CompletedProcess(argv, 0, stdout="ok\n", stderr="")
        monkeypatch.setattr(ad.subprocess, "run", fake_run)
        assert ad.run_logcli(["logcli", "query", "x"]) == "ok\n"

    def test_non_zero_exit_raises(self, ad, monkeypatch):
        def fake_run(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")
        monkeypatch.setattr(ad.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError) as exc:
            ad.run_logcli(["logcli", "query", "x"])
        assert "boom" in str(exc.value)

    def test_timeout_raises(self, ad, monkeypatch):
        def fake_run(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 300)
        monkeypatch.setattr(ad.subprocess, "run", fake_run)
        with pytest.raises(RuntimeError):
            ad.run_logcli(["logcli", "query", "x"])


class TestParseJsonlRecords:
    def test_parses_line_format_output(self, ad):
        stdout = (
            '{"labels":{"node_id":"1","module_id":"nethvoice2"},'
            '"line":"<3> [1:nethvoice2:asterisk] boom","timestamp":"t"}\n'
            '{"labels":{},"line":"<4> [?:?:?] other","timestamp":"t"}\n'
        )
        records = ad.parse_jsonl_records(stdout)
        assert len(records) == 2
        assert records[0]["line"] == "<3> [1:nethvoice2:asterisk] boom"

    def test_skips_unparsable_and_blank_lines(self, ad):
        stdout = '\nnot json\n{"line":"ok"}\n'
        assert ad.parse_jsonl_records(stdout) == [{"line": "ok"}]

    def test_empty_stdout(self, ad):
        assert ad.parse_jsonl_records("") == []


class TestQueryMetric:
    class _Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class _Session:
        def __init__(self, payload):
            self._payload = payload
            self.calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return TestQueryMetric._Response(self._payload)

    def test_calls_the_instant_query_endpoint(self, ad):
        payload = {"data": {"result": [
            {"metric": {"module_id": "a", "priority": "6"}, "value": [0, "10"]}]}}
        session = self._Session(payload)
        at = datetime(2026, 7, 29, 14, 0, tzinfo=timezone.utc)
        rates = ad.query_metric(session, "http://127.0.0.1:3100", ("u", "p"), "Q", at)
        url, kwargs = session.calls[0]
        assert url == "http://127.0.0.1:3100/loki/api/v1/query"
        assert kwargs["params"]["query"] == "Q"
        assert kwargs["params"]["time"] == at.isoformat()
        assert kwargs["auth"] == ("u", "p")
        assert rates == {("a", "6"): 10.0}


class TestQueryLines:
    def test_truncation_is_detected_at_the_cap(self, ad, monkeypatch):
        stdout = "".join(
            '{"line":"<3> [1:a:b] boom %d"}\n' % i for i in range(3))
        monkeypatch.setattr(ad, "run_logcli", lambda argv, **kw: stdout)
        records, truncated = ad.query_lines(WINDOW, 3, "loki1")
        assert len(records) == 3
        assert truncated is True

    def test_below_the_cap_is_not_truncated(self, ad, monkeypatch):
        monkeypatch.setattr(ad, "run_logcli", lambda argv, **kw: '{"line":"x"}\n')
        _, truncated = ad.query_lines(WINDOW, 500, "loki1")
        assert truncated is False

    def test_argv_carries_window_and_limit(self, ad, monkeypatch):
        seen = {}
        def fake(argv, **kw):
            seen["argv"] = argv
            return ""
        monkeypatch.setattr(ad, "run_logcli", fake)
        ad.query_lines(WINDOW, 42, "loki1")
        argv = seen["argv"]
        assert argv[:2] == ["logcli", "query"]
        assert "--limit" in argv and "42" in argv
        assert "--forward" in argv
        assert WINDOW[0].isoformat() in argv
        assert WINDOW[1].isoformat() in argv


class TestRecallFindings:
    def test_extracts_severity_and_title(self, ad, monkeypatch):
        stdout = "\n".join([
            json.dumps({"line": json.dumps(
                {"severity": "high", "title": "asterisk storm"})}),
            json.dumps({"line": json.dumps(
                {"window_assessment": "nominal", "findings_count": 0})}),
            json.dumps({"line": "not json at all"}),
        ]) + "\n"
        monkeypatch.setattr(ad, "run_logcli", lambda argv, **kw: stdout)
        found = ad.recall_findings(WINDOW[1], "loki1")
        assert found == [{"severity": "high", "title": "asterisk storm"}]

    def test_keeps_only_the_last_n(self, ad, monkeypatch):
        stdout = "".join(
            json.dumps({"line": json.dumps(
                {"severity": "low", "title": f"t{i}"})}) + "\n"
            for i in range(15))
        monkeypatch.setattr(ad, "run_logcli", lambda argv, **kw: stdout)
        found = ad.recall_findings(WINDOW[1], "loki1", limit=10)
        assert len(found) == 10
        assert found[-1]["title"] == "t14"

    def test_a_failing_recall_is_not_fatal(self, ad, monkeypatch):
        def boom(argv, **kw):
            raise RuntimeError("loki down")
        monkeypatch.setattr(ad, "run_logcli", boom)
        assert ad.recall_findings(WINDOW[1], "loki1") == []


class TestLokiEnv:
    def test_builds_addr_and_exports_for_logcli(self, ad, monkeypatch):
        monkeypatch.setattr(ad.os, "environ", {
            "LOKI_HTTP_PORT": "3100",
            "LOKI_API_AUTH_USERNAME": "loki",
            "LOKI_API_AUTH_PASSWORD": "sekrit",
        })
        addr, auth = ad.loki_env()
        assert addr == "http://127.0.0.1:3100"
        assert auth == ("loki", "sekrit")
        assert ad.os.environ["LOKI_ADDR"] == "http://127.0.0.1:3100"
        assert ad.os.environ["LOKI_USERNAME"] == "loki"
        assert ad.os.environ["LOKI_PASSWORD"] == "sekrit"

    def test_missing_variable_raises(self, ad, monkeypatch):
        monkeypatch.setattr(ad.os, "environ", {})
        with pytest.raises(RuntimeError):
            ad.loki_env()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./test-unit.sh -k "Logql or QueryBuilders or RunLogcli or Jsonl or QueryMetric or QueryLines or Recall or LokiEnv"
```

Expected: FAIL with `AttributeError: module 'anomaly_detector' has no attribute 'logql_duration'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `imageroot/bin/anomaly-detector`:

```python
#------------------------------- COLLECT --------------------------------#

LOGCLI_TIMEOUT = 300
HTTP_TIMEOUT = (10, 300)

# The whole journal record is stored as the log line, so every query needs
# a `| json` stage, exactly as cloud-log-manager-forwarder does today.
LINE_FORMAT = '| line_format "<{{.priority}}> [{{.node_id}}:{{.module_id}}:{{.identifier}}] {{.message}}"'


def logql_duration(delta):
    """A timedelta as a LogQL range, in seconds."""
    return "{0}s".format(max(1, int(delta.total_seconds())))


def build_metric_query(range_text):
    return (
        'sum by (module_id, priority) '
        '(count_over_time({{node_id=~".+"}} | json priority="PRIORITY" [{0}]))'
    ).format(range_text)


def build_lines_query(module_id):
    """Prefiltered lines for the window.

    The detector's own identifier is excluded BEFORE the priority filter.
    Its diagnostics land in the journal at PRIORITY=3, so without this a
    single failure would be re-analysed every hour and past evidence lines
    would re-enter the prompt as fresh input.
    """
    return " ".join([
        '{node_id=~".+"}',
        '| json priority="PRIORITY", identifier="SYSLOG_IDENTIFIER", message="MESSAGE"',
        '| identifier != "{0}/anomaly-detector"'.format(module_id),
        '| priority < 5 or category="security"',
        LINE_FORMAT,
    ])


def build_recall_query(module_id):
    """The detector's own past findings — its self-hosted memory."""
    return " ".join([
        '{{module_id="{0}"}}'.format(module_id),
        '| json identifier="SYSLOG_IDENTIFIER", message="MESSAGE"',
        '| identifier="{0}/anomaly-detector"'.format(module_id),
        '| line_format "{{.message}}"',
    ])


def loki_env():
    """Derive and export the Loki endpoint, as the forwarders do.

    The module environment sets LOKI_ADDR to the VPN IP address, which is
    not a URL, so it is overwritten here with the local traefik endpoint.
    """
    try:
        addr = "http://127.0.0.1:{0}".format(os.environ['LOKI_HTTP_PORT'])
        username = os.environ['LOKI_API_AUTH_USERNAME']
        password = os.environ['LOKI_API_AUTH_PASSWORD']
    except KeyError as exc:
        raise RuntimeError(f"missing Loki variable {exc}; run under runagent") from exc
    os.environ['LOKI_ADDR'] = addr
    os.environ['LOKI_USERNAME'] = username
    os.environ['LOKI_PASSWORD'] = password
    return addr, (username, password)


def run_logcli(argv, timeout=LOGCLI_TIMEOUT):
    """Run logcli and return its stdout. Fail loudly: one window is cheap."""
    try:
        response = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"logcli timed out after {timeout}s") from exc
    if response.returncode != 0:
        raise RuntimeError(
            "logcli exited {0}: {1}".format(response.returncode, response.stderr.strip()))
    return response.stdout


def parse_jsonl_records(stdout):
    """Parse `logcli -o jsonl` output, skipping anything unparsable."""
    records = []
    for raw in stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            records.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            print(f"Skipping unparsable logcli record: {exc}", file=sys.stderr)
    return records


def query_metric(session, addr, auth, query, at):
    """Run a Loki instant query and return {(module_id, priority): value}."""
    response = session.get(
        addr + "/loki/api/v1/query",
        params={"query": query, "time": at.isoformat()},
        auth=auth,
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return parse_metric_response(response.json())


def query_lines(window, max_lines, module_id):
    """Collect the prefiltered lines for the window.

    Returns (records, truncated). Truncation is never silent: the caller
    puts it in the prompt and on stderr.
    """
    start, end = window
    argv = [
        "logcli", "query",
        "--limit", str(max_lines),
        "--forward",
        "--timezone", "UTC",
        "--from", start.isoformat(),
        "--to", end.isoformat(),
        "--no-labels", "-q", "-o", "jsonl",
        build_lines_query(module_id),
    ]
    records = parse_jsonl_records(run_logcli(argv))
    return records, len(records) >= max_lines


def recall_findings(window_end, module_id, limit=10):
    """The last `limit` finding titles from the detector's own journal output.

    A failure here is logged and treated as "no memory": losing dedup
    context is not worth losing the whole window.
    """
    argv = [
        "logcli", "query",
        "--limit", "200",
        "--forward",
        "--timezone", "UTC",
        "--from", (window_end - timedelta(hours=24)).isoformat(),
        "--to", window_end.isoformat(),
        "--no-labels", "-q", "-o", "jsonl",
        build_recall_query(module_id),
    ]
    try:
        stdout = run_logcli(argv)
    except RuntimeError as exc:
        print(f"Recall query failed, continuing without memory: {exc}", file=sys.stderr)
        return []

    recalled = []
    for record in parse_jsonl_records(stdout):
        try:
            finding = json.loads(record.get("line", ""))
        except json.JSONDecodeError:
            continue
        if isinstance(finding, dict) and finding.get("title"):
            recalled.append({
                "severity": finding.get("severity", "?"),
                "title": finding["title"],
            })
    return recalled[-limit:]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./test-unit.sh
```

Expected: every test PASSES.

- [ ] **Step 5: Verify the real queries on the test node**

The query builders must produce LogQL that a real Loki accepts. Generate the
queries from the code itself, so a typo in the constant cannot pass:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
python3 - > /tmp/probe.sh <<'PY'
import importlib.machinery, importlib.util
l = importlib.machinery.SourceFileLoader('ad', 'imageroot/bin/anomaly-detector')
s = importlib.util.spec_from_loader('ad', l)
m = importlib.util.module_from_spec(s); l.exec_module(m)
print('#!/bin/bash')
print('export LOKI_ADDR="http://127.0.0.1:$LOKI_HTTP_PORT"')
print('export LOKI_USERNAME="$LOKI_API_AUTH_USERNAME"')
print('export LOKI_PASSWORD="$LOKI_API_AUTH_PASSWORD"')
print('FROM=$(date -u -d "-1 hour" +%Y-%m-%dT%H:%M:%SZ)')
print('TO=$(date -u +%Y-%m-%dT%H:%M:%SZ)')
print('set -e')
print('echo "== metric query"')
print('curl -sSf -u "$LOKI_USERNAME:$LOKI_PASSWORD" -G "$LOKI_ADDR/loki/api/v1/query" \\')
print('  --data-urlencode {0} \\'.format(repr("query=" + m.build_metric_query("3600s"))))
print('  --data-urlencode "time=$TO" | head -c 200; echo')
print('echo "== lines query"')
print('logcli query --limit 500 --forward --timezone UTC --from "$FROM" --to "$TO" \\')
print('  --no-labels -q -o jsonl {0} | wc -l'.format(repr(m.build_lines_query("loki1"))))
print('echo "== recall query"')
print('logcli query --limit 200 --forward --timezone UTC --from "$FROM" --to "$TO" \\')
print('  --no-labels -q -o jsonl {0} | wc -l'.format(repr(m.build_recall_query("loki1"))))
PY
scp -q /tmp/probe.sh ${NODE}:/tmp/probe.sh
ssh ${NODE} runagent -m loki1 bash /tmp/probe.sh
```

Expected: the metric query prints `{"status":"success",...`; the lines query
prints a non-zero count (a few hundred on this node); the recall query prints
`0` because the detector has never run. **All three must exit 0** — `set -e`
plus `curl -sSf` makes a LogQL parse error a failure rather than a silent empty
result. If the recall query errors rather than returning 0, the query is
malformed; a genuinely empty result is not an error.

- [ ] **Step 6: Commit**

```bash
git add imageroot/bin/anomaly-detector tests/unit/test_anomaly_detector.py
git commit -m "feat(anomaly-detector): collect rates, lines and recalled findings from Loki"
```

---

### Task 5: Config precedence, LLM call, emit, webhook and `main()`

This completes the script. After this task `--dry-run` works end to end on a real node.

**Files:**
- Modify: `imageroot/bin/anomaly-detector` (append)
- Modify: `tests/unit/test_anomaly_detector.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  - `CONFIG_KEYS` (tuple), `DEFAULT_MAX_LINES = 500`
  - `_read_state_envfile(path) -> dict` — lazily imports `agent`; returns `{}` when the file is missing.
  - `load_config(args, environ, reader=_read_state_envfile) -> dict` — precedence lowest→highest: `environment`, `secrets.env`, shell env, `--config` file, CLI flags.
  - `make_session() -> requests.Session`
  - `ask_llm(session, config, prompt) -> str`
  - `render_findings(findings, assessment, window, truncated, llm_called, pretty) -> list[str]`
  - `post_webhook(session, config, payload) -> None`
  - `build_parser() -> argparse.ArgumentParser`
  - `main(argv=None) -> int`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_anomaly_detector.py`:

```python
import types


def _args(**kw):
    defaults = {
        "dry_run": False, "since": None, "config": None, "pretty": False,
        "no_webhook": False, "max_lines": None, "print_prompt": False,
    }
    defaults.update(kw)
    return types.SimpleNamespace(**defaults)


class TestLoadConfig:
    def test_precedence_order(self, ad):
        files = {
            "environment": {"ANOMALY_LLM_MODEL": "from-environment",
                            "ANOMALY_LLM_BASE_URL": "from-environment"},
            "secrets.env": {"ANOMALY_LLM_MODEL": "from-secrets",
                            "ANOMALY_LLM_API_KEY": "from-secrets"},
            "/tmp/override.env": {"ANOMALY_LLM_MODEL": "from-config-file"},
        }
        environ = {"ANOMALY_LLM_MODEL": "from-shell", "PATH": "/bin"}
        config = ad.load_config(
            _args(config="/tmp/override.env"), environ, reader=files.get)
        # --config beats shell env beats secrets.env beats environment
        assert config["ANOMALY_LLM_MODEL"] == "from-config-file"
        assert config["ANOMALY_LLM_BASE_URL"] == "from-environment"
        assert config["ANOMALY_LLM_API_KEY"] == "from-secrets"

    def test_shell_env_beats_state_files(self, ad):
        files = {"environment": {"ANOMALY_LLM_MODEL": "old"}}
        config = ad.load_config(
            _args(), {"ANOMALY_LLM_MODEL": "new"}, reader=files.get)
        assert config["ANOMALY_LLM_MODEL"] == "new"

    def test_cli_max_lines_wins(self, ad):
        files = {"environment": {"ANOMALY_MAX_LINES": "10"}}
        config = ad.load_config(_args(max_lines=7), {}, reader=files.get)
        assert config["ANOMALY_MAX_LINES"] == "7"

    def test_max_lines_default(self, ad):
        config = ad.load_config(_args(), {}, reader=lambda p: {})
        assert config["ANOMALY_MAX_LINES"] == str(ad.DEFAULT_MAX_LINES)

    def test_unrelated_variables_are_ignored(self, ad):
        config = ad.load_config(
            _args(), {"LOKI_API_AUTH_PASSWORD": "sekrit"}, reader=lambda p: {})
        assert "LOKI_API_AUTH_PASSWORD" not in config

    def test_missing_keys_default_to_empty_string(self, ad):
        config = ad.load_config(_args(), {}, reader=lambda p: {})
        assert config["ANOMALY_LLM_API_KEY"] == ""
        assert config["ANOMALY_WEBHOOK_URL"] == ""


class TestAskLlm:
    class _Response:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    class _Session:
        def __init__(self, response):
            self._response = response
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self._response

    def _config(self, **kw):
        config = {
            "ANOMALY_LLM_BASE_URL": "https://api.example.org/v1",
            "ANOMALY_LLM_MODEL": "gpt-4o-mini",
            "ANOMALY_LLM_API_KEY": "sk-test",
        }
        config.update(kw)
        return config

    def test_posts_to_chat_completions(self, ad):
        response = self._Response(
            200, {"choices": [{"message": {"content": "{}"}}]})
        session = self._Session(response)
        assert ad.ask_llm(session, self._config(), "PROMPT") == "{}"
        url, kwargs = session.calls[0]
        assert url == "https://api.example.org/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer sk-test"
        assert kwargs["json"]["messages"][1]["content"] == "PROMPT"

    def test_trailing_slash_in_base_url(self, ad):
        session = self._Session(
            self._Response(200, {"choices": [{"message": {"content": "{}"}}]}))
        ad.ask_llm(session, self._config(
            ANOMALY_LLM_BASE_URL="https://api.example.org/v1/"), "P")
        assert session.calls[0][0] == "https://api.example.org/v1/chat/completions"

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_errors_mention_the_api_key(self, ad, status):
        session = self._Session(self._Response(status, text="nope"))
        with pytest.raises(RuntimeError) as exc:
            ad.ask_llm(session, self._config(), "P")
        assert "check API key" in str(exc.value)

    def test_other_errors_truncate_the_body(self, ad):
        session = self._Session(self._Response(500, text="x" * 900))
        with pytest.raises(RuntimeError) as exc:
            ad.ask_llm(session, self._config(), "P")
        assert len(str(exc.value)) < 700


class TestRenderFindings:
    def _lines(self, ad, **kw):
        params = {
            "findings": [{
                "severity": "high", "title": "asterisk storm",
                "summary": "s", "evidence": ["e"],
                "modules": ["nethvoice2"], "suggested_action": "a",
            }],
            "assessment": "degraded",
            "window": WINDOW,
            "truncated": False,
            "llm_called": True,
            "pretty": False,
        }
        params.update(kw)
        return ad.render_findings(**params)

    def test_one_json_line_per_finding_plus_a_summary(self, ad):
        lines = self._lines(ad)
        assert len(lines) == 2
        finding = json.loads(lines[0])
        assert finding["title"] == "asterisk storm"
        assert finding["window_start"] == WINDOW[0].isoformat()
        summary = json.loads(lines[1])
        assert summary["window_assessment"] == "degraded"
        assert summary["findings_count"] == 1
        assert summary["llm_called"] is True
        assert summary["truncated"] is False

    def test_summary_line_is_emitted_even_with_no_findings(self, ad):
        lines = self._lines(ad, findings=[], assessment="nominal", llm_called=False)
        assert len(lines) == 1
        summary = json.loads(lines[0])
        assert summary["findings_count"] == 0
        assert summary["llm_called"] is False

    def test_pretty_mode_is_not_json(self, ad):
        lines = self._lines(ad, pretty=True)
        blob = "\n".join(lines)
        assert "HIGH" in blob
        assert "asterisk storm" in blob
        with pytest.raises(json.JSONDecodeError):
            json.loads(lines[0])


class TestPostWebhook:
    class _Session:
        def __init__(self):
            self.calls = []

        class _Response:
            status_code = 200

            def raise_for_status(self):
                pass

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self._Response()

    def test_no_url_is_a_no_op(self, ad):
        session = self._Session()
        ad.post_webhook(session, {"ANOMALY_WEBHOOK_URL": ""}, {"a": 1})
        assert session.calls == []

    def test_posts_with_bearer_token(self, ad):
        session = self._Session()
        ad.post_webhook(session, {
            "ANOMALY_WEBHOOK_URL": "https://hook.example.org/h",
            "ANOMALY_WEBHOOK_TOKEN": "t0ken",
        }, {"a": 1})
        url, kwargs = session.calls[0]
        assert url == "https://hook.example.org/h"
        assert kwargs["headers"]["Authorization"] == "Bearer t0ken"
        assert kwargs["json"] == {"a": 1}

    def test_posts_without_token(self, ad):
        session = self._Session()
        ad.post_webhook(session, {
            "ANOMALY_WEBHOOK_URL": "https://hook.example.org/h"}, {"a": 1})
        assert "Authorization" not in session.calls[0][1]["headers"]


class TestParser:
    def test_every_flag_is_optional(self, ad):
        args = ad.build_parser().parse_args([])
        assert args.dry_run is False
        assert args.since is None
        assert args.max_lines is None

    def test_flags_parse(self, ad):
        args = ad.build_parser().parse_args([
            "--dry-run", "--since", "2h", "--pretty", "--no-webhook",
            "--max-lines", "50", "--print-prompt", "--config", "/tmp/x.env",
        ])
        assert args.dry_run is True
        assert args.since == "2h"
        assert args.pretty is True
        assert args.no_webhook is True
        assert args.max_lines == 50
        assert args.print_prompt is True
        assert args.config == "/tmp/x.env"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
./test-unit.sh -k "LoadConfig or AskLlm or RenderFindings or PostWebhook or Parser"
```

Expected: FAIL with `AttributeError: module 'anomaly_detector' has no attribute 'load_config'`.

- [ ] **Step 3: Write the minimal implementation**

First add the two HTTP imports to the import block near the top of `imageroot/bin/anomaly-detector`, matching `cloud-log-manager-forwarder`:

```python
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
```

Then append:

```python
#-------------------------------- CONFIG --------------------------------#

DEFAULT_MAX_LINES = 500

CONFIG_KEYS = (
    "ANOMALY_LLM_BASE_URL",
    "ANOMALY_LLM_MODEL",
    "ANOMALY_LLM_API_KEY",
    "ANOMALY_MAX_LINES",
    "ANOMALY_WEBHOOK_URL",
    "ANOMALY_WEBHOOK_TOKEN",
)

# Lowest precedence first. Shell env, --config and CLI flags are layered
# on top by load_config().
STATE_ENVFILES = ("environment", "secrets.env")


def _read_state_envfile(path):
    """Read an env file relative to AGENT_STATE_DIR, or {} if absent.

    `agent` is imported lazily so the module stays importable in the unit
    test container, where the NS8 SDK is not installed.
    """
    import agent
    try:
        return agent.read_envfile(path)
    except FileNotFoundError:
        return {}


def load_config(args, environ=None, reader=None):
    """Resolve configuration.

    Precedence, highest first: CLI flag, --config file, shell environment,
    secrets.env, environment.
    """
    environ = os.environ if environ is None else environ
    reader = _read_state_envfile if reader is None else reader

    merged = {}
    for path in STATE_ENVFILES:
        merged.update(reader(path) or {})
    merged.update({key: value for key, value in environ.items() if key in CONFIG_KEYS})
    if args.config:
        merged.update(reader(args.config) or {})
    if args.max_lines is not None:
        merged["ANOMALY_MAX_LINES"] = str(args.max_lines)

    config = {key: str(merged.get(key, "") or "") for key in CONFIG_KEYS}
    if not config["ANOMALY_MAX_LINES"]:
        config["ANOMALY_MAX_LINES"] = str(DEFAULT_MAX_LINES)
    return config


#--------------------------------- ASK ----------------------------------#

def make_session():
    """A Session that retries transient LLM and webhook failures."""
    session = Session()
    retries = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["GET", "POST"]),
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def ask_llm(session, config, prompt):
    """POST the prompt and return the raw assistant message."""
    url = config["ANOMALY_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    response = session.post(
        url,
        headers={
            "Authorization": "Bearer " + config["ANOMALY_LLM_API_KEY"],
            "Content-Type": "application/json",
        },
        json=build_request_body(config["ANOMALY_LLM_MODEL"], prompt),
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code in (401, 403):
        raise RuntimeError(f"LLM returned {response.status_code}: check API key")
    if response.status_code >= 400:
        raise RuntimeError("LLM returned {0}: {1}".format(
            response.status_code, response.text[:500]))
    return extract_content(response.json())


#--------------------------------- EMIT ---------------------------------#

def render_findings(findings, assessment, window, truncated, llm_called, pretty):
    """Render the output lines. One line per finding, then a summary line."""
    start, end = window
    lines = []

    for finding in findings:
        record = dict(finding)
        record["window_start"] = start.isoformat()
        record["window_end"] = end.isoformat()
        if pretty:
            lines.append("[{0}] {1}".format(finding["severity"].upper(), finding["title"]))
            lines.append("    modules: {0}".format(", ".join(finding["modules"]) or "-"))
            lines.append("    summary: {0}".format(finding["summary"]))
            lines.append("    action:  {0}".format(finding["suggested_action"] or "-"))
            for item in finding["evidence"]:
                lines.append("    | {0}".format(item))
            lines.append("")
        else:
            lines.append(json.dumps(record, sort_keys=True))

    summary = {
        "window_assessment": assessment,
        "findings_count": len(findings),
        "llm_called": llm_called,
        "truncated": truncated,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }
    if pretty:
        lines.append("window {0} .. {1}: {2}, {3} finding(s){4}".format(
            start.isoformat(), end.isoformat(), assessment, len(findings),
            ", window truncated" if truncated else ""))
    else:
        lines.append(json.dumps(summary, sort_keys=True))
    return lines


def post_webhook(session, config, payload):
    """Best-effort delivery. Journald is the source of truth."""
    url = config.get("ANOMALY_WEBHOOK_URL", "")
    if not url:
        return
    headers = {"Content-Type": "application/json"}
    token = config.get("ANOMALY_WEBHOOK_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    response = session.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
    response.raise_for_status()


#--------------------------------- MAIN ---------------------------------#

def build_parser():
    parser = argparse.ArgumentParser(
        description="Detect anomalies in one window of NS8 journal logs.")
    parser.add_argument("--dry-run", action="store_true",
                        help="collect and render the prompt, print it, make no LLM call")
    parser.add_argument("--since", metavar="DURATION",
                        help="analyse [now-DURATION, now] instead of the previous full hour")
    parser.add_argument("--config", metavar="FILE",
                        help="read ANOMALY_* from FILE instead of the module state")
    parser.add_argument("--pretty", action="store_true",
                        help="print findings as indented text instead of JSON lines")
    parser.add_argument("--no-webhook", action="store_true",
                        help="skip webhook delivery")
    parser.add_argument("--max-lines", type=int, metavar="N",
                        help="override the prefiltered line cap for this run")
    parser.add_argument("--print-prompt", action="store_true",
                        help="print the prompt to stderr alongside a real LLM call")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = load_config(args)
    module_id = os.environ.get('MODULE_ID', 'loki1')

    if not args.dry_run:
        for key in ("ANOMALY_LLM_BASE_URL", "ANOMALY_LLM_MODEL", "ANOMALY_LLM_API_KEY"):
            if not config[key]:
                print(f"not configured: {key} is unset", file=sys.stderr)
                return 1

    addr, auth = loki_env()
    window = compute_window(datetime.now(timezone.utc), args.since)
    start, end = window
    duration = end - start
    max_lines = int(config["ANOMALY_MAX_LINES"])

    session = make_session()

    rates = query_metric(session, addr, auth,
                         build_metric_query(logql_duration(duration)), end)
    baseline_raw = query_metric(session, addr, auth,
                                build_metric_query(logql_duration(timedelta(days=7))),
                                start)
    window_hours = duration.total_seconds() / 3600.0
    baseline = {
        key: (value / BASELINE_HOURS) * window_hours
        for key, value in baseline_raw.items()
    }
    digest = build_digest(rates, baseline)

    records, truncated = query_lines(window, max_lines, module_id)
    if truncated:
        print("Line cap of {0} reached: the window is truncated".format(max_lines),
              file=sys.stderr)
    # LINE_FORMAT already rendered each line server-side, so only flattening
    # and scrubbing remain. Nothing formats log lines in Python.
    lines = [sanitize_line(record.get("line", "")) for record in records]
    lines = [line for line in lines if line]

    recalled = recall_findings(end, module_id)

    prompt = render_prompt(window, digest, recalled, lines, truncated)

    if args.dry_run:
        print(prompt, file=sys.stderr)
        print("--- {0} characters, ~{1} tokens, {2} lines, no LLM call".format(
            len(prompt), estimate_tokens(prompt), len(lines)), file=sys.stderr)
        return 0

    if is_nominal(records, digest):
        print("nominal, no LLM call", file=sys.stderr)
        for line in render_findings([], "nominal", window, truncated, False, args.pretty):
            print(line)
        return 0

    if args.print_prompt:
        print(prompt, file=sys.stderr)

    findings, assessment = parse_findings(ask_llm(session, config, prompt))

    for line in render_findings(findings, assessment, window, truncated, True, args.pretty):
        print(line)
    sys.stdout.flush()

    if not args.no_webhook:
        post_webhook(session, config, {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "window_assessment": assessment,
            "truncated": truncated,
            "findings": findings,
        })

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"anomaly-detector failed: {exc}", file=sys.stderr)
        sys.exit(1)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
./test-unit.sh
```

Expected: every test PASSES.

- [ ] **Step 5: Verify the CLI is wired up**

```bash
python3 -c "
import importlib.machinery, importlib.util, sys
l = importlib.machinery.SourceFileLoader('ad', 'imageroot/bin/anomaly-detector')
s = importlib.util.spec_from_loader('ad', l); m = importlib.util.module_from_spec(s); l.exec_module(m)
m.build_parser().parse_args(['--help'])
" || true
```

Expected: the help text lists all seven flags and exits 0.

- [ ] **Step 6: Verify `--dry-run` end to end on the test node**

This is the first full run of stages 1–4 against real logs, with no LLM call and
no cost:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
scp -q imageroot/bin/anomaly-detector ${NODE}:/tmp/
ssh ${NODE} runagent -m loki1 python3 /tmp/anomaly-detector --dry-run --since 1h
```

Expected, all on stderr, exit code 0:
- all four fenced blocks present: `WINDOW`, `RATES`, `RECENT_FINDINGS`, `LINES`
- `RECENT_FINDINGS` shows `(none)` — the detector has never run
- `RATES` lists real modules (`crowdsec1`, `nethvoice2`, `traefik1`, …) with
  `observed=` and `expected=` values, and `ratio=n/a` for pairs with no 7-day
  history
- the trailing line reports characters, approximate tokens and line count;
  on this node expect roughly 40k characters / ~10k tokens / ~380 lines
- **no line in the `LINES` block contains a raw newline** — verify with
  `... --dry-run --since 1h 2>&1 | sed -n '/^LINES/,$p' | wc -l` and check the
  count matches the reported line count plus the two fence lines

Then confirm the missing-configuration path:

```bash
ssh ${NODE} runagent -m loki1 python3 /tmp/anomaly-detector --since 1h; echo "exit=$?"
```

Expected: `not configured: ANOMALY_LLM_BASE_URL is unset` on stderr, `exit=1`,
and no LLM call attempted.

- [ ] **Step 7: Verify a real LLM call end to end**

This exercises stages 5 and 6 for the first time, against the OpenRouter endpoint
described in "The LLM endpoint used for verification". Pass the key through the
environment so it never lands in a file or in shell history on the node:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
ORKEY=$(grep -oE 'sk-or-[A-Za-z0-9._-]+' open_router | head -1)
scp -q imageroot/bin/anomaly-detector ${NODE}:/tmp/
ssh ${NODE} "ANOMALY_LLM_API_KEY='${ORKEY}' runagent -m loki1 env \
  ANOMALY_LLM_BASE_URL=https://openrouter.ai/api/v1 \
  ANOMALY_LLM_MODEL=google/gemma-4-26b-a4b-it:free \
  ANOMALY_LLM_API_KEY=\"\$ANOMALY_LLM_API_KEY\" \
  python3 /tmp/anomaly-detector --since 1h --pretty --no-webhook"
```

Expected: exit 0, and on **stdout** either one or more `[SEVERITY] title` blocks
followed by a `window …: <assessment>, N finding(s)` line, or just that summary
line if the model found nothing. Diagnostics, if any, appear on stderr only.

Then prove the machine-readable path, which is what systemd actually captures:

```bash
ssh ${NODE} "ANOMALY_LLM_API_KEY='${ORKEY}' runagent -m loki1 env \
  ANOMALY_LLM_BASE_URL=https://openrouter.ai/api/v1 \
  ANOMALY_LLM_MODEL=google/gemma-4-26b-a4b-it:free \
  ANOMALY_LLM_API_KEY=\"\$ANOMALY_LLM_API_KEY\" \
  python3 /tmp/anomaly-detector --since 1h --no-webhook" \
  | while read -r line; do echo "$line" | python3 -m json.tool >/dev/null \
      && echo "valid JSON: $(echo "$line" | head -c 80)" \
      || echo "NOT JSON: $line"; done
```

Expected: **every** stdout line parses as JSON — one object per finding plus the
summary object. A single `NOT JSON` line means diagnostics leaked into stdout,
which would poison the Loki recall query in stage 3; treat it as a failure.

Finally confirm the schema-rejection path is real rather than theoretical, by
pointing at a model that ignores `response_format`:

```bash
ssh ${NODE} "ANOMALY_LLM_API_KEY='${ORKEY}' runagent -m loki1 env \
  ANOMALY_LLM_BASE_URL=https://openrouter.ai/api/v1 \
  ANOMALY_LLM_MODEL=google/gemma-3-4b-it \
  ANOMALY_LLM_API_KEY=\"\$ANOMALY_LLM_API_KEY\" \
  python3 /tmp/anomaly-detector --since 1h --no-webhook"; echo "exit=$?"
```

Expected: either a clean run (if that model happens to comply) or `exit=1` with a
message on stderr containing the body truncated to 500 characters and **no partial
finding on stdout**. What must never happen is a malformed finding being emitted.

Report the observed token count and the model's actual findings in your report —
prompt quality is a judgement call that only real logs can settle.

- [ ] **Step 8: Commit**

```bash
git add imageroot/bin/anomaly-detector tests/unit/test_anomaly_detector.py
git commit -m "feat(anomaly-detector): add config precedence, LLM call, emit and CLI"
```

---

### Task 6: Systemd units, unit refresh and backup inclusion

**Files:**
- Create: `imageroot/systemd/user/anomaly-detector.service`
- Create: `imageroot/systemd/user/anomaly-detector.timer`
- Create: `imageroot/update-module.d/15systemd`
- Modify: `imageroot/etc/state-include.conf`

**Interfaces:**
- Consumes: `imageroot/bin/anomaly-detector` (Task 5).
- Produces: the unit names `anomaly-detector.service` and `anomaly-detector.timer`, which Task 7 enables and Tasks 8–9 query.

- [ ] **Step 1: Write the unit files**

Create `imageroot/systemd/user/anomaly-detector.service` (mode 644):

```
[Unit]
Description=Loki anomaly detector
Requires=loki-server.service
After=loki-server.service

[Service]
Type=oneshot
EnvironmentFile=%E/state/environment
EnvironmentFile=-%E/state/secrets.env
ExecStart=runagent %E/bin/anomaly-detector
SyslogIdentifier=%u/%N
```

There is deliberately no `[Install]` section: the timer is what gets enabled.

`SyslogIdentifier=%u/%N` is mandatory, not cosmetic. Alloy (configured by
`core/imageroot/var/lib/nethserver/node/bin/generate-promtail-config` in ns8-core)
assigns the `module_id` label only when the module name appears in `_SYSTEMD_UNIT`,
`SYSLOG_IDENTIFIER` or `CONTAINER_NAME`. A rootless user unit reports
`_SYSTEMD_UNIT=user@<uid>.service`, which contains no module name, so without this
the detector's own findings would be ingested unlabeled and the recall query in
`recall_findings()` would never match them. `%u/%N` expands to `loki1/anomaly-detector`.

`EnvironmentFile=-%E/state/secrets.env` carries the leading `-` because the file
does not exist until `set-anomaly-detector` runs; `runagent` loads `state/environment`
but not `secrets.env`.

Create `imageroot/systemd/user/anomaly-detector.timer` (mode 644):

```
[Unit]
Description=Loki anomaly detector timer

[Timer]
OnCalendar=hourly
Persistent=true
RandomizedDelaySec=5m
FixedRandomDelay=true

[Install]
WantedBy=timers.target
```

`Persistent=true` recovers a single window missed across a reboot.
`RandomizedDelaySec=5m` with `FixedRandomDelay=true` keeps the fire off the exact
top of the hour so the journal has settled and Loki has ingested it; the analysed
window is derived from the wall clock, so the delay never shifts it. This matches
`ns8-nethvoice/imageroot/systemd/user/nethvoice-cdr-cleanup.timer`.

- [ ] **Step 2: Add the update hook**

Create `imageroot/update-module.d/15systemd` (mode 755):

```bash
#!/bin/bash

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

set -e

# Redirect any output to the journal (stderr)
exec 1>&2

# Pick up unit files added by this update (anomaly-detector.service/.timer)
systemctl --user daemon-reload
```

This is idempotent and does not enable anything: the detector stays disabled until
`set-anomaly-detector` is called. It runs before `20restart`, which restarts
`loki.service`.

- [ ] **Step 3: Include the secrets file in backups**

Modify `imageroot/etc/state-include.conf`. Current content is the single line
`volumes/loki-server-data`. Result:

```
state/secrets.env
volumes/loki-server-data
```

Paths are relative to the module install root. The Restic repository is encrypted,
so the API key is protected at rest; including it means restore keeps a configured
detector working.

- [ ] **Step 4: Verify the units parse**

```bash
chmod 644 imageroot/systemd/user/anomaly-detector.service imageroot/systemd/user/anomaly-detector.timer
chmod 755 imageroot/update-module.d/15systemd
systemd-analyze verify --user-unit imageroot/systemd/user/anomaly-detector.timer 2>&1 | grep -v 'loki-server.service' || true
```

Expected: no syntax errors reported for `anomaly-detector.timer` or
`anomaly-detector.service`. Complaints about the missing `loki-server.service`
dependency are expected outside a real module and are filtered out above.

- [ ] **Step 5: Verify the units load on the test node**

Sync `imageroot/` to the node as described in "Deploying to the node between
tasks", then:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
ssh ${NODE} 'runagent -m loki1 systemctl --user show --property=LoadState anomaly-detector.service
runagent -m loki1 systemctl --user show --property=LoadState anomaly-detector.timer
runagent -m loki1 systemctl --user is-enabled anomaly-detector.timer
runagent -m loki1 systemctl --user show anomaly-detector.service -p SyslogIdentifier --value'
```

Expected: `LoadState=loaded` twice; `disabled` for `is-enabled` (the detector is
off until configured); `SyslogIdentifier` prints `loki1/anomaly-detector` — this
is the check that the `%u/%N` expansion actually produces the string the recall
query and the `module_id` label rule depend on. Any other value here breaks
stage 3.

- [ ] **Step 6: Commit**

```bash
git add imageroot/systemd/user/anomaly-detector.service \
        imageroot/systemd/user/anomaly-detector.timer \
        imageroot/update-module.d/15systemd \
        imageroot/etc/state-include.conf
git commit -m "feat(anomaly-detector): add oneshot service, hourly timer and state include"
```

---

### Task 7: The `set-anomaly-detector` action

**Files:**
- Create: `imageroot/actions/set-anomaly-detector/validate-input.json`
- Create: `imageroot/actions/set-anomaly-detector/10set`

**Interfaces:**
- Consumes: the unit name `anomaly-detector.timer` (Task 6); the env var names in `CONFIG_KEYS` (Task 5).
- Produces: `state/environment` entries `ANOMALY_LLM_BASE_URL`, `ANOMALY_LLM_MODEL`, `ANOMALY_MAX_LINES`, `ANOMALY_WEBHOOK_URL`; `state/secrets.env` entries `ANOMALY_LLM_API_KEY`, `ANOMALY_WEBHOOK_TOKEN`. Task 8 reads all of these back.

- [ ] **Step 1: Write the input schema**

Create `imageroot/actions/set-anomaly-detector/validate-input.json` (mode 644):

```json
{
    "$schema": "http://json-schema.org/draft-04/schema#",
    "$id": "http://schema.nethserver.org/loki/set-anomaly-detector.json",
    "title": "Configure Loki anomaly detector",
    "description": "Configure the hourly LLM-based journal anomaly detector.",
    "type": "object",
    "properties": {
        "active": {
            "type": "boolean",
            "description": "Enable or disable the hourly detector timer."
        },
        "base_url": {
            "type": "string",
            "format": "uri",
            "description": "OpenAI-compatible API base URL, without the /chat/completions suffix."
        },
        "model": {
            "type": "string",
            "minLength": 1,
            "description": "Model name passed to the completions endpoint."
        },
        "api_key": {
            "type": "string",
            "minLength": 1,
            "description": "API key for the completions endpoint. Stored outside Redis and never returned."
        },
        "max_lines": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5000,
            "description": "Cap on prefiltered log lines sent per window."
        },
        "webhook_url": {
            "type": "string",
            "description": "Optional URL receiving a copy of each report. Empty string clears it."
        },
        "webhook_token": {
            "type": "string",
            "description": "Optional bearer token for the webhook. Empty string clears it."
        }
    },
    "oneOf": [
        {
            "properties": {
                "active": {"enum": [true]}
            },
            "required": [
                "active",
                "base_url",
                "model",
                "api_key"
            ]
        },
        {
            "properties": {
                "active": {"enum": [false]}
            },
            "required": ["active"]
        }
    ]
}
```

- [ ] **Step 2: Write the action step**

Create `imageroot/actions/set-anomaly-detector/10set` (mode 755):

```python
#!/usr/bin/env python3

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import json
import os
import subprocess
import sys

import agent

# Secrets never go through agent.set_env: that writes state/environment,
# which is mirrored into the Redis hash module/<module_id>/environment.
SECRETS_FILE = "secrets.env"
SECRET_KEYS = ("ANOMALY_LLM_API_KEY", "ANOMALY_WEBHOOK_TOKEN")
PUBLIC_KEYS = ("ANOMALY_LLM_BASE_URL", "ANOMALY_LLM_MODEL",
               "ANOMALY_MAX_LINES", "ANOMALY_WEBHOOK_URL")

DEFAULT_MAX_LINES = 500


def read_secrets():
    """Read secrets.env, merging rather than overwriting unrelated keys."""
    try:
        return agent.read_envfile(SECRETS_FILE)
    except FileNotFoundError:
        return {}


def write_secrets(secrets):
    """Write secrets.env and force 0600.

    safe_open() preserves the mode of an existing file, but a freshly
    created one would otherwise depend on the umask.
    """
    agent.write_envfile(SECRETS_FILE, secrets)
    os.chmod(SECRETS_FILE, 0o600)


request = json.load(sys.stdin)
secrets = read_secrets()

if request['active']:
    agent.set_env('ANOMALY_LLM_BASE_URL', request['base_url'].rstrip('/'))
    agent.set_env('ANOMALY_LLM_MODEL', request['model'])
    agent.set_env('ANOMALY_MAX_LINES', str(request.get('max_lines', DEFAULT_MAX_LINES)))

    if request.get('webhook_url'):
        agent.set_env('ANOMALY_WEBHOOK_URL', request['webhook_url'])
    else:
        agent.unset_env('ANOMALY_WEBHOOK_URL')

    secrets['ANOMALY_LLM_API_KEY'] = request['api_key']
    if request.get('webhook_token'):
        secrets['ANOMALY_WEBHOOK_TOKEN'] = request['webhook_token']
    else:
        secrets.pop('ANOMALY_WEBHOOK_TOKEN', None)

    action = 'enable'
else:
    agent.munset_env(list(PUBLIC_KEYS))
    for key in SECRET_KEYS:
        secrets.pop(key, None)
    action = 'disable'

write_secrets(secrets)

# The unit files may be new to this installation
subprocess.run(["systemctl", "--user", "daemon-reload"],
               stdout=sys.stderr,
               stderr=sys.stderr,
               text=True,
               check=True)

# Enable or disable the timer, never the oneshot service. Re-running while
# active only rewrites the configuration: the oneshot reads its environment
# at each fire, so the timer needs no restart.
subprocess.run(["systemctl", "--user", action, "--now", "anomaly-detector.timer"],
               stdout=sys.stderr,
               stderr=sys.stderr,
               text=True,
               check=True)
```

- [ ] **Step 3: Verify the schema is valid draft-04 and the script compiles**

```bash
chmod 755 imageroot/actions/set-anomaly-detector/10set
chmod 644 imageroot/actions/set-anomaly-detector/validate-input.json
python3 -c "import json; json.load(open('imageroot/actions/set-anomaly-detector/validate-input.json'))"
python3 -m py_compile imageroot/actions/set-anomaly-detector/10set && echo OK
```

Expected: no output from the `json.load`, then `OK`.

- [ ] **Step 4: Verify both `oneOf` branches against the schema**

```bash
python3 - <<'PY'
import json, jsonschema  # pip install jsonschema if missing
schema = json.load(open('imageroot/actions/set-anomaly-detector/validate-input.json'))
validator = jsonschema.Draft4Validator(schema)
ok = [
    {"active": False},
    {"active": True, "base_url": "https://api.openai.com/v1",
     "model": "gpt-4o-mini", "api_key": "sk-x"},
    {"active": True, "base_url": "https://api.openai.com/v1",
     "model": "gpt-4o-mini", "api_key": "sk-x", "max_lines": 100,
     "webhook_url": "https://example.org/hook", "webhook_token": "t"},
]
bad = [
    {"active": True},
    {"active": True, "base_url": "https://x/v1", "model": "m"},
    {"active": True, "base_url": "https://x/v1", "api_key": "k"},
    {},
    {"active": True, "base_url": "https://x/v1", "model": "m",
     "api_key": "k", "max_lines": 0},
]
for payload in ok:
    validator.validate(payload)
for payload in bad:
    assert not validator.is_valid(payload), payload
print("schema OK")
PY
```

Expected: `schema OK`.

- [ ] **Step 5: Verify the action on the test node**

Sync `imageroot/` to the node, then run the action for real. Use a deliberately
unreachable `base_url` so nothing is ever sent anywhere:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{
  \"active\": true,
  \"base_url\": \"http://127.0.0.1:9\",
  \"model\": \"probe-model\",
  \"api_key\": \"sk-probe-key-do-not-use\",
  \"max_lines\": 50
}"'

ssh ${NODE} 'echo "== timer:";   runagent -m loki1 systemctl --user is-active anomaly-detector.timer
echo "== mode:";                 runagent -m loki1 stat -c %a state/secrets.env
echo "== secrets keys:";         runagent -m loki1 sed "s/=.*/=<value>/" state/secrets.env
echo "== public env:";           runagent -m loki1 grep ^ANOMALY_ state/environment
echo "== redis (must be empty):"; redis-cli hgetall module/loki1/environment | grep -i -e api_key -e webhook_token || echo NONE'
```

Expected: timer `active`; mode `600`; `secrets.env` lists
`ANOMALY_LLM_API_KEY=<value>` and no `ANOMALY_WEBHOOK_TOKEN`; `state/environment`
carries `ANOMALY_LLM_BASE_URL`, `ANOMALY_LLM_MODEL`, `ANOMALY_MAX_LINES`;
the Redis grep prints `NONE`. **`NONE` is the load-bearing assertion of this
task** — the whole reason secrets bypass `agent.set_env`.

Then verify idempotence and teardown:

```bash
# re-running while active must succeed and leave the timer active
ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{
  \"active\": true, \"base_url\": \"http://127.0.0.1:9\",
  \"model\": \"probe-model-2\", \"api_key\": \"sk-probe-key-do-not-use\"}"
runagent -m loki1 systemctl --user is-active anomaly-detector.timer
runagent -m loki1 grep ANOMALY_LLM_MODEL state/environment'

# disabling must clear both the timer and the stored key
ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{\"active\": false}"
runagent -m loki1 systemctl --user is-active anomaly-detector.timer || true
runagent -m loki1 cat state/secrets.env
runagent -m loki1 grep ^ANOMALY_ state/environment || echo "no ANOMALY_ vars left"'
```

Expected: still `active` with `ANOMALY_LLM_MODEL=probe-model-2` after the second
enable; then `inactive`, an empty `secrets.env`, and `no ANOMALY_ vars left`.

Leave the detector disabled at the end of this task.

- [ ] **Step 6: Commit**

```bash
git add imageroot/actions/set-anomaly-detector
git commit -m "feat(anomaly-detector): add set-anomaly-detector action"
```

---

### Task 8: Expose detector state through `get-configuration`

**Files:**
- Modify: `imageroot/actions/get-configuration/10get`
- Modify: `imageroot/actions/get-configuration/validate-output.json`

**Interfaces:**
- Consumes: the env vars written by Task 7; the unit names from Task 6.
- Produces: the `anomaly_detector` object in the `get-configuration` output, asserted by Task 9.

- [ ] **Step 1: Add the anomaly detector block to `10get`**

In `imageroot/actions/get-configuration/10get`, insert the following **after** the
Syslog block (after the `syslog["last_timestamp"] = ""` `except` clause) and
**before** the `# General` comment. It reuses the file's existing `match`/`case`
status idiom and its `os.getenv` style.

```python
# Anomaly detector

anomaly_detector = {}

ad_status = subprocess.run(['systemctl', '--user', 'is-active', 'anomaly-detector.timer'], capture_output=True, text=True)
match ad_status.stdout.strip():
    case 'active':
        anomaly_detector["status"] = 'active'
    case 'failed':
        anomaly_detector["status"] = 'failed'
    case _:
        anomaly_detector["status"] = 'inactive'

anomaly_detector["base_url"] = os.getenv('ANOMALY_LLM_BASE_URL', '')
anomaly_detector["model"] = os.getenv('ANOMALY_LLM_MODEL', '')
anomaly_detector["max_lines"] = int(os.getenv('ANOMALY_MAX_LINES', '500'))
anomaly_detector["webhook_url"] = os.getenv('ANOMALY_WEBHOOK_URL', '')

# The API key value is never returned, only its presence.
try:
    anomaly_detector["api_key_configured"] = bool(agent.read_envfile('secrets.env').get('ANOMALY_LLM_API_KEY'))
except FileNotFoundError:
    anomaly_detector["api_key_configured"] = False

ad_last_run = subprocess.run(['systemctl', '--user', 'show', 'anomaly-detector.service', '-p', 'ExecMainExitTimestamp', '--value'], capture_output=True, text=True)
anomaly_detector["last_run"] = ad_last_run.stdout.strip()
```

Then add the object to the response dict, so it reads:

```python
response = {
    "retention_days": int(os.getenv('LOKI_RETENTION_PERIOD')),
    "active_from": os.getenv('LOKI_ACTIVE_FROM'),
    "cloud_log_manager": cloud_log_manager,
    "syslog": syslog,
    "anomaly_detector": anomaly_detector
}
```

- [ ] **Step 2: Declare it in `validate-output.json`**

Add `"anomaly_detector"` to the top-level `required` array, and this property
alongside the existing `cloud_log_manager` and `syslog` properties:

```json
        "anomaly_detector": {
            "type": "object",
            "title": "Anomaly detector",
            "description": "State of the hourly LLM-based journal anomaly detector.",
            "required": ["status", "api_key_configured"],
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "failed", "inactive"],
                    "description": "State of anomaly-detector.timer."
                },
                "base_url": {
                    "type": "string",
                    "description": "OpenAI-compatible API base URL."
                },
                "model": {
                    "type": "string",
                    "description": "Model name."
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Cap on prefiltered log lines per window."
                },
                "webhook_url": {
                    "type": "string",
                    "description": "Optional report delivery URL."
                },
                "api_key_configured": {
                    "type": "boolean",
                    "description": "True when an API key is stored. The key value is never returned."
                },
                "last_run": {
                    "type": "string",
                    "description": "ExecMainExitTimestamp of anomaly-detector.service, empty if never run."
                }
            }
        }
```

- [ ] **Step 3: Verify the schema is still valid and the script compiles**

```bash
python3 -c "import json; json.load(open('imageroot/actions/get-configuration/validate-output.json'))"
python3 -m py_compile imageroot/actions/get-configuration/10get && echo OK
```

Expected: no output, then `OK`.

- [ ] **Step 4: Verify a representative response validates**

```bash
python3 - <<'PY'
import json, jsonschema
schema = json.load(open('imageroot/actions/get-configuration/validate-output.json'))
response = {
    "retention_days": 7,
    "active_from": "2026-07-29T13:00:00+00:00",
    "cloud_log_manager": {"status": "inactive"},
    "syslog": {"status": "inactive"},
    "anomaly_detector": {
        "status": "active", "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini", "max_lines": 500, "webhook_url": "",
        "api_key_configured": True, "last_run": "Wed 2026-07-29 14:00:11 UTC",
    },
}
jsonschema.Draft4Validator(schema).validate(response)
missing = dict(response); del missing["anomaly_detector"]
assert not jsonschema.Draft4Validator(schema).is_valid(missing)
print("output schema OK")
PY
```

Expected: `output schema OK`.

- [ ] **Step 5: Verify on the test node, both configured and not**

Sync `imageroot/` to the node. First with the detector off:

```bash
NODE=root@rl1.leader.default.gs.nethserver.net
ssh ${NODE} 'api-cli run module/loki1/get-configuration | python3 -m json.tool'
```

Expected: an `anomaly_detector` object with `"status": "inactive"`,
`"api_key_configured": false`, empty `base_url`/`model`/`webhook_url`,
`"max_lines": 500`, and a `last_run` string. The action must exit 0 — a non-zero
exit here means the output failed its own `validate-output.json`.

Then with it on:

```bash
ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{
  \"active\": true, \"base_url\": \"http://127.0.0.1:9\",
  \"model\": \"probe-model\", \"api_key\": \"sk-probe-key-do-not-use\"}"
api-cli run module/loki1/get-configuration | python3 -m json.tool'
```

Expected: `"status": "active"`, `"api_key_configured": true`,
`"model": "probe-model"`, and **the string `sk-probe-key-do-not-use` appears
nowhere in the output**. Confirm that explicitly:

```bash
ssh ${NODE} 'api-cli run module/loki1/get-configuration | grep -c sk-probe-key-do-not-use || echo "key not leaked"'
ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{\"active\": false}"'
```

Expected: `key not leaked`, then the detector is left disabled.

- [ ] **Step 6: Commit**

```bash
git add imageroot/actions/get-configuration
git commit -m "feat(anomaly-detector): expose detector state in get-configuration"
```

---

### Task 9: Robot test against a stub LLM

**Files:**
- Create: `tests/llm-stub.py`
- Create: `tests/20__anomaly_detector.robot`

**Interfaces:**
- Consumes: `set-anomaly-detector` (Task 7), `get-configuration` (Task 8), both units (Task 6), the script's `--since/--pretty/--no-webhook` flags (Task 5).
- Produces: nothing consumed downstream.

The suite inherits `Connect to the node`, `Wait until boot completes` and the
journal collection from `tests/__init__.robot`, which applies its `Suite Setup`
and `Suite Teardown` to every file in `tests/`. `${MID}` is `loki1`, matching
`tests/10__check_services.robot`.

- [ ] **Step 1: Write the stub LLM server**

Create `tests/llm-stub.py` (mode 644 — it is copied to the node and run with
`python3 <path>`, never executed in place):

```python
#!/usr/bin/env python3

#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

#
# Canned OpenAI-compatible chat completions server for the Robot suite.
# No real LLM in CI: no network egress, no cost, deterministic.
#
#   python3 llm-stub.py [PORT]
#

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

CANNED_REPORT = {
    "window_assessment": "degraded",
    "findings": [
        {
            "severity": "high",
            "title": "ROBOTSTUBFINDING synthetic error burst",
            "summary": "Synthetic errors injected by the Robot test suite.",
            "evidence": ["<3> [1:loki1:robot-noise] robot synthetic error"],
            "modules": ["loki1"],
            "suggested_action": "None: this finding is produced by the test stub.",
        }
    ],
}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get('Content-Length') or 0)
        self.rfile.read(length)
        payload = {
            "id": "chatcmpl-robotstub",
            "object": "chat.completion",
            "model": "robot-stub",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(CANNED_REPORT),
                    },
                }
            ],
        }
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')

    def log_message(self, fmt, *args):
        sys.stderr.write("llm-stub: " + (fmt % args) + "\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9099
    HTTPServer(('127.0.0.1', port), Handler).serve_forever()
```

- [ ] **Step 2: Write the Robot suite**

Create `tests/20__anomaly_detector.robot` (mode 644):

```robotframework
*** Settings ***
Library     SSHLibrary
Library     String
Suite Setup       Start the stub LLM server
Suite Teardown    Tear down the anomaly detector

*** Variables ***
${MID}            loki1
${STUB_PORT}      9099
${STUB_URL}       http://127.0.0.1:${STUB_PORT}/v1
${STUB_TITLE}     ROBOTSTUBFINDING
${NOISE_TAG}      robot-noise

*** Keywords ***
Start the stub LLM server
    Put File    ${CURDIR}/llm-stub.py    /tmp/llm-stub.py
    Execute Command    setsid nohup python3 /tmp/llm-stub.py ${STUB_PORT} </dev/null >/tmp/llm-stub.log 2>&1 &
    Wait Until Keyword Succeeds    30s    2s    The stub LLM server answers

The stub LLM server answers
    ${output}    ${rc} =    Execute Command
    ...    curl -sf http://127.0.0.1:${STUB_PORT}/    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0
    Should Be Equal As Strings     ${output}    ok

Tear down the anomaly detector
    Execute Command    api-cli run module/${MID}/set-anomaly-detector --data '{"active":false}'
    Execute Command    pkill -f llm-stub.py

Run module action
    [Arguments]    ${action}    ${data}=${EMPTY}
    IF    '${data}' == '${EMPTY}'
        ${output}    ${rc} =    Execute Command
        ...    api-cli run module/${MID}/${action}    return_rc=${True}
    ELSE
        ${output}    ${rc} =    Execute Command
        ...    api-cli run module/${MID}/${action} --data '${data}'    return_rc=${True}
    END
    Should Be Equal As Integers    ${rc}    0    action ${action} failed: ${output}
    RETURN    ${output}

Query Loki for the detector output
    ${command} =    Catenate
    ...    runagent -m ${MID} bash -c
    ...    'LOKI_ADDR=http://127.0.0.1:$LOKI_HTTP_PORT
    ...    LOKI_USERNAME=$LOKI_API_AUTH_USERNAME
    ...    LOKI_PASSWORD=$LOKI_API_AUTH_PASSWORD
    ...    logcli query --limit 50 --since 20m --forward --no-labels -q -o raw
    ...    "{module_id=\\"${MID}\\"} | json identifier=\\"SYSLOG_IDENTIFIER\\", message=\\"MESSAGE\\"
    ...    | identifier=\\"${MID}/anomaly-detector\\" | line_format \\"{{.message}}\\""'
    ${output}    ${rc} =    Execute Command    ${command}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    logcli failed: ${output}
    RETURN    ${output}

The detector output is in Loki
    ${output} =    Query Loki for the detector output
    Should Contain    ${output}    window_assessment

*** Test Cases ***
Configure the anomaly detector against the stub
    ${data} =    Catenate    SEPARATOR=
    ...    {"active":true,
    ...    "base_url":"${STUB_URL}",
    ...    "model":"robot-stub",
    ...    "api_key":"sk-robot-stub-key",
    ...    "max_lines":50}
    Run module action    set-anomaly-detector    ${data}
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user is-active anomaly-detector.timer
    ...    return_rc=${True}
    Should Be Equal As Strings    ${output}    active

The secrets file is not world readable
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} stat -c %a state/secrets.env    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0
    Should Be Equal As Strings    ${output}    600

The API key never reaches Redis
    ${output} =    Run module action    get-configuration
    Should Not Contain    ${output}    sk-robot-stub-key
    Should Contain       ${output}    "api_key_configured": true

The oneshot service runs and lands in the journal and in Loki
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user start anomaly-detector.service
    ...    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    service failed to run: ${output}
    ${result}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user show anomaly-detector.service -p Result --value
    ...    return_rc=${True}
    Should Be Equal As Strings    ${result}    success
    # The summary line is emitted for every window, nominal or not
    ${journal}    ${rc} =    Execute Command
    ...    journalctl --no-pager -o cat SYSLOG_IDENTIFIER=${MID}/anomaly-detector
    ...    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0
    Should Contain    ${journal}    window_assessment
    # Proves the SyslogIdentifier setting produced the module_id label
    Wait Until Keyword Succeeds    90s    10s    The detector output is in Loki

The LLM path produces the canned finding
    # Inject errors into the current hour, then analyse a window that
    # contains them, so the run cannot take the nominal early-exit.
    FOR    ${i}    IN RANGE    5
        Execute Command    logger -p daemon.err -t ${NOISE_TAG} robot synthetic error ${i}
    END
    Sleep    20s    let the collector ship the noise to Loki
    ${command} =    Catenate
    ...    runagent -m ${MID} env ANOMALY_LLM_BASE_URL=${STUB_URL}
    ...    ANOMALY_LLM_MODEL=robot-stub ANOMALY_LLM_API_KEY=sk-robot-stub-key
    ...    python3 bin/../bin/anomaly-detector --since 30m --pretty --no-webhook
    ${output}    ${rc} =    Execute Command    ${command}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    manual run failed: ${output}
    Should Contain    ${output}    ${STUB_TITLE}

The dry run makes no LLM call
    ${before}    ${rc} =    Execute Command    wc -l < /tmp/llm-stub.log    return_rc=${True}
    ${command} =    Catenate
    ...    runagent -m ${MID} python3 bin/../bin/anomaly-detector --dry-run --since 30m
    ${output}    ${rc} =    Execute Command    ${command}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    dry run failed: ${output}
    Should Contain    ${output}    WINDOW
    Should Contain    ${output}    no LLM call
    ${after}    ${rc2} =    Execute Command    wc -l < /tmp/llm-stub.log    return_rc=${True}
    Should Be Equal As Strings    ${before}    ${after}    the dry run contacted the stub

Disabling the detector clears the secrets
    Run module action    set-anomaly-detector    {"active":false}
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user is-active anomaly-detector.timer
    ...    return_rc=${True}
    Should Not Be Equal As Strings    ${output}    active
    ${secrets}    ${rc} =    Execute Command
    ...    runagent -m ${MID} cat state/secrets.env    return_rc=${True}
    Should Not Contain    ${secrets}    ANOMALY_LLM_API_KEY
    ${config} =    Run module action    get-configuration
    Should Contain    ${config}    "api_key_configured": false
```

Two details that will bite if changed: the manual-run tests invoke the script with
`python3 bin/../bin/anomaly-detector` because `runagent` chdirs to
`AGENT_STATE_DIR` (`%E/state`), so the script is one level up at `%E/bin/`; and the
`env VAR=...` prefix is needed because `runagent` loads `state/environment` but not
`state/secrets.env`, so the API key is not in the inherited environment.

- [ ] **Step 3: Run the suite against the test node**

Sync `imageroot/` to the node first (see "Deploying to the node between tasks"),
because `test-module.sh` with the default `SCENARIO=install` does not reinstall
the module — it tests whatever code is already on the node.

```bash
SSH_KEYFILE=~/.ssh/id_ecdsa ./test-module.sh \
    rl1.leader.default.gs.nethserver.net ghcr.io/nethserver/loki:latest \
    --suite '*anomaly*'
```

Expected: 7 tests PASS. Two to watch:

- `The LLM path produces the canned finding` — if it fails because `is_nominal`
  took the early exit, the injected `daemon.err` lines have not reached Loki yet;
  raise the `Sleep 20s`.
- `The oneshot service runs and lands in the journal and in Loki` — the
  `Wait Until Keyword Succeeds 90s` covers collector latency. If it still fails,
  check `SyslogIdentifier` on the node before suspecting the query:
  `ssh root@rl1.leader.default.gs.nethserver.net journalctl -o cat SYSLOG_IDENTIFIER=loki1/anomaly-detector`

Leave the detector disabled afterwards — the suite teardown does this, but
confirm:

```bash
ssh root@rl1.leader.default.gs.nethserver.net \
  'runagent -m loki1 systemctl --user is-active anomaly-detector.timer || true; pkill -f llm-stub.py || true'
```

- [ ] **Step 4: Commit**

```bash
git add tests/llm-stub.py tests/20__anomaly_detector.robot
git commit -m "test(anomaly-detector): end-to-end suite against a stub LLM server"
```

---

### Task 10: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the action name and parameters (Task 7), the `get-configuration` shape (Task 8), the CLI flags (Task 5).
- Produces: nothing.

The README currently has this outline: `# Loki` → `## Install` → `## Usage` →
`## APIs` → `### configure-module` (`#### Parameters`, `#### Example`) →
`### get-configuration` (`#### Example`) → `## Uninstall`. It documents neither
`set-clm-forwarder` nor `set-syslog-forwarder`, so there is no prior section to
copy — the style to follow is `### \`action-name\`` heading, a one-line
description, a `#### Parameters` bullet list, and a `#### Example` with a
` ```bash ` fenced `api-cli run ...` command.

- [ ] **Step 1: Add the API section**

Insert into `README.md` after the `### \`get-configuration\`` section and before
`## Uninstall`:

````markdown
### `set-anomaly-detector`

Configure the hourly anomaly detector. It sends a scrubbed digest of the
cluster journal to an OpenAI-compatible LLM and writes the findings back to the
journal. Disabled by default.

#### Parameters

- `active`: enable or disable the hourly timer. Required.
- `base_url`: OpenAI-compatible API base URL, without the `/chat/completions`
  suffix. Required when `active` is `true`.
- `model`: model name. Required when `active` is `true`.
- `api_key`: API key. Required when `active` is `true`. Stored in
  `state/secrets.env` with mode `0600`, kept out of the Redis environment hash,
  and never returned by `get-configuration`.
- `max_lines`: cap on prefiltered log lines sent per window. Optional, default
  `500`.
- `webhook_url`: optional URL receiving a copy of each report. Pass an empty
  string to clear it.
- `webhook_token`: optional bearer token for the webhook. Pass an empty string
  to clear it.

#### Example

```bash
api-cli run module/loki1/set-anomaly-detector --data '{
  "active": true,
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key": "sk-...",
  "max_lines": 500
}'
```

Disable it again, which also removes the stored key and token:

```bash
api-cli run module/loki1/set-anomaly-detector --data '{"active": false}'
```

#### Findings

Findings are written to the journal as one JSON object per line under
`SYSLOG_IDENTIFIER=loki1/anomaly-detector`, plus one summary line per window
carrying `window_assessment` (`nominal`, `degraded` or `incident`). The log
collector ships them to Loki, so they are queryable and graphable like any other
log:

```bash
runagent -m loki1 bash -c 'LOKI_ADDR=http://127.0.0.1:$LOKI_HTTP_PORT \
  LOKI_USERNAME=$LOKI_API_AUTH_USERNAME LOKI_PASSWORD=$LOKI_API_AUTH_PASSWORD \
  logcli query --since 24h -o raw \
  "{module_id=\"loki1\"} | json identifier=\"SYSLOG_IDENTIFIER\", message=\"MESSAGE\" | identifier=\"loki1/anomaly-detector\" | line_format \"{{.message}}\""'
```

An empty findings list is the normal outcome. The detector reads its own last 10
findings back out of Loki each run and is instructed not to repeat them, so its
memory needs no state file and nothing extra to back up.

#### Manual execution

The script is also a CLI, with every flag optional, so systemd invokes it with
none. It can be run on any node with an installed Loki module — no unit, no
configuration, nothing written to module state:

```bash
# see exactly what would be sent, with a character and token count.
# no key needed, no cost.
runagent -m loki1 python3 ../bin/anomaly-detector --dry-run --since 2h

# real call, findings on the terminal, no webhook delivery
runagent -m loki1 env \
  ANOMALY_LLM_BASE_URL=https://api.openai.com/v1 \
  ANOMALY_LLM_MODEL=gpt-4o-mini \
  ANOMALY_LLM_API_KEY=sk-... \
  python3 ../bin/anomaly-detector --since 2h --pretty --no-webhook
```

`runagent` changes directory to the module state directory, hence the
`../bin/` prefix.

| Flag | Effect |
|------|--------|
| `--dry-run` | collect, digest, scrub and render the prompt, print it with a character and approximate token count, make no LLM call, emit no findings |
| `--since 2h` | window becomes `[now-2h, now]`; accepts `30m`, `6h`, `2d` |
| `--config FILE` | read `ANOMALY_*` from a plain env file instead of `environment` and `secrets.env` |
| `--pretty` | render findings as indented text instead of JSON lines |
| `--no-webhook` | skip webhook delivery |
| `--max-lines N` | override the line cap for one run |
| `--print-prompt` | print the prompt to stderr alongside a real LLM call |

Precedence: CLI flag, then `--config` file, then shell environment, then
`state/secrets.env`, then `state/environment`.

#### Privacy

**Enabling the anomaly detector sends log text from your cluster to a
third-party API.** This is the real privacy boundary, and it is the reason the
feature is disabled by default and requires an explicit API key.

Before each request the detector removes likely secrets — `password=`,
`token=`, `api_key=`, `secret=` and similar assignments, `Authorization`
headers, base64 or hex runs of 32 characters or more, and email addresses.
IP addresses, hostnames, module IDs and usernames are deliberately **kept**,
because they carry the anomaly signal. This scrubbing is defence in depth, not
a guarantee.

Point `base_url` at a self-hosted gateway (vLLM, Ollama, or any
OpenAI-compatible endpoint) if log text must not leave your infrastructure.
The API key is stored in `state/secrets.env` with mode `0600` and is included in
module backups; the Restic repository is encrypted.
````

- [ ] **Step 2: Extend the `get-configuration` example**

In the existing `### \`get-configuration\`` section, extend the example JSON
response so it shows the new object:

```json
{
  "retention_days": 7,
  "active_from": "2021-05-28T15:49:27Z+00:00",
  "active_to": "2021-05-28T15:49:27Z+00:00",
  "anomaly_detector": {
    "status": "active",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "max_lines": 500,
    "webhook_url": "",
    "api_key_configured": true,
    "last_run": "Wed 2026-07-29 14:00:11 UTC"
  }
}
```

- [ ] **Step 3: Verify the rendered Markdown**

```bash
grep -n '^#' README.md
```

Expected: the outline now reads `# Loki`, `## Install`, `## Usage`, `## APIs`,
`### configure-module`, `#### Parameters`, `#### Example`, `### get-configuration`,
`#### Example`, `### set-anomaly-detector`, `#### Parameters`, `#### Example`,
`#### Findings`, `#### Manual execution`, `#### Privacy`, `## Uninstall`.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(anomaly-detector): document the action, manual runs and privacy boundary"
```

---

## Final verification

- [ ] `./test-unit.sh` — every pytest test passes.
- [ ] `SSH_KEYFILE=~/.ssh/id_ecdsa ./test-module.sh rl1.leader.default.gs.nethserver.net ghcr.io/nethserver/loki:latest` — both Robot suites pass.
- [ ] `git ls-files -s imageroot/bin/anomaly-detector imageroot/actions/set-anomaly-detector/10set imageroot/update-module.d/15systemd test-unit.sh` — all four are mode `100755`.
- [ ] `git ls-files -s imageroot/systemd/user/anomaly-detector.service imageroot/systemd/user/anomaly-detector.timer imageroot/actions/set-anomaly-detector/validate-input.json` — all three are mode `100644`.
- [ ] `grep -rn '%S' imageroot/systemd/` returns nothing.
- [ ] Full timer-driven run against the test node, using the OpenRouter endpoint —
  the last thing the Robot stub cannot prove, because it exercises the real unit,
  the real secret store and the real journal round-trip together:
  ```bash
  NODE=root@rl1.leader.default.gs.nethserver.net
  ORKEY=$(grep -oE 'sk-or-[A-Za-z0-9._-]+' open_router | head -1)
  ssh ${NODE} "api-cli run module/loki1/set-anomaly-detector --data '{
    \"active\": true,
    \"base_url\": \"https://openrouter.ai/api/v1\",
    \"model\": \"google/gemma-4-26b-a4b-it:free\",
    \"api_key\": \"${ORKEY}\"
  }'"
  ssh ${NODE} 'runagent -m loki1 systemctl --user start anomaly-detector.service
  runagent -m loki1 systemctl --user show anomaly-detector.service -p Result --value
  journalctl --no-pager -o cat SYSLOG_IDENTIFIER=loki1/anomaly-detector | tail -5'
  ```
  Expected: `Result=success`, and the journal tail shows JSON findings written by
  the service itself — proving `EnvironmentFile=-%E/state/secrets.env` delivered the
  key and `SyslogIdentifier` labelled the output. Then confirm the round-trip into
  Loki, which is the detector's own memory:
  ```bash
  ssh ${NODE} 'runagent -m loki1 bash -c "LOKI_ADDR=http://127.0.0.1:\$LOKI_HTTP_PORT \
    LOKI_USERNAME=\$LOKI_API_AUTH_USERNAME LOKI_PASSWORD=\$LOKI_API_AUTH_PASSWORD \
    logcli query --since 30m -o raw --limit 20 -q \
    \"{module_id=\\\"loki1\\\"} | json identifier=\\\"SYSLOG_IDENTIFIER\\\", message=\\\"MESSAGE\\\" | identifier=\\\"loki1/anomaly-detector\\\" | line_format \\\"{{.message}}\\\"\""'
  ```
  Then **disable it again and confirm the key is gone**, so the test node is not
  left holding a live credential:
  ```bash
  ssh ${NODE} 'api-cli run module/loki1/set-anomaly-detector --data "{\"active\": false}"
  runagent -m loki1 cat state/secrets.env
  runagent -m loki1 systemctl --user is-active anomaly-detector.timer || true'
  ```
  Expected: an empty `secrets.env` and an inactive timer. This step is mandatory,
  not tidiness — leaving a real OpenRouter key in a shared test node's module state
  is a credential leak.
- [ ] Report the measured prompt size rather than tuning `max_lines` silently. This
  node produces ~9k tokens per hour for the `LINES` block alone, against the spec's
  4–6k target; the default of 500 is fixed by the spec, and lowering it is an
  operator decision.
- [ ] Confirm the key never entered the repo: `git log -p --all | grep -c 'sk-or-'`
  must print `0`, and `git check-ignore open_router test.sh` must list both.

## Spec coverage

| Spec section | Task |
|---|---|
| New files: `bin/anomaly-detector` | 1–5 |
| New files: service + timer | 6 |
| New files: `set-anomaly-detector/*` | 7 |
| Modified: `get-configuration/10get`, `validate-output.json` | 8 |
| Modified: `etc/state-include.conf` | 6 |
| Modified: unit installation on update | 6 (`update-module.d/15systemd`, not `10config`) |
| Modified: `README.md` | 10 |
| Stage 1 Window | 2 |
| Stage 2 Collect (digest, baseline, lines, own-identifier exclusion) | 4 |
| Stage 3 Recall own findings | 4 |
| Stage 4 Scrub | 1 |
| Stage 5 Ask | 3 (prompt, schema), 5 (HTTP) |
| Stage 6 Emit (journal, webhook, stderr-only diagnostics, truncation notice) | 5 |
| Configuration + secrets placement | 7 |
| Enabling and disabling | 7 |
| Manual execution flags and precedence | 5, 10 |
| Error handling table | 4 (`run_logcli`), 5 (`ask_llm`, `parse_findings`, `main` guard) |
| Unit tests | 1–5 |
| Robot test | 9 |
| Manual verification | Final verification |
| Out of scope: no UI, no Redis history, no email, no re-hydration, fixed interval | respected — nothing in this plan adds them |
