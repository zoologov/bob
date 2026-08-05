# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the digest provenance format — bob-g7t.

A consolidation digest stamps the ts-range of its sources («откуда я это помню»). The
format used to be written in one module and re-read nowhere; the privacy repair reads it
back, so writer and reader now share ONE definition. Covered here: the round trip, and
every shape that must be REFUSED rather than half-parsed — because an unparseable
provenance is what makes the repair fall back to the strict label.
"""

from __future__ import annotations

import pytest

from bob.memory.digest_provenance import parse_provenance_window, provenance_window

_FIRST = "2026-06-19T06:34:46.759504+00:00"
_LAST = "2026-06-25T05:35:19.933810+00:00"


def test_a_written_window_reads_back_unchanged() -> None:
    """The round trip: what consolidation stamps is exactly what the repair resolves."""
    assert parse_provenance_window(provenance_window(_FIRST, _LAST)) == (_FIRST, _LAST)


def test_the_written_form_is_the_one_already_on_disk() -> None:
    """21 live digests carry ``<first>..<last>`` — the format is HISTORY, not a choice."""
    assert provenance_window(_FIRST, _LAST) == f"{_FIRST}..{_LAST}"


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "не-провенанс",
        f"{_FIRST}",
        f"..{_LAST}",
        f"{_FIRST}..",
        f"{_FIRST}..{_LAST}..{_LAST}",
    ],
)
def test_an_unresolvable_provenance_is_refused(value: str | None) -> None:
    """Half-parsing would fabricate a window and, with it, a WRONG privacy verdict."""
    assert parse_provenance_window(value) is None


def test_surrounding_whitespace_does_not_break_the_window() -> None:
    """A stored value is compared against ``ts`` strings, so the ends must be clean."""
    assert parse_provenance_window(f"  {_FIRST}..{_LAST}  ") == (_FIRST, _LAST)
