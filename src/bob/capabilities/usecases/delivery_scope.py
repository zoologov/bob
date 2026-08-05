# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=capabilities
# beadloom:layer=application

"""DeliveryScope — обстоятельства ХОДА, в которых оценивается отправка (BOB-090.B1).

Отправить сообщение в другой чат — действие, которое зависит не от аргументов вызова, а
от того, ЧЕЙ это ход: кто просит, откуда он говорит и из какого материала собран ответ.
Реестр capability при этом общий и живёт всё время процесса, поэтому сам инструмент этих
фактов не знает и знать не может.

Этот модуль — шов между тем и другим:

* :class:`DeliveryScope` — неизменяемый снимок хода: owner ли просит, из какого чата,
  чего именно просил, что подняла память и в какой нити это сказано.
* :func:`armed_delivery_scope` — контекстный менеджер, которым ход «армируется»;
* :func:`current_delivery_scope` — то, что читает инструмент. ``None`` = хода нет.

🔴 Почему :class:`~contextvars.ContextVar`, а не общий мутабельный холдер: у Боба ходы
живут в разных задачах (реактивный ход, проактивный тик, догоняющий разбор), и общий
атрибут означал бы, что признак «просит owner» одного хода может достаться другому. Это
не гипотетика, а класс ошибки — а ``ContextVar`` копируется ПО ЗАДАЧЕ и не течёт между
ними. Умолчание ``None`` даёт главное свойство: **нет армированного хода — нет отправки**,
то есть инструмент структурно не может выстрелить сам по себе (урок BOB-076).
"""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = ["DeliveryScope", "armed_delivery_scope", "current_delivery_scope"]


@dataclass(frozen=True, slots=True)
class DeliveryScope:
    """Снимок хода, по которому решается, можно ли отправить сообщение вовне.

    ``from_owner`` — просит ли owner (только он вправе, BOB-076); ``here_chat_id`` — где
    идёт разговор (чтобы «отправить» в тот же чат распозналось структурно, а не по
    словам); ``request_text`` — сама просьба (её же оценивает гейт согласия);
    ``recalled`` — то, что подняла память: материал, который Боб ДОБАВЛЯЕТ от себя, и
    по нему считается перенос приватного (BOB-090.B4). ``recent_thread`` — лёгкий снимок
    нити, в которой прозвучала просьба: гейт согласия судит её В СИТУАЦИИ.

    🔴 Видимости самого хода здесь нет намеренно (BOB-090.B-fix): ход в личке помечен
    ``owner_private`` целиком, поэтому «место разговора» как признак переноса зажигало
    гейт на каждой отправке и Боб отказывал owner'у в прямом распоряжении. Поле было
    ровно этим триггером и уехало вместе с ним — мёртвого признака в снимке не осталось.
    """

    from_owner: bool
    here_chat_id: int
    request_text: str
    recalled: tuple[Mapping[str, object], ...] = ()
    recent_thread: str = ""


_CURRENT: ContextVar[DeliveryScope | None] = ContextVar(
    "bob_delivery_scope", default=None
)


def current_delivery_scope() -> DeliveryScope | None:
    """Ход, армированный ЗДЕСЬ и СЕЙЧАС, или ``None``, если хода нет."""
    return _CURRENT.get()


@contextlib.contextmanager
def armed_delivery_scope(scope: DeliveryScope) -> Iterator[None]:
    """Армировать ход на время блока и снять армирование на выходе.

    Снимает всегда — в том числе когда генерация упала: «висящий» ход означал бы, что
    инструмент остаётся заряженным чужими обстоятельствами.
    """
    token = _CURRENT.set(scope)
    try:
        yield
    finally:
        _CURRENT.reset(token)
