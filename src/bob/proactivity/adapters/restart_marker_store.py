# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=proactivity
# beadloom:layer=infrastructure

"""KvRestartMarkerStore — маркер апдейт-остановки в ``kv`` (BOB-094 срез 1).

Реализует :class:`~bob.proactivity.usecases.announce_restart.RestartMarkerStore` над
generic-таблицей ``kv`` (без новой схемы/миграции), тем же способом, что
:class:`~bob.personality.adapters.notable_reaction_store.KvNotableReactionStore`:

* ``mark_update_pending`` — shutdown-хук кладёт маркер: «прошлый выход — апдейт»;
* ``consume_update_pending`` — startup-хук читает-и-снимает его (маркер есть → это был
  апдейт; нет → Боб упал сам или это первый старт — «вернулся» он не скажет). Снятие
  через пустой tombstone, чтобы одно возвращение приходилось на один апдейт;
* ``next_epoch`` — персистентный растущий счётчик рестартов; им ядро голоса варьирует
  реплику от раза к разу без ``random``/времени. Битое/пустое значение деградирует к
  свежему счёту — уход на обновление не вправе упасть из-за нечитаемой строки.

Весь доступ идёт через параметризованные ``kv_set`` / ``kv_get`` репозитория — никаких
f-string SQL.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

# Ключи в generic ``kv``. Маркер апдейт-остановки и счётчик рестартов — независимы:
# первый снимается возвращением, второй только растёт.
_PENDING_KEY = "restart.pending_update"
_EPOCH_KEY = "restart.epoch"

# Tombstone снятого маркера: пустая строка читается как «маркера нет» (чистый консум),
# ровно как в :mod:`bob.personality.adapters.notable_reaction_store`.
_CLEARED = ""


class _KvStore(Protocol):
    """Узкий kv-шов, который нужен стору (реализует SqliteMemoryRepo)."""

    async def kv_set(self, key: str, value: str) -> None: ...

    async def kv_get(self, key: str) -> str | None: ...


class KvRestartMarkerStore:
    """SQLite ``kv``-backed маркер апдейт-остановки + счётчик рестартов (BOB-094)."""

    def __init__(self, repo: _KvStore) -> None:
        self._repo = repo

    async def mark_update_pending(self, marker: str) -> None:
        """Отметить, что этот выход — апдейт-остановка (shutdown-хук)."""
        await self._repo.kv_set(_PENDING_KEY, marker)

    async def consume_update_pending(self) -> str | None:
        """Прочитать-и-снять маркер: был ли прошлый выход апдейтом (startup-хук).

        Возвращает маркер, если он есть (тогда Боб говорит «вернулся, обновился»), и
        снимает его пустым tombstone, чтобы одно возвращение приходилось на один
        апдейт. Пустая строка / отсутствие ключа → ``None`` (падение или первый старт).
        """
        raw = await self._repo.kv_get(_PENDING_KEY)
        if not raw:
            return None
        await self._repo.kv_set(_PENDING_KEY, _CLEARED)
        return raw

    async def next_epoch(self) -> int:
        """Вернуть следующий (растущий) номер рестарта, персистентно (без random/времени).

        Считается по сохранённому значению; битое/пустое читается как 0, поэтому уход на
        обновление не падает из-за нечитаемой строки, а разнообразие реплик деградирует
        к свежему счёту.
        """
        current = _parse_epoch(await self._repo.kv_get(_EPOCH_KEY))
        nxt = current + 1
        await self._repo.kv_set(_EPOCH_KEY, str(nxt))
        return nxt


def _parse_epoch(raw: str | None) -> int:
    """Разобрать сохранённый epoch; нечитаемое/пустое → 0 (чистая деградация)."""
    if not raw:
        return 0
    try:
        return int(raw)
    except ValueError:
        logger.warning("ignoring an unreadable restart-epoch value")
        return 0
