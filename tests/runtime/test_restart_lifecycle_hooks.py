# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Хуки рестарта живут в lifecycle собранного приложения (BOB-094 срез 1).

🔴 Отгрузка ≠ активация (§0.3 п.10): недостаточно, что use-case собран — надо, чтобы
``Application.shutdown`` РЕАЛЬНО объявлял уход, а ``Application.startup`` — возвращение.
Тесты гоняют настоящую композицию с фейковыми ботами (без сети) и наблюдают отправки
через границу.

Порядок в shutdown критичен: объявление обязано уйти ДО закрытия соединения/рантайма,
иначе оно писало бы маркер в закрытую БД. Проверяем это, наблюдая, что отправка удалась и
маркер лёг (а значит kv был ещё жив).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.runtime.composition import build_application
from bob.social.adapters.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import BotLike, UpdateLike
    from bob.kernel.ports import LLMProvider


def _bots(bob_bot: _Bot) -> tuple[BotLike, BotLike]:
    """Cast the minimal send-tracking fakes to ``BotLike`` for the composition seam.

    The fake exercises only the send path this slice needs; the full ``BotLike`` protocol
    is not reimplemented (out of scope) — the cast keeps mypy honest about that boundary.
    """
    return cast("BotLike", bob_bot), cast("BotLike", _Bot())


class _Provider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return "ok"


class _Msg:
    message_id = 1


class _Bot:
    def __init__(self) -> None:
        self.sends: list[tuple[int, str, int | None]] = []

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _Msg:
        self.sends.append((chat_id, text, message_thread_id))
        return _Msg()

    async def set_message_reaction(self, **_: object) -> bool:
        return True

    async def send_chat_action(self, **_: object) -> bool:
        return True


def _providers() -> dict[int, LLMProvider]:
    return {0: _Provider(), 1: _Provider()}


def _seed_soul(tmp_path: Path) -> None:
    # Pre-seed a SOUL so startup's Genesis is a no-op (it would otherwise call the fake
    # provider, whose "ok" is not valid personality JSON, and fail the boot).
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nBob.\n")


def _config(tmp_path: Path, *, restart_notice: bool) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 1, "restart_notice": restart_notice},
        "telegram": {
            "poll_timeout": 1,
            "owner_id": 111,
            "chat_id": 222,
            "bob": {"token": "bob-tok", "topic_id": 5},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


async def test_shutdown_announces_leaving_and_leaves_a_marker(tmp_path: Path) -> None:
    _seed_soul(tmp_path)
    bob_bot = _Bot()
    bob, guppi = _bots(bob_bot)
    app = build_application(
        config=_config(tmp_path, restart_notice=True),
        providers=_providers(),
        bob_bot=bob,
        guppi_bot=guppi,
    )
    await app.startup()
    bob_bot.sends.clear()  # отбросить всё, что могло уйти на старте

    await app.shutdown()

    # Ушло владельцу (111) и в группу-топик (222, 5) — значит транспорт был ещё жив.
    targets = {(chat, thread) for chat, _text, thread in bob_bot.sends}
    assert (111, None) in targets
    assert (222, 5) in targets


async def test_startup_after_update_stop_announces_return(tmp_path: Path) -> None:
    _seed_soul(tmp_path)
    # Первый цикл: старт + shutdown ставит маркер апдейт-остановки.
    first_bob, first_guppi = _bots(_Bot())
    first = build_application(
        config=_config(tmp_path, restart_notice=True),
        providers=_providers(),
        bob_bot=first_bob,
        guppi_bot=first_guppi,
    )
    await first.startup()
    await first.shutdown()

    # Второй цикл поверх ТОЙ ЖЕ БД: старт видит маркер и говорит «вернулся».
    second_bot = _Bot()
    second_bob, second_guppi = _bots(second_bot)
    second = build_application(
        config=_config(tmp_path, restart_notice=True),
        providers=_providers(),
        bob_bot=second_bob,
        guppi_bot=second_guppi,
    )
    await second.startup()

    assert second_bot.sends, "старт после апдейт-остановки обязан объявить возвращение"
    await second.shutdown()


async def test_flag_off_keeps_lifecycle_silent(tmp_path: Path) -> None:
    _seed_soul(tmp_path)
    bob_bot = _Bot()
    bob, guppi = _bots(bob_bot)
    app = build_application(
        config=_config(tmp_path, restart_notice=False),
        providers=_providers(),
        bob_bot=bob,
        guppi_bot=guppi,
    )
    await app.startup()
    await app.shutdown()

    assert bob_bot.sends == [], "при выключенном флаге рестарт-объявлений нет (байт-в-байт)"
