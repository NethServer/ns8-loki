#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#

from insights import bundle


def line(ts, text, category=""):
    return (ts, text, category)


class TestGroupTemplates:
    def test_repeats_collapse_to_one_counted_template(self):
        lines = [line(i, "smbd[%d] connection refused to 10.0.0.%d:8080" % (i, i))
                 for i in range(1, 38)]
        templates, kept, fetched = bundle.group_templates(lines, "samba2", 20)
        assert len(templates) == 1
        assert templates[0]["count"] == 37
        assert kept == 37
        assert fetched == 37

    def test_the_share_caps_distinct_templates_not_lines(self):
        # 100 distinct events, budget of 5: five templates survive, and they
        # are the five most frequent rather than the five earliest.
        #
        # Names are letter pairs on purpose. Digits would mask to <NUM> and
        # merge, and chr() walks into Unicode whitespace such as NEL and
        # NBSP, which sanitize_line correctly collapses.
        alphabet = "abcdefghij"
        lines = []
        for i in range(100):
            name = alphabet[i // 10] + alphabet[i % 10]
            lines.extend([line(i, "event kind %s happened" % name)] * (i + 1))
        templates, _kept, _fetched = bundle.group_templates(lines, "m", 5)
        assert len(templates) == 5
        counts = [t["count"] for t in templates]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] == 100

    def test_samples_keep_first_and_last_only(self):
        lines = [line(i, "smbd[%d] refused 10.0.0.4:80" % i) for i in range(10)]
        templates, _k, _f = bundle.group_templates(lines, "m", 20)
        samples = templates[0]["samples"]
        assert len(samples) == 2
        assert "smbd[0]" in samples[0]
        assert "smbd[9]" in samples[1]

    def test_samples_are_scrubbed_but_not_masked(self):
        lines = [line(1, "refused 10.0.0.4:8080 password=hunter2")]
        templates, _k, _f = bundle.group_templates(lines, "m", 20)
        sample = templates[0]["samples"][0]
        assert "password=<redacted>" in sample, "secrets must be removed"
        assert "10.0.0.4" in sample, "detail must survive in the sample"
        assert "<IP>" in templates[0]["template"], "the template must be masked"

    def test_priority_is_parsed_from_the_rendered_line(self):
        templates, _k, _f = bundle.group_templates(
            [line(1, "<3> [traefik] backend down")], "traefik1", 20)
        assert templates[0]["priority"] == 3

    def test_category_is_carried_through(self):
        templates, _k, _f = bundle.group_templates(
            [line(1, "<6> [sshd] Invalid user bob", "security")], "", 20)
        assert templates[0]["category"] == "security"

    def test_absent_category_is_omitted_entirely(self):
        templates, _k, _f = bundle.group_templates(
            [line(1, "<6> [systemd] Started thing")], "m", 20)
        assert "category" not in templates[0]

    def test_same_text_in_different_categories_stays_separate(self):
        templates, _k, _f = bundle.group_templates(
            [line(1, "<6> [x] same text"), line(2, "<6> [x] same text", "security")],
            "m", 20)
        assert len(templates) == 2

    def test_first_and_last_seen_span_the_group(self):
        lines = [line(500, "<6> [x] a"), line(100, "<6> [x] a"), line(900, "<6> [x] a")]
        templates, _k, _f = bundle.group_templates(lines, "m", 20)
        assert templates[0]["first_seen"] == 100
        assert templates[0]["last_seen"] == 900

    def test_empty_input(self):
        templates, kept, fetched = bundle.group_templates([], "m", 20)
        assert templates == [] and kept == 0 and fetched == 0


class TestSampleEnds:
    def test_keeps_both_ends_of_the_window(self):
        # An early burst must not hide a late-developing incident.
        forward = [line(i, "early %d" % i) for i in range(10)]
        backward = [line(100 + i, "late %d" % i) for i in range(10)]
        merged = bundle.sample_ends(forward, backward, 6)
        texts = [row[1] for row in merged]
        assert any(t.startswith("early") for t in texts)
        assert any(t.startswith("late") for t in texts)
        assert len(merged) == 6

    def test_deduplicates_the_overlap(self):
        shared = [line(5, "same")]
        merged = bundle.sample_ends(shared, shared, 10)
        assert len(merged) == 1

    def test_returns_everything_when_under_the_limit(self):
        forward = [line(1, "a"), line(2, "b")]
        assert len(bundle.sample_ends(forward, [], 10)) == 2


class TestBuild:
    def test_payload_shape(self):
        payload = bundle.build("sys1", "2.0.0", (1000, 1900), [], [], {"max_lines": 500})
        assert payload["schema_version"] == bundle.SCHEMA_VERSION
        assert payload["system_id"] == "sys1"
        assert payload["window"] == {"start": 1000, "end": 1900}
        assert isinstance(payload["masking_version"], int)
