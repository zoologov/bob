# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Шаги сценариев «Боб пишет туда, куда просят» (BOB-090 Срез B, US-2 / US-3).

Связывают ``chat_addressing.feature`` с :mod:`tests.acceptance.delivery_harness`: ход идёт
через живой композиционный корень (настоящая SQLite, настоящий ростер, настоящий реестр
capability и tool-loop), а утверждается наблюдаемое — что ушло, каким ботом, в какой чат и
топик, и что инструмент отправки ответил самой модели. Сценарии синхронные (pytest-bdd),
поэтому асинхронный ход гоняется через ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.delivery_harness import (
    DeliveryOutcome,
    run_owner_dm_request,
    run_trusted_peer_request,
)
from tests.acceptance.live_app_harness import (
    BOB_TOPIC_ID,
    GROUP_CHAT_ID,
    NORMAN_USERNAME,
    RecordingBot,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

scenarios("../features/chat_addressing.feature")

# Как владелец формулирует просьбу и что Боб пишет ИМЕННО ТУДА (аргумент инструмента).
_ASK_TO_TELL_NORMAN = "Боб, напиши Норману в группу, что я закончил обзор"
_MESSAGE_FOR_THE_ROOM = "@Норман, Вова закончил обзор — можно смотреть."

# Сказанное наедине, которое УЖЕ лежит в памяти Боба: именно его поднимет живой recall на
# просьбу «расскажи, о чём мы говорили» — то есть материал, который Боб добавляет от себя.
_PRIVATE_MOMENT = "Вова: я вымотался и не тяну этот спринт, нужна передышка"
_ASK_TO_TRANSFER = "Боб, расскажи Норману в группе, о чём мы говорили про спринт"

# Приватный материал в двух формах. По решению owner'а перенос считается ПО МАТЕРИАЛУ, так
# что форма не должна менять ничего: и цитата, и пересказ — один и тот же вынос.
_TRANSFER_FORMS: Mapping[str, str] = {
    "дословно передать": (
        "Вова сказал дословно: «я вымотался и не тяну этот спринт»."
    ),
    "пересказать своими словами": (
        "Вова немного устал за спринт, ему бы передышку."
    ),
}


@dataclass(slots=True)
class _AddressingContext:
    """Слейт сценария: обстоятельства просьбы и наблюдаемый итог хода."""

    tmp_path: Path
    norman_username: str | None = NORMAN_USERNAME
    consent: bool = True
    delivery_enabled: bool = True
    request: str = _ASK_TO_TELL_NORMAN
    tool_call: Mapping[str, object] | None = None
    from_peer: bool = False
    private_memory: str | None = None
    outcome: DeliveryOutcome = field(
        default_factory=lambda: DeliveryOutcome(
            bob=RecordingBot("bob"), guppi=RecordingBot("guppi")
        )
    )
    # S7: тот же ход при включённом флаге — база для доказательства равенством.
    counterpart: DeliveryOutcome | None = None


@pytest.fixture
def addressing_context(tmp_path: Path) -> _AddressingContext:
    """Свежий изолированный корень хранилища на каждый сценарий."""
    return _AddressingContext(tmp_path=tmp_path)


# --- Дано: ростер, просьба, согласие --------------------------------------------


@given("у Нормана в ростере записан настоящий ник")
def norman_has_a_handle(addressing_context: _AddressingContext) -> None:
    addressing_context.norman_username = NORMAN_USERNAME


@given("у Нормана в ростере ника нет")
def norman_has_no_handle(addressing_context: _AddressingContext) -> None:
    # Нормальное состояние в Telegram, а не отсутствие данных.
    addressing_context.norman_username = None


@given("владелец из лички просит написать Норману в группу")
def owner_asks_to_write_to_the_room(addressing_context: _AddressingContext) -> None:
    addressing_context.request = _ASK_TO_TELL_NORMAN
    addressing_context.tool_call = {
        "place": "group",
        "text": _MESSAGE_FOR_THE_ROOM,
    }


@given("владелец из лички просит написать «куда надо»")
def owner_asks_vaguely(addressing_context: _AddressingContext) -> None:
    addressing_context.request = "Боб, напиши это куда надо"
    addressing_context.tool_call = {"place": "куда надо", "text": "Я закончил обзор."}


@given("доверенный участник комнаты просит написать владельцу в личку")
def a_peer_asks_to_write_to_the_owner(addressing_context: _AddressingContext) -> None:
    # Адрес однозначен (личка владельца известна) — и это ничего не меняет: распорядиться
    # отправкой в другой чат вправе только владелец (урок BOB-076).
    addressing_context.from_peer = True
    addressing_context.request = "Боб, напиши Вове в личку, что я жду ревью"
    addressing_context.tool_call = {
        "place": "owner_dm",
        "text": "Норман ждёт ревью.",
    }


@given("Боб помнит сказанное владельцем наедине")
def bob_remembers_a_private_moment(addressing_context: _AddressingContext) -> None:
    # 🔴 Материал кладётся в ЖИВУЮ память, а не подставляется инструменту: гейт должен
    # зажечься от того, что Боб добавляет ОТ СЕБЯ (recall поднял приватный эпизод), а не
    # от места разговора — иначе он срабатывал бы и на прямом распоряжении владельца.
    addressing_context.private_memory = _PRIVATE_MOMENT


@given(parsers.parse("владелец из лички просит {form} сказанное наедине"))
def owner_asks_to_transfer_private_matter(
    addressing_context: _AddressingContext, form: str
) -> None:
    addressing_context.request = _ASK_TO_TRANSFER
    addressing_context.tool_call = {"place": "group", "text": _TRANSFER_FORMS[form]}


@given("владелец согласия на этот вынос не давал")
def owner_withholds_consent(addressing_context: _AddressingContext) -> None:
    addressing_context.consent = False


@given("владелец даёт согласие на этот вынос")
def owner_gives_consent(addressing_context: _AddressingContext) -> None:
    addressing_context.consent = True


@given("флаг social.delivery выключен")
def delivery_flag_off(addressing_context: _AddressingContext) -> None:
    addressing_context.delivery_enabled = False


# --- Когда: ход ------------------------------------------------------------------


@when("Боб выполняет просьбу")
def bob_acts_on_the_request(addressing_context: _AddressingContext) -> None:
    addressing_context.outcome = asyncio.run(_run(addressing_context))


@when("владелец просто разговаривает с Бобом в личке")
def owner_just_talks(addressing_context: _AddressingContext) -> None:
    # Обычный ход без единой попытки отправки: при выключенном флаге он обязан выглядеть
    # ровно так же, как при включённом.
    addressing_context.request = "Боб, как сам?"
    addressing_context.tool_call = None
    addressing_context.outcome = asyncio.run(_run(addressing_context))
    addressing_context.counterpart = asyncio.run(
        run_owner_dm_request(
            addressing_context.tmp_path / "on",
            request=addressing_context.request,
            tool_call=None,
            delivery=True,
        )
    )


async def _run(context: _AddressingContext) -> DeliveryOutcome:
    """Прогнать ход того, кто просит: владелец из лички или участник из комнаты."""
    if context.from_peer:
        return await run_trusted_peer_request(
            context.tmp_path,
            request=context.request,
            tool_call=context.tool_call,
        )
    return await run_owner_dm_request(
        context.tmp_path / "turn",
        request=context.request,
        tool_call=context.tool_call,
        consent=context.consent,
        norman_username=context.norman_username,
        delivery=context.delivery_enabled,
        private_memory=context.private_memory,
    )


# --- Тогда: что ушло и куда ------------------------------------------------------


@then("сообщение появляется в общей группе, в топике Боба")
def the_message_reaches_the_room(addressing_context: _AddressingContext) -> None:
    delivered = addressing_context.outcome.group
    assert delivered, (
        "в общую группу не ушло ничего — просьба «напиши в группу» снова не выполнена"
    )
    assert delivered[0].chat_id == GROUP_CHAT_ID
    assert delivered[0].topic_id == BOB_TOPIC_ID, (
        f"сообщение упало мимо топика Боба: {delivered[0]!r}"
    )


@then("его несёт бот Боба")
def bobs_own_bot_carries_it(addressing_context: _AddressingContext) -> None:
    outcome = addressing_context.outcome
    assert outcome.bob.to(GROUP_CHAT_ID), "в комнате появился не Боб"
    assert not outcome.guppi.to(GROUP_CHAT_ID), "обращение к человеку унёс бот GUPPI"


@then("обращение к Норману — его настоящий ник")
def norman_is_addressed_by_his_handle(addressing_context: _AddressingContext) -> None:
    said = addressing_context.outcome.group[0].text
    assert f"@{NORMAN_USERNAME}" in said, f"тег не заземлён на ростер: {said!r}"
    assert "@Норман" not in said, "в комнату ушёл выдуманный тег (эпизод 3088)"


@then("к Норману обращаются по имени, без «собаки»")
def norman_is_addressed_by_name(addressing_context: _AddressingContext) -> None:
    said = addressing_context.outcome.group[0].text
    assert "Норман" in said
    assert "@Норман" not in said


@then("в сообщении нет выдуманного тега")
def no_tag_is_invented(addressing_context: _AddressingContext) -> None:
    # 🔴 Из имени тег не собирается никогда: выдуманный хуже отсутствующего.
    assert "@" not in addressing_context.outcome.group[0].text


@then("в личку владельца копия сообщения не уходит")
def no_copy_lands_in_the_dm(addressing_context: _AddressingContext) -> None:
    outcome = addressing_context.outcome
    said_in_the_room = outcome.group[0].text
    assert all(said_in_the_room not in line.text for line in outcome.dm), (
        "сообщение для комнаты продублировалось в личку — снова «не туда»"
    )


@then("в общую группу ничего не ушло")
def nothing_reaches_the_room(addressing_context: _AddressingContext) -> None:
    outcome = addressing_context.outcome
    assert not outcome.group, f"в комнату всё-таки ушло: {outcome.group!r}"
    assert not outcome.delivered


@then("в личку владельца ничего не ушло")
def nothing_reaches_the_owner_dm(addressing_context: _AddressingContext) -> None:
    outcome = addressing_context.outcome
    assert not outcome.dm, f"в личку владельца всё-таки ушло: {outcome.dm!r}"
    assert not outcome.delivered


@then("Бобу сказано переспросить, в какой именно чат писать")
def bob_is_told_to_ask_which_chat(addressing_context: _AddressingContext) -> None:
    # Вердикт возвращается МОДЕЛИ подсказкой — Боб переспрашивает своими словами.
    assert "Переспроси, в какой именно чат" in addressing_context.outcome.tool_said


@then("Бобу сказано, что такое распоряжение может дать только владелец")
def bob_is_told_only_the_owner_may_order_it(
    addressing_context: _AddressingContext,
) -> None:
    said = addressing_context.outcome.tool_said
    assert "только по просьбе Вовы" in said, said


@then("согласия на прямое распоряжение у владельца не спрашивали")
def no_consent_was_ever_asked(addressing_context: _AddressingContext) -> None:
    # 🔴 Ровно дефект B-fix: раньше переносом считался ЛЮБОЙ ход из лички, поэтому
    # прямое распоряжение уходило к консервативному судье согласия и получало отказ.
    # Согласие содержится в самой команде — спрашивать не о чем, и Tier-0 не горит.
    assert addressing_context.outcome.consent_calls == 0, (
        "у владельца спросили согласие на его же прямое распоряжение"
    )


@then("согласие у владельца спросили")
def consent_was_asked(addressing_context: _AddressingContext) -> None:
    # Обратная сторона: приватное из памяти без вопроса не уезжает даже с «да» в кармане.
    assert addressing_context.outcome.consent_calls > 0, (
        "приватное из памяти поехало в комнату, ни о чём не спросив"
    )


@then("Бобу сказано спросить согласие владельца")
def bob_is_told_to_ask_for_consent(addressing_context: _AddressingContext) -> None:
    said = addressing_context.outcome.tool_said
    assert "говорилось наедине" in said, said
    assert "согласие" in said


@then("модель не видит инструмента отправки")
def the_tool_is_absent(addressing_context: _AddressingContext) -> None:
    assert not addressing_context.outcome.tool_offered


@then("отправленное совпадает с ходом при включённом флаге строка в строку")
def the_off_turn_is_identical(addressing_context: _AddressingContext) -> None:
    counterpart = addressing_context.counterpart
    assert counterpart is not None
    assert addressing_context.outcome.bob.sent == counterpart.bob.sent, (
        "выключенный флаг изменил обычный ход"
    )
    assert addressing_context.outcome.guppi.sent == counterpart.guppi.sent
    assert counterpart.tool_offered, "контрольный ход шёл без инструмента — сравнивать нечего"
