#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Loki HTTP client.

Everything goes over the HTTP API. logcli is deliberately not used: the
two-pass design issues one query per module per run, and a subprocess spawn
per module is both slower and harder to diagnose than a status code.
"""

import base64
import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 60

# Host-level journal records (sshd, systemd, runagent) carry no module_id
# label at all, so the label-values endpoint never lists them. They are
# collected under this synthetic bucket instead. Measured on a live cluster,
# these lines are the majority of security-relevant traffic, so dropping them
# would defeat the point of the collector.
HOST_BUCKET = ""


class LokiError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url, username, password, timeout=TIMEOUT):
        self._base = base_url.rstrip("/")
        self._auth = base64.b64encode(
            "{0}:{1}".format(username, password).encode()).decode()
        self._timeout = timeout

    def _get(self, path, params):
        url = "{0}{1}?{2}".format(self._base, path, urllib.parse.urlencode(params))
        request = urllib.request.Request(url)
        request.add_header("Authorization", "Basic " + self._auth)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            raise LokiError("{0} {1}: {2}".format(path, exc.code, body)) from exc
        except urllib.error.URLError as exc:
            raise LokiError("{0}: {1}".format(path, exc.reason)) from exc

    @staticmethod
    def _ns(when):
        return str(int(when.timestamp() * 1e9))

    def module_ids(self, start, end):
        """Module IDs present in the window, plus the host bucket.

        The label endpoint reads the index rather than series data, so unlike
        a metric query it is not subject to max_query_series.
        """
        payload = self._get("/loki/api/v1/label/module_id/values",
                            {"start": self._ns(start), "end": self._ns(end)})
        return sorted(payload.get("data") or []) + [HOST_BUCKET]

    def digest(self, at, range_seconds):
        """{(module_id, priority): count} over the range ending at `at`.

        Returns {} on failure. A busy cluster can exceed max_query_series on
        this aggregation, and losing the digest costs prioritisation and the
        `expected` field, not the run.
        """
        query = ('sum by (module_id, priority) '
                 '(count_over_time({{node_id=~".+"}} | json priority="PRIORITY" [{0}s]))'
                 ).format(int(range_seconds))
        try:
            payload = self._get("/loki/api/v1/query",
                                {"query": query, "time": at.isoformat()})
        except LokiError:
            return {}
        out = {}
        for series in (payload.get("data") or {}).get("result") or []:
            labels = series.get("metric") or {}
            try:
                priority = int(labels.get("priority", -1))
                value = float(series["value"][1])
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            out[(labels.get("module_id", HOST_BUCKET), priority)] = value
        return out

    def lines(self, module_id, start, end, limit, denylist, self_identifier,
              direction="forward"):
        """Prefiltered lines for one module. Returns a list of (ts_ms, text)."""
        selector = ('{{module_id="{0}", node_id=~".+"}}'.format(module_id)
                    if module_id else '{node_id=~".+", module_id=""}')
        stages = [
            selector,
            '| json priority="PRIORITY", identifier="SYSLOG_IDENTIFIER", message="MESSAGE"',
            '| identifier != "{0}"'.format(self_identifier),
            '| priority < 5 or category="security"',
        ]
        if denylist:
            stages.append('!~ "{0}"'.format("|".join(denylist)))
        stages.append(
            '| line_format "<{{.priority}}> [{{.identifier}}] {{.message}}"')
        payload = self._get("/loki/api/v1/query_range", {
            "query": " ".join(stages),
            "start": self._ns(start), "end": self._ns(end),
            "limit": str(int(limit)), "direction": direction,
        })
        # category is a stream label, not a line field, so it is read per
        # series rather than parsed back out of the rendered line. Losing it
        # would make the server's security gate condition unreachable.
        out = []
        for series in (payload.get("data") or {}).get("result") or []:
            category = (series.get("stream") or {}).get("category", "")
            for ns, text in series.get("values") or []:
                out.append((int(ns) // 1000000, text, category))
        out.sort()
        return out
