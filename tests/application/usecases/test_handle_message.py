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
from typing import TYPE_CHECKING

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.events import MessageReceived
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.handle_message import (
    HandleMessage,
    OwnerActivityRecorder,
    PersonalityState,
)
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.personality.mood import Mood
from bob.domain.personality.negotiation import NegotiationZone
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine, Verdict
from bob.domain.ports import ToolCall, ToolCallResult
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

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
    """Recall returning a canned (shareable) recalled memory."""

    async def recall(self, query: str, *, k: int) -> Sequence[Recalled]:  # noqa: ARG002
        return [{"content": _RECALL_MEMORY, "category": "personal"}]


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


def _build(
    *,
    reply: str,
    history: Sequence[Mapping[str, object]] = (),
    tier0_replies: Sequence[str] | None = None,
    registry: CapabilityRegistry | None = None,
    tool_provider: ToolCallingProvider | None = None,
    owner_activity: OwnerActivityRecorder | None = None,
    zone_classifier: ZoneClassifier | None = None,
    soul: SOUL | None = None,
) -> tuple[HandleMessage, FakeBot, FakeRepo, CapturingProvider]:
    tier0 = CapturingProvider(reply="positive", replies=tier0_replies)
    tier1 = CapturingProvider(reply=reply)
    router = LLMRouter(providers={0: tier0, 1: tier1})
    clock = FixedClock(_moment())
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
        recall=FakeRecall(),
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
    # The warm base persona is preserved alongside the new voice guidance.
    assert "warmly" in folded


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
    assert "warmly" in tier1.all_text


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
    assert "warmly" in tier1.all_text
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
    # The base warm prompt is still there.
    assert "warmly" in tier1.all_text


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
    assert "warmly" in tier1.all_text


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
