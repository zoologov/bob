# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Канон о голосе достаёт до КАЖДОЙ двери, пишущей в память (BOB-096, срез 3).

Дефект (bob-alr.12): запрет отыгрывать GUPPI был приклеен ровно к ОДНОЙ двери —
разговорному ходу. Рефлексия, переоценка, консолидация, проактивная реплика,
work_journal и ``extract_facts`` его не видели, их вывод ложился в память, а память
возвращается в ход припоминанием — Боб писал себе few-shot по нарушению канона и потом
добросовестно ему подражал (BOB-074). Живое: «GUPPI уже проверил все связи. Он ГОВОРИТ,
что стрелочки идут именно туда».

Здесь пинается ДОСЯГАЕМОСТЬ, двумя разными способами:

1. **По двери.** Каждая дверь из карты гоняется НАСТОЯЩИМ use-case'ом (``ReflectTick``,
   ``ReappraiseReflection``, ``ConsolidateMemory``, ``ExtractFacts``,
   ``Tier0WorkJournalDistiller``) через НАСТОЯЩИЙ :class:`LLMRouter`, снабжённый
   НАСТОЯЩИМ каноном персоны, а провайдер записывает то, что реально уехало модели.
   Фейк здесь ровно один — сеть.
2. **Архитектурно.** Список дверей стареет, поэтому его недостаточно: сканирование
   ``src/`` краснеет на новой двери, которая обошла шов — собрала себе роутер мимо
   композиционного корня, потеряла в корне сам канон или пошла к провайдеру напрямую.
   Образец конструкции — единственный обёрнутый порт памяти (BOB-090.B-fix2).

🔴 Автобиография (``memory/self_action.py``) — дверь БЕЗ модели: детерминированный
шаблон от первого лица. Канон достигается там конструкцией, и это тоже проверяется:
формулировки не отдают поступок никому, кроме самого Боба.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import ReflectTick
from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
from bob.memory.self_action import SelfAction, SelfActionKind, describe_self_action
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine
from bob.personality.usecases.reappraise_reflection import ReappraiseReflection
from bob.personality.voice import guppi_no_roleplay_directive, guppi_voice_canon
from bob.proactivity.usecases.engine import _COMPOSE_SYSTEM

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

_PROSE_CANON = guppi_voice_canon(prose_answer=True)
_MACHINE_CANON = guppi_voice_canon(prose_answer=False)
_MOMENT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


class RecordingProvider:
    """Единственный фейк: сеть. Пишет каждый payload и отвечает заготовкой."""

    def __init__(self, *, reply: str = "мысль") -> None:
        self._reply = reply
        self.payloads: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — часть протокола LLMProvider
    ) -> str | AsyncIterator[str]:
        self.payloads.append("\n".join(m.get("content", "") for m in messages))
        return self._reply


def _live_router(provider: RecordingProvider) -> LLMRouter:
    """Роутер, снабжённый каноном ровно так, как его снабжает композиционный корень."""
    return LLMRouter(providers={0: provider, 1: provider}, voice_canon=guppi_voice_canon)


def _said_to_the_model(provider: RecordingProvider) -> str:
    return "\n".join(provider.payloads)


class _FakeClock:
    def now(self) -> datetime:
        return _MOMENT


class _FakeEpisodes:
    """Пишущий seam эпизодов: рефлексия обязана куда-то лечь."""

    def __init__(self) -> None:
        self.saved: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.saved.append(episode)


class _FakeFacts:
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save_fact(self, fact: object) -> None:
        self.saved.append(fact)


class _FakeConsolidationStore:
    """Хранилище консолидации: отдаёт один старый эпизод и принимает дайджест."""

    def __init__(self) -> None:
        self.digests: list[Mapping[str, object]] = []

    async def select_consolidatable_episodes(
        self, *, older_than: datetime, limit: int
    ) -> Sequence[Mapping[str, object]]:
        del older_than, limit
        return [{"id": 1, "ts": "2026-01-01T00:00:00+00:00", "content": "мы чинили сборку"}]

    async def save_digest(self, digest: Mapping[str, object]) -> None:
        self.digests.append(digest)

    async def mark_consolidated(self, episode_ids: Sequence[int]) -> None:
        del episode_ids


def _soul() -> SOUL:
    return SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(),
        disposition=Disposition(optimism=0.8, resilience=0.7),
    )


# --- 1. По двери: настоящий use-case → настоящий роутер → записанный payload ----------


@pytest.mark.asyncio
async def test_the_reflection_door_carries_the_canon() -> None:
    # Главный источник отравления: рефлексии ложатся в episodic_log и всплывают в ходе.
    provider = RecordingProvider(reply="сегодня тише обычного")
    tick = ReflectTick(
        router=_live_router(provider),
        repo=_FakeEpisodes(),
        state=PersonalityState(soul=_soul()),
        clock=_FakeClock(),
    )

    await tick.run()

    assert _PROSE_CANON in _said_to_the_model(provider)


@pytest.mark.asyncio
async def test_the_reappraisal_door_carries_the_canon() -> None:
    # Переоценка ПЕРЕЗАПИСЫВАЕТ рефлексию — её текст ложится в память вместо исходного.
    provider = RecordingProvider(reply="negative")
    reappraiser = ReappraiseReflection(
        router=_live_router(provider),
        rng=Random(1),  # noqa: S311 — не крипто: сеяный жребий переоценки
        disposition=Disposition(optimism=1.0, resilience=1.0),
    )

    await reappraiser.run("всё разваливается")

    assert _PROSE_CANON in _said_to_the_model(provider)


@pytest.mark.asyncio
async def test_the_consolidation_door_carries_the_canon() -> None:
    # Дайджест — сжатое воспоминание от первого лица: канон нужен ему так же.
    provider = RecordingProvider(reply="я чинил сборку")
    store = _FakeConsolidationStore()
    consolidation = ConsolidateMemory(
        store=store, router=_live_router(provider), clock=_FakeClock()
    )

    await consolidation.run()

    assert store.digests, "дайджест не записан — прогон ничего не доказывает"
    assert _PROSE_CANON in _said_to_the_model(provider)


@pytest.mark.asyncio
async def test_the_work_journal_door_carries_the_canon() -> None:
    provider = RecordingProvider(reply="я поправил сборку")
    distiller = Tier0WorkJournalDistiller(router=_live_router(provider))

    await distiller.distill(
        "починить сборку",
        SessionKeyFacts(files=("app.py",), tests_passed=True),
        WorkOutcome.FINISHED,
    )

    assert _PROSE_CANON in _said_to_the_model(provider)


@pytest.mark.asyncio
async def test_the_fact_extraction_door_carries_the_canon_in_machine_form() -> None:
    # 🔴 Выжимка фактов отвечает JSON'ом и ложится в semantic_memory: канон обязан
    # доехать, но в форме, которая не зовёт в прозу и не ломает контракт ответа.
    provider = RecordingProvider(reply="[]")
    extract = ExtractFacts(
        router=_live_router(provider), repo=_FakeFacts(), clock=_FakeClock()
    )

    await extract.run(user_message="меня зовут Лиля", reply="приятно")

    payload = _said_to_the_model(provider)
    assert _MACHINE_CANON in payload
    assert _PROSE_CANON not in payload


@pytest.mark.asyncio
async def test_the_proactive_door_carries_the_canon() -> None:
    """Проактивная реплика ходит дверью разговорного хода, но своим мини-промптом.

    Её ``_COMPOSE_SYSTEM`` персоны не содержит — именно поэтому она годами уходила без
    канона. Здесь пинается сам факт: этот промпт, отправленный как ``REPLY_TO_USER``,
    возвращается модели уже с запретом.
    """
    assert _PROSE_CANON not in _COMPOSE_SYSTEM
    provider = RecordingProvider(reply="привет, вспомнил тебя")

    await _live_router(provider).run(
        LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[{"role": "system", "content": _COMPOSE_SYSTEM}],
        )
    )

    assert _PROSE_CANON in _said_to_the_model(provider)


def test_the_autobiography_door_is_closed_by_construction() -> None:
    # 🔴 Дверь БЕЗ модели: канон в неё не «досылается» — он выполнен конструкцией.
    # Каждая формулировка от первого лица и не отдаёт поступок никому другому.
    for kind in SelfActionKind:
        rendered = describe_self_action(SelfAction(kind=kind, target="сборка"))

        assert rendered.content.startswith("я ")
        assert "guppi" not in rendered.content.casefold()


# --- 2. Архитектурно: новая дверь не заведётся мимо шва --------------------------------


def _repo_src_root() -> Path:
    """Найти НАСТОЯЩЕЕ дерево исходников (не установленный пакет, не песочницу mutmut).

    Опознаётся по самому сканируемому файлу, поэтому найти не тот каталог нельзя, а не
    найти ни одного — ошибка, а не тихий пропуск (иначе гард был бы вакуумно зелёным).
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "src" / "bob"
        if (candidate / "runtime" / "composition.py").is_file():
            return candidate
    raise AssertionError("дерево исходников проекта не найдено — гард нечего сканировать")


_SRC_ROOT = _repo_src_root()
_COMPOSITION = "runtime/composition.py"
# Сколько символов после «LLMRouter(» считается телом вызова (аргументы корня + отступы).
_BUILD_SITE_WINDOW = 400

# Сборка роутера: у Боба она разрешена ровно в одном месте — композиционном корне.
_ROUTER_BUILD = re.compile(r"\bLLMRouter\s*\(")
# Прямой разговор с провайдером в обход роутера (и, значит, в обход канона). Разрешён
# самому роутеру и композиту-дублёру, который стоит ПОД тиром, а не рядом с ним.
_PROVIDER_CALL = re.compile(r"\.complete(?:_with_tools)?\s*\(")
_ALLOWED_PROVIDER_CALLERS = {
    "application/router/llm_router.py",
    "infrastructure/llm/fallback_provider.py",
    # Tool-loop разговорного хода: system-промпт ему даёт VoiceComposer, а он несёт
    # канон в базовой персоне дословно (BOB-090.D3) — дверь та же, не новая.
    "capabilities/usecases/tool_loop.py",
}


def _modules_matching(pattern: re.Pattern[str]) -> set[str]:
    return {
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }


def test_the_router_is_built_in_one_place_only() -> None:
    # Свой роутер = свой (пустой) канон: дверь такого модуля тихо выпала бы из-под
    # запрета. Здесь краснеет ровно в этот момент.
    assert _modules_matching(_ROUTER_BUILD) == {_COMPOSITION}


def test_that_single_build_site_hands_the_router_the_canon() -> None:
    # И ровно та единственная сборка снабжена каноном — иначе гард выше стерёг бы
    # пустое место, а шов остался бы неподключённым (см. композиционный корень).
    source = (_SRC_ROOT / _COMPOSITION).read_text(encoding="utf-8")

    build_site = source.split("LLMRouter(", 1)[1][:_BUILD_SITE_WINDOW]

    assert "voice_canon=" in build_site


def test_no_door_talks_to_a_provider_behind_the_routers_back() -> None:
    # Шов стоит в роутере, поэтому дверь, дошедшая до провайдера напрямую, канона не
    # увидит вовсе. Список исключений именной: неизвестный обходчик краснеет.
    assert _modules_matching(_PROVIDER_CALL) <= _ALLOWED_PROVIDER_CALLERS


def test_the_canon_text_stays_in_the_persona() -> None:
    # 🔴 Копипаста директивы по дверям — это ровно то, что уже сломалось. Текст запрета
    # живёт в ОДНОМ месте (персона), а двери получают его швом; вторая копия в дереве
    # означала бы, что канон снова начал разъезжаться.
    literal = guppi_no_roleplay_directive()[:60]
    carriers = {
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if literal in path.read_text(encoding="utf-8")
    }

    assert carriers <= {"personality/voice.py"}
