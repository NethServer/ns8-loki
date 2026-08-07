#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

import base64
import datetime
import json
import ssl
import sys
import types

import pytest


UTC = datetime.timezone.utc


class TestComputeWindow:
    """compute_window floors `now` to the previous window boundary.

    The systemd timer fires with a 2-minute randomised delay, so the window
    it asks for must be derived purely from wall-clock time, not from "the
    last N minutes" relative to whenever the timer happened to wake up.
    Otherwise two consecutive runs could double-count or skip a slice.
    """

    @pytest.mark.parametrize("now,expected_start,expected_end", [
        (datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)),
        (datetime.datetime(2026, 1, 1, 10, 7, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)),
        (datetime.datetime(2026, 1, 1, 10, 14, 59, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 9, 45, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)),
        (datetime.datetime(2026, 1, 1, 10, 15, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 15, 0, tzinfo=UTC)),
        (datetime.datetime(2026, 1, 1, 10, 44, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 15, 0, tzinfo=UTC),
         datetime.datetime(2026, 1, 1, 10, 30, 0, tzinfo=UTC)),
    ])
    def test_floors_to_the_previous_15_minute_boundary(
            self, collector, now, expected_start, expected_end):
        start, end = collector.compute_window(now)
        assert (start, end) == (expected_start, expected_end)

    def test_window_length_always_matches_the_requested_minutes(self, collector):
        for now in (
                datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC),
                datetime.datetime(2026, 1, 1, 10, 7, 0, tzinfo=UTC),
                datetime.datetime(2026, 1, 1, 10, 14, 59, tzinfo=UTC),
                datetime.datetime(2026, 1, 1, 10, 15, 0, tzinfo=UTC),
                datetime.datetime(2026, 1, 1, 10, 44, 0, tzinfo=UTC),
        ):
            for minutes in (5, 15, 60):
                start, end = collector.compute_window(now, minutes)
                assert end - start == datetime.timedelta(minutes=minutes)

    def test_non_default_window_size(self, collector):
        # A 5-minute window floors to a 5-minute boundary, not 15.
        # 10:07 -> minute 7 % 5 == 2, so end steps back to 10:05.
        now = datetime.datetime(2026, 1, 1, 10, 7, 0, tzinfo=UTC)
        start, end = collector.compute_window(now, 5)
        assert start == datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        assert end == datetime.datetime(2026, 1, 1, 10, 5, 0, tzinfo=UTC)


class TestMs:
    def test_converts_to_integer_unix_millis(self, collector):
        assert collector.ms(datetime.datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)) == 1000

    def test_truncates_sub_millisecond_precision(self, collector):
        when = datetime.datetime(1970, 1, 1, 0, 0, 0, 500000, tzinfo=UTC)
        assert collector.ms(when) == 500

    def test_result_is_an_int(self, collector):
        when = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
        assert isinstance(collector.ms(when), int)


class FakeResponse:
    def __init__(self, status=202, body=b'{"ok":true}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class TestShip:
    """ship() must produce a request an insights server can authenticate."""

    def _capture(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None, context=None):
            captured["request"] = request
            captured["timeout"] = timeout
            captured["context"] = context
            return FakeResponse()

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        return captured

    @pytest.mark.parametrize("base_url", ["https://x", "https://x/"])
    def test_url_has_exactly_one_bundles_path(self, collector, monkeypatch, base_url):
        captured = self._capture(monkeypatch)
        collector.ship({"a": 1}, base_url, "sys1", "secret1")
        assert captured["request"].full_url == "https://x/v1/bundles"

    def test_content_type_is_json(self, collector, monkeypatch):
        captured = self._capture(monkeypatch)
        collector.ship({"a": 1}, "https://x", "sys1", "secret1")
        assert captured["request"].get_header("Content-type") == "application/json"

    def test_authorization_is_basic_system_id_and_secret(self, collector, monkeypatch):
        captured = self._capture(monkeypatch)
        collector.ship({"a": 1}, "https://x", "sys1", "s3cr3t")
        header = captured["request"].get_header("Authorization")
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header[len("Basic "):]).decode()
        assert decoded == "sys1:s3cr3t"

    def test_body_round_trips_to_the_payload(self, collector, monkeypatch):
        captured = self._capture(monkeypatch)
        payload = {"schema_version": 1, "templates": [{"template": "x"}]}
        collector.ship(payload, "https://x", "sys1", "secret1")
        assert json.loads(captured["request"].data.decode()) == payload

    def test_verify_true_builds_a_verifying_context(self, collector, monkeypatch):
        captured = self._capture(monkeypatch)
        collector.ship({"a": 1}, "https://x", "sys1", "secret1", verify=True)
        ctx = captured["context"]
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_verify_false_builds_a_non_verifying_context(self, collector, monkeypatch):
        captured = self._capture(monkeypatch)
        collector.ship({"a": 1}, "https://x", "sys1", "secret1", verify=False)
        ctx = captured["context"]
        assert ctx.verify_mode == ssl.CERT_NONE

    def test_returns_status_and_decoded_body(self, collector, monkeypatch):
        def fake_urlopen(request, timeout=None, context=None):
            return FakeResponse(status=202, body=b'{"queued":true}')

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        status, text = collector.ship({"a": 1}, "https://x", "sys1", "secret1")
        assert status == 202
        assert text == '{"queued":true}'


class TestReadIdentity:
    """read_identity() reads the node's own subscription, never module state.

    The `agent` SDK is only ever imported inside the function, so it can be
    replaced with a fake module for these tests without the real SDK being
    installed in the unit-test container.
    """

    @pytest.fixture
    def fake_agent(self):
        previous = sys.modules.get("agent")

        def install(hash_data):
            stub = types.SimpleNamespace(hgetall=lambda key: dict(hash_data))
            module = types.ModuleType("agent")
            module.redis_connect = lambda: stub
            sys.modules["agent"] = module
            return module

        yield install

        if previous is not None:
            sys.modules["agent"] = previous
        else:
            sys.modules.pop("agent", None)

    def test_full_hash_returns_system_id_and_first_secret_field(self, collector, fake_agent):
        fake_agent({"system_id": "sys1", "auth_token": "tok1",
                    "secret": "sec1", "password": "pw1"})
        assert collector.read_identity() == ("sys1", "tok1")

    @pytest.mark.parametrize("field", ["auth_token", "secret", "password"])
    def test_each_secret_field_is_used_when_it_is_the_only_one_present(
            self, collector, fake_agent, field):
        fake_agent({"system_id": "sys1", field: "value-for-" + field})
        assert collector.read_identity() == ("sys1", "value-for-" + field)

    def test_secret_fields_are_tried_in_declared_order(self, collector, fake_agent):
        assert list(collector.SUBSCRIPTION_SECRET_FIELDS) == \
            ["auth_token", "secret", "password"]
        fake_agent({"system_id": "sys1", "secret": "sec1", "password": "pw1"})
        assert collector.read_identity() == ("sys1", "sec1")

    def test_empty_hash_yields_none_none(self, collector, fake_agent):
        fake_agent({})
        assert collector.read_identity() == (None, None)

    def test_missing_id_field_yields_none_none(self, collector, fake_agent):
        fake_agent({"auth_token": "tok1"})
        assert collector.read_identity() == (None, None)

    def test_missing_secret_yields_none_none(self, collector, fake_agent):
        fake_agent({"system_id": "sys1"})
        assert collector.read_identity() == (None, None)

    def test_bytes_values_are_decoded_to_str(self, collector, fake_agent):
        fake_agent({b"system_id": b"sys1", b"auth_token": b"tok1"})
        result = collector.read_identity()
        assert result == ("sys1", "tok1")
        assert all(isinstance(part, str) for part in result)

    def test_failure_message_lists_field_names_but_never_values(
            self, collector, fake_agent, capsys):
        fake_agent({"password": "top-secret-value"})
        result = collector.read_identity()
        assert result == (None, None)
        err = capsys.readouterr().err
        assert "password" in err
        assert "top-secret-value" not in err


class TestVerifyTlsParsing:
    """INSIGHTS_VERIFY_TLS fails safe: anything unrecognised means verify.

    There is no dedicated helper for this, so it is exercised through
    main() with ship() and collect() monkeypatched to avoid any I/O.
    """

    @pytest.fixture
    def run_main(self, collector, monkeypatch):
        monkeypatch.setenv("LOKI_HTTP_PORT", "3100")
        monkeypatch.setenv("LOKI_API_AUTH_USERNAME", "u")
        monkeypatch.setenv("LOKI_API_AUTH_PASSWORD", "p")
        monkeypatch.setenv("INSIGHTS_SERVER_URL", "https://insights.example/")
        monkeypatch.setattr(collector, "read_identity", lambda: ("sys1", "secret1"))
        monkeypatch.setattr(collector, "collect",
                            lambda *a, **k: {"schema_version": 1, "templates": [],
                                             "budget": {"lines_kept": 0}})
        captured = {}

        def fake_ship(payload, url, system_id, secret, verify=True, timeout=60):
            captured["verify"] = verify
            return 202, "ok"

        monkeypatch.setattr(collector, "ship", fake_ship)

        def call():
            rc = collector.main([])
            return rc, captured.get("verify")

        return call

    @pytest.mark.parametrize("value", ["0", "false", "False", "  false  ",
                                       "NO", "no", "off", "OFF"])
    def test_false_spellings_disable_verification(self, monkeypatch, run_main, value):
        monkeypatch.setenv("INSIGHTS_VERIFY_TLS", value)
        rc, verify = run_main()
        assert rc == 0
        assert verify is False

    @pytest.mark.parametrize("value", ["", "1", "true", "True", "yes", "maybe", "garbage"])
    def test_everything_else_verifies(self, monkeypatch, run_main, value):
        monkeypatch.setenv("INSIGHTS_VERIFY_TLS", value)
        rc, verify = run_main()
        assert rc == 0
        assert verify is True

    def test_unset_verifies(self, monkeypatch, run_main):
        # Fail-safe direction: an operator who forgets to set this variable
        # gets certificate verification, not a silently-open channel.
        monkeypatch.delenv("INSIGHTS_VERIFY_TLS", raising=False)
        rc, verify = run_main()
        assert rc == 0
        assert verify is True


class TestMainFailurePaths:
    def _set_loki_env(self, monkeypatch):
        monkeypatch.setenv("LOKI_HTTP_PORT", "3100")
        monkeypatch.setenv("LOKI_API_AUTH_USERNAME", "u")
        monkeypatch.setenv("LOKI_API_AUTH_PASSWORD", "p")

    def test_fails_when_server_url_is_unset(self, collector, monkeypatch):
        self._set_loki_env(monkeypatch)
        monkeypatch.delenv("INSIGHTS_SERVER_URL", raising=False)
        monkeypatch.setattr(collector, "read_identity", lambda: ("sys1", "secret1"))
        monkeypatch.setattr(collector, "collect",
                            lambda *a, **k: {"templates": [], "budget": {"lines_kept": 0}})
        assert collector.main([]) == 1

    def test_fails_when_identity_is_missing(self, collector, monkeypatch):
        self._set_loki_env(monkeypatch)
        monkeypatch.setenv("INSIGHTS_SERVER_URL", "https://insights.example/")
        monkeypatch.setattr(collector, "read_identity", lambda: (None, None))
        assert collector.main([]) == 1

    def test_ship_timeout_fails_cleanly(self, collector, monkeypatch, capsys):
        # urllib only wraps send-phase failures as URLError; a timeout while
        # waiting for the response on an already-open connection surfaces as
        # a bare TimeoutError, which main() must not let escape as a
        # traceback.
        self._set_loki_env(monkeypatch)
        monkeypatch.setenv("INSIGHTS_SERVER_URL", "https://insights.example/")
        monkeypatch.setattr(collector, "read_identity", lambda: ("sys1", "secret1"))
        monkeypatch.setattr(collector, "collect",
                            lambda *a, **k: {"templates": [], "budget": {"lines_kept": 0}})

        def fake_ship(*a, **k):
            raise TimeoutError("timed out")

        monkeypatch.setattr(collector, "ship", fake_ship)

        assert collector.main([]) == 1
        assert "timed out" in capsys.readouterr().err

    def test_print_succeeds_with_neither_subscription_nor_server_url(
            self, collector, monkeypatch, capsys):
        # --print is the documented zero-cost inspection path: it must work
        # on a node that has no insights server configured at all yet.
        self._set_loki_env(monkeypatch)
        monkeypatch.delenv("INSIGHTS_SERVER_URL", raising=False)
        payload = {"schema_version": 1, "templates": [],
                  "budget": {"max_lines": 500, "lines_seen": 0, "lines_kept": 0}}
        monkeypatch.setattr(collector, "collect", lambda *a, **k: payload)

        def fail_if_called():
            raise AssertionError("read_identity should not be needed for --print")

        monkeypatch.setattr(collector, "read_identity", fail_if_called)

        assert collector.main(["--print"]) == 0
        assert json.loads(capsys.readouterr().out) == payload
