# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=interactive
# beadloom:layer=domain

"""Живой интерактивный терминал — «Боб держит запущенный claude, owner им правит».

Второй bounded context поверх общей поверхности coding-сессии (BOB-087.E, bob-6u2).
Отличие от гейтед-кодера (:mod:`bob.coding`) — не в масштабе, а в СУТИ взаимодействия:

* гейтед-кодер — ЭФЕМЕРНЫЙ прогон по протоколу «план → апрув → PR»: Боб уходит
  работать, возвращается с результатом, owner решает на двух гейтах;
* живой терминал — ДОЛГОЖИВУЩИЙ процесс с открытым stdin: owner сидит за клавиатурой
  в личке и правит ``claude`` в реальном времени, а Боб — оператор этого сеанса
  (открыть / направить реплику / поднять приостановленную работу / оборвать).

Отсюда и разный словарь (сеанс/реплика/возобновление против плана/апрува/PR), и разные
инварианты (одна живая сессия за раз, никакого live-attach, прямой kill вместо
кооперативного break), и разный голос. Общее — рабочее место и запись о сессии:
:mod:`bob.coding.ports`, :mod:`bob.coding.entities`, :mod:`bob.coding.state`,
:mod:`bob.coding.naming`, :mod:`bob.coding.sandbox_policy`, :mod:`bob.coding.push_guard`,
:mod:`bob.coding.stream_json` — их этот модуль ИСПОЛЬЗУЕТ (ребро interactive → coding,
одностороннее: coding о живом терминале не знает ничего).

Чистый домен здесь: разбор команд режима (:mod:`bob.interactive.intent`), политика
возобновления (:mod:`bob.interactive.resume_policy`), переговоры о подъёме
(:mod:`bob.interactive.resume_negotiation`), argv живого спавна
(:mod:`bob.interactive.argv_policy`), голос режима (:mod:`bob.interactive.voice`) и
держатель живого сеанса (:mod:`bob.interactive.entities`). Оркестрация — в
``usecases/``, транспорт ``claude`` — в ``adapters/``.
"""

from __future__ import annotations

from bob.interactive.entities import LiveSession
from bob.interactive.resume_policy import is_confirmation_fresh, select_resumable

__all__ = ["LiveSession", "is_confirmation_fresh", "select_resumable"]
