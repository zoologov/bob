# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Харнесс сценариев «Боб предлагает поправить себя» (BOB-096, срезы 1/2/5).

Живой симптом, с которого начался эпик (owner, 6–12 августа 2026): «Заметил за собой:
Боб замечает, что его поведение часто повторяется**..** Предлагаю: **.** Включить?
(``/rule approve rule-…``)» — и так на КАЖДОМ reflect-тике шесть дней подряд, а каждый
перезапуск начинал комплект заново.

🔴 Что здесь настоящее, а что фейк — названо прямо:

* настоящий композиционный сборщик самоулучшения
  (:func:`~bob.runtime.wiring.self_improvement._build_self_improvement`), то есть
  ``detector_tier`` и ``max_magnitude`` приезжают из конфига ровно так, как в проде;
* настоящий детектор, настоящая отбраковка вырожденных кандидатов, настоящий анонсёр,
  настоящий голос (:mod:`bob.proactivity.rule_voice`);
* настоящая SQLite: правило и обе пометки доставки лежат в файле базы, а «перезапуск» —
  это ЗАКРЫТЬ базу и открыть заново, новым репо, новым стором, новым use-case'ом;
* настоящая команда владельца ``/rules`` (:class:`~bob.infrastructure.telegram.guppi.
  GuppiHandler`) — там владелец видит правило, о котором Боб уже молчит;
* фейка ровно два, и оба — граница мира: сеть (провайдер тира отдаёт заготовленный ответ
  модели) и Telegram (бот записывает отправленное вместо реальной отправки).

Сценарии утверждают только НАБЛЮДАЕМОЕ снаружи: что владелец получил в чат, что он видит
в ``/rules``, на какой тир ушёл запрос детектора и что пережило перезапуск. Ни одного
обращения к приватному состоянию.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

from bob.application.router.llm_router import LLMRouter
from bob.infrastructure.telegram.guppi import GuppiHandler
from bob.memory.adapters.sqlite_memory_repo import SqliteMemoryRepo
from bob.personality.voice import guppi_voice_canon
from bob.proactivity.adapters.self_improvement_store import SqliteSelfImprovementStore
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.runtime.wiring.self_improvement import (
    _build_self_improvement,
    _self_improvement_max_magnitude,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from aiogram.types import (
        BufferedInputFile,
        InputRichMessage,
        ReactionTypeEmoji,
        ReplyParameters,
    )

    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import ReplyGateway

# Живые адреса: личка владельца (её chat_id равен его user id) и General, где GUPPI
# отвечает на команды.
OWNER_ID = 27468732
OWNER_DM_CHAT_ID = OWNER_ID
GENERAL_CHAT_ID = -1004372947307
PERSONA = "bob"

#: Потолок величины из живого ``config/bob.yaml`` — сценарии про «сверх потолка»
#: отсчитывают от него.
CONFIGURED_CEILING = 0.3
#: Тир детектора из живого конфига (до BOB-096 у этого ключа не было ни одного читателя).
LIVE_DETECTOR_TIER = 1


def self_improvement_config(*, detector_tier: int) -> Mapping[str, object]:
    """Секция ``self_improvement`` формы живого ``config/bob.yaml``."""
    return {
        "self_improvement": {
            "detector_tier": detector_tier,
            "max_magnitude": CONFIGURED_CEILING,
        }
    }


_MOMENT = datetime(2026, 8, 12, 6, 6, 49, tzinfo=UTC)
#: Медленный кадэнс Боба: между тиками проходит время, и правила различимы по времени.
_TICK = timedelta(minutes=5)

# Что модель ответила детектору. Наблюдение непустое во ВСЕХ вариантах: разница ровно в
# том, есть ли в кандидате то, что владелец может осмысленно одобрить.
_OBSERVATION = "Отвечаю длиннее, чем нужно, когда разговор долгий"
_ADJUSTMENT = "Ужиматься к концу разговора"
_OTHER_OBSERVATION = "Жду, когда позовут, вместо того чтобы заговорить самому"
_OTHER_ADJUSTMENT = "Начинать разговор чаще"

NO_CANDIDATES = "[]"


def detector_says(
    *,
    observation: str = _OBSERVATION,
    adjustment: str = _ADJUSTMENT,
    lever: str = "length",
    magnitude: float = 0.2,
) -> str:
    """Ответ модели детектору — один кандидат заданной формы."""
    return json.dumps(
        [
            {
                "observation": observation,
                "adjustment": adjustment,
                "lever": lever,
                "magnitude": magnitude,
            }
        ],
        ensure_ascii=False,
    )


def another_detector_says() -> str:
    """Второй, СОДЕРЖАТЕЛЬНО ИНОЙ кандидат (дедуп такого не глушит)."""
    return detector_says(
        observation=_OTHER_OBSERVATION,
        adjustment=_OTHER_ADJUSTMENT,
        lever="proactivity",
        magnitude=0.2,
    )


#: Сырой текст детектора, который в живом дефекте попадал владельцу дословно.
DETECTOR_TEXT: tuple[str, ...] = (_OBSERVATION, _ADJUSTMENT)

def stored_rule(
    rid: str,
    *,
    adjustment: str = _ADJUSTMENT,
    magnitude: float = 0.2,
    minutes_old: int = 0,
) -> ImprovementRule:
    """Правило, лежащее в базе владельца ДО прогона (наследство, а не рождение).

    Такое правило родилось раньше отбраковки вырожденных кандидатов, поэтому оно
    существует в базе в любом виде — включая тот, который сегодня не родился бы.
    """
    return ImprovementRule(
        id=rid,
        observation=_OBSERVATION,
        adjustment=adjustment,
        lever=Lever.LENGTH,
        magnitude=magnitude,
        state=RuleState.PROPOSED,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_MOMENT - timedelta(minutes=minutes_old),
        evidence="",
    )


#: Слово из СОБСТВЕННОЙ формулировки Боба про рычаг «длина» — по нему видно, что он
#: говорит именно о той черте, а не общей запасной фразой «заметил кое-что».
LENGTH_LEVER_MARKER = "длиннее"


class _ScriptedTier:
    """Фейк ровно одной вещи — сети: отдаёт заготовленный ответ модели."""

    def __init__(self, reply: str) -> None:
        self._reply = reply
        self.payloads: list[str] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        self.payloads.append("\n".join(m.get("content", "") for m in messages))
        return self._reply


@dataclass
class _RecordingChat:
    """Фейк Telegram: записывает, что Боб отправил владельцу; умеет ломаться."""

    broken_attempts: int = 0
    posts: list[str] = field(default_factory=list)
    chat_ids: list[int] = field(default_factory=list)
    attempts: int = 0

    async def reply(
        self,
        *,
        chat_id: int,
        markdown: str,
        thinking: str | None = None,
    ) -> int | None:
        self.attempts += 1
        if self.attempts <= self.broken_attempts:
            # Ровно та форма отказа, что жила в логах те шесть дней.
            raise RuntimeError("bot bob poll failed (isolated): Request timeout")
        self.posts.append(markdown)
        self.chat_ids.append(chat_id)
        return 1


class _TickingClock:
    """Часы медленного кадэнса: каждый взгляд на них — следующий тик."""

    def __init__(self) -> None:
        self._now = _MOMENT

    def now(self) -> datetime:
        moment = self._now
        self._now += _TICK
        return moment


@dataclass
class _SentMessage:
    """Минимальная замена aiogram-сообщения: GUPPI смотрит только на id."""

    message_id: int = 0
    text: str | None = None
    message_thread_id: int | None = None


@dataclass
class _OwnerBot:
    """Бот GUPPI: записывает ответы на команды владельца (``/rules``)."""

    sent: list[str] = field(default_factory=list)

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:
        del offset, timeout
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: ReplyParameters | None = None,
    ) -> _SentMessage:
        del chat_id, reply_parameters
        self.sent.append(text)
        return _SentMessage(text=text, message_thread_id=message_thread_id)

    async def send_rich_message(  # pragma: no cover — GUPPI отвечает простым текстом
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
        reply_parameters: ReplyParameters | None = None,
    ) -> _SentMessage:
        del chat_id, rich_message, message_thread_id, reply_parameters
        raise NotImplementedError

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:  # pragma: no cover — сценарии команд индикатор набора не трогают
        del chat_id, action, message_thread_id
        return True

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: Sequence[ReactionTypeEmoji],
        message_thread_id: int | None = None,
    ) -> bool:  # pragma: no cover — реакции здесь ни при чём
        del chat_id, message_id, reaction, message_thread_id
        return True

    async def send_photo(  # pragma: no cover — паритет протокола, не путь сценария
        self,
        *,
        chat_id: int,
        photo: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _SentMessage:
        del chat_id, photo, caption, message_thread_id
        raise NotImplementedError

    async def send_document(  # pragma: no cover — паритет протокола, не путь сценария
        self,
        *,
        chat_id: int,
        document: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _SentMessage:
        del chat_id, document, caption, message_thread_id
        raise NotImplementedError


class _OwnerOnly:
    """Авторизация: команды ``/rules`` принимаются только от владельца."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == OWNER_ID

    async def is_authorized(  # pragma: no cover — этот путь сценариям не нужен
        self, *, user_id: int | None, chat_id: int
    ) -> bool:
        del user_id, chat_id
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:  # pragma: no cover
        del user_id
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover
        del user_id
        raise NotImplementedError


@dataclass(slots=True)
class ProposalRun:
    """Как сценарий ставит прогон: что отвечает модель и что с транспортом."""

    #: Ответ модели детектору по запускам: последний повторяется на всех дальнейших.
    detector_replies: tuple[str, ...] = (NO_CANDIDATES,)
    #: Сколько раз за один запуск Боб проводит тик самонаблюдения (детектор + анонс).
    ticks_per_start: int = 1
    #: Сколько ПЕРЕЗАПУСКОВ процесса после первого (база та же, объекты новые).
    restarts: int = 0
    #: Сколько первых попыток отправки транспорт роняет (0 — исправен).
    broken_attempts: int = 0
    #: ``self_improvement.detector_tier`` из конфига этого прогона.
    detector_tier: int = LIVE_DETECTOR_TIER
    #: Правила, УЖЕ лежащие в базе до первого тика — наследство владельца: они родились
    #: раньше, чем появилась отбраковка вырожденных предложений, и живут в его базе.
    preexisting_rules: tuple[ImprovementRule, ...] = ()


@dataclass(slots=True)
class ProposalOutcome:
    """Что увидел владелец и что пережило перезапуск."""

    #: Сообщения, дошедшие до владельца, в порядке отправки.
    said_to_owner: tuple[str, ...] = ()
    #: Чаты, в которые они ушли, — предложение адресовано лично владельцу.
    chats: tuple[int, ...] = ()
    #: Сколько раз транспорт вообще дёрнули, включая упавшие попытки.
    send_attempts: int = 0
    #: Ответ GUPPI на владельческое ``/rules`` — единственное место, где владелец видит
    #: правило, о котором Боб уже молчит.
    rules_listing: str = ""
    #: Правила, пережившие последний перезапуск (читаются из файла базы).
    stored: tuple[ImprovementRule, ...] = ()
    #: Что уехало модели на каждом тире — и, значит, на каком тире работал детектор.
    tier0_saw: tuple[str, ...] = ()
    tier1_saw: tuple[str, ...] = ()


class _Process:
    """Один «запуск процесса»: своё соединение с базой, своя сборка самоулучшения."""

    def __init__(
        self,
        db: Path,
        *,
        chat: _RecordingChat,
        clock: _TickingClock,
        detector_reply: str,
        detector_tier: int,
    ) -> None:
        self._repo = SqliteMemoryRepo(db)
        self._chat = chat
        self._clock = clock
        self._detector_tier = detector_tier
        self.tier0 = _ScriptedTier(detector_reply)
        self.tier1 = _ScriptedTier(detector_reply)

    async def __aenter__(self) -> _Process:
        await self._repo.initialize()
        self.store = SqliteSelfImprovementStore(self._repo)
        self._wired = _build_self_improvement(
            self_improvement_config(detector_tier=self._detector_tier),
            router=LLMRouter(
                providers={0: self.tier0, 1: self.tier1}, voice_canon=guppi_voice_canon
            ),
            rule_store=self.store,
            gateway=cast("ReplyGateway", self._chat),
            chat_id=OWNER_DM_CHAT_ID,
            clock=self._clock,
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._repo.close()

    async def self_observation_tick(self) -> None:
        """Медленный тик Боба в том же порядке, в каком его гоняет heartbeat."""
        assert self._wired.detect_patterns is not None, "детектор не собрался"
        assert self._wired.announce_rules is not None, "анонсёр не собрался"
        await self._wired.detect_patterns.run()
        await self._wired.announce_rules.run()

    async def rules_command(self) -> str:
        """Владелец набрал ``/rules`` — вернуть то, что ответил ему GUPPI."""
        bot = _OwnerBot()
        handler = GuppiHandler(
            bot=bot,
            authorizer=_OwnerOnly(),
            general_chat_id=GENERAL_CHAT_ID,
            rule_store=self.store,
            # Тот же потолок из того же конфига, что и у анонсёра (так его раздаёт
            # настоящая провязка): список обязан судить о правиле так же, как Боб.
            rule_max_magnitude=_self_improvement_max_magnitude(
                self_improvement_config(detector_tier=self._detector_tier)
            ),
            persona_id=PERSONA,
        )
        consumed = await handler.handle_general_command(
            text="/rules", user_id=OWNER_ID, chat_id=GENERAL_CHAT_ID
        )
        assert consumed, "команда владельца не дошла до GUPPI — сценарий поехал не туда"
        return "\n".join(bot.sent)


async def run_self_observation(run: ProposalRun, *, db_root: Path) -> ProposalOutcome:
    """Прогнать тики самонаблюдения (с перезапусками) и вернуть наблюдаемое снаружи."""
    db = db_root / "bob.db"
    chat = _RecordingChat(broken_attempts=run.broken_attempts)
    clock = _TickingClock()
    outcome = ProposalOutcome()
    tier0: list[str] = []
    tier1: list[str] = []
    for start in range(run.restarts + 1):
        reply = run.detector_replies[min(start, len(run.detector_replies) - 1)]
        async with _Process(
            db,
            chat=chat,
            clock=clock,
            detector_reply=reply,
            detector_tier=run.detector_tier,
        ) as process:
            if start == 0:
                for legacy in run.preexisting_rules:
                    await process.store.save_rule(PERSONA, legacy)
            for _tick in range(run.ticks_per_start):
                await process.self_observation_tick()
            outcome.rules_listing = await process.rules_command()
            outcome.stored = await process.store.load(PERSONA)
            tier0.extend(process.tier0.payloads)
            tier1.extend(process.tier1.payloads)
    outcome.said_to_owner = tuple(chat.posts)
    outcome.chats = tuple(chat.chat_ids)
    outcome.send_attempts = chat.attempts
    outcome.tier0_saw = tuple(tier0)
    outcome.tier1_saw = tuple(tier1)
    return outcome
