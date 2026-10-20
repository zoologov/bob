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
   композиционного корня, потеряла в корне сам канон, пошла к провайдеру со своим
   заданием или подняла тул-луп, не назвав ему канон. Образец конструкции — единственный
   обёрнутый порт памяти (BOB-090.B-fix2).

🔴 **Гарды ловят СВОЙСТВО, а не имя** (BOB-096.8). Прошлая редакция держала именной
allowlist модулей, которым разрешено звать провайдера, и была зелёной ровно на том обходе,
ради которого писалась: ``tool_loop.py`` стоял в списке с обоснованием, верным только для
одного из двух его вызывающих, а второй — привилегированное исполнение — уходил к модели
без канона (ревью MAJOR-1). Ещё один гард сторожит РАЗМЕТКУ дверей: у служебной двери
появился новый вызывающий — сверь, куда девается вывод (так и нашлось, что «внутренний
монолог» сохраняет тему увлечения в SQLite, ревью MAJOR-2).

🔴 **Но свойство здесь проверяется ТЕКСТОМ ИСХОДНИКА — то есть формой, а не фактом**
(BOB-096.10, ревью MAJOR-5). Гарды провязки видят подстроку ``voice_canon=`` рядом со
сборкой; значение не смотрит никто, а ``None`` — легальное значение типа. Замена канона на
``None`` в композиционном корне выключала шов на десятке дверей при 7586 зелёных тестах —
починка сломанного тем же способом, каким оно было сломано. Поэтому ФАКТ («канон реально
уехал провайдеру») стережёт отдельный поведенческий тест над СОБРАННОЙ проводкой:
``tests/runtime/test_composed_wiring_carries_the_canon.py``. Файл ниже — дешёвый ранний
сигнал и карта дверей, а не последняя линия.

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
from bob.application.usecases.heartbeat import ReflectTick
from bob.application.usecases.privileged_fulfiller import PrivilegedRequestFulfiller
from bob.capabilities.usecases.registry import CapabilityRegistry
from bob.capabilities.usecases.tool_loop import ToolLoop
from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
from bob.kernel.ports import ToolCallResult
from bob.memory.self_action import SelfAction, SelfActionKind, describe_self_action
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.personality.adapters.reaction_judge import LlmReactionJudge
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.reaction_meaning import ReactionContext
from bob.personality.soul import SOUL
from bob.personality.state import PersonalityState
from bob.personality.taste import TasteEngine
from bob.personality.usecases.evolve_fascination import EvolveFascination
from bob.personality.usecases.reappraise_reflection import ReappraiseReflection
from bob.personality.usecases.voice_composer import _SYSTEM_PROMPT as _PERSONA_SYSTEM_PROMPT
from bob.personality.voice import guppi_no_roleplay_directive, guppi_voice_canon
from bob.proactivity.usecases.engine import _COMPOSE_SYSTEM
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.capabilities.ports import Permission
    from bob.kernel.ports import ToolDefinition, ToolLoopMessage
    from bob.personality.fascination import Fascination

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


class _RecordingToolProvider:
    """Единственный фейк для тул-лупа: сеть. Отвечает финальным текстом, без вызовов."""

    def __init__(self, *, reply: str = "готово") -> None:
        self._reply = reply
        self.payloads: list[str] = []

    async def complete_with_tools(
        self, messages: Sequence[ToolLoopMessage], *, tools: Sequence[ToolDefinition]
    ) -> ToolCallResult:
        del tools
        self.payloads.append("\n".join(str(m.get("content", "")) for m in messages))
        return ToolCallResult(text=self._reply)

    @property
    def payload(self) -> str:
        return "\n".join(self.payloads)


class _Diagram:
    """Минимальная способность: реестр обязан быть непустым, иначе тул-луп не поедет."""

    name = "render_diagram"
    description = "render a mermaid diagram"
    input_schema: Mapping[str, object] = {}
    permission: Permission = "safe"

    async def execute(self, args: Mapping[str, object]) -> object:
        del args
        return "ok"


class _FakeFascinationStore:
    """Пишущий seam увлечений: тема обязана куда-то лечь, иначе прогон вакуумный."""

    def __init__(self) -> None:
        self.saved: list[Fascination] = []

    async def load(self, persona_id: str) -> Fascination | None:
        del persona_id
        return None

    async def save(self, persona_id: str, fascination: Fascination) -> None:
        del persona_id
        self.saved.append(fascination)


class _FakeGrounding:
    """Настоящий материал, из которого Боб выбирает увлечение: своя мысль и свои вкусы."""

    async def latest_reflection_text(self) -> str | None:
        return "думал об орбитах"

    def strong_taste_topics(self) -> tuple[str, ...]:
        return ("звёзды",)


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


@pytest.mark.asyncio
async def test_the_privileged_fulfilment_door_carries_the_canon() -> None:
    """🔴 Восьмая дверь: исполнение по разрешению владельца идёт ТУЛ-ЛУПОМ, не роутером.

    Ревью BOB-096 (bob-q3k.7, MAJOR-1) распечатало настоящий payload этого хода: канона в
    нём не было ВОВСЕ, при том что промпт двери прямо велит «You are Bob… Answer them
    directly, in character» и ход умеет ходить инструментами. Гард молчал, потому что
    именовал МОДУЛЬ ``tool_loop.py``, а обоснование было верно лишь для второго его
    вызывающего (разговорный ход, где канон приносит персона).

    Здесь пинается наблюдаемое: то, что реально уехало модели через настоящий
    :class:`ToolLoop`. Фейк ровно один — сеть.
    """
    provider = _RecordingToolProvider(reply="вот задачи: A, B, C")
    registry = CapabilityRegistry()
    registry.register(_Diagram())
    fulfiller = PrivilegedRequestFulfiller(
        router=_live_router(RecordingProvider()),
        registry=registry,
        tool_provider=provider,
        voice_canon=guppi_voice_canon,
    )

    reply = await fulfiller.fulfil("покажи задачи", requester_id=7, requester_name="Лиля")

    assert reply == "вот задачи: A, B, C", "ход не состоялся — прогон ничего не доказывает"
    assert _PROSE_CANON in provider.payload


@pytest.mark.asyncio
async def test_the_fascination_door_carries_the_canon_in_machine_form() -> None:
    """🔴 Девятая дверь: выбор увлечения (ревью MAJOR-2 — разметка по неверному факту).

    Ходила «внутренним монологом», то есть служебной дверью, и канона не получала вовсе,
    хотя ответ модели становится темой в SQLite и неделями вплетается в реплики Боба. Тема
    вида «упрямство GUPPI» жила бы месяц и возвращалась припоминанием — ровно механизм
    BOB-074. Ответ разбирает код (первая строка), поэтому форма запрета машинная.
    """
    provider = RecordingProvider(reply="орбитальная механика")
    store = _FakeFascinationStore()
    evolve = EvolveFascination(
        persona_id="bob",
        store=store,
        router=_live_router(provider),
        grounding=_FakeGrounding(),
        clock=_FakeClock(),
    )

    await evolve.run()

    assert store.saved, "увлечение не сохранено — прогон ничего не доказывает"
    payload = _said_to_the_model(provider)
    assert _MACHINE_CANON in payload
    assert _PROSE_CANON not in payload


@pytest.mark.asyncio
async def test_the_reaction_reading_door_carries_the_canon_in_machine_form() -> None:
    # 🔴 Десятая дверь, найденная той же сверкой: прочтение реакции ложится в эпизод
    # «X отреагировал 👍 на моё «…» — <прочтение>» и в стор заметных реакций, откуда
    # возвращается припоминанием. Ответ — размеченные строки, значит машинная форма.
    provider = RecordingProvider(
        reply="interpretation: он обрадовался\nsentiment: warm\nintensity: mild\nacknowledge: no"
    )

    meaning = await LlmReactionJudge(router=_live_router(provider)).interpret(
        ReactionContext(
            emoji=("❤",),
            added=True,
            bob_message_text="я правда рад, что ты написал",
            reactor=Interlocutor(
                sender_id=1,
                display_name="Лиля",
                kind=InterlocutorKind.KNOWN,
                trust=Trust.TRUSTED,
            ),
            reactor_warmth=0.3,
            recent_thread="Лиля: привет\nbob: привет!",
        )
    )

    assert meaning.interpretation, "прочтение не разобрано — прогон ничего не доказывает"
    payload = _said_to_the_model(provider)
    assert _MACHINE_CANON in payload
    assert _PROSE_CANON not in payload


@pytest.mark.asyncio
async def test_the_conversational_tool_loop_gets_no_second_copy_of_the_canon() -> None:
    # Обратная сторона шва на второй точке прохода: разговорный ход уже несёт запрет
    # ДОСЛОВНО (он в базовой персоне, ``_SYSTEM_PROMPT``), поэтому подключённый канон
    # обязан оставить его payload байт-в-байт. Иначе «дотягивание» стало бы удвоением.
    assert _PROSE_CANON in _PERSONA_SYSTEM_PROMPT, "персона потеряла запрет — тест вакуумный"
    provider = _RecordingToolProvider(reply="готово")
    registry = CapabilityRegistry()
    registry.register(_Diagram())
    payload: list[ToolLoopMessage] = [
        {"role": "system", "content": _PERSONA_SYSTEM_PROMPT},
        {"role": "user", "content": "нарисуй схему"},
    ]

    await ToolLoop(
        provider=provider, registry=registry, voice_canon=guppi_voice_canon
    ).run(payload)

    assert provider.payload.count(_PROSE_CANON) == 1


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
# Прямой разговор с провайдером — то есть точка, где payload УХОДИТ модели.
_PROVIDER_CALL = re.compile(r"\.complete(?:_with_tools)?\s*\(")
# Модуль СОЧИНЯЕТ содержимое задания сам (строит хотя бы одно сообщение payload'а).
_AUTHORS_PROMPT = re.compile(r"""["']role["']\s*:""")
# Модуль применяет шов канона к тому, что отправляет.
_FOLDS_THE_CANON = re.compile(r"\bfold_voice_canon\s*\(")
# Сборка тул-лупа: вторая точка прохода payload'а, поэтому канон обязан приехать и сюда.
_TOOL_LOOP_BUILD = re.compile(r"\bToolLoop\s*\(")


def _modules_matching(pattern: re.Pattern[str]) -> set[str]:
    return {
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    }


def _sources() -> dict[str, str]:
    return {
        path.relative_to(_SRC_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in _SRC_ROOT.rglob("*.py")
    }


def test_the_router_is_built_in_one_place_only() -> None:
    # Свой роутер = свой (пустой) канон: дверь такого модуля тихо выпала бы из-под
    # запрета. Здесь краснеет ровно в этот момент.
    assert _modules_matching(_ROUTER_BUILD) == {_COMPOSITION}


def test_that_single_build_site_hands_the_router_the_canon() -> None:
    """🔴 Ловит ФОРМУ (написан ли аргумент), а НЕ ФАКТ (передан ли канон) — BOB-096.10.

    Дешёвый ранний сигнал, и только: гард читает исходник и видит подстроку
    ``voice_canon=``, а ``None`` — легальное значение типа ``VoiceCanon | None``. Ревьюер
    заменил канон на ``None`` в композиционном корне и получил 7586 passed: шов был
    выключен на десятке дверей, гард — зелёный. Это тот же класс, которым прошёл сам обход
    MAJOR-1 (проверялось написание, а не поведение), поэтому ЗАЩИТА ТЕПЕРЬ НЕ ЗДЕСЬ: факт
    стережёт поведенческий тест над собранной проводкой —
    ``tests/runtime/test_composed_wiring_carries_the_canon.py``. Здесь остаётся ранняя,
    быстрая и понятная проверка «сборка вообще знает про аргумент».
    """
    source = (_SRC_ROOT / _COMPOSITION).read_text(encoding="utf-8")

    # Без этой строки обход (сборка под другим именем — саботаж D третьего прохода) падал бы
    # ``IndexError`` из ``split``, и легитимный промах гарда читался бы как поломка теста.
    # §0.3 п.5 требует отличать ERROR от FAILED — здесь это стоит одной строки.
    assert "LLMRouter(" in source, f"сборка роутера в {_COMPOSITION} не найдена — гард слеп"
    build_site = source.split("LLMRouter(", 1)[1][:_BUILD_SITE_WINDOW]

    assert "voice_canon=" in build_site


def test_a_door_that_reaches_a_provider_folds_the_canon_into_what_it_sends() -> None:
    """🔴 Гард ловит СВОЙСТВО, а не имя модуля (BOB-096.8, review MAJOR-1).

    Прошлая редакция держала именной allowlist модулей, которым разрешено звать провайдера,
    и ``capabilities/usecases/tool_loop.py`` стоял в нём с обоснованием, верным лишь для
    ОДНОГО из двух его вызывающих. Второй — привилегированное исполнение — собирал свой
    промпт и уходил к модели вообще без канона, а гард был зелёным, потому что проверял
    ИМЯ. Имя не свойство: следующий обходчик прошёл бы так же.

    Свойство, которое проверяется теперь: модуль, у которого payload УХОДИТ провайдеру и
    который САМ сочиняет содержимое задания, обязан применить шов канона к тому, что
    отправляет. Единственное освобождение — тоже по свойству, а не по имени: сквозной
    композит (дублёр под тиром) не сочиняет ни одного сообщения, он пересылает payload,
    который шов уже прошёл этажом выше.
    """
    offenders = {
        module: "сочиняет задание и зовёт провайдера, но канон не вплетает"
        for module, source in _sources().items()
        if _PROVIDER_CALL.search(source)
        and _AUTHORS_PROMPT.search(source)
        and not _FOLDS_THE_CANON.search(source)
    }

    assert offenders == {}


def test_every_tool_loop_in_the_tree_is_handed_the_canon() -> None:
    """Каждая сборка тул-лупа НАЗЫВАЕТ канон — но это опять форма, не факт (BOB-096.10).

    Тул-луп — вторая (и единственная другая) точка, где payload уходит модели ПОРТОМ
    ПРОВАЙДЕРА, и канон приходит ему инъекцией. Поэтому каждая сборка петли в дереве
    обязана его назвать: ровно на этом месте дверь привилегированного исполнения и
    осталась без запрета. Проверка идёт по свойству вызова, а не по списку разрешённых
    мест — но проверяется НАПИСАНИЕ аргумента: ``voice_canon=None`` этот гард устраивает
    (ревьюер выключил так провязку разрешений при 7586 passed). Факт — что канон реально
    доезжает до провайдера — проверяет
    ``tests/runtime/test_composed_wiring_carries_the_canon.py``.
    """
    silent = {
        module
        for module, source in _sources().items()
        if any(
            "voice_canon=" not in source[match.end() : match.end() + _BUILD_SITE_WINDOW]
            for match in _TOOL_LOOP_BUILD.finditer(source)
        )
    }

    assert silent == set()


# 🔴 Кто РЕАЛЬНО открывает каждую дверь — снимок, сверенный С КОДОМ (BOB-096.8). Разметка
# двери — это факт о вызывающем («куда девается вывод»), и оба дефекта ревью MAJOR-2
# родились ровно так: у двери появился НОВЫЙ вызывающий, а разметка осталась прежней.
# Внутренний монолог получил третьего (выбор увлечения, который вывод СОХРАНЯЛ), и реестр
# продолжал утверждать «нигде не сохраняется». Снимок ниже краснеет в ту же секунду.
_DOOR_CALLERS: dict[str, set[str]] = {
    # Голос, который остаётся.
    "REPLY_TO_USER": {
        "application/usecases/handle_message.py",  # разговорный ход
        "application/usecases/privileged_fulfiller.py",  # исполнение по разрешению
        "proactivity/usecases/engine.py",  # проактивная реплика
        "capabilities/usecases/tool_loop.py",  # шов канона на второй точке прохода
    },
    "GENESIS": {"social/usecases/run_genesis.py"},  # SOUL.md + genesis_log, навсегда
    "REFLECT": {
        "application/usecases/heartbeat.py",  # рефлексия → episodic_log
        "memory/usecases/consolidate_memory.py",  # дайджест → память
        "personality/usecases/reappraise_reflection.py",  # переоценка переписывает мысль
    },
    "WORK_JOURNAL": {"coding/usecases/distill_work_journal.py"},  # эпизоды 'work'
    "DETECT_PATTERNS": {"proactivity/usecases/detect_patterns.py"},  # правило-поправка
    "FASCINATION_PICK": {"personality/usecases/evolve_fascination.py"},  # тема → SQLite
    # Вывод остаётся, но голосом Боба не звучит.
    "EXTRACT_FACTS": {"memory/usecases/extract_facts.py"},  # факты → semantic_memory
    "PLAN_GOAL": {"proactivity/usecases/plan_goal.py"},  # задачи → граф целей
    "REACTION_JUDGE": {"personality/adapters/reaction_judge.py"},  # прочтение → эпизод
    # Голос, который не остаётся (решение owner'а BOB-087.E-M1).
    "INTERIM_LINE": {"conversation/adapters/interim_line.py"},  # печатается и пропадает
    # Служебные: вердикт/метка расходуются в этом же ходе.
    "INNER_MONOLOGUE": {
        "application/usecases/heartbeat.py",  # мысль → шаг настроения
        "proactivity/usecases/engine.py",  # гейт «заговаривать ли»
    },
    "SENTIMENT": {
        "personality/usecases/reappraise_reflection.py",
        "personality/usecases/update_mood_from_text.py",
    },
    "CODING_INTENT": {"coding/usecases/classify_coding_intent.py"},
    "WORK_TALK": {"memory/usecases/classify_work_talk.py"},
    "ROOM_READ": {"conversation/adapters/room_reader.py"},
    "RESPONSE_JUDGE": {"conversation/adapters/response_judge.py"},
    "PRIVILEGE_JUDGE": {"social/adapters/privilege_judge.py"},
    "VOLATILITY_JUDGE": {"conversation/adapters/volatility_judge.py"},
    "STALENESS_JUDGE": {"presence/adapters/staleness_judge.py"},
    "DISCLOSURE_CONSENT": {"social/adapters/disclosure_consent_judge.py"},
}

# Открыть дверь можно двумя способами: собрать запрос этого вида работы или спросить про
# неё сам шов. Пакет роутера не считается — там дверь ОПИСАНА, а не открыта.
_DOOR_USE = re.compile(r"(?:task_type=|door_for\()TaskType\.(\w+)")


def test_every_door_knows_who_calls_it() -> None:
    """🔴 У двери появился новый вызывающий — сверь разметку с тем, куда девается вывод.

    Не «сколько дверей», а «кто в них ходит»: канон и вердикт о дублёре решаются по тому,
    ЧЕМ является вывод, а это факт о вызывающем. Обновляя снимок, проверь по коду, куда
    девается вывод нового хода, и при необходимости переразметь дверь в
    :mod:`bob.application.router.generation_door` — иначе разметка снова станет
    предположением, как это было с внутренним монологом.
    """
    actual: dict[str, set[str]] = {}
    for module, source in _sources().items():
        if module.startswith("application/router/"):
            continue
        for match in _DOOR_USE.finditer(source):
            actual.setdefault(match.group(1), set()).add(module)

    assert actual == _DOOR_CALLERS


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
