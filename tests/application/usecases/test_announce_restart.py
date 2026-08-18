# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""AnnounceRestart — Боб предупреждает об обновлении и говорит, что вернулся (BOB-094 срез 1).

Оркестрация вокруг чистого ядра :mod:`bob.proactivity.restart_voice`:

* **уход** (в graceful-shutdown, ДО закрытия транспорта) — реплика owner'у И в группу,
  🔴 С ТАЙМАУТОМ: сеть легла → отправка не должна ПОДВЕСИТЬ завершение, Боб молча
  выходит. И маркер апдейт-остановки кладётся в ``kv``;
* **возвращение** (на старте) — реплика «вернулся», ТОЛЬКО если прошлый выход был
  апдейт-остановкой (маркер есть). Упал сам (маркера нет) → молчит, не притворяется
  апдейтом. Маркер консумится (одно возвращение на один апдейт).
"""

from __future__ import annotations

import asyncio

import pytest

from bob.proactivity.usecases.announce_restart import (
    AnnounceRestart,
    RestartMarkerStore,
    RestartNotifier,
)


class _RecordingNotifier:
    """Фейк notifier: пишет, что и куда отправили (owner-DM + группа)."""

    def __init__(self) -> None:
        self.owner_lines: list[str] = []
        self.group_lines: list[str] = []

    async def notify_owner(self, text: str) -> None:
        self.owner_lines.append(text)

    async def notify_group(self, text: str) -> None:
        self.group_lines.append(text)


class _HangingNotifier:
    """Фейк notifier, который ВИСНЕТ (моделирует легшую сеть)."""

    def __init__(self) -> None:
        self.attempted = False

    async def notify_owner(self, text: str) -> None:  # noqa: ARG002
        self.attempted = True
        await asyncio.Event().wait()  # никогда не разрешится

    async def notify_group(self, text: str) -> None:  # noqa: ARG002
        await asyncio.Event().wait()


class _FakeMarkerStore:
    """Фейк маркер-стора поверх словаря kv (set / consume / epoch)."""

    def __init__(self, *, pending: str | None = None, epoch: int = 0) -> None:
        self._pending = pending
        self._epoch = epoch
        self.consumed = False

    async def mark_update_pending(self, marker: str) -> None:
        self._pending = marker

    async def consume_update_pending(self) -> str | None:
        marker = self._pending
        self._pending = None
        self.consumed = True
        return marker

    async def next_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    @property
    def pending(self) -> str | None:
        return self._pending


def _announcer(
    notifier: RestartNotifier, store: RestartMarkerStore, *, timeout: float = 5.0
) -> AnnounceRestart:
    return AnnounceRestart(notifier=notifier, marker_store=store, timeout_seconds=timeout)


# --- Уход на обновление -------------------------------------------------------


async def test_leaving_notifies_owner_and_group() -> None:
    notifier = _RecordingNotifier()
    store = _FakeMarkerStore()

    await _announcer(notifier, store).announce_leaving()

    assert len(notifier.owner_lines) == 1, "owner обязан получить предупреждение"
    assert len(notifier.group_lines) == 1, "группа обязана получить предупреждение"
    assert notifier.owner_lines[0].strip()
    assert notifier.group_lines[0].strip()


async def test_leaving_sets_the_update_pending_marker() -> None:
    notifier = _RecordingNotifier()
    store = _FakeMarkerStore()

    await _announcer(notifier, store).announce_leaving()

    assert store.pending is not None, "апдейт-остановка обязана оставить маркер в kv"


async def test_leaving_does_not_hang_when_the_network_is_down() -> None:
    # 🔴 Обманывающий саботаж-мишень: без таймаута зависший notifier подвесил бы
    # весь shutdown. Хук ОБЯЗАН вернуться быстро.
    notifier = _HangingNotifier()
    store = _FakeMarkerStore()
    announcer = _announcer(notifier, store, timeout=0.05)

    # Если announce_leaving не ограничен таймауту — этот wait_for сработает и тест
    # красный именно на «завис»; при исправном таймауте announce_leaving вернётся сам.
    await asyncio.wait_for(announcer.announce_leaving(), timeout=2.0)

    assert notifier.attempted, "попытка отправки всё же должна была стартовать"


async def test_leaving_still_sets_marker_even_if_send_times_out() -> None:
    # Маркер важнее реплики: даже когда сеть легла и реплика не ушла, следующий старт
    # должен знать, что это был АПДЕЙТ (иначе возвращение промолчит зря).
    notifier = _HangingNotifier()
    store = _FakeMarkerStore()

    await asyncio.wait_for(
        _announcer(notifier, store, timeout=0.05).announce_leaving(), timeout=2.0
    )

    assert store.pending is not None


# --- Возвращение после обновления ---------------------------------------------


async def test_returned_speaks_only_when_the_marker_is_present() -> None:
    notifier = _RecordingNotifier()
    store = _FakeMarkerStore(pending="epoch-3")

    await _announcer(notifier, store).announce_returned()

    assert len(notifier.owner_lines) == 1
    assert len(notifier.group_lines) == 1


async def test_returned_consumes_the_marker() -> None:
    notifier = _RecordingNotifier()
    store = _FakeMarkerStore(pending="epoch-3")

    await _announcer(notifier, store).announce_returned()

    assert store.consumed
    assert store.pending is None, "возвращение обязано СНЯТЬ маркер (одно на один апдейт)"


async def test_self_crash_does_not_pretend_it_was_an_update() -> None:
    # 🔴 Обманывающий саботаж-мишень: маркера нет (Боб упал сам) — он НЕ должен
    # говорить «вернулся, обновился», иначе притворился бы апдейтом.
    notifier = _RecordingNotifier()
    store = _FakeMarkerStore(pending=None)

    await _announcer(notifier, store).announce_returned()

    assert notifier.owner_lines == []
    assert notifier.group_lines == []


async def test_returned_is_silent_when_send_fails() -> None:
    # Возвращение best-effort: зависшая сеть не должна подвесить старт.
    notifier = _HangingNotifier()
    store = _FakeMarkerStore(pending="epoch-3")

    await asyncio.wait_for(
        _announcer(notifier, store, timeout=0.05).announce_returned(), timeout=2.0
    )
    # Маркер всё равно снят — иначе Боб пытался бы «вернуться» на каждом старте вечно.
    assert store.pending is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
