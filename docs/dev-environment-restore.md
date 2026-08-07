# Restoring the rl1 dev environment

Steps to rebuild the `rl1.leader.default.gs.nethserver.net` dev box back to
the state it was in during the `anomaly_detector` branch work, after it gets
torn down. Written for an agent with no memory of this session.

**Deliberately excluded** (ask the user/operator, never store in this repo):
the cluster subscription `auth_token`, and any `system_id` value read back
from `cluster/subscription`. Everything else below is reproducible from
public repo state.

## 1. Provision + install NS8

Use the `accessing-nethserver-test-vps` skill (or, if unavailable,
`ns8-terraform-infra`'s `tofu apply -var 'leader_node={"dn1":"rl1"}'`, then
NS8 core install + `create-cluster`). Set the real admin password per that
skill — do not leave the default cluster-admin password from
`create-cluster` in place.

## 2. Enroll the cluster subscription

Required for the insights feature below to actually authenticate — without
it, `insights-collector` logs "no subscription found" and ships nothing.

```bash
api-cli run cluster/set-subscription --data '{"subscription":{"auth_token":"<TOKEN>"}}'
```

`<TOKEN>` is a Nethesis subscription auth token, ≥32 chars — get it from the
operator, not from any file in this repo. Confirm it landed with:

```bash
api-cli run cluster/get-subscription
```

## 3. Install modules

```bash
add-module ghcr.io/nethserver/loki:latest 1        # -> loki1
add-module ghcr.io/nethserver/crowdsec:latest 1    # -> crowdsec1 (+ its firewall-bouncer companion)
```

`crowdsec1` was present on the box but **untouched** in this session — no
config changes were made to it. It matters only if continuing the
blocked-IP-evidence work; see
`/home/giacomo/projects/ns8/ns8-crowdsec/crowdsec.plan` on this machine (not
in this repo, not on rl1 — a local planning note) for that follow-on design.

## 4. Update loki1 to the branch build

The `anomaly_detector` branch publishes its image via CI on every push —
no local build needed. Command actually used:

```bash
update-module ghcr.io/nethserver/loki:anomaly_detector loki1 --force
```

## 5. Configure the insights collector

```bash
api-cli run module/loki1/set-insights --data '{
  "active": true,
  "base_url": "https://controller.gs.nethserver.net/insights",
  "verify_tls": false
}'
```

The `/insights` path suffix is required — the server on
`controller.gs.nethserver.net` is path-mounted, not on the bare host (bare
host `/v1/bundles` 404s; `curl -k https://controller.gs.nethserver.net/insights/healthz`
should return `200`). `verify_tls: false` matches that server's self-signed
cert; use `true` against a properly-certified endpoint.

## 6. Verify

```bash
# Confirm config landed
api-cli run module/loki1/get-configuration
# -> "insights": {"status": "active", "base_url": "https://controller.gs.nethserver.net/insights", ...}

# Zero-cost payload check, no shipping
runagent -m loki1 ../bin/insights-collector --print

# Actually ship one window
runagent -m loki1 ../bin/insights-collector
# or, as the timer would:
runagent -m loki1 systemctl --user start insights-collector.service
runagent -m loki1 journalctl --user -u insights-collector
```

## Known state at time of writing (not yet resolved — do not assume fixed)

- **Real end-to-end shipping against `controller.gs.nethserver.net` was not
  confirmed working.** The server accepts auth and rejects malformed bodies
  fast, but a real, well-formed bundle causes a request that hangs until the
  client's 60s read timeout — looks like a server-side issue (likely a
  downstream queue/broker not responding in that dev deployment), not
  something fixable from `ns8-loki`. Re-check this before relying on it.
- Local unit tests: `./test-unit.sh` → 106 passed.
- CI on the branch: green as of commit `8b3e86b` (port-collision fix in
  `tests/20__insights.robot` — the e2e stub was colliding with
  node_exporter's default port 9100 on the test node; moved to 19100).
- PR: https://github.com/NethServer/ns8-loki/pull/70 (draft, no assignee, no
  reviewer requested as of last check).
