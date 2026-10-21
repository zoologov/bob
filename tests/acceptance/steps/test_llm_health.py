# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the LLM-health scenarios (BOB-116, ``llm_health.feature``).

Binds the feature to :mod:`tests.acceptance.llm_health_harness`: the whole application built
by ``build_application`` over REAL loopback endpoints, with recording Telegram bots and a clock
the scenario moves. Every assertion is on what crossed that boundary — the owner's DM, GUPPI's
``/status`` answer, how many times the cloud was called, the operator's log lines, the episodes
in memory — never on the monitor's state.

pytest-bdd steps are synchronous, while the application lives on ONE event loop. So the
«Дано» steps only stage the world and queue what has already happened, the «Когда» steps
queue the action under test, and the first «Тогда» runs the whole story once, in one
``asyncio.run``, recording where the action started — so a «Тогда» can tell what the action
produced from what the arrangement produced.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenario, scenarios, then, when

from bob.kernel.events import MessageReceived
from tests.acceptance.llm_health_harness import (
    BOB_TOPIC_ID,
    GROUP_CHAT_ID,
    OWNER_ID,
    START,
    UNDERSTUDY_MODEL,
    UNDERSTUDY_MODEL_MISSING,
    UNDERSTUDY_OFF,
    UNDERSTUDY_READY,
    HealthWorld,
    WorldSetup,
    health_world,
)
from tests.acceptance.tier0_fallback_harness import ANSWERS, FORBIDDEN, SERVER_ERROR

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from pathlib import Path

type _Action = Callable[[HealthWorld], Awaitable[None]]

_FEATURE = "../features/llm_health.feature"

# Сколько настоящего времени ждать ответа на сообщение гостя: ход с честным уведомлением
# идёт через ограниченные повторы с настоящим backoff (EssentialRunner).
_TURN_WAIT_SECONDS = 6.0
_TURN_WAIT_STEP_SECONDS = 0.05
_GUPPI_OUTAGE_MARK = "Боб временно недоступен"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BOB-116 T, находка: без дублёра ход гостя падает ДО честного уведомления GUPPI — "
        "классификатор настроения (UpdateMoodFromText._classify_sentiment, служебная дверь "
        "Tier-0) пропускает 403 наружу, и intake-воркер роняет весь ход: ни ответа, ни "
        "уведомления. Замер: с откатом настроения в 'neutral' сценарий зелёный за 1 с. "
        "strict — как только дефект починят, XPASS покраснеет и маркер надо снять."
    ),
)
@scenario(
    _FEATURE,
    "S5 — 403 на Tier-0 без дублёра → голосовая дверь отвечает честным «не могу», "
    "сервисная — молчит, сигнал владельцу ушёл",
)
def test_s5_voice_door_without_understudy() -> None:
    """Сценарий S5 — поведение собранной программы; шаги ниже."""


scenarios(_FEATURE)


@dataclass
class _Story:
    """Мир сценария: как он поставлен, что уже случилось, что делаем — и что вышло."""

    tmp_path: Path
    setup: WorldSetup = field(default_factory=WorldSetup)
    arrange: list[_Action] = field(default_factory=list)
    act: list[_Action] = field(default_factory=list)
    world: HealthWorld | None = None
    #: Сколько личных сообщений владельцу было до действия сценария.
    owner_messages_before_act: int = 0
    #: С какой строки лога началось действие сценария.
    log_index_before_act: int = 0
    #: Вызовы облака по отрезкам работы heartbeat (по отрезку на шаг часов).
    heartbeat_calls: list[int] = field(default_factory=list)
    #: Ответ GUPPI на ``/status``, если сценарий его спрашивал.
    status_text: str = ""
    #: Эпизоды о простое в памяти Боба к концу истории.
    episodes: list[Mapping[str, object]] = field(default_factory=list)

    def outcome(self) -> HealthWorld:
        """Прогнать историю один раз (при первом «Тогда») и вернуть наблюдаемый мир."""
        if self.world is None:
            asyncio.run(self._run())
        assert self.world is not None
        return self.world

    async def _run(self) -> None:
        async with health_world(self.tmp_path, self.setup) as world:
            self.world = world
            for action in self.arrange:
                await action(world)
            self.owner_messages_before_act = len(world.owner_messages)
            self.log_index_before_act = len(world.log.records)
            for action in self.act:
                await action(world)
            self.episodes = await world.outage_episodes()


@pytest.fixture
def story(tmp_path: Path) -> _Story:
    """Свежий мир на каждый сценарий: свои порты, своя БД, свой лог."""
    return _Story(tmp_path=tmp_path)


def _think(times: int, every_seconds: int) -> _Action:
    async def action(world: HealthWorld) -> None:
        await world.think(times, every_seconds=every_seconds)

    return action


# --- Дано: машина, дублёр, облако ------------------------------------------------


@given("Боб работает на машине без дублёра")
def without_understudy(story: _Story) -> None:
    story.setup = replace(story.setup, understudy=UNDERSTUDY_OFF)


@given("у Боба подключён дублёр, и его модель на месте")
def understudy_ready(story: _Story) -> None:
    story.setup = replace(story.setup, understudy=UNDERSTUDY_READY)


@given("в конфигурации дублёр включён, но его модели в Ollama нет")
def understudy_model_missing(story: _Story) -> None:
    story.setup = replace(story.setup, understudy=UNDERSTUDY_MODEL_MISSING)


@given("облачный Tier-0 отвечает 403")
def cloud_forbidden(story: _Story) -> None:
    # Настоящий 403 с loopback — форма десяти дней немоты на VPS (2026-10-01…10).
    story.setup = replace(story.setup, cloud=FORBIDDEN)


@given("облачный Tier-0 один раз отвечает 503, а потом отвечает нормально")
def cloud_single_server_error(story: _Story) -> None:
    story.setup = replace(story.setup, cloud=ANSWERS, cloud_script=(SERVER_ERROR,))


@given("Боб помнит свои поступки")
def autobiography_on(story: _Story) -> None:
    story.setup = replace(story.setup, autobiography=True)


@given(
    parsers.parse(
        "Боб уже {times:d} раз подряд не смог подумать, раз в {every:d} секунд"
    )
)
def already_failed(story: _Story, times: int, every: int) -> None:
    story.arrange.append(_think(times, every))


# --- Когда: что делает Боб и что делает мир -------------------------------------


@when(parsers.parse("Боб {times:d} раз подряд пытается подумать, раз в {every:d} секунд"))
def bob_thinks(story: _Story, times: int, every: int) -> None:
    story.act.append(_think(times, every))


@when(parsers.parse("Боб {times:d} раза подряд пытается подумать, раз в {every:d} секунд"))
def bob_thinks_few(story: _Story, times: int, every: int) -> None:
    story.act.append(_think(times, every))


@when(
    "спустя 2 часа 15 минут после первого отказа облако снова отвечает, и Боб думает"
)
def cloud_returns_after_a_while(story: _Story) -> None:
    async def action(world: HealthWorld) -> None:
        world.clock.moment = START + timedelta(hours=2, minutes=15)
        world.cloud.behaviour = ANSWERS
        await world.think(1)

    story.act.append(action)


def _heartbeat_minutes(story: _Story, minutes: int) -> _Action:
    async def action(world: HealthWorld) -> None:
        for _ in range(minutes):
            world.clock.advance(60)
            story.heartbeat_calls.append(await world.heartbeat_runs())

    return action


@when("heartbeat работает 10 минут, а часы Боба идут шагами по минуте")
def heartbeat_ten_minutes(story: _Story) -> None:
    story.act.append(_heartbeat_minutes(story, 10))


@when(
    "облако снова отвечает, а heartbeat работает 2 минуты, и часы Боба идут шагами по минуте"
)
def cloud_returns_under_heartbeat(story: _Story) -> None:
    async def revive(world: HealthWorld) -> None:
        world.cloud.behaviour = ANSWERS

    story.act.append(revive)
    story.act.append(_heartbeat_minutes(story, 2))


@when("владелец спрашивает у GUPPI /status")
def owner_asks_status(story: _Story) -> None:
    async def action(world: HealthWorld) -> None:
        story.status_text = await world.guppi_status()

    story.act.append(action)


@when("гость пишет Бобу в его топик «Боб, привет!»")
def guest_writes_to_bob(story: _Story) -> None:
    async def action(world: HealthWorld) -> None:
        await world.app.event_bus.publish(
            MessageReceived(
                update_id=1,
                chat_id=GROUP_CHAT_ID,
                message_id=11,
                text="Боб, привет!",
                sender_id=777,
                sender_name="Гость",
                is_group=True,
                topic_id=BOB_TOPIC_ID,
            )
        )
        await _wait_for_a_line_in_the_room(world)

    story.act.append(action)


async def _wait_for_a_line_in_the_room(world: HealthWorld) -> None:
    """Ход гостя идёт фоновым обработчиком: ждём, пока в комнату что-то придёт, или предела."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TURN_WAIT_SECONDS
    while loop.time() < deadline:
        if _room_lines(world):
            return
        await asyncio.sleep(_TURN_WAIT_STEP_SECONDS)


def _room_lines(world: HealthWorld) -> list[str]:
    """Всё, что любой из двух ботов отправил в группу."""
    sent = [*world.bob_bot.sent, *world.guppi_bot.sent]
    return [line.text for line in sent if line.chat_id == GROUP_CHAT_ID]


# --- Тогда: личка владельца -------------------------------------------------------


@then("владелец получил ровно одно личное сообщение от бота Боба")
def exactly_one_owner_message(story: _Story) -> None:
    world = story.outcome()
    assert len(world.owner_messages) == 1, world.owner_texts()
    # Личка — это бот Боба: GUPPI владельцу в личку не пишет.
    assert not [line for line in world.guppi_bot.sent if line.chat_id == OWNER_ID]


@then(
    parsers.parse(
        "это сообщение пришло на {failure:d}-м отказе, через {minutes:d} минуты после первого"
    )
)
def message_came_on_failure(story: _Story, failure: int, minutes: int) -> None:
    message = story.outcome().owner_messages[0]
    assert message.after_failures == failure
    assert message.at - START == timedelta(minutes=minutes)


@then("в нём Боб от первого лица говорит, что не может думать, и называет код 403")
def message_says_cannot_think(story: _Story) -> None:
    text = story.outcome().owner_messages[0].text
    assert "я не могу думать" in text
    assert "403" in text


@then("Боб ни разу не остался без мысли")
def no_thought_failed(story: _Story) -> None:
    assert story.outcome().failed_thoughts == 0


@then("на отказ облака ответил дублёр — его позвали ровно один раз")
def understudy_answered_once(story: _Story) -> None:
    world = story.outcome()
    assert world.local.calls == 1
    assert world.cloud.calls == 10  # облако спрашивали каждый раз, дублёр — только на 503


@then("владелец не получил ни одного личного сообщения")
def no_owner_message(story: _Story) -> None:
    world = story.outcome()
    assert world.startup_messages == ()
    assert world.owner_messages == []


@then("после этого владелец получил ровно одно новое личное сообщение")
def one_new_owner_message(story: _Story) -> None:
    world = story.outcome()
    new = world.owner_messages[story.owner_messages_before_act :]
    assert len(new) == 1, [message.text for message in new]


@then(
    "в нём Боб говорит, что вернулся, и называет длительность простоя «2 часа 15 минут»"
)
def says_back_with_duration(story: _Story) -> None:
    world = story.outcome()
    text = world.owner_messages[story.owner_messages_before_act].text
    assert "я вернулся" in text
    assert "Молчал 2 часа 15 минут" in text


@then("в нём нет слов «не могу думать»")
def recovery_is_not_a_complaint(story: _Story) -> None:
    world = story.outcome()
    text = world.owner_messages[story.owner_messages_before_act].text
    assert "не могу думать" not in text


@then(parsers.parse("владелец получил {count:d} личных сообщения на {failures:d} отказов"))
def owner_messages_per_failures(story: _Story, count: int, failures: int) -> None:
    world = story.outcome()
    assert world.failed_thoughts == failures
    assert len(world.owner_messages) == count, world.owner_texts()


@then("между ними прошло 10 минут, а затем 1 час — интервал растёт")
def reminder_intervals_grow(story: _Story) -> None:
    moments = [message.at for message in story.outcome().owner_messages]
    gaps = [later - earlier for earlier, later in itertools.pairwise(moments)]
    assert gaps == [timedelta(minutes=10), timedelta(hours=1)]


@then("каждое сообщение после первого — напоминание, что Боб всё ещё не может думать")
def later_messages_are_reminders(story: _Story) -> None:
    texts = story.outcome().owner_texts()
    assert "я не могу думать" in texts[0]
    assert all("я всё ещё не могу думать" in text for text in texts[1:])


# --- Тогда: голос без дублёра --------------------------------------------------------


@then("в топике Боба появилось честное уведомление GUPPI, что Боб временно недоступен")
def honest_outage_notice(story: _Story) -> None:
    world = story.outcome()
    topic = [
        line.text
        for line in world.bob_bot.sent
        if line.chat_id == GROUP_CHAT_ID and line.topic_id == BOB_TOPIC_ID
    ]
    assert any(_GUPPI_OUTAGE_MARK in text for text in topic), _room_lines(world)


@then("чужим голосом за Боба в комнате никто не ответил")
def nobody_answered_for_bob(story: _Story) -> None:
    world = story.outcome()
    assert world.local.calls == 0  # дублёра нет — и подставного голоса нет
    assert all(_GUPPI_OUTAGE_MARK in text for text in _room_lines(world))


@then("внутренний монолог никому ничего не отправил")
def monologue_stays_silent(story: _Story) -> None:
    world = story.outcome()
    assert world.failed_thoughts == 5
    # До хода гостя в комнату не ушло ничего, а в личку — только сигнал владельцу.
    assert all(_GUPPI_OUTAGE_MARK in text for text in _room_lines(world))
    assert len(world.owner_messages) == 1


@then("владелец получил личное сообщение, что Боб не может думать")
def owner_told_cannot_think(story: _Story) -> None:
    texts = story.outcome().owner_texts()
    assert any("я не могу думать" in text for text in texts), texts


# --- Тогда: heartbeat и лог -----------------------------------------------------------


@then("облако позвали только на 1-й, 3-й и 8-й минуте — по одному разу")
def probes_on_schedule(story: _Story) -> None:
    story.outcome()
    calls = story.heartbeat_calls
    assert [calls[0], calls[2], calls[7]] == [1, 1, 1], calls


@then("в остальные минуты облако не позвали ни разу")
def no_calls_between_probes(story: _Story) -> None:
    story.outcome()
    calls = story.heartbeat_calls
    others = [count for minute, count in enumerate(calls, start=1) if minute not in {1, 3, 8}]
    assert others == [0] * 7, calls


def _degraded_lines(records: list[logging.LogRecord]) -> list[logging.LogRecord]:
    return [
        record
        for record in records
        if "LLM health tier0-primary: healthy → degraded" in record.getMessage()
    ]


@then("в логе ровно одна строка о переходе облака из «healthy» в «degraded»")
def one_transition_line(story: _Story) -> None:
    records = story.outcome().log.records
    lines = _degraded_lines(records)
    assert len(lines) == 1
    assert lines[0].exc_info is None


@then("с момента перехода ни одна строка лога не несёт стека")
def no_stack_after_transition(story: _Story) -> None:
    records = story.outcome().log.records
    start = records.index(_degraded_lines(records)[0])
    with_stack = [record.getMessage() for record in records[start:] if record.exc_info]
    assert with_stack == []


@then("каждый проваленный зонд — ровно одна строка INFO от heartbeat")
def one_info_line_per_failed_probe(story: _Story) -> None:
    world = story.outcome()
    after_act = world.log.records[story.log_index_before_act :]
    probe_lines = [
        record
        for record in after_act
        if record.name == "bob.application.runtime.heartbeat"
        and "heartbeat probe of tier0-primary failed" in record.getMessage()
    ]
    failed_probes = sum(story.heartbeat_calls)
    assert failed_probes == 3
    assert len(probe_lines) == failed_probes
    assert all(record.levelno == logging.INFO for record in probe_lines)
    # И ничего громче INFO от heartbeat за всё время в degraded: строки на тик нет.
    loud = [
        record
        for record in after_act
        if record.name == "bob.application.runtime.heartbeat" and record.levelno > logging.INFO
    ]
    assert loud == []


@then("владелец получил личное сообщение, что Боб вернулся")
def owner_told_back(story: _Story) -> None:
    world = story.outcome()
    new = world.owner_texts()[story.owner_messages_before_act :]
    assert len(new) == 1, new
    assert "я вернулся" in new[0]


@then("в каждую из этих минут облако зовут без ограничений — больше 10 раз за минуту")
def ordinary_rhythm(story: _Story) -> None:
    story.outcome()
    assert len(story.heartbeat_calls) == 2
    assert all(count > 10 for count in story.heartbeat_calls), story.heartbeat_calls


# --- Тогда: /status и память -------------------------------------------------------------


def _status_line(story: _Story, label: str) -> str:
    story.outcome()
    lines = [line for line in story.status_text.splitlines() if line.startswith(f"{label} — ")]
    assert len(lines) == 1, story.status_text
    return lines[0]


@then("в ответе GUPPI есть блок «LLM:»")
def status_has_llm_block(story: _Story) -> None:
    story.outcome()
    assert "\nLLM:\n" in story.status_text


@then("облако Tier-0 в нём деградировано с момента первого отказа, во времени машины Боба")
def status_names_since(story: _Story) -> None:
    line = _status_line(story, "tier0 облако")
    local_start = START.astimezone()  # пояс машины Боба, посчитанный мимо кода Боба
    offset = local_start.strftime("%z")
    expected = f"{local_start:%Y-%m-%d %H:%M} {offset[:3]}:{offset[3:]}"
    assert line.startswith(f"tier0 облако — деградирован с {expected} ("), line


@then("причина в нём названа словами «не пускало по ключу/квоте», и подряд 5 отказов")
def status_names_reason(story: _Story) -> None:
    line = _status_line(story, "tier0 облако")
    assert line.endswith("(не пускало по ключу/квоте, 5 подряд)"), line


@then("Tier-1 в нём «ок», а дублёра «нет»")
def status_other_providers(story: _Story) -> None:
    assert _status_line(story, "tier1") == "tier1 — ок"
    assert _status_line(story, "дублёр") == "дублёр — нет"


@then("в памяти Боба ровно один эпизод о простое")
def one_outage_episode(story: _Story) -> None:
    story.outcome()
    assert len(story.episodes) == 1, story.episodes


@then("он от первого лица: Боб молчал, облако не пускало его по ключу, теперь снова может")
def episode_in_first_person(story: _Story) -> None:
    story.outcome()
    content = str(story.episodes[0]["content"])
    assert re.search(r"я молчал .*\(2 часа 15 минут\)", content), content
    assert "облако не пускало меня по ключу" in content
    assert content.endswith("Теперь снова могу."), content


@then("этот эпизод виден только владельцу")
def episode_is_owner_private(story: _Story) -> None:
    story.outcome()
    assert story.episodes[0]["visibility"] == "owner_private"


# --- Тогда: старт без дублёра ------------------------------------------------------------


@then("при старте владелец получил одно личное сообщение, что Боб стартовал без дублёра")
def startup_message(story: _Story) -> None:
    world = story.outcome()
    assert len(world.startup_messages) == 1, world.startup_messages
    text = world.startup_messages[0]
    assert "я стартовал без дублёра" in text
    assert f"модели {UNDERSTUDY_MODEL} нет" in text


@then("к дублёру с просьбой подумать не обратились ни разу")
def understudy_never_asked(story: _Story) -> None:
    world = story.outcome()
    assert world.local.model_lookups == 1  # проверка при старте была — и только она
    assert world.local.calls == 0
    assert world.cloud.calls == 5


@then("когда облако легло, Боб сказал владельцу, что думать нечем и дублёра нет")
def mute_without_understudy(story: _Story) -> None:
    texts = story.outcome().owner_texts()
    assert len(texts) == 1, texts
    assert "я не могу думать" in texts[0]
    assert "Дублёра на этой машине нет" in texts[0]
