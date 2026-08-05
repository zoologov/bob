# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""TurnMaterial — единый СЛЕД материала, попавшего в контекст хода (BOB-090.B-fix2).

Гейт переноса (:func:`~bob.social.disclosure.transfer_needs_consent`) обещает считать
перенос **по материалу**. Обещание было неверным: гейт читал ОДНУ дверь — авто-recall,
снятый до генерации, — а материал, который Боб добавляет от себя, приходит к модели ещё
как минимум тремя: выдачей ``search_memory`` / ``recall_memory`` в том же tool-loop,
grounded-addon callback'ом и реплеем нити. Живой вызов реальной capability показал ровно
это: при пустом ``recalled`` приватное содержание уехало в комнату без вопроса.

Здесь живёт лечение — не четвёртая проверка, а ОДИН след:

* :class:`MaterialOrigin` — ДВЕРЬ, которой материал вошёл в ход;
* :class:`TurnMaterial` — сам след: набор меток «дверь + видимость», без содержимого;
* :class:`MaterialTrailRecall` — декоратор порта памяти, который наполняет след;
* :func:`armed_turn_material` / :func:`current_turn_material` — армирование хода и чтение.

🔴 Почему новая дверь не сможет добавиться МОЛЧА — два независимых механизма:

1. **Дверь к памяти ровно одна.** Стоячая память Боба выходит наружу единственным портом
   :class:`~bob.memory.ports.MemoryRecall`, и :class:`MaterialTrailRecall` оборачивает его
   в ЕДИНСТВЕННОМ месте сборки (композиционный корень). Любой будущий потребитель порта —
   ещё один инструмент, ещё один addon, проактивный шов — попадает в след сам собой, без
   строчки учёта у себя. Архитектурный тест стережёт, что источник порта конструируется
   только там (``tests/capabilities/test_turn_material.py``).
2. **Дверь НЕ к памяти обязана назваться.** Она добавляет значение в :class:`MaterialOrigin`,
   а политика переноса перечисляет ИСКЛЮЧЕНИЯ (:data:`_NOT_A_TRANSFER`) — значит незнакомая
   дверь считается переносимым материалом по умолчанию (fail-closed, INV-8), а не выпадает
   из гейта.

🔴 Что в след НЕ кладётся: содержимое. Вопрос, на который след отвечает, — «нёс ли этот ход
приватный материал и какой дверью», поэтому хранятся только метки. След от этого ограничен
по размеру (число дверей × число видимостей) и не держит переписку в
:class:`~contextvars.ContextVar`.

🔴 Надмножество, а не точный слепок: порт отмечается тем, что ПОДНЯЛА память, ещё до того
как ход отфильтрует выборку под аудиторию и обрежет по ``k``. Гейт от этого консервативен —
он может спросить согласие о материале, который до промпта не доехал. Это осознанная
сторона ошибки: лишний вопрос владелец видит и отвечает «да», а тихий пропуск — нет.
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from bob.social.disclosure import VISIBILITY_OWNER_PRIVATE, visibility_of

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

    from bob.memory.ports import MemoryRecall, Recalled

__all__ = [
    "MaterialOrigin",
    "MaterialTrailRecall",
    "TurnMaterial",
    "armed_turn_material",
    "current_turn_material",
]


class MaterialOrigin(Enum):
    """Дверь, которой материал вошёл в контекст хода.

    ``MEMORY`` — всё, что подняла ПАМЯТЬ Боба, какой бы дверью его ни достали: авто-recall
    хода, выдача ``recall_memory`` / ``search_memory``, grounded-addon callback. Все они
    ходят одним портом, поэтому дверь у них одна и на уровне политики: приватное здесь —
    это то, что Боб ДОБАВЛЯЕТ от себя.

    ``LIVE_THREAD`` — живой разговор, в котором звучит сама просьба (нить + текст хода).
    """

    MEMORY = "memory"
    LIVE_THREAD = "live_thread"


# 🔴 Двери, материал которых переносом НЕ считается — исключение названо, а не забыто.
#
# Живая нить — это разговор, в котором owner и отдаёт распоряжение: он ему сторона, он же
# его и адресует. Решение owner'а (B-fix): прямая команда — волеизъявление, согласие
# содержится в самой команде, и переспрашивать «а можно?» на «напиши в группу, что я
# закончил обзор» — это бот, а не Боб. Ход в личке помечен приватным ЦЕЛИКОМ, поэтому
# считать нить переносом = зажигать гейт на КАЖДОЙ отправке из лички, то есть ровно тот
# дефект, который B-fix убрал.
#
# 🔴 Остаточный риск назван прямо (ревью bob-alr.8): в нити могут быть СОБСТВЕННЫЕ прошлые
# реплики Боба, а в них — то, что ему рассказал третий человек. Гейтом это не ловится (для
# гейта нить неотличима от слов самого владельца), и owner решил, что ловить не нужно: в
# комнату это выносит он сам, своей командой и под своим именем. Список — единственное
# место, где такое исключение вообще может появиться.
_NOT_A_TRANSFER = frozenset({MaterialOrigin.LIVE_THREAD})


@dataclass(frozen=True, slots=True)
class _MaterialNote:
    """Одна метка следа: чем материал вошёл и какой у него признак приватности."""

    origin: MaterialOrigin
    visibility: str | None


class TurnMaterial:
    """Что попало в контекст ЭТОГО хода — метками «дверь + видимость», без содержимого.

    Мутабелен намеренно: ход армируется ОДНИМ объектом, и все двери дописывают в него по
    ссылке — в том числе из задач, которым :class:`~contextvars.ContextVar` достался
    копией контекста (копируется ссылка, а объект остаётся тем же).
    """

    __slots__ = ("_notes",)

    def __init__(self, notes: Sequence[_MaterialNote] = ()) -> None:
        self._notes: set[_MaterialNote] = set(notes)

    def note(
        self, items: Sequence[Mapping[str, object]], *, origin: MaterialOrigin
    ) -> None:
        """Отметить материал, вошедший дверью ``origin`` (читается ``visibility``)."""
        for item in items:
            self._notes.add(_MaterialNote(origin, visibility_of(item)))

    def note_visibility(
        self, visibility: str | None, *, origin: MaterialOrigin
    ) -> None:
        """Отметить материал одной готовой меткой видимости (у нити своего поля нет)."""
        self._notes.add(_MaterialNote(origin, visibility))

    def transferable(self) -> tuple[Mapping[str, object], ...]:
        """Материал следа, который МОЖЕТ быть переносом, — как его читает гейт.

        Отдаётся в том же виде, в каком гейт читает припомненное (``{"visibility": …}``),
        чтобы «приватное» осталось ОДНИМ определением
        (:func:`~bob.social.disclosure.carries_owner_private`), а не завелось вторым.
        Двери-исключения (:data:`_NOT_A_TRANSFER`) сюда не попадают.
        """
        return tuple(
            {"visibility": note.visibility}
            for note in self._notes
            if note.origin not in _NOT_A_TRANSFER
        )

    @property
    def origins(self) -> frozenset[MaterialOrigin]:
        """Двери, которыми в этот ход вообще что-то вошло (для диагностики и тестов)."""
        return frozenset(note.origin for note in self._notes)

    @classmethod
    def unknown(cls) -> TurnMaterial:
        """След неармированного хода: «материал мог быть приватным» (fail-closed).

        Сомнение удерживает, а не выпускает (INV-8): если следа нет, отправка обязана
        спросить согласие. Тихий пропуск был бы дырой ровно того класса, ради которого
        след и заведён; лишний вопрос владелец видит и снимает одним «да».
        """
        return cls((_MaterialNote(MaterialOrigin.MEMORY, VISIBILITY_OWNER_PRIVATE),))


_CURRENT: ContextVar[TurnMaterial | None] = ContextVar(
    "bob_turn_material", default=None
)


def current_turn_material() -> TurnMaterial:
    """След ЭТОГО хода — или консервативный «материал неизвестен», если хода нет."""
    trail = _CURRENT.get()
    return trail if trail is not None else TurnMaterial.unknown()


@contextlib.contextmanager
def armed_turn_material() -> Iterator[TurnMaterial]:
    """Армировать след на весь ход и снять армирование на выходе (в том числе при сбое).

    Армируется РАНЬШЕ авто-recall — иначе первая же дверь прошла бы мимо следа, и гейт
    вернулся бы к тому, с чего начинали.
    """
    trail = TurnMaterial()
    token = _CURRENT.set(trail)
    try:
        yield trail
    finally:
        _CURRENT.reset(token)


class MaterialTrailRecall:
    """Порт памяти, который отмечает в следе хода ВСЁ, что он поднял (BOB-090.B-fix2).

    Тот же приём, которым :class:`~bob.memory.adapters.casual_floor_recall.CasualFloorRecall`
    закрыл вторичные двери для register-фильтра: не учёт в каждой двери по отдельности, а
    один декоратор на месте сборки порта — и двери закрыты ПО ПОСТРОЕНИЮ. Контракт порта не
    меняется ни на байт: выдача возвращается как есть, вне армированного хода писать
    некуда и декоратор просто прозрачен.
    """

    __slots__ = ("_inner",)

    def __init__(self, inner: MemoryRecall) -> None:
        self._inner = inner

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        """Поднять память и отметить поднятое в следе хода (вне хода — просто поднять)."""
        hits = await self._inner.recall(query, k=k, surface_old=surface_old)
        trail = _CURRENT.get()
        if trail is not None:
            trail.note(hits, origin=MaterialOrigin.MEMORY)
        return hits
