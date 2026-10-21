# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Guard: the example config shows ids only as obvious placeholders (BOB-116 D8b).

``config/bob.example.yaml`` is tracked in a PUBLIC repository and teaches by example, so
its id examples were once real-looking group ids. Every run of six or more digits in its
text — comments included, ``_`` and single-space separators between digits removed, so
``-100 4372 9473 07`` is still one run — must be one of the placeholders
below; the one other long number allowed is the VALUE of ``runtime.log_max_bytes``. A new
example id that looks real is a finding, whatever key or comment it hides in.
"""

from __future__ import annotations

import re
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parents[3] / "config" / "bob.example.yaml"

# Group ids that cannot be mistaken for real ones: the -100 prefix plus a counting run.
PLACEHOLDER_IDS = frozenset({"1001234567890", "1009876543210"})

_ID_LIKE_DIGIT_RUN = re.compile(r"\d{6,}")
_DIGIT_SEPARATOR = re.compile(r"(?<=\d)[_ ](?=\d)")
_LOG_MAX_BYTES_VALUE = re.compile(r"^(\s*log_max_bytes:\s*)\d+", re.MULTILINE)


def _scanned_text() -> str:
    text = _DIGIT_SEPARATOR.sub("", _EXAMPLE.read_text(encoding="utf-8"))
    return _LOG_MAX_BYTES_VALUE.sub(r"\1", text)


def test_every_long_number_in_the_example_is_a_placeholder() -> None:
    findings = [
        f"line {number}: {run}"
        for number, line in enumerate(_scanned_text().splitlines(), start=1)
        for run in _ID_LIKE_DIGIT_RUN.findall(line)
        if run not in PLACEHOLDER_IDS
    ]

    assert findings == [], f"an id-like number that is not a placeholder: {findings}"


def test_the_example_still_shows_a_group_id_placeholder() -> None:
    # Without this the guard above would pass on a file that dropped the examples.
    assert "-1001234567890" in _EXAMPLE.read_text(encoding="utf-8")


def test_the_log_rotation_exemption_still_applies_to_its_value() -> None:
    assert _LOG_MAX_BYTES_VALUE.search(_EXAMPLE.read_text(encoding="utf-8")) is not None
