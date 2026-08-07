#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Normalise volatile tokens in a log line so repeats collapse to one template.

This runs *after* `scrub()` and does a different job. `scrub()` removes
secrets and deliberately preserves IP addresses, hostnames and module IDs
because they carry signal. Masking replaces exactly those volatile parts,
because two lines that differ only by a PID or an address are the same event
and must group together.

Both outputs are kept downstream: the template (masked) is what gets counted
and hashed into a finding's identity, while the retained sample line is the
scrubbed-but-unmasked original, so an operator can still see which address
was actually refused.

Rule order is load-bearing and is documented per rule below.
"""

import re

# Bumped by hand whenever MASKING_RULES changes. A change alters every
# template's text, so it invalidates every server-side template and
# fingerprint at once. Travelling in the bundle makes the resulting one-time
# duplicate burst explainable instead of mysterious.
MASKING_VERSION = 1

# Placeholders already present in the input are left alone, which is what
# makes mask() idempotent. Listed here so one rule can protect all of them.
_PLACEHOLDER = r'<(?:TS|PID|UUID|IP|PORT|HEX|NUM|PATH|USER|redacted[a-z-]*)>'

MASKING_RULES = [
    # 1. Volatile paths. Before any number rule, or /proc/12345 loses its
    #    shape and stops matching as a path at all.
    (
        re.compile(r'(?:/tmp|/run|/var/tmp)/\S+'),
        '<PATH>',
    ),
    (
        re.compile(r'/proc/\d+(?:/\S*)?'),
        '<PATH>',
    ),
    # 2. ISO-8601 timestamps. Before clock times, which are a prefix of them.
    (
        re.compile(
            r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}'
            r'(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'
        ),
        '<TS>',
    ),
    # 3. Bare clock times. Before the port rule, which would otherwise claim
    #    the ":32" tail, and before IPv6, which also uses colons.
    (
        re.compile(r'\b\d{2}:\d{2}:\d{2}(?:\.\d+)?\b'),
        '<TS>',
    ),
    # 4. UUIDs. Must precede the hex rule, which would otherwise shred a UUID
    #    into <HEX>-<HEX>-... and produce a template that never groups.
    (
        re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}'
                   r'-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b'),
        '<UUID>',
    ),
    # 5. IPv6. Must precede the hex rule for the same reason as UUIDs, and
    #    precede IPv4 so an IPv4-mapped form is taken whole. The compressed
    #    "::" form may be followed by several more groups, so the tail is a
    #    repeating group rather than a single optional one.
    (
        re.compile(r'(?<![\w:.])(?:'
                   r'(?:[0-9a-fA-F]{1,4}:){1,7}:'
                   r'(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?'
                   r'|(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}'
                   r'|::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4})*)?'
                   r')(?![\w:.])'),
        '<IP>',
    ),
    # 6. IPv4, with an optional port taken in the same match.
    #
    #    The port cannot be a separate rule with a (?<=<IP>) lookbehind: by
    #    the time that rule ran, <IP> would be a protected placeholder and
    #    excluded from the text the rule is applied to, so the lookbehind
    #    could never match. Consuming the port here also keeps the port from
    #    reaching the bare-number rule.
    (
        re.compile(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?::(\d{1,5}))?(?![\w.])'),
        lambda m: '<IP>:<PORT>' if m.group(1) else '<IP>',
    ),
    # 7. PIDs in their three common shapes. Before the bare-number rule.
    (
        re.compile(r'\[\d+\]'),
        '[<PID>]',
    ),
    (
        re.compile(r'(?i)\b(pid)\b([=: ]+)\d+'),
        r'\1\2<PID>',
    ),
    (
        re.compile(r'\((\d{2,})\)'),
        '(<PID>)',
    ),
    # 9. Hex runs. After UUID and IPv6. Eight is the shortest run that is
    #    more often a checksum than a word: "cafe" and "deadbeef" both exist
    #    in prose, but eight-plus hex characters rarely do.
    (
        re.compile(r'\b(?=[0-9a-fA-F]*\d)[0-9a-fA-F]{8,}\b'),
        '<HEX>',
    ),
    # 10. Account names in authentication messages.
    #
    #     Measured against six hours of real cluster logs: an SSH dictionary
    #     attack produced 319 distinct templates that differed only by the
    #     account being tried. Left unmasked, every window of an ongoing
    #     attack looks like hundreds of brand-new templates, which opens the
    #     server's novelty gate forever and defeats the cost control it
    #     exists to provide. The retained sample line still carries the
    #     actual account name, and the count carries the volume.
    (
        re.compile(r'(?i)\b(user)\s+(?!<)[^\s]+'),
        r'\1 <USER>',
    ),
    # 11. Bare integers, last of all: every rule above embeds digits, and
    #     running this earlier would dismantle them. Two digits minimum, so
    #     priority markers like <3> and names like traefik1 survive.
    (
        re.compile(r'(?<![\w<])\d{2,}(?![\w>])'),
        '<NUM>',
    ),
]

# One pass that alternates "an existing placeholder" against "the next rule".
# Matching placeholders first and re-emitting them unchanged is what stops a
# second mask() call from rewriting <PID> into <[<PID>]> or <NUM> into <<NUM>>.
_PROTECTED = re.compile(_PLACEHOLDER)


def mask(line):
    """Return the template form of one already-scrubbed log line."""
    for pattern, replacement in MASKING_RULES:
        line = _apply(pattern, replacement, line)
    return line


def _apply(pattern, replacement, line):
    """Apply one rule to the parts of `line` that are not already placeholders."""
    out = []
    position = 0
    for protected in _PROTECTED.finditer(line):
        out.append(pattern.sub(replacement, line[position:protected.start()]))
        out.append(protected.group(0))
        position = protected.end()
    out.append(pattern.sub(replacement, line[position:]))
    return "".join(out)
