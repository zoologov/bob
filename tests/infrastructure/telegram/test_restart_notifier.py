# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for _RestartNotifier — объявление рестарта в личку owner'а и группу (BOB-094 срез 1).

Реализует ``RestartNotifier`` над ботом Боба (канон BOB-090.D: голос Боба, его бот):
owner-DM ``chat_id == owner_id`` (без топика), группа ``chat_id`` + топик Боба
``message_thread_id == topic_id``.
"""

from __future__ import annotations

from bob.infrastructure.telegram.restart_notifier import _RestartNotifier


class _RecordingBot:
    """Записывает каждый send_message (chat_id, text, message_thread_id)."""

    def __init__(self) -> None:
        self.sends: list[tuple[int, str, int | None]] = []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        self.sends.append((chat_id, text, message_thread_id))
        return object()


def _notifier(bot: _RecordingBot) -> _RestartNotifier:
    return _RestartNotifier(bot=bot, owner_id=100, chat_id=200, topic_id=7)


async def test_notify_owner_goes_to_the_owner_dm_without_a_topic() -> None:
    bot = _RecordingBot()
    await _notifier(bot).notify_owner("ухожу обновиться")
    assert bot.sends == [(100, "ухожу обновиться", None)]


async def test_notify_group_goes_to_the_group_topic() -> None:
    bot = _RecordingBot()
    await _notifier(bot).notify_group("вернулся")
    assert bot.sends == [(200, "вернулся", 7)]
