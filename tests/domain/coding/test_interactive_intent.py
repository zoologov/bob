# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure interactive-intake predicates (BOB-083 .4 + BOB-087.D3).

``parse_interactive_entry`` recognises the two DM entry commands that open a live
interactive terminal (``/code -i <task>`` / ``/interactive <task>``) and returns the
task; ``is_interactive_exit`` recognises a DELIBERATE, whole-message exit command
(``stop`` / ``стоп`` / ``/exit`` / ``/code stop``). Both are pure, deterministic, no I/O
— mutation targets. The exit predicate is deliberately NARROW (an exact whole-message
match) so a steer reply that merely mentions a stop-word («подожди, сделай иначе») is
forwarded to claude, never hijacked into an exit.

BOB-087.D3 adds the resume trio, equally pure: ``parse_interactive_resume`` (ONLY the
explicit leading slash-command ``/code -r <workspace>`` / ``/resume <workspace>`` — free
natural language is DELIBERATELY not recognised, the BOB-076 runaway lesson) plus
``is_confirmation`` / ``is_rejection`` (exact whole-message match, so any OTHER reply is
never mistaken for a «да» that raises a session).
"""

from __future__ import annotations

import pytest

from bob.coding.interactive_intent import (
    is_confirmation,
    is_interactive_exit,
    is_rejection,
    parse_interactive_entry,
    parse_interactive_resume,
)

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


# --- parse_interactive_resume (BOB-087.D3) ---------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/code -r epic-bob-087", "epic-bob-087"),
        ("/resume epic-bob-087", "epic-bob-087"),
        ("  /code -r   epic bob 087  ", "epic bob 087"),  # trimmed, name verbatim
        ("/CODE -R Epic-Bob", "Epic-Bob"),  # command + flag case-insensitive
        ("/Resume Epic-Bob", "Epic-Bob"),
    ],
)
def test_resume_command_parses_the_workspace(text: str, expected: str) -> None:
    assert parse_interactive_resume(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # 🔴 BOB-076: free natural language NEVER resumes — a powerful action needs an
        # explicit command, because a cheap classifier once launched a runaway coder.
        "продолжи нашу сессию по эпику",
        "давай продолжим epic-bob-087",
        "подними сессию",
        "resume epic-bob-087",  # no leading slash → not a command
        "/code -i epic-bob-087",  # the interactive ENTRY command, not resume
        "/code -r",  # no workspace → not a valid resume
        "/code -r    ",  # blank workspace
        "/resume",
        "just /resume inline",  # the command must LEAD the message
        "",
    ],
)
def test_non_resume_text_returns_none(text: str) -> None:
    assert parse_interactive_resume(text) is None


def test_resume_and_entry_commands_do_not_overlap() -> None:
    # The two verbs stay disjoint: an entry command is never read as a resume and
    # vice versa (otherwise `/code -i` could silently raise an old session).
    assert parse_interactive_entry("/code -r epic-bob-087") is None
    assert parse_interactive_resume("/code -i почини баг") is None


# --- is_confirmation / is_rejection (BOB-087.D3) ---------------------------------


@pytest.mark.parametrize(
    "text",
    ["да", "Да", " ДА ", "ага", "yes", "Y", "ок", "окей", "ok", "давай", "/confirm"],
)
def test_confirmation_is_recognised(text: str) -> None:
    assert is_confirmation(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "да, но сначала покажи дифф",  # 🔴 not a bare yes → must NOT raise a session
        "давай посмотрим что там",
        "ok the tests are green",
        "",
        "нет",
        "/resume epic-bob-087",
    ],
)
def test_non_confirmation_text_is_not_a_confirmation(text: str) -> None:
    assert is_confirmation(text) is False


@pytest.mark.parametrize(
    "text",
    ["нет", "Нет", " НЕТ ", "no", "N", "отмена", "cancel", "/cancel"],
)
def test_rejection_is_recognised(text: str) -> None:
    assert is_rejection(text) is True


@pytest.mark.parametrize(
    "text",
    ["нет, давай позже разберёмся", "no way", "", "да", "отмена рейса"],
)
def test_non_rejection_text_is_not_a_rejection(text: str) -> None:
    assert is_rejection(text) is False


def test_confirmation_and_rejection_are_disjoint() -> None:
    # No message may be both — the resolver's yes/no branches must never race.
    for text in ("да", "ага", "yes", "y", "ок", "окей", "ok", "давай", "/confirm"):
        assert is_rejection(text) is False
    for text in ("нет", "no", "n", "отмена", "cancel", "/cancel"):
        assert is_confirmation(text) is False
