# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=infrastructure

"""_DmLiveStreamer — лайв-стрим сырых событий coding-прогона в личку owner'а (BOB-082.3).

Реализует порт use-case
:class:`~bob.coding.usecases.coding_assistant.LiveRunStreamer`: когда включён dev-канал
(флаг ``coder.dev_dm``), use-case делегирует сюда ВЕСЬ поток execute-событий, а этот
адаптер:

* рендерит КАЖДОЕ сырое stream-json событие через
  :func:`~bob.coding.stream_render.render_stream_event` (ПОЛНЫЙ рендер, не lossy
  ``narrate``) и шлёт строку в DM-нотификатор — БЕЗ капа ``_MAX_NARRATION`` (в приватной
  личке флуд уместен: owner смотрит «терминал»);
* прогрессивно катит одну editable «терминальную» панель (последние N строк) через
  инъектированный :class:`~bob.coding.usecases.coding_assistant.StatusPanel` для живого
  ощущения потока — отдельные сообщения (нотификатор) + одна катящаяся панель.

Групповой топик firehose НЕ получает (INV-5) — там только короткий указатель, который
шлёт сам use-case. ``is_cancelled`` (kill-switch ``stop``) обрывает поток на следующем
событии → аклоуз раннера убивает процесс. Панель best-effort: её сбой не валит стрим.
Нотификатор/панель инъектируются (DM-нацеленные адаптеры собираются в композиции), поэтому
адаптер transport-free и детерминирован в тестах.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from bob.coding.stream_render import render_stream_event

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping

    from bob.coding.usecases.coding_assistant import OwnerNotifier, StatusPanel

logger = logging.getLogger(__name__)

# Последние N отрендеренных строк, удерживаемых в катящейся «терминальной» панели личка.
_ROLL_WINDOW = 12


class _DmLiveStreamer:
    """Live-стрим сырых событий прогона в dev-канал owner'а (реализует ``LiveRunStreamer``)."""

    def __init__(
        self,
        *,
        notifier: OwnerNotifier,
        panel: StatusPanel | None = None,
        window: int = _ROLL_WINDOW,
    ) -> None:
        self._notifier = notifier
        self._panel = panel
        self._recent: deque[str] = deque(maxlen=window)
        self._opened = False

    async def stream(
        self,
        events: AsyncIterator[Mapping[str, object]],
        *,
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Пролить сырые события в личку (рендер + отправка + катящаяся панель), без капа."""
        async for event in events:
            if is_cancelled():  # a /code stop landed — break (runner closes → proc killed)
                break
            line = render_stream_event(event)
            if line is None:  # pure noise (system-init/heartbeat) — skip
                continue
            await self._notifier.send(line)
            await self._roll(line)

    async def _roll(self, line: str) -> None:
        """Прокатить «терминальную» панель последними строками (best-effort, лениво откр.)."""
        if self._panel is None:
            return
        self._recent.append(line)
        text = "\n".join(self._recent)
        try:
            if self._opened:
                await self._panel.update(text)
            else:
                await self._panel.open(text)
                self._opened = True
        except Exception as exc:  # a panel edit must never break the live firehose
            logger.info("coding dev-channel panel roll failed (ignored): %s", exc)
