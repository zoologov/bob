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
    MARK_IN_ROOM,
    MARK_PRIVATELY,
    MIXED_ORIGINS,
    SAID_IN_ROOM,
    SAID_PRIVATELY,
    Memory,
    OriginOutcome,
    marked_thread_lines,
    origin_lines,
    run_origin_pair,
    run_origin_turn,
    without_places,
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

# --- Недавняя НИТЬ (C3) ---------------------------------------------------------
# Ровно та сцена, на которой дефект вернулся живьём 2026-08-05: разговор шёл в личке,
# owner просит вынести его в общий чат, а Боб на повтор просьбы отвечает «я же только
# что рассказал ГРУППЕ». Просьба лексически НЕ цепляет содержимое разговора — так
# сценарий проверяет именно нить (её реплеят всегда), а не recall.
_THREAD_REQUEST = "Боб, расскажи ребятам в общем чате, чем мы занимались"
_TOLD_IN_DM = "Вова: чем занимались?\nbob: чинили выключенный свет и обидели GUPPI"
_TOLD_IN_ROOM = "Лиля: как жизнь?\nbob: да вот, свет чинили при всех"

_DM_THREAD = (Memory(_TOLD_IN_DM, "owner_private"),)
_ROOM_THREAD = (Memory(_TOLD_IN_ROOM, "public"),)
_MIXED_THREAD = _DM_THREAD + _ROOM_THREAD
_UNMARKED_THREAD = (Memory("Вова: а помнишь?\nbob: смутно", None),)


@dataclass(slots=True)
class _OriginContext:
    """Слейт сценария: изолированный корень хранилища, архив, флаг и итоги хода."""

    tmp_path: Path
    archive: tuple[Memory, ...] = _PRIVATE_ARCHIVE
    # Вопрос хода: у нити своя просьба (та самая, живая), у припомненного — своя.
    question: str = _QUESTION
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


@given("разговор состоялся в личке, и он ещё в недавней нити")
def thread_is_private(origin_context: _OriginContext) -> None:
    origin_context.archive = _DM_THREAD
    origin_context.question = _THREAD_REQUEST


@given("разговор состоялся при всех в общем чате, и он ещё в недавней нити")
def thread_is_public(origin_context: _OriginContext) -> None:
    origin_context.archive = _ROOM_THREAD
    origin_context.question = _THREAD_REQUEST


@given("часть нити была сказана в личке, а часть при всех")
def thread_is_mixed(origin_context: _OriginContext) -> None:
    origin_context.archive = _MIXED_THREAD
    origin_context.question = _THREAD_REQUEST


@given("в недавней нити лежит старая реплика без метки места")
def thread_is_unmarked(origin_context: _OriginContext) -> None:
    origin_context.archive = _UNMARKED_THREAD
    origin_context.question = _THREAD_REQUEST


# --- Когда: ход владельца -------------------------------------------------------


@when("владелец спрашивает Боба про этот разговор")
@when("владелец просит рассказать это в общем чате")
def owner_asks(origin_context: _OriginContext) -> None:
    origin_context.outcome = asyncio.run(
        run_origin_turn(
            origin_context.tmp_path,
            archive=origin_context.archive,
            question=origin_context.question,
            origin_provenance=origin_context.provenance_enabled,
        )
    )


@when("владелец задаёт один и тот же вопрос при выключенном и при включённом провенансе")
def owner_asks_both_ways(origin_context: _OriginContext) -> None:
    off, on = asyncio.run(
        run_origin_pair(
            origin_context.tmp_path,
            archive=origin_context.archive,
            question=origin_context.question,
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


@then("ход с выключенным флагом совпадает с включённым строка в строку, кроме сказанного о месте")
def off_path_is_identical_apart_from_the_place(
    origin_context: _OriginContext,
) -> None:
    assert without_places(origin_context.outcome.prompt) == (
        origin_context.without_provenance.prompt
    ), "включённый провенанс изменил ход не только тем, что назвал место"


# --- Тогда: что Боб видит про место реплик НИТИ (C3) -----------------------------


@then("каждая реплика нити помечена как сказанная в личке")
def thread_turns_are_marked_private(origin_context: _OriginContext) -> None:
    # 🔴 Тот самый дефект: без пометки Боб счёл, что уже рассказал ГРУППЕ то, что
    # сказал в личку, и потому ничего не отправил.
    prompt = origin_context.outcome.prompt
    assert f"{MARK_PRIVATELY} {_TOLD_IN_DM}" in prompt, (
        f"нить пришла без места: {marked_thread_lines(prompt)!r}"
    )
    assert MARK_IN_ROOM not in prompt


@then("Бобу сказано, что сказанное в личке в общий чат ещё не попадало")
def warned_that_the_dm_never_reached_the_room(origin_context: _OriginContext) -> None:
    assert origin_context.outcome.claims("в общий чат это ещё не попадало")


@then("каждая реплика нити помечена как сказанная при всех")
def thread_turns_are_marked_public(origin_context: _OriginContext) -> None:
    # Обратный случай: сказанное при всех не должно выдаваться за сказанное наедине.
    assert f"{MARK_IN_ROOM} {_TOLD_IN_ROOM}" in origin_context.outcome.prompt


@then("ни одна реплика нити не помечена как сказанная в личке")
def no_thread_turn_is_marked_private(origin_context: _OriginContext) -> None:
    assert MARK_PRIVATELY not in origin_context.outcome.prompt


@then("сказанное в личке помечено личкой, а сказанное при всех — общим чатом")
def each_turn_carries_its_own_place(origin_context: _OriginContext) -> None:
    # Нить почти всегда смешана: Бобу нужно ЗНАТЬ, где что было, а не общее «не угадывай».
    prompt = origin_context.outcome.prompt
    assert f"{MARK_PRIVATELY} {_TOLD_IN_DM}" in prompt
    assert f"{MARK_IN_ROOM} {_TOLD_IN_ROOM}" in prompt


@then("ни одна реплика нити не помечена местом")
def no_thread_turn_carries_a_place(origin_context: _OriginContext) -> None:
    # ``visibility IS NULL`` — «место неизвестно», а не «сказано при всех».
    assert marked_thread_lines(origin_context.outcome.prompt) == ()


@then("при выключенном флаге ни одна реплика нити не помечена местом")
def off_marks_no_thread_turn(origin_context: _OriginContext) -> None:
    assert marked_thread_lines(origin_context.without_provenance.prompt) == ()
