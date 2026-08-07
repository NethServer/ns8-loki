#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import pytest

from insights.masking import MASKING_VERSION, mask


class TestIndividualRules:
    @pytest.mark.parametrize("raw,expected", [
        ("started at 2026-08-05T14:42:32Z", "started at <TS>"),
        ("started at 2026-08-05 14:42:32.123456+00:00", "started at <TS>"),
        ("elapsed 14:42:32", "elapsed <TS>"),
        ("elapsed 14:42:32.918", "elapsed <TS>"),
    ])
    def test_timestamps(self, raw, expected):
        assert mask(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("smbd[12345]: oplock", "smbd[<PID>]: oplock"),
        ("killed pid=987", "killed pid=<PID>"),
        ("killed pid 987", "killed pid <PID>"),
        ("main process (4211) exited", "main process (<PID>) exited"),
    ])
    def test_pids(self, raw, expected):
        assert mask(raw) == expected

    def test_uuid(self):
        assert mask("job 3f2504e0-4f89-11d3-9a0c-0305e82c3301 done") == "job <UUID> done"

    def test_uuid_is_not_shredded_into_hex(self):
        # The hex rule would otherwise eat a UUID piecewise, producing
        # <HEX>-<HEX>-... and a template that never groups with itself.
        assert "<HEX>" not in mask("id=3f2504e0-4f89-11d3-9a0c-0305e82c3301")

    @pytest.mark.parametrize("raw,expected", [
        ("from 10.0.0.4", "from <IP>"),
        ("from 192.168.100.200", "from <IP>"),
        ("peer fe80::1", "peer <IP>"),
        ("peer 2001:db8::8a2e:370:7334", "peer <IP>"),
    ])
    def test_ip_addresses(self, raw, expected):
        assert mask(raw) == expected

    def test_ipv6_is_not_shredded_into_hex(self):
        assert "<HEX>" not in mask("peer 2001:db8::8a2e:370:7334")

    def test_ip_with_port(self):
        assert mask("connection refused to 10.0.0.4:8080") == \
            "connection refused to <IP>:<PORT>"

    def test_hex_blob(self):
        assert mask("sha 9f86d081884c7d65") == "sha <HEX>"

    def test_short_hex_is_left_alone(self):
        # "cafe" is a word far more often than it is a checksum.
        assert mask("the cafe is open") == "the cafe is open"

    @pytest.mark.parametrize("raw,expected", [
        ("wrote /tmp/abc123/file", "wrote <PATH>"),
        ("read /proc/12345/status", "read <PATH>"),
        ("socket /run/user/1000/bus", "socket <PATH>"),
    ])
    def test_volatile_paths(self, raw, expected):
        assert mask(raw) == expected

    def test_stable_paths_are_preserved(self):
        # A real config path is signal and must survive.
        assert mask("/etc/loki/loki-config.yaml") == "/etc/loki/loki-config.yaml"

    def test_bare_numbers(self):
        assert mask("retried 37 times") == "retried <NUM> times"

    def test_single_digits_are_preserved(self):
        # Priority markers like <3> and version suffixes carry meaning.
        assert mask("<3> module traefik1 failed") == "<3> module traefik1 failed"


class TestGrouping:
    def test_same_event_different_volatiles_yields_one_template(self):
        a = mask("smbd[1234]: connection refused to 10.0.0.4:8080 after 37 tries")
        b = mask("smbd[9876]: connection refused to 10.9.9.9:9090 after 4210 tries")
        assert a == b

    def test_genuinely_different_events_stay_distinct(self):
        a = mask("smbd[1234]: connection refused to 10.0.0.4:8080")
        b = mask("smbd[1234]: permission denied for 10.0.0.4:8080")
        assert a != b


class TestSafety:
    def test_is_idempotent(self):
        # Templates get compared and hashed; masking twice must not drift.
        raw = "smbd[1234] 2026-08-05T14:42:32Z 10.0.0.4:8080 id=3f2504e0-4f89-11d3-9a0c-0305e82c3301 n=37"
        once = mask(raw)
        assert mask(once) == once

    def test_placeholders_are_never_re_masked(self):
        assert mask("<PID> <NUM> <IP> <TS> <UUID> <HEX> <PATH>") == \
            "<PID> <NUM> <IP> <TS> <UUID> <HEX> <PATH>"

    def test_scrub_markers_survive(self):
        # masking runs after scrub(); its redactions must not be mangled.
        assert mask("token=<redacted> blob=<redacted-blob>") == \
            "token=<redacted> blob=<redacted-blob>"

    def test_empty_and_whitespace(self):
        assert mask("") == ""
        assert mask("   ") == "   "

    def test_version_is_an_int(self):
        assert isinstance(MASKING_VERSION, int)
        assert MASKING_VERSION >= 1


class TestAccountNames:
    """An SSH dictionary attack must collapse to one template, not hundreds.

    Measured on six hours of real cluster logs: 319 of 561 templates were
    single-occurrence brute-force attempts differing only by account name.
    """

    def test_invalid_user_collapses(self):
        a = mask("Connection closed by invalid user admin 10.0.0.4 port 5000")
        b = mask("Connection closed by invalid user alice 10.9.9.9 port 6000")
        assert a == b
        assert "<USER>" in a

    def test_authenticating_user_collapses(self):
        a = mask("Connection closed by authenticating user root 10.0.0.4 port 1")
        b = mask("Connection closed by authenticating user nobody 10.0.0.4 port 1")
        assert a == b

    def test_distinct_auth_events_stay_distinct(self):
        assert mask("Invalid user admin from 10.0.0.4") != \
            mask("Accepted password for admin from 10.0.0.4")

    def test_is_still_idempotent_with_user_rule(self):
        once = mask("Invalid user admin from 10.0.0.4 port 5000")
        assert mask(once) == once
