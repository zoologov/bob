# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the roster-recall scenarios (BOB-080).

Binds ``roster_recall.feature`` to :mod:`tests.acceptance.roster_recall_harness`, which
seeds recent joiners into a REAL SQLite first-impression store, recalls the roster via the
REAL :class:`~bob.social.usecases.roster_recall.RosterRecall` (ambient window + privacy),
and folds the REAL :func:`~bob.personality.voice.roster_directive`. The scenarios assert
Bob's OBSERVABLE recall — which people the roster line names, whom he holds as a fresh
newcomer, and whether any line is folded — through that composed-directive boundary, never
the store/use-case internals. INV-2 is witnessed by proving the named people are absent
from the incoming text (the recall is ambient, not lexical).

The scenarios are synchronous (pytest-bdd), so the async recall path runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.roster_recall_harness import (
    Joiner,
    RosterOutcome,
    compose_roster_line,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/roster_recall.feature")


@dataclass(slots=True)
class _RosterContext:
    """The slate the steps share: isolated store root, joiners, viewer, the outcome."""

    tmp_path: Path
    joined: list[Joiner] = field(default_factory=list)
    viewer: str = "owner"
    incoming_text: str = ""
    outcome: RosterOutcome = field(default_factory=RosterOutcome)


@pytest.fixture
def roster_context(tmp_path: Path) -> _RosterContext:
    """A fresh, isolated SQLite store per scenario."""
    return _RosterContext(tmp_path=tmp_path)


# --- Given: who is in the room's history + who is asking ------------------------


@given("в чат недавно зашли Лиля (2 дня назад) и Паша (1 день назад)")
def recent_lilya_and_pasha(roster_context: _RosterContext) -> None:
    roster_context.joined += [
        Joiner(sender_id=50, name="Лиля", days_ago=2.0),
        Joiner(sender_id=60, name="Паша", days_ago=1.0),
    ]


@given("в чат недавно зашла Лиля (2 дня назад)")
def recent_lilya(roster_context: _RosterContext) -> None:
    roster_context.joined.append(Joiner(sender_id=50, name="Лиля", days_ago=2.0))


@given("давно знакомы Norman (40 дней назад) и Алексей (90 дней назад)")
def old_timers(roster_context: _RosterContext) -> None:
    roster_context.joined += [
        Joiner(sender_id=70, name="Norman", days_ago=40.0),
        Joiner(sender_id=80, name="Алексей", days_ago=90.0),
    ]


@given(
    "в чат давно никто не заходил: только Norman (40 дней назад) "
    "и Алексей (90 дней назад)"
)
def only_old_timers(roster_context: _RosterContext) -> None:
    roster_context.joined += [
        Joiner(sender_id=70, name="Norman", days_ago=40.0),
        Joiner(sender_id=80, name="Алексей", days_ago=90.0),
    ]


@given("в чат вообще никто не заходил")
def nobody_joined(roster_context: _RosterContext) -> None:
    assert roster_context.joined == []


@given("спрашивает владелец")
def viewer_is_owner(roster_context: _RosterContext) -> None:
    roster_context.viewer = "owner"


@given("спрашивает гость")
def viewer_is_guest(roster_context: _RosterContext) -> None:
    roster_context.viewer = "guest"


# --- When: the open social question (names deliberately absent) ------------------


@when(
    parsers.re(
        r"(?:владелец|гость) открыто спрашивает «(?P<text>[^»]+)» \(имён не называя\)"
    )
)
def someone_asks_openly(roster_context: _RosterContext, text: str) -> None:
    roster_context.incoming_text = text
    roster_context.outcome = asyncio.run(
        compose_roster_line(
            roster_context.tmp_path,
            joined=roster_context.joined,
            viewer=roster_context.viewer,
            incoming_text=text,
        )
    )


# --- Then: Bob's observable recall at the directive boundary ---------------------


@then("строка ростера присутствует и называет и Лилю, и Пашу")
def roster_line_names_both(roster_context: _RosterContext) -> None:
    outcome = roster_context.outcome
    assert outcome.present, "строка ростера не свёрнута, хотя есть свежие"
    assert "Лиля" in outcome.directive, f"Лиля не названа: {outcome.directive!r}"
    assert "Паша" in outcome.directive, f"Паша не названа: {outcome.directive!r}"


@then("этих имён не было во входящем сообщении — ростер поднялся по составу, не по словам")
def names_absent_from_incoming(roster_context: _RosterContext) -> None:
    # INV-2: the recall is ambient, not a lexical FTS match on the message text.
    text = roster_context.incoming_text
    assert "Лиля" not in text, f"имя во входящем тексте, INV-2 не проверяется: {text!r}"
    assert "Паша" not in text, f"имя во входящем тексте, INV-2 не проверяется: {text!r}"
    assert {"Лиля", "Паша"}.issubset(set(roster_context.outcome.named))


@then("Боб держит новичком только Лилю, а Norman и Алексея — как старожилов")
def only_lilya_is_a_newcomer(roster_context: _RosterContext) -> None:
    outcome = roster_context.outcome
    newcomers = set(outcome.newcomers)
    assert "Лиля" in newcomers, f"Лиля не отмечена новичком: {newcomers}"
    assert "Norman" not in newcomers, "Norman ошибочно отмечен новичком (старожил)"
    assert "Алексей" not in newcomers, "Алексей ошибочно отмечен новичком (старожил)"
    # BOB-080.6 honesty: the OBSERVABLE «недавно зашли» line names only the fresh
    # newcomer — старожилов НЕ подаёт как только что зашедших (иначе Боб их так и
    # отрапортует в промпте).
    assert "Лиля" in outcome.directive, f"Лиля не названа: {outcome.directive!r}"
    assert "Norman" not in outcome.directive, (
        f"старожил Norman подан как «недавно зашёл»: {outcome.directive!r}"
    )
    assert "Алексей" not in outcome.directive, (
        f"старожил Алексей подан как «недавно зашёл»: {outcome.directive!r}"
    )


@then("владельца в ростере нет, а Лиля названа в строке")
def owner_excluded_recent_named(roster_context: _RosterContext) -> None:
    outcome = roster_context.outcome
    assert "Владимир" not in outcome.named, "владелец просочился в ростер"
    assert "Лиля" in outcome.directive, f"Лиля не названа: {outcome.directive!r}"


@then("строки ростера нет — выдумывать некого")
def no_roster_line(roster_context: _RosterContext) -> None:
    outcome = roster_context.outcome
    assert outcome.present is False, f"ростер всплыл без свежих: {outcome.named}"
    assert outcome.directive == "", f"строка не пуста: {outcome.directive!r}"


@then("строки ростера нет — гостю состав комнаты не вручают")
def no_roster_line_for_guest(roster_context: _RosterContext) -> None:
    outcome = roster_context.outcome
    assert outcome.present is False, f"гостю выдали состав: {outcome.named}"
    assert outcome.directive == ""
