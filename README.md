# Loki

Start and configure a instance of Loki, a log aggregation system.
The module use the [Loki official docker image](https://github.com/grafana/loki/releases)

## Install

Instantiate the module, example:
```
add-module ghcr.io/nethserver/loki:latest 1
```

The output of the command will return the instance name.
Output example:
```
{"module_id": "loki1", "image_name": "Loki log aggregation system", "image_url": "ghcr.io/nethserver/loki:latest"}
```

After the installation, the Loki server will listen on the IP address of the selected node's VPN interface, using the default fixed port `3100`.

## Usage

The instance can be queried with logcli. eg:
```
root@leader:~# add-module ghcr.io/nethserver/loki:latest 1
Extracting container filesystem ui to /var/lib/nethserver/cluster/ui/apps/loki1
ui/index.html
b89469d5a964b4e97ca2d40b25758cd2e06a96ebe6c00af7d95b1a2d5cf635a5
{"module_id": "loki1", "image_name": "Loki log aggregation system", "image_url": "ghcr.io/nethserver/loki:latest"}
root@leader:~# add-module ghcr.io/nethserver/promtail:latest 1
Extracting container filesystem ui to /var/lib/nethserver/cluster/ui/apps/promtail1
ui/index.html
fe8d71c5b5f0c579ba96e4a64660b275e3a667ffddcc576b1e4cab9f3a8bf9f8
{"module_id": "promtail1", "image_name": "Promtail logs collector for Loki", "image_url": "ghcr.io/nethserver/promtail:latest"}
root@leader:~# logcli labels -q
__name__
job
nodename
root@leader:~# logcli labels nodename -q
bullseye
leader
root@leader:~# logcli  query -q --no-labels -t '{nodename="leader"} | json | line_format "{{.MESSAGE}}"'
2021-05-28T15:49:27Z Created slice cgroup user-libpod_pod_d32e9a0f2237ca996c90f6790ca90447b3e8cbb30d16cc91701ab8257bb704d6.slice.
2021-05-28T15:49:27Z 2021-05-28 15:49:27.621079036 +0000 UTC m=+0.106351212 container create 6e51520a9fa4f63ac0f3dbbf89ef2ef075041dd90c5df952a35206a14691c654 (image=k8s.gcr.io/pause:3.2, name=d32e9a0f2237-infra)
2021-05-28T15:49:27Z 2021-05-28 15:49:27.62160088 +0000 UTC m=+0.106873062 pod create d32e9a0f2237ca996c90f6790ca90447b3e8cbb30d16cc91701ab8257bb704d6 (image=, name=loki)
2021-05-28T15:49:27Z d32e9a0f2237ca996c90f6790ca90447b3e8cbb30d16cc91701ab8257bb704d6
2021-05-28T15:49:27Z loki.service: Found left-over process 19008 (podman pause) in control group while starting unit. Ignoring.
2021-05-28T15:49:27Z This usually indicates unclean termination of a previous run, or service implementation deficiencies.
```

`logcli` will use the default Loki instance of the cluster, this can be changed using the environment variable [`LOKI_ADDR`](https://grafana.com/docs/loki/latest/getting-started/logcli/#example)

## APIs

The module provides some APIs to interact with the Loki instance:

- `configure-module`
- `get-configuration`

### `configure-module`

Configure the Loki instance.

#### Parameters

- `retention_days`: The number of days to keep the logs.

#### Example

```bash
api-cli run module/loki1/configure-module '{"retention_days": 7}'
```

### `get-configuration`

Get the Loki instance configuration.

#### Example

```bash
api-cli run module/loki1/get-configuration
```

```json
{
  "retention_days": 7,
  "active_from": "2021-05-28T15:49:27Z+00:00",
  "active_to": "2021-05-28T15:49:27Z+00:00",
  "insights": {
    "status": "active",
    "base_url": "https://insights.nethesis.it",
    "verify_tls": true,
    "subscription_configured": true,
    "last_run": "Wed 2026-08-07 14:00:11 UTC"
  }
}
```

Note: `active_to` field WILL miss if the instance is still active.

### `set-insights`

Configure the insights collector. It follows the cluster journal
continuously — scrubbing likely secrets, masking variable text and folding
each line into counted templates as it arrives — and every 15 minutes ships
what it has accumulated to the Nethesis insights service, where the actual
(LLM-based) analysis happens. The node performs no analysis and holds no LLM
credential. Disabled by default.

Only a bounded number of distinct templates is held in memory between two
bundles; past that, the least recently seen one is discarded. The per-module
counts a bundle carries are not subject to that cap, so a discarded template
still shows up in the counts.

#### Parameters

- `active`: enable or disable the `insights-collector` daemon. Required.
- `base_url`: base URL of the insights server. Required when `active` is
  `true`. Some deployments path-mount the server (e.g.
  `https://host/insights`) rather than serving it at the bare host, in which
  case that path segment is part of `base_url`; check with
  `curl <base_url>/healthz`, which should return `200`.
- `verify_tls`: verify the server TLS certificate. Optional, default `true`.
  Set to `false` only for a self-signed test server — never against a
  production endpoint.

No API key is required or accepted any more. Identity comes from the node's
existing NethServer subscription: the collector reads `system_id` and its
secret from the `cluster/subscription` Redis hash at run time and
authenticates as `Authorization: Basic base64(system_id:secret)`. A node with
no subscription ships nothing and says so in the journal.

#### Example

```bash
api-cli run module/loki1/set-insights --data '{
  "active": true,
  "base_url": "https://insights.nethesis.it"
}'
```

Disable it again:

```bash
api-cli run module/loki1/set-insights --data '{"active": false}'
```

#### Findings

Findings are no longer written to the local journal: analysis happens on the
insights server, and findings are read back through its API, not through this
module. The node's only journal output is operational, one line per window
under `SYSLOG_IDENTIFIER=loki1/insights-collector`: a
`shipped N templates, M lines -> 202` line on success, an error line
otherwise.

Check the collector's own health with:

```bash
runagent -m loki1 journalctl --user -u insights-collector
```

#### Manual execution

The collector is also a plain CLI with three flags, so systemd invokes it
with none:

```bash
# See exactly what would leave the node before enabling anything.
# No subscription needed, no server URL needed, nothing is shipped.
runagent -m loki1 ../bin/insights-collector --print
```

`runagent` changes directory to the module state directory, hence the
`../bin/` prefix.

| Flag | Effect |
|------|--------|
| `--print` | build the bundle and write it to stdout instead of shipping; needs no subscription and no server URL |
| `--max-lines N` | cap on the templates a bundle may carry, divided between module families. Default `500` |
| `--minutes N` | window size in minutes. Default `15` |
| `--daemon` | follow the log stream, shipping a bundle every `--minutes`, instead of collecting one closed window and exiting; this is how `systemctl --user start insights-collector.service` runs it |

Without `--daemon`, a run reads one already-closed window and exits — useful
for manual testing, and deterministic in a way that watching the daemon is
not. As a long-running daemon, it reads forward from a cursor it keeps in
`insights_stream_cursor` in the module state directory, so a restart resumes
where it stopped instead of losing whatever it had not yet shipped. A failed
read is logged and retried on the next pass, leaving the cursor where it was;
a failed ship is logged and the loop continues to the next window.

#### Sizing

What ships is deduplicated *templates*, not raw log lines, so the outbound
volume is far below the raw line count of a window. `--max-lines` caps how
many templates a bundle may carry, 500 by default, divided between module
families with a floor each so a chatty module cannot starve the rest. Check
your own figure with `--print` before enabling the collector.

#### Privacy

What leaves the node is masked, deduplicated log templates plus per-module
counts. A template still carries the fixed text of the log messages it stands
for — that text is the signal — but the variable parts are replaced and
identical events collapse into one counted entry, so no line is sent verbatim.
Two passes run before anything is sent:
the `scrub()` function in `imageroot/bin/insights-collector`
removes likely secrets (`password=`, `token=`, `api_key=`, `Authorization`
headers, long base64 runs, email addresses), and `mask()` in the same file
replaces variable text (timestamps, PIDs, addresses, UUIDs and similar) so
that repeated events collapse to one template. Both passes run as the line
is read, so an unscrubbed line is never held in memory for a whole window.
Each template carries at most two example lines, truncated to 512
characters. This is defence in depth, not a guarantee.

The destination is the Nethesis insights service, authenticated with the
subscription identity (`system_id` and secret) the node already holds —
nothing new to provision or store. This is an explicit improvement over the
previous design: no third-party LLM API key is stored on any node any more,
and `state/secrets.env` no longer exists.

The feature is disabled by default.

## Uninstall

To uninstall the instance:
```
remove-module loki1
```
