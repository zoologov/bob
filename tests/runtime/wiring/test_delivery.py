# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты проводки инструмента отправки (BOB-090.B1).

Флаг ``social.delivery`` — единственное место, где инструмент вообще появляется. OFF
(умолчание) → его нет в манифесте, значит модель физически не может его вызвать, и
поведение байт-в-байт прежнее. ON → он собран над известными адресами, взятыми из
конфига: точный чат И точный форум-топик.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.runtime.wiring.delivery import build_send_to_chat, known_destinations
from bob.social.destination import DestinationKind

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.social.first_impression import FirstImpression

_CONFIG_ON: dict[str, object] = {
    "social": {"delivery": True},
    "telegram": {
        "chat_id": -1004372947307,
        "owner_id": 27468732,
        "bob": {"topic_id": 32},
    },
}


class _FakeBot:
    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        del chat_id, text, message_thread_id
        return None

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
    ) -> object:
        del chat_id, rich_message, message_thread_id
        return None


class _FakeDirectory:
    async def recent(self, *, limit: int) -> list[FirstImpression]:
        del limit
        return []


def _bot() -> BotLike:
    return cast("BotLike", _FakeBot())


def _names(registry: CapabilityRegistry) -> set[str]:
    return {
        str(tool["function"]["name"])  # type: ignore[index]
        for tool in registry.manifest()
    }


def test_the_tool_is_absent_by_default() -> None:
    registry = CapabilityRegistry()

    built = build_send_to_chat(
        {"telegram": {"chat_id": -100, "owner_id": 1}},
        registry=registry,
        bot=_bot(),
        directory=_FakeDirectory(),
        consent=None,
    )

    assert built is False
    assert "send_to_chat" not in _names(registry)


def test_the_flag_registers_the_tool() -> None:
    registry = CapabilityRegistry()

    built = build_send_to_chat(
        _CONFIG_ON,
        registry=registry,
        bot=_bot(),
        directory=_FakeDirectory(),
        consent=None,
    )

    assert built is True
    assert "send_to_chat" in _names(registry)


def test_without_any_known_address_the_tool_is_not_offered() -> None:
    # Нечего предлагать: не настроен ни один чат — инструмент, который может только
    # переспрашивать, модели не нужен.
    registry = CapabilityRegistry()

    built = build_send_to_chat(
        {"social": {"delivery": True}, "telegram": {}},
        registry=registry,
        bot=_bot(),
        directory=_FakeDirectory(),
        consent=None,
    )

    assert built is False
    assert "send_to_chat" not in _names(registry)


def test_the_group_address_carries_bobs_topic() -> None:
    group = next(
        address
        for address in known_destinations(_CONFIG_ON)
        if address.kind is DestinationKind.GROUP
    )

    assert group.chat_id == -1004372947307
    assert group.topic_id == 32  # именно топик Боба, а не General
    assert group.label


def test_the_owner_dm_address_defaults_to_the_owner_id() -> None:
    dm = next(
        address
        for address in known_destinations(_CONFIG_ON)
        if address.kind is DestinationKind.OWNER_DM
    )

    assert dm.chat_id == 27468732
    assert dm.topic_id is None  # у лички форум-топиков не бывает


def test_an_unconfigured_chat_is_not_invented() -> None:
    assert known_destinations({"telegram": {"chat_id": 0, "owner_id": 0}}) == ()
