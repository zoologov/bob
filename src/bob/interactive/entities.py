# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""Держатель ОДНОГО живого сеанса — что именно сейчас запущено (BOB-083 .3).

``LiveSession`` связывает три вещи, которые в живом режиме нельзя разлучать:
персистнутую запись сессии (:class:`~bob.coding.entities.CodingSession`), её раннер
(:class:`~bob.coding.ports.InteractiveRunner`) и судьбу рабочего дерева. Пока объект
существует — сеанс жив; он же передаётся тому, кто сеанс завершает.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.coding.entities import CodingSession
    from bob.coding.ports import InteractiveRunner

__all__ = ["LiveSession"]


@dataclass(slots=True)
class LiveSession:
    """Держатель живого сеанса: персистнутая сессия, её раннер и судьба рабочего дерева.

    ``persistent`` — 🔴 маркер «это ДОЛГОЖИВУЩИЙ workspace, его дерево не удалять»:
    ``open`` заводит эфемерный посессионный worktree (убирается на ``stop``), а
    ``open_workspace`` / ``resume`` работают в накопленном workspace, который переживает
    остановку. Маркер держится в памяти рядом с живым сеансом, а не выводится из имени
    ветки (эфемерная задача,
    названная «epic …», дала бы ту же форму ``bob/epic-…``) и не требует новой колонки в
    БД: судьба дерева нужна ровно тому сеансу, который сейчас жив в этом процессе.
    """

    session: CodingSession
    runner: InteractiveRunner
    persistent: bool = False
