# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Дублёр не говорит ни в одну дверь, чей ГОЛОС ОСТАЁТСЯ (BOB-096, срез 4).

Защита «своим голосом Боб через дублёра не говорит» (BOB-087.E-M1) стояла на условии
``task_type is TaskType.REPLY_TO_USER`` — то есть на ТРЁХ дверях из девятнадцати. Цена
известна поимённо: 6 августа 2026, в секунду отвала Tier-1, дублёр сочинил предложение
самоулучшения и оно уехало owner'у (дверь ``DETECT_PATTERNS`` вердикта не проходила), а
рефлексии тех же часов приехали с английскими вставками и легли в ``episodic_log`` —
то есть вернулись к модели как её собственный few-shot (механизм BOB-074).

Срез 4 заменяет частный признак понятием двери из
:mod:`bob.application.router.generation_door`: **«голос, который остаётся»** =
``speaks_as_bob AND output_is_kept``. Здесь это пинается ПОВЕДЕНИЕМ, а не предикатом:

1. **Сценарий 6 августа на настоящей проводке** — конфиг формы живого ``config/bob.yaml``
   (``tier0_fallback: ollama``) через НАСТОЯЩУЮ фабрику провайдеров, а дублёр — настоящий
   локальный HTTP-сервер (как ollama), который считает запросы. Фейка нет вовсе: облачные
   тиры лежат на мёртвом порту, то есть отвал — настоящий отказ соединения (§0.3 п.4).
   🔴 И тем же сервером проверяется, что харнесс не зелёный вакуумно: служебный ход по ТОЙ
   ЖЕ проводке до дублёра доезжает.
2. **Двери, пишущие в память** — рефлексия, дайджест консолидации и work_journal гоняются
   НАСТОЯЩИМИ use-case'ами: при отвале они не рождаются ВООБЩЕ (ни эпизода, ни дайджеста),
   вместо того чтобы родиться голосом дублёра.
3. **Служебные суждения продолжают работать** — страховка Среза E не тронута: судьи,
   ``coding_intent``, ``sentiment``, ``room_read`` и ``extract_facts`` при том же отвале
   по-прежнему отвечают с дублёра.
4. **Обход всех дверей** — список запрещённых дверей задан ЛИТЕРАЛОМ, поэтому новая дверь
   краснеет здесь, пока про неё не примут решение осознанно.
"""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

import pytest
from aiohttp import web

from bob.application.router.generation_door import TaskType
from bob.application.router.llm_router import LLMRequest, LLMRouter
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import ReflectTick
from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
from bob.infrastructure.llm.factory import build_tier_providers
from bob.infrastructure.llm.fallback_provider import build_fallback_provider
from bob.kernel.ports import UnderstudyBackedProvider
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine
from bob.personality.usecases.evolve_fascination import EvolveFascination
from bob.personality.usecases.reappraise_reflection import ReappraiseReflection
from bob.personality.voice import guppi_voice_canon
from bob.proactivity.usecases.detect_patterns import DetectPatterns, LlmPatternDetector

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.kernel.ports import LLMProvider
    from bob.personality.fascination import Fascination
    from bob.proactivity.self_improvement import ImprovementRule

_MOMENT = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)

# 🔴 ДВЕРИ, КОТОРЫМ ДУБЛЁР НЕДОПУСТИМ — литерал, а не вывод из тех же свойств, которые
# проверяются: иначе тест доказывал бы сам себя. Ровно список BRIEF: разговорный ход,
# проактивная реплика (ходит той же дверью), пробуждение, рефлексия/переоценка/дайджест,
# дневник работы и правило-поправка. Новая дверь краснеет здесь, пока решение о ней не
# принято ЯВНО (и, пока не принято, шов считает её голосом, который остаётся).
_THE_VOICE_THAT_STAYS = frozenset(
    {
        TaskType.REPLY_TO_USER,
        TaskType.GENESIS,
        TaskType.REFLECT,
        TaskType.WORK_JOURNAL,
        TaskType.DETECT_PATTERNS,
        # 🔴 BOB-096.8: выбор увлечения разведён из «внутреннего монолога» в свою дверь —
        # тема ложится в SQLite и неделями звучит в репликах как «меня сейчас занимает…»,
        # то есть это голос Боба, который остаётся. При отвале её выбирает не дублёр, а
        # детерминированная опора на реальный материал (см. ``EvolveFascination``).
        TaskType.FASCINATION_PICK,
    }
)

# То, что дублёр сочинил в ночь на 6 августа: форма правильная (отбраковка вырожденных из
# среза 2 его пропускает — наблюдение и поправка непусты, величина в диапазоне), а голос
# чужой — третье лицо о себе и английские вставки. Отсеять такое может только вердикт о
# голосе: содержательного дефекта, за который можно зацепиться, здесь нет.
_UNDERSTUDY_RULE_JSON = json.dumps(
    [
        {
            "observation": "Боб замечает, что his behavior often repeats",
            "adjustment": "чуть less verbosity in private",
            "lever": "length",
            "magnitude": 0.2,
            "evidence": "reflections",
        }
    ],
    ensure_ascii=False,
)
# Рефлексия тех же часов — она легла бы в episodic_log и завтра вернулась бы few-shot'ом.
_UNDERSTUDY_REFLECTION = "вашу текущую мoods стоит обсудить in private"
# Отрывок промпта переоценки: по нему видно, ЧТО именно спросили у дублёра — служебный
# вердикт о настроении или сам переписанный текст мысли.
_REFRAME_MARKER = "rewrite it"


class RecordingProvider:
    """Единственный фейк второго и третьего разделов: сеть. Пишет вызовы, может отвалиться."""

    def __init__(self, *, reply: str = "ok", fail: bool = False) -> None:
        self._reply = reply
        self._fail = fail
        self.calls: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — часть протокола LLMProvider
    ) -> str | AsyncIterator[str]:
        self.calls.append("\n".join(m.get("content", "") for m in messages))
        if self._fail:
            # ConnectionError — OSError, то есть транспортный вердикт: тир отвалился.
            raise ConnectionError("облачный тир недоступен")
        return self._reply


class _FakeClock:
    def now(self) -> datetime:
        return _MOMENT


class _FakeEpisodes:
    def __init__(self) -> None:
        self.saved: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.saved.append(episode)


class _FakeFacts:
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save_fact(self, fact: object) -> None:
        self.saved.append(fact)


class _FakeFascinationStore:
    """Стор увлечений: пуст на входе, пишет то, что Боб выбрал темой."""

    def __init__(self) -> None:
        self.saved: list[Fascination] = []

    async def load(self, persona_id: str) -> Fascination | None:
        del persona_id
        return None

    async def save(self, persona_id: str, fascination: Fascination) -> None:
        del persona_id
        self.saved.append(fascination)


class _FakeGrounding:
    """Настоящий материал выбора: последняя мысль Боба и его сильные вкусы."""

    async def latest_reflection_text(self) -> str | None:
        return "думал об орбитах"

    def strong_taste_topics(self) -> tuple[str, ...]:
        return ("звёзды",)


class _FakeRuleStore:
    """Хранилище самоулучшения: пусто на входе, записывает всё, что предложено."""

    def __init__(self) -> None:
        self.saved: list[ImprovementRule] = []

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:
        del persona_id
        return ()

    async def save_rule(self, persona_id: str, rule: ImprovementRule) -> None:
        del persona_id
        self.saved.append(rule)


class _FakeConsolidationStore:
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


def _router_with_understudy(
    *,
    tier0_primary: LLMProvider,
    understudy: LLMProvider,
    tier1: LLMProvider,
) -> LLMRouter:
    """Роутер ровно той сборки, что даёт фабрика при ``llm.tier0_fallback`` ON."""
    composite = build_fallback_provider(primary=tier0_primary, fallback=understudy)
    return LLMRouter(providers={0: composite, 1: tier1}, voice_canon=guppi_voice_canon)


# ─── 1. Сценарий 6 августа на НАСТОЯЩЕЙ проводке: фабрика + живой HTTP-дублёр ───────────

# Мёртвый порт loopback: соединение отвергается сразу — настоящий транспортный отвал
# облачных тиров (в ту ночь отвалился Aliyun, где стоят ОБА тира живого конфига).
_DEAD_ENDPOINT = "http://127.0.0.1:1/v1"
_UNDERSTUDY_MODEL = "qwen3:8b"


async def _start_understudy(reply: str) -> tuple[str, web.AppRunner, list[Mapping[str, object]]]:
    """Поднять локальный OpenAI-совместимый сервер — стенд-ин настоящей ollama."""
    seen: list[Mapping[str, object]] = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(await request.json())
        return web.json_response({"choices": [{"message": {"content": reply}}]})

    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    host, port = runner.addresses[0][0], runner.addresses[0][1]
    return f"http://{host}:{port}/v1", runner, seen


def _live_shaped_llm_config(understudy_url: str) -> dict[str, object]:
    """Секция ``llm`` формы живого ``config/bob.yaml``: оба тира в облаке, дублёр локальный."""
    return {
        "llm": {
            "tier0_base_url": _DEAD_ENDPOINT,
            "tier0_model": "qwen3.6-flash",
            "tier1_base_url": _DEAD_ENDPOINT,
            "tier1_model": "qwen3.7-plus",
            "tier0_fallback": "ollama",
            "tier0_fallback_base_url": understudy_url,
            "tier0_fallback_model": _UNDERSTUDY_MODEL,
            "timeout_seconds": 5.0,
        }
    }


async def test_the_live_wiring_actually_composes_the_verdicts_precondition() -> None:
    # 🔴 §0.3 п.10: вердикт о голосе включается ТОЛЬКО если Tier-0 собран дублёр-бэкед
    # композитом. Если бы фабрика живого конфига его не собирала, вся защита существовала
    # бы на бумаге. Проверяется на настоящей фабрике, а не чтением кода.
    understudy_url, runner, _seen = await _start_understudy("ok")
    try:
        providers = build_tier_providers(_live_shaped_llm_config(understudy_url))

        assert isinstance(providers[0], UnderstudyBackedProvider)
        assert providers[0].without_understudy() is not providers[0]
        assert not isinstance(providers[1], UnderstudyBackedProvider)
    finally:
        await runner.cleanup()


async def test_the_rule_proposal_of_the_sixth_of_august_is_never_born_on_the_understudy() -> None:
    # Воспроизведение: облако отвалилось, дублёр на месте и готов сочинить правило.
    understudy_url, runner, seen = await _start_understudy(_UNDERSTUDY_RULE_JSON)
    try:
        providers = build_tier_providers(_live_shaped_llm_config(understudy_url))
        router = LLMRouter(providers=providers, voice_canon=guppi_voice_canon)
        store = _FakeRuleStore()
        detect = DetectPatterns(
            detector=LlmPatternDetector(router=router, clock=_FakeClock()),
            store=store,
            persona_id="bob",
        )

        await detect.run()

        assert store.saved == [], "предложение правила уехало owner'у голосом дублёра"
        assert seen == [], "дублёру вообще не должны были дать сочинять правило"
    finally:
        await runner.cleanup()


async def test_a_service_turn_on_that_same_wiring_does_reach_the_understudy() -> None:
    # 🔴 Анти-вакуум: тот же сервер, та же проводка, тот же отвал — служебный ход до
    # дублёра ДОЕЗЖАЕТ. Без этого «дублёр промолчал» ничего не доказывало бы: цепочка
    # могла быть сломана целиком.
    understudy_url, runner, seen = await _start_understudy("positive")
    try:
        providers = build_tier_providers(_live_shaped_llm_config(understudy_url))
        router = LLMRouter(providers=providers, voice_canon=guppi_voice_canon)

        answer = await router.run(
            LLMRequest(
                task_type=TaskType.SENTIMENT,
                messages=[{"role": "user", "content": "какое настроение"}],
            )
        )

        assert answer == "positive"
        assert [call["model"] for call in seen] == [_UNDERSTUDY_MODEL]
    finally:
        await runner.cleanup()


# ─── 2. Двери, пишущие в память: при отвале не рождаются ВООБЩЕ ─────────────────────────


async def test_the_reflection_is_not_born_when_only_the_understudy_is_left() -> None:
    # Рефлексия — главный источник отравления: она ложится в episodic_log и всплывает
    # припоминанием. Дверь локальная (Tier-0 по политике), поэтому эскалации нет: за Боба
    # не говорит НИКТО, тик падает и супервизор его изолирует (retry-политика heartbeat).
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply=_UNDERSTUDY_REFLECTION)
    tier1 = RecordingProvider(reply="облачная рефлексия")
    episodes = _FakeEpisodes()
    tick = ReflectTick(
        router=_router_with_understudy(
            tier0_primary=tier0_primary, understudy=understudy, tier1=tier1
        ),
        repo=episodes,
        state=PersonalityState(soul=_soul()),
        clock=_FakeClock(),
    )

    with pytest.raises(ConnectionError):
        await tick.run()

    assert understudy.calls == [], "рефлексию писал дублёр"
    assert episodes.saved == [], "чужой голос лёг в память как эпизод Боба"
    assert tier1.calls == [], "нередактированный Tier-0 payload уехал в облако"


async def test_the_consolidation_digest_is_not_born_on_the_understudy() -> None:
    # Дайджест — сжатое воспоминание от первого лица: он тоже переживает ход.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="я чинил сборку and it was fine")
    store = _FakeConsolidationStore()
    consolidation = ConsolidateMemory(
        store=store,
        router=_router_with_understudy(
            tier0_primary=tier0_primary,
            understudy=understudy,
            tier1=RecordingProvider(reply="облако"),
        ),
        clock=_FakeClock(),
    )

    with pytest.raises(ConnectionError):
        await consolidation.run()

    assert understudy.calls == []
    assert store.digests == [], "дайджест голосом дублёра лёг в память"


async def test_the_work_journal_is_not_written_by_the_understudy() -> None:
    # Дневник работы — эпизоды 'work' от первого лица. Дистиллятор best-effort: сбой даёт
    # ПУСТО, и это правильный исход — лучше без записи, чем чужим голосом.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply="я поправил сборку and pushed it")
    distiller = Tier0WorkJournalDistiller(
        router=_router_with_understudy(
            tier0_primary=tier0_primary,
            understudy=understudy,
            tier1=RecordingProvider(reply="облако"),
        )
    )

    episodes = await distiller.distill(
        "починить сборку",
        SessionKeyFacts(files=("app.py",), tests_passed=True),
        WorkOutcome.FINISHED,
    )

    assert episodes == ()
    assert understudy.calls == []


# ─── 3. Служебные суждения продолжают работать (страховка Среза E не тронута) ───────────


async def test_fact_extraction_still_degrades_to_the_understudy() -> None:
    # 🔴 Осознанная граница: выжимка фактов ОСТАЁТСЯ (semantic_memory), но говорит не
    # голосом Боба — это JSON, который читает код. Дублёр ей допустим, иначе отвал облака
    # оставлял бы Боба ещё и без новых фактов о собеседнике.
    tier0_primary = RecordingProvider(fail=True)
    understudy = RecordingProvider(reply='[{"category": "identity", "content": "её зовут Лиля"}]')
    facts = _FakeFacts()
    extract = ExtractFacts(
        router=_router_with_understudy(
            tier0_primary=tier0_primary,
            understudy=understudy,
            tier1=RecordingProvider(reply="облако"),
        ),
        repo=facts,
        clock=_FakeClock(),
    )

    await extract.run(user_message="меня зовут Лиля", reply="приятно")

    assert len(understudy.calls) == 1
    assert len(facts.saved) == 1


@pytest.mark.parametrize(
    "task_type",
    [
        TaskType.SENTIMENT,
        TaskType.CODING_INTENT,
        TaskType.ROOM_READ,
        TaskType.RESPONSE_JUDGE,
        TaskType.PRIVILEGE_JUDGE,
        TaskType.INNER_MONOLOGUE,
        TaskType.WORK_TALK,
        TaskType.INTERIM_LINE,
    ],
)
async def test_a_service_judgment_keeps_working_through_the_outage(task_type: TaskType) -> None:
    # Служебный вердикт расходуется в этом же ходе и никого не учит говорить, поэтому
    # отвал облака не должен ронять машинерию Боба (ровно то, ради чего Срез E и был).
    understudy = RecordingProvider(reply="verdict")
    router = _router_with_understudy(
        tier0_primary=RecordingProvider(fail=True),
        understudy=understudy,
        tier1=RecordingProvider(fail=True),
    )

    answer = await router.run(
        LLMRequest(task_type=task_type, messages=[{"role": "user", "content": "?"}])
    )

    assert answer == "verdict"
    assert len(understudy.calls) == 1


# ─── 4. Обход ВСЕХ дверей: кому дублёр допустим, а кому нет ─────────────────────────────


@pytest.mark.parametrize("task_type", list(TaskType))
async def test_every_door_decides_the_understudy_by_what_its_output_is(
    task_type: TaskType,
) -> None:
    # Полный отвал обоих облачных тиров: остался только дублёр. Дверь, чей голос
    # остаётся, молчит; служебная — отвечает. Никаких исключений по типу задачи.
    understudy = RecordingProvider(reply="дублёр")
    router = _router_with_understudy(
        tier0_primary=RecordingProvider(fail=True),
        understudy=understudy,
        tier1=RecordingProvider(fail=True),
    )
    request = LLMRequest(
        task_type=task_type,
        messages=[{"role": "user", "content": "?"}],
        tier_override=0,  # каждая дверь прижата к умирающему тиру: путь отвала
    )

    with contextlib.suppress(ConnectionError):  # кого некому обслужить — падает честно
        await router.run(request)

    if task_type in _THE_VOICE_THAT_STAYS:
        assert understudy.calls == [], f"{task_type.value}: дублёр заговорил голосом Боба"
    else:
        assert len(understudy.calls) == 1, f"{task_type.value}: служебный ход лишился страховки"


async def test_the_understudy_never_picks_what_bob_is_into_but_the_step_survives() -> None:
    """🔴 BOB-096.8 (ревью MAJOR-2): тему увлечения при отвале выбирает НЕ дублёр.

    Тема живёт в SQLite неделями и вплетается в реплики, поэтому «упрямство GUPPI»,
    сочинённое 0.5b-моделью в час отвала, месяц звучало бы как увлечение Боба. И
    обратная сторона той же границы: шаг не теряется — тема рождается детерминированной
    опорой на тот же реальный материал (последняя мысль + сильные вкусы).
    """
    understudy = RecordingProvider(reply="упрямство GUPPI")
    store = _FakeFascinationStore()
    evolve = EvolveFascination(
        persona_id="bob",
        store=store,
        router=_router_with_understudy(
            tier0_primary=RecordingProvider(fail=True),
            understudy=understudy,
            tier1=RecordingProvider(fail=True),
        ),
        grounding=_FakeGrounding(),
        clock=_FakeClock(),
    )

    await evolve.run()

    assert understudy.calls == [], "увлечение Бобу выбрал дублёр"
    assert len(store.saved) == 1, "шаг увлечений потерялся вместе с облаком"
    assert store.saved[0].topic == "думал об орбитах"


async def test_the_reappraisal_of_a_reflection_is_not_handed_to_the_understudy() -> None:
    # Переоценка ПЕРЕЗАПИСЫВАЕТ рефлексию — её текст ложится в память вместо исходного,
    # то есть это та же дверь REFLECT и тот же запрет. 🔴 И это самый выразительный случай
    # различения: у дублёра тут спрашивают ОДИН раз — служебное «мысль негативная?»
    # (SENTIMENT, страховка Среза E), а сам переписанный текст ему не доверяют.
    understudy = RecordingProvider(reply="negative")
    reappraiser = ReappraiseReflection(
        router=_router_with_understudy(
            tier0_primary=RecordingProvider(fail=True),
            understudy=understudy,
            tier1=RecordingProvider(fail=True),
        ),
        rng=Random(1),  # noqa: S311 — не крипто: сеяный жребий переоценки
        disposition=Disposition(optimism=1.0, resilience=1.0),
    )

    with pytest.raises(ConnectionError):
        await reappraiser.run("всё разваливается")

    assert len(understudy.calls) == 1, "дублёру отдали не только служебный вердикт"
    assert _REFRAME_MARKER not in "\n".join(understudy.calls), "переоценку писал дублёр"
