#
# Copyright (C) 2026 Nethesis S.r.l.
# SPDX-License-Identifier: GPL-3.0-or-later
#
"""Secret removal for collected log lines.

Distinct from masking: this removes secrets and deliberately PRESERVES IP
addresses, hostnames and module IDs because they carry signal. mask() then
replaces those for grouping. Both outputs are kept downstream.
"""

import re



# Ordered: keyword assignments (Bearer's space-separated value first, then
# other secret keywords requiring an explicit assignment character), then
# Authorization headers, then email addresses, then long opaque blobs. Email
# runs before the blob rule so a long local part is still reported as an
# email. Both keyword rules allow optional whitespace around the separator
# (aligned/structured logs commonly pad it, e.g. "key : value") without
# reopening the bare-whitespace false positive: the character class still
# requires an actual "=", ":" or quote, which plain prose never supplies.
SCRUB_RULES = [
    (
        re.compile(r'(?i)\b(bearer)\b\s*[=:\s"\']+\s*\S+'),
        r'\1=<redacted>',
    ),
    (
        re.compile(r'(?i)\b(tokens?|api[-_]?keys?|secrets?|passwords?|passwd|pwd)\b\s*[=:"\']+\s*\S+'),
        r'\1=<redacted>',
    ),
    (
        re.compile(r'(?i)\bauthorization:\s*\S+(?:\s+\S+)?'),
        'authorization: <redacted>',
    ),
    # The negative lookahead keeps systemd templated unit names intact.
    # `agent@nethvoice2.service` is not an address, and those PRIORITY=3 lines
    # are how a crash loop names the module that is failing.
    (
        re.compile(
            r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*'
            r'\.(?!service\b|timer\b|socket\b|target\b|slice\b|scope\b|mount\b'
            r'|path\b|device\b|swap\b|automount\b)[A-Za-z]{2,}\b'
        ),
        '<redacted-email>',
    ),
    # `/` is deliberately excluded: a long filesystem path or URL is signal,
    # not an opaque blob, and the base64 alphabet would otherwise swallow it.
    (
        re.compile(r'\b[A-Za-z0-9+]{32,}={0,2}\b'),
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
