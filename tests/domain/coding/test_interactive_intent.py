# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure interactive-intake predicates (BOB-083 .4).

``parse_interactive_entry`` recognises the two DM entry commands that open a live
interactive terminal (``/code -i <task>`` / ``/interactive <task>``) and returns the
task; ``is_interactive_exit`` recognises a DELIBERATE, whole-message exit command
(``stop`` / ``стоп`` / ``/exit`` / ``/code stop``). Both are pure, deterministic, no I/O
— mutation targets. The exit predicate is deliberately NARROW (an exact whole-message
match) so a steer reply that merely mentions a stop-word («подожди, сделай иначе») is
forwarded to claude, never hijacked into an exit.
"""

from __future__ import annotations

import pytest

from bob.coding.interactive_intent import is_interactive_exit, parse_interactive_entry

# --- parse_interactive_entry -----------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/code -i fix the bug", "fix the bug"),
        ("/interactive fix the bug", "fix the bug"),
        ("  /code -i   trim me  ", "trim me"),
        ("/CODE -I Fix It", "Fix It"),  # command + flag case-insensitive, task verbatim
        ("/Interactive Do X", "Do X"),
    ],
)
def test_entry_command_parses_the_task(text: str, expected: str) -> None:
    assert parse_interactive_entry(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "hello there",
        "/code approve",  # a different /code sub-verb, not interactive entry
        "/code stop",
        "/code -i",  # no task → not a valid entry
        "/code -i    ",  # blank task → not a valid entry
        "/interactive",  # no task
        "just /code -i inline",  # the command must lead the message
        "",
    ],
)
def test_non_entry_text_returns_none(text: str) -> None:
    assert parse_interactive_entry(text) is None


# --- is_interactive_exit ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["stop", "STOP", "стоп", "Стоп", " /exit ", "/stop", "/code stop", "exit", "выход"],
)
def test_exit_command_is_recognised(text: str) -> None:
    assert is_interactive_exit(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "подожди, сделай иначе",  # a steer reply mentioning a stop-word → NOT an exit
        "stop the server please",  # a real steer instruction, not a bare exit
        "давай запусти тесты",
        "/code -i new task",
        "",
    ],
)
def test_non_exit_text_is_not_an_exit(text: str) -> None:
    assert is_interactive_exit(text) is False
