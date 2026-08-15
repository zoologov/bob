# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests: конфигурный потолок величины доезжает до ОБОИХ владельческих концов (BOB-096).

Концов два, и оба собираются композицией: реплика Боба (анонсёр) и список ``/rules``
(GUPPI). Судить о них по разным потолкам — значит показывать владельцу одно, а делать
другое, поэтому потолок здесь читается из ОДНОЙ секции конфига на всех потребителей.

🔴 Регрессия, найденная ревью на копии живой базы владельца. Вердикт «есть что
одобрять» (:func:`~bob.proactivity.self_improvement.is_actionable_proposal`) спрашивался
только при РОЖДЕНИИ правила, а пять правил владельца родились раньше него — и уезжали к
нему прежним путём. Голос среза 5 берёт из правила лишь рычаг и величину, поэтому пустая
поправка звучала как нормальное предложение: «Хочу чуть поправить тон. Попробуем?».

Поэтому здесь проверяется не «ключ прочитан», а ПОПЫТКА, наблюдаемая через границу:
собранный композицией анонсёр гоняется целиком (конфиг → use-case → домен → шлюз), и
утверждения читают только то, что владелец получил в чат, и то, что осталось в
хранилище. Потолок берётся из ТОЙ ЖЕ секции конфига, что и у детектора: судить о
рождении и о доставке по разным потолкам было бы двумя разными Бобами.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.event_bus import AsyncEventBus
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.runtime.wiring.self_improvement import _build_self_improvement
from bob.runtime.wiring.telegram import _build_multibot

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.application.usecases.handle_message import ReplyGateway
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.proactivity.adapters import SqliteSelfImprovementStore
    from bob.proactivity.adapters.proactivity_store import SqliteProactivityStore
    from bob.social.usecases import Authorizer

_NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
_CHAT_ID = 27468732
_OWNER_ID = 27468732
_GROUP_CHAT_ID = -1004372947307
#: Потолок величины из живого ``config/bob.yaml``.
_CEILING = 0.3


class _SilentProvider:
    """Провайдер тира: детектор в этих сценариях новых кандидатов не находит."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        del messages
        return "[]"


@dataclass
class _FakeGateway:
    """Фейк ровно одной вещи — Telegram: записывает, что ушло владельцу."""

    posts: list[str] = field(default_factory=list)

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> int | None:
        del chat_id, thinking
        self.posts.append(markdown)
        return 1


@dataclass
class _FakeRuleStore:
    """Хранилище правил, уже содержащее наследство: правила, родившиеся ДО фикса."""

    rules: tuple[ImprovementRule, ...] = ()

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:
        del persona_id
        return self.rules

    async def record_announce_attempt(self, persona_id: str, rule_id: str) -> None:
        del persona_id
        self._patch(rule_id, attempts_delta=1)

    async def mark_announced(self, persona_id: str, rule_id: str) -> None:
        del persona_id
        self._patch(rule_id, announced=True)

    def _patch(
        self, rule_id: str, *, announced: bool | None = None, attempts_delta: int = 0
    ) -> None:
        self.rules = tuple(
            rule
            if rule.id != rule_id
            else ImprovementRule(
                id=rule.id,
                observation=rule.observation,
                adjustment=rule.adjustment,
                lever=rule.lever,
                magnitude=rule.magnitude,
                state=rule.state,
                origin=rule.origin,
                created_at=rule.created_at,
                evidence=rule.evidence,
                announced=rule.announced if announced is None else announced,
                announce_attempts=rule.announce_attempts + attempts_delta,
            )
            for rule in self.rules
        )


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _rule(rid: str, *, adjustment: str = "Ужиматься к концу", magnitude: float) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Отвечаю длиннее, чем нужно, когда разговор долгий",
        adjustment=adjustment,
        lever=Lever.LENGTH,
        magnitude=magnitude,
        state=RuleState.PROPOSED,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
    )


async def _announce(
    rules: tuple[ImprovementRule, ...], *, config: Mapping[str, object]
) -> tuple[_FakeGateway, _FakeRuleStore]:
    """Собрать самоулучшение по конфигу и прогнать ОДИН проход анонсёра."""
    gateway = _FakeGateway()
    store = _FakeRuleStore(rules=rules)
    wired = _build_self_improvement(
        config,
        router=LLMRouter(providers={0: _SilentProvider(), 1: _SilentProvider()}),
        rule_store=cast("SqliteSelfImprovementStore", store),
        gateway=cast("ReplyGateway", gateway),
        chat_id=_CHAT_ID,
        clock=_FixedClock(),
    )
    assert wired.announce_rules is not None
    await wired.announce_rules.run()
    return gateway, store


@dataclass
class _RecordingBot:
    """Фейк Telegram-бота: записывает текст, который GUPPI отправил владельцу."""

    sends: list[str] = field(default_factory=list)

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[object]:
        del offset, timeout
        return []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> object:
        del chat_id, message_thread_id, reply_parameters
        self.sends.append(text)
        return _SentMessage()

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
        reply_parameters: object = None,
    ) -> object:  # pragma: no cover — GUPPI отвечает простым текстом
        del chat_id, rich_message, message_thread_id, reply_parameters
        raise NotImplementedError

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None
    ) -> bool:  # pragma: no cover — индикатор набора здесь ни при чём
        del chat_id, action, message_thread_id
        return True

    async def set_message_reaction(
        self,
        *,
        chat_id: int,
        message_id: int,
        reaction: object,
        message_thread_id: int | None = None,
    ) -> bool:  # pragma: no cover — реакции здесь ни при чём
        del chat_id, message_id, reaction, message_thread_id
        return True

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> object:  # pragma: no cover — паритет протокола
        del chat_id, photo, caption, message_thread_id
        raise NotImplementedError

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> object:  # pragma: no cover — паритет протокола
        del chat_id, document, caption, message_thread_id
        raise NotImplementedError


@dataclass
class _SentMessage:
    message_id: int = 1
    text: str | None = None
    message_thread_id: int | None = None


class _OwnerOnly:
    """Авторизация: ``/rules`` принимается только от владельца."""

    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(  # pragma: no cover — этот путь тесту не нужен
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


async def _rules_command(
    rules: tuple[ImprovementRule, ...], *, config: Mapping[str, object]
) -> tuple[_RecordingBot, AsyncEventBus]:
    """Собрать multibot по конфигу и дать владельцу набрать ``/rules``."""
    bus = AsyncEventBus()
    guppi_bot = _RecordingBot()
    multibot = _build_multibot(
        config,
        bus=bus,
        bob_bot=cast("BotLike", _RecordingBot()),
        guppi_bot=cast("BotLike", guppi_bot),
        authorizer=cast("Authorizer", _OwnerOnly()),
        proactivity_store=cast("SqliteProactivityStore", object()),
        proactivity_clock=_FixedClock(),
        rule_store=cast("SqliteSelfImprovementStore", _FakeRuleStore(rules=rules)),
    )
    guppi = multibot.guppi
    assert guppi is not None, "GUPPI не собрался — тест поехал не туда"
    consumed = await guppi.handle_general_command(
        text="/rules", user_id=_OWNER_ID, chat_id=_GROUP_CHAT_ID
    )
    assert consumed, "команда владельца не дошла до GUPPI"
    return guppi_bot, bus


async def test_a_degenerate_rule_already_in_the_store_is_not_voiced() -> None:
    # Ровно живое rule-20260806060649-0: пустая поправка, величина 0.0.
    gateway, _store = await _announce(
        (_rule("legacy", adjustment="", magnitude=0.0),),
        config={"self_improvement": {"max_magnitude": _CEILING}},
    )

    assert gateway.posts == []


async def test_a_rule_above_the_configured_ceiling_is_not_voiced() -> None:
    gateway, _store = await _announce(
        (_rule("bold", magnitude=0.7),),
        config={"self_improvement": {"max_magnitude": _CEILING}},
    )

    assert gateway.posts == []


async def test_the_configured_ceiling_is_the_one_delivery_judges_by() -> None:
    # КОНТРОЛЬ к тесту выше: та же величина при потолке 0.9 доезжает до владельца —
    # иначе проверка была бы вакуумной («по этой провязке не уезжает вообще ничего»).
    gateway, _store = await _announce(
        (_rule("bold", magnitude=0.7),),
        config={"self_improvement": {"max_magnitude": 0.9}},
    )

    assert len(gateway.posts) == 1


async def test_the_degenerate_rule_is_left_for_the_owner_to_decide() -> None:
    # Молчание — не удаление и не «уже сказали»: правило ждёт решения владельца.
    _gateway, store = await _announce(
        (_rule("legacy", adjustment="", magnitude=0.0),),
        config={"self_improvement": {"max_magnitude": _CEILING}},
    )

    assert store.rules[0].state is RuleState.PROPOSED
    assert store.rules[0].announced is False
    assert store.rules[0].announce_attempts == 0


# --- Второй конец: список /rules, собранный настоящей провязкой ----------------
#
# 🔴 Запись в конфиге без ВЫЗЫВАЮЩЕГО — не возможность (§0.3 п.10). Поэтому потолок
# проверяется не чтением, а тем, что владелец получил в ответ на настоящую команду.


async def test_the_owner_list_judges_by_the_configured_ceiling() -> None:
    # Список называет владельцу ОБА числа — запрошенное и разрешённое, — и оба
    # приезжают из настоящей провязки, а не из дефолта.
    bot, _bus = await _rules_command(
        (_rule("bold", magnitude=0.7),),
        config={
            "telegram": {"chat_id": _GROUP_CHAT_ID, "owner_id": _OWNER_ID},
            "self_improvement": {"max_magnitude": _CEILING},
        },
    )

    assert "просит 0.7 при потолке 0.3" in bot.sends[-1]


async def test_the_owner_list_follows_a_raised_ceiling() -> None:
    # КОНТРОЛЬ: та же величина при потолке 0.9 — нормальное предложение, метки нет.
    bot, _bus = await _rules_command(
        (_rule("bold", magnitude=0.7),),
        config={
            "telegram": {"chat_id": _GROUP_CHAT_ID, "owner_id": _OWNER_ID},
            "self_improvement": {"max_magnitude": 0.9},
        },
    )

    assert "просит" not in bot.sends[-1]
