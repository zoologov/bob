# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=coding
# beadloom:layer=application

"""Дистиллятор рабочего журнала (Tier-0) — арка сессии → операторские эпизоды (BOB-087.B1).

Берёт ОГРАНИЧЕННЫЕ ключевые факты сессии (:class:`~bob.coding.work_facts.SessionKeyFacts`)
+ исход и сводит их в НЕСКОЛЬКО (1-3) ДЕТАЛЬНЫХ первого-лица «операторских» эпизода
(«я попросил GUPPI починить краш стрима в interactive_runner.py; тесты падали на >64 КБ;
подняли лимит буфера — позеленело»): конкретика (файлы/тесты/что-сломалось/фикс), первое
лицо, операторская рамка — НЕ generic («починили что-то»), НЕ сырой лог.

Зеркалит :class:`~bob.coding.usecases.classify_coding_intent.ClassifyCodingIntent`: один
дешёвый Tier-0 вызов (``TaskType.WORK_JOURNAL``, приватность → локально), результат
разбирается КОНСЕРВАТИВНО. Чистый строитель промпта + чистый парсер
:func:`parse_work_episodes` (mutation-цель); сам LLM-вызов — адаптер. Best-effort: сбой
модели → ноль эпизодов (никогда не бросает в сессию).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Protocol

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.memory.work_journal import WorkEpisode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.application.router.llm_router import LLMRouter
    from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
    from bob.kernel.ports import LLMMessage

logger = logging.getLogger(__name__)

__all__ = [
    "Tier0WorkJournalDistiller",
    "WorkJournalDistiller",
    "parse_work_episodes",
]

# Bob writes a FEW detailed episodes, not a wall of text (anti-flood, lesson BOB-076).
_MAX_EPISODES = 3

# Leading list markers the model may prepend to each line ("- ", "* ", "• ", "1. ", "2) ").
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")

# Human phrasing of the session outcome, folded into the distiller prompt.
_OUTCOME_RU = {
    "finished": "довёл до конца, открыл PR",
    "failed": "сессия упала",
    "aborted": "прервал на полпути",
}

_SYSTEM_PROMPT = (
    "Ты — Боб, живой инженер. По фактам dev-сессии напиши от ПЕРВОГО ЛИЦА 1-3 КОРОТКИХ "
    "детальных воспоминания о том, что ты сейчас сделал — так, как человек помнит свою "
    "работу: конкретные файлы, какие тесты падали/зеленели, что сломалось и как починили. "
    "Ты — ОПЕРАТОР: фактическую работу делает GUPPI по твоим директивам, пиши «я попросил "
    "GUPPI…», «GUPPI сделал…». Каждое воспоминание — одной строкой, начинай с «я». Пиши "
    "по-русски, конкретно (не «починил что-то»). Только строки-воспоминания, без преамбул."
)


class WorkJournalDistiller(Protocol):
    """Порт дистилляции: факты сессии + исход → несколько операторских эпизодов.

    Реализуется Tier-0-адаптером (:class:`Tier0WorkJournalDistiller`). Best-effort:
    реализация НЕ бросает — сбой модели деградирует к пустой последовательности.
    """

    async def distill(
        self, task: str, facts: SessionKeyFacts, outcome: WorkOutcome
    ) -> Sequence[WorkEpisode]:
        """Свести факты сессии в 1-3 первого-лица эпизода (или пусто при сбое)."""
        ...


def parse_work_episodes(text: str) -> tuple[WorkEpisode, ...]:
    """Разобрать ответ модели в 1-3 первого-лица эпизода (чистый парсер, mutation-цель).

    Каждая непустая строка (со снятым list-маркером) → один :class:`WorkEpisode`; пустые
    строки отбрасываются, кэп ``_MAX_EPISODES``. Пустой/мусорный ответ → пустой кортеж
    (best-effort: лучше ничего, чем шум).
    """
    episodes: list[WorkEpisode] = []
    for raw in text.splitlines():
        line = _BULLET.sub("", raw).strip()
        if not line:
            continue
        episodes.append(WorkEpisode(content=line))
        if len(episodes) >= _MAX_EPISODES:
            break
    return tuple(episodes)


def build_work_journal_messages(
    task: str, facts: SessionKeyFacts, outcome: WorkOutcome
) -> list[LLMMessage]:
    """Собрать сообщения Tier-0 запроса: system-инструкция + дайджест фактов (чистый)."""
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _facts_digest(task, facts, outcome)},
    ]


def _facts_digest(task: str, facts: SessionKeyFacts, outcome: WorkOutcome) -> str:
    """Человекочитаемый дайджест фактов сессии для промпта (чистый)."""
    lines = [f"Задача: {task}", f"Итог: {_OUTCOME_RU.get(outcome.value, outcome.value)}"]
    if facts.files:
        lines.append(f"Тронутые файлы: {', '.join(facts.files)}")
    if facts.tests_passed:
        lines.append("Тесты: проходили")
    if facts.tests_failed:
        lines.append("Тесты: были падения")
    if facts.errors:
        lines.append("Что ломалось: " + "; ".join(facts.errors))
    return "\n".join(lines)


class Tier0WorkJournalDistiller:
    """Дистиллятор через один дешёвый Tier-0 вызов (зеркало ClassifyCodingIntent)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def distill(
        self, task: str, facts: SessionKeyFacts, outcome: WorkOutcome
    ) -> tuple[WorkEpisode, ...]:
        """Свести факты сессии в 1-3 первого-лица эпизода (сбой модели → пусто)."""
        try:
            answer = await self._router.run(self._request(task, facts, outcome))
        except Exception:
            logger.exception("work-journal distillation failed (yielding no episodes)")
            return ()
        return parse_work_episodes(answer)

    @staticmethod
    def _request(task: str, facts: SessionKeyFacts, outcome: WorkOutcome) -> LLMRequest:
        """Построить Tier-0 запрос дистилляции (локальный — приватность dev-работы)."""
        return LLMRequest(
            task_type=TaskType.WORK_JOURNAL,
            messages=build_work_journal_messages(task, facts, outcome),
        )
