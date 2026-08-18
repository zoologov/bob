# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Провязка объявления рестарта: флаг ``runtime.restart_notice`` РЕАЛЬНО доезжает (BOB-094 срез 1).

🔴 Отгрузка без активации — не возможность (§0.3 п.10): наличие use-case ничего не
значит, если хук его не зовёт. Поэтому тесты наблюдают ПОВЕДЕНИЕ собранной системы через
границу (фейковый бот): при выключенном флаге shutdown/startup молчат байт-в-байт, при
включённом — уход шлёт owner'у И в группу и оставляет маркер, а следующий старт говорит
«вернулся» и снимает маркер.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.runtime.wiring import _build_restart_announcer

if TYPE_CHECKING:
    from bob.infrastructure.telegram.restart_notifier import _PlainNotifyBot


class _RecordingBot:
    def __init__(self) -> None:
        self.sends: list[tuple[int, str, int | None]] = []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        self.sends.append((chat_id, text, message_thread_id))
        return object()


class _FakeKv:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def kv_set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def kv_get(self, key: str) -> str | None:
        return self.data.get(key)


def _config(*, restart_notice: bool) -> dict[str, object]:
    return {
        "runtime": {"restart_notice": restart_notice},
        "telegram": {
            "owner_id": 111,
            "chat_id": 222,
            "bob": {"topic_id": 5},
        },
    }


def test_flag_off_wires_no_announcer() -> None:
    announcer = _build_restart_announcer(
        _config(restart_notice=False),
        bot=cast("_PlainNotifyBot", _RecordingBot()),
        kv=_FakeKv(),
    )
    assert announcer is None


async def test_flag_on_leaving_announces_to_owner_and_group_and_marks() -> None:
    bot = _RecordingBot()
    kv = _FakeKv()
    announcer = _build_restart_announcer(
        _config(restart_notice=True), bot=cast("_PlainNotifyBot", bot), kv=kv
    )
    assert announcer is not None

    await announcer.announce_leaving()

    # owner-DM (111, без топика) + группа (222, топик 5)
    targets = {(chat, thread) for chat, _text, thread in bot.sends}
    assert (111, None) in targets
    assert (222, 5) in targets
    # маркер апдейт-остановки оставлен в kv
    assert kv.data.get("restart.pending_update")


async def test_flag_on_returned_speaks_then_the_marker_is_gone() -> None:
    bot = _RecordingBot()
    kv = _FakeKv()
    announcer = _build_restart_announcer(
        _config(restart_notice=True), bot=cast("_PlainNotifyBot", bot), kv=kv
    )
    assert announcer is not None

    # Сначала уход поставил маркер, затем старт возвращается по нему.
    await announcer.announce_leaving()
    bot.sends.clear()
    await announcer.announce_returned()

    assert bot.sends, "возвращение по апдейт-маркеру обязано что-то сказать"
    assert not kv.data.get("restart.pending_update")
