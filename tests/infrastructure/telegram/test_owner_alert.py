# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for OwnerAlert — сигнал владельцу о простое LLM-провайдера ботом Боба (BOB-116 D4).

Адаптер порта :class:`~bob.kernel.ports.OwnerAlertSink`: личка владельца
(``chat_id == owner_id``, без топика), текст байт-в-байт, отправка под таймаутом, ошибка
транспорта — наружу (глотает монитор). Путь сигнала не зависит от LLM-стека: модуль не
тянет ни одного модуля провайдеров/роутера.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from bob.infrastructure.telegram.owner_alert import NoopOwnerAlert, OwnerAlert

if TYPE_CHECKING:
    from bob.kernel.ports import OwnerAlertSink

_OWNER_ID = 100500
_ALERT = "Не могу достучаться до своей модели уже 3 минуты (auth). Молчу не от обиды."


class _RecordingBot:
    """Записывает каждый send_message (chat_id, text, message_thread_id)."""

    def __init__(self) -> None:
        self.sends: list[tuple[int, str, int | None]] = []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        self.sends.append((chat_id, text, message_thread_id))
        return object()


class _HangingBot(_RecordingBot):
    """Записывает отправку и не возвращается никогда (зависший транспорт)."""

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        await super().send_message(
            chat_id=chat_id, text=text, message_thread_id=message_thread_id
        )
        await asyncio.Event().wait()
        return object()


class _FailingBot(_RecordingBot):
    """Записывает отправку и падает ошибкой транспорта."""

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> object:
        await super().send_message(
            chat_id=chat_id, text=text, message_thread_id=message_thread_id
        )
        raise ConnectionError("telegram unreachable")


async def test_alert_goes_to_the_owner_dm_verbatim_without_a_topic() -> None:
    bot = _RecordingBot()
    await OwnerAlert(bot, _OWNER_ID).notify_owner(_ALERT)
    assert bot.sends == [(_OWNER_ID, _ALERT, None)]


async def test_each_alert_is_one_send() -> None:
    bot = _RecordingBot()
    alert = OwnerAlert(bot, _OWNER_ID)
    await alert.notify_owner("первый")
    await alert.notify_owner("второй")
    assert bot.sends == [(_OWNER_ID, "первый", None), (_OWNER_ID, "второй", None)]


async def test_a_hanging_transport_times_out() -> None:
    bot = _HangingBot()
    alert = OwnerAlert(bot, _OWNER_ID, timeout_seconds=0.05)
    task = asyncio.ensure_future(alert.notify_owner(_ALERT))
    # Внешний предел — не таймаут: без таймаута адаптера задача просто не завершится.
    done, _ = await asyncio.wait({task}, timeout=5.0)
    if not done:
        task.cancel()
    assert task in done, "notify_owner hung past its own timeout"
    assert isinstance(task.exception(), TimeoutError)
    assert bot.sends == [(_OWNER_ID, _ALERT, None)]


def test_the_default_timeout_is_the_restart_notice_timeout() -> None:
    assert OwnerAlert(_RecordingBot(), _OWNER_ID).timeout_seconds == 5.0


async def test_a_transport_error_propagates_to_the_caller() -> None:
    bot = _FailingBot()
    with pytest.raises(ConnectionError, match="telegram unreachable"):
        await OwnerAlert(bot, _OWNER_ID).notify_owner(_ALERT)
    assert bot.sends == [(_OWNER_ID, _ALERT, None)]


@pytest.mark.parametrize("timeout_seconds", [0.0, -1.0])
def test_a_non_positive_timeout_is_rejected(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        OwnerAlert(_RecordingBot(), _OWNER_ID, timeout_seconds=timeout_seconds)


async def test_noop_alert_sends_nothing_and_does_not_fail() -> None:
    await NoopOwnerAlert().notify_owner(_ALERT)


def test_both_adapters_satisfy_the_owner_alert_port() -> None:
    sinks: list[OwnerAlertSink] = [OwnerAlert(_RecordingBot(), _OWNER_ID), NoopOwnerAlert()]
    assert all(callable(sink.notify_owner) for sink in sinks)


# Модули, через которые проходит отказавший путь: провайдеры, роутер, дублёр, разговор.
_LLM_PATH_PREFIXES = (
    "bob.infrastructure.llm",
    "bob.application.router",
    "bob.conversation",
)


def test_the_alert_path_does_not_load_the_llm_stack() -> None:
    """Поведение собранного импорта, а не форма исходника: чистый интерпретатор, импорт
    адаптера, затем — какие модули реально загрузились."""
    probe = (
        "import sys, bob.infrastructure.telegram.owner_alert\n"
        "print('\\n'.join(sorted(sys.modules)))\n"
    )
    loaded = subprocess.run(  # noqa: S603 — этот интерпретатор, фиксированный argv
        [sys.executable, "-c", probe], check=True, capture_output=True, text=True
    ).stdout.splitlines()
    assert "bob.infrastructure.telegram.owner_alert" in loaded
    llm_modules = [m for m in loaded if m.startswith(_LLM_PATH_PREFIXES)]
    assert llm_modules == []
