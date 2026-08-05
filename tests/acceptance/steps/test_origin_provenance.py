# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шаги сценариев «Боб помнит, ГДЕ это было» (BOB-090 Срез C, US-1).

Связывают ``origin_provenance.feature`` с
:mod:`tests.acceptance.origin_provenance_harness`: архив осаждается в настоящую SQLite,
пул собирает настоящий FTS5-recall, ход идёт через живой композиционный корень, а
утверждается наблюдаемое на границе с моделью — что Боб сказал о месте припомненного.
Сценарии синхронные (pytest-bdd), поэтому асинхронный ход гоняется через ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.origin_provenance_harness import (
    MIXED_ORIGINS,
    SAID_IN_ROOM,
    SAID_PRIVATELY,
    Memory,
    OriginOutcome,
    origin_lines,
    run_origin_pair,
    run_origin_turn,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/origin_provenance.feature")

# Вопрос владельца: лексически цепляет весь архив, поэтому место припомненного решает
# именно провенанс, а не то, что чего-то не нашлось.
_QUESTION = "Боб, что мы там обсуждали про переезд?"

_PRIVATELY_SAID = "Мы обсуждали переезд в новый офис, я тогда сомневался."
_SAID_IN_ROOM = "Мы обсуждали переезд всей командой при всех, спорили про сроки."

_PRIVATE_ARCHIVE = (Memory(_PRIVATELY_SAID, "owner_private"),)
_ROOM_ARCHIVE = (Memory(_SAID_IN_ROOM, "public"),)
_MIXED_ARCHIVE = _PRIVATE_ARCHIVE + _ROOM_ARCHIVE
# Легаси-строка: записана до того, как источник вообще появился. NULL — это «не знаю
# где», а не «сказано при всех».
_UNMARKED_ARCHIVE = (Memory("Мы обсуждали переезд, а когда — не помню.", None),)


@dataclass(slots=True)
class _OriginContext:
    """Слейт сценария: изолированный корень хранилища, архив, флаг и итоги хода."""

    tmp_path: Path
    archive: tuple[Memory, ...] = _PRIVATE_ARCHIVE
    provenance_enabled: bool = False
    outcome: OriginOutcome = field(default_factory=OriginOutcome)
    # S6: тот же ход при выключенном флаге — база для доказательства равенством.
    without_provenance: OriginOutcome = field(default_factory=OriginOutcome)


@pytest.fixture
def origin_context(tmp_path: Path) -> _OriginContext:
    """Свежая изолированная память на каждый сценарий."""
    return _OriginContext(tmp_path=tmp_path)


# --- Дано: архив и флаг ---------------------------------------------------------


@given("в памяти Боба лежит разговор, который был только наедине")
def archive_is_private(origin_context: _OriginContext) -> None:
    origin_context.archive = _PRIVATE_ARCHIVE


@given("в памяти Боба лежит разговор, который был при всех в общем чате")
def archive_is_public(origin_context: _OriginContext) -> None:
    origin_context.archive = _ROOM_ARCHIVE


@given("в памяти Боба лежит разговор, часть которого была наедине, а часть при всех")
def archive_is_mixed(origin_context: _OriginContext) -> None:
    origin_context.archive = _MIXED_ARCHIVE


@given("в памяти Боба лежит старый разговор без метки места")
def archive_is_unmarked(origin_context: _OriginContext) -> None:
    origin_context.archive = _UNMARKED_ARCHIVE


@given("флаг memory.origin_provenance включён")
def provenance_on(origin_context: _OriginContext) -> None:
    origin_context.provenance_enabled = True


# --- Когда: ход владельца -------------------------------------------------------


@when("владелец спрашивает Боба про этот разговор")
def owner_asks(origin_context: _OriginContext) -> None:
    origin_context.outcome = asyncio.run(
        run_origin_turn(
            origin_context.tmp_path,
            archive=origin_context.archive,
            question=_QUESTION,
            origin_provenance=origin_context.provenance_enabled,
        )
    )


@when("владелец задаёт один и тот же вопрос при выключенном и при включённом провенансе")
def owner_asks_both_ways(origin_context: _OriginContext) -> None:
    off, on = asyncio.run(
        run_origin_pair(
            origin_context.tmp_path,
            archive=origin_context.archive,
            question=_QUESTION,
        )
    )
    origin_context.without_provenance = off
    origin_context.outcome = on


# --- Тогда: что Боб знает о месте -----------------------------------------------


@then("Боб знает, что припомненное было сказано наедине")
def knows_it_was_private(origin_context: _OriginContext) -> None:
    outcome = origin_context.outcome
    assert outcome.claims(SAID_PRIVATELY), "место не названо: Боб снова его не видит"
    assert outcome.claims("в личке"), "Боб не может назвать место словами"
    assert not outcome.claims(SAID_IN_ROOM)


@then("Боб не приписывает эти слова общему чату")
def does_not_credit_the_room(origin_context: _OriginContext) -> None:
    # Ровно тот дефект, из-за которого заведён эпик (эпизод 3092).
    assert origin_context.outcome.claims("не приписывай эти слова общему чату")


@then("Боб знает, что припомненное было сказано при всех")
def knows_it_was_public(origin_context: _OriginContext) -> None:
    outcome = origin_context.outcome
    assert outcome.claims(SAID_IN_ROOM), "место не названо"
    assert not outcome.claims(SAID_PRIVATELY)


@then("Боб знает, что припомненное пришло из разных мест")
def knows_the_origins_are_mixed(origin_context: _OriginContext) -> None:
    outcome = origin_context.outcome
    assert outcome.claims(MIXED_ORIGINS), "смешанный источник не распознан"
    assert not outcome.claims(SAID_PRIVATELY)
    assert not outcome.claims(SAID_IN_ROOM)


@then("Бобу сказано не называть место наугад")
def warned_against_guessing(origin_context: _OriginContext) -> None:
    assert origin_context.outcome.claims("не называть место совсем, чем назвать его наугад")


@then("Боб не называет места вовсе")
def names_no_place(origin_context: _OriginContext) -> None:
    outcome = origin_context.outcome
    assert not outcome.names_a_place, (
        f"место названо там, где Боб его не знает: {origin_lines(outcome.prompt)!r}"
    )


@then("Боб припомнил и сказанное наедине, и сказанное при всех")
def recall_stays_cross_cutting(origin_context: _OriginContext) -> None:
    # 🔴 Источник — сигнал для суждения, а не фильтр: память остаётся сквозной (BOB-082).
    outcome = origin_context.outcome
    assert outcome.recalled(_PRIVATELY_SAID), "приватное вырезано — память засилосили"
    assert outcome.recalled(_SAID_IN_ROOM), "публичное не всплыло"


@then("при выключенном флаге Боб не называет места вовсе")
def off_names_no_place(origin_context: _OriginContext) -> None:
    outcome = origin_context.without_provenance
    assert not outcome.names_a_place, (
        f"выключенный флаг всё равно назвал место: {origin_lines(outcome.prompt)!r}"
    )


@then("ход с выключенным флагом совпадает с включённым строка в строку, кроме строки про место")
def off_path_is_identical_apart_from_the_origin_line(
    origin_context: _OriginContext,
) -> None:
    on_lines = origin_context.outcome.prompt.splitlines()
    off_lines = origin_context.without_provenance.prompt.splitlines()
    added = origin_lines(origin_context.outcome.prompt)

    assert len(added) == 1, f"провенанс добавил не одну строку: {added!r}"
    assert [line for line in on_lines if line not in added] == off_lines, (
        "включённый провенанс изменил ход не только строкой про место"
    )
