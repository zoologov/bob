# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Харнесс сценариев здоровья LLM-стека (BOB-116, ``llm_health.feature``).

🔴 Граница — вся собранная программа: настоящий :func:`~bob.runtime.composition.build_application`
с монитором здоровья, роутером, дублёр-обёрткой, гейтами дорожек heartbeat, адаптером сигнала
владельцу и GUPPI. Провайдеры НЕ подменяются: облачный Tier-0, Tier-1 и локальный дублёр —
настоящие loopback-эндпоинты :class:`~tests.acceptance.tier0_fallback_harness.LoopbackEndpoint`
поверх aiohttp, и отказ 403 — настоящий ответ HTTP, который классифицирует настоящая политика
(урок BOB-084: поддельный транспорт не моделирует настоящий). Фейки стоят ровно там, где
кончается Боб:

* боты Боба и GUPPI — :class:`~tests.acceptance.live_app_harness.RecordingBot`: что ушло, куда
  и в каком треде — ровно то, что увидел бы человек. Личка владельца — ``chat_id == owner_id``
  без треда, отправленная ботом Боба: так её видит владелец в Telegram;
* часы — :class:`ScenarioClock`, которые двигает сценарий: пороги «3 минуты», напоминания «через
  час» и зонд «раз в минуту» проверяются без настоящего ожидания.

Сценарий видит только наблюдаемое: тексты в личке и в ответе ``/status``, сколько раз облако
реально позвали, строки лога оператора и эпизоды в памяти. Внутреннее состояние монитора не
читается нигде.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final, cast

from bob.infrastructure.telegram.multibot import BotIdentity
from bob.runtime.composition import build_application
from bob.social.adapters.soul_store import SoulStore
from tests.acceptance.live_app_harness import RecordingBot
from tests.acceptance.tier0_fallback_harness import (
    ANSWERS,
    CLOUD_REPLY,
    LOCAL_REPLY,
    TIER1_REPLY,
    UNREACHABLE,
    LoopbackEndpoint,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import BotLike, UpdateLike
    from bob.runtime.composition import Application

OWNER_ID: Final = 4242
OWNER_NAME: Final = "Вова"
GROUP_CHAT_ID: Final = -1001234567890
BOB_TOPIC_ID: Final = 32
UNDERSTUDY_MODEL: Final = "qwen3:8b"

#: Начало каждого сценария — утро первого дня немоты из замера VPS (06:10 UTC).
START: Final = datetime(2026, 10, 1, 6, 10, tzinfo=UTC)

#: Как часто бьётся heartbeat Боба по умолчанию (``runtime.heartbeat_seconds``).
HEARTBEAT_SECONDS: Final = 30

# Дублёр, каким его застаёт проверка при старте.
UNDERSTUDY_OFF: Final = "off"  # в конфигурации выключен (так на VPS сейчас)
UNDERSTUDY_READY: Final = "ready"  # включён, Ollama отвечает, модель на месте
UNDERSTUDY_MODEL_MISSING: Final = "model_missing"  # включён, Ollama жив, модели нет

# Сколько настоящего времени даётся собранному heartbeat на один отрезок, и как часто
# смотреть, не пришёл ли ожидаемый вызов. Часы Боба при этом стоят — их двигает сценарий.
_SPIN_SECONDS: Final = 0.3
_WAIT_LIMIT_SECONDS: Final = 5.0
_WAIT_STEP_SECONDS: Final = 0.01


class ScenarioClock:
    """Часы Боба, которые двигает сценарий; сами по себе не идут."""

    def __init__(self, moment: datetime = START) -> None:
        self.moment = moment

    def now(self) -> datetime:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class OwnerMessage:
    """Одно личное сообщение владельцу: что сказано и когда по часам Боба."""

    text: str
    at: datetime
    #: Сколько неудачных попыток подумать было к моменту сообщения (0 — до первой).
    after_failures: int


class _LogCollector(logging.Handler):
    """Строки, которые увидел бы оператор в журнале Боба (логгер ``bob``, INFO и выше)."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@dataclass
class HealthWorld:
    """Собранный Боб на loopback-провайдерах и всё, что видно снаружи."""

    app: Application
    clock: ScenarioClock
    cloud: LoopbackEndpoint
    local: LoopbackEndpoint
    tier1: LoopbackEndpoint
    bob_bot: RecordingBot
    guppi_bot: RecordingBot
    log: _LogCollector
    #: Личные сообщения владельцу в порядке прихода, с моментом по часам Боба.
    owner_messages: list[OwnerMessage] = field(default_factory=list)
    #: Сколько попыток подумать не удалось (каждая — отказ провайдера).
    failed_thoughts: int = 0
    #: Что сказали о старте — личка владельца ДО первой мысли.
    startup_messages: tuple[str, ...] = ()

    # --- что делает Боб -------------------------------------------------------------

    async def think(self, times: int = 1, *, every_seconds: float = 0) -> None:
        """Тик внутреннего монолога ``times`` раз; между тиками часы уходят вперёд.

        Отказ тика — предмет сценария, а не ошибка харнесса: он считается, а не
        поднимается. Первая попытка идёт сразу, следующие — через ``every_seconds``.
        """
        for index in range(times):
            if index:
                self.clock.advance(every_seconds)
            try:
                await self.app.inner_monologue_tick.run()
            except Exception:  # отказ провайдера — то, что сценарий и ставит
                self.failed_thoughts += 1
            self._collect_owner_messages()

    async def heartbeat_runs(self) -> int:
        """Собранный heartbeat работает отрезок настоящего времени; часы Боба стоят.

        Возвращает, сколько раз за отрезок позвали облако. ``runtime.heartbeat_seconds``
        у сборки — ноль: без гейта каждая дорожка звала бы облако сотни раз за отрезок.
        """
        before = self.cloud.calls
        await self.app.runtime.start()
        try:
            await asyncio.sleep(_SPIN_SECONDS)
        finally:
            await self.app.runtime.stop()
        self._collect_owner_messages()
        return self.cloud.calls - before

    async def guppi_status(self) -> str:
        """Владелец пишет ``/status`` GUPPI в General; ответ — то, что он увидит."""
        update = _Update(
            update_id=1,
            message=_Message(message_id=7, text="/status"),
            effective_chat=_Chat(id=GROUP_CHAT_ID),
            effective_user=_User(id=OWNER_ID),
        )
        before = len(self.guppi_bot.sent)
        await self.app.multibot.route(cast("UpdateLike", update), BotIdentity.GUPPI)
        answers = self.guppi_bot.sent[before:]
        return "\n".join(line.text for line in answers)

    async def outage_episodes(self) -> list[Mapping[str, object]]:
        """Эпизоды автобиографии о простое — то, что Боб о нём помнит."""
        episodes = await self.app.memory_repo.recent_episodes(100)
        return [
            row
            for row in episodes
            if row["event_type"] == "self_action" and "outage" in str(row["tags"])
        ]

    # --- что видно ------------------------------------------------------------------

    def owner_texts(self) -> list[str]:
        return [message.text for message in self.owner_messages]

    def log_lines(self, *, since: int = 0) -> list[logging.LogRecord]:
        return self.log.records[since:]

    def _collect_owner_messages(self) -> None:
        dms = [
            line.text
            for line in self.bob_bot.sent
            if line.chat_id == OWNER_ID and line.topic_id is None
        ]
        seen = len(self.startup_messages) + len(self.owner_messages)
        for text in dms[seen:]:
            self.owner_messages.append(
                OwnerMessage(text=text, at=self.clock.now(), after_failures=self.failed_thoughts)
            )


@dataclass
class _Message:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _User:
    id: int
    full_name: str = "Владелец"
    username: str | None = None


@dataclass
class _Chat:
    id: int
    type: str = "supergroup"


@dataclass
class _Update:
    update_id: int
    message: _Message | None = None
    effective_chat: _Chat | None = None
    effective_user: _User | None = None


@dataclass(frozen=True, slots=True)
class WorldSetup:
    """Как сценарий ставит мир: что делают эндпоинты, есть ли дублёр, помнит ли Боб."""

    cloud: str = ANSWERS
    cloud_script: Sequence[str] = ()
    #: Что облако отвечает, когда отвечает. По умолчанию — фраза, которую не разберёт ни один
    #: судья хода: ход в комнате кончается на суждении, до основной модели не доходя.
    cloud_reply: str = CLOUD_REPLY
    tier1: str = ANSWERS
    understudy: str = UNDERSTUDY_OFF
    autobiography: bool = False


@contextlib.asynccontextmanager
async def health_world(tmp_path: Path, setup: WorldSetup) -> AsyncIterator[HealthWorld]:
    """Поднять эндпоинты, собрать и запустить Боба; на выходе — гарантированный shutdown."""
    models = _listed_models(setup.understudy)
    cloud = LoopbackEndpoint(
        behaviour=setup.cloud, reply=setup.cloud_reply, script=setup.cloud_script
    )
    local = LoopbackEndpoint(behaviour=ANSWERS, reply=LOCAL_REPLY, models=models)
    tier1 = LoopbackEndpoint(behaviour=setup.tier1, reply=TIER1_REPLY)
    endpoints = (cloud, local, tier1)
    for endpoint in endpoints:
        await endpoint.start()
    collector = _LogCollector()
    bob_logger = logging.getLogger("bob")
    previous_level = bob_logger.level
    bob_logger.addHandler(collector)
    bob_logger.setLevel(logging.INFO)
    try:
        world = _build_world(tmp_path, setup, cloud=cloud, local=local, tier1=tier1)
        world.log = collector
        await world.app.startup()
        try:
            world.startup_messages = tuple(
                line.text
                for line in world.bob_bot.sent
                if line.chat_id == OWNER_ID and line.topic_id is None
            )
            yield world
        finally:
            await world.app.shutdown()
    finally:
        bob_logger.removeHandler(collector)
        bob_logger.setLevel(previous_level)
        for endpoint in endpoints:
            await endpoint.stop()


def _listed_models(understudy: str) -> Sequence[str] | None:
    if understudy == UNDERSTUDY_READY:
        return (UNDERSTUDY_MODEL,)
    if understudy == UNDERSTUDY_MODEL_MISSING:
        return ("llama3:8b",)
    return None


def _build_world(
    tmp_path: Path,
    setup: WorldSetup,
    *,
    cloud: LoopbackEndpoint,
    local: LoopbackEndpoint,
    tier1: LoopbackEndpoint,
) -> HealthWorld:
    # SOUL заранее — иначе Genesis на старте позвал бы модель за первой душой.
    SoulStore(tmp_path / "soul").write_soul("# SOUL\n\nЯ Боб.\n")
    bob_bot, guppi_bot = RecordingBot("bob"), RecordingBot("guppi")
    clock = ScenarioClock()
    app = build_application(
        config=_config(tmp_path, setup, cloud=cloud, local=local, tier1=tier1),
        bob_bot=cast("BotLike", bob_bot),
        guppi_bot=cast("BotLike", guppi_bot),
        clock=clock,
    )
    return HealthWorld(
        app=app,
        clock=clock,
        cloud=cloud,
        local=local,
        tier1=tier1,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        log=_LogCollector(),
    )


def _config(
    tmp_path: Path,
    setup: WorldSetup,
    *,
    cloud: LoopbackEndpoint,
    local: LoopbackEndpoint,
    tier1: LoopbackEndpoint,
) -> dict[str, object]:
    """Конфигурация как на VPS: облако Qwen, блок ``llm.health`` по умолчанию, личка владельца.

    ``heartbeat_seconds: 0`` — дорожки крутятся без пауз, поэтому «не позвали облако» за
    отрезок значит «гейт не пустил», а не «не успели». Пороги здоровья — дефолты RFC.
    """
    llm: dict[str, object] = {
        "tier0_base_url": cloud.base_url,
        "tier0_model": "qwen3.6-flash",
        "tier1_base_url": tier1.base_url,
        "tier1_model": "qwen3.7-plus",
        "timeout_seconds": 5.0,
    }
    if setup.understudy != UNDERSTUDY_OFF:
        llm |= {
            "tier0_fallback": "ollama",
            "tier0_fallback_base_url": local.base_url,
            "tier0_fallback_model": UNDERSTUDY_MODEL,
        }
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": llm,
        "telegram": {
            "poll_timeout": 1,
            "owner_id": OWNER_ID,
            "owner_name": OWNER_NAME,
            "chat_id": GROUP_CHAT_ID,
            "allowed_chat_ids": [GROUP_CHAT_ID],
            "bob": {"token": "bob-tok", "topic_id": BOB_TOPIC_ID},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
        "memory": {"autobiography": setup.autobiography},
    }


async def wait_for_cloud_calls(world: HealthWorld, expected: int) -> None:
    """Дать собранному heartbeat столько настоящего времени, сколько нужно ``expected`` вызовам."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _WAIT_LIMIT_SECONDS
    while world.cloud.calls < expected and loop.time() < deadline:
        await asyncio.sleep(_WAIT_STEP_SECONDS)


__all__ = [
    "BOB_TOPIC_ID",
    "GROUP_CHAT_ID",
    "HEARTBEAT_SECONDS",
    "OWNER_ID",
    "OWNER_NAME",
    "START",
    "UNDERSTUDY_MODEL",
    "UNDERSTUDY_MODEL_MISSING",
    "UNDERSTUDY_OFF",
    "UNDERSTUDY_READY",
    "UNREACHABLE",
    "HealthWorld",
    "OwnerMessage",
    "ScenarioClock",
    "WorldSetup",
    "health_world",
]
