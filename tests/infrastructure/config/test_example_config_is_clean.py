# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Guard: the example config shows ids only as obvious placeholders (BOB-116 D8b).

``config/bob.example.yaml`` is tracked in a PUBLIC repository and teaches by example, so
its id examples were once real-looking group ids. Every run of six or more digits in its
text — comments included, horizontal separators between digits removed (the scan the
tracked-VPS-config guard shares, :mod:`tests.support.id_like_numbers`), so
``-100 4372 9473 07`` is still one run — must be one of the placeholders
below; the one other long number allowed is the VALUE of ``runtime.log_max_bytes``. A new
example id that looks real is a finding, whatever key or comment it hides in.
"""

from __future__ import annotations

from tests.support.id_like_numbers import has_log_rotation_value, id_like_digit_runs
from tests.support.repository_root import repository_root

_EXAMPLE = repository_root() / "config" / "bob.example.yaml"

# Group ids that cannot be mistaken for real ones: the -100 prefix plus a counting run.
PLACEHOLDER_IDS = frozenset({"1001234567890", "1009876543210"})


def test_every_long_number_in_the_example_is_a_placeholder() -> None:
    findings = [
        f"line {run.line}: {run.digits}"
        for run in id_like_digit_runs(_EXAMPLE.read_text(encoding="utf-8"))
        if run.digits not in PLACEHOLDER_IDS
    ]

    assert findings == [], f"an id-like number that is not a placeholder: {findings}"


def test_the_example_still_shows_a_group_id_placeholder() -> None:
    # Without this the guard above would pass on a file that dropped the examples.
    assert "-1001234567890" in _EXAMPLE.read_text(encoding="utf-8")


def test_the_log_rotation_exemption_still_applies_to_its_value() -> None:
    assert has_log_rotation_value(_EXAMPLE.read_text(encoding="utf-8"))
