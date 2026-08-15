# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты GUPPI self-improvement-команд (контроль owner) — BOB-028 .3.

Owner-only, в General-чате, по образцу /goals:
* ``/rules`` — список правил + состояния + рычаг;
* ``/rule approve <id>`` (PROPOSED→APPROVED) — ЕДИНСТВЕННЫЙ путь апрува
  (authz-before-autonomy);
* ``/rule reject <id>`` (PROPOSED→REJECTED);
* ``/rule pause|resume <id>`` (APPROVED↔PAUSED);
* ``/rule remove <id>`` (APPROVED/PAUSED→REMOVED);
* недопустимый переход → отказ (через can_transition), не форс;
* не-owner / чужой чат / не-команда — игнор и тишина (authz-инвариант BOB-019);
* правило НЕ даёт никаких прав/инструментов — только флип RuleState;
* BOB-096 срез 1: предложение, попытки доставки которого исчерпаны, помечено в списке —
  Боб о нём молчит, поэтому ``/rules`` — единственное место, где владелец его видит;
* BOB-096 фикс ревью: предложение, о котором Боб молчит по СОДЕРЖАНИЮ, помечено
  отдельно от недоставленного — и причина названа своя у каждого случая: «нечего
  одобрять» (пусто / нулевой наклон) против «просит N при потолке M» (содержание есть,
  величина выше разрешённой). Одна метка на оба случая назвала бы осмысленное
  предложение мусором и отняла бы у владельца настоящее решение.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.infrastructure.telegram.guppi import GuppiHandler
from bob.proactivity.rule_announcement import MAX_ANNOUNCE_ATTEMPTS
from bob.proactivity.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from aiogram.types import InputRichMessage

    from bob.infrastructure.telegram.gateway import UpdateLike

_CHAT_ID = -1004372947307
_OWNER_ID = 27468732
_STRANGER_ID = 555
_FOREIGN_CHAT_ID = -100999
_PERSONA = "bob"
_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)
#: Потолок величины из живого ``config/bob.yaml`` — с ним GUPPI и собирают.
_CEILING = 0.3


@dataclass
class _FakeMessage:
    message_id: int
    text: str | None
    message_thread_id: int | None = None


@dataclass
class _SendCall:
    chat_id: int
    text: str
    message_thread_id: int | None


@dataclass
class _FakeBot:
    sends: list[_SendCall] = field(default_factory=list)

    async def get_updates(
        self, *, offset: int, timeout: int  # noqa: ARG002
    ) -> Sequence[UpdateLike]:  # pragma: no cover
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.sends.append(
            _SendCall(chat_id=chat_id, text=text, message_thread_id=message_thread_id)
        )
        return _FakeMessage(message_id=0, text=text)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_chat_action(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        action: str,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:  # pragma: no cover
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: InputRichMessage,  # noqa: ARG002
        message_thread_id: int | None = None,# noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> _FakeMessage:  # pragma: no cover
        return _FakeMessage(message_id=0, text="")

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover


    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> _FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

@dataclass
class _FakeAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID

    async def is_authorized(
        self, *, user_id: int | None, chat_id: int
    ) -> bool:  # pragma: no cover
        raise NotImplementedError

    async def authorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError

    async def deauthorize(self, user_id: int) -> None:  # pragma: no cover
        raise NotImplementedError


@dataclass
class _FakeRuleStore:
    rules: dict[str, ImprovementRule] = field(default_factory=dict)
    moves: list[tuple[str, RuleState]] = field(default_factory=list)

    async def load(self, persona_id: str) -> tuple[ImprovementRule, ...]:  # noqa: ARG002
        return tuple(self.rules.values())

    async def update_rule_state(
        self, persona_id: str, rule_id: str, state: RuleState  # noqa: ARG002
    ) -> None:
        self.moves.append((rule_id, state))
        if rule_id in self.rules:
            self.rules[rule_id] = ImprovementRule(
                id=self.rules[rule_id].id,
                observation=self.rules[rule_id].observation,
                adjustment=self.rules[rule_id].adjustment,
                lever=self.rules[rule_id].lever,
                magnitude=self.rules[rule_id].magnitude,
                state=state,
                origin=self.rules[rule_id].origin,
                created_at=self.rules[rule_id].created_at,
                evidence=self.rules[rule_id].evidence,
            )


def _rule(
    rid: str = "r1",
    *,
    lever: Lever = Lever.TONE,
    state: RuleState = RuleState.PROPOSED,
    announced: bool = False,
    announce_attempts: int = 0,
    adjustment: str = "Добавить теплоты",
    magnitude: float = _CEILING,
) -> ImprovementRule:
    return ImprovementRule(
        id=rid,
        observation="Отвечаю слишком сухо",
        adjustment=adjustment,
        lever=lever,
        magnitude=magnitude,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_NOW,
        evidence="",
        announced=announced,
        announce_attempts=announce_attempts,
    )


def _build(
    *,
    rules: dict[str, ImprovementRule] | None = None,
    max_magnitude: float = _CEILING,
) -> tuple[GuppiHandler, _FakeBot, _FakeRuleStore]:
    bot = _FakeBot()
    rule_store = _FakeRuleStore(rules=rules or {})
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        rule_store=rule_store,
        rule_max_magnitude=max_magnitude,
        persona_id=_PERSONA,
    )
    return handler, bot, rule_store


async def _send(
    handler: GuppiHandler,
    text: str,
    *,
    user_id: int = _OWNER_ID,
    chat_id: int = _CHAT_ID,
) -> bool:
    return await handler.handle_general_command(
        text=text, user_id=user_id, chat_id=chat_id
    )


async def test_rules_lists_rules_with_state_and_lever() -> None:
    handler, bot, _store = _build(rules={"r1": _rule("r1", lever=Lever.HUMOR)})

    consumed = await _send(handler, "/rules")

    assert consumed
    text = bot.sends[-1].text
    assert "r1" in text
    assert "proposed" in text
    assert "humor" in text


async def test_rules_empty_when_no_rules() -> None:
    handler, bot, _store = _build(rules={})

    consumed = await _send(handler, "/rules")

    assert consumed
    assert "пока нет" in bot.sends[-1].text


async def test_rules_marks_an_undelivered_proposal() -> None:
    # BOB-096 срез 1: исчерпав попытки, Боб об этом правиле молчит — и именно поэтому
    # владелец обязан увидеть его тут, иначе предложение теряется молча.
    handler, bot, _store = _build(
        rules={
            "stuck": _rule("stuck", announce_attempts=MAX_ANNOUNCE_ATTEMPTS),
        }
    )

    consumed = await _send(handler, "/rules")

    assert consumed
    assert "не доставлено" in bot.sends[-1].text


async def test_rules_does_not_mark_a_delivered_proposal() -> None:
    handler, bot, _store = _build(
        rules={
            "heard": _rule(
                "heard", announced=True, announce_attempts=MAX_ANNOUNCE_ATTEMPTS
            ),
        }
    )

    await _send(handler, "/rules")

    assert "не доставлено" not in bot.sends[-1].text


async def test_rules_does_not_mark_a_proposal_still_being_tried() -> None:
    handler, bot, _store = _build(
        rules={"fresh": _rule("fresh", announce_attempts=MAX_ANNOUNCE_ATTEMPTS - 1)}
    )

    await _send(handler, "/rules")

    assert "не доставлено" not in bot.sends[-1].text


async def test_rules_does_not_mark_a_rule_the_owner_decided() -> None:
    handler, bot, _store = _build(
        rules={
            "done": _rule(
                "done",
                state=RuleState.REJECTED,
                announce_attempts=MAX_ANNOUNCE_ATTEMPTS,
            ),
        }
    )

    await _send(handler, "/rules")

    assert "не доставлено" not in bot.sends[-1].text


async def test_rule_approve_moves_proposed_to_approved() -> None:
    handler, _bot, store = _build(rules={"r1": _rule("r1", state=RuleState.PROPOSED)})

    consumed = await _send(handler, "/rule approve r1")

    assert consumed
    assert ("r1", RuleState.APPROVED) in store.moves


async def test_rule_reject_moves_proposed_to_rejected() -> None:
    handler, _bot, store = _build(rules={"r1": _rule("r1", state=RuleState.PROPOSED)})

    await _send(handler, "/rule reject r1")

    assert ("r1", RuleState.REJECTED) in store.moves


async def test_rule_pause_and_resume_round_trip() -> None:
    handler, _bot, store = _build(rules={"r1": _rule("r1", state=RuleState.APPROVED)})

    await _send(handler, "/rule pause r1")
    assert ("r1", RuleState.PAUSED) in store.moves

    await _send(handler, "/rule resume r1")
    assert ("r1", RuleState.APPROVED) in store.moves


async def test_rule_remove_moves_approved_to_removed() -> None:
    handler, _bot, store = _build(rules={"r1": _rule("r1", state=RuleState.APPROVED)})

    await _send(handler, "/rule remove r1")

    assert ("r1", RuleState.REMOVED) in store.moves


async def test_illegal_transition_is_rejected_not_forced() -> None:
    # SAFETY: approving an already-REJECTED (terminal) rule is illegal — the move is
    # rejected with a message, the store is never written (can_transition gate).
    handler, bot, store = _build(rules={"r1": _rule("r1", state=RuleState.REJECTED)})

    consumed = await _send(handler, "/rule approve r1")

    assert consumed
    assert store.moves == []
    assert "недопустим" in bot.sends[-1].text


async def test_unknown_rule_id_is_reported() -> None:
    handler, bot, store = _build(rules={})

    consumed = await _send(handler, "/rule approve nope")

    assert consumed
    assert store.moves == []
    assert "не найдено" in bot.sends[-1].text


async def test_unknown_rule_action_is_not_consumed() -> None:
    # A typo'd action must not be silently swallowed (returns False — not consumed).
    handler, _bot, store = _build(rules={"r1": _rule("r1")})

    consumed = await _send(handler, "/rule frobnicate r1")

    assert not consumed
    assert store.moves == []


async def test_non_owner_cannot_manage_rules() -> None:
    # SAFETY (guest invariant BOB-019): a non-owner never manages rules — silent, no move.
    handler, bot, store = _build(rules={"r1": _rule("r1", state=RuleState.PROPOSED)})

    consumed = await _send(handler, "/rule approve r1", user_id=_STRANGER_ID)

    assert not consumed
    assert store.moves == []
    assert bot.sends == []


async def test_foreign_chat_cannot_manage_rules() -> None:
    # SAFETY: even the owner only manages rules in General — a foreign chat is ignored.
    handler, bot, store = _build(rules={"r1": _rule("r1", state=RuleState.PROPOSED)})

    consumed = await _send(handler, "/rule approve r1", chat_id=_FOREIGN_CHAT_ID)

    assert not consumed
    assert store.moves == []
    assert bot.sends == []


async def test_bare_rule_command_shows_usage() -> None:
    # `/rule` with no action/id → the usage hint (consumed, no store write).
    handler, bot, store = _build(rules={"r1": _rule("r1")})

    consumed = await _send(handler, "/rule")

    assert consumed
    assert store.moves == []
    assert "Использование" in bot.sends[-1].text


async def test_rule_action_without_id_shows_usage() -> None:
    # `/rule approve` (action but no id) → usage hint, never a blind state move.
    handler, bot, store = _build(rules={"r1": _rule("r1")})

    consumed = await _send(handler, "/rule approve")

    assert consumed
    assert store.moves == []
    assert "Использование" in bot.sends[-1].text


async def test_unrelated_command_is_not_consumed_by_rules_dispatch() -> None:
    # A non-rule owner command reaches the rules dispatcher (store wired) but matches
    # neither /rules nor /rule → not consumed, no store write.
    handler, bot, store = _build(rules={"r1": _rule("r1")})

    consumed = await _send(handler, "/somethingelse")

    assert not consumed
    assert store.moves == []
    assert bot.sends == []


async def test_no_rule_store_means_commands_not_consumed() -> None:
    # Unwired (rule_store=None) → the rule commands are not consumed (behaviour as before).
    bot = _FakeBot()
    handler = GuppiHandler(
        bot=bot,
        authorizer=_FakeAuthorizer(),
        general_chat_id=_CHAT_ID,
        persona_id=_PERSONA,
    )

    consumed = await handler.handle_general_command(
        text="/rules", user_id=_OWNER_ID, chat_id=_CHAT_ID
    )

    assert not consumed


# --- BOB-096 фикс ревью: «нечего одобрять» — вторая метка списка ---------------


async def test_rules_marks_a_proposal_with_nothing_to_approve() -> None:
    # 🔴 Живое rule-20260806060649-0: пустая поправка, нулевой наклон. Боб о нём
    # молчит — значит владелец обязан увидеть его ЗДЕСЬ, названным честно.
    handler, bot, _store = _build(rules={"empty": _rule("empty", adjustment="", magnitude=0.0)})

    consumed = await _send(handler, "/rules")

    assert consumed
    assert "нечего одобрять" in bot.sends[-1].text


async def test_an_over_ceiling_proposal_is_not_called_garbage() -> None:
    # 🔴 Живые rule-20260806083754-1 / rule-20260813135602-*: поправка осмысленная
    # (47–74 символа), величина выше потолка. Назвать это «нечего одобрять» — соврать:
    # владелец решил бы, что модель опять выдала пустоту, и прошёл бы мимо.
    handler, bot, _store = _build(rules={"bold": _rule("bold", magnitude=0.7)})

    await _send(handler, "/rules")

    text = bot.sends[-1].text
    assert "нечего одобрять" not in text
    assert "просит" in text


async def test_an_over_ceiling_proposal_shows_both_numbers() -> None:
    # Владельцу нужна ровно та информация, из которой он примет решение: поднять
    # потолок или отклонить осознанно. Значит — и запрошенная величина, и потолок.
    handler, bot, _store = _build(rules={"bold": _rule("bold", magnitude=0.7)})

    await _send(handler, "/rules")

    assert "просит 0.7 при потолке 0.3" in bot.sends[-1].text


async def test_the_ceiling_guppi_was_wired_with_is_the_one_it_judges_by() -> None:
    # Потолок, с которым собрали GUPPI, и есть потолок метки: то же правило непригодно
    # при 0.3 и нормально при 0.9. Иначе список судил бы по чужому потолку.
    strict, strict_bot, _s = _build(
        rules={"r1": _rule("r1", magnitude=0.5)}, max_magnitude=_CEILING
    )
    loose, loose_bot, _l = _build(rules={"r1": _rule("r1", magnitude=0.5)}, max_magnitude=0.9)

    await _send(strict, "/rules")
    await _send(loose, "/rules")

    assert "просит 0.5 при потолке 0.3" in strict_bot.sends[-1].text
    assert "просит" not in loose_bot.sends[-1].text


async def test_an_actionable_proposal_is_not_marked() -> None:
    handler, bot, _store = _build(rules={"r1": _rule("r1")})

    await _send(handler, "/rules")

    text = bot.sends[-1].text
    assert "нечего одобрять" not in text
    assert "просит" not in text


async def test_a_degenerate_proposal_is_never_called_undelivered() -> None:
    # 🔴 Две разные вещи: «пробовали и не дошло» и «говорить не о чем». Владельцу
    # нельзя показывать вторую под именем первой — он ждал бы повторной доставки.
    handler, bot, _store = _build(
        rules={
            "empty": _rule(
                "empty",
                adjustment="",
                magnitude=0.0,
                announce_attempts=MAX_ANNOUNCE_ATTEMPTS,
            )
        }
    )

    await _send(handler, "/rules")

    text = bot.sends[-1].text
    assert "нечего одобрять" in text
    assert "не доставлено" not in text


async def test_a_degenerate_rule_the_owner_decided_is_not_marked() -> None:
    handler, bot, _store = _build(
        rules={"done": _rule("done", state=RuleState.REJECTED, adjustment="", magnitude=0.0)}
    )

    await _send(handler, "/rules")

    assert "нечего одобрять" not in bot.sends[-1].text


async def test_the_owner_still_sees_every_rule_he_has() -> None:
    # Молчание Боба — не удаление: все пять правил живой базы остаются в списке, и
    # причина молчания у каждого своя — один мусор и три «просит больше разрешённого».
    handler, bot, _store = _build(
        rules={
            "empty": _rule("empty", adjustment="", magnitude=0.0),
            "bold": _rule("bold", magnitude=0.4),
            "bolder": _rule("bolder", magnitude=0.5),
            "boldest": _rule("boldest", magnitude=0.7),
            "real": _rule("real", magnitude=0.2),
        }
    )

    await _send(handler, "/rules")

    text = bot.sends[-1].text
    for rule_id in ("empty", "bold", "bolder", "boldest", "real"):
        assert rule_id in text
    assert text.count("нечего одобрять") == 1
    assert text.count("просит") == 3
    assert "просит 0.4 при потолке 0.3" in text
    assert "просит 0.7 при потолке 0.3" in text
