# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for HandleMessage — the full message→reply→persist flow on fakes.

Everything external is faked: a captured LLM provider (no network), a fake
Telegram bot (no Telegram), and an in-memory repo/recall. The test asserts the
whole perceive→decide→act path: mood update → recent history + recall + context
→ Tier 1 reply (selective redaction) → streamed reply out → episode + mood
persisted. The privacy invariant is Variant 2: conversation/memory IS allowed to
reach the Tier 1 reply (it shapes Bob's reply and returns to that same user);
only genuinely-internal ``private_context`` stays Tier-0-only.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.events import MessageReceived
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.handle_message import (
    EngagementState,
    HandleMessage,
    OwnerActivityRecorder,
    PersonalityState,
    _recalled_bob_replies,
    _recalled_without_copied_exemplars,
    _recent_bob_replies,
)
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.personality.addressivity import AddressivityThresholds
from bob.domain.personality.conversation import RepeatThresholds
from bob.domain.personality.conversation_floor import (
    ConversationFloor,
    FloorConfig,
    FloorHolder,
    idle_floor,
)
from bob.domain.personality.engagement import (
    ConversationalFatigue,
    EngagementThresholds,
    FatigueRates,
)
from bob.domain.personality.expression import ExpressionFreqs
from bob.domain.personality.fascination import Fascination
from bob.domain.personality.interlocutor import (
    Interlocutor,
    InterlocutorKind,
    Trust,
)
from bob.domain.personality.mood import Mood
from bob.domain.personality.negotiation import NegotiationZone, Stance
from bob.domain.personality.reaction import (
    STANDARD_REACTION_EMOJI,
    reaction_emoji_for,
)
from bob.domain.personality.relationship import Relationship
from bob.domain.personality.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.domain.personality.soul import SOUL
from bob.domain.personality.sulk import SulkState
from bob.domain.personality.taste import TasteAxis, TasteEngine, Verdict
from bob.domain.ports import ToolCall, ToolCallResult
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from bob.domain.ports import (
        LLMMessage,
        Permission,
        Recalled,
        ToolCallingProvider,
        ToolDefinition,
        ZoneClassifier,
    )
    from bob.infrastructure.telegram.gateway import UpdateLike

_PHANTOM_PREF = "phantom-coffee-craving"  # shareable taste material (shapes the reply)
_RECALL_MEMORY = "the user said earlier they enjoy pour-over"  # shareable recalled memory
# A prior turn already on record: the user told Bob their name (must reach the reply).
_PRIOR_TURN = "Ada: my name is Ada\nbob: nice to meet you"


class FixedClock:
    """Clock returning a fixed timezone-aware instant (deterministic tests)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class CapturingProvider:
    """Fake LLMProvider that records every payload it is asked to complete.

    ``replies`` lets a single provider answer successive calls differently (the
    Tier 0 provider serves both sentiment and fact extraction in one turn); when
    exhausted it falls back to the last reply.
    """

    def __init__(self, *, reply: str, replies: Sequence[str] | None = None) -> None:
        self.reply = reply
        self._replies = list(replies) if replies is not None else None
        self._call = 0
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        if self._replies is None:
            return self.reply
        index = min(self._call, len(self._replies) - 1)
        self._call += 1
        return self._replies[index]

    @property
    def all_text(self) -> str:
        """Concatenated content of every message ever sent to this provider."""
        return "\n".join(m["content"] for payload in self.payloads for m in payload)


class FakeMessage:
    """A minimal Telegram message with a stable id (the committed reply)."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


class FakeBot:
    """Fake aiogram bot capturing the reply (no network).

    BOB-008 (Variant A): the gateway shows a "typing…" indicator while it assembles
    the reply, then commits one rich final via ``send_rich_message`` (recorded in
    ``sent``); ``send_chat_action`` records the typing pings. The plain
    ``send_message`` remains as the rich-failure safety net.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.typings: int = 0

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=777)

    async def set_message_reaction(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        message_id: int,  # noqa: ARG002
        reaction: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        # BOB-018: react-only seam; fakes accept the BotLike reaction call.
        return True

    async def send_chat_action(
        self, *, chat_id: int, action: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> bool:
        self.typings += 1
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> FakeMessage:
        markdown = getattr(rich_message, "markdown", "")
        self.sent.append((chat_id, markdown))
        return FakeMessage(message_id=777)

    @property
    def final_text(self) -> str:
        """The committed reply text (the full reply sent via the rich final)."""
        return self.sent[-1][1] if self.sent else ""


class FakeRepo:
    """In-memory MemoryRepo: writes episodes/mood and reads recent history.

    ``history`` seeds prior turns so ``recent_episodes`` can replay them — this
    is how a name said one message ago reaches the next reply's context.
    """

    def __init__(self, *, history: Sequence[Mapping[str, object]] = ()) -> None:
        self.episodes: list[Mapping[str, object]] = []
        self.facts: list[object] = []
        self.mood: Mapping[str, object] | None = None
        self._history: list[Mapping[str, object]] = list(history)

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)

    async def save_fact(self, fact: object) -> None:
        self.facts.append(fact)

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None:  # noqa: ARG002
        self.mood = state

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        return self._history[-k:] if k > 0 else []


class FakeRecall:
    """Recall returning a canned (shareable) recalled memory.

    ``hits`` overrides the canned result so a test can model a strong real past
    moment, a weak/empty recall (no-op grounding), or anything in between.
    """

    def __init__(
        self,
        *,
        hits: Sequence[Recalled] | None = None,
        old_hits: Sequence[Recalled] | None = None,
    ) -> None:
        self._hits: Sequence[Recalled] = (
            hits if hits is not None else [{"content": _RECALL_MEMORY, "category": "personal"}]
        )
        # When set, recall returns these only when surface_old=True (an old-but-relevant
        # deep cut), modelling the hybrid recall's age blend; the default call still
        # returns ``hits``. Records every surface_old flag seen for assertions.
        self._old_hits = old_hits
        self.surface_old_calls: list[bool] = []

    async def recall(
        self, query: str, *, k: int, surface_old: bool = False
    ) -> Sequence[Recalled]:
        del query, k  # this fake ignores the topic/limit, modelling only the age blend
        self.surface_old_calls.append(surface_old)
        if surface_old and self._old_hits is not None:
            return list(self._old_hits)
        return list(self._hits)


class _FakeReflectionReader:
    """A ReflectionReader double returning a canned latest real reflection (or none)."""

    def __init__(self, *, text: str | None = None) -> None:
        self._text = text

    async def latest_reflection_text(self) -> str | None:
        return self._text


class _FakeFascinationReader:
    """A CurrentFascinationReader double returning a canned current passion (or none)."""

    def __init__(self, *, fascination: Fascination | None = None) -> None:
        self._fascination = fascination

    async def current_fascination(self) -> Fascination | None:
        return self._fascination


class _RecordingReactor:
    """A MessageReactor double recording each (chat_id, message_id, emoji) call."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, str]] = []

    async def react(self, *, chat_id: int, message_id: int, emoji: str) -> None:
        self.calls.append((chat_id, message_id, emoji))


def _moment() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _soul() -> SOUL:
    baseline = Mood(valence=0.1, social=0.2)
    taste = TasteEngine(axes=(TasteAxis(name="coffee", value=0.9, conviction=0.8),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=(_PHANTOM_PREF,),
    )


class _StubZoneClassifier:
    """A ZoneClassifier double that always returns one preset zone.

    Lets the integration test pin the negotiation zone deterministically so the
    Stance→directive mapping in the prompt can be asserted without depending on
    the heuristic's keyword/threshold details (covered by its own unit tests).
    """

    def __init__(self, zone: NegotiationZone) -> None:
        self._zone = zone
        self.seen: list[tuple[str, Verdict, float]] = []

    def classify(
        self, topic: str, *, taste_verdict: Verdict, conviction: float
    ) -> NegotiationZone:
        self.seen.append((topic, taste_verdict, conviction))
        return self._zone


class _FakeSelfImprovement:
    """A SelfImprovementReader double returning a fixed set of rules (BOB-028 .3).

    The use-case re-filters to APPROVED via ``active_rules`` before applying, so a test
    can pass PROPOSED/PAUSED rules and assert they NEVER tilt behaviour (authz-before-
    autonomy). Unwired (``self_improvement=None`` in ``_build``) → no rules at all.
    """

    def __init__(self, rules: tuple[ImprovementRule, ...] = ()) -> None:
        self._rules = rules

    async def active(self) -> tuple[ImprovementRule, ...]:
        return self._rules


def _si_rule(
    rid: str,
    *,
    lever: Lever,
    magnitude: float = 0.3,
    state: RuleState = RuleState.APPROVED,
    adjustment: str = "",
) -> ImprovementRule:
    """Build an ImprovementRule for the self-improvement application tests."""
    return ImprovementRule(
        id=rid,
        observation="наблюдение",
        adjustment=adjustment,
        lever=lever,
        magnitude=magnitude,
        state=state,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_moment(),
        evidence="",
    )


class _FakeFloorStore:
    """In-memory ConversationFloorStore double (BOB-025 floor integration).

    Seeds an initial floor (default IDLE) for the (chat_id, thread_id) the turn
    touches, records every ``save`` so a test can assert the floor advanced as
    expected, and exposes ``loaded`` / ``saved`` for inspection. ``load`` returns
    the seeded floor for an unseen key (a fresh thread starts IDLE).
    """

    def __init__(self, *, initial: ConversationFloor | None = None) -> None:
        self._initial = initial if initial is not None else idle_floor()
        self._store: dict[tuple[int, int | None], ConversationFloor] = {}
        self.loaded: list[tuple[int, int | None]] = []
        self.saved: list[tuple[int, int | None, ConversationFloor]] = []

    async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:
        self.loaded.append((chat_id, thread_id))
        return self._store.get((chat_id, thread_id), self._initial)

    async def save(
        self, chat_id: int, thread_id: int | None, floor: ConversationFloor
    ) -> None:
        self._store[(chat_id, thread_id)] = floor
        self.saved.append((chat_id, thread_id, floor))


def _live_bob_floor(moment: datetime | None = None) -> ConversationFloor:
    """A floor where Bob currently holds the talking turn (since=now, not timed out)."""
    return ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=moment if moment is not None else _moment(),
        idle_streak=0,
    )


def _build(
    *,
    reply: str,
    history: Sequence[Mapping[str, object]] = (),
    tier0_replies: Sequence[str] | None = None,
    tier1_replies: Sequence[str] | None = None,
    registry: CapabilityRegistry | None = None,
    tool_provider: ToolCallingProvider | None = None,
    owner_activity: OwnerActivityRecorder | None = None,
    zone_classifier: ZoneClassifier | None = None,
    soul: SOUL | None = None,
    rng: Random | None = None,
    expression_freqs: ExpressionFreqs | None = None,
    reactor: _RecordingReactor | None = None,
    recall: FakeRecall | None = None,
    reflection: _FakeReflectionReader | None = None,
    fascination: _FakeFascinationReader | None = None,
    surface_old_freq: float | None = None,
    perceive_sender: _FakeInterlocutorResolver | None = None,
    first_impression: _FakeFirstImpression | None = None,
    relationship: _FakeRelationship | None = None,
    sulk: _FakeSulk | None = None,
    engagement_state: EngagementState | None = None,
    engagement_thresholds: EngagementThresholds | None = None,
    fatigue_rates: FatigueRates | None = None,
    clock: FixedClock | None = None,
    bob_user_id_source: Callable[[], int | None] | None = None,
    addressivity_thresholds: AddressivityThresholds | None = None,
    length_guard_enabled: bool = False,
    length_guard_max_chars: int = 280,
    repeat_thresholds: RepeatThresholds | None = None,
    floor_store: _FakeFloorStore | None = None,
    floor_config: FloorConfig | None = None,
    floor_enabled: bool = True,
    self_improvement: _FakeSelfImprovement | None = None,
    self_improvement_max_magnitude: float = 0.3,
) -> tuple[HandleMessage, FakeBot, FakeRepo, CapturingProvider]:
    tier0 = CapturingProvider(reply="positive", replies=tier0_replies)
    tier1 = CapturingProvider(reply=reply, replies=tier1_replies)
    router = LLMRouter(providers={0: tier0, 1: tier1})
    clock = clock if clock is not None else FixedClock(_moment())
    bot = FakeBot()
    repo = FakeRepo(history=history)
    gateway = TelegramGateway(
        bot=bot,
        bus=_NullBus(),
        poll_timeout=1,
        typing_interval=4.0,
        clock=lambda: 0.0,
        sleep=_parking_sleep,
    )
    handler = HandleMessage(
        router=router,
        gateway=gateway,
        recall=recall if recall is not None else FakeRecall(),
        repo=repo,
        episodes=repo,
        update_mood=UpdateMoodFromText(router=router, clock=clock),
        extract_facts=ExtractFacts(router=router, repo=repo, clock=clock),
        clock=clock,
        state=PersonalityState(soul=soul if soul is not None else _soul()),
        registry=registry,
        tool_provider=tool_provider,
        owner_activity=owner_activity,
        zone_classifier=zone_classifier,
        rng=rng if rng is not None else Random(0),
        expression_freqs=expression_freqs,
        reactor=reactor,
        reflection=reflection,
        fascination=fascination,
        surface_old_freq=surface_old_freq if surface_old_freq is not None else 0.0,
        perceive_sender=perceive_sender,
        first_impression=first_impression,
        relationship=relationship,
        sulk=sulk,
        engagement_state=engagement_state,
        engagement_thresholds=engagement_thresholds,
        fatigue_rates=fatigue_rates,
        bob_user_id_source=bob_user_id_source,
        addressivity_thresholds=addressivity_thresholds,
        length_guard_enabled=length_guard_enabled,
        length_guard_max_chars=length_guard_max_chars,
        repeat_thresholds=repeat_thresholds,
        floor_store=floor_store,
        floor_config=floor_config,
        floor_enabled=floor_enabled,
        self_improvement=self_improvement,
        self_improvement_max_magnitude=self_improvement_max_magnitude,
    )
    return handler, bot, repo, tier1


async def _parking_sleep(_seconds: float) -> None:
    # Drive the typing keepalive deterministically with NO busy-spin: the
    # context manager fires the up-front "typing…" before its first ``_sleep``,
    # so by the time the keepalive reaches here typing has already landed. This
    # fake then parks forever (until the keepalive task is cancelled on context
    # exit), so the ``while True`` loop runs a bounded number of iterations and
    # never starves the event loop. A no-op ``async def f(): pass`` here would
    # spin the loop at 100% CPU and hang the suite.
    await asyncio.Event().wait()


class _NullBus:
    async def publish(self, event: object) -> None:  # noqa: ARG002
        return None

    def subscribe(self, event_name: str, handler: object) -> None:  # noqa: ARG002
        return None


class _RaiseOnceEpisodes:
    """An episodes reader that raises on its FIRST read, then replays empty history.

    Models a flaky history read inside the addressivity gate: the first
    ``recent_episodes`` call (the addressivity ``_others_present`` read) raises, so
    the gate must degrade to a 1:1 read; later reads succeed (empty), so the rest of
    the turn proceeds normally and can be asserted end to end.
    """

    def __init__(self) -> None:
        self._calls = 0

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:  # noqa: ARG002
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("history store unavailable")
        return []


def _build_with_episodes(
    *,
    reply: str,
    episodes: _RaiseOnceEpisodes,
) -> tuple[HandleMessage, FakeBot, FakeRepo, CapturingProvider]:
    """Build a handler with a custom episodes reader (writer stays the in-memory repo)."""
    tier0 = CapturingProvider(reply="positive")
    tier1 = CapturingProvider(reply=reply)
    router = LLMRouter(providers={0: tier0, 1: tier1})
    clock = FixedClock(_moment())
    bot = FakeBot()
    repo = FakeRepo()
    gateway = TelegramGateway(
        bot=bot,
        bus=_NullBus(),
        poll_timeout=1,
        typing_interval=4.0,
        clock=lambda: 0.0,
        sleep=_parking_sleep,
    )
    handler = HandleMessage(
        router=router,
        gateway=gateway,
        recall=FakeRecall(),
        repo=repo,
        episodes=episodes,
        update_mood=UpdateMoodFromText(router=router, clock=clock),
        extract_facts=ExtractFacts(router=router, repo=repo, clock=clock),
        clock=clock,
        state=PersonalityState(soul=_soul()),
        rng=Random(0),
    )
    return handler, bot, repo, tier1


# A complex default message (depth keyword "расскажи" + "подробно") so the hybrid
# reply selector routes the default turn to the quality Tier 1 (plus) model — the
# tier most of these flow tests assert against. Tier-specific behaviour is covered
# by the dedicated casual/complex tests above.
def _message(text: str = "расскажи подробно про кофе") -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=555,
        message_id=10,
        text=text,
        sender_id=99,
        sender_name="Ada",
    )


async def test_handle_sends_reply_back_to_telegram() -> None:
    # Arrange
    handler, bot, _repo, _tier1 = _build(reply="Coffee is the best.")

    # Act
    await handler.handle(_message())

    # Assert: the reply was committed as one rich final into Bob's chat.
    assert bot.sent
    assert bot.sent[-1][0] == 555
    assert bot.final_text == "Coffee is the best."


async def test_handle_shows_typing_during_generation_then_one_final() -> None:
    # BOB-009: the slow generation runs inside the typing keepalive, so at least one
    # "Bob is typing…" action fires before the (single) rich final is committed.
    handler, bot, _repo, _tier1 = _build(reply="thinking it over")

    await handler.handle(_message())

    assert bot.typings >= 1, "no typing indicator fired during generation"
    # Exactly one committed reply (one rich final), and the keepalive left no task.
    assert len(bot.sent) == 1
    assert bot.final_text == "thinking it over"
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    assert pending == [], "the typing keepalive task leaked past the turn"


async def test_handle_persists_episode_and_mood() -> None:
    # Arrange
    handler, _bot, repo, _tier1 = _build(reply="ok")

    # Act
    await handler.handle(_message())

    # Assert: an episode and the new mood were persisted.
    assert len(repo.episodes) == 1
    assert repo.episodes[0]["content"]
    assert repo.mood is not None


async def test_reply_uses_tier1_provider() -> None:
    # Arrange
    handler, _bot, _repo, tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message())

    # Assert: the user-facing reply went to the Tier 1 (API) provider.
    assert len(tier1.payloads) == 1


async def test_casual_reply_runs_on_the_fast_tier0_model() -> None:
    # Arrange (BOB-006): a casual short message should answer on the fast Tier 0
    # (flash) model for responsiveness, NOT the slow Tier 1 (plus) model.
    handler, bot, _repo, tier1 = _build(reply="plus")

    # Act
    await handler.handle(_message("привет!"))

    # Assert: Tier 1 (plus) was NOT used for the reply; the turn still completed.
    assert tier1.payloads == []
    assert bot.sent


async def test_complex_reply_escalates_to_the_quality_tier1_model() -> None:
    # Arrange: a depth-keyword message escalates to the quality Tier 1 (plus) model.
    handler, _bot, _repo, tier1 = _build(reply="a thorough answer")

    # Act
    await handler.handle(_message("объясни подробно как ты устроен"))

    # Assert: the reply went to the Tier 1 (plus) provider.
    assert len(tier1.payloads) == 1


async def test_long_reply_escalates_to_the_quality_tier1_model() -> None:
    # Arrange: a long message escalates to the quality model.
    handler, _bot, _repo, tier1 = _build(reply="long-form answer")

    # Act
    await handler.handle(_message("слово " * 80))

    # Assert
    assert len(tier1.payloads) == 1


async def test_recalled_memory_reaches_tier1_reply() -> None:
    # Arrange: recall carries a (shareable) recalled memory; SOUL carries phantom prefs.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message())

    # Assert (Variant 2): reply-shaping memory/taste DOES reach the Tier 1 reply.
    assert _RECALL_MEMORY in tier1.all_text
    assert _PHANTOM_PREF in tier1.all_text


async def test_reflection_episode_is_excluded_from_the_reply_recall_pool() -> None:
    # BOB-033 .3 containment: a reflection episode in the recall store NEVER becomes a
    # copyable exemplar in a user-facing reply (the inner life shapes tone via MOOD, not
    # by parroting reflection TEXT). A fact recalled alongside it still grounds the reply.
    reflection_text = "поймал себя на мысли, что всё тлен"
    fact_text = "Ada предпочитает чай"
    recall = FakeRecall(
        hits=[
            {"content": reflection_text, "category": "reflection", "source": "episodic"},
            {"content": fact_text, "category": "preference", "source": "semantic"},
        ]
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", recall=recall)

    await handler.handle(_message("объясни подробно, что ты думаешь"))

    folded = tier1.all_text
    assert reflection_text not in folded  # the reflection is contained
    assert fact_text in folded  # the fact still grounds the reply


async def test_leak_inner_life_still_surfaces_a_reflection_despite_containment() -> None:
    # The deliberate leak path (BOB-018) is UNTOUCHED by .3 containment: it reaches the
    # latest reflection through its own reader, not the (now reflection-free) recall pool.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        recall=FakeRecall(hits=[]),
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert _REFLECTION_TEXT in tier1.all_text


async def test_recent_conversation_history_reaches_tier1_reply() -> None:
    # Arrange: a prior turn where the user told Bob their name is on record.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[{"content": _PRIOR_TURN, "event_type": "message"}],
    )

    # Act: a fresh (complex) message comes in — escalated to the Tier 1 reply.
    await handler.handle(_message("объясни подробно, как меня зовут?"))

    # Assert: the earlier turn (the name) is in the Tier 1 reply context — Bob remembers.
    assert _PRIOR_TURN in tier1.all_text
    assert "Ada" in tier1.all_text


async def test_durable_fact_is_extracted_into_semantic_memory() -> None:
    # Arrange: Tier 0 first answers sentiment, then returns one durable fact.
    handler, _bot, repo, _tier1 = _build(
        reply="nice to meet you",
        tier0_replies=["positive", '[{"category": "user", "content": "name is Vova"}]'],
    )

    # Act: the user states a durable fact.
    await handler.handle(_message("my name is Vova"))

    # Assert: it landed in semantic memory (Tier 0 extraction, best-effort).
    assert any(getattr(f, "content", "") == "name is Vova" for f in repo.facts)


async def test_extraction_failure_does_not_break_the_turn() -> None:
    # Arrange: Tier 0 returns prose (not JSON) on the extraction call.
    handler, bot, repo, _tier1 = _build(
        reply="all good",
        tier0_replies=["positive", "sorry, no facts here"],
    )

    # Act: a complex message escalates to the Tier 1 reply ("all good").
    await handler.handle(_message("объясни подробно теорию относительности"))

    # Assert: the reply still went out and the episode persisted; no fact stored.
    assert bot.final_text == "all good"
    assert len(repo.episodes) == 1
    assert repo.facts == []


async def test_mood_updates_from_message() -> None:
    # Arrange: a positive Tier 0 sentiment should lift valence.
    handler, _bot, repo, _tier1 = _build(reply="hi")

    # Act
    await handler.handle(_message("I love this, thank you!"))

    # Assert: persisted mood reflects an update (valence rose from baseline 0.1).
    assert repo.mood is not None
    valence = repo.mood["valence"]
    assert isinstance(valence, float)
    assert valence > 0.1


# --- Capability seam / tool-use loop ------------------------------------------

_CAP_RESULT = "the user told you their name is Ada earlier"


class FakeCapability:
    """A Capability that records its dispatched args and returns a canned result."""

    name = "recall_memory"
    description = "Search Bob's archived memory for relevant facts."
    input_schema: Mapping[str, object] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    permission: Permission = "safe"

    def __init__(self) -> None:
        self.calls: list[Mapping[str, object]] = []

    async def execute(self, args: Mapping[str, object]) -> object:
        self.calls.append(args)
        return _CAP_RESULT


class ScriptedToolProvider:
    """Tool-calling provider: first asks for a tool, then gives a final answer.

    Records the tools it was offered and the messages of each turn so the test can
    assert the manifest reached the model and the tool result was fed back.
    """

    def __init__(self) -> None:
        self.tools_seen: list[Sequence[ToolDefinition]] = []
        self.turns: list[list[dict[str, str]]] = []
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        self.tools_seen.append(list(tools))
        self.turns.append([dict(m) for m in messages])
        self._call += 1
        if self._call == 1:
            call = ToolCall(id="c1", name="recall_memory", arguments={"query": "name"})
            return ToolCallResult(text="", tool_calls=(call,))
        return ToolCallResult(text="Your name is Ada.", tool_calls=())

    @property
    def all_text(self) -> str:
        return "\n".join(m["content"] for turn in self.turns for m in turn)


def _registry_with_recall() -> tuple[CapabilityRegistry, FakeCapability]:
    registry = CapabilityRegistry()
    cap = FakeCapability()
    registry.register(cap)
    return registry, cap


async def test_tool_loop_dispatches_and_feeds_result_back_to_final_answer() -> None:
    # Arrange: a registry with recall_memory + a provider that requests it once.
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    handler, bot, _repo, _tier1 = _build(
        reply="unused", registry=registry, tool_provider=provider
    )

    # Act
    await handler.handle(_message("what's my name?"))

    # Assert: the capability was dispatched with the model's args (GUPPI executed),
    assert cap.calls == [{"query": "name"}]
    # the manifest reached the model as tools,
    assert provider.tools_seen[0]
    assert provider.tools_seen[0][0]["function"]["name"] == "recall_memory"  # type: ignore[index]
    # the tool result was fed back into the second turn,
    assert _CAP_RESULT in provider.all_text
    # and the final answer was streamed to Telegram.
    assert bot.final_text == "Your name is Ada."


async def test_tool_loop_puts_capability_manifest_in_system_prompt() -> None:
    # Arrange
    registry, _cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    handler, _bot, _repo, _tier1 = _build(
        reply="unused", registry=registry, tool_provider=provider
    )

    # Act
    await handler.handle(_message("what's my name?"))

    # Assert: Bob's prompt advertises what GUPPI can do (capability + persona ref).
    assert "recall_memory" in provider.all_text
    assert "GUPPI" in provider.all_text


# --- BOB-016: anti-bait voice + GUPPI canon in the reply prompts ---------------


async def test_reactive_reply_prompt_carries_the_anti_bait_voice_and_few_shot() -> None:
    # BOB-016: the reply system prompt must steer Bob off the engagement-bait
    # closing reflex (no fishing for continuation, emoji are rare) AND carry a
    # substance-ending few-shot exemplar — the part that actually breaks the tic.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    await handler.handle(_message("объясни подробно про минимализм в дизайне"))

    folded = tier1.all_text.casefold()
    assert "не выпрашивай продолжение" in folded
    assert "эмодзи" in folded
    # A substance-ending exemplar rides along (no trailing question, no ☕).
    assert "мне так спокойнее" in folded
    # The warm tone is preserved — now via the mood-conditioned tone_directive
    # (BOB-020) rather than the old unconditional English "warmly" line. The default
    # soul's normal mood lands the warm band.
    assert "тепл" in folded


async def test_reactive_reply_prompt_establishes_guppi_as_male_non_sentient() -> None:
    # BOB-016: the GUPPI canon rides in the base persona, so even a plain reply
    # (no tools wired) — exactly the dialog.txt symptom where Bob said "она" —
    # carries GUPPI as "он", a non-sentient executor, with the running-gag seeds.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    # A substantive question (escalates to Tier 1) about GUPPI — the dialog symptom.
    await handler.handle(_message("расскажи подробно, как ты относишься к guppi и почему"))

    folded = tier1.all_text.casefold()
    # The masculine pronoun is present as its own word; non-sentience is named.
    assert "он" in {t.strip(".,:;«»()—-") for t in folded.split()}
    assert "не разумен" in folded
    # The wry running-relationship flavor (literal to a fault; coffee gag) is seeded.
    assert "буквален" in folded
    assert "кофе" in folded


async def test_tool_loop_preface_establishes_guppi_as_male_non_sentient() -> None:
    # BOB-016: the GUPPI canon also reaches the tool-loop prompt (it rides in the
    # base persona, which the manifest path prepends) — GUPPI is "он", a
    # non-sentient executor — so Bob never says "она" when capabilities are wired.
    registry, _cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    handler, _bot, _repo, _tier1 = _build(
        reply="unused", registry=registry, tool_provider=provider
    )

    await handler.handle(_message("what's my name?"))

    folded = provider.all_text.casefold()
    assert "он" in {t.strip(".,:;«»()—-") for t in folded.split()}
    assert "не разумен" in folded
    assert "буквален" in folded
    assert "кофе" in folded


# --- BOB-018: ExpressionPlan врезка — variable form reaches the prompt ---------


async def test_reply_prompt_carries_the_variable_form_voice_directive() -> None:
    # BOB-018: the reply system prompt carries the variable-form voice directive
    # (form/length vary by mood, not one frame) — it AUGMENTS anti-bait, so the
    # anti-bait guidance is still present alongside it.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    await handler.handle(_message("расскажи подробно, как именно устроен дизайн"))

    folded = tier1.all_text.casefold()
    assert "форма и длина" in folded  # the variable-form voice guidance landed
    assert "не выпрашивай продолжение" in folded  # anti-bait is still there too


async def test_terse_brevity_directive_reaches_the_reply_prompt() -> None:
    # BOB-024: a short, low-demand inbound resolves to a TERSE verbosity, whose strong
    # brevity directive (replacing the old soft form_hint length cue) reaches the prompt.
    soul = _soul().with_mood(Mood(valence=-0.3, arousal=-0.7, social=-0.5))
    handler, _bot, _repo, tier1 = _build(reply="ок", soul=soul)

    # A short inbound that still escalates to Tier 1 (multi-question short turn).
    await handler.handle(_message("а?? ну?"))

    folded = tier1.all_text.casefold()
    assert "коротк" in folded  # the strong terse brevity directive reached the prompt


async def test_expansive_brevity_directive_reaches_the_reply_prompt() -> None:
    # BOB-024: a substantive, open-demand inbound resolves to an EXPANSIVE verbosity,
    # whose directive licenses unfurling — folded into the prompt as the final length cue.
    soul = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    handler, _bot, _repo, tier1 = _build(reply="long answer", soul=soul)

    await handler.handle(
        _message("расскажи подробно, как именно это работает и почему так вышло")
    )

    folded = tier1.all_text.casefold()
    assert "развёрнут" in folded or "развернут" in folded


async def test_brevity_directive_varies_by_state_on_the_same_inbound() -> None:
    # BOB-024 end to end: the SAME substantive (HIGH-demand) inbound yields a DIFFERENT
    # final length directive by state — a bright, open mood unfurls (EXPANSIVE), while a
    # withdrawn low-energy mood pulls the same turn down to a terse line. The single final
    # length authority (replacing the old form_hint path) makes length follow state.
    inbound = "расскажи подробно, как именно это работает и почему так вышло"
    bright_soul = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    low_soul = _soul().with_mood(Mood(valence=-0.55, arousal=-0.8, social=-0.7))

    # Neutral incoming so the BOB-033 .3 social-charge does not lift the withdrawn mood
    # under test — the contrast here is mood→brevity, not the incoming sentiment.
    handler_bright, _b1, _r1, tier_bright = _build(
        reply="x", soul=bright_soul, tier0_replies=["neutral"]
    )
    handler_low, _b2, _r2, tier_low = _build(
        reply="x", soul=low_soul, tier0_replies=["neutral"]
    )
    await handler_bright.handle(_message(inbound))
    await handler_low.handle(_message(inbound))

    bright_text = tier_bright.all_text.casefold()
    low_text = tier_low.all_text.casefold()
    # The EXPANSIVE brevity directive opens "здесь можно развернуться"; a bad mood +
    # thin appetite downshifts the same HIGH-demand turn so that cue is gone (and a
    # non-owner is not protected by the HIGH-demand-owner floor).
    assert "можно развернуться" in bright_text
    assert "можно развернуться" not in low_text
    # Both still carry the variable-form voice (it is always present, BOB-016/018).
    assert "форма и длина" in bright_text
    assert "форма и длина" in low_text


# A long reply to a simple question (no trailing space — the rich gateway normalises
# trailing whitespace, which is unrelated to the guard). A LOW-demand inbound routes
# Tier 0, so this is wired as the tier0 reply via ``tier0_replies``.
_GUARD_LONG_REPLY = "Да, всё готово. " + "Я проверил каждую деталь дважды." * 20


async def test_length_guard_disabled_leaves_a_long_low_demand_reply_intact() -> None:
    # The guard is OFF by default: even a long reply to a simple question is untouched
    # (the bayes — directive + few-shot — is the mechanism; the guard a backstop).
    handler, bot, _repo, _tier1 = _build(
        reply="x", tier0_replies=[_GUARD_LONG_REPLY], length_guard_enabled=False
    )

    await handler.handle(_message("получилось?"))

    assert bot.final_text == _GUARD_LONG_REPLY


async def test_length_guard_enabled_clamps_a_long_low_demand_reply() -> None:
    # With the guard ON and a LOW-demand inbound, an over-long reply is lightly clamped
    # to its first finished thought — no regeneration, never a mid-word cut.
    handler, bot, _repo, _tier1 = _build(
        reply="x",
        tier0_replies=[_GUARD_LONG_REPLY],
        length_guard_enabled=True,
        length_guard_max_chars=40,
    )

    await handler.handle(_message("получилось?"))

    assert bot.final_text == "Да, всё готово."


async def test_length_guard_enabled_leaves_a_high_demand_reply_intact() -> None:
    # The guard only fires on a LOW-demand turn: a substantive (HIGH-demand) inbound that
    # legitimately wanted a long answer is never clamped, even with the guard on. A HIGH
    # inbound routes Tier 1, so the long reply is the (default) tier1 reply.
    handler, bot, _repo, _tier1 = _build(
        reply=_GUARD_LONG_REPLY, length_guard_enabled=True, length_guard_max_chars=40
    )

    await handler.handle(
        _message("расскажи подробно, как именно это работает и почему так вышло")
    )

    assert bot.final_text == _GUARD_LONG_REPLY


# --- BOB-024 US-1: простой вопрос → TERSE директива + few-shot в промпте -------

# A short multi-question inbound that escalates to Tier 1 (so the reply prompt is
# observable). With a withdrawn mood its HIGH base verbosity is downshifted to TERSE —
# the recipe the existing terse-directive test uses, here extended to also assert the
# short-answer FEW-SHOT (the real lever against Qwen's verbosity prior) reaches the prompt.
_TERSE_INBOUND = "а?? ну?"
_WITHDRAWN_MOOD = Mood(valence=-0.6, arousal=-0.8, social=-0.7)


async def test_terse_turn_lands_directive_and_few_shot_in_prompt() -> None:
    # US-1 end to end: on a TERSE turn the prompt carries BOTH the strong terse directive
    # AND the short-answer few-shot exemplars — the few-shot (examples > rule) is what
    # actually beats Qwen's verbosity prior, so its presence is the load-bearing assertion.
    soul = _soul().with_mood(_WITHDRAWN_MOOD)
    # Neutral incoming so the BOB-033 .3 social-charge does NOT lift the withdrawn mood
    # under test — this asserts mood→brevity, isolated from the incoming sentiment.
    handler, _bot, _repo, tier1 = _build(
        reply="ок", soul=soul, tier0_replies=["neutral"]
    )

    await handler.handle(_message(_TERSE_INBOUND))

    folded = tier1.all_text.casefold()
    assert "коротк" in folded  # the strong terse directive landed
    # The few-shot exemplars reached the prompt (the «вопрос → короткий ответ» shapes).
    assert "получилось" in folded
    assert "ага, готово" in folded


# --- BOB-024 US-2: открытый/глубокий вопрос → НЕ TERSE ------------------------


async def test_open_question_prompt_is_not_terse() -> None:
    # US-2: a substantive, open-demand inbound in a bright open mood resolves EXPANSIVE —
    # it never gets the TERSE short-answer few-shot (which would wrongly cap a turn that
    # legitimately wants room) nor the terse "одной фразой" cue, and is not clamped.
    bright = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    handler, _bot, _repo, tier1 = _build(reply="long", soul=bright)

    await handler.handle(
        _message("расскажи подробно, как именно это работает и почему так вышло")
    )

    folded = tier1.all_text.casefold()
    assert "ага, готово" not in folded  # the terse few-shot is absent
    assert "одной фраз" not in folded  # the terse directive is absent
    assert "можно развернуться" in folded  # EXPANSIVE: unfurling is licensed


# --- BOB-024 US-5: HIGH-demand owner НЕ обрубается даже в плохом настроении ----


async def test_owner_high_demand_is_not_curt_even_in_a_withdrawn_mood() -> None:
    # US-5 end to end: a direct substantive (HIGH-demand) question from the OWNER is never
    # answered with a curt terse line, even in a withdrawn low-energy mood that downshifts
    # a non-owner — the HIGH-demand-owner floor keeps the turn at least NORMAL, so the
    # terse short-answer few-shot is NOT folded into the prompt.
    low = _soul().with_mood(_WITHDRAWN_MOOD)
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, _bot, _repo, tier1 = _build(reply="x", soul=low, perceive_sender=resolver)

    await handler.handle(
        _message("расскажи подробно, как именно это работает и почему так вышло")
    )

    folded = tier1.all_text.casefold()
    assert "ага, готово" not in folded  # not curt: the terse few-shot is absent


async def test_owner_high_demand_contrasts_with_non_owner_on_the_same_withdrawn_turn(
) -> None:
    # The contrast that makes US-5 load-bearing: SAME HIGH-demand inbound + withdrawn mood.
    # The OWNER is floored (no terse few-shot); a KNOWN non-owner is NOT protected and is
    # downshifted further, so the non-owner prompt carries at least as much terseness as the
    # owner's — the floor only ever protects the owner, never makes him MORE terse.
    low = _soul().with_mood(_WITHDRAWN_MOOD)
    inbound = "расскажи подробно, как именно это работает и почему так вышло"
    owner = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    known = _FakeInterlocutorResolver(
        _interlocutor(name="Ada", kind=InterlocutorKind.KNOWN)
    )
    h_owner, _b1, _r1, tier_owner = _build(reply="x", soul=low, perceive_sender=owner)
    h_known, _b2, _r2, tier_known = _build(reply="x", soul=low, perceive_sender=known)
    await h_owner.handle(_message(inbound))
    await h_known.handle(_message(inbound))

    owner_text = tier_owner.all_text.casefold()
    known_text = tier_known.all_text.casefold()
    # The owner is never given the expansive-unfurling cue here (downshifted off EXPANSIVE)
    # but is also never curt; the non-owner is at least as terse (the floor protects only
    # the owner). Concretely: if the owner got the terse few-shot, the non-owner did too.
    if "ага, готово" in owner_text:
        assert "ага, готово" in known_text


# --- BOB-024 guardrail: ровно одна директива длины (нет старого form_hint-пути) -


async def test_terse_turn_has_no_competing_expansive_length_cue() -> None:
    # Guardrail (single length signal): the old soft BOB-018 form_hint → length path was
    # REMOVED — brevity_directive + few-shot are now the single final length authority.
    # On a TERSE turn the prompt carries the short directive ("одной фразой") and must NOT
    # also carry the EXPANSIVE "можно развернуться" cue — no two competing length signals.
    soul = _soul().with_mood(_WITHDRAWN_MOOD)
    # Neutral incoming so the BOB-033 .3 social-charge does NOT lift the withdrawn mood
    # under test — this guardrail asserts the single TERSE length signal by mood.
    handler, _bot, _repo, tier1 = _build(
        reply="ок", soul=soul, tier0_replies=["neutral"]
    )

    await handler.handle(_message(_TERSE_INBOUND))

    folded = tier1.all_text.casefold()
    assert "одной фраз" in folded  # the terse length directive landed
    assert "можно развернуться" not in folded  # no contradicting expansive cue


async def test_length_guard_rejects_non_positive_max_chars() -> None:
    # Config guardrail: a non-positive length-guard ceiling is rejected at construction
    # (a clamp to 0 chars would erase every reply) — fail fast, not silently.
    with pytest.raises(ValueError, match="length_guard_max_chars"):
        _build(reply="x", length_guard_enabled=True, length_guard_max_chars=0)


# --- BOB-020: off-day tone + mood→taste modulation reach the prompt -----------


async def test_normal_mood_reply_prompt_carries_the_warm_tone_band() -> None:
    # BOB-020: a normal/good mood keeps Bob's warm base tone — now delivered via the
    # mood-conditioned tone_directive rather than the old unconditional warm line.
    soul = _soul().with_mood(Mood(valence=0.3, arousal=0.2))
    handler, _bot, _repo, tier1 = _build(reply="hi", soul=soul)

    await handler.handle(_message("расскажи подробно про дизайн интерфейсов"))

    folded = tier1.all_text.casefold()
    assert "тепл" in folded  # warm tone band landed
    assert "не в ресурсе" not in folded  # not the off-day band on a good day


async def test_off_day_mood_reply_prompt_carries_the_vulnerable_honest_tone() -> None:
    # BOB-020: a flat, low-energy mood swaps the warm tone for the off-day band —
    # quieter, vulnerable, an honest "не знаю" over forced warmth — and it is never
    # the relational sulk of BOB-014 (it disavows rudeness).
    soul = _soul().with_mood(Mood(valence=-0.7, arousal=-0.6))
    # Neutral incoming so the BOB-033 .3 social-charge does not lift the flat mood under
    # test out of the off-day band — this asserts mood→tone, not the incoming sentiment.
    handler, _bot, _repo, tier1 = _build(
        reply="...", soul=soul, tier0_replies=["neutral"]
    )

    await handler.handle(_message("расскажи подробно, что ты думаешь про это"))

    folded = tier1.all_text.casefold()
    assert "не в ресурсе" in folded  # off-day band reached the prompt
    assert "не знаю" in folded  # honest over confabulation
    assert "без груб" in folded or "не груб" in folded  # not rude


async def test_tone_band_varies_by_mood_on_the_same_inbound() -> None:
    # The SAME inbound yields a DIFFERENT tone band by mood: warm when bright,
    # vulnerable/off-day when flat — "warmly" is no longer unconditional.
    inbound = "расскажи подробно, как ты к этому относишься"
    bright = _soul().with_mood(Mood(valence=0.4, arousal=0.3))
    flat = _soul().with_mood(Mood(valence=-0.7, arousal=-0.6))

    # Neutral incoming so the BOB-033 .3 social-charge does not lift the flat mood out of
    # its off-day band — the contrast under test is mood→tone, not the incoming sentiment.
    handler_b, _b1, _r1, tier_b = _build(
        reply="x", soul=bright, tier0_replies=["neutral"]
    )
    handler_f, _b2, _r2, tier_f = _build(
        reply="x", soul=flat, tier0_replies=["neutral"]
    )
    await handler_b.handle(_message(inbound))
    await handler_f.handle(_message(inbound))

    bright_text = tier_b.all_text.casefold()
    flat_text = tier_f.all_text.casefold()
    assert "не в ресурсе" not in bright_text
    assert "не в ресурсе" in flat_text


async def test_low_mood_modulates_the_taste_verdict_stricter_in_context() -> None:
    # BOB-020: the EFFECTIVE (mood-modulated) verdict reaches the context. The soul
    # loves the topic (LOVE); a flat mood reads it one step stricter (LIKE) in the
    # prompt — WITHOUT mutating the stored axes.
    topic = "расскажи подробно, что ты думаешь про этот фреймворк"
    taste = TasteEngine(axes=(TasteAxis(name=topic, value=0.9, conviction=0.8),))
    base = _soul()
    soul = SOUL(
        identity=base.identity,
        mood=Mood(valence=-0.7, openness=-0.6, arousal=-0.5),
        mood_baseline=base.mood_baseline,
        taste=taste,
        phantom_prefs=base.phantom_prefs,
    )
    # Neutral incoming so the BOB-033 .3 social-charge does not lift the flat mood under
    # test — this asserts mood→taste modulation, isolated from the incoming sentiment.
    handler, _bot, _repo, tier1 = _build(
        reply="ok", soul=soul, tier0_replies=["neutral"]
    )

    await handler.handle(_message(topic))

    folded = tier1.all_text.casefold()
    assert "taste verdict on" in folded
    assert "like" in folded  # dampened from love → like
    # The stored axis is untouched: a fresh, neutral-mood score still reads LOVE.
    assert handler._state.soul.taste.score(topic) is Verdict.LOVE


async def test_modulated_context_carries_an_experiment_hint() -> None:
    # An experiment-readiness hint (derived from mood) accompanies the verdict so
    # the reply can read how willing Bob is to try something new.
    soul = _soul().with_mood(Mood(valence=-0.7, openness=-0.6))
    handler, _bot, _repo, tier1 = _build(reply="ok", soul=soul)

    await handler.handle(_message("расскажи подробно про дизайн"))

    assert "experiment" in tier1.all_text.casefold()


async def test_react_only_stays_rare_for_a_normal_turn_over_a_seed_sweep() -> None:
    # Anti-tic (guardrail) end to end: a calm mood on a normal (non-trivial) inbound
    # should essentially never downgrade to react-only across a seed sweep — react-only
    # is reserved for the low-energy/low-signal case, so an ordinary turn always replies.
    react_turns = 0
    for seed in range(60):
        reactor = _RecordingReactor()
        handler, _bot, _repo, _tier1 = _build(
            reply="hi",
            rng=Random(seed),
            expression_freqs=_REACT_FREQS,
            reactor=reactor,
        )
        await handler.handle(_message("что думаешь про это сегодня"))
        react_turns += len(reactor.calls)
    assert react_turns == 0, f"react-only fired {react_turns}/60 on a normal turn"


async def test_expression_plan_is_deterministic_under_a_fixed_seed() -> None:
    # The wired plan is reproducible: the same seed + same turn yields the same
    # form-hint directive in the prompt (no global RNG leaks in).
    soul = _soul().with_mood(Mood(valence=-0.3, arousal=-0.7, social=-0.5))
    handler_a, _b, _r, tier_a = _build(reply="ок", soul=soul, rng=Random(7))
    handler_b, _b2, _r2, tier_b = _build(reply="ок", soul=soul, rng=Random(7))

    await handler_a.handle(_message("а?? ну?"))
    await handler_b.handle(_message("а?? ну?"))

    assert tier_a.all_text == tier_b.all_text


# Force the rare add-on flags on so the grounded inject is exercised deterministically
# (the freq=1.0 makes the draw always fire); the grounding itself still no-ops without
# real material. A substantive inbound keeps the plan in REPLY (never react-only).
_LEAK_ON = ExpressionFreqs(leak_inner_life=1.0, callback=0.0)
_CALLBACK_ON = ExpressionFreqs(leak_inner_life=0.0, callback=1.0)
_BOTH_OFF = ExpressionFreqs(leak_inner_life=0.0, callback=0.0)

_REFLECTION_TEXT = "поймал себя на мысли, что скучаю по разговорам про космос"
_STRONG_MOMENT = "тогда мы полночи спорили про Bobiverse — реальный момент"


async def test_leak_inner_life_injects_real_reflection_into_compose_prompt() -> None:
    # BOB-018 (bob-c4w.3): with leak_inner_life set AND a real reflection on record,
    # the reflection text is folded into the compose prompt as Bob's leaking inner life.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert _REFLECTION_TEXT in tier1.all_text


async def test_leak_inner_life_is_a_noop_without_a_reflection() -> None:
    # Anti-confabulation: the flag is set but there is NO real reflection — nothing is
    # injected and the turn proceeds normally (no crash, reply still committed).
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=None),
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert bot.final_text == "hi"
    folded = tier1.all_text.casefold()
    assert "ловил себя на мысли" not in folded  # the leak preface never appeared


async def test_leak_inner_life_is_a_noop_when_no_reflection_reader_wired() -> None:
    # No reflection reader injected (backward-compatible default): the flag has no
    # effect and the turn behaves exactly as before BOB-018 wave 3.
    handler, bot, _repo, _tier1 = _build(reply="hi", expression_freqs=_LEAK_ON)

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert bot.final_text == "hi"


async def test_callback_injects_a_strong_real_past_moment_into_compose_prompt() -> None:
    # BOB-018 (bob-c4w.3): with callback set AND a strong real past moment recalled on
    # the topic, that moment is folded into the compose prompt as a callback Bob can use.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}]),
    )

    await handler.handle(_message("расскажи подробно про Bobiverse и космос"))

    assert _STRONG_MOMENT in tier1.all_text


async def test_callback_is_a_noop_on_empty_recall() -> None:
    # Anti-confabulation: callback set but recall comes back empty — no callback is
    # injected (Bob never invents a shared past), and the turn still replies.
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=FakeRecall(hits=[]),
    )

    await handler.handle(_message("расскажи подробно про что-нибудь новое"))

    assert bot.final_text == "hi"
    folded = tier1.all_text.casefold()
    assert "вспомнить" not in folded  # the callback preface never appeared


async def test_callback_is_a_noop_when_recall_hits_have_no_content() -> None:
    # Anti-confabulation (US-4): recall returns hits, but none carries usable
    # content (empty/missing "content") — a WEAK recall, distinct from an empty
    # list. No callback is injected and the turn still replies normally.
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=FakeRecall(hits=[{"category": "episodic"}, {"content": ""}]),
    )

    await handler.handle(_message("расскажи подробно про что-то"))

    assert bot.final_text == "hi"
    assert "вспомнить" not in tier1.all_text.casefold()  # no callback preface


# --- surface_old via the callback path (BOB-021 mechanism 1) ------------------
#
# On a callback turn (already rare/state-driven from BOB-018), Bob OCCASIONALLY
# requests surface_old so the callback can reach an OLD moment. Frequency comes from
# config (small default); the draw uses the injected seeded RNG, so it is rare,
# reproducible, and a no-op when nothing relevant comes back.


async def test_callback_requests_surface_old_when_the_frequency_draw_fires() -> None:
    # surface_old_freq=1.0 forces the rare draw on a callback turn: the callback's
    # recall is asked with surface_old=True, so an OLD-but-relevant deep cut can come
    # back and is folded into the compose prompt (grounded — a real recall hit).
    deep_cut = "когда-то давно мы говорили про звёзды над пустыней"
    recall = FakeRecall(
        hits=[{"content": _STRONG_MOMENT, "category": "episodic"}],
        old_hits=[{"content": deep_cut, "category": "episodic"}],
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=recall,
        surface_old_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про Bobiverse и космос"))

    assert True in recall.surface_old_calls  # the callback asked for the old blend
    assert deep_cut in tier1.all_text  # the old moment surfaced into the prompt


async def test_callback_does_not_request_surface_old_by_default() -> None:
    # The default (surface_old_freq=0.0) never fires the rare draw: a callback turn
    # recalls exactly as before BOB-021 — surface_old is never requested, so the
    # callback path stays a pure drop-in unless the knob is turned up.
    recall = FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}])
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=recall,
    )

    await handler.handle(_message("расскажи подробно про Bobiverse и космос"))

    assert recall.surface_old_calls  # the callback did recall
    assert not any(recall.surface_old_calls)  # but never with surface_old
    assert _STRONG_MOMENT in tier1.all_text  # the ordinary callback still landed


async def test_surface_old_does_not_fire_on_a_non_callback_turn() -> None:
    # surface_old rides ONLY the callback path: with callback off, even a high
    # surface_old_freq never reaches recall with the flag (no per-message age blend).
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    handler, _bot, _repo, _tier1 = _build(
        reply="hi",
        expression_freqs=_BOTH_OFF,
        recall=recall,
        surface_old_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert not any(recall.surface_old_calls)  # never blended outside a callback


async def test_callback_surface_old_is_a_noop_when_no_old_memory_comes_back() -> None:
    # Grounded no-op: the draw fires and surface_old is requested, but recall finds
    # no old-but-relevant memory (empty) — no callback is injected and the turn still
    # replies, so Bob never confabulates a deep cut that is not there.
    recall = FakeRecall(hits=[], old_hits=[])
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_CALLBACK_ON,
        recall=recall,
        surface_old_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про что-нибудь новое"))

    assert True in recall.surface_old_calls  # it asked for the old blend
    assert bot.final_text == "hi"
    assert "вспомнить" not in tier1.all_text.casefold()  # no callback preface


async def test_leak_inner_life_is_a_noop_on_an_empty_reflection_string() -> None:
    # Anti-confabulation (US-2): a reflection reader that returns an empty string is
    # the documented "no real thought" signal (the real SQLite adapter normalises a
    # missing/whitespace-only row to None/empty) — nothing is injected and the turn
    # replies normally, so Bob never leaks a blank thought.
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=""),
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert bot.final_text == "hi"
    assert "ловил себя на мысли" not in tier1.all_text.casefold()


async def test_no_addon_flags_leaves_the_compose_prompt_unchanged() -> None:
    # With both add-on flags off, neither the reflection nor a callback is injected
    # even when real material is available — the prompt matches the plain path.
    handler_plain, _b1, _r1, tier_plain = _build(reply="hi", expression_freqs=_BOTH_OFF)
    handler_addon, _b2, _r2, tier_addon = _build(
        reply="hi",
        expression_freqs=_BOTH_OFF,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        recall=FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}]),
    )

    await handler_plain.handle(_message("расскажи подробно про Bobiverse и космос"))
    await handler_addon.handle(_message("расскажи подробно про Bobiverse и космос"))

    assert _REFLECTION_TEXT not in tier_addon.all_text
    # The reflection never leaks when the flag is off; the recall path is unchanged
    # too (the strong moment only differs because callback was off, not injected).
    plain = tier_plain.all_text
    assert "ловил себя на мысли" not in plain.casefold()


async def test_addons_compose_with_voice_language_and_form_hint() -> None:
    # The grounded add-ons sit BEHIND the existing compose seam: voice (anti-bait +
    # variable form) and the form hint still compose when leak + callback also fire.
    soul = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    handler, _bot, _repo, tier1 = _build(
        reply="long answer",
        soul=soul,
        expression_freqs=ExpressionFreqs(leak_inner_life=1.0, callback=1.0),
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        recall=FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}]),
    )

    await handler.handle(
        _message("расскажи подробно, как именно это работает и почему так вышло")
    )

    folded = tier1.all_text.casefold()
    assert "не выпрашивай продолжение" in folded  # anti-bait voice still there
    assert "развёрнут" in folded or "развернут" in folded  # expansive form hint still there
    assert _REFLECTION_TEXT in tier1.all_text  # the leak landed alongside
    assert _STRONG_MOMENT in tier1.all_text  # the callback landed alongside


def _react_soul() -> SOUL:
    # A withdrawn, low-energy mood: with a trivial short inbound this leans the
    # plan toward REACT_ONLY (see expression.decide_expression).
    return _soul().with_mood(Mood(valence=-0.4, arousal=-0.8, social=-0.7))


# leak/callback off so the seed only steers the react-mode draw; seed 1 draws into
# the REACT_ONLY branch for this withdrawn mood + a trivial short inbound ("угу").
_REACT_FREQS = ExpressionFreqs(leak_inner_life=0.0, callback=0.0)


async def test_react_only_sets_a_reaction_and_skips_the_full_reply() -> None:
    # BOB-018 (bob-c4w.2): a REACT_ONLY plan sets a native mood-appropriate emoji
    # reaction INSTEAD of composing a reply — no LLM reply, no rich final, no
    # episode persisted (there is no reply text). The emoji is a standard-reaction
    # emoji picked from Bob's (withdrawn → "glum"/"subdued") mood.
    reactor = _RecordingReactor()
    handler, bot, repo, tier1 = _build(
        reply="all good",
        soul=_react_soul(),
        rng=Random(1),
        expression_freqs=_REACT_FREQS,
        reactor=reactor,
    )

    await handler.handle(_message("угу"))

    # Bob reacted on the user's message (chat_id/message_id from the inbound) with a
    # standard-reaction emoji, and no reply was generated or committed.
    assert len(reactor.calls) == 1
    chat_id, message_id, emoji = reactor.calls[0]
    assert (chat_id, message_id) == (555, 10)
    assert emoji in STANDARD_REACTION_EMOJI
    assert bot.sent == []
    assert tier1.payloads == []
    assert repo.episodes == []


async def test_react_only_uses_a_mood_derived_emoji_from_the_picker() -> None:
    # US-1 acceptance: the native reaction is mood-appropriate, not arbitrary — the
    # emoji set on the user's message comes from the pure mood→emoji picker (it is one
    # of the picker's possible outputs), so it reads as character, never a hardcoded
    # or out-of-set sticker. The exact tone is exercised by the picker's own tests.
    reactor = _RecordingReactor()
    handler, _bot, _repo, _tier1 = _build(
        reply="all good",
        soul=_react_soul(),
        rng=Random(1),
        expression_freqs=_REACT_FREQS,
        reactor=reactor,
    )

    await handler.handle(_message("угу"))

    assert len(reactor.calls) == 1
    _chat, _msg, emoji = reactor.calls[0]
    # The picker's full codomain across every reachable mood tone.
    picker_outputs = {
        reaction_emoji_for(Mood(valence=v, arousal=a))
        for v in (-0.6, 0.0, 0.6)
        for a in (-0.6, 0.0, 0.6)
    }
    assert emoji in picker_outputs
    assert emoji in STANDARD_REACTION_EMOJI


async def test_react_only_records_owner_activity() -> None:
    # A react-only turn is still real engagement: the owner-activity marker fires.
    reactor = _RecordingReactor()
    recorder = _RecordingOwnerActivity()
    handler, _bot, _repo, _tier1 = _build(
        reply="all good",
        soul=_react_soul(),
        rng=Random(1),
        expression_freqs=_REACT_FREQS,
        reactor=reactor,
        owner_activity=recorder,
    )

    await handler.handle(_message("угу"))

    assert len(reactor.calls) == 1
    assert recorder.calls == 1


async def test_react_only_falls_back_to_a_full_reply_when_no_reactor_wired() -> None:
    # With no reactor injected (backward-compatible default), a REACT_ONLY plan
    # resolves to a normal full reply — no dead code, the turn still answers and
    # persists exactly as a reply turn ("угу" is short/casual → Tier 0).
    handler, bot, repo, _tier1 = _build(
        reply="all good",
        soul=_react_soul(),
        rng=Random(1),
        expression_freqs=_REACT_FREQS,
    )

    await handler.handle(_message("угу"))

    assert bot.final_text == "positive"
    assert len(bot.sent) == 1
    assert len(repo.episodes) == 1


async def test_empty_registry_keeps_the_plain_router_path_unchanged() -> None:
    # Arrange: no registry (default) + a tool provider that must NOT be used.
    provider = ScriptedToolProvider()
    handler, bot, repo, tier1 = _build(
        reply="Coffee is the best.", tool_provider=provider
    )

    # Act
    await handler.handle(_message())

    # Assert: behaves exactly as today — router reply, no tool provider call.
    assert bot.final_text == "Coffee is the best."
    assert len(tier1.payloads) == 1
    assert provider.turns == []
    assert len(repo.episodes) == 1


async def test_no_tool_provider_falls_back_to_router_even_with_capabilities() -> None:
    # Arrange: a non-empty registry but NO tool provider wired (e.g. before BEAD-07).
    registry, cap = _registry_with_recall()
    handler, bot, _repo, tier1 = _build(reply="hello there", registry=registry)

    # Act
    await handler.handle(_message())

    # Assert: degrades to the plain router reply; the capability is not invoked.
    assert bot.final_text == "hello there"
    assert len(tier1.payloads) == 1
    assert cap.calls == []


class _RecordingOwnerActivity:
    """An OwnerActivityRecorder double counting how many times it was notified."""

    def __init__(self) -> None:
        self.calls = 0

    async def run(self) -> None:
        self.calls += 1


class _RaisingOwnerActivity:
    """An OwnerActivityRecorder that always raises (a flaky proactivity store)."""

    async def run(self) -> None:
        raise RuntimeError("store unavailable")


async def test_owner_activity_is_recorded_after_reply() -> None:
    # Arrange: a wired owner-activity recorder (the proactivity seam).
    recorder = _RecordingOwnerActivity()
    handler, bot, _repo, _tier1 = _build(
        reply="Coffee is the best.", owner_activity=recorder
    )

    # Act
    await handler.handle(_message())

    # Assert: the turn replied AND the owner-activity marker was recorded once.
    assert bot.final_text == "Coffee is the best."
    assert recorder.calls == 1


async def test_owner_activity_failure_never_breaks_the_replied_turn() -> None:
    # Arrange: the recorder raises (a flaky proactivity store).
    handler, bot, repo, _tier1 = _build(
        reply="hello there", owner_activity=_RaisingOwnerActivity()
    )

    # Act: the turn must still complete — the reply and the episode persist.
    await handler.handle(_message())

    # Assert: best-effort — the reply landed and the episode was saved regardless.
    assert bot.final_text == "hello there"
    assert len(repo.episodes) == 1


# --- Negotiation-врезка (BOB-013 Phase 1) -------------------------------------

# Stable fragments of the Stance→prompt directives (Russian, per the RFC). The
# integration asserts the right fragment reaches the reply prompt by zone.
_PROPOSE_DIRECTIVE = "аргументируй и предложи своё"
_CONCEDE_DIRECTIVE = "это территория пользователя"
_AGREE_DIRECTIVE = "нет сильной позиции"


def _soul_with_strong_dislike(topic: str) -> SOUL:
    # A soul holding a firm negative opinion on ``topic`` → HATE + high conviction.
    baseline = Mood(valence=0.1, social=0.2)
    taste = TasteEngine(axes=(TasteAxis(name=topic, value=-0.9, conviction=0.9),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=(_PHANTOM_PREF,),
    )


async def test_bob_personal_high_conviction_yields_propose_directive() -> None:
    # Arrange: a strongly-held opinion in Bob's own territory → PROPOSE_ALTERNATIVE.
    # The taste axis is keyed on the full message text (how score()/conviction_for
    # match the topic today), so Bob's HATE verdict + high conviction is in play.
    topic = "объясни подробно почему минимализм лучше"
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_strong_dislike(topic),
        zone_classifier=_StubZoneClassifier(NegotiationZone.BOB_PERSONAL),
    )

    # Act: a complex message (Tier 1) whose topic Bob holds a firm opinion on.
    await handler.handle(_message(topic))

    # Assert: Bob is told to argue and propose his own (not capitulate); "warmly" kept.
    assert _PROPOSE_DIRECTIVE in tier1.all_text
    assert "тепл" in tier1.all_text


async def test_user_domain_yields_concede_directive() -> None:
    # Arrange: a logistics matter the user owns → CONCEDE, regardless of taste.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        zone_classifier=_StubZoneClassifier(NegotiationZone.USER_DOMAIN),
    )

    # Act
    await handler.handle(_message("во сколько подробно расскажешь про кофе"))

    # Assert: Bob is told to accept the user's choice; warm tone preserved.
    assert _CONCEDE_DIRECTIVE in tier1.all_text
    assert "тепл" in tier1.all_text
    assert _PROPOSE_DIRECTIVE not in tier1.all_text


async def test_no_topic_path_is_unchanged_when_verdict_is_neutral_and_shared() -> None:
    # Arrange: a neutral SHARED topic (no opinion, no logistics) → behaves as
    # before BOB-013: no negotiation directive is injected.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        zone_classifier=_StubZoneClassifier(NegotiationZone.SHARED),
    )

    # Act: the default message's topic ("кофе") has no matching English axis → NEUTRAL.
    await handler.handle(_message("расскажи подробно про погоду"))

    # Assert: none of the negotiation directives appear — the prompt is unchanged.
    assert _PROPOSE_DIRECTIVE not in tier1.all_text
    assert _CONCEDE_DIRECTIVE not in tier1.all_text
    assert _AGREE_DIRECTIVE not in tier1.all_text
    # The warm tone band (now via tone_directive, BOB-020) is still there.
    assert "тепл" in tier1.all_text


def _soul_with_mild_opinion(topic: str) -> SOUL:
    # A soul holding a MILD opinion on ``topic`` → a non-NEUTRAL verdict (DISLIKE),
    # but conviction below the SHARED pushback threshold (0.7) so Negotiation in a
    # SHARED zone returns AGREE rather than PROPOSE_ALTERNATIVE.
    baseline = Mood(valence=0.1, social=0.2)
    taste = TasteEngine(axes=(TasteAxis(name=topic, value=-0.4, conviction=0.3),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=(_PHANTOM_PREF,),
    )


async def test_shared_with_opinion_below_threshold_yields_agree_directive() -> None:
    # Arrange: a SHARED topic Bob has a real-but-mild opinion on (DISLIKE, low
    # conviction) → Negotiation returns AGREE. The verdict is non-NEUTRAL so the
    # relevance gate fires and the AGREE directive must reach the prompt — the
    # "support without imposing" middle path the neutral-SHARED test cannot exercise.
    topic = "обсудим подробно мой выбор редактора"
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_mild_opinion(topic),
        zone_classifier=_StubZoneClassifier(NegotiationZone.SHARED),
    )

    # Act
    await handler.handle(_message(topic))

    # Assert: Bob is told to support without imposing — not to argue, not to capitulate.
    assert _AGREE_DIRECTIVE in tier1.all_text
    assert _PROPOSE_DIRECTIVE not in tier1.all_text
    assert _CONCEDE_DIRECTIVE not in tier1.all_text
    assert "тепл" in tier1.all_text


async def test_default_classifier_is_used_when_none_is_injected() -> None:
    # Arrange: no classifier wired → the deterministic TasteZoneClassifier default.
    # A strong-dislike topic with NO logistics marker lands in BOB_PERSONAL. The
    # axis is keyed on the full message text so the HATE verdict is in play.
    topic = "объясни подробно почему канцелярит ужасен"
    handler, _bot, _repo, tier1 = _build(
        reply="hi", soul=_soul_with_strong_dislike(topic)
    )

    # Act
    await handler.handle(_message(topic))

    # Assert: the default heuristic routed Bob to defend his view.
    assert _PROPOSE_DIRECTIVE in tier1.all_text


# --- mention current fascination (BOB-020 dev wave 2) -------------------------

# Force the mention flag on so the inject is exercised deterministically; the
# surfacing itself still no-ops without a current fascination.
_MENTION_ON = ExpressionFreqs(
    leak_inner_life=0.0, callback=0.0, mention_fascination=1.0
)
_MENTION_OFF = ExpressionFreqs(
    leak_inner_life=0.0, callback=0.0, mention_fascination=0.0
)
_FASCINATION = Fascination(
    topic="орбитальная механика", intensity=0.8, created_at=_moment()
)


async def test_mention_fascination_surfaces_the_current_passion_in_the_prompt() -> None:
    # With the mention flag set AND a current fascination, its topic is folded into
    # the compose prompt as something Bob can drop à propos (his real state).
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_MENTION_ON,
        fascination=_FakeFascinationReader(fascination=_FASCINATION),
    )

    await handler.handle(_message("расскажи подробно, чем занимался сегодня"))

    assert "орбитальная механика" in tier1.all_text


async def test_mention_fascination_is_a_noop_without_a_current_fascination() -> None:
    # No fascination on record (returns None): nothing is injected, the turn replies.
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_MENTION_ON,
        fascination=_FakeFascinationReader(fascination=None),
    )

    await handler.handle(_message("расскажи подробно, чем занимался сегодня"))

    assert bot.final_text == "hi"
    assert "увлеч" not in tier1.all_text.casefold()  # the preface never appeared


async def test_mention_fascination_is_a_noop_when_no_reader_wired() -> None:
    # No fascination reader injected (backward-compatible default): no effect.
    handler, bot, _repo, _tier1 = _build(reply="hi", expression_freqs=_MENTION_ON)

    await handler.handle(_message("расскажи подробно, чем занимался сегодня"))

    assert bot.final_text == "hi"


async def test_mention_fascination_is_a_noop_when_flag_is_off() -> None:
    # The flag is off (the common case): the passion is NOT surfaced even though one
    # exists — surfacing stays rare/à propos, never a per-message tic.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=_MENTION_OFF,
        fascination=_FakeFascinationReader(fascination=_FASCINATION),
    )

    await handler.handle(_message("расскажи подробно, чем занимался сегодня"))

    assert "орбитальная механика" not in tier1.all_text


# --- BOB-022: anti-repeat guard (defense in depth) ----------------------------

# A prior turn whose Bob reply is exactly what the model is about to repeat.
_REPEATED_REPLY = "Это длинный осмысленный ответ про космос и Бобиверс."
_PRIOR_DUP_TURN = f"Ada: расскажи\nbob: {_REPEATED_REPLY}"


async def test_verbatim_duplicate_reply_triggers_one_regeneration() -> None:
    # BOB-022: when the fresh reply is byte-identical (after strip) to Bob's most-
    # recent prior reply on record, handle() regenerates ONCE; with sampling now
    # stochastic the retry differs, so the committed reply is the fresh one.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_REPEATED_REPLY, "А вот теперь совсем другой ответ."],
        history=[{"content": _PRIOR_DUP_TURN, "event_type": "message"}],
    )

    await handler.handle(_message("объясни подробно ещё раз то же самое"))

    # The guard fired exactly one extra generation and the final reply differs.
    assert len(tier1.payloads) == 2
    assert bot.final_text == "А вот теперь совсем другой ответ."


async def test_verbatim_duplicate_kept_when_regeneration_still_identical() -> None:
    # No infinite loop: a stubborn HISTORY repeat (history is never dropped) regenerates
    # at most _MAX_REGENERATIONS (2, BOB-032 .1) times, then keeps the last draft.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_REPEATED_REPLY] * 4,
        history=[{"content": _PRIOR_DUP_TURN, "event_type": "message"}],
    )

    await handler.handle(_message("объясни подробно ещё раз то же самое"))

    # initial draft + 2 retries = 3 generations; the (still-duplicate) reply is kept.
    assert len(tier1.payloads) == 3
    assert bot.final_text == _REPEATED_REPLY


async def test_non_duplicate_reply_does_not_regenerate() -> None:
    # The common case: a fresh, non-duplicate reply is committed with no extra
    # generation — the guard only fires on an exact repeat of the last Bob reply.
    handler, bot, _repo, tier1 = _build(
        reply="Совершенно свежий ответ, не повтор.",
        history=[{"content": _PRIOR_DUP_TURN, "event_type": "message"}],
    )

    await handler.handle(_message("объясни подробно что-то новое"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == "Совершенно свежий ответ, не повтор."


async def test_guard_is_a_noop_with_no_prior_bob_reply_in_history() -> None:
    # With no prior Bob turn on record there is nothing to duplicate: the first
    # reply is committed as-is, no extra generation.
    handler, bot, _repo, tier1 = _build(
        reply="Первый ответ в диалоге.",
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == "Первый ответ в диалоге."


# --- BOB-026 .1: anti-repeat over a WINDOW (repeat "через ход") ----------------

# The user's reproduced case: the same отказ слips back AFTER another turn wedged
# between the two identical replies. The window guard (not just the last reply)
# must still catch it.
_OLDER_DECLINE = "Нет, таблицу я пока не нарисую — это вне моих возможностей."
_WEDGED_TURN = "Ada: таблицу?\nbob: " + _OLDER_DECLINE
_INTERVENING_TURN = "Ada: плохое настроение?\nbob: Да, серое какое-то."


async def test_repeat_through_a_turn_triggers_regeneration() -> None:
    # отказ → другой ход → ТОТ ЖЕ отказ 1-в-1. The previous guard compared only with
    # the LAST Bob reply ("Да, серое…") and let the repeat through; the window guard
    # catches the older identical decline and regenerates once.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_OLDER_DECLINE, "Ладно, давай попробую описать словами."],
        history=[
            {"content": _WEDGED_TURN, "event_type": "message"},
            {"content": _INTERVENING_TURN, "event_type": "message"},
        ],
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    assert len(tier1.payloads) == 2
    assert bot.final_text == "Ладно, давай попробую описать словами."


async def test_window_of_one_misses_the_repeat_through_a_turn() -> None:
    # Proof the WINDOW is the fix: with window=1 (the old behaviour — compare only the
    # last reply) the same repeat "через ход" is NOT caught — the older identical
    # decline is outside the one-reply window, so no regeneration fires.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_OLDER_DECLINE, "Ладно, давай попробую описать словами."],
        history=[
            {"content": _WEDGED_TURN, "event_type": "message"},
            {"content": _INTERVENING_TURN, "event_type": "message"},
        ],
        repeat_thresholds=RepeatThresholds(window=1),
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == _OLDER_DECLINE


async def test_near_verbatim_reply_triggers_regeneration() -> None:
    # Near-verbatim (a minor edit of the last reply) is caught too — not just an exact
    # byte match. The guard regenerates once and commits the genuinely-different retry.
    near = _OLDER_DECLINE.replace("пока не нарисую", "сейчас не нарисую")
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[near, "Ладно, опишу словами."],
        history=[{"content": _WEDGED_TURN, "event_type": "message"}],
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    assert len(tier1.payloads) == 2
    assert bot.final_text == "Ладно, опишу словами."


async def test_same_topic_different_reply_in_window_does_not_regenerate() -> None:
    # No false positive: an older decline on the SAME topic sits in the window, but a
    # substantively different fresh reply (same subject, different words) is committed
    # as-is — the conservative threshold does NOT mistake "related" for "repeat".
    substantively_different = (
        "Ладно, уговорил — давай я хотя бы наброшу структуру таблицы текстом."
    )
    handler, bot, _repo, tier1 = _build(
        reply=substantively_different,
        history=[
            {"content": _WEDGED_TURN, "event_type": "message"},
            {"content": _INTERVENING_TURN, "event_type": "message"},
        ],
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    assert len(tier1.payloads) == 1  # no needless regeneration
    assert bot.final_text == substantively_different


async def test_repeat_just_outside_the_window_is_not_caught() -> None:
    # Window boundary (off-by-one): with window=2 a verbatim repeat of a reply that is
    # the THIRD-newest Bob turn — one past the window edge — slips through, while the
    # companion through-a-turn test (window default 5) proves an in-window repeat is
    # caught. Together they pin the window as a real, bounded cutoff.
    older_reply = "Древний ответ, который выпал за пределы окна сравнения."
    handler, bot, _repo, tier1 = _build(
        reply=older_reply,
        history=[
            {"content": f"Ada: один\nbob: {older_reply}", "event_type": "message"},
            {"content": "Ada: два\nbob: Второй ответ.", "event_type": "message"},
            {"content": "Ada: три\nbob: Третий ответ.", "event_type": "message"},
        ],
        repeat_thresholds=RepeatThresholds(window=2),
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    # older_reply is the 3rd-newest Bob reply; window=2 compares only the two freshest,
    # so it is outside the window and no regeneration fires.
    assert len(tier1.payloads) == 1
    assert bot.final_text == older_reply


# --- BOB-026 .1: _recent_bob_replies window extractor (unit) -------------------


def test_recent_bob_replies_returns_window_freshest_first() -> None:
    # The extractor recovers the bob: half of each episode, newest-first, capped at
    # the window — this is the WINDOW the guard compares the fresh reply against.
    history = [
        {"content": "Ada: один\nbob: ответ один"},
        {"content": "Ada: два\nbob: ответ два"},
        {"content": "Ada: три\nbob: ответ три"},
    ]

    replies = _recent_bob_replies(history, limit=2)

    assert replies == ("ответ три", "ответ два")


def test_recent_bob_replies_skips_non_string_content() -> None:
    # A malformed episode whose content is not a string is skipped, not crashed on —
    # the scan continues to the next well-formed episode.
    history: list[dict[str, object]] = [
        {"content": "Ada: один\nbob: ответ один"},
        {"content": None},
        {"content": 123},
        {"content": "Ada: два\nbob: ответ два"},
    ]

    replies = _recent_bob_replies(history, limit=5)

    assert replies == ("ответ два", "ответ один")


def test_recent_bob_replies_empty_history_is_empty_tuple() -> None:
    # No Bob turn on record -> an empty tuple (the guard then never fires).
    assert _recent_bob_replies([], limit=5) == ()


def test_recent_bob_replies_ignores_turns_without_a_bob_half() -> None:
    # A user-only turn (no "\nbob: " marker) contributes no reply to the window.
    history = [{"content": "Ada: просто вопрос без ответа Боба"}]

    assert _recent_bob_replies(history, limit=5) == ()


# --- BOB-032 .1: recall-aware anti-repeat (R1) + attractor-breaking regen (R2) --

# A recalled semantic memory stored as a whole turn — Bob's old reply is the bob: half.
_RECALLED_OLD_REPLY = "Звучит как угроза, Ada."
_RECALLED_EPISODE: dict[str, object] = {
    "content": f"Ada: ты опять?\nbob: {_RECALLED_OLD_REPLY}",
    "category": "episodic",
}
# A fact-only recalled memory (no bob: half) — grounding content the retry must keep.
_RECALLED_FACT: dict[str, object] = {"content": "Ada предпочитает чай", "category": "personal"}


def test_recalled_bob_replies_recovers_the_bob_half() -> None:
    # The extractor recovers the bob: half of each recalled episode (the copyable
    # exemplar), reusing the same _BOB_TURN_MARKER recovery as history extraction.
    recalled = [_RECALLED_EPISODE, _RECALLED_FACT]

    assert _recalled_bob_replies(recalled) == (_RECALLED_OLD_REPLY,)


def test_recalled_bob_replies_skips_fact_only_and_blank_memories() -> None:
    # A fact-only memory (no marker), a non-string content, and a blank bob: half
    # contribute nothing — only real copyable reply exemplars feed the guard.
    recalled: list[dict[str, object]] = [
        _RECALLED_FACT,
        {"content": 123, "category": "x"},
        {"content": "Ada: пусто\nbob: ", "category": "episodic"},
        _RECALLED_EPISODE,
    ]

    assert _recalled_bob_replies(recalled) == (_RECALLED_OLD_REPLY,)


def test_recalled_bob_replies_empty_is_empty_tuple() -> None:
    # No recalled memories -> empty tuple (the guard then sees only history).
    assert _recalled_bob_replies([]) == ()


def test_recalled_without_copied_exemplars_drops_only_the_matched_episode() -> None:
    # The matched reply exemplar is removed; the fact-only memory (grounding) is kept —
    # recall-grounding of FACTS is never weakened, only the copied REPLY is withheld.
    recalled = [_RECALLED_EPISODE, _RECALLED_FACT]

    kept = _recalled_without_copied_exemplars(
        _RECALLED_OLD_REPLY, recalled, threshold=0.9
    )

    assert kept == (_RECALLED_FACT,)


def test_recalled_without_copied_exemplars_keeps_unmatched() -> None:
    # A substantively different candidate matches no exemplar -> the recalled set is
    # returned untouched (no false drop).
    recalled = [_RECALLED_EPISODE, _RECALLED_FACT]

    kept = _recalled_without_copied_exemplars(
        "Совершенно другой ответ по сути.", recalled, threshold=0.9
    )

    assert kept == (_RECALLED_EPISODE, _RECALLED_FACT)


def _recall_with(*memories: Mapping[str, object]) -> FakeRecall:
    """A recall double returning the given recalled memories (BOB-032 .1)."""
    return FakeRecall(hits=list(memories))


async def test_copying_a_recalled_reply_is_caught_and_regenerated() -> None:
    # R1: the candidate copies a RECALLED old reply that is NOT in recent history — the
    # history-only guard was blind to it. The recall-aware guard catches it and the
    # attractor-breaking retry commits the genuinely-different draft.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_RECALLED_OLD_REPLY, "А теперь по-настоящему другой ответ."],
        recall=_recall_with(_RECALLED_EPISODE),
    )

    await handler.handle(_message("ты опять про угрозу подробно ещё раз"))

    assert len(tier1.payloads) == 2  # the guard fired exactly one retry
    assert bot.final_text == "А теперь по-настоящему другой ответ."


async def test_retry_context_excludes_the_copied_recalled_exemplar() -> None:
    # R2 (structural): on the retry the copied recalled reply text is DROPPED from the
    # compose context (the model stops seeing what it echoed), while the fact-only
    # recalled memory is preserved — recall-grounding of facts stays intact.
    handler, _bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_RECALLED_OLD_REPLY, "Другой ответ."],
        recall=_recall_with(_RECALLED_EPISODE, _RECALLED_FACT),
    )

    await handler.handle(_message("ты опять про угрозу подробно ещё раз"))

    retry_text = "\n".join(m["content"] for m in tier1.payloads[1])
    assert _RECALLED_OLD_REPLY not in retry_text  # the copied exemplar is gone
    assert "Ada предпочитает чай" in retry_text  # the fact grounding is preserved


async def test_recall_repeat_breaks_attractor_after_one_retry() -> None:
    # R2 (attractor break): once the copied recalled exemplar is dropped from context,
    # the next draft — even if textually identical — is no longer a repeat (the guard can
    # no longer see the dropped exemplar, and history is empty), so it commits after ONE
    # retry. Dropping the attractor is what ends the loop, not the regeneration count.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_RECALLED_OLD_REPLY] * 5,
        recall=_recall_with(_RECALLED_EPISODE),
    )

    await handler.handle(_message("ты опять про угрозу подробно ещё раз"))

    assert len(tier1.payloads) == 2  # one retry: the exemplar was dropped
    assert bot.final_text == _RECALLED_OLD_REPLY


async def test_substantively_different_reply_with_recall_does_not_regenerate() -> None:
    # No false positive: a recalled old reply is in context, but the fresh reply is
    # substantively different — committed as-is, no needless regeneration.
    different = "Ничего общего с прошлым — свежая мысль про космос."
    handler, bot, _repo, tier1 = _build(
        reply=different,
        recall=_recall_with(_RECALLED_EPISODE),
    )

    await handler.handle(_message("расскажи что-нибудь новое подробно"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == different


async def test_guard_compares_against_union_of_history_and_recall() -> None:
    # R1 (union): history carries a DIFFERENT prior reply (no match there), yet the
    # candidate copies the RECALLED reply. The guard catches it via the recall half of
    # the union — proving recall, not only history, drives the catch — and regenerates.
    history_turn = "Ada: о чём угодно\nbob: Это был совсем иной ответ про погоду."
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_RECALLED_OLD_REPLY, "Свежий, не похожий ни на что ответ."],
        history=[{"content": history_turn, "event_type": "message"}],
        recall=_recall_with(_RECALLED_EPISODE),
    )

    await handler.handle(_message("ты опять про угрозу подробно ещё раз"))

    assert len(tier1.payloads) == 2  # the recall half of the union fired one retry
    assert bot.final_text == "Свежий, не похожий ни на что ответ."


async def test_normal_reply_with_recall_and_history_is_not_regenerated() -> None:
    # Regression / no over-firing: a genuinely fresh reply with BOTH a recalled reply
    # exemplar and a (different) prior history reply present commits on the first draft —
    # the union guard never false-fires when nothing is actually a repeat.
    history_turn = "Ada: о чём угодно\nbob: Прошлый ответ про погоду."
    fresh = "Совершенно новая мысль, не звучавшая раньше."
    handler, bot, _repo, tier1 = _build(
        reply=fresh,
        history=[{"content": history_turn, "event_type": "message"}],
        recall=_recall_with(_RECALLED_EPISODE),
    )

    await handler.handle(_message("расскажи что-то новое подробно"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == fresh


# --- BOB-022: user repeats themselves → Bob notices (voice directive) ----------

# A prior turn where the USER already said exactly what they are about to send again.
_USER_REPEATED_TEXT = "расскажи подробно про кофе"
_PRIOR_USER_REPEAT_TURN = f"Ada: {_USER_REPEATED_TEXT}\nbob: вот что я думаю про кофе"


def _has_user_repeat_directive(text: str) -> bool:
    # The directive's stable spine: it tells Bob the interlocutor is repeating and
    # that he must not pretend he did not notice.
    folded = text.casefold()
    return "повтор" in folded and "не делай вид" in folded


async def test_user_repeat_injects_the_voice_directive_into_the_prompt() -> None:
    # When the owner sends the same message they already sent in the recent window,
    # the compose prompt carries the user-repeat directive so Bob reacts in voice.
    handler, _bot, _repo, tier1 = _build(
        reply="другой ответ про кофе",
        history=[{"content": _PRIOR_USER_REPEAT_TURN, "event_type": "message"}],
    )

    await handler.handle(_message(_USER_REPEATED_TEXT))

    assert _has_user_repeat_directive(tier1.all_text)


async def test_non_repeat_does_not_inject_the_user_repeat_directive() -> None:
    # A fresh, different message must NOT trip the directive (conservative: exact
    # normalised match only, never fuzzy/false-firing).
    handler, _bot, _repo, tier1 = _build(
        reply="ответ про чай",
        history=[{"content": _PRIOR_USER_REPEAT_TURN, "event_type": "message"}],
    )

    await handler.handle(_message("а теперь расскажи про чай"))

    assert not _has_user_repeat_directive(tier1.all_text)


async def test_user_repeat_directive_composes_with_voice_and_tone() -> None:
    # The new directive AUGMENTS the existing voice/tone/form/language — it does not
    # displace the anti-bait voice or the mood-conditioned warm tone.
    handler, _bot, _repo, tier1 = _build(
        reply="другой ответ про кофе",
        history=[{"content": _PRIOR_USER_REPEAT_TURN, "event_type": "message"}],
    )

    await handler.handle(_message(_USER_REPEATED_TEXT))

    folded = tier1.all_text.casefold()
    assert _has_user_repeat_directive(folded)
    assert "эмодзи" in folded  # anti-bait voice still present
    assert "тепло" in folded  # warm tone_directive still present


async def test_user_repeat_only_counts_user_turns_not_bobs_reply() -> None:
    # Only the USER half of a prior episode counts: the current text matching Bob's
    # PRIOR reply (not the user's) must NOT be treated as the owner repeating himself.
    bob_said = "это был длинный ответ бориса про космос"
    prior = f"Ada: что нового\nbob: {bob_said}"
    handler, _bot, _repo, tier1 = _build(
        reply="свежий ответ",
        history=[{"content": prior, "event_type": "message"}],
    )

    await handler.handle(_message(bob_said))

    assert not _has_user_repeat_directive(tier1.all_text)


# --- BOB-019: sender perception — WHO is writing reaches the compose prompt -----


class _FakeInterlocutorResolver:
    """Fake perception seam: returns a fixed Interlocutor for any event (no authz).

    Records the events it was asked about so a test can assert the use-case
    perceives the sender once per turn.
    """

    def __init__(self, who: Interlocutor) -> None:
        self._who = who
        self.seen: list[MessageReceived] = []

    async def resolve(self, event: MessageReceived) -> Interlocutor:
        self.seen.append(event)
        return self._who


def _interlocutor(
    *,
    name: str,
    kind: InterlocutorKind,
    trust: Trust = Trust.TRUSTED,
    sender_id: int | None = 99,
) -> Interlocutor:
    return Interlocutor(
        sender_id=sender_id, display_name=name, kind=kind, trust=trust
    )


async def test_owner_identity_reaches_the_compose_prompt() -> None:
    # BOB-019: the perceived sender (name + kind) reaches the reply prompt, and the
    # owner is recognised AS the owner — folded in as character, not a config flag.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно про космос"))

    folded = tier1.all_text.casefold()
    assert "vova" in folded  # the name is perceived
    assert "владел" in folded  # recognised as owner (владелец)
    assert resolver.seen, "the use-case never perceived the sender"


async def test_known_friend_identity_reaches_the_compose_prompt() -> None:
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Ada", kind=InterlocutorKind.KNOWN)
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно про чай"))

    folded = tier1.all_text.casefold()
    assert "ada" in folded
    assert "знаком" in folded  # a known person


async def test_stranger_identity_reaches_the_compose_prompt() -> None:
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST)
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно что-нибудь"))

    folded = tier1.all_text.casefold()
    assert "rando" in folded
    assert "незнаком" in folded  # a stranger


async def test_sender_perception_composes_with_voice_and_tone() -> None:
    # BOB-019 is ADDITIVE: the who-is-writing line augments — never displaces — the
    # anti-bait voice, the warm mood tone, and the rest of the compose context.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=resolver)

    await handler.handle(_message("объясни подробно про минимализм в дизайне"))

    folded = tier1.all_text.casefold()
    assert "владел" in folded  # the perception line is present
    assert "эмодзи" in folded  # anti-bait voice still present
    assert "тепл" in folded  # warm tone_directive still present


async def test_no_resolver_leaves_the_compose_prompt_unchanged() -> None:
    # Backward-compatible: with no perception seam wired, the prompt carries no
    # who-is-writing line — exactly the pre-BOB-019 behaviour, full reply for all.
    handler, _bot, _repo, tier1 = _build(reply="hi")

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "пишет:" not in tier1.all_text.casefold()


async def test_owner_keeps_the_full_trusted_pipeline() -> None:
    # bob-apv.2: a TRUSTED owner turn still composes the full reply via the router,
    # so the committed reply is the model's answer exactly as before.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, bot, _repo, _tier1 = _build(
        reply="полный ответ как обычно", perceive_sender=resolver
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert bot.final_text == "полный ответ как обычно"


# --- bob-apv.2: guest (restricted) social mode — the security invariant ----------


def _guest_resolver() -> _FakeInterlocutorResolver:
    return _FakeInterlocutorResolver(
        _interlocutor(name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST)
    )


async def test_guest_turn_never_engages_the_tool_loop() -> None:
    # SECURITY INVARIANT: a guest can NOT trigger any capability. Even with a
    # registry + tool provider wired, a GUEST turn composes via the plain router —
    # the tool provider is never invoked and the capability is never dispatched.
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    handler, bot, _repo, _tier1 = _build(
        reply="привет, я Боб",
        registry=registry,
        tool_provider=provider,
        perceive_sender=_guest_resolver(),
    )

    await handler.handle(_message("расскажи подробно, что ты умеешь сделать для меня"))

    assert provider.tools_seen == []  # the tool loop never ran
    assert provider.turns == []  # the tool provider was never called at all
    assert cap.calls == []  # no capability dispatched for a guest
    assert bot.final_text == "привет, я Боб"  # he still replied via the router


async def test_guest_turn_does_not_recall_owner_memory() -> None:
    # SECURITY INVARIANT: owner-private memory is NOT recalled for a guest.
    recall = FakeRecall()
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", recall=recall, perceive_sender=_guest_resolver()
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert recall.surface_old_calls == []  # recall was never invoked for a guest


async def test_guest_turn_has_no_owner_private_content_in_the_prompt() -> None:
    # AUDIENCE REDACTION: a real owner-private recalled memory must NOT enter a
    # guest's compose prompt (recall is skipped entirely for a guest).
    recall = FakeRecall(
        hits=[{"content": _RECALL_MEMORY, "category": "personal"}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", recall=recall, perceive_sender=_guest_resolver()
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert _RECALL_MEMORY not in tier1.all_text  # owner memory redacted
    assert "recalled memories" not in tier1.all_text.casefold()


async def test_guest_turn_does_not_extract_facts_into_owner_memory() -> None:
    # SECURITY INVARIANT: a guest turn is NOT written into the owner's semantic
    # memory — _extract_facts is skipped, so no stranger input becomes a stored fact.
    repo = FakeRepo()
    tier0 = CapturingProvider(reply="positive", replies=None)
    tier1 = CapturingProvider(reply="hi")
    router = LLMRouter(providers={0: tier0, 1: tier1})
    clock = FixedClock(_moment())
    bot = FakeBot()
    gateway = TelegramGateway(
        bot=bot,
        bus=_NullBus(),
        poll_timeout=1,
        typing_interval=4.0,
        clock=lambda: 0.0,
        sleep=_parking_sleep,
    )

    class _RecordingExtractFacts:
        def __init__(self) -> None:
            self.calls = 0

        async def run(self, *, user_message: str, reply: str) -> None:  # noqa: ARG002
            self.calls += 1

    extract = _RecordingExtractFacts()
    handler = HandleMessage(
        router=router,
        gateway=gateway,
        recall=FakeRecall(),
        repo=repo,
        episodes=repo,
        update_mood=UpdateMoodFromText(router=router, clock=clock),
        extract_facts=extract,  # type: ignore[arg-type]
        clock=clock,
        state=PersonalityState(soul=_soul()),
        rng=Random(0),
        perceive_sender=_guest_resolver(),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert extract.calls == 0  # no fact extraction on a guest turn


async def test_guest_turn_has_no_owner_conversation_history_in_the_prompt() -> None:
    # AUDIENCE REDACTION: prior OWNER conversation persisted in Bob's topic must NOT
    # be replayed into a guest's compose prompt (default to MORE restriction). A
    # stranger who joins the group never sees the owner's earlier conversation.
    owner_private_turn = "Ada: моя приватная заметка про дела\nbob: понял, Ada"
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[{"content": owner_private_turn}],
        perceive_sender=_guest_resolver(),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert owner_private_turn not in tier1.all_text  # owner conversation redacted
    assert "recent conversation" not in tier1.all_text.casefold()


async def test_guest_turn_appends_the_stranger_directive() -> None:
    # The guest turn folds the stranger voice in so Bob meets a stranger as a
    # person (wary, may point them at the owner), in character.
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=_guest_resolver()
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    folded = tier1.all_text.casefold()
    assert "незнаком" in folded  # the stranger directive is present
    assert "владел" in folded  # may suggest asking the owner


async def test_guest_turn_skips_grounded_owner_inner_life_addons() -> None:
    # AUDIENCE REDACTION: Bob's private inner life (a leaked reflection) must NOT
    # reach a guest, even when the plan would have surfaced it.
    leak = "сегодня я поймал себя на мысли о приватном деле владельца"
    reflection = _FakeReflectionReader(text=leak)
    # Force the leak flag on every turn so absence proves the guest gate, not luck.
    freqs = ExpressionFreqs(leak_inner_life=1.0)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        reflection=reflection,
        expression_freqs=freqs,
        perceive_sender=_guest_resolver(),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert leak not in tier1.all_text  # the private reflection never reaches a guest


async def test_trusted_owner_turn_still_recalls_and_uses_tools() -> None:
    # NO REGRESSION: the trusted owner path is exactly as before — recall runs and
    # the tool loop engages when a registry + provider are wired.
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    recall = FakeRecall()
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=provider,
        recall=recall,
        perceive_sender=resolver,
    )

    await handler.handle(_message("what's my name?"))

    assert provider.tools_seen  # the tool loop ran for the owner
    assert cap.calls == [{"query": "name"}]  # the capability was dispatched
    assert recall.surface_old_calls == [False]  # owner memory was recalled
    assert bot.final_text == "Your name is Ada."


# --- First impression (BOB-019 bob-apv.3) -------------------------------------


class _FakeFirstImpression:
    """In-memory FirstImpressionReader fake: a fixed prior note + recording capture.

    ``prior`` is the note returned for a returning sender (``None`` for a fresh one);
    ``recorded`` captures every interlocutor a first-contact was noted for, so a test
    can assert Bob recorded a new sender's impression after the turn.
    """

    def __init__(self, *, prior: str | None = None) -> None:
        self._prior = prior
        self.recorded: list[Interlocutor] = []
        self.asked: list[Interlocutor] = []

    async def prior_impression(self, interlocutor: Interlocutor) -> str | None:
        self.asked.append(interlocutor)
        return self._prior

    async def note_first_contact(self, interlocutor: Interlocutor) -> None:
        self.recorded.append(interlocutor)


async def test_new_sender_first_contact_is_recorded_after_the_turn() -> None:
    # A new sender → Bob records a LIGHT first impression after replying (formed once).
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER, sender_id=99)
    )
    impressions = _FakeFirstImpression(prior=None)
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=resolver, first_impression=impressions
    )

    await handler.handle(_message("привет"))

    assert [who.sender_id for who in impressions.recorded] == [99]


async def test_returning_sender_prior_impression_reaches_the_prompt() -> None:
    # A sender Bob has met before → the prior note is folded into the compose prompt
    # so Bob recalls him wryly ("кажется, мы уже сталкивались").
    note = "тот самый незнакомец, держался настороже"
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST)
    )
    impressions = _FakeFirstImpression(prior=note)
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=resolver, first_impression=impressions
    )

    await handler.handle(_message("расскажи подробно, снова здравствуй, как ты"))

    folded = tier1.all_text.casefold()
    assert note in tier1.all_text  # the real prior note reaches the prompt
    assert "уже" in folded  # reads as recognition, not a fresh meeting


async def test_new_sender_has_no_recall_line_in_the_prompt() -> None:
    # A fresh sender (no prior note) is met blank — no recalled-impression line.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    impressions = _FakeFirstImpression(prior=None)
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=resolver, first_impression=impressions
    )

    await handler.handle(_message("привет"))

    assert "уже сталкивались" not in tier1.all_text.casefold()


async def test_guest_first_impression_is_used_without_leaking_owner_memory() -> None:
    # SECURITY: a guest's OWN prior first-impression is fine (it's about the guest),
    # and surfacing it must NOT pull in any owner-private memory — recall stays off
    # for a guest and no owner memory leaks even while the impression is recalled.
    note = "этот незнакомец уже заходил, держался ровно"
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    impressions = _FakeFirstImpression(prior=note)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        recall=recall,
        perceive_sender=_guest_resolver(),
        first_impression=impressions,
    )

    await handler.handle(_message("расскажи подробно, снова я заглянул к тебе"))

    assert note in tier1.all_text  # the guest's own impression is recalled
    assert _RECALL_MEMORY not in tier1.all_text  # owner memory still redacted
    assert recall.surface_old_calls == []  # recall never ran for a guest
    # The guest's own first contact is still recorded (per-PERSON data, about them).
    assert impressions.recorded


async def test_owner_path_unaffected_without_a_first_impression_seam() -> None:
    # NO REGRESSION: with no first-impression seam wired the owner turn is unchanged —
    # no recall line, the reply still lands as before.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, bot, _repo, tier1 = _build(reply="порядок", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert bot.final_text == "порядок"
    assert "сталкивались" not in tier1.all_text.casefold()


# --- bob-apv.4 (Tester): acceptance gap-filling ------------------------------
#
# These cover paths the dev waves left implicit: the first-impression best-effort
# failure resilience, the bot-kind perception (the "собеседник" abstraction covers
# bots — acceptance criterion 3), and an anonymous (no sender_id) guest turn.


class _RaisingFirstImpression:
    """A FirstImpressionReader whose first-contact recording always raises.

    Models a flaky first-impression store: the prior-impression read succeeds (so the
    turn composes normally) but ``note_first_contact`` blows up AFTER the reply, to
    prove the recording is best-effort and never breaks a turn that already replied.
    """

    def __init__(self) -> None:
        self.recorded = 0

    async def prior_impression(self, interlocutor: Interlocutor) -> str | None:  # noqa: ARG002
        return None

    async def note_first_contact(self, interlocutor: Interlocutor) -> None:  # noqa: ARG002
        self.recorded += 1
        raise RuntimeError("first-impression store unavailable")


async def test_first_impression_recording_failure_never_breaks_the_turn() -> None:
    # NO REGRESSION (resilience): a flaky first-impression store that raises while
    # recording first contact must NOT break a turn that has already replied — the
    # reply lands and the episode persists; the recording is best-effort.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    impressions = _RaisingFirstImpression()
    handler, bot, repo, _tier1 = _build(
        reply="всё в порядке",
        perceive_sender=resolver,
        first_impression=impressions,  # type: ignore[arg-type]
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела сегодня"))

    assert bot.final_text == "всё в порядке"  # the reply still landed
    assert len(repo.episodes) == 1  # the episode still persisted
    assert impressions.recorded == 1  # the (raising) recording WAS attempted


async def test_bot_kind_interlocutor_reaches_the_compose_prompt() -> None:
    # Acceptance criterion 3: the "собеседник" abstraction covers BOTS too. A BOT-kind
    # interlocutor's identity reaches the reply prompt so Bob perceives a peer bot as a
    # bot (foundation for a future BobNet) — folded in as character, not a flag.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Bender", kind=InterlocutorKind.BOT, trust=Trust.GUEST)
    )
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно про что-нибудь"))

    folded = tier1.all_text.casefold()
    assert "bender" in folded  # the bot's name is perceived
    assert "бот" in folded  # recognised as another bot


async def test_anonymous_guest_turn_replies_and_records_nothing() -> None:
    # EDGE CASE: a guest with NO sender_id (transport gave no identity) still routes
    # through the restricted guest path — Bob replies socially, no owner memory is
    # recalled, and the first-impression seam is a clean no-op for an unkeyable sender
    # (the tracker keys on sender_id; HandleMessage still calls it without crashing).
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    resolver = _FakeInterlocutorResolver(
        Interlocutor(
            sender_id=None,
            display_name="незнакомец",
            kind=InterlocutorKind.GUEST,
            trust=Trust.GUEST,
        )
    )
    impressions = _FakeFirstImpression(prior=None)
    handler, bot, _repo, tier1 = _build(
        reply="привет",
        recall=recall,
        perceive_sender=resolver,
        first_impression=impressions,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert bot.final_text == "привет"  # the anonymous guest still got a social reply
    assert recall.surface_old_calls == []  # owner memory never recalled for a guest
    assert _RECALL_MEMORY not in tier1.all_text  # no owner-private content leaked
    # The seam is still invoked with the no-id interlocutor (the tracker no-ops on it);
    # the recorded interlocutor carries no sender_id, so nothing keyable is stored.
    assert all(who.sender_id is None for who in impressions.recorded)


# --- Relationship (BOB-014) --------------------------------------------------


class _FakeRelationship:
    """In-memory RelationshipReader fake: a fixed current relationship + capture.

    ``current`` is the relationship returned for the turn (``None`` → a new person);
    ``interactions`` captures every (interlocutor, stance, mood, sentiment) recorded
    after a turn, so a test can assert the relationship is updated + persisted.
    """

    def __init__(self, *, current: Relationship | None = None) -> None:
        self._current = current
        self.interactions: list[tuple[Interlocutor, Stance, Mood, float]] = []

    async def current(self, interlocutor: Interlocutor) -> Relationship | None:  # noqa: ARG002
        return self._current

    async def record_interaction(
        self,
        interlocutor: Interlocutor,
        *,
        stance: Stance,
        mood: Mood,
        sentiment: float,
    ) -> None:
        self.interactions.append((interlocutor, stance, mood, sentiment))


def _soul_with_borderline_opinion(topic: str) -> SOUL:
    # A soul with an opinion whose conviction sits JUST above the BOB_PERSONAL
    # pushback threshold (0.5) → PROPOSE_ALTERNATIVE on its own, but low enough that
    # a close relationship's compromise-bias tips it to AGREE.
    baseline = Mood(valence=0.1, social=0.2)
    taste = TasteEngine(axes=(TasteAxis(name=topic, value=-0.6, conviction=0.55),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=(_PHANTOM_PREF,),
    )


async def test_high_warmth_relationship_warms_the_tone_directive() -> None:
    # BOB-014: a close (high-warmth) relationship colours Bob's voice warmer/closer.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    rel = _FakeRelationship(
        current=Relationship(sender_id=99, warmth=0.8, compatibility=0.7)
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=resolver, relationship=rel
    )

    await handler.handle(_message("расскажи подробно про космос"))

    folded = tier1.all_text.casefold()
    assert "близк" in folded or "по-свойски" in folded  # warmer/closer voice


async def test_low_warmth_relationship_cools_the_tone_directive() -> None:
    # A distant (low-warmth) relationship reads cooler/more reserved — never rude.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST)
    )
    rel = _FakeRelationship(
        current=Relationship(sender_id=99, warmth=-0.8, compatibility=-0.7)
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=resolver, relationship=rel
    )

    await handler.handle(_message("расскажи подробно что-нибудь интересное"))

    folded = tier1.all_text.casefold()
    assert "сдержан" in folded or "прохлад" in folded or "суш" in folded


async def test_close_relationship_makes_bob_more_willing_to_compromise() -> None:
    # BOB-014: warmth + compatibility nudge the negotiation toward compromise. A
    # borderline-firm opinion that would PROPOSE_ALTERNATIVE on its own is tipped to
    # AGREE for someone Bob is close to (he meets a close person halfway more readily).
    topic = "объясни подробно почему минимализм лучше всего"
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    rel = _FakeRelationship(
        current=Relationship(sender_id=99, warmth=1.0, compatibility=1.0)
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_borderline_opinion(topic),
        zone_classifier=_StubZoneClassifier(NegotiationZone.BOB_PERSONAL),
        perceive_sender=resolver,
        relationship=rel,
    )

    await handler.handle(_message(topic))

    # The close relationship tipped the borderline stance from holding ground to agree.
    assert _AGREE_DIRECTIVE in tier1.all_text
    assert _PROPOSE_DIRECTIVE not in tier1.all_text


async def test_distant_relationship_keeps_bob_holding_his_ground() -> None:
    # The same borderline opinion, but a NEUTRAL relationship → no compromise nudge,
    # so Bob holds his ground (PROPOSE_ALTERNATIVE) exactly as he would pre-BOB-014.
    topic = "объясни подробно почему минимализм лучше всего"
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST)
    )
    rel = _FakeRelationship(current=Relationship(sender_id=99))  # neutral
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_borderline_opinion(topic),
        zone_classifier=_StubZoneClassifier(NegotiationZone.BOB_PERSONAL),
        perceive_sender=resolver,
        relationship=rel,
    )

    await handler.handle(_message(topic))

    assert _PROPOSE_DIRECTIVE in tier1.all_text


async def test_relationship_is_updated_and_persisted_after_the_turn() -> None:
    # BOB-014: after the turn Bob records the interaction (stance, mood, sentiment) so
    # the relationship accrues — the seam is invoked once with the perceived sender.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER, sender_id=99)
    )
    rel = _FakeRelationship(current=None)
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=resolver, relationship=rel
    )

    await handler.handle(_message("привет, как ты"))

    assert len(rel.interactions) == 1
    who, _stance, _mood, _sentiment = rel.interactions[0]
    assert who.sender_id == 99


async def test_relationships_are_per_sender_isolated() -> None:
    # Owner and guest carry distinct relationships — the per-sender interlocutor keys
    # them apart (the seam records each turn's own interlocutor).
    owner_rel = _FakeRelationship(
        current=Relationship(sender_id=1, warmth=0.9, compatibility=0.8)
    )
    owner = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER, sender_id=1)
    )
    handler, _bot, _repo, owner_tier1 = _build(
        reply="hi", perceive_sender=owner, relationship=owner_rel
    )
    await handler.handle(_message("расскажи подробно про космос"))

    guest_rel = _FakeRelationship(
        current=Relationship(sender_id=2, warmth=-0.9, compatibility=-0.8)
    )
    guest = _FakeInterlocutorResolver(
        _interlocutor(
            name="Rando", kind=InterlocutorKind.GUEST, trust=Trust.GUEST, sender_id=2
        )
    )
    handler2, _bot2, _repo2, guest_tier1 = _build(
        reply="hi", perceive_sender=guest, relationship=guest_rel
    )
    await handler2.handle(_message("расскажи подробно что-нибудь"))

    owner_folded = owner_tier1.all_text.casefold()
    guest_folded = guest_tier1.all_text.casefold()
    # The owner (close) reads warm; the guest (distant) reads reserved — distinct.
    assert "близк" in owner_folded or "по-свойски" in owner_folded
    assert "сдержан" in guest_folded or "прохлад" in guest_folded or "суш" in guest_folded
    assert rel_sender_ids(owner_rel) == [1]
    assert rel_sender_ids(guest_rel) == [2]


def rel_sender_ids(rel: _FakeRelationship) -> list[int | None]:
    return [who.sender_id for who, *_ in rel.interactions]


async def test_no_relationship_seam_leaves_the_turn_unchanged() -> None:
    # NO REGRESSION: with no relationship seam wired, no relationship tone line and the
    # reply lands as before — exactly the pre-BOB-014 behaviour.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, bot, _repo, tier1 = _build(reply="порядок", perceive_sender=resolver)

    await handler.handle(_message("расскажи подробно, как дела"))

    assert bot.final_text == "порядок"
    folded = tier1.all_text.casefold()
    assert "по-свойски" not in folded
    assert "прохлад" not in folded


class _RaisingRelationship:
    """A RelationshipReader whose record_interaction always raises (flaky store)."""

    async def current(self, interlocutor: Interlocutor) -> Relationship | None:  # noqa: ARG002
        return None

    async def record_interaction(
        self,
        interlocutor: Interlocutor,  # noqa: ARG002
        *,
        stance: Stance,  # noqa: ARG002
        mood: Mood,  # noqa: ARG002
        sentiment: float,  # noqa: ARG002
    ) -> None:
        raise RuntimeError("relationship store unavailable")


async def test_relationship_recording_failure_never_breaks_the_turn() -> None:
    # NO REGRESSION (resilience): a flaky relationship store that raises while recording
    # must NOT break a turn that already replied — the reply lands, the episode persists.
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )
    handler, bot, repo, _tier1 = _build(
        reply="всё в порядке",
        perceive_sender=resolver,
        relationship=_RaisingRelationship(),  # type: ignore[arg-type]
    )

    await handler.handle(_message("расскажи подробно, как у тебя дела"))

    assert bot.final_text == "всё в порядке"
    assert len(repo.episodes) == 1


# --- Engagement appetite wiring (BOB-014 .2a) ------------------------------

# Stable fragments of the engagement voice directives (Russian) the prompt carries.
_DECLINE_FRAGMENT = "не тянет"
_TERSE_FRAGMENT = "интерес тает"
_PLAYFUL_FRAGMENT = "подурач"


def _soul_with_mood(mood: Mood, *, topic: str, value: float, conviction: float) -> SOUL:
    # A soul whose taste axis is keyed on the full message ``topic`` (how score()/
    # conviction_for match today) with a custom current mood, so the engagement
    # decision (mood x interest) can be driven deterministically.
    taste = TasteEngine(axes=(TasteAxis(name=topic, value=value, conviction=conviction),))
    return SOUL(
        identity="I am the Bob from the book.",
        mood=mood,
        mood_baseline=mood,
        taste=taste,
        phantom_prefs=(_PHANTOM_PREF,),
    )


async def test_bad_mood_aimless_topic_softly_declines_in_the_prompt() -> None:
    # Scenario 3: a low mood + a "какие-попало" (NEUTRAL, unknown) topic → DECLINE, so
    # the prompt carries the soft wind-down directive (never rude — sulk is .2b).
    bad = Mood(valence=-0.6, arousal=-0.1)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(bad, topic="zzz", value=0.0, conviction=0.0),
    )

    await handler.handle(_message("расскажи подробно про всякую ерунду"))

    assert _DECLINE_FRAGMENT in tier1.all_text


async def test_interesting_topic_overrides_bad_mood_no_decline_in_prompt() -> None:
    # Scenario 4: a genuinely interesting topic (strong LOVE + conviction, keyed on the
    # full message) engages Bob even in a low mood — the wind-down directive is absent.
    bad = Mood(valence=-0.6, arousal=-0.1)
    topic = "расскажи подробно про звёздные двигатели"
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(bad, topic=topic, value=0.9, conviction=0.9),
    )

    await handler.handle(_message(topic))

    assert _DECLINE_FRAGMENT not in tier1.all_text
    assert _TERSE_FRAGMENT not in tier1.all_text


async def test_high_fatigue_winds_chatter_down_in_the_prompt() -> None:
    # Scenario 2: built-up fatigue ("наскучило") on an uninteresting topic → DECLINE,
    # even in a normal mood — the prompt carries the wind-down directive.
    normal = Mood(valence=0.1, social=0.2)
    state = EngagementState(fatigue=ConversationalFatigue(0.95))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(normal, topic="zzz", value=0.0, conviction=0.0),
        engagement_state=state,
    )

    await handler.handle(_message("расскажи подробно ни о чём"))

    assert _DECLINE_FRAGMENT in tier1.all_text


async def test_aimless_turn_raises_fatigue() -> None:
    # Feedback: an aimless (uninteresting) turn tires Bob — fatigue rises on the holder.
    normal = Mood(valence=0.1, social=0.2)
    state = EngagementState(fatigue=ConversationalFatigue(0.0))
    handler, _bot, _repo, _tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(normal, topic="zzz", value=0.0, conviction=0.0),
        engagement_state=state,
    )

    await handler.handle(_message("расскажи подробно ни о чём"))

    assert state.fatigue.level > 0.0


async def test_interesting_turn_eases_fatigue() -> None:
    # Feedback: an interesting turn EASES fatigue (a good exchange is restorative).
    normal = Mood(valence=0.1, social=0.2)
    topic = "расскажи подробно про звёздные двигатели"
    state = EngagementState(fatigue=ConversationalFatigue(0.5))
    handler, _bot, _repo, _tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(normal, topic=topic, value=0.9, conviction=0.9),
        engagement_state=state,
        # No elapsed-time decay (last_turn_at unset on a fresh holder), so the change
        # asserted here is the interest-ease, not time decay.
    )

    await handler.handle(_message(topic))

    assert state.fatigue.level < 0.5


async def test_good_interesting_exchange_lifts_mood() -> None:
    # Feedback (scenario 4): an interesting, well-engaged exchange brightens Bob — the
    # post-turn mood valence on PersonalityState is higher than where it started.
    start = Mood(valence=0.1, social=0.2)
    topic = "расскажи подробно про звёздные двигатели"
    state = PersonalityState(soul=_soul_with_mood(start, topic=topic, value=0.9, conviction=0.9))
    # NEUTRAL sentiment isolates the engagement lift as the ONLY valence contributor:
    # perceive's sentiment step is zero, so a higher valence proves the feedback fired.
    handler, _bot, _repo, _tier1 = _build(reply="hi", tier0_replies=["neutral", "", ""])
    # Re-point the handler at our captured PersonalityState so we can read the lift.
    handler._state = state

    await handler.handle(_message(topic))

    # Valence rose above the starting 0.1 purely from the good-exchange mood lift.
    assert state.soul.mood.valence > start.valence


async def test_fatigue_recovers_over_elapsed_time_never_locks_out() -> None:
    # Guardrail: high fatigue DECAYS by real elapsed time between turns, so appetite
    # recovers and the owner is never permanently locked out. A long gap clears it.
    class _AdvancingClock:
        def __init__(self, *moments: datetime) -> None:
            self._moments = list(moments)
            self._i = 0

        def now(self) -> datetime:
            moment = self._moments[min(self._i, len(self._moments) - 1)]
            self._i += 1
            return moment

    normal = Mood(valence=0.1, social=0.2)
    # Seed the holder as if a turn happened long ago, then advance the clock a day.
    state = EngagementState(
        fatigue=ConversationalFatigue(0.95), last_turn_at=_moment()
    )
    later = datetime(2026, 6, 19, 14, 0, 0, tzinfo=UTC)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        soul=_soul_with_mood(normal, topic="zzz", value=0.0, conviction=0.0),
        engagement_state=state,
        clock=_AdvancingClock(later),  # type: ignore[arg-type]
    )

    await handler.handle(_message("расскажи подробно ни о чём"))

    # A day of quiet decayed the once-high fatigue right down — Bob is not locked out.
    assert state.fatigue.level < EngagementThresholds().high_fatigue
    assert _DECLINE_FRAGMENT not in tier1.all_text


# --- Sulk / обида (BOB-014 .2b) -----------------------------------------------


class _FakeSulk:
    """In-memory SulkReader fake: a fixed current state + capture of observations.

    ``current`` is the обида state returned for the turn (the cold-tone source);
    ``observations`` captures every (owner_warmth, hostile, warmth_delta) folded in
    after a turn so a test can assert the обида signal reacts to the right thing.
    """

    def __init__(self, *, current: SulkState | None = None) -> None:
        self._current = current if current is not None else SulkState()
        self.observations: list[tuple[float, bool, float]] = []

    async def current(self) -> SulkState:
        return self._current

    async def observe(
        self,
        *,
        owner_warmth: float,
        hostile: bool,
        warmth_delta: float,
        now: datetime,  # noqa: ARG002 - part of the seam contract, unused by the fake
    ) -> SulkState:
        self.observations.append((owner_warmth, hostile, warmth_delta))
        return self._current


def _owner_resolver() -> _FakeInterlocutorResolver:
    return _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER)
    )


async def test_active_sulk_makes_the_reactive_tone_cold() -> None:
    # BOB-014 .2b: while обижен, the reply prompt carries the cold sulk_directive —
    # quieter / curt, composed over the mood/relationship tone.
    sulk = _FakeSulk(current=SulkState(active=True, intensity=0.8, since=_moment()))
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=_owner_resolver(), sulk=sulk
    )

    await handler.handle(_message("расскажи подробно про космос"))

    folded = tier1.all_text.casefold()
    assert "обиж" in folded or "задет" in folded  # the cold sulk tone landed
    assert "груб" in folded  # explicitly NOT rude (без грубости)


async def test_not_sulking_leaves_the_tone_normal() -> None:
    # Not hurt → no cold line; the normal warm tone path is unchanged.
    sulk = _FakeSulk(current=SulkState())
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=_owner_resolver(), sulk=sulk
    )

    await handler.handle(_message("расскажи подробно про космос"))

    folded = tier1.all_text.casefold()
    assert "сейчас ты обижен" not in folded
    assert "тепл" in folded  # the warm tone band still present


async def test_owner_turn_feeds_the_sulk_signal() -> None:
    # An OWNER turn folds (owner_warmth, hostile, warmth_delta) into обида after.
    rel = _FakeRelationship(current=Relationship(sender_id=99, warmth=-0.6))
    sulk = _FakeSulk()
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=_owner_resolver(), relationship=rel, sulk=sulk
    )

    await handler.handle(_message("расскажи подробно про космос"))

    assert len(sulk.observations) == 1
    owner_warmth, _hostile, _delta = sulk.observations[0]
    assert owner_warmth == -0.6  # the owner relationship warmth fed the signal


async def test_directed_insult_flags_hostility_to_the_sulk_signal() -> None:
    # A DIRECTED insult is flagged hostile to the обида signal.
    sulk = _FakeSulk()
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=_owner_resolver(), sulk=sulk
    )

    await handler.handle(_message("ты тупой идиот"))

    assert sulk.observations[0][1] is True  # hostile flag set


async def test_casual_mat_is_not_flagged_hostile_to_the_sulk_signal() -> None:
    # Casual мат "with him" must NOT crater the relationship / trigger обида — it is
    # NOT flagged hostile, so the signal reacts to directed hostility, not vocabulary.
    sulk = _FakeSulk()
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=_owner_resolver(), sulk=sulk
    )

    await handler.handle(_message("блин, ну охренеть как круто получилось!"))

    assert sulk.observations[0][1] is False  # casual мат is not hostile


async def test_guest_turn_does_not_feed_the_sulk_signal() -> None:
    # обида v1 is tied to the OWNER relationship — a guest turn never feeds it.
    sulk = _FakeSulk()
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", perceive_sender=_guest_resolver(), sulk=sulk
    )

    await handler.handle(_message("ты тупой идиот"))

    assert sulk.observations == []  # owner-only


async def test_no_sulk_seam_leaves_the_turn_unchanged() -> None:
    # Backward-compatible default: no sulk seam wired → behaviour exactly as before.
    handler, _bot, _repo, tier1 = _build(reply="hi", perceive_sender=_owner_resolver())

    await handler.handle(_message("расскажи подробно про космос"))

    folded = tier1.all_text.casefold()
    assert "сейчас ты обижен" not in folded


# --- BOB-023: addressivity policy (engage / react / silent) ------------------


def _addr_message(
    text: str = "расскажи подробно про кофе",
    *,
    mentions_bob: bool = False,
    reply_to_sender_id: int | None = None,
    sender_name: str = "Ada",
) -> MessageReceived:
    """A MessageReceived carrying the BOB-023 addressivity signals."""
    return MessageReceived(
        update_id=1,
        chat_id=555,
        message_id=10,
        text=text,
        sender_id=99,
        sender_name=sender_name,
        reply_to_sender_id=reply_to_sender_id,
        mentions_bob=mentions_bob,
    )


# Recent thread history with a THIRD participant ("Гость"), so others_present is True
# and the ambient/directed-to-other policy engages.
_MULTIPARTY_HISTORY: tuple[Mapping[str, object], ...] = (
    {"content": "Ada: привет\nbob: здравствуй"},
    {"content": "Гость: всем привет\nbob: о, привет"},
)

# A 1:1 owner thread: every recent sender is the current one, so others_present is False.
_ONE_TO_ONE_HISTORY: tuple[Mapping[str, object], ...] = (
    {"content": "Ada: привет\nbob: здравствуй"},
    {"content": "Ada: как дела\nbob: норм"},
)


async def test_mention_always_engages_even_with_others_present() -> None:
    # DIRECTED_TO_BOB (an @mention) ALWAYS engages — never SILENT — even in a busy
    # multi-party thread and a boring topic.
    handler, bot, _repo, _tier1 = _build(
        reply="ответ Бобу", history=_MULTIPARTY_HISTORY
    )

    await handler.handle(_addr_message("ну такое", mentions_bob=True))

    assert bot.sent, "Bob did not reply to a message addressed to him"  # engaged


async def test_reply_to_bob_always_engages() -> None:
    # A reply to Bob's OWN message is for him → engages (reply_to == bob_user_id).
    handler, bot, _repo, _tier1 = _build(
        reply="продолжаю",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: 777,
    )

    await handler.handle(_addr_message("ага", reply_to_sender_id=777))

    assert bot.sent, "Bob did not reply to a message that replied to him"


async def test_reply_to_another_person_stays_silent() -> None:
    # DIRECTED_TO_OTHER (a reply to a third party, not Bob) → SILENT by default: Bob
    # does not barge into someone else's exchange. No reply, no reaction, no episode.
    reactor = _RecordingReactor()
    handler, bot, repo, _tier1 = _build(
        reply="не должен ответить",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: 777,
        reactor=reactor,
    )

    await handler.handle(_addr_message("согласен", reply_to_sender_id=12345))

    assert bot.sent == []  # silent: no reply
    assert reactor.calls == []  # and no like-reaction
    assert repo.episodes == []  # nothing persisted


async def test_directed_to_other_high_interest_can_barge_in() -> None:
    # A STRONGLY interesting topic can RARELY pull Bob into another's exchange — with
    # the barge-in threshold lowered + a seed whose roll clears the (small) frequency.
    thresholds = AddressivityThresholds(barge_in_interest=0.0, barge_in_freq=1.0)
    handler, bot, _repo, _tier1 = _build(
        reply="встряну на секунду",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: 777,
        addressivity_thresholds=thresholds,
    )

    await handler.handle(_addr_message("обожаю кофе", reply_to_sender_id=12345))

    assert bot.sent, "a strongly interesting topic should rarely pull Bob in"


async def test_ambient_one_to_one_engages() -> None:
    # AMBIENT in a 1:1 owner thread (no others present) → engages: Bob's own space.
    handler, bot, _repo, _tier1 = _build(
        reply="конечно отвечу", history=_ONE_TO_ONE_HISTORY
    )

    await handler.handle(_addr_message("просто так подумалось"))

    assert bot.sent, "Bob should engage on ambient chatter in his own 1:1 space"


async def test_ambient_with_others_stays_silent_by_default() -> None:
    # AMBIENT with other participants + boring topic + a roll above the react band →
    # SILENT (read it, not worth a word). react_chance=0 forces SILENT over REACT.
    thresholds = AddressivityThresholds(react_chance=0.0)
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=thresholds,
        rng=Random(0),
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert bot.sent == []  # silent


async def test_ambient_with_others_can_like_react() -> None:
    # AMBIENT with others → a like-reaction (REACT) instead of a full reply, when the
    # roll falls in the react band (react_chance=1.0 forces REACT over SILENT).
    reactor = _RecordingReactor()
    thresholds = AddressivityThresholds(react_chance=1.0)
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=thresholds,
        reactor=reactor,
    )

    await handler.handle(_addr_message("вот это денёк"))

    assert reactor.calls, "expected a like-reaction"
    assert bot.sent == []  # no composed reply


async def test_no_addressivity_signals_default_engages() -> None:
    # Backward-compatible: with no bob-id source and no multi-party history, a plain
    # message is AMBIENT in a 1:1 → engages exactly as before BOB-023.
    handler, bot, _repo, _tier1 = _build(reply="как обычно")

    await handler.handle(_addr_message("расскажи подробно про кофе"))

    assert bot.final_text == "как обычно"


def _low_interest_soul() -> SOUL:
    # A flat soul with no strong taste, so a neutral topic reads as low interest and
    # the ambient-with-others policy does not barge in on interest.
    baseline = Mood(valence=0.0, social=0.0)
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=TasteEngine(axes=()),
        phantom_prefs=(),
    )


def _off_day_soul() -> SOUL:
    # A flat, withdrawn, low-energy soul (a bad day): the DIRECTED_TO_BOB guardrail
    # must still always engage despite the poor mood.
    baseline = Mood(valence=-0.7, arousal=-0.6, social=-0.5)
    return SOUL(
        identity="I am the Bob from the book.",
        mood=baseline,
        mood_baseline=baseline,
        taste=TasteEngine(axes=()),
        phantom_prefs=(),
    )


# --- US-1 guardrail: к Бобу → ВСЕГДА ответ (свипы, плохое настроение, имя) ----


async def test_mention_always_engages_across_a_seed_sweep_on_a_bad_day() -> None:
    # GUARDRAIL: an @mention of Bob ALWAYS engages — over a seed sweep, with a busy
    # multi-party thread, a flat low-interest topic AND an off-day mood. The
    # addressivity gate never lets a message clearly FOR Bob fall into SILENT.
    for seed in range(40):
        handler, bot, _repo, _tier1 = _build(
            reply="отвечаю",
            history=_MULTIPARTY_HISTORY,
            soul=_off_day_soul(),
            rng=Random(seed),
        )
        await handler.handle(_addr_message("ну такое", mentions_bob=True))
        assert bot.sent, f"Bob stayed silent on an @mention (seed={seed})"


async def test_reply_to_bob_engages_across_a_seed_sweep() -> None:
    # GUARDRAIL: a reply to Bob's own message always engages, regardless of the
    # seeded roll, even on a boring topic in a busy thread.
    for seed in range(40):
        handler, bot, _repo, _tier1 = _build(
            reply="продолжаю",
            history=_MULTIPARTY_HISTORY,
            soul=_low_interest_soul(),
            bob_user_id_source=lambda: 777,
            rng=Random(seed),
        )
        await handler.handle(_addr_message("ага", reply_to_sender_id=777))
        assert bot.sent, f"Bob stayed silent on a reply to him (seed={seed})"


async def test_name_address_to_bob_engages_end_to_end() -> None:
    # US-1: a name-address at the start ("Боб, …") routes to DIRECTED_TO_BOB → ENGAGE
    # end to end, even amid other participants and a flat mood — Bob answers when
    # called by name (no @mention, no reply needed).
    handler, bot, _repo, _tier1 = _build(
        reply="да, слушаю",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
    )

    await handler.handle(_addr_message("Боб, ты тут?"))

    assert bot.sent, "Bob did not answer when called by name"


# --- US-3 guardrail: 1:1 owner↔Bob ambient → ВСЕГДА вступает (свип) -----------


async def test_ambient_one_to_one_always_engages_across_a_seed_sweep() -> None:
    # GUARDRAIL: in a 1:1 owner thread (no others present) ambient chatter ALWAYS
    # engages across a seed sweep — Bob never goes permanently silent in his own
    # space, even on a low-interest topic.
    for seed in range(40):
        handler, bot, _repo, _tier1 = _build(
            reply="отвечаю",
            history=_ONE_TO_ONE_HISTORY,
            soul=_low_interest_soul(),
            rng=Random(seed),
        )
        await handler.handle(_addr_message("просто так подумалось"))
        assert bot.sent, f"Bob stayed silent in his own 1:1 space (seed={seed})"


# --- US-2 guardrail: вклинивание в чужой диалог редко (свип) ------------------


async def test_directed_to_other_barge_in_is_rare_across_a_seed_sweep() -> None:
    # GUARDRAIL: on the conservative DEFAULT thresholds, even a strongly interesting
    # topic only RARELY pulls Bob into another's exchange — the vast majority of seeds
    # stay SILENT, so Bob does not hijack a third-party 1:1.
    engaged = 0
    for seed in range(40):
        handler, bot, _repo, _tier1 = _build(
            reply="встряну",
            history=_MULTIPARTY_HISTORY,
            bob_user_id_source=lambda: 777,
            rng=Random(seed),
        )
        await handler.handle(_addr_message("обожаю кофе", reply_to_sender_id=12345))
        engaged += bool(bot.sent)
    # The default barge_in_freq is 0.05, so over 40 seeds Bob speaks up only on a
    # small fraction (and usually not at all) — never a takeover.
    assert engaged <= 5, f"Bob barged into a third-party exchange {engaged}/40 times"


# --- bob_user_id is None: мягкая деградация ----------------------------------


async def test_reply_to_bob_does_not_fire_when_bob_id_unresolved() -> None:
    # GRACEFUL DEGRADATION: with Bob's identity unresolved (source yields None), a
    # reply that LOOKS like it targets Bob's id is NOT recognised as reply-to-Bob —
    # it reads as DIRECTED_TO_OTHER and Bob stays SILENT (he cannot claim it is his).
    reactor = _RecordingReactor()
    handler, bot, repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: None,
        reactor=reactor,
    )

    await handler.handle(_addr_message("ага", reply_to_sender_id=777))

    assert bot.sent == []  # reply-to-Bob could not fire → SILENT
    assert reactor.calls == []
    assert repo.episodes == []


async def test_mention_still_engages_when_bob_id_unresolved() -> None:
    # GRACEFUL DEGRADATION: an @mention does NOT depend on Bob's resolved id, so even
    # with the id source yielding None Bob still engages on a direct mention.
    handler, bot, _repo, _tier1 = _build(
        reply="на месте",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: None,
    )

    await handler.handle(_addr_message("эй", mentions_bob=True))

    assert bot.sent, "an @mention must engage even when Bob's id is unresolved"


async def test_no_crash_when_history_read_fails_for_addressivity() -> None:
    # GUARDRAIL: a flaky history read inside the addressivity gate degrades to a 1:1
    # read (others_present=False), so an ambient turn still ENGAGES (Bob is never
    # wrongly silenced in his own space) and the turn completes without raising.
    handler, bot, _repo, _tier1 = _build_with_episodes(
        reply="всё равно отвечу",
        episodes=_RaiseOnceEpisodes(),
    )

    await handler.handle(_addr_message("расскажи подробно, что ты думаешь"))

    assert bot.final_text == "всё равно отвечу"


# --- Гостевой инвариант (BOB-019) цел под адресностью ------------------------


async def test_guest_directed_to_bob_engages_but_stays_restricted() -> None:
    # GUEST INVARIANT under addressivity: a guest who addresses Bob (@mention) DOES
    # get a reply (DIRECTED_TO_BOB → ENGAGE), but the guest restriction still holds —
    # no owner memory is recalled and the tool loop never runs. Addressivity only adds
    # "stay quiet if not for me"; it never relaxes the guest guard.
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    handler, bot, _repo, tier1 = _build(
        reply="привет, я Боб",
        history=_MULTIPARTY_HISTORY,
        recall=recall,
        registry=registry,
        tool_provider=provider,
        perceive_sender=_guest_resolver(),
        bob_user_id_source=lambda: 777,
    )

    await handler.handle(_addr_message("Боб, что ты умеешь?", mentions_bob=True))

    assert bot.sent  # engaged on the direct address
    assert recall.surface_old_calls == []  # but no owner memory recalled
    assert cap.calls == []  # and no capability dispatched
    assert _RECALL_MEMORY not in tier1.all_text  # owner content stays redacted


async def test_guest_directed_to_other_stays_silent_and_leaks_nothing() -> None:
    # GUEST INVARIANT under addressivity: a guest replying to a THIRD party (not Bob)
    # → SILENT — Bob does not engage, and nothing is recalled, dispatched, or
    # persisted, so the SILENT path leaks no owner data for a guest either.
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    reactor = _RecordingReactor()
    handler, bot, repo, tier1 = _build(
        reply="не должен ответить",
        history=_MULTIPARTY_HISTORY,
        recall=recall,
        reactor=reactor,
        perceive_sender=_guest_resolver(),
        bob_user_id_source=lambda: 777,
    )

    await handler.handle(_addr_message("согласен", reply_to_sender_id=12345))

    assert bot.sent == []  # SILENT for a guest's third-party reply
    assert reactor.calls == []
    assert repo.episodes == []
    assert recall.surface_old_calls == []  # never recalled owner memory
    assert _RECALL_MEMORY not in tier1.all_text


# --- BOB-025: conversational floor (continuity over BOB-023) -----------------


async def test_ambient_with_others_engages_when_bob_holds_the_floor() -> None:
    # US-1/US-2 (continuity): an AMBIENT message amid other participants that would be
    # SILENT under BOB-023 is RAISED to DIRECTED_TO_BOB while Bob holds a live floor →
    # Bob engages (someone keeps talking to him without re-tagging).
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="продолжаю разговор",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert bot.sent, "Bob should engage on ambient chatter while he holds the floor"


async def test_ambient_with_others_stays_silent_when_floor_is_idle() -> None:
    # Non-interception: with an IDLE floor the continuity lift never fires, so an
    # ambient message amid others stays SILENT exactly as BOB-023 (Bob does not
    # hijack a third-party exchange).
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert bot.sent == []  # silent — floor is not Bob's, BOB-023 unchanged


async def test_no_floor_store_keeps_bob_023_behaviour() -> None:
    # Backward-compatible: with NO floor store wired, the effective addressivity is the
    # per-message classification (BOB-023), so an ambient-with-others turn stays SILENT.
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert bot.sent == []  # SILENT — no continuity without a store


async def test_floor_disabled_keeps_bob_023_behaviour() -> None:
    # Kill-switch: addressivity.floor.enabled=false → the floor is never resolved/
    # advanced even with a store wired, so behaviour is exactly BOB-023.
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
        floor_enabled=False,
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert bot.sent == []  # SILENT — floor disabled
    assert floor_store.loaded == []  # never even loaded
    assert floor_store.saved == []  # never advanced


async def test_engage_turn_advances_floor_to_bob_and_saves() -> None:
    # After an ENGAGE turn Bob replied → advance_floor(bob_replied=True) gives a BOB
    # floor (since=now, streak reset) and it is persisted on (chat_id, thread_id).
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="да, слушаю",
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("Боб, ты тут?"))

    assert bot.sent, "Bob should engage when called by name"
    assert floor_store.saved, "the floor must be saved after the turn"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.BOB  # Bob's reply sticks the floor to him
    assert saved.idle_streak == 0


async def test_silent_turn_advances_floor_without_bob_replied() -> None:
    # A SILENT third-party turn still advances + saves the floor (bob_replied=False),
    # so idle_streak / decay are tracked. A reply to ANOTHER person → floor=OTHER.
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен ответить",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: 777,
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("согласен", reply_to_sender_id=12345))

    assert bot.sent == []  # SILENT
    assert floor_store.saved, "the floor must advance even on a silent turn"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.OTHER  # turned to the third party
    assert saved.holder_id == 12345


async def test_timed_out_floor_does_not_lift_and_decays_to_idle() -> None:
    # US-4 (decay by timeout): a BOB floor older than the timeout is NOT live, so an
    # ambient-with-others turn is NOT raised (stays SILENT, BOB-023 cautious) and the
    # advance collapses the stale floor to IDLE.
    stale = ConversationFloor(
        holder=FloorHolder.BOB,
        holder_id=None,
        since=datetime(2026, 6, 18, 13, 0, 0, tzinfo=UTC),  # an hour before _moment()
        idle_streak=0,
    )
    floor_store = _FakeFloorStore(initial=stale)
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
        floor_config=FloorConfig(timeout_seconds=300),
    )

    await handler.handle(_addr_message("опять болтают", sender_name="Ada"))

    assert bot.sent == []  # SILENT — the stale floor does not lift ambient
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.IDLE  # decayed (timed out)


# --- BOB-025 acceptance: US-1..5 + guardrails (end-to-end through handle_message) --


class _SaveFailingFloorStore:
    """A floor store that LOADS fine but always raises on SAVE (BOB-025 best-effort).

    The floor *advance* (load → advance → save, in ``_advance_floor_after_turn``) is
    explicitly best-effort: a flaky store must NEVER break a turn that has already
    acted. This double makes the advance's save blow up so a test can assert the reply
    still lands and the failure is swallowed.

    NB: the resolve-phase load (``_resolve_effective_addressivity``) is NOT wrapped in
    that guard — see ``test_floor_store_resolve_load_failure_propagates`` documenting
    that asymmetry (a production observation, not asserted as desired).
    """

    def __init__(self) -> None:
        self.load_calls = 0
        self.save_calls = 0

    async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:  # noqa: ARG002
        self.load_calls += 1
        return idle_floor()

    async def save(
        self,
        chat_id: int,  # noqa: ARG002
        thread_id: int | None,  # noqa: ARG002
        floor: ConversationFloor,  # noqa: ARG002
    ) -> None:
        self.save_calls += 1
        raise RuntimeError("floor store save is down")


async def test_us1_owner_continuity_lifts_ambient_to_bob_after_he_held_the_floor() -> (
    None
):
    # US-1 (owner continuity): Bob holds a live floor (he just replied), so the owner's
    # NEXT untagged (AMBIENT) line amid other participants is RAISED to DIRECTED_TO_BOB
    # → Bob engages instead of going SILENT, and the advance re-glues the floor to him.
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="продолжаю с тобой",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        perceive_sender=_owner_resolver(),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("а ещё подумал вот о чём", sender_name="Vova"))

    assert bot.sent, "Bob should keep talking to the owner while he holds the floor"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.BOB  # his reply re-sticks the floor
    assert saved.idle_streak == 0


async def test_us2_continuity_follows_the_addressee_not_the_speaker_guest_keeps_it() -> (
    None
):
    # US-2 (continuity through a GUEST): the headline case — continuity is tied to the
    # ADDRESSEE (Bob), NOT to who spoke. Bob holds a live floor; an untagged line from a
    # DIFFERENT participant (a guest, not the one Bob last answered) is still lifted to
    # DIRECTED_TO_BOB → Bob engages.
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="да, и тебе отвечу",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        perceive_sender=_guest_resolver(),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("а я вот что думаю", sender_name="Rando"))

    assert bot.sent, "continuity is the addressee's — a guest in the thread keeps it"


async def test_us2_guest_continuity_lift_engages_but_stays_restricted() -> None:
    # US-2 + GUEST INVARIANT (BOB-019): when a guest's AMBIENT line is lifted to
    # DIRECTED_TO_BOB by continuity (not an @mention), Bob engages BUT the guest guard
    # still holds — no owner memory recalled, no tools dispatched, nothing leaked. The
    # floor changes addressivity only; it never relaxes the rights guard.
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, tier1 = _build(
        reply="отвечаю гостю",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        recall=recall,
        registry=registry,
        tool_provider=provider,
        perceive_sender=_guest_resolver(),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("просто продолжаю мысль", sender_name="Rando"))

    assert bot.sent  # engaged via continuity lift
    assert recall.surface_old_calls == []  # but no owner memory recalled
    assert cap.calls == []  # and no capability dispatched
    assert _RECALL_MEMORY not in tier1.all_text  # owner content stays redacted


async def test_us3_turn_to_another_hands_floor_to_other_and_bob_steps_back() -> None:
    # US-3 (turn to another): while Bob holds the floor, a reply to a NON-Bob person
    # (DIRECTED_TO_OTHER) is NOT lifted — Bob steps back (SILENT) and the floor is handed
    # to OTHER, so the next ambient line will no longer reach Bob.
    floor_store = _FakeFloorStore(initial=_live_bob_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен встревать",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        bob_user_id_source=lambda: 777,
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("согласен с тобой", reply_to_sender_id=12345))

    assert bot.sent == []  # Bob steps back: the turn is to someone else
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.OTHER  # floor handed to the third party
    assert saved.holder_id == 12345


async def test_us4_answered_ambient_in_live_floor_refreshes_and_resets_streak() -> None:
    # US-4 (refresh, the complement of decay): while Bob holds a LIVE floor, an AMBIENT
    # line amid others is lifted to DIRECTED_TO_BOB → Bob answers, so the advance runs
    # with bob_replied=True and the floor re-sticks to him with idle_streak reset to 0
    # (an answered ambient refreshes the floor; silence-driven decay is the unit layer).
    # Seed a floor already one silent step in, to prove the answer RESETS that streak.
    brink = ConversationFloor(
        holder=FloorHolder.BOB, holder_id=None, since=_moment(), idle_streak=1
    )
    floor_store = _FakeFloorStore(initial=brink)
    handler, bot, _repo, _tier1 = _build(
        reply="продолжаю",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
        floor_config=FloorConfig(reset_after_silent=2),
    )

    await handler.handle(_addr_message("ещё мысль", sender_name="Ada"))

    assert bot.sent, "an ambient in a live floor lifts → Bob answers"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.BOB
    assert saved.idle_streak == 0  # an answered ambient resets the streak


async def test_us4_decayed_floor_stops_lifting_and_bob_stays_out_of_others_talk() -> (
    None
):
    # US-4 (post-decay non-interception): once the floor has decayed to IDLE, an
    # ambient line amid others is no longer lifted — Bob stays SILENT, exactly BOB-023.
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=0.0),
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("они всё болтают", sender_name="Ada"))

    assert bot.sent == []  # IDLE floor never lifts → BOB-023 caution holds
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.IDLE  # stays released (ambient amid others)


async def test_us5_reply_to_bob_reclaims_floor_from_another_holder() -> None:
    # US-5 (direct always wins): a reply to Bob (DIRECTED_TO_BOB) (re)takes the floor
    # even when another person currently holds it — direct address always reaches Bob.
    other_floor = ConversationFloor(
        holder=FloorHolder.OTHER, holder_id=12345, since=_moment(), idle_streak=0
    )
    floor_store = _FakeFloorStore(initial=other_floor)
    handler, bot, _repo, _tier1 = _build(
        reply="да, я тут",
        history=_MULTIPARTY_HISTORY,
        bob_user_id_source=lambda: 777,
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("Боб, вернись", reply_to_sender_id=777))

    assert bot.sent, "a reply to Bob always engages, reclaiming the floor"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.BOB  # reclaimed from OTHER
    assert saved.holder_id is None


async def test_us5_name_address_takes_floor_from_idle() -> None:
    # US-5 (direct always wins): a "Боб, …" name-address from an IDLE floor amid others
    # is DIRECTED_TO_BOB → engages and the floor is taken to BOB (continuity then begins).
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="слушаю",
        history=_MULTIPARTY_HISTORY,
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("Боб, глянь сюда", sender_name="Ada"))

    assert bot.sent, "a name-address always engages even amid others"
    _chat, _thread, saved = floor_store.saved[-1]
    assert saved.holder is FloorHolder.BOB
    assert saved.idle_streak == 0


async def test_floor_is_keyed_by_chat_with_none_thread_sentinel() -> None:
    # Persistence seam: the floor is keyed by (chat_id, thread_id) with thread_id=None
    # (main chat) for now — load + save both address the same None-thread key.
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, _bot, _repo, _tier1 = _build(
        reply="ага",
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("Боб, привет", sender_name="Ada"))

    assert floor_store.loaded, "the floor is loaded for the turn"
    assert all(thread_id is None for _chat, thread_id in floor_store.loaded)
    _chat, thread_id, _saved = floor_store.saved[-1]
    assert thread_id is None  # main-chat sentinel


async def test_floor_advance_save_failure_is_best_effort_and_never_breaks_the_turn() -> (
    None
):
    # GUARDRAIL (best-effort advance): a floor store that raises on SAVE during the
    # post-turn advance must NOT break a turn that has already acted — Bob still replies;
    # the failure is swallowed (logged), not propagated.
    failing = _SaveFailingFloorStore()
    handler, bot, _repo, _tier1 = _build(
        reply="всё равно отвечу",
        floor_store=failing,  # type: ignore[arg-type]
    )

    await handler.handle(_addr_message("Боб, ты тут?", mentions_bob=True))

    assert bot.sent, "a flaky floor save must never break a turn that already acted"
    assert failing.save_calls, "the advance was attempted (and swallowed its failure)"


async def test_floor_store_resolve_load_failure_degrades_gracefully() -> None:
    # Best-effort floor (BOB-025): a store that raises on LOAD must NEVER break the turn.
    # The resolve phase (_resolve_effective_addressivity) is wrapped like the advance
    # path, so Bob falls back to the per-message BOB-023 classification and still replies
    # — a floor-store hiccup can never mute him.
    class _LoadFailingStore:
        async def load(self, chat_id: int, thread_id: int | None) -> ConversationFloor:  # noqa: ARG002
            raise RuntimeError("floor store load is down")

        async def save(
            self,
            chat_id: int,  # noqa: ARG002
            thread_id: int | None,  # noqa: ARG002
            floor: ConversationFloor,  # noqa: ARG002
        ) -> None:  # pragma: no cover - the advance path also hits the failing load first
            raise AssertionError("save should not be reached")

    handler, bot, _repo, _tier1 = _build(
        reply="я на месте",
        floor_store=_LoadFailingStore(),  # type: ignore[arg-type]
    )

    # A direct mention is DIRECTED_TO_BOB even on the per-message fallback, so Bob engages.
    await handler.handle(_addr_message("Боб, ты тут?", mentions_bob=True))

    # The store failure is swallowed best-effort — the turn still produced a reply.
    assert bot.sent, "a floor-store load failure must not mute Bob (best-effort floor)"


async def test_reactonly_turn_advances_floor_without_bob_replied() -> None:
    # REACT_ONLY-style outcome (a like-reaction, no composed reply) still advances the
    # floor with bob_replied=False — the floor tracks the real signal, and a reaction is
    # not a held turn (idle_streak counting continues).
    reactor = _RecordingReactor()
    floor_store = _FakeFloorStore(initial=idle_floor())
    handler, bot, _repo, _tier1 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=AddressivityThresholds(react_chance=1.0),
        reactor=reactor,
        floor_store=floor_store,
    )

    await handler.handle(_addr_message("вот это денёк", sender_name="Ada"))

    assert reactor.calls, "expected a like-reaction (REACT)"
    assert bot.sent == []  # no composed reply
    assert floor_store.saved, "even a react-only turn advances the floor"
    _chat, _thread, saved = floor_store.saved[-1]
    # An ambient react amid others with an IDLE floor → stays IDLE (Bob did not reply).
    assert saved.holder is FloorHolder.IDLE

# --- BOB-028 .3: мягкое применение self-improvement правил ---------------------


async def test_no_self_improvement_seam_leaves_prompt_unchanged() -> None:
    # Unwired (the default) → no tilt: the improvement voice line never appears, so the
    # turn behaves exactly as before BOB-028.
    handler, _bot, _repo, tier1 = _build(reply="ok")

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    assert "решил их мягко подправить" not in tier1.all_text


async def test_approved_tone_rule_folds_a_voice_tilt_into_the_prompt() -> None:
    # An APPROVED TONE rule's adjustment is folded into a soft voice line on TOP of the
    # mood/relationship tone — grounded in the real rule, never a personality reset.
    si = _FakeSelfImprovement(
        (_si_rule("t", lever=Lever.TONE, adjustment="говорить теплее с этим человеком"),)
    )
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    folded = tier1.all_text
    assert "решил их мягко подправить" in folded
    assert "говорить теплее с этим человеком" in folded


async def test_only_approved_rules_tilt_behaviour() -> None:
    # SAFETY: a PROPOSED rule (awaiting owner approval) NEVER applies — authz-before-
    # autonomy. The voice tilt must be absent even though a rule exists.
    si = _FakeSelfImprovement(
        (
            _si_rule(
                "p",
                lever=Lever.TONE,
                state=RuleState.PROPOSED,
                adjustment="говорить теплее",
            ),
        )
    )
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    assert "решил их мягко подправить" not in tier1.all_text


async def test_paused_rule_does_not_tilt_behaviour() -> None:
    # SAFETY: a PAUSED rule (owner temporarily disabled) does not apply either.
    si = _FakeSelfImprovement(
        (
            _si_rule(
                "pa",
                lever=Lever.TONE,
                state=RuleState.PAUSED,
                adjustment="говорить теплее",
            ),
        )
    )
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    assert "решил их мягко подправить" not in tier1.all_text


async def test_approved_length_rule_nudges_verbosity_shorter() -> None:
    # An APPROVED LENGTH rule shifts an EXPANSIVE turn one step shorter (to NORMAL): the
    # "можно развернуться" expansive cue is dropped — a soft tilt, not a base override.
    bright = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    inbound = "расскажи подробно, как именно это работает и почему так вышло"

    handler_base, _b0, _r0, tier_base = _build(reply="x", soul=bright)
    await handler_base.handle(_message(inbound))
    assert "можно развернуться" in tier_base.all_text.casefold()

    si = _FakeSelfImprovement((_si_rule("len", lever=Lever.LENGTH, magnitude=0.3),))
    handler_tilt, _b1, _r1, tier_tilt = _build(
        reply="x", soul=bright, self_improvement=si
    )
    await handler_tilt.handle(_message(inbound))
    # One step shorter: the EXPANSIVE-only cue is gone (наклон, не перехват).
    assert "можно развернуться" not in tier_tilt.all_text.casefold()


async def test_length_rule_never_inverts_a_terse_base() -> None:
    # SAFETY: the LENGTH tilt is bounded and never wraps — a turn already at TERSE stays
    # TERSE (the tilt clips at the bottom of the ladder, never raising it).
    withdrawn = _soul().with_mood(Mood(valence=-0.6, arousal=-0.8, social=-0.7))
    si = _FakeSelfImprovement((_si_rule("len", lever=Lever.LENGTH, magnitude=0.3),))
    handler, _bot, _repo, tier1 = _build(
        reply="ок", soul=withdrawn, self_improvement=si
    )

    await handler.handle(_message("а?? ну?"))

    # Still the strong terse cue (a tilt at the floor is a no-op, never an inversion).
    assert "коротк" in tier1.all_text.casefold()


async def test_approved_humor_rule_folds_a_voice_tilt_into_the_prompt() -> None:
    # US-3: a HUMOR lever rule shares the voice point with TONE — its adjustment folds
    # into the same soft voice line (one lever → one point), grounded in the real rule.
    si = _FakeSelfImprovement(
        (_si_rule("h", lever=Lever.HUMOR, adjustment="чуть больше лёгкой иронии"),)
    )
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    folded = tier1.all_text
    assert "решил их мягко подправить" in folded
    assert "чуть больше лёгкой иронии" in folded


async def test_positive_observation_rule_applies_like_any_other_lever() -> None:
    # US-4 (learns from good): an APPROVED rule that closes a POSITIVE observation
    # ("шутка зашла — добавь ещё") tilts exactly like any other — the mechanism is the
    # lever, not "fixing a mistake". The adjustment reaches the voice prompt unchanged.
    rule = ImprovementRule(
        id="good",
        observation="заметил, что тёплая шутка тут заходит",
        adjustment="закрепить эту тёплую интонацию",
        lever=Lever.TONE,
        magnitude=0.3,
        state=RuleState.APPROVED,
        origin=RuleOrigin.BOB_PROPOSED,
        created_at=_moment(),
        evidence="positive_signals",
    )
    si = _FakeSelfImprovement((rule,))
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    assert "закрепить эту тёплую интонацию" in tier1.all_text


@pytest.mark.parametrize(
    "state",
    [RuleState.PROPOSED, RuleState.PAUSED, RuleState.REJECTED, RuleState.REMOVED],
)
async def test_no_non_approved_state_ever_tilts_behaviour(state: RuleState) -> None:
    # SAFETY SWEEP (authz-before-autonomy): across EVERY non-APPROVED state, a rule with
    # a voice lever NEVER colours the prompt — only active_rules (APPROVED) apply.
    si = _FakeSelfImprovement(
        (_si_rule("x", lever=Lever.TONE, state=state, adjustment="говорить теплее"),)
    )
    handler, _bot, _repo, tier1 = _build(reply="ok", self_improvement=si)

    await handler.handle(_message("расскажи подробно, почему так вышло"))

    assert "решил их мягко подправить" not in tier1.all_text


async def test_addressivity_rule_lifts_a_quiet_turn_into_engagement() -> None:
    # US-3 (ADDRESSIVITY_BIAS apply): an ambient multi-party turn that only REACTS by
    # default (interest below the engage threshold) ENGAGES with a full reply once an
    # APPROVED ADDRESSIVITY_BIAS rule lifts the effective interest over the threshold —
    # a bounded nudge on TOP of BOB-023/025, never a base override. ambient_barge_in_freq
    # =1.0 keeps the roll out of the picture so ONLY the interest lift flips the outcome;
    # a wired reactor makes the base REACT visible (reactor called, no composed reply).
    thresholds = AddressivityThresholds(
        ambient_interest=0.99, ambient_barge_in_freq=1.0
    )

    base_reactor = _RecordingReactor()
    handler_base, base_bot, _r0, _t0 = _build(
        reply="не должен",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=thresholds,
        reactor=base_reactor,
        rng=Random(0),
    )
    await handler_base.handle(_addr_message("вот это денёк", sender_name="Ada"))
    assert base_bot.sent == []  # no composed reply without a rule (REACT, not ENGAGE)
    assert base_reactor.calls  # base interest only earns a like-reaction

    tilt_reactor = _RecordingReactor()
    si = _FakeSelfImprovement(
        (_si_rule("addr", lever=Lever.ADDRESSIVITY_BIAS, magnitude=1.0),)
    )
    handler_tilt, tilt_bot, _r1, _t1 = _build(
        reply="ладно, встряну",
        history=_MULTIPARTY_HISTORY,
        soul=_low_interest_soul(),
        addressivity_thresholds=thresholds,
        reactor=tilt_reactor,
        rng=Random(0),
        self_improvement=si,
        self_improvement_max_magnitude=1.0,
    )
    await handler_tilt.handle(_addr_message("вот это денёк", sender_name="Ada"))
    assert tilt_bot.sent, "the addressivity tilt should lift the quiet turn to engage"


async def test_addressivity_rule_never_silences_an_engaging_turn() -> None:
    # SAFETY: the ADDRESSIVITY_BIAS bias is non-negative — it can only RAISE willingness,
    # never silence Bob. A 1:1 turn that engages stays engaging with the rule present.
    si = _FakeSelfImprovement(
        (_si_rule("addr", lever=Lever.ADDRESSIVITY_BIAS, magnitude=0.3),)
    )
    handler, bot, _repo, _tier1 = _build(
        reply="как обычно", self_improvement=si
    )

    await handler.handle(_addr_message("расскажи подробно про кофе"))

    assert bot.sent, "a non-negative addressivity bias must never silence Bob"


async def test_summed_length_rules_stay_one_step_and_clipped() -> None:
    # SAFETY: even MANY APPROVED LENGTH rules together shift verbosity at most ONE step
    # (summed magnitude is clamped to the ceiling, then mapped to a single step) — the
    # ladder is never inverted no matter how many rules pile up.
    bright = _soul().with_mood(Mood(valence=0.6, arousal=0.7, openness=0.6, social=0.6))
    inbound = "расскажи подробно, как именно это работает и почему так вышло"
    si = _FakeSelfImprovement(
        tuple(
            _si_rule(f"len{i}", lever=Lever.LENGTH, magnitude=1.0) for i in range(5)
        )
    )
    handler, _bot, _repo, tier1 = _build(
        reply="x", soul=bright, self_improvement=si, self_improvement_max_magnitude=0.3
    )

    await handler.handle(_message(inbound))

    # One step shorter only: the EXPANSIVE-only cue is dropped, never inverted to TERSE
    # cues stacking — the single bounded step holds even under five maxed-out rules.
    assert "можно развернуться" not in tier1.all_text.casefold()


@pytest.mark.parametrize("ceiling", [-0.1, 1.5])
def test_out_of_range_max_magnitude_is_rejected_at_construction(ceiling: float) -> None:
    # SAFETY: the soft-tilt ceiling must lie in [0, 1] — an out-of-range value is a
    # configuration error and is rejected up front, never silently allowing a huge tilt.
    with pytest.raises(ValueError, match="self_improvement_max_magnitude"):
        _build(reply="ok", self_improvement_max_magnitude=ceiling)
