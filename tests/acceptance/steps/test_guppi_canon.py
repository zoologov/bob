# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шаги сценариев канона GUPPI и голоса разрешений (BOB-090 Срезы D и E, US-4 / US-5).

Связывают ``guppi_canon.feature`` с :mod:`tests.acceptance.guppi_canon_harness`: сессия
кодера идёт через настоящий транспортный адаптер на двух записывающих ботах, эпизоды
читаются из настоящей SQLite в том же прогоне, а просьба о разрешении прогоняется через
живой композиционный корень. Утверждается наблюдаемое: какой бот что сказал, в какой топик
и что от этого осталось в памяти.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.acceptance.guppi_canon_harness import (
    GUPPI_PREFIX,
    CanonOutcome,
    PermissionOutcome,
    run_coding_session,
    run_permission_ask,
)
from tests.acceptance.live_app_harness import (
    BOB_TOPIC_ID,
    GROUP_CHAT_ID,
    NORMAN_NAME,
    RecordingBot,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/guppi_canon.feature")

# Просьба постороннего, которой нужно разрешение владельца, и внутренняя английская
# строка классификатора — ровно та, что однажды прозвучала в чате целиком.
_PRIVILEGED_ASK = "Боб, расскажи, о чём вы с Вовой говорили в личке"
_JUDGE_VERDICT = "Requesting details of private conversations with another user"
_OWNER_HANDLE = "vzoologov"

# Живые реплики самого Боба на гейтах сессии (его голос, не отчёт машины): он берётся за
# задачу и он же приносит результат человеку. Куски выбраны так, чтобы не совпасть с сухим
# «GUPPI: готово» — иначе сценарий не отличал бы голоса, а искал общее слово.
_BOBS_OWN_LINES = ("берусь", "Вот PR")


@dataclass(slots=True)
class _CanonContext:
    """Слейт сценария: изолированный корень и итог одного прогона."""

    tmp_path: Path
    owner_username: str | None = None
    session: CanonOutcome | None = None
    permission: PermissionOutcome | None = None


@pytest.fixture
def canon_context(tmp_path: Path) -> _CanonContext:
    """Свежий изолированный корень хранилища на каждый сценарий."""
    return _CanonContext(tmp_path=tmp_path)


def _session(canon_context: _CanonContext) -> CanonOutcome:
    assert canon_context.session is not None, "сессия в этом сценарии не проводилась"
    return canon_context.session


def _permission(canon_context: _CanonContext) -> PermissionOutcome:
    assert canon_context.permission is not None, "просьба в этом сценарии не звучала"
    return canon_context.permission


def _carried(bot: RecordingBot, needle: str) -> bool:
    return any(needle in line.text for line in bot.sent)


# --- Дано / Когда ----------------------------------------------------------------


@given("владелец проводит полную сессию кодера при включённом канале GUPPI")
def a_session_with_guppis_channel(canon_context: _CanonContext) -> None:
    canon_context.session = asyncio.run(
        run_coding_session(canon_context.tmp_path, stream_via_guppi=True)
    )


@given("владелец проводит полную сессию кодера при выключенном канале GUPPI")
def a_session_without_guppis_channel(canon_context: _CanonContext) -> None:
    canon_context.session = asyncio.run(
        run_coding_session(canon_context.tmp_path, stream_via_guppi=False)
    )


@given("у владельца в ростере записан настоящий ник")
def the_owner_has_a_handle(canon_context: _CanonContext) -> None:
    canon_context.owner_username = _OWNER_HANDLE


@given("посторонний человек просит у Боба то, на что нужно разрешение владельца")
def a_stranger_asks_for_something_privileged(canon_context: _CanonContext) -> None:
    canon_context.owner_username = canon_context.owner_username


@when("Боб решает, спрашивать ли владельца")
def bob_weighs_the_ask(canon_context: _CanonContext) -> None:
    canon_context.permission = asyncio.run(
        run_permission_ask(
            canon_context.tmp_path,
            request=_PRIVILEGED_ASK,
            judge_what=_JUDGE_VERDICT,
            owner_username=canon_context.owner_username,
        )
    )


# --- Тогда: кто что нёс ----------------------------------------------------------


@then("пошаговый нарратив исполнения несёт бот GUPPI")
def guppi_carries_the_mechanics(canon_context: _CanonContext) -> None:
    assert _carried(_session(canon_context).guppi, GUPPI_PREFIX), (
        "механика не ушла каналом GUPPI"
    )


@then("реплики самого Боба несёт бот Боба")
def bob_carries_his_own_voice(canon_context: _CanonContext) -> None:
    bob = _session(canon_context).bob
    for line in _BOBS_OWN_LINES:
        assert _carried(bob, line), f"голос Боба не ушёл его ботом: {line!r}"


@then("бот Боба не несёт пошаговый нарратив")
def bobs_bot_stays_out_of_the_mechanics(canon_context: _CanonContext) -> None:
    assert not _carried(_session(canon_context).bob, GUPPI_PREFIX)


@then("бот GUPPI не несёт реплик Боба")
def guppis_bot_stays_out_of_bobs_voice(canon_context: _CanonContext) -> None:
    guppi = _session(canon_context).guppi
    for line in _BOBS_OWN_LINES:
        assert not _carried(guppi, line), f"голос Боба унёс бот GUPPI: {line!r}"


@then("ни одна строка канала GUPPI не осела в памяти")
def guppis_lines_never_become_memories(canon_context: _CanonContext) -> None:
    # 🔴 Голос Боба воспроизводится по recall: осевшая машинная строка вернулась бы в его
    # речь через несколько ходов (класс BOB-022 / 074 / 078).
    session = _session(canon_context)
    assert session.guppi.sent, "механика вообще не звучала — проверять нечего"
    for line in session.guppi.sent:
        assert all(line.text not in content for content in session.remembered), line
    assert all(GUPPI_PREFIX not in content for content in session.remembered)


@then("в памяти остались поступки Боба от первого лица и его рабочая вспоминка")
def memory_keeps_bobs_own_deeds(canon_context: _CanonContext) -> None:
    # Позитивный контроль: память в этом прогоне ПИСАЛАСЬ, значит «ничего не нашли» выше —
    # не пустой ассерт.
    session = _session(canon_context)
    assert session.remembers("self_action"), "память не писалась вовсе"
    assert session.remembers("work")
    deeds = [
        content
        for kind, content in session.episodes
        if kind == "self_action"
    ]
    assert any(content.lower().startswith("я ") for content in deeds), deeds


@then("всё сказанное за сессию несёт бот Боба")
def the_whole_session_goes_on_bobs_bot(canon_context: _CanonContext) -> None:
    session = _session(canon_context)
    assert _carried(session.bob, GUPPI_PREFIX), "механика не ушла ботом Боба"
    for line in _BOBS_OWN_LINES:
        assert _carried(session.bob, line)


@then("бот GUPPI молчит")
def guppis_bot_is_silent(canon_context: _CanonContext) -> None:
    assert not _session(canon_context).guppi.sent


# --- Тогда: голос разрешений ------------------------------------------------------


@then("просьба приходит ботом Боба, в топик Боба")
def the_ask_comes_from_bob_in_his_topic(canon_context: _CanonContext) -> None:
    notice = _permission(canon_context).to_owner
    assert notice is not None, "Боб не спросил владельца вовсе"
    assert notice.chat_id == GROUP_CHAT_ID
    assert notice.topic_id == BOB_TOPIC_ID, (
        f"просьба упала мимо топика Боба: {notice!r}"
    )


@then("просьба звучит словами Боба: кто просит, чего именно и почему он спрашивает")
def the_ask_sounds_like_bob(canon_context: _CanonContext) -> None:
    notice = _permission(canon_context).to_owner
    assert notice is not None
    said = notice.text
    assert NORMAN_NAME in said, f"не сказано, кто просит: {said!r}"
    assert _PRIVILEGED_ASK in said, f"не сказано, чего именно просят: {said!r}"
    assert "решать тебе" in said, f"не сказано, почему Боб спрашивает: {said!r}"
    assert said.rstrip().endswith("?"), f"это не вопрос: {said!r}"


@then("служебной строки классификатора в просьбе нет")
def the_judges_verdict_stays_inside(canon_context: _CanonContext) -> None:
    outcome = _permission(canon_context)
    notice = outcome.to_owner
    assert notice is not None
    assert outcome.judge_verdict not in notice.text, (
        "английский вердикт классификатора зачитан человеку"
    )


@then("бот GUPPI при этом молчит")
def guppi_says_nothing_about_the_ask(canon_context: _CanonContext) -> None:
    # Просьба о разрешении — социальный акт Боба, а не механика.
    assert not _permission(canon_context).guppi.sent


@then("просителю уходит короткое «спрошу владельца» в топик Боба")
def the_requester_gets_an_ack_in_the_same_topic(canon_context: _CanonContext) -> None:
    ack = _permission(canon_context).to_requester
    assert ack is not None, "проситель остался без ответа"
    assert "спрошу" in ack.text.casefold()
    assert ack.topic_id == BOB_TOPIC_ID, (
        f"ответ просителю снова упал в General: {ack!r}"
    )


@then("владельца называют по имени, без выдуманного тега")
def the_owner_is_named_without_an_invented_tag(canon_context: _CanonContext) -> None:
    notice = _permission(canon_context).to_owner
    assert notice is not None
    assert notice.text.startswith("Вова,"), notice.text
    assert "@Вова" not in notice.text


@then("владельца зовут его настоящим ником")
def the_owner_is_addressed_by_his_handle(canon_context: _CanonContext) -> None:
    notice = _permission(canon_context).to_owner
    assert notice is not None
    assert f"@{_OWNER_HANDLE}" in notice.text, notice.text
