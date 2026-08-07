# Loki anomaly detector — design

Date: 2026-07-29
Repository: ns8-loki
Status: approved design, not yet implemented

## Goal

Detect anomalies in NethServer 8 journal logs by sending a compact,
scrubbed representation of each hour's logs to a remote LLM and recording
its findings back into the journal.

The detector ships as an extension of the existing `ns8-loki` module,
alongside `syslog-forwarder` and `cloud-log-manager-forwarder`. It is
disabled by default and requires explicit configuration.

## Motivation and constraints

Measured on a live single-node cluster (`rl1`, 9 modules) over one hour:

| Metric | Count |
|--------|-------|
| Total journal lines | 1317 (~32k/day) |
| Lines with `PRIORITY <= 4` | 82 |
| Lines with `category="security"` | 268 |
| Top talker | `nethvoice2` (656) |

A raw hourly dump is roughly 40k input tokens per hour, near 1M tokens per
day per node. Busier nodes are worse by an order of magnitude. The design
therefore sends a digest plus a capped set of prefiltered lines, targeting
4–6k tokens per window.

Loki labels available for selection: `node_id`, `module_id`, `category`,
`job`, `service_name`. Journal fields reachable through the `json` stage:
`PRIORITY`, `SYSLOG_IDENTIFIER`, `MESSAGE`.

## Architecture

### New files

```
imageroot/bin/anomaly-detector                       # the whole job, one Python script
imageroot/systemd/user/anomaly-detector.service      # Type=oneshot
imageroot/systemd/user/anomaly-detector.timer        # OnCalendar=hourly
imageroot/actions/set-anomaly-detector/validate-input.json
imageroot/actions/set-anomaly-detector/10set
```

### Modified files

- `imageroot/actions/get-configuration/10get` — expose detector state
- `imageroot/actions/get-configuration/validate-output.json` — new object
- `imageroot/etc/state-include.conf` — add `state/secrets.env`
- `imageroot/update-module.d/10config` — install the new units
- `README.md` — configuration, manual test, privacy statement

### Process shape

A `systemd` timer fires hourly and starts a `Type=oneshot` service that
analyses one window and exits. The window derives from the wall clock, so
there is no cursor file and no drift. `Persistent=true` recovers a single
window missed across a reboot. A crashed run costs exactly one window; the
next fire retries.

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

Unit files use `%E`, matching the convention established by #68.

`SyslogIdentifier=%u/%N` is mandatory, not cosmetic. The log collector
(Alloy, configured by `core/imageroot/var/lib/nethserver/node/bin/generate-promtail-config`
in ns8-core) assigns the `module_id` label only when the module name appears
in `_SYSTEMD_UNIT`, `SYSLOG_IDENTIFIER` or `CONTAINER_NAME`. A rootless user
unit reports `_SYSTEMD_UNIT=user@<uid>.service`, which contains no module
name, so without an explicit identifier the detector's own output would be
ingested unlabeled and the recall query in stage 3 would never match it.
`%u/%N` expands to `loki1/anomaly-detector`, which satisfies the label rule
and doubles as a stable selector. The same convention is already used by
five units in other NS8 modules.

The timer, not the service, is enabled and disabled by the action.

## Data flow

One run performs six stages.

### 1. Window

`[hour_start, hour_start + 1h)` computed from the wall clock, where
`hour_start` is the start of the previous full hour. `--since` overrides
this for manual runs.

### 2. Collect

Three `logcli` invocations, all selecting `{node_id=~".+"}` so a single
detector on the Loki node covers the whole cluster:

- **Digest** — `sum by (module_id, priority) (count_over_time({node_id=~".+"} | json priority="PRIORITY" [1h]))`
- **Baseline** — the same query over `[7d]`, divided by 168, giving an
  expected hourly rate per `(module_id, priority)` pair
- **Lines** — `logcli query --forward -o jsonl` over the window, selecting
  `PRIORITY < 5 or category="security"`, with `--limit` set to
  `ANOMALY_MAX_LINES` (default 500)

Loki stores the entire journal record as the line, so every query needs a
`| json` stage to extract `MESSAGE`, `PRIORITY` and `SYSLOG_IDENTIFIER`,
then a `line_format` to render them, exactly as
`cloud-log-manager-forwarder` does today.

The line query must exclude the detector's own identifier:

```
| identifier != "<MODULE_ID>/anomaly-detector"
```

Without this the detector feeds on itself. Diagnostics written to stderr
land in the journal at `PRIORITY=3`, which the `PRIORITY < 5` prefilter
would collect on the next run, so a single failure would be re-analysed
every hour and the evidence lines of past findings would re-enter the
prompt as fresh input.

`logcli` requires `LOKI_ADDR`, `LOKI_USERNAME` and `LOKI_PASSWORD`, derived
from `LOKI_HTTP_PORT` and `LOKI_API_AUTH_*` exactly as
`cloud-log-manager-forwarder` does today.

### 3. Recall own findings

A fourth query over the last 24h selects the detector's own past output:

```
{module_id="<MODULE_ID>"} | json identifier="SYSLOG_IDENTIFIER"
  | identifier="<MODULE_ID>/anomaly-detector"
```

The last 10 finding titles enter the prompt so the LLM can suppress
repeats instead of re-reporting them. Because findings are emitted to the
journal and the collector ships the journal to Loki, the detector's memory
is self-hosted: no state file, nothing extra to back up.

### 4. Scrub

Every collected line and every rendered prompt block passes through an
ordered regex list before leaving the process:

| Pattern | Replacement |
|---------|-------------|
| `(?i)(bearer\|token\|api[-_]?key\|secret\|password\|passwd\|pwd)[=:\s"']+\S+` | `\1=<redacted>` |
| `(?i)authorization:\s*\S+\s*\S*` | `authorization: <redacted>` |
| base64 or hex runs of 32 or more characters | `<redacted-blob>` |
| email addresses | `<redacted-email>` |

IP addresses, hostnames, module IDs and usernames appearing in message
text are deliberately preserved: they carry the anomaly signal.

The scrub is defence in depth, not a guarantee. The real privacy boundary
is that log text is sent to a third-party API, and the README states this
plainly.

### 5. Ask

A single `POST` to `${ANOMALY_LLM_BASE_URL}/chat/completions` using the
OpenAI-compatible chat completions shape, so any of OpenAI, OpenRouter,
vLLM, Ollama or a self-hosted gateway works with one code path.
`temperature: 0` and `response_format: {"type": "json_schema", ...}` to
force a machine-checkable answer.

The system message pins the role: an NS8 cluster log analyst judging this
hour against the supplied baseline, reporting only actionable deviations,
never restating a recalled finding unless it has escalated.

The user message carries four fenced blocks:

- `WINDOW` — start and end timestamps, and whether the line cap truncated
  the window
- `RATES` — per `(module_id, priority)`: observed this hour vs expected per
  hour
- `RECENT_FINDINGS` — last 10 titles with severity
- `LINES` — scrubbed, formatted `<priority> [node:module:identifier] message`

### 6. Emit

Response schema:

```json
{
  "findings": [
    {
      "severity": "critical|high|medium|low",
      "title": "short, stable, dedup-able",
      "summary": "what happened and why it deviates from baseline",
      "evidence": ["verbatim scrubbed log lines that justify it"],
      "modules": ["nethvoice2"],
      "suggested_action": "what an admin should check"
    }
  ],
  "window_assessment": "nominal|degraded|incident"
}
```

An empty `findings` array is the normal outcome.

Each finding is written as one JSON line to stdout, plus one summary line
carrying `window_assessment`. Under systemd, stdout is the journal, so
findings are indexed by the collector into Loki with
`SYSLOG_IDENTIFIER=<module_id>/anomaly-detector` and become queryable and
graphable like any other log. When the script is run by hand the same lines appear on
the terminal — one code path, no mode divergence.

If `ANOMALY_WEBHOOK_URL` is set, the same JSON is POSTed there, with an
optional bearer token. Journald is the source of truth; the webhook is
best-effort delivery.

Diagnostics go exclusively to stderr, so the `identifier="anomaly-detector"`
Loki query returns findings and nothing else.

Truncation is never silent: if the line cap trims the window, that fact
enters both the prompt and a journald notice on stderr.

## Configuration

One action, `set-anomaly-detector`, following the `oneOf` on `active` shape
already used by `set-clm-forwarder`.

```json
{
  "active": true,
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4o-mini",
  "api_key": "sk-...",
  "max_lines": 500,
  "webhook_url": "https://example.org/hook",
  "webhook_token": "..."
}
```

`base_url`, `model` and `api_key` are required when `active` is `true`.
`max_lines`, `webhook_url` and `webhook_token` are optional.

### Where each value is stored

Secrets go to `state/secrets.env` and never to the `environment` file,
because `environment` is mirrored into the Redis hash
`module/<module_id>/environment` and would be readable by anything able to
read that hash. The pattern follows ns8-dependencytrack.

| Variable | Location |
|----------|----------|
| `ANOMALY_LLM_API_KEY` | `state/secrets.env` |
| `ANOMALY_WEBHOOK_TOKEN` | `state/secrets.env` |
| `ANOMALY_LLM_BASE_URL` | `environment` |
| `ANOMALY_LLM_MODEL` | `environment` |
| `ANOMALY_WEBHOOK_URL` | `environment` |
| `ANOMALY_MAX_LINES` | `environment` |

`secrets.env` is written with `agent.read_envfile` / `agent.write_envfile`,
merging rather than overwriting so unrelated keys survive, followed by an
explicit `os.chmod(0o600)` — `safe_open` preserves the mode of an existing
file but a freshly created one should not depend on the umask.

`state/secrets.env` is added to `etc/state-include.conf` so restore keeps
the key. The Restic repository is encrypted.

### Enabling and disabling

`active: true` writes the configuration, then
`systemctl --user enable --now anomaly-detector.timer`. Re-running while
active only rewrites the configuration; the timer needs no restart because
the oneshot reads its environment at each fire.

`active: false` runs `systemctl --user disable --now anomaly-detector.timer`,
unsets the `environment` variables, and removes both keys from
`secrets.env` rather than leaving them behind.

### get-configuration

A new `anomaly_detector` object:

| Field | Source |
|-------|--------|
| `status` | `systemctl --user is-active anomaly-detector.timer` mapped to `active`/`failed`/`inactive` |
| `base_url`, `model`, `max_lines`, `webhook_url` | `environment` |
| `api_key_configured` | boolean, key presence in `secrets.env` |
| `last_run` | `systemctl --user show anomaly-detector.service -p ExecMainExitTimestamp` |

The API key value is never returned.

## Manual execution

The script is also the CLI, via `argparse` with every flag optional, so
systemd invokes it with none. `runagent -m loki1` already exports
`LOKI_HTTP_PORT` and `LOKI_API_AUTH_*`, so log collection works on any
existing machine with no install, no unit, and nothing written to module
state.

```
scp imageroot/bin/anomaly-detector root@node:/tmp/
ssh root@node runagent -m loki1 python3 /tmp/anomaly-detector --dry-run --since 2h
```

| Flag | Effect |
|------|--------|
| `--dry-run` | collect, digest, scrub and render the prompt, print it with a character and approximate token count, make no LLM call, emit no findings |
| `--since 2h` | window becomes `[now-2h, now]`; accepts `30m`, `6h`, `2d` |
| `--config FILE` | read `ANOMALY_*` from a plain env file instead of `environment` and `secrets.env` |
| `--pretty` | render findings on stdout as indented human-readable text instead of JSON lines |
| `--no-webhook` | skip webhook delivery |
| `--max-lines N` | override the line cap for one run |
| `--print-prompt` | print the prompt alongside a real LLM call |

Precedence: CLI flag, then `--config` file, then shell environment, then
`secrets.env`, then `environment`.

Typical sequence on an existing machine:

```
# 1. see what would be sent — no key, no cost
runagent -m loki1 python3 /tmp/anomaly-detector --dry-run --since 2h

# 2. real call, findings on the terminal, no webhook delivery
ANOMALY_LLM_BASE_URL=https://api.openai.com/v1 \
ANOMALY_LLM_MODEL=gpt-4o-mini \
ANOMALY_LLM_API_KEY=sk-... \
  runagent -m loki1 python3 /tmp/anomaly-detector --since 2h --pretty --no-webhook
```

The manual flags add behaviour; they never alter the default path taken by
the systemd unit.

## Error handling

A oneshot failure costs one window, so the rule is to fail loudly, exit
non-zero, and let the next timer fire retry. No internal retry loops except
at the HTTP layer.

| Failure | Behaviour |
|---------|-----------|
| `logcli` exits non-zero or exceeds its 300s timeout | log stderr, exit 1; no LLM call and no cost |
| zero prefiltered lines and rates match baseline | log `nominal, no LLM call`, exit 0 |
| LLM returns 429 or 5xx | `urllib3` `Retry(total=3, backoff_factor=2, status_forcelist=[429,500,502,503,504])`, then exit 1 |
| LLM returns 401 or 403 | log `check API key`, exit 1, no retry |
| response does not match the schema | log the body truncated to 500 characters, exit 1, emit no partial finding |
| webhook delivery fails | findings are already in the journal; log the error and exit 1 so the failure is visible |
| `secrets.env` missing while the timer is enabled | log `not configured`, exit 1 |

Skipping the LLM call on an idle window is a meaningful saving on quiet
nodes, where most hours produce nothing worth analysing.

## Testing

### Unit tests

`scrub(line)`, `build_digest(rates, baseline)`, `render_prompt(...)` and
`parse_findings(body)` are top-level functions with no I/O, tested with
`pytest` in a container in the style of `core/agent/test-agent.sh` in
ns8-core. Each scrub row gets a positive and a negative case, plus a test
asserting that an IP address and a module ID survive scrubbing.

### Robot test

`tests/20__anomaly_detector.robot`:

1. Start a local stub HTTP server returning a canned findings response in
   the OpenAI chat completions shape.
2. Call `set-anomaly-detector` pointing `base_url` at the stub.
3. Run `systemctl --user start anomaly-detector.service`.
4. Assert the finding appears in the journal and in Loki under
   `identifier="<module_id>/anomaly-detector"` — this also proves the
   `SyslogIdentifier` setting produced the `module_id` label.
5. Assert `get-configuration` reports `api_key_configured: true` and never
   echoes the key.

No real LLM in CI: no network egress, no cost, deterministic.

### Manual verification

A one-shot run against a real node with a real key, to judge whether the
findings are useful. The stub-based test proves plumbing only; prompt
quality can only be assessed against real logs.

## Out of scope

- Vue UI. `ns8-loki` has no UI beyond `ui/index.html`, and findings are
  queryable through Loki and deliverable by webhook.
- Redis-backed findings history. The journal round-trip through the log
  collector already provides it.
- Email or cluster notification delivery.
- Local placeholder mapping and re-hydration of redacted values.
- Configurable interval. Hourly is fixed; only the line cap is tunable.
