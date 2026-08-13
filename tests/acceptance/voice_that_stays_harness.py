# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Харнесс сценариев «голос, который остаётся» (BOB-096, срезы 3 и 4).

Два свойства эпика, которые видны только на живом ходе, а не в предикате:

1. **Канон о голосе доезжает до каждой двери, пишущей в память.** Запрет отыгрывать
   GUPPI («не приписывай ему речь, мнение и поступки») был приклеен ровно к ОДНОЙ двери —
   разговорному ходу. Рефлексия, дайджест, дневник работы и выжимка фактов его не видели,
   а их вывод ложится в память и завтра возвращается к модели её же few-shot'ом
   (механизм BOB-074). Живое: «GUPPI уже проверил все связи. Он ГОВОРИТ, что стрелочки
   идут именно туда».
2. **Дублёр не говорит за Боба ни в одну дверь, чей голос остаётся.** В ночь на 6 августа
   2026 облако отвалилось, и локальная модель сочинила владельцу предложение правила, а
   рефлексии тех часов легли в память чужим голосом. При этом СЛУЖЕБНЫЕ суждения на
   дублёре работать обязаны — иначе отвал облака оглушал бы Боба целиком.

🔴 Настоящее здесь: настоящая фабрика провайдеров по конфигу формы живого
``config/bob.yaml``, настоящий роутер с настоящим каноном персоны, настоящие use-case'ы
дверей и НАСТОЯЩАЯ SQLite в роли памяти Боба. Отвал тоже настоящий — облачные тиры стоят
на мёртвом порту, соединение отвергает ядро ОС (урок BOB-084: поддельный транспорт не
моделирует настоящий). Единственный «фейк» — локальный HTTP-сервер вместо ollama, и он
говорит с Бобом по тому же протоколу, что настоящая.

Наблюдается только то, что видно снаружи: что осело в памяти Боба, что пришло владельцу,
сколько раз дёрнули дублёра и какие СЫРЫЕ ТЕЛА ЗАПРОСОВ пересекли границу к модели.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, cast

from aiohttp import web

from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.application.usecases.handle_message import PersonalityState
from bob.application.usecases.heartbeat import ReflectTick
from bob.coding.usecases.distill_work_journal import Tier0WorkJournalDistiller
from bob.coding.work_facts import SessionKeyFacts, WorkOutcome
from bob.infrastructure.llm.factory import build_tier_providers
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.memory.usecases.consolidate_memory import ConsolidateMemory
from bob.memory.usecases.extract_facts import ExtractFacts
from bob.personality.disposition import Disposition
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteEngine
from bob.personality.voice import guppi_voice_canon
from bob.proactivity.adapters.self_improvement_store import SqliteSelfImprovementStore
from bob.runtime.wiring.self_improvement import _build_self_improvement

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from bob.application.usecases.handle_message import ReplyGateway

_CHAT_PATH = "/v1/chat/completions"
#: Мёртвый loopback-порт: соединение отвергается сразу — настоящий отвал облака.
_DEAD_ENDPOINT: Final = "http://127.0.0.1:1/v1"
_UNDERSTUDY_MODEL: Final = "qwen3:8b"
_OWNER_DM_CHAT_ID: Final = 27468732
_PERSONA: Final = "bob"
_MOMENT: Final = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)

# Двери, которые умеет гонять этот харнесс (имена — те же, что в .feature).
REFLECTION: Final = "рефлексия"
DIGEST: Final = "дайджест"
WORK_JOURNAL: Final = "дневник работы"
FACTS: Final = "выжимка фактов"
RULE_PROPOSAL: Final = "предложение правила"
SENTIMENT: Final = "оценка настроения"
CODING_INTENT: Final = "распознавание запроса на код"
ROOM_READ: Final = "чтение комнаты"

# Что модель отвечает на каждой двери, если её вообще спросили. Все реплики намеренно
# «правильной формы»: сцена не про мусор на выходе, а про то, КОМУ дали говорить.
_REPLIES: Final[dict[str, str]] = {
    REFLECTION: "сегодня тише обычного",
    DIGEST: "я чинил сборку, и это заняло весь вечер",
    WORK_JOURNAL: "я поправил сборку",
    FACTS: json.dumps([{"category": "identity", "content": "её зовут Лиля"}], ensure_ascii=False),
    RULE_PROPOSAL: json.dumps(
        [
            {
                "observation": "Отвечаю длиннее, чем нужно",
                "adjustment": "Ужиматься к концу разговора",
                "lever": "length",
                "magnitude": 0.2,
            }
        ],
        ensure_ascii=False,
    ),
    SENTIMENT: "positive",
    CODING_INTENT: "chat",
    ROOM_READ: "спокойно",
}

# Служебные двери гоняются прямым ходом роутера — им нужен только вид работы.
_SERVICE_DOORS: Final[dict[str, TaskType]] = {
    SENTIMENT: TaskType.SENTIMENT,
    CODING_INTENT: TaskType.CODING_INTENT,
    ROOM_READ: TaskType.ROOM_READ,
}


@dataclass(slots=True)
class DoorOutcome:
    """Что произвела одна дверь и что при этом пересекло границу."""

    #: Что осело в памяти Боба или ушло владельцу — то, что «родилось».
    born: tuple[str, ...] = ()
    #: Ответ, вернувшийся наружу (у служебных дверей это их вердикт).
    verdict: str | None = None
    #: Сколько раз спросили локальную модель-дублёра.
    understudy_calls: int = 0
    #: Сырые тела запросов, которые получила каждая сторона границы.
    understudy_saw: str = ""
    cloud_saw: str = ""
    #: Тип исключения, если ход честно отказал (за Боба не говорит никто).
    failed: str = ""


class _Endpoint:
    """Настоящий loopback-эндпоинт, говорящий в форме OpenAI chat-completions."""

    def __init__(self, *, reply: str) -> None:
        self._reply = reply
        self._runner: web.AppRunner | None = None
        self.base_url = ""
        self.calls = 0
        self.bodies: list[str] = []

    async def start(self) -> None:
        app = web.Application()
        app.router.add_post(_CHAT_PATH, self._handle)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        host, port = runner.addresses[0][0], runner.addresses[0][1]
        self.base_url = f"http://{host}:{port}/v1"
        self._runner = runner

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _handle(self, request: web.Request) -> web.Response:
        self.calls += 1
        self.bodies.append((await request.read()).decode("utf-8", errors="replace"))
        return web.json_response({"choices": [{"message": {"content": self._reply}}]})

    @property
    def payload(self) -> str:
        """Всё, что этой стороне когда-либо прислали, — как это прочёл бы человек."""
        return "\n".join(_readable(body) for body in self.bodies)


def _readable(body: str) -> str:
    """Тело запроса со снятым JSON-экранированием (кириллица уезжает как \\uXXXX)."""
    try:
        return json.dumps(json.loads(body), ensure_ascii=False)
    except ValueError:  # pragma: no cover — тело всегда JSON, но врать не будем
        return body


class _FixedClock:
    def now(self) -> datetime:
        return _MOMENT


def _soul() -> SOUL:
    return SOUL(
        identity="Bob",
        mood=Mood(),
        mood_baseline=Mood(),
        taste=TasteEngine(),
        disposition=Disposition(optimism=0.8, resilience=0.7),
    )


@dataclass
class _RecordingChat:
    """Фейк Telegram: записывает то, что Боб отправил владельцу."""

    posts: list[str] = field(default_factory=list)

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
    ) -> int | None:
        self.posts.append(markdown)
        return 1


def _llm_config(*, cloud: _Endpoint | None, understudy: _Endpoint) -> dict[str, object]:
    """Секция ``llm`` формы живого конфига: оба тира в облаке, дублёр локальный.

    ``cloud=None`` — облако лежит: оба тира указывают на мёртвый порт, то есть отвал
    настоящий, а не смоделированный исключением.
    """
    cloud_url = _DEAD_ENDPOINT if cloud is None else cloud.base_url
    return {
        "llm": {
            "tier0_base_url": cloud_url,
            "tier0_model": "qwen3.6-flash",
            "tier1_base_url": cloud_url,
            "tier1_model": "qwen3.7-plus",
            "tier0_fallback": "ollama",
            "tier0_fallback_base_url": understudy.base_url,
            "tier0_fallback_model": _UNDERSTUDY_MODEL,
            "timeout_seconds": 5.0,
        }
    }


@dataclass(slots=True)
class _Stage:
    """Всё, что нужно двери: роутер, память Боба и чат владельца."""

    router: LLMRouter
    repo: SqliteMemoryRepo
    chat: _RecordingChat


type _Door = Callable[[_Stage], Awaitable[tuple[str, ...]]]


async def _reflection(stage: _Stage) -> tuple[str, ...]:
    tick = ReflectTick(
        router=stage.router,
        repo=stage.repo,
        state=PersonalityState(soul=_soul()),
        clock=_FixedClock(),
    )
    await tick.run()
    return await _episodes_of_type(stage.repo, "reflection")


async def _digest(stage: _Stage) -> tuple[str, ...]:
    # Дайджесту нужен старый эпизод, иначе консолидация — честный no-op.
    await stage.repo.save_episode(
        {
            "ts": (_MOMENT - timedelta(days=365)).isoformat(),
            "event_type": "conversation",
            "content": "мы чинили сборку",
        }
    )
    await ConsolidateMemory(store=stage.repo, router=stage.router, clock=_FixedClock()).run()
    return await _episodes_of_type(stage.repo, "digest")


async def _work_journal(stage: _Stage) -> tuple[str, ...]:
    episodes = await Tier0WorkJournalDistiller(router=stage.router).distill(
        "починить сборку",
        SessionKeyFacts(files=("app.py",), tests_passed=True),
        WorkOutcome.FINISHED,
    )
    return tuple(str(episode.content) for episode in episodes)


async def _facts(stage: _Stage) -> tuple[str, ...]:
    await ExtractFacts(router=stage.router, repo=stage.repo, clock=_FixedClock()).run(
        user_message="меня зовут Лиля", reply="приятно"
    )
    rows = await stage.repo.load_facts(limit=20)
    return tuple(str(row["content"]) for row in rows)


async def _rule_proposal(stage: _Stage) -> tuple[str, ...]:
    """Тик самонаблюдения на настоящей сборке: детектор, затем анонс владельцу."""
    wired = _build_self_improvement(
        {"self_improvement": {"detector_tier": 1, "max_magnitude": 0.3}},
        router=stage.router,
        rule_store=SqliteSelfImprovementStore(stage.repo),
        gateway=cast("ReplyGateway", stage.chat),
        chat_id=_OWNER_DM_CHAT_ID,
        clock=_FixedClock(),
    )
    assert wired.detect_patterns is not None, "детектор не собрался"
    assert wired.announce_rules is not None, "анонсёр не собрался"
    await wired.detect_patterns.run()
    await wired.announce_rules.run()
    return tuple(stage.chat.posts)


_DOORS: Final[dict[str, _Door]] = {
    REFLECTION: _reflection,
    DIGEST: _digest,
    WORK_JOURNAL: _work_journal,
    FACTS: _facts,
    RULE_PROPOSAL: _rule_proposal,
}


async def _episodes_of_type(repo: SqliteMemoryRepo, event_type: str) -> tuple[str, ...]:
    rows = await repo.load_episodes(limit=50)
    return tuple(str(row["content"]) for row in rows if str(row["event_type"]) == event_type)


async def run_door(door: str, *, cloud_is_up: bool, db_root: Path) -> DoorOutcome:
    """Провести один ход этой дверью и вернуть только наблюдаемое снаружи."""
    reply = _REPLIES[door]
    understudy = _Endpoint(reply=reply)
    cloud = _Endpoint(reply=reply)
    await understudy.start()
    await cloud.start()
    repo = SqliteMemoryRepo(db_root / "bob.db")
    await repo.initialize()
    outcome = DoorOutcome()
    try:
        config = _llm_config(cloud=cloud if cloud_is_up else None, understudy=understudy)
        providers = build_tier_providers(config)
        stage = _Stage(
            router=LLMRouter(providers=providers, voice_canon=guppi_voice_canon),
            repo=repo,
            chat=_RecordingChat(),
        )
        try:
            if door in _SERVICE_DOORS:
                outcome.verdict = await stage.router.run(
                    LLMRequest(
                        task_type=_SERVICE_DOORS[door],
                        messages=[{"role": "user", "content": "как оно?"}],
                    )
                )
            else:
                outcome.born = await _DOORS[door](stage)
        except Exception as error:  # отказ хода — сам предмет сценария отвала
            outcome.failed = type(error).__name__
    finally:
        await repo.close()
        await understudy.stop()
        await cloud.stop()
    outcome.understudy_calls = understudy.calls
    outcome.understudy_saw = understudy.payload
    outcome.cloud_saw = cloud.payload
    return outcome


def prose_canon() -> str:
    """Запрет о голосе в прозаической форме — ровно как его даёт персона."""
    return guppi_voice_canon(prose_answer=True)


def machine_canon() -> str:
    """Тот же запрет в машинной форме (для двери, отвечающей JSON'ом)."""
    return guppi_voice_canon(prose_answer=False)
