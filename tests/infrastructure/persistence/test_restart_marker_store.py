# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for KvRestartMarkerStore — маркер апдейт-остановки в ``kv`` (BOB-094 срез 1).

Маркер живёт в generic ``kv`` (без новой схемы): shutdown-хук кладёт его при уходе на
обновление, startup-хук читает-и-снимает. Есть маркер → прошлый выход был апдейтом;
нет → Боб упал сам (или это первый старт) — и «вернулся, обновился» он не скажет.
``next_epoch`` — растущий счётчик рестартов, которым ядро голоса варьирует реплику.
"""

from __future__ import annotations

from bob.proactivity.adapters.restart_marker_store import KvRestartMarkerStore


class _FakeKv:
    """In-memory kv-заглушка под kv_set/kv_get репозитория."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def kv_set(self, key: str, value: str) -> None:
        self.data[key] = value

    async def kv_get(self, key: str) -> str | None:
        return self.data.get(key)


async def test_consume_is_none_when_no_update_pending() -> None:
    # Первый старт / падение: маркера нет → None (не притворяемся апдейтом).
    store = KvRestartMarkerStore(_FakeKv())
    assert await store.consume_update_pending() is None


async def test_mark_then_consume_returns_the_marker() -> None:
    store = KvRestartMarkerStore(_FakeKv())
    await store.mark_update_pending("leaving-7")
    assert await store.consume_update_pending() == "leaving-7"


async def test_consume_clears_the_marker() -> None:
    # Одно возвращение на один апдейт: после консума маркера больше нет.
    store = KvRestartMarkerStore(_FakeKv())
    await store.mark_update_pending("leaving-7")
    await store.consume_update_pending()
    assert await store.consume_update_pending() is None


async def test_next_epoch_grows_monotonically_across_calls() -> None:
    kv = _FakeKv()
    store = KvRestartMarkerStore(kv)
    first = await store.next_epoch()
    second = await store.next_epoch()
    assert second > first


async def test_next_epoch_survives_a_fresh_store_over_the_same_kv() -> None:
    # Epoch персистится в kv: новый объект стора поверх той же БД продолжает счёт
    # (перезапуск процесса не сбрасывает разнообразие реплик к одной и той же).
    kv = _FakeKv()
    await KvRestartMarkerStore(kv).next_epoch()
    resumed = await KvRestartMarkerStore(kv).next_epoch()
    assert resumed >= 2


async def test_unreadable_epoch_row_degrades_to_a_fresh_count() -> None:
    # Битое значение epoch не должно ронять уход на обновление — деградируем чисто.
    kv = _FakeKv()
    kv.data["restart.epoch"] = "не-число"
    store = KvRestartMarkerStore(kv)
    assert await store.next_epoch() >= 1
