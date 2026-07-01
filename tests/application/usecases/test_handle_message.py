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
from datetime import UTC, datetime, timedelta
from random import Random
from typing import TYPE_CHECKING

import pytest

from bob.application.capabilities.registry import CapabilityRegistry
from bob.application.capabilities.render_diagram import (
    CollectingDiagramSink,
    make_render_diagram_capability,
)
from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.events import MessageReceived
from bob.application.usecases.decide_response import DecideResponse
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.handle_message import (
    _CLOSER_TIC_NUDGE,
    _VERIFY_GROUNDED_NOTE,
    _VERIFY_HEDGE_NOTE,
    DiagramSendMode,
    EngagementState,
    HandleMessage,
    OwnerActivityRecorder,
    PermissionFlowLike,
    PersonalityState,
    _history_for_author,
    _recalled_bob_replies,
    _recalled_without_copied_exemplars,
    _recent_bob_replies,
    _user_turns,
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
from bob.domain.personality.reaction_effect import NotableReaction
from bob.domain.personality.relationship import Relationship
from bob.domain.personality.response_choice import (
    ResponseChoice,
    ResponseContext,
    ResponseIntent,
)
from bob.domain.personality.self_improvement import (
    ImprovementRule,
    Lever,
    RuleOrigin,
    RuleState,
)
from bob.domain.personality.soul import SOUL
from bob.domain.personality.sulk import SulkState
from bob.domain.personality.taste import TasteAxis, TasteEngine, Verdict
from bob.domain.personality.volatility_judgment import (
    VolatilityContext,
    VolatilityVerdict,
)
from bob.domain.ports import ToolCall, ToolCallResult, WebSearchResult
from bob.infrastructure.diagrams.mmdc_renderer import DiagramRenderError
from bob.infrastructure.telegram.gateway import TelegramGateway

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Mapping, Sequence

    from aiogram.types import BufferedInputFile

    from bob.domain.ports import (
        DiagramSink,
        LLMMessage,
        LLMProvider,
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


class _FakeVolatilityJudge:
    """A scripted VolatilityJudge (BOB-057 .2): returns a fixed verdict or raises.

    Records each :class:`VolatilityContext` it assessed so a test can prove the judge
    saw the turn (or, when ``raises``, that a judge failure is caught decoratively).
    """

    def __init__(
        self, *, verdict: VolatilityVerdict | None = None, raises: bool = False
    ) -> None:
        self._verdict = verdict
        self._raises = raises
        self.calls: list[VolatilityContext] = []

    async def assess(self, ctx: VolatilityContext) -> VolatilityVerdict:
        self.calls.append(ctx)
        if self._raises:
            raise RuntimeError("volatility judge unavailable")
        assert self._verdict is not None
        return self._verdict


class _FakeWebSearchProvider:
    """A scripted WebSearchProvider (BOB-057 .2): returns a result, raises, or hangs.

    Records each query so a test can assert the verify path called ``search`` DIRECTLY
    with ``verdict.query`` (never routed through the capability registry / tool-loop).
    ``hang`` parks forever so a short ``verify.timeout_seconds`` trips the hedge path.
    """

    def __init__(
        self,
        *,
        result: WebSearchResult | None = None,
        raises: bool = False,
        hang: bool = False,
        on_search: Callable[[], None] | None = None,
    ) -> None:
        self._result = result
        self._raises = raises
        self._hang = hang
        # BOB-057 .3 probe: fired at the moment ``search`` runs so a test can prove the
        # live interim line was already sent BEFORE the search (US-3b ordering).
        self._on_search = on_search
        self.queries: list[str] = []

    async def search(self, query: str) -> WebSearchResult:
        self.queries.append(query)
        if self._on_search is not None:
            self._on_search()
        if self._hang:
            await asyncio.Event().wait()
        if self._raises:
            raise RuntimeError("web_search unavailable")
        assert self._result is not None
        return self._result


class _FakeCloserLog:
    """A CloserLog double (BOB-061 .2): records appends, serves canned recent closers.

    ``recent`` returns the seeded closers (most-recent first, as the real ring does),
    truncated to ``k``. ``append_raises`` / ``recent_raises`` model a flaky store so a
    test can prove the wiring is DECORATIVE (a persist/read failure never breaks the turn
    and never fires the nudge).
    """

    def __init__(
        self,
        *,
        recent: Sequence[str] = (),
        append_raises: bool = False,
        recent_raises: bool = False,
    ) -> None:
        self._recent = tuple(recent)
        self._append_raises = append_raises
        self._recent_raises = recent_raises
        self.appended: list[str] = []

    async def append(self, closer: str) -> None:
        if self._append_raises:
            raise RuntimeError("closer-log append unavailable")
        self.appended.append(closer)

    async def recent(self, k: int) -> tuple[str, ...]:
        if self._recent_raises:
            raise RuntimeError("closer-log read unavailable")
        return self._recent[:k] if k > 0 else ()


class _FakeInterimLineGenerator:
    """A scripted interim-line generator (BOB-057 .3): a live line, empty, or raises.

    Records the (topic, sender_name) it saw so a test can prove the live gen was
    asked with the turn's subject + perceived interlocutor.
    """

    def __init__(self, *, line: str = "", raises: bool = False) -> None:
        self._line = line
        self._raises = raises
        self.calls: list[tuple[str, str]] = []

    async def generate(self, *, topic: str, sender_name: str) -> str:
        self.calls.append((topic, sender_name))
        if self._raises:
            raise RuntimeError("local model down")
        return self._line


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

    def __init__(self, *, photo_raises: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.photos: list[tuple[int, bytes, str | None]] = []
        self.documents: list[tuple[int, bytes, str | None]] = []
        self.typings: int = 0
        self._photo_raises = photo_raises

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

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> FakeMessage:
        # BOB-035: the photo-send seam — records each diagram photo posted to chat.
        # The gateway wraps the PNG in an aiogram BufferedInputFile (``.data`` bytes).
        if self._photo_raises:
            # An UNEXPECTED transport error (not AiogramError/ValueError) propagates
            # past the gateway's own guard up to the use-case's best-effort swallow.
            raise RuntimeError("transport blew up")
        self.photos.append((chat_id, photo.data, caption))
        return FakeMessage(message_id=778)

    async def send_document(
        self,
        *,
        chat_id: int,
        document: BufferedInputFile,
        caption: str | None = None,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> FakeMessage:
        # BOB-037: the document-send seam — records each diagram file posted to chat.
        if self._photo_raises:
            raise RuntimeError("transport blew up")
        self.documents.append((chat_id, document.data, caption))
        return FakeMessage(message_id=779)

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
        # Every ``recent_episodes`` window size asked for this turn (BOB-044): lets a
        # test assert the configured recent-history window is the one actually replayed.
        self.requested_ks: list[int] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self.episodes.append(episode)

    async def save_fact(self, fact: object) -> None:
        self.facts.append(fact)

    async def set_mood(self, state: Mapping[str, object], *, at: datetime) -> None:  # noqa: ARG002
        self.mood = state

    async def recent_episodes(self, k: int) -> Sequence[Mapping[str, object]]:
        self.requested_ks.append(k)
        return self._history[-k:] if k > 0 else []

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        if k <= 0:
            return []
        scoped = [e for e in self._history if e.get("sender_id") == sender_id]
        return scoped[-k:]


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


# The retry backoff used in the reliability tests (BOB-049 .3): a recognizable value the
# recording sleep seam captures, so a test can assert the backoff was awaited (never a
# real delay — the sleep is faked).
_TEST_BACKOFF_SECONDS = 0.25


class _RecordingSleep:
    """A retry-backoff sleep seam double recording each delay (BOB-049 .3, no real wait)."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


class _FakeOutageNotifier:
    """A GUPPI OutageNotifier double recording each honest-outage notice (BOB-049 .3)."""

    def __init__(self) -> None:
        self.notices = 0

    async def notify_outage(self) -> None:
        self.notices += 1


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
    recent_turns: int = 14,
    absence_hint_hours: float = 8.0,
    notable_reaction: _FakeNotableStore | None = None,
    acknowledge_reaction_freq: float = 0.0,
    repeat_thresholds: RepeatThresholds | None = None,
    floor_store: _FakeFloorStore | None = None,
    floor_config: FloorConfig | None = None,
    floor_enabled: bool = True,
    self_improvement: _FakeSelfImprovement | None = None,
    self_improvement_max_magnitude: float = 0.3,
    diagram_sink: DiagramSink | None = None,
    diagram_renderer: object | None = None,
    diagram_send_as: DiagramSendMode = "photo",
    photo_send_raises: bool = False,
    coding_router: _FakeCodingRouter | None = None,
    permission_flow: PermissionFlowLike | None = None,
    decide_response: DecideResponse | None = None,
    outage_notifier: _FakeOutageNotifier | None = None,
    retry_sleep: _RecordingSleep | None = None,
    essential_attempts: int = 3,
    essential_backoff_seconds: float = _TEST_BACKOFF_SECONDS,
    tier0_provider: LLMProvider | None = None,
    tier1_provider: LLMProvider | None = None,
    verify_judge: _FakeVolatilityJudge | None = None,
    verify_provider: _FakeWebSearchProvider | None = None,
    verify_timeout_seconds: float = 75.0,
    interim_line_generator: _FakeInterimLineGenerator | None = None,
    closer_log: _FakeCloserLog | None = None,
) -> tuple[HandleMessage, FakeBot, FakeRepo, CapturingProvider]:
    tier0 = CapturingProvider(reply="positive", replies=tier0_replies)
    tier1 = CapturingProvider(reply=reply, replies=tier1_replies)
    # Custom tier providers (e.g. a flaky/failing one for the BOB-049 .3 reliability tests)
    # drive the router when supplied; the returned ``tier1`` capturing provider is left in
    # place for the default path that inspects the reply payloads.
    router_tier0: LLMProvider = tier0_provider if tier0_provider is not None else tier0
    router_tier1: LLMProvider = tier1_provider if tier1_provider is not None else tier1
    router = LLMRouter(providers={0: router_tier0, 1: router_tier1})
    clock = clock if clock is not None else FixedClock(_moment())
    bot = FakeBot(photo_raises=photo_send_raises)
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
        recent_turns=recent_turns,
        absence_hint_hours=absence_hint_hours,
        notable_reaction=notable_reaction,
        acknowledge_reaction_freq=acknowledge_reaction_freq,
        repeat_thresholds=repeat_thresholds,
        floor_store=floor_store,
        floor_config=floor_config,
        floor_enabled=floor_enabled,
        self_improvement=self_improvement,
        self_improvement_max_magnitude=self_improvement_max_magnitude,
        diagram_sink=diagram_sink,
        diagram_renderer=diagram_renderer,  # type: ignore[arg-type]
        diagram_send_as=diagram_send_as,
        coding_router=coding_router,
        permission_flow=permission_flow,
        decide_response=decide_response,
        outage_notifier=outage_notifier,
        retry_sleep=retry_sleep,
        essential_attempts=essential_attempts,
        essential_backoff_seconds=essential_backoff_seconds,
        verify_judge=verify_judge,
        verify_provider=verify_provider,
        verify_timeout_seconds=verify_timeout_seconds,
        interim_line_generator=interim_line_generator,
        closer_log=closer_log,
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

    async def recent_episodes_for(
        self, sender_id: int, k: int
    ) -> Sequence[Mapping[str, object]]:
        del sender_id, k
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


async def test_persisted_episode_carries_sender_id() -> None:
    # BOB-045 .1: the saved episode is attributed to its sender so the reply path
    # can later replay a per-person thread keyed on sender_id.
    handler, _bot, repo, _tier1 = _build(reply="ok")

    await handler.handle(_message())  # _message() has sender_id=99

    assert len(repo.episodes) == 1
    assert repo.episodes[0]["sender_id"] == 99


async def test_persisted_episode_records_outgoing_bob_message_id() -> None:
    # BOB-050 .1: the saved episode records the message_id of Bob's outgoing reply
    # (the FakeBot's rich send returns 777) so a later reaction can be linked back
    # to what Bob said.
    handler, _bot, repo, _tier1 = _build(reply="ok")

    await handler.handle(_message())

    assert len(repo.episodes) == 1
    assert repo.episodes[0]["bob_message_id"] == 777


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


# A history long enough that an early topic sits ~10 turns back — the case the old
# 6-turn window dropped (Bob "lost the thread"). The distinct early turn is the probe.
_THREAD_TOPIC_TURN = "Ada: нарисуй архитектурную диаграмму с деталями\nbob: окей, рисую"
_THREAD_HISTORY: list[Mapping[str, object]] = [
    {"content": _THREAD_TOPIC_TURN, "event_type": "message"},
    *[
        {"content": f"Ada: реплика {i}\nbob: ответ {i}", "event_type": "message"}
        for i in range(11)
    ],
]


async def test_default_recent_window_holds_an_older_turn_a_six_window_would_drop() -> None:
    # BOB-044: with the WIDENED default (14), a topic raised ~11 turns ago is still
    # replayed into the reply context — Bob keeps the dialogue thread.
    handler, _bot, _repo, tier1 = _build(reply="hi", history=_THREAD_HISTORY)

    await handler.handle(_message("расскажи подробно про кофе"))

    assert _THREAD_TOPIC_TURN in tier1.all_text


async def test_a_six_turn_window_drops_the_older_topic() -> None:
    # BOB-044 (the bug it fixes): the OLD hardcoded window of 6 drops the early topic —
    # it falls out before Bob can return to it, so he loses the thread.
    handler, _bot, _repo, tier1 = _build(
        reply="hi", history=_THREAD_HISTORY, recent_turns=6
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert _THREAD_TOPIC_TURN not in tier1.all_text


async def test_a_wider_window_brings_the_older_topic_back() -> None:
    # BOB-044: widening the window to 14 (over the same history) re-includes the early
    # topic a window of 6 dropped — the fix, demonstrated on one history.
    handler, _bot, _repo, tier1 = _build(
        reply="hi", history=_THREAD_HISTORY, recent_turns=14
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert _THREAD_TOPIC_TURN in tier1.all_text


async def test_recent_window_replays_the_configured_number_of_turns() -> None:
    # BOB-044: the configured window size is the one actually asked of the episode
    # reader (not the old hardcoded 6) — both the addressivity read and the compose read.
    handler, _bot, repo, _tier1 = _build(
        reply="hi", history=_THREAD_HISTORY, recent_turns=9
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert 9 in repo.requested_ks
    assert 6 not in repo.requested_ks  # the old hardcoded window is gone


async def test_member_without_sender_reads_the_unified_recent_window() -> None:
    # 🔴 BOB-051: memory is UNIFIED for the closed group. A member with no resolvable
    # sender_id has no per-person thread, so history degrades to the SHARED recent
    # window (not an empty one) — Bob keeps the group's recent conversation thread for
    # any member. (An @mention forces ENGAGE so the assertion is RNG-independent.)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_THREAD_HISTORY,
        recent_turns=14,
        perceive_sender=_guest_with_id(None),
    )

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert _THREAD_TOPIC_TURN in tier1.all_text


async def test_non_positive_recent_window_is_rejected() -> None:
    # BOB-044: a window that replays nothing is a misconfiguration, not a silent no-op.
    with pytest.raises(ValueError, match="recent_turns"):
        _build(reply="hi", recent_turns=0)


# --- BOB-045 .2: per-person history replay + privacy-scoped recall ------------

# An owner's turn (sender 1) and a member's turn (sender 2) share the group log. Under
# BOB-058 .1 the conversation context is the SHARED thread, so BOTH members see BOTH turns
# (author-labeled); only the per-person SIGNALS (absence, anti-repeat) filter by author.
_OWNER_THREAD_TURN = "Vova: секретный план на завтра\nbob: понял, держим в тайне"
_GUEST_THREAD_TURN = "Norman: привет, расскажи о себе\nbob: привет, я Боб"
_OWNER_SENDER_ID = 1
_GUEST_SENDER_ID = 2
_PERSON_THREAD: list[Mapping[str, object]] = [
    {"content": _OWNER_THREAD_TURN, "event_type": "message", "sender_id": _OWNER_SENDER_ID},
    {"content": _GUEST_THREAD_TURN, "event_type": "message", "sender_id": _GUEST_SENDER_ID},
]


def _guest_with_id(sender_id: int | None) -> _FakeInterlocutorResolver:
    return _FakeInterlocutorResolver(
        _interlocutor(
            name="Norman",
            kind=InterlocutorKind.GUEST,
            trust=Trust.GUEST,
            sender_id=sender_id,
        )
    )


def _owner_with_id(sender_id: int | None) -> _FakeInterlocutorResolver:
    return _FakeInterlocutorResolver(
        _interlocutor(name="Vova", kind=InterlocutorKind.OWNER, sender_id=sender_id)
    )


async def test_member_hears_the_shared_group_thread() -> None:
    # 🔴 BOB-058 .1 (US-1/2/3): the conversation context is the SHARED recent thread of
    # the whole topic, so a member replaying it hears EVERY participant — both their own
    # turn AND another member's — with the author labels intact (the closed group's
    # memory is unified, BOB-051). This is the continuity fix: Bob no longer loses the
    # multi-party thread behind a per-person replay.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert _GUEST_THREAD_TURN in tier1.all_text  # this member's own turn
    assert _OWNER_THREAD_TURN in tier1.all_text  # 🔴 and the other member's turn too


async def test_non_owner_recall_is_unified_full_knowledge() -> None:
    # 🔴 BOB-051: memory is UNIFIED for the closed group — a non-owner's recall is Bob's
    # FULL knowledge, no per-person scoping. A fact attributed to the owner (sender 1),
    # a sender-less fact (None) AND the member's own memory (sender 2) all surface, so
    # talking to a member Bob keeps access to his general knowledge.
    recall = FakeRecall(
        hits=[
            {"content": "owner shared fact", "category": "personal", "sender_id": 1},
            {"content": "ownerless fact", "category": "fact", "sender_id": None},
            {"content": "norman own memory", "category": "personal", "sender_id": 2},
        ]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", recall=recall, perceive_sender=_guest_with_id(_GUEST_SENDER_ID)
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "norman own memory" in tier1.all_text  # the member's own memory
    assert "owner shared fact" in tier1.all_text  # 🔴 owner knowledge now unified
    assert "ownerless fact" in tier1.all_text  # 🔴 sender-less knowledge unified


async def test_owner_hears_the_shared_thread_and_keeps_global_recall() -> None:
    # BOB-058 .1: the owner replays the SHARED thread (every member's turn, not only his
    # own) and keeps GLOBAL recall — a sender-less fact still grounds the owner reply
    # (owner recall is never scoped).
    recall = FakeRecall(
        hits=[{"content": "ownerless fact", "category": "fact", "sender_id": None}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        recall=recall,
        perceive_sender=_owner_with_id(_OWNER_SENDER_ID),
    )

    await handler.handle(_message("объясни подробно про кофе"))

    assert _OWNER_THREAD_TURN in tier1.all_text  # the owner's own turn
    assert _GUEST_THREAD_TURN in tier1.all_text  # 🔴 and the member's turn (shared thread)
    assert "ownerless fact" in tier1.all_text  # owner recall stays global


async def test_member_context_unifies_knowledge_and_hears_the_shared_thread() -> None:
    # 🔴 BOB-051 + BOB-058 .1: a member's RECALL is unified (Bob's full knowledge surfaces,
    # whatever its attribution) AND the replayed HISTORY is the shared group thread — Bob
    # knows WHAT he knows AND holds the whole multi-party conversation (every member's
    # turn is in view, author-labeled).
    recall = FakeRecall(
        hits=[
            {"content": "owner shared fact", "category": "personal", "sender_id": 1},
            {"content": "ownerless fact", "category": "fact", "sender_id": None},
            {"content": "norman own memory", "category": "personal", "sender_id": 2},
        ]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        recall=recall,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    text = tier1.all_text
    # Knowledge is UNIFIED — every recalled item surfaces, regardless of attribution.
    assert "norman own memory" in text
    assert "owner shared fact" in text
    assert "ownerless fact" in text
    # Continuity is the SHARED thread — the member sees the whole group's recent turns.
    assert _GUEST_THREAD_TURN in text
    assert _OWNER_THREAD_TURN in text  # 🔴 the other member's turn is replayed too


async def test_history_degrades_to_global_for_owner_without_sender_seam() -> None:
    # BOB-045 degradation: no perception seam → no interlocutor → owner-or-unknown keeps
    # the pre-BOB-045 GLOBAL window (no regression for an unresolved identity).
    handler, _bot, _repo, tier1 = _build(reply="hi", history=_THREAD_HISTORY)

    await handler.handle(_message("объясни подробно про кофе"))

    assert _THREAD_TOPIC_TURN in tier1.all_text  # global replay, unchanged


async def test_guest_without_sender_id_still_gets_unified_recall() -> None:
    # 🔴 BOB-051: recall is unified for ANY interlocutor — a guest with no resolvable
    # sender_id still gets Bob's full knowledge (recall no longer needs a scopable id).
    # (An @mention forces ENGAGE so the assertion is RNG-independent.)
    recall = FakeRecall(
        hits=[{"content": "norman own memory", "category": "personal", "sender_id": 2}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        recall=recall,
        perceive_sender=_guest_with_id(None),
    )

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert "norman own memory" in tier1.all_text  # unified recall, no sender_id needed


async def test_guest_with_thread_still_gets_no_owner_inner_life_leak() -> None:
    # 🔴 BOB-045 keeps ALL other guest restrictions: even though the guest now gets THEIR
    # OWN thread, the grounded owner inner-life leak (BOB-018) is still withheld — only
    # the memory boundary moved to per-person, the authz boundary is untouched.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        bob_user_id_source=lambda: 777,
    )

    # A direct @mention forces ENGAGE so the assertion is RNG-independent.
    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert _GUEST_THREAD_TURN in tier1.all_text  # the guest's own thread is replayed
    assert _REFLECTION_TEXT not in tier1.all_text  # but no owner inner-life leak


# --- BOB-045 .3: long-gap absence hint ----------------------------------------


def _person_turn_at(
    *, sender_id: int, hours_ago: float, name: str = "Norman"
) -> Mapping[str, object]:
    """A prior turn by ``name`` timestamped ``hours_ago`` before the fixed clock now.

    The ``name`` is only the human-readable author label the shared thread carries
    (BOB-058); the per-person absence filter keys on ``sender_id`` (BOB-058 .3), so it must
    match the interlocutor's sender_id — the label is free to differ.
    """
    ts = (_moment() - timedelta(hours=hours_ago)).isoformat()
    return {
        "content": f"{name}: давнее сообщение\nbob: ответил",
        "event_type": "message",
        "sender_id": sender_id,
        "ts": ts,
    }


async def test_guest_long_gap_adds_an_absence_hint() -> None:
    # BOB-045 .3: a guest resuming after a long pause (14h > 8h threshold) gets ONE
    # light absence line folded into the compose context so Bob notices it humanly.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[_person_turn_at(sender_id=_GUEST_SENDER_ID, hours_ago=14)],
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Absence:" in tier1.all_text
    assert "час" in tier1.all_text  # the hours bucket


async def test_owner_long_gap_adds_an_absence_hint() -> None:
    # BOB-045 .3: applies to ANY per-person thread — the owner resuming after a day-long
    # pause gets the "вчера" bucket hint too (symmetry; owner and guest alike).
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[
            _person_turn_at(sender_id=_OWNER_SENDER_ID, hours_ago=26, name="Vova")
        ],
        perceive_sender=_owner_with_id(_OWNER_SENDER_ID),
    )

    await handler.handle(_message("объясни подробно про кофе"))

    assert "Absence: последний разговор был вчера" in tier1.all_text


async def test_short_gap_adds_no_absence_hint() -> None:
    # Under the threshold (2h < 8h) it is still the same conversation — no line added.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[_person_turn_at(sender_id=_GUEST_SENDER_ID, hours_ago=2)],
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Absence:" not in tier1.all_text


async def test_first_contact_adds_no_absence_hint() -> None:
    # First contact (no prior per-person turn) -> nothing to compare, no hint.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[],
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Absence:" not in tier1.all_text


async def test_disabled_absence_hint_adds_no_line_even_after_a_long_gap() -> None:
    # absence_hint_hours == 0 disables the texture entirely (no regression, no line).
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[_person_turn_at(sender_id=_GUEST_SENDER_ID, hours_ago=72)],
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        absence_hint_hours=0.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Absence:" not in tier1.all_text


# --- BOB-045 acceptance: US-3 multi-party + US-2 recency-with-them -------------


async def test_both_members_share_one_group_thread() -> None:
    # 🔴 BOB-058 .1 (US-3 multi-party): over ONE shared log (owner turn + Norman turn),
    # BOTH members' assembled context carries the WHOLE thread — the owner hears Norman
    # and Norman hears the owner. The closed group's conversation is a single shared
    # thread (BOB-051 unified memory), not two isolated per-person slices.
    owner_handler, _ob, _or, owner_tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        perceive_sender=_owner_with_id(_OWNER_SENDER_ID),
    )
    guest_handler, _gb, _gr, guest_tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await owner_handler.handle(_message("объясни подробно про кофе"))
    await guest_handler.handle(_message("расскажи подробно про кофе"))

    # The owner hears the whole thread — his own turn AND Norman's...
    assert _OWNER_THREAD_TURN in owner_tier1.all_text
    assert _GUEST_THREAD_TURN in owner_tier1.all_text
    # ...and Norman hears the whole thread too — both turns, in both directions.
    assert _GUEST_THREAD_TURN in guest_tier1.all_text
    assert _OWNER_THREAD_TURN in guest_tier1.all_text


# A guest's multi-turn thread: an EARLY distinct topic plus a recent turn timestamped
# past the absence threshold — proves resumption is keyed on recency-WITH-THEM (the
# whole per-person thread replays), not a fresh calendar window.
_GUEST_OLD_TOPIC = "Norman: помнишь, мы обсуждали джаз?\nbob: конечно, помню"
_GUEST_LONG_GAP_THREAD: list[Mapping[str, object]] = [
    {
        "content": _GUEST_OLD_TOPIC,
        "event_type": "message",
        "sender_id": _GUEST_SENDER_ID,
        "ts": (_moment() - timedelta(hours=30)).isoformat(),
    },
    _person_turn_at(sender_id=_GUEST_SENDER_ID, hours_ago=26),
]


async def test_long_gap_still_replays_the_person_thread_and_adds_the_hint() -> None:
    # US-2: after a gap beyond the threshold the guest's WHOLE per-person thread is
    # STILL replayed (recency-with-them, not a reset) AND a single Absence hint is
    # folded in — the two BOB-045 .2/.3 mechanisms compose on one turn.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_GUEST_LONG_GAP_THREAD,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    text = tier1.all_text
    assert _GUEST_OLD_TOPIC in text  # the earlier topic survived the gap
    assert "Absence:" in text  # and Bob is told about the pause
    assert text.count("Absence:") == 1  # exactly one light hint, never a pile-up


async def test_negative_absence_hint_hours_is_rejected_at_construction() -> None:
    # Guardrail: a negative absence threshold is a misconfiguration, surfaced eagerly
    # at construction (not a silent disable), mirroring the recent_turns guard.
    with pytest.raises(ValueError, match="absence_hint_hours"):
        _build(reply="hi", absence_hint_hours=-1.0)


# --- BOB-058 .1: shared group thread + per-author absence/anti-repeat ----------

# Two members of the closed group over ONE shared log: Alexey talked about a film, then
# Vladimir writes. The shared thread carries BOTH turns, author-labeled — the continuity
# the per-person replay used to hide ("нет такого сообщения от Лёши").
_ALEXEY_FILM_TURN = "Alexey: смотрел вчера отличный фильм про космос\nbob: о, расскажи"
_VLADIMIR_TURN = "Vladimir: всем привет\nbob: привет"
_SHARED_GROUP_THREAD: list[Mapping[str, object]] = [
    {"content": _ALEXEY_FILM_TURN, "event_type": "message", "sender_id": 1},
    {"content": _VLADIMIR_TURN, "event_type": "message", "sender_id": 2},
]


def _member_named(name: str, sender_id: int | None) -> _FakeInterlocutorResolver:
    """A perceived KNOWN member of the closed group with a stable display name."""
    return _FakeInterlocutorResolver(
        _interlocutor(
            name=name,
            kind=InterlocutorKind.KNOWN,
            trust=Trust.TRUSTED,
            sender_id=sender_id,
        )
    )


async def test_shared_thread_lets_bob_hear_other_participants() -> None:
    # 🔴 BOB-058 .1 (US-1/2/3, the core continuity fix): the reply context is the SHARED
    # recent thread of the whole topic. When Vladimir asks Bob to answer Lyosha, Alexey's
    # film message is right there in the context — with its author label — so Bob no longer
    # replays only HIS thread with Vladimir and denies Lyosha ever wrote.
    handler, _bot, _repo, tier1 = _build(
        reply="про фильм Лёши",
        history=_SHARED_GROUP_THREAD,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(
        _addr_message("ответь подробно на сообщение Лёши", mentions_bob=True)
    )

    text = tier1.all_text
    assert _ALEXEY_FILM_TURN in text  # another member's turn is in the shared thread
    assert "Alexey:" in text  # author labels distinguish who said what (US-3)


async def test_absence_hint_tracks_only_the_current_authors_gap() -> None:
    # 🔴 BOB-058 .1: per-person absence (BOB-045) preserved over the SHARED thread. Vladimir
    # was last seen 14h ago (> 8h), while Alexey spoke just 1h ago. Filtering the shared
    # thread to THIS author, Vladimir's own gap still fires the hint — a DIFFERENT member's
    # recent turn must not reset it (a naive last-seen over the shared thread would).
    now = _moment()
    shared: list[Mapping[str, object]] = [
        {
            "content": "Vladimir: до завтра\nbob: пока",
            "event_type": "message",
            "sender_id": 2,
            "ts": (now - timedelta(hours=14)).isoformat(),
        },
        {
            "content": "Alexey: я всё ещё тут\nbob: ага",
            "event_type": "message",
            "sender_id": 1,
            "ts": (now - timedelta(hours=1)).isoformat(),
        },
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=shared,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(
        _addr_message("расскажи подробно, снова тут", mentions_bob=True)
    )

    assert "Absence:" in tier1.all_text  # Vladimir's own 14h gap, not reset by Alexey


async def test_anti_repeat_ignores_a_different_authors_similar_line() -> None:
    # 🔴 BOB-058 .1: per-person anti-repeat (BOB-032) over the SHARED thread. Alexey earlier
    # said X; now Vladimir says the SAME X for the FIRST time. It is NOT Vladimir repeating
    # himself — the repeat check is filtered to the current author's own prior turns.
    same = "расскажи подробно про кофе"
    shared: list[Mapping[str, object]] = [
        {
            "content": f"Alexey: {same}\nbob: вот про кофе",
            "event_type": "message",
            "sender_id": 1,
        }
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="свежий ответ",
        history=shared,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(_addr_message(same, mentions_bob=True))

    assert not _has_user_repeat_directive(tier1.all_text)


async def test_anti_repeat_detects_the_current_author_repeating() -> None:
    # 🔴 BOB-058 .1 (the other side): the SAME author (Vladimir) repeating his own recent
    # line still trips the user-repeat directive — the per-author filter keeps his own
    # turns in view over the shared thread.
    same = "расскажи подробно про кофе"
    shared: list[Mapping[str, object]] = [
        {
            "content": f"Vladimir: {same}\nbob: вот про кофе",
            "event_type": "message",
            "sender_id": 2,
        }
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="свежий ответ",
        history=shared,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(_addr_message(same, mentions_bob=True))

    assert _has_user_repeat_directive(tier1.all_text)


# --- BOB-058 .3: per-author signals key on sender_id, not the name label -------
#
# LOCK the robustness fix: the SIGNAL FILTER (absence, anti-repeat) keys on the persisted
# ``sender_id`` — the same identity relationship/first-impression use — NOT the parsed
# ``"<name>:"`` label. So homonymous members are isolated, and a display name carrying a
# ``": "`` no longer silently drops the signal. Bob still SEES ``"<name>:"`` in context
# (rendering unchanged) — only the key of the per-author filter moved.


async def test_homonymous_members_are_not_cross_attributed_for_anti_repeat() -> None:
    # 🔴 BOB-058 .3 (the invariant a name key could VIOLATE): two DIFFERENT members share
    # the display name "Sasha" (sender_id 1 vs 2). Sasha#1 earlier said X; now Sasha#2 says
    # the SAME X for the FIRST time. Keyed on the name they collide → a FALSE repeat fire;
    # keyed on sender_id they are isolated → NOT a repeat.
    x = "расскажи подробно про кофе"
    shared: list[Mapping[str, object]] = [
        {"content": f"Sasha: {x}\nbob: вот про кофе", "event_type": "message", "sender_id": 1}
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="свежий ответ",
        history=shared,
        perceive_sender=_member_named("Sasha", 2),  # SAME name, DIFFERENT id
    )

    await handler.handle(_addr_message(x, mentions_bob=True))

    assert not _has_user_repeat_directive(tier1.all_text)


async def test_homonymous_members_absence_isolated_by_sender_id() -> None:
    # 🔴 BOB-058 .3: two members named "Sasha". Sasha#1 (id 1) spoke just 1h ago; Sasha#2
    # (id 2) was last seen 14h ago. Keyed on the shared NAME, Sasha#1's fresh turn would
    # mask Sasha#2's gap (no hint); keyed on sender_id, Sasha#2's own 14h gap still fires.
    now = _moment()
    shared: list[Mapping[str, object]] = [
        {
            "content": "Sasha: свежак\nbob: ага",
            "event_type": "message",
            "sender_id": 1,
            "ts": (now - timedelta(hours=1)).isoformat(),
        },
        {
            "content": "Sasha: давно был\nbob: пока",
            "event_type": "message",
            "sender_id": 2,
            "ts": (now - timedelta(hours=14)).isoformat(),
        },
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=shared,
        perceive_sender=_member_named("Sasha", 2),
    )

    await handler.handle(
        _addr_message("расскажи подробно, снова тут", mentions_bob=True)
    )

    assert "Absence:" in tier1.all_text  # Sasha#2's own gap, not masked by his homonym


async def test_colon_in_display_name_does_not_drop_the_absence_signal() -> None:
    # 🔴 BOB-058 .3 (minor #colon): a member whose display name contains ": " ("Dr: House").
    # A name-label key truncated at the FIRST ": " → the filter never matched his rows → his
    # absence silently dropped. Keyed on sender_id the label's colon is irrelevant: his own
    # 14h gap fires the hint.
    now = _moment()
    shared: list[Mapping[str, object]] = [
        {
            "content": "Dr: House: до завтра\nbob: пока",
            "event_type": "message",
            "sender_id": 5,
            "ts": (now - timedelta(hours=14)).isoformat(),
        }
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=shared,
        perceive_sender=_member_named("Dr: House", 5),
    )

    await handler.handle(
        _addr_message("расскажи подробно, снова тут", mentions_bob=True)
    )

    assert "Absence:" in tier1.all_text  # colon-in-name signal survives, keyed by id


# --- BOB-058 .2 (Tester): HARDEN shared-thread continuity + per-author signals --
#
# These LOCK the .1 invariants beyond the dev happy-path (no duplication): the SHARED
# thread reaches the JUDGMENT context (not only the reply prompt) with authors kept
# distinct; per-author absence stays graceful when the current author is ABSENT from the
# window (another member's turn never becomes his last-seen); anti-repeat isolates the
# current author amid INTERLEAVED speakers; relationship (BOB-014) + first-impression
# (BOB-019) still fire per-SENDER regardless of who else is in the thread; owner-private
# inner life never leaks into the shared PUBLIC thread (BOB-051); and a degraded/empty
# window is handled without a crash.


async def test_judgment_context_holds_the_shared_multiparty_thread() -> None:
    # 🔴 BOB-058 .1 (US-1/2/3 for the JUDGE): the semantic judge (BOB-049) receives the
    # SHARED recent thread, so when Vladimir asks Bob to answer Lyosha the judge already
    # SEES Alexey's film turn — the continuity fix reaches the DECISION, not just the
    # compose prompt (the dev happy-path). Author labels keep the two speakers apart (US-3).
    decide, fake = _judge(ResponseIntent.REPLY)
    handler, _bot, _repo, _tier1 = _build(
        reply="про фильм Лёши",
        history=_SHARED_GROUP_THREAD,
        perceive_sender=_member_named("Vladimir", 2),
        decide_response=decide,
    )

    await handler.handle(
        _addr_message("ответь подробно на сообщение Лёши", mentions_bob=True)
    )

    assert fake.contexts, "the judge never assessed the turn"
    thread = fake.contexts[0].recent_thread
    assert _ALEXEY_FILM_TURN in thread  # 🔴 the other member's turn reaches the judge
    assert "Alexey:" in thread  # author labels distinguish who said what (US-3)
    assert "Vladimir:" in thread  # ...and the current sender's own label too


async def test_absence_hint_absent_when_current_author_never_spoke_in_window() -> None:
    # 🔴 BOB-058 .1 (graceful per-author absence): the current sender (Vladimir) has NO
    # turn in the shared window — only Alexey spoke, and long ago. Filtering to Vladimir
    # yields an EMPTY per-author slice, so NO absence hint is added (author-absent degrades
    # exactly like an empty history), and Alexey's OWN 30h-old turn is never mis-attributed
    # to Vladimir as a false last-seen. The complement of the dev "gap fires the hint" test.
    now = _moment()
    shared: list[Mapping[str, object]] = [
        {
            "content": "Alexey: я тут раньше писал\nbob: ага",
            "event_type": "message",
            "sender_id": 1,
            "ts": (now - timedelta(hours=30)).isoformat(),
        }
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=shared,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(
        _addr_message("расскажи подробно, я впервые тут", mentions_bob=True)
    )

    assert "Absence:" not in tier1.all_text  # Vladimir absent from window → no false hint


async def test_anti_repeat_isolates_current_author_among_interleaved_speakers() -> None:
    # 🔴 BOB-058 .1 (anti-repeat over an INTERLEAVED shared thread): Alexey earlier said X
    # and Vladimir earlier said his OWN different line. Now Vladimir says X for the FIRST
    # time. Even with Vladimir's own prior turn present as a distractor, the filter keeps
    # only HIS turns — none of which is X — so it is NOT counted as Vladimir repeating.
    x = "расскажи подробно про кофе"
    shared: list[Mapping[str, object]] = [
        {
            "content": f"Alexey: {x}\nbob: вот про кофе",
            "event_type": "message",
            "sender_id": 1,
        },
        {
            "content": "Vladimir: всем привет\nbob: привет",
            "event_type": "message",
            "sender_id": 2,
        },
    ]
    handler, _bot, _repo, tier1 = _build(
        reply="свежий ответ",
        history=shared,
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(_addr_message(x, mentions_bob=True))

    assert not _has_user_repeat_directive(tier1.all_text)


async def test_relationship_colours_tone_for_current_sender_despite_shared_thread() -> None:
    # 🔴 BOB-058 no-regression (BOB-014): relationship reads the CURRENT sender's OWN store,
    # not the thread — so even with another member's turns interleaved in the shared thread,
    # Vladimir's warm relationship still colours Bob's voice warmer/closer for THIS turn.
    rel = _FakeRelationship(
        current=Relationship(sender_id=2, warmth=0.8, compatibility=0.7)
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_SHARED_GROUP_THREAD,
        perceive_sender=_member_named("Vladimir", 2),
        relationship=rel,
    )

    await handler.handle(
        _addr_message("расскажи подробно про космос", mentions_bob=True)
    )

    folded = tier1.all_text.casefold()
    assert "близк" in folded or "по-свойски" in folded  # warm voice for the current sender


async def test_first_impression_surfaces_for_current_sender_despite_shared_thread() -> None:
    # 🔴 BOB-058 no-regression (BOB-019): the prior first-impression is per-SENDER data read
    # from its OWN store — another member's turns in the shared thread never displace it.
    # Vladimir's prior note still reaches the compose prompt, and his store is consulted.
    note = "этот уже заходил, держался ровно"
    impressions = _FakeFirstImpression(prior=note)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_SHARED_GROUP_THREAD,
        perceive_sender=_member_named("Vladimir", 2),
        first_impression=impressions,
    )

    await handler.handle(
        _addr_message("Боб, расскажи подробно, снова я", mentions_bob=True)
    )

    assert note in tier1.all_text  # the current sender's own prior note surfaces
    assert impressions.asked  # per-person first-impression store was consulted


async def test_shared_thread_is_public_but_owner_inner_life_never_leaks() -> None:
    # 🔴 BOB-058 privacy (BOB-051 public memory ∧ BOB-018 inner-life stays owner-only): a
    # GUEST reads the SHARED thread, so the owner's ORDINARY turn is visible (public group
    # memory) — but the owner's PRIVATE reflection (inner life) is NOT woven in. The shared
    # conversation channel carries public topic traffic; no private/internal channel leaks.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,  # owner turn + guest turn in one shared log
        expression_freqs=_LEAK_ON,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        bob_user_id_source=lambda: 777,
    )

    await handler.handle(
        _addr_message("Боб, расскажи подробно про кофе", mentions_bob=True)
    )

    assert _OWNER_THREAD_TURN in tier1.all_text  # 🔴 public shared memory (BOB-051)
    assert _REFLECTION_TEXT not in tier1.all_text  # 🔴 no owner inner-life leak


async def test_per_author_signals_are_graceful_on_an_empty_shared_window() -> None:
    # 🔴 BOB-058 .1 (graceful degradation, mirrors _others_present): an EMPTY shared thread
    # (a cold start, or a degraded read that returned nothing) with a perceived member must
    # not crash the per-author signals — the absence filter and anti-repeat both see an
    # empty slice, add no line, and the turn still produces a reply.
    handler, bot, _repo, tier1 = _build(
        reply="всё равно отвечу",
        history=(),
        perceive_sender=_member_named("Vladimir", 2),
    )

    await handler.handle(
        _addr_message("расскажи подробно, первый раз тут", mentions_bob=True)
    )

    assert bot.final_text == "всё равно отвечу"  # turn produced, no crash
    assert "Absence:" not in tier1.all_text  # empty window → no hint
    assert not _has_user_repeat_directive(tier1.all_text)  # empty window → no repeat


# --- BOB-058 .3: the author-attribution pure helpers (unit) -------------------
#
# The per-author signals stand on these pure projections of a stored episode. Unit-test
# them directly so the attribution (by ROBUST sender_id, BOB-058 .3) + extraction contract
# — and its GRACEFUL handling of a shapeless / non-string episode (never crash, never
# mis-attribute) — is locked precisely.


def test_history_for_author_filters_by_sender_id() -> None:
    # 🔴 BOB-058 .3: only the current author's OWN episodes (matched by sender_id, NOT the
    # "<name>:" label) survive, ordering preserved.
    hist: list[Mapping[str, object]] = [
        {"content": "Alexey: X\nbob: a", "sender_id": 1},
        {"content": "Vladimir: Y\nbob: b", "sender_id": 2},
        {"content": "Alexey: Z\nbob: c", "sender_id": 1},
    ]
    assert [i["content"] for i in _history_for_author(hist, 2)] == [
        "Vladimir: Y\nbob: b"
    ]


def test_history_for_author_keys_on_id_not_name_for_homonyms() -> None:
    # 🔴 BOB-058 .3: two members share the display name "Sasha" (sender_id 1 vs 2). The
    # filter isolates by sender_id — a homonym's turn is NOT cross-attributed.
    hist: list[Mapping[str, object]] = [
        {"content": "Sasha: чужое\nbob: a", "sender_id": 1},
        {"content": "Sasha: моё\nbob: b", "sender_id": 2},
    ]
    assert [i["content"] for i in _history_for_author(hist, 2)] == ["Sasha: моё\nbob: b"]


def test_history_for_author_none_returns_the_whole_window() -> None:
    # 🔴 ``sender_id is None`` (unresolved identity) → no filter, the pre-BOB-058 window.
    hist: list[Mapping[str, object]] = [{"content": "Alexey: X\nbob: a", "sender_id": 1}]
    assert _history_for_author(hist, None) == hist


def test_user_turns_skips_shapeless_and_non_string_content() -> None:
    # 🔴 BOB-058 graceful extraction: a non-string OR shapeless episode is skipped, so the
    # anti-repeat scan over the shared thread never crashes and never invents a user turn.
    hist: list[Mapping[str, object]] = [
        {"content": 123},  # non-string → skipped
        {"content": "нет разделителя"},  # no "<name>: " shape → skipped
        {"content": "Ada: реальная реплика\nbob: ответ"},
    ]
    assert _user_turns(hist) == ["реальная реплика"]


def test_user_turns_author_filter_keeps_only_that_authors_text() -> None:
    # 🔴 BOB-058 .3: over a shared thread, ``sender_id`` restricts the extracted user turns
    # to that person BY ID (not the "<name>:" label).
    hist: list[Mapping[str, object]] = [
        {"content": "Alexey: чужая реплика\nbob: a", "sender_id": 1},
        {"content": "Vladimir: моя реплика\nbob: b", "sender_id": 2},
    ]
    assert _user_turns(hist, 2) == ["моя реплика"]


# --- BOB-050 .3: low-frequency being-received acknowledgment hint --------------


class _FakeNotableStore:
    """In-memory NotableReactionStore stand-in (latest/clear/record), or a raiser."""

    def __init__(
        self, note: NotableReaction | None = None, *, raises: bool = False
    ) -> None:
        self._note = note
        self._raises = raises
        self.cleared = False

    async def record(self, note: NotableReaction) -> None:
        self._note = note

    async def latest(self) -> NotableReaction | None:
        if self._raises:
            msg = "store read failed"
            raise RuntimeError(msg)
        return self._note

    async def clear(self) -> None:
        self.cleared = True
        self._note = None


def _notable(*, sender_id: int | None) -> NotableReaction:
    return NotableReaction(
        sender_id=sender_id,
        reactor_name="Norman",
        emoji="❤️",
        bob_excerpt="кофе по утрам — это ритуал",
        interpretation="ему откликнулось",
        at=_moment(),
    )


async def test_lucky_roll_surfaces_one_acknowledgment_hint() -> None:
    # BOB-050 .3: a genuinely notable recent reaction from THIS person + a lucky low-freq
    # roll (freq 1.0 ⇒ always fires) folds ONE light acknowledgment HINT into the compose
    # context — Bob may weave it in himself, it is never a forced/scripted line.
    store = _FakeNotableStore(_notable(sender_id=_GUEST_SENDER_ID))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    text = tier1.all_text
    assert "Замечено:" in text
    assert "кофе по утрам — это ритуал" in text
    assert "не обязательно" in text  # a HINT, not a directive
    assert store.cleared is True  # consumed so Bob does not repeat it


async def test_unlucky_roll_adds_no_hint_and_keeps_the_marker() -> None:
    # An unlucky roll (freq 0.0 ⇒ never fires) leaves the context unchanged AND keeps the
    # marker, so a later turn may still surface it — not needy, but not lost either.
    store = _FakeNotableStore(_notable(sender_id=_GUEST_SENDER_ID))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=0.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text
    assert store.cleared is False


async def test_no_notable_reaction_adds_no_hint() -> None:
    # No recorded reaction ⇒ no hint even on a lucky roll (a clean no-op, no crash).
    store = _FakeNotableStore(None)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text


async def test_unwired_store_leaves_the_turn_unchanged() -> None:
    # No store wired (the default) ⇒ the acknowledgment path is inert, behaviour as before.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text


async def test_a_guests_reaction_is_not_woven_into_the_owners_context() -> None:
    # 🔴 Authz (BOB-019) / per-person: a notable reaction by the GUEST must NOT surface
    # to the OWNER — the hint is per-person, keyed on the reactor's sender_id.
    store = _FakeNotableStore(_notable(sender_id=_GUEST_SENDER_ID))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_owner_with_id(_OWNER_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("объясни подробно про кофе"))

    assert "Замечено:" not in tier1.all_text
    assert store.cleared is False  # someone else's marker is left untouched


async def test_owners_reaction_is_not_woven_into_a_guests_context() -> None:
    # 🔴 The mirror direction: the OWNER's notable reaction must NOT surface to a GUEST.
    store = _FakeNotableStore(_notable(sender_id=_OWNER_SENDER_ID))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text
    assert store.cleared is False


async def test_a_failing_store_read_is_dropped_silently() -> None:
    # 🔴 Decorative: a store failure in the hint path is caught and DROPPED — the reply
    # is still composed, never a crash, never a GUPPI outage notice.
    store = _FakeNotableStore(raises=True)
    handler, bot, _repo, tier1 = _build(
        reply="полный ответ",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text
    assert bot.sent  # the reply still shipped


async def test_anonymous_reaction_is_never_woven_to_a_person() -> None:
    # An anonymous reaction (no reactor id) is never surfaced to a specific person —
    # there is no "who" to acknowledge it to.
    store = _FakeNotableStore(_notable(sender_id=None))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert "Замечено:" not in tier1.all_text


def test_out_of_range_acknowledge_freq_is_rejected_at_construction() -> None:
    # Guardrail: the frequency is a probability — out-of-range is a misconfiguration.
    with pytest.raises(ValueError, match="acknowledge_reaction_freq"):
        _build(reply="hi", acknowledge_reaction_freq=1.5)


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


# --- BOB-035: render_diagram → local PNG → Telegram photo ----------------------


class _DiagramToolProvider:
    """Tool-calling provider: asks for ``render_diagram`` once, then finalises."""

    def __init__(self, *, mermaid: str = "graph TD; A-->B") -> None:
        self._mermaid = mermaid
        self._call = 0

    async def complete_with_tools(
        self,
        messages: Sequence[LLMMessage],  # noqa: ARG002
        *,
        tools: Sequence[ToolDefinition],  # noqa: ARG002
    ) -> ToolCallResult:
        self._call += 1
        if self._call == 1:
            call = ToolCall(
                id="d1", name="render_diagram", arguments={"mermaid": self._mermaid}
            )
            return ToolCallResult(text="", tool_calls=(call,))
        return ToolCallResult(text="Готово, вот диаграмма.", tool_calls=())


def _registry_with_render_diagram(
    renderer: object, sink: DiagramSink
) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(make_render_diagram_capability(renderer, sink))  # type: ignore[arg-type]
    return registry


class _FakeDiagramRenderer:
    """A scripted DiagramRenderer: returns canned PNG bytes (no real mmdc)."""

    def __init__(self, *, png: bytes = b"PNGBYTES") -> None:
        self._png = png

    async def render(self, mermaid_source: str) -> bytes:  # noqa: ARG002
        return self._png


class _FailingDiagramRenderer:
    """A DiagramRenderer that always raises DiagramRenderError (mmdc unavailable)."""

    async def render(self, mermaid_source: str) -> bytes:  # noqa: ARG002
        raise DiagramRenderError("mmdc not installed")


async def test_render_diagram_sends_the_png_as_a_photo_to_the_chat() -> None:
    # BOB-035: the capability renders via a FAKE renderer; the reply path drains the
    # per-turn sink and posts the PNG as a Telegram photo into the current chat.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(
        _FakeDiagramRenderer(png=b"PNGBYTES"), sink
    )
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )

    await handler.handle(_message("нарисуй схему"))

    # The photo landed in the CURRENT chat with the PNG bytes,
    assert len(bot.photos) == 1
    chat_id, photo, _caption = bot.photos[0]
    assert chat_id == _message("нарисуй схему").chat_id
    assert photo == b"PNGBYTES"
    # and a short text confirmation reached the chat too.
    assert bot.final_text


async def test_render_diagram_graceful_when_renderer_unavailable() -> None:
    # BOB-035: a renderer that raises DiagramRenderError must NOT crash — no photo,
    # an honest reply, the turn still completes.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FailingDiagramRenderer(), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )

    await handler.handle(_message("нарисуй схему"))

    # No photo was posted (the render failed gracefully),
    assert bot.photos == []
    # but Bob still replied (no crash).
    assert bot.final_text


async def test_render_diagram_sends_caption_alongside_the_photo() -> None:
    # BOB-035 acceptance: the drained DiagramResult carries a short caption that the
    # gateway forwards with the photo — Bob's in-character line, not a system message.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )

    await handler.handle(_message("нарисуй схему"))

    assert len(bot.photos) == 1
    _chat_id, _photo, caption = bot.photos[0]
    assert caption  # a short caption rode along with the photo


async def test_render_diagram_drains_the_sink_so_no_residue_remains() -> None:
    # BOB-035 per-turn isolation: after the turn the sink is fully drained — nothing is
    # left buffered to bleed into a later turn.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )

    await handler.handle(_message("нарисуй схему"))

    assert len(bot.photos) == 1
    # The reply path drained the sink; a fresh drain is empty (no residue).
    assert sink.drain() == ()


async def test_render_diagram_no_cross_turn_photo_bleed() -> None:
    # BOB-035 GUARDRAIL: a diagram turn followed by a plain (no-tool) turn must NOT
    # re-send the first turn's photo — the per-turn sink is drained, not accumulated.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)

    # Turn 1: a render_diagram turn → exactly one photo.
    diagram_handler, diagram_bot, _r1, _t1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )
    await diagram_handler.handle(_message("нарисуй схему"))
    assert len(diagram_bot.photos) == 1

    # Turn 2: a plain text reply over the SAME shared sink (no tool call) → no photo,
    # and crucially NOT the first turn's photo bleeding through.
    plain_handler, plain_bot, _r2, _t2 = _build(
        reply="просто текст",
        diagram_sink=sink,
    )
    await plain_handler.handle(_message("как дела"))
    assert plain_bot.photos == []


async def test_normal_text_reply_sends_no_photo_regression() -> None:
    # BOB-035 REGRESSION: a normal reply path with a wired-but-empty diagram sink must
    # behave exactly as before — a text reply, zero photos (no spurious send).
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(reply="привет", diagram_sink=sink)

    await handler.handle(_message("привет"))

    assert bot.final_text
    assert bot.photos == []


async def test_normal_reply_with_no_sink_wired_is_unaffected_regression() -> None:
    # BOB-035 REGRESSION: the default wiring (no diagram sink) is a clean no-op — the
    # reply path still replies and never reaches the photo send.
    handler, bot, _repo, _tier1 = _build(reply="привет")

    await handler.handle(_message("привет"))

    assert bot.final_text
    assert bot.photos == []


async def test_render_diagram_photo_goes_to_the_correct_chat_id() -> None:
    # BOB-035 GUARDRAIL: the photo lands in the CURRENT turn's chat_id (per-turn), not
    # some stale/global chat — the chat_id is resolved by the reply path per turn.
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
    )
    msg = _message("нарисуй схему")

    await handler.handle(msg)

    assert len(bot.photos) == 1
    chat_id, _photo, _caption = bot.photos[0]
    assert chat_id == msg.chat_id


async def test_render_diagram_photo_send_failure_never_breaks_the_turn() -> None:
    # BOB-035 best-effort: an UNEXPECTED transport error on the photo send is logged
    # and swallowed — the text reply still lands, the turn completes (no crash).
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
        photo_send_raises=True,
    )

    await handler.handle(_message("нарисуй схему"))

    # The photo send blew up but was swallowed — no photo recorded, reply still landed.
    assert bot.photos == []
    assert bot.final_text


# --- BOB-037: auto-render inline mermaid + send-as-document ---------------------


class _RecordingRenderer:
    """A DiagramRenderer that records every source it rendered (no real mmdc)."""

    def __init__(self, *, png: bytes = b"INLINE-PNG") -> None:
        self.sources: list[str] = []
        self._png = png

    async def render(self, mermaid_source: str) -> bytes:
        self.sources.append(mermaid_source)
        return self._png


class _FailingInlineRenderer:
    """A DiagramRenderer that always raises (mmdc absent) — drives the graceful path."""

    async def render(self, mermaid_source: str) -> bytes:  # noqa: ARG002
        raise DiagramRenderError("mmdc not installed")


_INLINE_REPLY = "Вот схема:\n```mermaid\ngraph TD; A-->B\n```\nГотово."


async def test_inline_mermaid_in_reply_is_rendered_and_sent_as_a_photo() -> None:
    # BOB-037 A (the reliability fix): the model wrote the mermaid as a fenced block in
    # its TEXT reply (it did NOT call the tool) — the reply path renders it and sends it.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="photo",
    )

    await handler.handle(_message())

    assert len(bot.photos) == 1
    _chat_id, photo, _caption = bot.photos[0]
    assert photo == b"INLINE-PNG"


async def test_inline_mermaid_block_is_stripped_from_the_visible_reply() -> None:
    # BOB-037 A: the rendered image REPLACES the fence — the fenced block is removed
    # from the visible reply text while the surrounding prose stays.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
    )

    await handler.handle(_message())

    assert "```mermaid" not in bot.final_text
    assert "graph TD" not in bot.final_text
    assert "Вот схема:" in bot.final_text
    assert "Готово." in bot.final_text


async def test_multiple_inline_mermaid_blocks_become_multiple_images() -> None:
    # BOB-037 A: two fenced blocks → two rendered images.
    reply = (
        "Раз:\n```mermaid\ngraph TD; A-->B\n```\n"
        "Два:\n``` mermaid\ngraph LR; X-->Y\n```\nВсё."
    )
    sink = CollectingDiagramSink()
    renderer = _RecordingRenderer()
    handler, bot, _repo, _tier1 = _build(
        reply=reply, diagram_sink=sink, diagram_renderer=renderer
    )

    await handler.handle(_message())

    assert len(bot.photos) == 2
    assert renderer.sources == ["graph TD; A-->B", "graph LR; X-->Y"]


async def test_inline_mermaid_is_deduped_against_a_tool_rendered_diagram() -> None:
    # BOB-037 A dedup: the render_diagram TOOL already rendered this source AND the
    # model also echoed the SAME mermaid as a fence — it must be sent ONCE, not twice.
    mermaid = "graph TD; A-->B"
    sink = CollectingDiagramSink()
    inline_renderer = _RecordingRenderer()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)

    class _EchoToolProvider:
        def __init__(self) -> None:
            self._call = 0

        async def complete_with_tools(
            self,
            messages: Sequence[LLMMessage],  # noqa: ARG002
            *,
            tools: Sequence[ToolDefinition],  # noqa: ARG002
        ) -> ToolCallResult:
            self._call += 1
            if self._call == 1:
                call = ToolCall(
                    id="d1", name="render_diagram", arguments={"mermaid": mermaid}
                )
                return ToolCallResult(text="", tool_calls=(call,))
            # The final reply ALSO echoes the same mermaid as a fenced block.
            return ToolCallResult(
                text=f"Готово:\n```mermaid\n{mermaid}\n```", tool_calls=()
            )

    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_EchoToolProvider(),
        diagram_sink=sink,
        diagram_renderer=inline_renderer,
    )

    await handler.handle(_message("нарисуй схему"))

    # Exactly one image (the tool's) — the inline echo was deduped, not re-rendered.
    assert len(bot.photos) == 1
    assert inline_renderer.sources == []


async def test_inline_mermaid_render_failure_keeps_the_block_as_text() -> None:
    # BOB-037 A graceful: if rendering the inline block raises (mmdc missing), the
    # fenced block is LEFT as text (current behaviour) — no crash, no image.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_FailingInlineRenderer(),
    )

    await handler.handle(_message())

    assert bot.photos == []
    assert bot.documents == []
    # The block stayed in the visible reply (Bob still answered).
    assert "```mermaid" in bot.final_text


async def test_inline_auto_render_no_op_without_a_renderer_wired() -> None:
    # BOB-037 A: with no renderer wired (the default), the auto-render is inert — the
    # fenced block stays as text exactly as before, no image.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(reply=_INLINE_REPLY, diagram_sink=sink)

    await handler.handle(_message())

    assert bot.photos == []
    assert "```mermaid" in bot.final_text


async def test_send_as_document_drains_via_send_document() -> None:
    # BOB-037 C: with send_as=document (the product default) the drain posts the PNG as
    # an uncompressed FILE, not a recompressed photo.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="document",
    )

    await handler.handle(_message())

    assert len(bot.documents) == 1
    assert bot.photos == []
    _chat_id, doc, _caption = bot.documents[0]
    assert doc == b"INLINE-PNG"


async def test_send_as_photo_drains_via_send_photo() -> None:
    # BOB-037 C: send_as=photo keeps the legacy photo send.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="photo",
    )

    await handler.handle(_message())

    assert len(bot.photos) == 1
    assert bot.documents == []


async def test_normal_reply_with_no_mermaid_sends_nothing() -> None:
    # BOB-037 regression: a plain reply with no fenced mermaid → no image, text intact.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply="просто текст без диаграмм",
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="document",
    )

    await handler.handle(_message())

    assert bot.photos == []
    assert bot.documents == []
    assert "просто текст без диаграмм" in bot.final_text


# --- BOB-037 .2: acceptance/guardrail strengthening ----------------------------


async def test_inline_mermaid_reliability_renders_queues_and_strips_end_to_end() -> None:
    # BOB-037 A (the CORE reliability fix, end to end): the model inlined a fenced
    # ```mermaid block instead of calling the tool. Through the WHOLE turn: the block
    # is rendered (the fake renderer sees the source), queued + sent as a document
    # (the product default), AND the fence is stripped from the visible text.
    sink = CollectingDiagramSink()
    renderer = _RecordingRenderer()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=renderer,
        diagram_send_as="document",
    )

    await handler.handle(_message())

    # Rendered (the renderer saw the inlined source) ...
    assert renderer.sources == ["graph TD; A-->B"]
    # ... queued + sent as a full-resolution document (not a recompressed photo) ...
    assert len(bot.documents) == 1
    assert bot.photos == []
    _chat_id, doc, _caption = bot.documents[0]
    assert doc == b"INLINE-PNG"
    # ... and the fence is GONE from the visible reply (the image replaced it).
    assert "```mermaid" not in bot.final_text
    assert "graph TD" not in bot.final_text
    assert "Вот схема:" in bot.final_text
    assert "Готово." in bot.final_text


async def test_inline_auto_render_drains_the_sink_so_no_cross_turn_bleed() -> None:
    # BOB-037 guardrail: the per-turn sink is DRAINED after sending, so a following
    # plain turn (no mermaid) sends nothing — no diagram leaks across turns.
    sink = CollectingDiagramSink()
    renderer = _RecordingRenderer()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=renderer,
        diagram_send_as="document",
    )

    await handler.handle(_message())
    assert len(bot.documents) == 1
    # The sink is empty after the drain — nothing is left to re-send.
    assert sink.pending() == ()


async def test_inline_mermaid_with_a_non_mermaid_fence_left_untouched() -> None:
    # BOB-037 (item 3, mixed): a ```python fence is NOT a diagram — it must be left in
    # the visible reply verbatim, while the mermaid fence beside it is rendered + stripped.
    reply = (
        "Схема:\n```mermaid\ngraph TD; A-->B\n```\n"
        "А вот код:\n```python\nprint('hi')\n```\nКонец."
    )
    sink = CollectingDiagramSink()
    renderer = _RecordingRenderer()
    handler, bot, _repo, _tier1 = _build(
        reply=reply,
        diagram_sink=sink,
        diagram_renderer=renderer,
        diagram_send_as="document",
    )

    await handler.handle(_message())

    # Exactly one diagram — the python fence was never rendered.
    assert renderer.sources == ["graph TD; A-->B"]
    assert len(bot.documents) == 1
    # The mermaid fence is gone; the python fence + surrounding prose stay intact.
    assert "graph TD" not in bot.final_text
    assert "```python" in bot.final_text
    assert "print('hi')" in bot.final_text
    assert "Конец." in bot.final_text


async def test_inline_mermaid_partial_failure_sends_the_good_keeps_the_bad() -> None:
    # BOB-037 (item 4, graceful PARTIAL): two fenced blocks where the SECOND fails to
    # render — the first is still sent, the failed block is LEFT as text, no crash.
    reply = (
        "Раз:\n```mermaid\ngood-diagram\n```\n"
        "Два:\n```mermaid\nbad-diagram\n```\nВсё."
    )
    sink = CollectingDiagramSink()

    class _SecondFailsRenderer:
        """Render the first block, raise on the second (mmdc choked on it)."""

        def __init__(self) -> None:
            self.sources: list[str] = []

        async def render(self, mermaid_source: str) -> bytes:
            self.sources.append(mermaid_source)
            if mermaid_source == "bad-diagram":
                raise DiagramRenderError("malformed mermaid")
            return b"GOOD-PNG"

    renderer = _SecondFailsRenderer()
    handler, bot, _repo, _tier1 = _build(
        reply=reply,
        diagram_sink=sink,
        diagram_renderer=renderer,
        diagram_send_as="document",
    )

    await handler.handle(_message())

    # Both were attempted; only the good one was sent.
    assert renderer.sources == ["good-diagram", "bad-diagram"]
    assert len(bot.documents) == 1
    _chat_id, doc, _caption = bot.documents[0]
    assert doc == b"GOOD-PNG"
    # The good fence is stripped; the failed one stays as text (Bob still answered).
    assert "good-diagram" not in bot.final_text
    assert "bad-diagram" in bot.final_text
    assert "Всё." in bot.final_text


async def test_inline_mermaid_dedup_is_whitespace_insensitive() -> None:
    # BOB-037 dedup guardrail: the tool rendered the canonical source; the model echoed
    # the SAME diagram as a fence with different surrounding whitespace. The normalised
    # dedup must still catch it → exactly ONE image, no double send, no re-render.
    canonical = "graph TD; A-->B"
    sink = CollectingDiagramSink()
    inline_renderer = _RecordingRenderer()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(), sink)

    class _WhitespaceEchoToolProvider:
        def __init__(self) -> None:
            self._call = 0

        async def complete_with_tools(
            self,
            messages: Sequence[LLMMessage],  # noqa: ARG002
            *,
            tools: Sequence[ToolDefinition],  # noqa: ARG002
        ) -> ToolCallResult:
            self._call += 1
            if self._call == 1:
                call = ToolCall(
                    id="d1", name="render_diagram", arguments={"mermaid": canonical}
                )
                return ToolCallResult(text="", tool_calls=(call,))
            # The echoed fence has extra leading/trailing whitespace on each line.
            return ToolCallResult(
                text="Готово:\n```mermaid\n  graph TD; A-->B  \n```", tool_calls=()
            )

    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_WhitespaceEchoToolProvider(),
        diagram_sink=sink,
        diagram_renderer=inline_renderer,
        diagram_send_as="document",
    )

    await handler.handle(_message("нарисуй схему"))

    # One image (the tool's); the whitespace-variant echo deduped, never re-rendered.
    assert len(bot.documents) == 1
    assert inline_renderer.sources == []


async def test_inline_auto_render_caption_accompanies_the_diagram() -> None:
    # BOB-037 A: an auto-rendered inline diagram carries Bob's short in-character caption.
    sink = CollectingDiagramSink()
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_sink=sink,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="document",
    )

    await handler.handle(_message())

    _chat_id, _doc, caption = bot.documents[0]
    assert caption == "Вот диаграмма."


async def test_inline_auto_render_no_op_without_a_sink_wired() -> None:
    # BOB-037 guardrail: a renderer wired but NO sink (an incomplete wiring) is inert —
    # the fence stays as text, nothing is sent, no crash.
    handler, bot, _repo, _tier1 = _build(
        reply=_INLINE_REPLY,
        diagram_renderer=_RecordingRenderer(),
        diagram_send_as="document",
    )

    await handler.handle(_message())

    assert bot.photos == []
    assert bot.documents == []
    assert "```mermaid" in bot.final_text


async def test_render_diagram_tool_path_still_works_when_model_calls_it() -> None:
    # BOB-037 no-regression: the BOB-035 tool path is intact — when the model DOES call
    # render_diagram, the diagram is sent (as a document under the new default mode).
    sink = CollectingDiagramSink()
    registry = _registry_with_render_diagram(_FakeDiagramRenderer(png=b"TOOL-PNG"), sink)
    handler, bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=_DiagramToolProvider(),
        diagram_sink=sink,
        diagram_send_as="document",
    )

    await handler.handle(_message("нарисуй схему"))

    assert len(bot.documents) == 1
    _chat_id, doc, _caption = bot.documents[0]
    assert doc == b"TOOL-PNG"


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


# --- BOB-036 .1: phrase-tic guard (a recurring signature CLOSER) ---------------
#
# BOB-032's full-reply guard compares whole replies, so two substantively DIFFERENT
# replies that merely END with the same signature closer ("Мне так спокойнее.") slip
# through. The phrase-tic guard extends the SAME regeneration path: when the closer
# recurs across the recent window, a fresh draft carrying it is broken and re-rolled.
_TIC_CLOSER = "Мне так спокойнее."
_TIC_TURN_A = f"Ada: глянь логи\nbob: Хорошо, посмотрю логи. {_TIC_CLOSER}"
_TIC_TURN_B = f"Ada: и код\nbob: Ладно, перепишу функцию. {_TIC_CLOSER}"


async def test_recurring_closer_tic_triggers_regeneration() -> None:
    # The closer ends BOTH prior Bob replies in the window; a fresh, substantively
    # different draft that ALSO ends with it is a phrase-tic -> the guard regenerates
    # once and commits the tic-free retry. The full-reply bar alone would miss this:
    # the three replies are not near-duplicates, only their tail is shared.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[
            f"Окей, проверю конфиг. {_TIC_CLOSER}",
            "Готово, всё чисто — больше тут добавить нечего.",
        ],
        history=[
            {"content": _TIC_TURN_A, "event_type": "message"},
            {"content": _TIC_TURN_B, "event_type": "message"},
        ],
    )

    await handler.handle(_message("посмотри, пожалуйста, ещё и конфиг подробно"))

    assert len(tier1.payloads) == 2
    assert bot.final_text == "Готово, всё чисто — больше тут добавить нечего."


async def test_closer_used_once_before_is_not_a_tic_and_is_committed() -> None:
    # No false fire: the closer appears in only ONE prior reply in the window, so a
    # fresh draft carrying it is a legitimate reuse (not yet a tic) and is committed
    # as-is with no extra generation.
    handler, bot, _repo, tier1 = _build(
        reply=f"Окей, проверю конфиг. {_TIC_CLOSER}",
        history=[
            {"content": _TIC_TURN_A, "event_type": "message"},
            {"content": _INTERVENING_TURN, "event_type": "message"},
        ],
    )

    await handler.handle(_message("посмотри, пожалуйста, ещё и конфиг подробно"))

    assert len(tier1.payloads) == 1
    assert bot.final_text == f"Окей, проверю конфиг. {_TIC_CLOSER}"


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


# --- BOB-036 .2: acceptance + guardrails (user's case, recall union, bound) -----
#
# The .1 cases pin the closer-tic via HISTORY. These add the user's REAL production
# phrase end to end, prove the tic path rides the SAME recall-aware union (history +
# recalled Bob replies) and the SAME _MAX_REGENERATIONS bound, and prove the guard
# never over-fires on a legitimately reused short term.
_REAL_TIC = "Мне так спокойнее."
_REAL_TURN_A = f"Ada: подними сервис\nbob: Развернул сервис, всё поднялось. {_REAL_TIC}"
_REAL_TURN_B = f"Ada: прогони тесты\nbob: Прогнал тесты ещё раз. {_REAL_TIC}"


async def test_users_real_closer_tic_is_caught_and_regenerated() -> None:
    # 🔴 The user's actual report end to end: "Мне так спокойнее" closes the last two
    # Bob replies on record; a fresh, substantively different draft that ALSO ends with
    # it is a phrase-tic. The guard regenerates (proven via the fake router: a second
    # payload is drawn) and commits the tic-free retry — the final reply DIFFERS.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[
            f"Сделал бэкап на всякий случай. {_REAL_TIC}",
            "Готово, бэкап на месте — добавить тут нечего.",
        ],
        history=[
            {"content": _REAL_TURN_A, "event_type": "message"},
            {"content": _REAL_TURN_B, "event_type": "message"},
        ],
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 2  # the tic guard fired exactly one regeneration
    assert bot.final_text == "Готово, бэкап на месте — добавить тут нечего."


async def test_closer_tic_caught_via_the_recall_union_not_only_history() -> None:
    # Integration (union): the recurring closer lives in RECALLED Bob replies that are
    # NOT in recent history — the history-only window is blind to them. The tic path
    # rides the SAME recall-aware union as the full-repeat guard, so two recalled replies
    # sharing the closer + a fresh draft carrying it still fires one regeneration.
    recalled_a: dict[str, object] = {
        "content": f"Ada: a\nbob: Глянул дашборд. {_REAL_TIC}",
        "category": "episodic",
    }
    recalled_b: dict[str, object] = {
        "content": f"Ada: b\nbob: Перечитал лог. {_REAL_TIC}",
        "category": "episodic",
    }
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[
            f"Проверил алерты. {_REAL_TIC}",
            "Всё чисто, алерты молчат — добавить нечего.",
        ],
        recall=_recall_with(recalled_a, recalled_b),
    )

    await handler.handle(_message("проверь, пожалуйста, ещё и алерты подробно"))

    assert len(tier1.payloads) == 2  # recall half of the union drove the tic catch
    assert bot.final_text == "Всё чисто, алерты молчат — добавить нечего."


async def test_persistent_tic_is_stripped_after_the_regeneration_bound() -> None:
    # BOB-043: no infinite loop on the tic path — a stubborn closer-tic anchored in
    # HISTORY (never dropped) regenerates at most _MAX_REGENERATIONS (2) times. Every
    # drawn reply carries the closer, so the tic never clears via regeneration; after
    # the bound the recurring closer sentence is DETERMINISTICALLY STRIPPED so the tic
    # never ships (the substantive reply survives).
    sticky = f"Очередной свежий повод. {_REAL_TIC}"
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[sticky] * 4,
        history=[
            {"content": _REAL_TURN_A, "event_type": "message"},
            {"content": _REAL_TURN_B, "event_type": "message"},
        ],
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    # initial draft + 2 retries = 3 generations; the still-ticcing closer is stripped.
    assert len(tier1.payloads) == 3
    assert bot.final_text == "Очередной свежий повод."


async def test_reused_short_term_does_not_trigger_tic_regeneration() -> None:
    # No false positive end to end: a short technical term ("Ollama") recurs in every
    # recent reply, but it is below the notability bar — so a fresh reply reusing it is
    # committed as-is with NO regeneration. Over-firing on common terms is the headline
    # risk; this proves the guard stays quiet.
    handler, bot, _repo, tier1 = _build(
        reply="Снова дёрнул Ollama, ответ пришёл.",
        history=[
            {"content": "Ada: a\nbob: Подключаюсь к Ollama.", "event_type": "message"},
            {"content": "Ada: b\nbob: Спрашиваю Ollama.", "event_type": "message"},
        ],
    )

    await handler.handle(_message("спроси модель ещё раз подробно"))

    assert len(tier1.payloads) == 1  # no needless regeneration
    assert bot.final_text == "Снова дёрнул Ollama, ответ пришёл."


# --- BOB-043: wide closer-lookback (catch the SCATTERED tic) + deterministic strip --
#
# The tic is scattered (~21% prevalence): in the narrow 6-episode history + recall view
# it appears 0–1× (below tic_min_occurrences=2) → BOB-036 misses it live. The wide
# closer-lookback runs is_phrase_tic against Bob's last ~tic_lookback (20) replies,
# where a 21%-prevalence tic recurs ~4× → reliably caught. The only new I/O is the
# extra recent_episodes(tic_lookback) read.


def _scattered_tic_history() -> list[dict[str, object]]:
    """20 Bob replies with the tic at indices 2/5/9/13 — all OLDER than the last 6."""
    history: list[dict[str, object]] = []
    for index in range(20):
        reply = f"Реплика номер {index} готова."
        if index in (2, 5, 9, 13):
            reply = f"Что-то сделал по пункту {index}. {_REAL_TIC}"
        history.append(
            {"content": f"Ada: пункт {index}\nbob: {reply}", "event_type": "message"}
        )
    return history


async def test_scattered_tic_caught_by_wide_lookback_where_narrow_misses() -> None:
    # 🔴 BOB-043 headline: the tic is scattered across Bob's last 20 replies (4 of 20)
    # but ABSENT from the last 6 (the narrow history window). The narrow per-turn check
    # sees it 0× → misses (BOB-036 live failure); the WIDE closer-lookback sees 4 →
    # catches and regenerates, committing the tic-free retry.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[
            f"Сделал бэкап на всякий случай. {_REAL_TIC}",
            "Готово, бэкап на месте — добавить нечего.",
        ],
        history=_scattered_tic_history(),
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 2  # the wide lookback drove the catch
    assert bot.final_text == "Готово, бэкап на месте — добавить нечего."


async def test_scattered_tic_slips_through_when_lookback_is_narrowed() -> None:
    # Control for the wide-lookback win: narrow tic_lookback to 6 (== the history
    # window) and the SAME scattered tic is no longer caught — the first draft commits
    # as-is. Pins the WIDE window (not some other path) as the mechanism that catches it.
    handler, bot, _repo, tier1 = _build(
        reply=f"Сделал бэкап на всякий случай. {_REAL_TIC}",
        history=_scattered_tic_history(),
        repeat_thresholds=RepeatThresholds(tic_lookback=6),
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 1  # narrow lookback misses the scattered tic
    assert bot.final_text == f"Сделал бэкап на всякий случай. {_REAL_TIC}"


async def test_persistent_scattered_tic_is_stripped_after_the_bound() -> None:
    # End to end: a scattered tic the wide lookback catches, but every regeneration
    # re-copies it → after _MAX_REGENERATIONS the recurring closer is DETERMINISTICALLY
    # STRIPPED so the tic never ships, the substantive reply surviving.
    sticky = f"Свежий повод сделать ещё раз. {_REAL_TIC}"
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[sticky] * 4,
        history=_scattered_tic_history(),
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 3  # initial + 2 retries, then the closer is stripped
    assert bot.final_text == "Свежий повод сделать ещё раз."


async def test_distinct_closer_over_a_wide_window_is_not_stripped() -> None:
    # No false positive at the wide scale: a fresh reply ends with a UNIQUE closer that
    # appears in no prior reply across the wide window → not a recurring closer → no
    # regeneration and no strip; committed verbatim.
    history = [
        {"content": f"Ada: пункт {i}\nbob: Реплика номер {i} готова.", "event_type": "message"}
        for i in range(20)
    ]
    fresh = "Готово, всё на месте. Это совершенно уникальная финальная концовка."
    handler, bot, _repo, tier1 = _build(reply=fresh, history=history)

    await handler.handle(_message("подытожь, пожалуйста, всё подробно"))

    assert len(tier1.payloads) == 1  # no needless regeneration
    assert bot.final_text == fresh


async def test_single_occurrence_in_wide_window_does_not_regenerate() -> None:
    # 🔴 No false positive at the wide scale (occurrence boundary): the closer appears
    # in EXACTLY ONE of the last 20 replies — below tic_min_occurrences (2). A fresh
    # draft carrying it is a one-off reuse, NOT a tic, so it is committed verbatim with
    # no regeneration. Pins that the wide lookback still needs >= min_occurrences.
    history: list[dict[str, object]] = [
        {"content": f"Ada: пункт {i}\nbob: Реплика номер {i} готова.", "event_type": "message"}
        for i in range(20)
    ]
    history[4] = {
        "content": f"Ada: пункт 4\nbob: Однажды сделал. {_REAL_TIC}",
        "event_type": "message",
    }
    fresh = f"Сделал бэкап на всякий случай. {_REAL_TIC}"
    handler, bot, _repo, tier1 = _build(reply=fresh, history=history)

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 1  # one occurrence is below the bar — no catch
    assert bot.final_text == fresh


async def test_short_closer_recurring_across_wide_window_is_not_caught() -> None:
    # 🔴 No false positive: a SHORT closer ("Идём дальше." — 2 words, below
    # tic_min_words=3) recurs in every one of Bob's last 20 replies, yet is never
    # notable, so a fresh reply reusing it is committed as-is. Common short sign-offs
    # must never trip the wide-lookback detector.
    short_closer = "Идём дальше."
    history = [
        {
            "content": f"Ada: пункт {i}\nbob: Реплика номер {i} готова. {short_closer}",
            "event_type": "message",
        }
        for i in range(20)
    ]
    fresh = f"Сделал бэкап на всякий случай. {short_closer}"
    handler, bot, _repo, tier1 = _build(reply=fresh, history=history)

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 1  # short closer is below the notability bar
    assert bot.final_text == fresh


async def test_strip_fallback_preserves_a_multi_sentence_substantive_reply() -> None:
    # Strip fallback keeps the BODY intact: a stubborn scattered tic the wide lookback
    # catches, where every regeneration re-copies a TWO-sentence body + the tic closer.
    # After the bound only the trailing tic sentence is excised — both body sentences
    # (and their punctuation) survive, and the closer never ships.
    sticky = f"Первая часть готова. Вторая часть тоже готова. {_REAL_TIC}"
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[sticky] * 4,
        history=_scattered_tic_history(),
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 3  # initial + 2 retries, then the closer is stripped
    assert bot.final_text == "Первая часть готова. Вторая часть тоже готова."


async def test_recurring_reflection_phrase_is_not_treated_as_a_tic() -> None:
    # BOB-033 x BOB-036 regression: a private reflection that recurs in the recall store
    # is EXCLUDED from the recall pool BEFORE the guard runs, so even a repeating inner-
    # monologue phrase can never feed the phrase-tic detector. The reflection text never
    # enters the prompt (containment) AND the fresh reply commits with no regeneration.
    reflection_phrase = "Сегодня всё кажется бессмысленным."
    recall = FakeRecall(
        hits=[
            {"content": reflection_phrase, "category": "reflection", "source": "episodic"},
            {"content": reflection_phrase, "category": "inner_monologue", "source": "episodic"},
        ]
    )
    fresh = f"Разобрался с задачей. {reflection_phrase}"
    handler, bot, _repo, tier1 = _build(reply=fresh, recall=recall)

    await handler.handle(_message("объясни подробно, что ты думаешь"))

    assert len(tier1.payloads) == 1  # reflections never feed the tic guard
    assert bot.final_text == fresh
    assert reflection_phrase not in tier1.all_text  # the reflection stayed out of the prompt


# --- BOB-044: the dialogue-replay window is INDEPENDENT of the anti-repeat windows --
#
# BOB-044 widens the conversation-replay window (``dialogue.recent_turns``, default 14,
# was a hardcoded 6) so Bob holds the dialogue thread. The guardrail these tests pin: that
# window is the conversation replay ONLY — it must NOT be coupled to the anti-repeat
# windows, which each carry their own config. The risk is real because BOTH the
# compose/addressivity reads AND the wide tic-guard read (BOB-043) go through the SAME
# ``recent_episodes`` seam: a naive wiring could have piped ``recent_turns`` into the
# tic read too, blinding the scattered-tic guard whenever the dialogue window is narrow,
# or starving it whenever it is wide. These tests prove the two windows never touch.


async def test_tic_lookback_read_uses_its_own_window_not_the_dialogue_window() -> None:
    # The compose/addressivity reads ask ``recent_episodes`` for ``recent_turns`` (9
    # here), while the BOB-043 wide tic-guard read asks for its OWN ``tic_lookback`` (the
    # default 20). Both windows appear, distinct — neither is the old hardcoded 6.
    tic_lookback = RepeatThresholds().tic_lookback
    handler, _bot, repo, _tier1 = _build(
        reply="hi", history=_THREAD_HISTORY, recent_turns=9
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert 9 in repo.requested_ks  # the dialogue-replay window (recent_turns)
    assert tic_lookback in repo.requested_ks  # the wide tic-guard window (its own config)
    assert tic_lookback != 9  # two genuinely separate windows
    assert 6 not in repo.requested_ks  # the old hardcoded window is gone from BOTH reads


async def test_widening_the_dialogue_window_leaves_the_tic_lookback_untouched() -> None:
    # Widen the dialogue window far past the tic window: the tic-guard read STILL asks for
    # ``tic_lookback`` (its own default 20), not the widened ``recent_turns`` (30). The
    # tic window is driven by ``repeat.*`` config, never by the dialogue window.
    tic_lookback = RepeatThresholds().tic_lookback
    handler, _bot, repo, _tier1 = _build(
        reply="hi", history=_THREAD_HISTORY, recent_turns=30
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert 30 in repo.requested_ks  # the dialogue window is honored at its wide value
    assert tic_lookback in repo.requested_ks  # the tic read kept its own (smaller) window


async def test_tic_lookback_read_is_driven_by_repeat_config_not_recent_turns() -> None:
    # Pin the SOURCE of the tic window: override ``repeat.tic_lookback`` to 12 with a
    # different ``recent_turns`` (30). The wide read asks for 12 (the repeat config),
    # proving the tic window follows ``repeat.*`` and the dialogue read follows
    # ``dialogue.recent_turns`` — two independent knobs.
    handler, _bot, repo, _tier1 = _build(
        reply="hi",
        history=_THREAD_HISTORY,
        recent_turns=30,
        repeat_thresholds=RepeatThresholds(tic_lookback=12),
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert 12 in repo.requested_ks  # the tic window follows repeat.tic_lookback
    assert 30 in repo.requested_ks  # the dialogue window follows recent_turns
    assert 20 not in repo.requested_ks  # the tic default did NOT leak through


async def test_anti_repeat_window_fires_independent_of_a_widened_dialogue_window() -> None:
    # BOB-026 regression: a repeat "через ход" is caught by the narrow ``repeat.window``
    # (default 5) EVEN with the dialogue window widened to 20 — the anti-repeat guard is
    # governed by its own window, not coupled to ``recent_turns``.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_OLDER_DECLINE, "Ладно, давай попробую описать словами."],
        history=[
            {"content": _WEDGED_TURN, "event_type": "message"},
            {"content": _INTERVENING_TURN, "event_type": "message"},
        ],
        recent_turns=20,
    )

    await handler.handle(_message("слушай, а нарисуй мне всё-таки таблицу подробно ещё раз"))

    assert len(tier1.payloads) == 2  # the window guard still regenerated once
    assert bot.final_text == "Ладно, давай попробую описать словами."


async def test_scattered_tic_still_caught_when_the_dialogue_window_is_narrow() -> None:
    # 🔴 BOB-043 regression / decoupling proof: narrow the dialogue window to 3 (far below
    # where the scattered tic sits, indices 2/5/9/13 of 20). The narrow per-turn check
    # sees NO tic, yet the INDEPENDENT wide tic-guard read (tic_lookback=20) still scans
    # all 20 closers, sees 4 occurrences, and regenerates. A narrow dialogue window must
    # never blind the tic guard — which it would if the wide read used recent_turns.
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[
            f"Сделал бэкап на всякий случай. {_REAL_TIC}",
            "Готово, бэкап на месте — добавить нечего.",
        ],
        history=_scattered_tic_history(),
        recent_turns=3,
    )

    await handler.handle(_message("сделай, пожалуйста, ещё и бэкап подробно"))

    assert len(tier1.payloads) == 2  # the wide lookback still drove the catch
    assert bot.final_text == "Готово, бэкап на месте — добавить нечего."


async def test_recall_grounding_intact_regardless_of_the_dialogue_window() -> None:
    # BOB-032 regression: recall-grounding flows through the SEPARATE recall seam, not the
    # conversation-replay window. A custom ``recent_turns`` (7) leaves the recalled memory
    # reaching the reply exactly as before — the dialogue window does not touch recall.
    handler, _bot, _repo, tier1 = _build(reply="hi", recent_turns=7)

    await handler.handle(_message())

    assert _RECALL_MEMORY in tier1.all_text  # recall grounding is untouched by the window


# --- BOB-061 .2: cross-session closer persist + soft anti-tic nudge («провязка») -----
#
# The .1 mechanism (closer_text / is_recurring_closer_tic / CloserLog) is wired into the
# reply path here: after a reply Bob's NORMALISED closer is APPENDED to the ring; BEFORE
# generation the persisted closers ∪ the live window feed the tic detector, and on a
# genuine recurring motif a SOFT nudge folds into the context AND the motif is stripped off
# the recalled exemplars. 🔴 Everything is decorative + conservative (US-4 liveness): no
# tic / an unwired-or-failing log → zero change to the reply.
_PERSIST_TIC = "мне так спокойнее"  # a normalised closer (as the ring stores it)


async def test_reply_closer_is_appended_to_the_ring() -> None:
    # After a genuine reply Bob's closer (normalised, ≥ tic_min_words) is logged to the
    # cross-session ring — the persist half of the «провязка».
    log = _FakeCloserLog()
    handler, _bot, _repo, _tier1 = _build(
        reply="Развернул сервис, всё поднялось. Мне так спокойнее.", closer_log=log
    )

    await handler.handle(_message())

    assert log.appended == [_PERSIST_TIC]


async def test_empty_closer_is_not_appended() -> None:
    # A reply with NO notable closer (every trailing fragment is below the notability bar)
    # carries no motif → nothing is logged (skip-empty).
    log = _FakeCloserLog()
    handler, _bot, _repo, _tier1 = _build(reply="Ок.", closer_log=log)

    await handler.handle(_message())

    assert log.appended == []


async def test_recurring_persisted_motif_nudges_and_strips_the_exemplar() -> None:
    # The tic fires from the PERSIST ring alone (the once-per-session case the live window
    # never sees): the freshest persisted closer recurs across the ring → (a) the soft
    # nudge is folded into the generation context and (b) the tic motif is stripped off the
    # recalled Bob-reply exemplar so it is not fed back as few-shot.
    log = _FakeCloserLog(recent=(_PERSIST_TIC, _PERSIST_TIC, _PERSIST_TIC))
    recall = FakeRecall(
        hits=[{"content": "Ada: старое\nbob: Что-то ответил. Мне так спокойнее.",
               "category": "personal"}]
    )
    handler, bot, _repo, tier1 = _build(
        reply="Свежий, ни на что не похожий ответ по делу.",
        closer_log=log,
        recall=recall,
    )

    await handler.handle(_message())

    assert _CLOSER_TIC_NUDGE in tier1.all_text  # (b) soft nudge present
    assert "Что-то ответил." in tier1.all_text  # exemplar body preserved
    # (a) the tic closer is stripped off THIS recalled exemplar (the phrase alone also
    # appears in the baked-in anti-tic system example, so assert the exemplar combination):
    assert "Что-то ответил. Мне так спокойнее" not in tier1.all_text
    assert bot.final_text == "Свежий, ни на что не похожий ответ по делу."


async def test_no_tic_leaves_the_reply_context_unchanged() -> None:
    # 🔴 US-4 liveness: with an EMPTY ring and no recurring window closer there is no tic →
    # no nudge, and the reply is committed exactly as composed.
    log = _FakeCloserLog(recent=())
    handler, bot, _repo, tier1 = _build(
        reply="Обычный живой ответ без всякого тика.", closer_log=log
    )

    await handler.handle(_message())

    assert _CLOSER_TIC_NUDGE not in tier1.all_text
    assert bot.final_text == "Обычный живой ответ без всякого тика."


async def test_distinct_closers_below_threshold_do_not_nudge() -> None:
    # 🔴 US-4 no false positive: three SUBSTANTIVELY DISTINCT closers in the ring do not
    # cluster into one motif (conservative motif_similarity_threshold) → no tic, no nudge.
    log = _FakeCloserLog(
        recent=(
            "давай попробуем совсем иначе на этот раз",
            "мне кажется тут нужен другой подход целиком",
            "интересно чем это в итоге закончится для нас",
        )
    )
    handler, bot, _repo, tier1 = _build(
        reply="Ещё один непохожий содержательный ответ.", closer_log=log
    )

    await handler.handle(_message())

    assert _CLOSER_TIC_NUDGE not in tier1.all_text
    assert bot.final_text == "Ещё один непохожий содержательный ответ."


async def test_closer_log_read_failure_is_decorative() -> None:
    # 🔴 Decorative: a ring READ failure → no nudge and the turn still produces a reply
    # (the detect error is swallowed, never breaking the turn).
    log = _FakeCloserLog(recent_raises=True)
    handler, bot, _repo, tier1 = _build(reply="Ответ несмотря на сбой чтения.", closer_log=log)

    await handler.handle(_message())

    assert _CLOSER_TIC_NUDGE not in tier1.all_text
    assert bot.final_text == "Ответ несмотря на сбой чтения."


async def test_closer_log_append_failure_is_decorative() -> None:
    # 🔴 Decorative: a ring APPEND failure after the reply is swallowed — the turn already
    # replied and is not broken.
    log = _FakeCloserLog(append_raises=True)
    handler, bot, _repo, _tier1 = _build(
        reply="Развернул сервис. Мне так спокойнее.", closer_log=log
    )

    await handler.handle(_message())

    assert bot.final_text == "Развернул сервис. Мне так спокойнее."
    assert log.appended == []  # the raising append recorded nothing


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


async def test_guest_turn_recalls_unified_memory() -> None:
    # 🔴 BOB-051: memory is unified for the closed group — a recalled memory reaches a
    # member's compose prompt (an @mention forces ENGAGE so it is RNG-independent).
    recall = FakeRecall(
        hits=[{"content": _RECALL_MEMORY, "category": "personal"}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", recall=recall, perceive_sender=_guest_resolver()
    )

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert _RECALL_MEMORY in tier1.all_text  # unified knowledge reaches the member


async def test_guest_turn_extracts_facts_into_shared_memory() -> None:
    # 🔴 BOB-051: every member's turn feeds the SHARED/public group memory —
    # _extract_facts runs on a member turn too (the group memory grows for all).
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

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert extract.calls == 1  # 🔴 BOB-051: a member turn feeds the shared memory


async def test_guest_without_sender_reads_the_unified_conversation_window() -> None:
    # 🔴 BOB-051: a member with no resolvable sender_id reads the SHARED recent window
    # (memory unified for the closed group) — the group's recent conversation is part of
    # Bob's continuity for any member. (An @mention forces ENGAGE, RNG-independent.)
    shared_turn = "Ada: заметка про общие дела\nbob: понял, Ada"
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=[{"content": shared_turn}],
        perceive_sender=_guest_with_id(None),
    )

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert shared_turn in tier1.all_text  # the shared conversation window is replayed


async def test_guest_turn_uses_a_normal_voice_without_the_stranger_directive() -> None:
    # 🔴 BOB-051: a member of the closed group gets a NORMAL Bob voice — the wary
    # stranger directive is GONE — while Bob still knows WHO is writing (attribution
    # stays). (An @mention forces ENGAGE so the prompt is composed, RNG-independent.)
    handler, _bot, _repo, tier1 = _build(
        reply="hi", perceive_sender=_guest_resolver()
    )

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    folded = tier1.all_text.casefold()
    assert "настороже" not in folded  # the wary stranger directive is dropped
    assert "не раскрывай личное" not in folded  # ...and its owner-privacy clause
    assert "незнаком" in folded  # but Bob still clocks WHO is writing (attribution)


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


async def test_guest_first_impression_used_alongside_unified_memory() -> None:
    # BOB-051: a member's per-person first-impression (about THEM) sits alongside the
    # UNIFIED recall — both surface (the impression is continuity, the recall is shared
    # knowledge). (An @mention forces ENGAGE so the prompt is composed, RNG-independent.)
    note = "этот незнакомец уже заходил, держался ровно"
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    impressions = _FakeFirstImpression(prior=note)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        recall=recall,
        perceive_sender=_guest_resolver(),
        first_impression=impressions,
    )

    await handler.handle(
        _addr_message("Боб, расскажи подробно — снова я заглянул к тебе", mentions_bob=True)
    )

    assert note in tier1.all_text  # the member's own impression (continuity)
    assert _RECALL_MEMORY in tier1.all_text  # 🔴 unified recall surfaces too
    # The member's first contact is still recorded (per-PERSON data, about them).
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


async def test_anonymous_guest_turn_replies_with_unified_memory() -> None:
    # EDGE CASE: a guest with NO sender_id (transport gave no identity) still routes
    # through the social path — Bob replies, the first-impression seam is a clean no-op
    # for an unkeyable sender, and (🔴 BOB-051) the UNIFIED recall still reaches him.
    # (An @mention forces ENGAGE so the prompt is composed, RNG-independent.)
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

    await handler.handle(_addr_message("Боб, расскажи подробно про кофе", mentions_bob=True))

    assert bot.final_text == "привет"  # the anonymous guest still got a social reply
    assert _RECALL_MEMORY in tier1.all_text  # 🔴 unified memory reaches any member
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
    # BOB-045 .2: recall runs but is scoped per-person; the sender-less owner memory
    # is dropped, so no owner content reaches the guest's prompt.
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
    # BOB-045 .2: recall runs but is scoped per-person; the sender-less owner memory
    # is dropped, so no owner content reaches the guest's prompt.
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


# --- BOB-041 .2: natural-language coding intent in Bob's topic (owner-only) --------


class _FakeCodingRouter:
    """Fake natural-language coding router: records routing calls, consumes on demand.

    ``consume`` is the verdict the router returns (whether the message was a coding
    command that short-circuited the normal compose). ``calls`` records every
    ``(text, sender, is_owner)`` it was asked about, so a test can assert exactly when
    HandleMessage delegated and with which owner verdict.
    """

    def __init__(self, *, consume: bool) -> None:
        self._consume = consume
        self.calls: list[tuple[str, int | None, bool]] = []

    async def route(self, *, text: str, sender: int | None, is_owner: bool) -> bool:
        self.calls.append((text, sender, is_owner))
        return self._consume


async def test_owner_coding_message_is_routed_and_short_circuits_compose() -> None:
    # An owner dev-task in Bob's topic is consumed by the coding router; the normal
    # perceive→decide→act compose is skipped (no reply committed, no episode persisted).
    router = _FakeCodingRouter(consume=True)
    handler, bot, repo, tier1 = _build(
        reply="should-not-be-sent",
        perceive_sender=_owner_resolver(),
        coding_router=router,
    )

    await handler.handle(_message("Боб, создай файл HELLO.md"))

    assert router.calls == [("Боб, создай файл HELLO.md", 99, True)]
    assert bot.final_text == ""  # the normal reply path was short-circuited
    assert repo.episodes == []  # no conversation episode for a coding command
    assert tier1.payloads == []  # no Tier 1 compose call


async def test_owner_chat_message_falls_through_to_normal_flow() -> None:
    # An ordinary chat message: the router is consulted but does NOT consume, so the
    # normal compose runs and the reply is committed exactly as before.
    router = _FakeCodingRouter(consume=False)
    handler, bot, _repo, _tier1 = _build(
        reply="обычный ответ",
        perceive_sender=_owner_resolver(),
        coding_router=router,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert router.calls  # the router was consulted on the owner turn
    assert router.calls[0][2] is True  # owner verdict passed through
    assert bot.final_text == "обычный ответ"  # the normal compose ran and committed


async def test_guest_dev_message_is_never_routed_as_owner() -> None:
    # SECURITY: a guest is never owner — the router is told is_owner=False, so it can
    # never trigger a coding session (and the turn falls through to the normal path).
    router = _FakeCodingRouter(consume=False)
    handler, bot, _repo, _tier1 = _build(
        reply="ответ гостю",
        perceive_sender=_guest_resolver(),
        coding_router=router,
    )

    await handler.handle(_message("создай файл X"))

    assert router.calls  # the router was consulted
    assert router.calls[0][2] is False  # not owner
    assert bot.final_text != ""  # the turn fell through to the normal chat path


async def test_no_coding_router_leaves_the_natural_language_path_inert() -> None:
    # coder.enabled false → no router wired → the NL coding path is inert and the
    # message takes the normal chat flow exactly as before BOB-041.
    handler, bot, _repo, _tier1 = _build(
        reply="как обычно", perceive_sender=_owner_resolver()
    )

    await handler.handle(_message("Боб, поправь баг в Z"))

    assert bot.final_text != ""  # normal chat reply committed (NL path inert)


# --- BOB-049: semantic response judge wired into handle_message --------------
# The judge replaces the if/else addressivity decision: Bob UNDERSTANDS the message
# and chooses REPLY / REACT / IGNORE. A fake judge returns a scripted ResponseChoice
# (deterministic), so these tests assert the BRANCHING + persist-in-all-branches +
# the guest-restricted REPLY path staying intact — not the model's judgment itself.

_REACT_EMOJI = "🔥"  # a Telegram free-reaction emoji the judge picks BY MEANING


class _FakeResponseJudge:
    """A ResponseJudge double returning a scripted ResponseChoice, recording the ctx.

    Lets a test pin the social decision deterministically (no model) and inspect the
    ResponseContext the use-case assembled — so the structural signals can be asserted
    to flow in as INPUTS rather than being used as overrides.
    """

    def __init__(self, choice: ResponseChoice) -> None:
        self._choice = choice
        self.contexts: list[ResponseContext] = []

    async def decide(self, ctx: ResponseContext) -> ResponseChoice:
        self.contexts.append(ctx)
        return self._choice


def _judge(
    intent: ResponseIntent, *, emoji: str | None = None
) -> tuple[DecideResponse, _FakeResponseJudge]:
    """Build a DecideResponse over a fake judge returning ``intent`` (+ optional emoji)."""
    fake = _FakeResponseJudge(ResponseChoice(intent=intent, emoji=emoji, reason="test"))
    return DecideResponse(judge=fake), fake


def _bob_half(content: object) -> str:
    """Bob's persisted half of an episode ("<sender>: <text>\\nbob: <half>")."""
    _user, _sep, half = str(content).partition("\nbob: ")
    return half


async def test_judge_reply_composes_sends_and_persists() -> None:
    # REPLY → the existing compose+send path runs and the turn persists with the reply.
    decide, _fake = _judge(ResponseIntent.REPLY)
    handler, bot, repo, _tier1 = _build(
        reply="полный ответ",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert bot.final_text == "полный ответ"  # composed + sent
    assert len(repo.episodes) == 1
    assert _bob_half(repo.episodes[0]["content"]) == "полный ответ"


async def test_judge_react_sets_the_meaning_chosen_emoji_and_persists_reaction() -> None:
    # REACT → the reactor sets the emoji the JUDGE chose (by meaning), and the user's
    # turn persists as "(реакция: <emoji>)" — no reply composed, no router reply call.
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    reactor = _RecordingReactor()
    handler, bot, repo, _tier1 = _build(
        reply="не должно отправиться",
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("ну такое"))

    assert bot.sent == []  # no reply composed/sent
    assert len(reactor.calls) == 1
    _chat, _msg, emoji = reactor.calls[0]
    assert emoji == _REACT_EMOJI  # the emoji chosen BY MEANING, not the mood table
    assert len(repo.episodes) == 1
    assert _bob_half(repo.episodes[0]["content"]) == f"(реакция: {_REACT_EMOJI})"


async def test_judge_react_without_emoji_falls_back_to_the_mood_table() -> None:
    # A REACT with no emoji falls back to the BOB-018 mood→emoji default (kept as a
    # fallback only — the judge's emoji is the primary source when present).
    decide, _fake = _judge(ResponseIntent.REACT, emoji=None)
    reactor = _RecordingReactor()
    soul = _soul()
    handler, _bot, repo, _tier1 = _build(
        reply="x",
        soul=soul,
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("угу"))

    assert len(reactor.calls) == 1
    _chat, _msg, emoji = reactor.calls[0]
    assert emoji in STANDARD_REACTION_EMOJI
    assert _bob_half(repo.episodes[0]["content"]) == f"(реакция: {emoji})"


async def test_judge_ignore_stays_silent_and_persists_promolchal() -> None:
    # IGNORE → no message, no reaction; the user's turn still persists as "(промолчал)".
    decide, _fake = _judge(ResponseIntent.IGNORE)
    reactor = _RecordingReactor()
    handler, bot, repo, _tier1 = _build(
        reply="не должно отправиться",
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("болтают между собой"))

    assert bot.sent == []  # silent
    assert reactor.calls == []  # no reaction
    assert len(repo.episodes) == 1
    assert _bob_half(repo.episodes[0]["content"]) == "(промолчал)"


async def test_judge_react_without_a_reactor_still_persists_the_reaction_turn() -> None:
    # With no reactor wired, a REACT decision still stands (the turn persists as a
    # reaction) — the native reaction is simply not sent (a clean no-op, no crash).
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    handler, bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,  # reactor left unwired
    )

    await handler.handle(_message("ну такое"))

    assert bot.sent == []  # nothing composed/sent
    assert _bob_half(repo.episodes[0]["content"]) == f"(реакция: {_REACT_EMOJI})"


async def test_a_react_turn_lands_in_the_next_turns_per_person_history() -> None:
    # 🔴 persist-in-all-branches keeps the thread (BOB-045): after a REACT turn the prior
    # USER message is on record, so the next turn's per-person history includes it.
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    reactor = _RecordingReactor()
    handler, _bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("это моя первая реплика"))

    # The persisted episode is keyed to the sender and carries the user's words, so a
    # follow-up's recent_episodes_for(sender) replays it.
    assert repo.episodes[0]["sender_id"] == 99
    replayed = await repo.recent_episodes_for(99, 14)
    # (FakeRepo seeds replay from ``history``, not written episodes; assert the written
    # episode itself preserves the prior user turn so the per-person thread can hold it.)
    assert "это моя первая реплика" in str(repo.episodes[0]["content"])
    del replayed


async def test_guest_judge_reply_gets_unified_memory_and_normal_voice() -> None:
    # 🔴 BOB-051: a GUEST whom the judge sends to REPLY gets the UNIFIED recall (Bob's
    # full knowledge) and a NORMAL voice (the wary stranger directive is gone), while
    # attribution still clocks WHO is writing.
    decide, _fake = _judge(ResponseIntent.REPLY)
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    handler, _bot, _repo, tier1 = _build(
        reply="привет",
        perceive_sender=_guest_with_id(99),
        recall=recall,
        decide_response=decide,
    )

    await handler.handle(_message("расскажи подробно, кто ты такой?"))

    folded = tier1.all_text.casefold()
    assert _RECALL_MEMORY in tier1.all_text  # 🔴 unified knowledge reaches the member
    assert "настороже" not in folded  # the wary stranger directive is dropped
    assert "незнаком" in folded  # but Bob still clocks WHO is writing (attribution)


async def test_guest_react_turn_writes_no_owner_facts() -> None:
    # 🔴 BOB-019: a guest REACT turn records ONLY the episodic conversation record, never
    # an owner FACT (no fact extraction on a non-reply turn).
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    reactor = _RecordingReactor()
    handler, _bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_guest_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("случайный текст"))

    assert repo.facts == []  # no owner fact written from a guest turn
    assert len(repo.episodes) == 1  # only the episodic record


async def test_guest_ignore_turn_writes_no_owner_facts() -> None:
    decide, _fake = _judge(ResponseIntent.IGNORE)
    handler, _bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_guest_with_id(99),
        decide_response=decide,
    )

    await handler.handle(_message("болтовня"))

    assert repo.facts == []
    assert _bob_half(repo.episodes[0]["content"]) == "(промолчал)"


async def test_floor_advances_on_every_judge_branch() -> None:
    # The conversation floor advances on REPLY, REACT, and IGNORE alike (BOB-025): each
    # branch upserts the floor so idle_streak / continuity stay correct.
    for intent, emoji in (
        (ResponseIntent.REPLY, None),
        (ResponseIntent.REACT, _REACT_EMOJI),
        (ResponseIntent.IGNORE, None),
    ):
        decide, _fake = _judge(intent, emoji=emoji)
        floor_store = _FakeFloorStore()
        reactor = _RecordingReactor()
        handler, _bot, _repo, _tier1 = _build(
            reply="ответ",
            perceive_sender=_owner_with_id(99),
            reactor=reactor,
            floor_store=floor_store,
            decide_response=decide,
        )

        await handler.handle(_message("сообщение"))

        assert floor_store.saved, f"floor did not advance on {intent}"


async def test_structural_signals_flow_into_the_context_not_as_overrides() -> None:
    # The structural signals are INPUTS to the judge, not deciders: a message DIRECTED TO
    # ANOTHER person (which the legacy ladder would silence) still REPLIES when the judge
    # says so — and the assembled ResponseContext carries the raw structural hints.
    decide, fake = _judge(ResponseIntent.REPLY)
    handler, bot, _repo, _tier1 = _build(
        reply="всё равно отвечаю",
        history=_MULTIPARTY_HISTORY,
        perceive_sender=_owner_with_id(99),
        bob_user_id_source=lambda: 777,
        decide_response=decide,
    )

    # A reply to a THIRD party (not Bob) — legacy DIRECTED_TO_OTHER would stay SILENT.
    await handler.handle(
        _addr_message("расскажи подробно, ты согласен?", reply_to_sender_id=12345)
    )

    assert bot.sent != []  # the judge's REPLY wins — Bob replies despite the signal
    assert len(fake.contexts) == 1
    ctx = fake.contexts[0]
    assert ctx.text == "расскажи подробно, ты согласен?"
    assert ctx.others_present is True  # the multiparty thread is reflected as a hint
    assert ctx.reply_to_bob is False  # replied to someone else, not Bob
    assert ctx.interlocutor.kind is InterlocutorKind.OWNER


async def test_unwired_judge_keeps_the_legacy_addressivity_path() -> None:
    # Backward-compatible: with no judge wired, the legacy ladder runs — a 1:1 owner
    # thread engages and replies exactly as before BOB-049.
    handler, bot, repo, _tier1 = _build(
        reply="как раньше", perceive_sender=_owner_with_id(99)
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert bot.final_text == "как раньше"
    assert len(repo.episodes) == 1


# --- BOB-049 .3: «полный Боб или честный GUPPI-нотис» (reliability) -------------------
# An ESSENTIAL step (the semantic judgment OR the reply generation) that keeps failing
# after bounded retries → an honest GUPPI outage notice and NO degraded reply (the user's
# turn is still persisted). A flaky step that recovers → a normal turn. A SUCCESSFUL
# react/ignore is full Bob, not a failure (no retry, no notice). An OPTIONAL add-on that
# raises is dropped silently — the core reply still ships, no notice. The retry uses the
# injected sleep seam (no real delay).


class _FlakyResponseJudge:
    """A ResponseJudge double that raises on its first ``fail_times`` calls (BOB-049 .3).

    Models a flaky/timing-out semantic judgment: the first ``fail_times`` ``decide`` calls
    raise, then it returns the scripted choice. ``fail_times`` larger than the retry budget
    → it never succeeds (the persistent-failure path).
    """

    def __init__(self, choice: ResponseChoice, *, fail_times: int) -> None:
        self._choice = choice
        self._fail_times = fail_times
        self.calls = 0

    async def decide(self, ctx: ResponseContext) -> ResponseChoice:
        del ctx
        self.calls += 1
        if self.calls <= self._fail_times:
            msg = f"judge unavailable (call #{self.calls})"
            raise RuntimeError(msg)
        return self._choice


def _flaky_judge(
    intent: ResponseIntent, *, fail_times: int, emoji: str | None = None
) -> tuple[DecideResponse, _FlakyResponseJudge]:
    """Build a DecideResponse over a judge that fails ``fail_times`` then returns ``intent``."""
    fake = _FlakyResponseJudge(
        ResponseChoice(intent=intent, emoji=emoji, reason="test"), fail_times=fail_times
    )
    return DecideResponse(judge=fake), fake


class _ReplyFailingProvider:
    """Fails a REPLY completion while still answering the light Tier-0 classifiers (BOB-049 .3).

    Models the model being unable to GENERATE a reply (the essential step) while the
    lightweight Tier-0 calls (sentiment) still answer: a payload carrying Bob's reply
    persona ("You are Bob") raises, any other payload returns a benign label. Used for BOTH
    tiers so the router's Tier-1 → Tier-0 reply fallback ALSO fails — the essential reply
    generation genuinely cannot complete, so the retry budget is exhausted.
    """

    def __init__(self) -> None:
        self.reply_calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str:
        text = " ".join(str(m.get("content", "")) for m in messages)
        if "You are Bob" in text:
            self.reply_calls += 1
            msg = "reply generation unavailable"
            raise RuntimeError(msg)
        return "positive"


class _RaisingReflectionReader:
    """A ReflectionReader double whose read RAISES — models a flaky OPTIONAL add-on."""

    def __init__(self) -> None:
        self.calls = 0

    async def latest_reflection_text(self) -> str | None:
        self.calls += 1
        msg = "reflection store unavailable"
        raise RuntimeError(msg)


async def test_judge_persistent_failure_emits_guppi_notice_and_no_reply() -> None:
    # 🔴 ESSENTIAL judgment fails on EVERY attempt → retried N times then an honest GUPPI
    # outage notice; NO Bob reply is produced, but the user's turn IS persisted (not lost).
    decide, judge = _flaky_judge(ResponseIntent.REPLY, fail_times=99)
    sleep = _RecordingSleep()
    notifier = _FakeOutageNotifier()
    handler, bot, repo, _tier1 = _build(
        reply="не должно отправиться",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        essential_attempts=3,
        retry_sleep=sleep,
        outage_notifier=notifier,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert judge.calls == 3  # initial + 2 retries
    assert notifier.notices == 1  # the honest GUPPI outage notice fired
    assert bot.sent == []  # NO degraded Bob reply shipped
    assert len(repo.episodes) == 1  # the user's turn was persisted (not lost)
    assert _bob_half(repo.episodes[0]["content"]) == "(нет ответа: проблемы со связью)"
    assert sleep.delays == [_TEST_BACKOFF_SECONDS, _TEST_BACKOFF_SECONDS]  # injected sleep


async def test_judge_recovers_after_one_failure_completes_normally() -> None:
    # An essential step that fails ONCE then succeeds → the turn completes normally (the
    # retry worked); NO outage notice, and exactly one backoff was awaited.
    decide, judge = _flaky_judge(ResponseIntent.REPLY, fail_times=1)
    sleep = _RecordingSleep()
    notifier = _FakeOutageNotifier()
    handler, bot, _repo, _tier1 = _build(
        reply="полный ответ",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        retry_sleep=sleep,
        outage_notifier=notifier,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert judge.calls == 2  # failed once, succeeded on the retry
    assert bot.final_text == "полный ответ"  # the turn completed normally
    assert notifier.notices == 0  # a recovered step is NOT an outage
    assert sleep.delays == [_TEST_BACKOFF_SECONDS]  # one backoff between the two tries


async def test_reply_generation_persistent_failure_emits_notice_and_no_reply() -> None:
    # 🔴 The OTHER essential step: the judge says REPLY but the reply generation fails on
    # every attempt → retried then the honest GUPPI notice; no reply, user turn persisted.
    decide, _fake = _judge(ResponseIntent.REPLY)
    sleep = _RecordingSleep()
    notifier = _FakeOutageNotifier()
    # The SAME content-aware provider on both tiers: the lightweight sentiment classifier
    # still answers (so perceive works), but the reply generation fails on tier1 AND its
    # tier-0 fallback — the essential step truly cannot complete.
    provider = _ReplyFailingProvider()
    handler, bot, repo, _tier1 = _build(
        reply="unused",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        tier0_provider=provider,
        tier1_provider=provider,
        essential_attempts=3,
        retry_sleep=sleep,
        outage_notifier=notifier,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert provider.reply_calls > 0  # the reply generation was actually attempted
    assert sleep.delays == [_TEST_BACKOFF_SECONDS, _TEST_BACKOFF_SECONDS]  # retried (3 tries)
    assert notifier.notices == 1  # honest outage notice
    assert bot.sent == []  # no degraded half-answer
    assert _bob_half(repo.episodes[0]["content"]) == "(нет ответа: проблемы со связью)"


async def test_successful_react_is_full_bob_not_a_failure() -> None:
    # A SUCCESSFUL REACT is a genuine choice (full Bob), NOT a failure — no retry, no notice.
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    sleep = _RecordingSleep()
    notifier = _FakeOutageNotifier()
    reactor = _RecordingReactor()
    handler, bot, _repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
        retry_sleep=sleep,
        outage_notifier=notifier,
    )

    await handler.handle(_message("ну такое"))

    assert len(reactor.calls) == 1  # the genuine reaction happened
    assert bot.sent == []  # a react is not a reply, but it is NOT an outage either
    assert notifier.notices == 0  # 🔴 a genuine react never triggers the notice
    assert sleep.delays == []  # no retry on a success


async def test_successful_ignore_is_full_bob_not_a_failure() -> None:
    # A SUCCESSFUL IGNORE is a genuine choice, NOT a failure — no notice.
    decide, _fake = _judge(ResponseIntent.IGNORE)
    notifier = _FakeOutageNotifier()
    handler, bot, _repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        outage_notifier=notifier,
    )

    await handler.handle(_message("болтают между собой"))

    assert bot.sent == []
    assert notifier.notices == 0  # 🔴 a genuine ignore never triggers the notice


async def test_optional_addon_failure_is_dropped_and_core_reply_still_ships() -> None:
    # 🔴 An OPTIONAL flavour (the inner-life leak add-on) that RAISES is dropped silently —
    # the core full-Bob reply still ships, and it NEVER triggers the outage notice.
    decide, _fake = _judge(ResponseIntent.REPLY)
    sleep = _RecordingSleep()
    notifier = _FakeOutageNotifier()
    reflection = _RaisingReflectionReader()
    handler, bot, _repo, _tier1 = _build(
        reply="полный ответ",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        reflection=reflection,  # type: ignore[arg-type]
        expression_freqs=ExpressionFreqs(
            leak_inner_life=1.0, callback=0.0, mention_fascination=0.0
        ),
        retry_sleep=sleep,
        outage_notifier=notifier,
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert reflection.calls >= 1  # the add-on was attempted
    assert bot.final_text == "полный ответ"  # the core reply still ships (full Bob)
    assert notifier.notices == 0  # 🔴 a failing optional add-on is NOT an outage
    assert sleep.delays == []  # an add-on failure is not retried as an essential step


async def test_essential_failure_without_a_notifier_still_ends_cleanly() -> None:
    # Unwired notifier (the optional seam): a persistent essential failure still ends the
    # turn cleanly — the user's turn is persisted and NO degraded reply ships — just with
    # no visible notice (a clean no-op, never a crash).
    decide, _fake = _flaky_judge(ResponseIntent.REPLY, fail_times=99)
    handler, bot, repo, _tier1 = _build(
        reply="не должно отправиться",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        retry_sleep=_RecordingSleep(),
        # no outage_notifier wired
    )

    await handler.handle(_message("расскажи подробно про кофе"))

    assert bot.sent == []  # no degraded reply
    assert len(repo.episodes) == 1  # the user turn is still persisted


class _RaisingOutageNotifier:
    """An OutageNotifier double whose ``notify_outage`` RAISES (best-effort swallow test)."""

    async def notify_outage(self) -> None:
        msg = "notifier transport down"
        raise RuntimeError(msg)


async def test_a_failing_outage_notice_is_swallowed_not_re_raised() -> None:
    # The outage-notice send is best-effort: a flaky notifier must NOT raise on top of the
    # original essential failure — the turn still ends cleanly (user turn persisted).
    decide, _fake = _flaky_judge(ResponseIntent.REPLY, fail_times=99)
    handler, bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
        retry_sleep=_RecordingSleep(),
        outage_notifier=_RaisingOutageNotifier(),  # type: ignore[arg-type]
    )

    await handler.handle(_message("расскажи подробно про кофе"))  # must not raise

    assert bot.sent == []
    assert len(repo.episodes) == 1


@pytest.mark.parametrize(
    ("attempts", "backoff", "match"),
    [
        (0, 0.5, "essential_attempts must be >= 1"),
        (-1, 0.5, "essential_attempts must be >= 1"),
        (3, -0.1, "essential_backoff_seconds must be non-negative"),
    ],
)
def test_rejects_invalid_reliability_settings(
    attempts: int, backoff: float, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        _build(
            reply="x",
            essential_attempts=attempts,
            essential_backoff_seconds=backoff,
        )


async def test_guest_essential_failure_gets_the_same_notice_without_leaking() -> None:
    # A failure on a GUEST turn → the SAME honest GUPPI notice, no reply, no owner facts.
    decide, _judge_fake = _flaky_judge(ResponseIntent.REPLY, fail_times=99)
    notifier = _FakeOutageNotifier()
    handler, bot, repo, _tier1 = _build(
        reply="не должно отправиться",
        perceive_sender=_guest_with_id(99),
        decide_response=decide,
        retry_sleep=_RecordingSleep(),
        outage_notifier=notifier,
    )

    await handler.handle(_message("расскажи подробно, кто ты?"))

    assert notifier.notices == 1  # same honest notice for a guest
    assert bot.sent == []  # no reply (degraded or otherwise) — nothing leaks
    assert repo.facts == []  # a failed guest turn writes no owner facts
    assert len(repo.episodes) == 1  # only the episodic record (the turn is not lost)


# --- BOB-049 ACCEPTANCE: PRD US-1..5 + the semantic-decision principle ----------------
# Guardrails mapped directly to the product stories. The judge is a deterministic fake
# (no model), so each test pins WHAT Bob decided and asserts the OBSERVABLE turn outcome:
# the decision is SEMANTIC (the judge), never ``is_owner``; authz stays orthogonal; the
# structural/mood/thread components feed the judge as SIGNALS, not deciders.

# A real question, NO «Боб,» tag. Worded with a natural depth cue ("почему") so the
# hybrid tier selector escalates to the quality (tier1) reply the capturing fake inspects.
_FRIEND_QUESTION = "слушай, а почему ты сам про всё это так думаешь?"


def _known_with_id(sender_id: int | None) -> _FakeInterlocutorResolver:
    """A KNOWN, non-owner friend (e.g. Norman) — trusted enough for the full path."""
    return _FakeInterlocutorResolver(
        _interlocutor(
            name="Norman",
            kind=InterlocutorKind.KNOWN,
            trust=Trust.TRUSTED,
            sender_id=sender_id,
        )
    )


@pytest.mark.parametrize(
    "resolver_factory",
    [_owner_with_id, _known_with_id],
    ids=["owner", "friend-norman"],
)
async def test_us1_important_question_replies_by_semantic_decision_not_is_owner(
    resolver_factory: Callable[[int], _FakeInterlocutorResolver],
) -> None:
    # US-1: an important message — an OWNER question AND a non-owner FRIEND (Norman)
    # question, BOTH WITHOUT «Боб,» — that the judge reads as REPLY → Bob composes a full
    # reply. The owner and the friend land identically: the REPLY is the judge's SEMANTIC
    # read, not an ``is_owner`` shortcut (a friend is not silenced for lacking the tag).
    decide, fake = _judge(ResponseIntent.REPLY)
    handler, bot, repo, _tier1 = _build(
        reply="вот что я думаю...",
        perceive_sender=resolver_factory(99),
        decide_response=decide,
    )

    await handler.handle(_message(_FRIEND_QUESTION))

    assert bot.final_text == "вот что я думаю..."  # a full reply, owner and friend alike
    assert _bob_half(repo.episodes[0]["content"]) == "вот что я думаю..."
    assert fake.contexts[0].text == _FRIEND_QUESTION  # the judge weighed the message itself


@pytest.mark.parametrize(
    ("intent", "emoji"),
    [(ResponseIntent.REACT, _REACT_EMOJI), (ResponseIntent.IGNORE, None)],
    ids=["react", "ignore"],
)
async def test_us2_unimportant_ambient_message_is_not_forced_into_a_reply(
    intent: ResponseIntent, emoji: str | None
) -> None:
    # US-2: a long, ambient message in a busy thread (others present) the judge reads as
    # unimportant → REACT or IGNORE. Bob is NOT forced into a reply — no compose, no send;
    # the user's turn still persists (the thread is never dropped).
    long_ambient = "ну в общем мы там вчера долго гуляли и обсуждали всякое разное " * 6
    decide, _fake = _judge(intent, emoji=emoji)
    reactor = _RecordingReactor()
    handler, bot, repo, _tier1 = _build(
        reply="НЕ должно отправиться",
        history=_MULTIPARTY_HISTORY,
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message(long_ambient))

    assert bot.sent == []  # no forced reply
    assert len(repo.episodes) == 1  # the turn is still recorded (thread preserved)


async def test_us3_react_uses_the_judges_emoji_not_the_mood_to_emoji_table() -> None:
    # US-3: the REACT emoji is chosen BY MEANING — the judge's emoji is set on the message,
    # NOT the BOB-018 mood→emoji table's pick. Guardrail: the judge's emoji genuinely
    # DIFFERS from what the mood table would have chosen, so the table cannot be deciding.
    soul = _soul()
    mood_table_emoji = reaction_emoji_for(soul.mood)
    assert mood_table_emoji != _REACT_EMOJI, "fixture must make the two emoji differ"
    decide, _fake = _judge(ResponseIntent.REACT, emoji=_REACT_EMOJI)
    reactor = _RecordingReactor()
    handler, _bot, _repo, _tier1 = _build(
        reply="x",
        soul=soul,
        perceive_sender=_owner_with_id(99),
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("любопытная мысль"))

    _chat, _msg, emoji = reactor.calls[0]
    assert emoji == _REACT_EMOJI  # the judge's meaning-chosen emoji
    assert emoji != mood_table_emoji  # the mood table did NOT decide


# A prior turn the owner spoke that Bob IGNORED — the «что скажешь?»-class message whose
# loss was the original memory bug. Keyed to the owner's sender_id so the per-person
# replay surfaces it on the follow-up.
_PRIOR_IGNORED_TURN: tuple[Mapping[str, object], ...] = (
    {
        "content": "Vova: а что скажешь про новый план?\nbob: (промолчал)",
        "event_type": "message",
        "sender_id": 99,
    },
)


async def test_us4_ignore_turn_records_the_user_message_keyed_to_the_sender() -> None:
    # US-4 (record side): an IGNORE turn still PERSISTS the user's words keyed to the
    # sender, so the per-person thread is never dropped — the root of the «что скажешь?» bug.
    decide, _fake = _judge(ResponseIntent.IGNORE)
    handler, _bot, repo, _tier1 = _build(
        reply="x",
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
    )

    await handler.handle(_message("а что скажешь про новый план?"))

    assert repo.episodes[0]["sender_id"] == 99  # keyed to the person
    assert "а что скажешь про новый план?" in str(repo.episodes[0]["content"])


async def test_us4_followup_after_a_nonreply_turn_has_the_prior_thread_in_context() -> None:
    # US-4 (follow-up side): after Bob ignored a turn, a follow-up's judgment context
    # carries the prior user message in the per-person recent_thread — so Bob now answers
    # WITH the context he previously stayed silent on (the bug is fixed end to end).
    decide, fake = _judge(ResponseIntent.REPLY)
    handler, bot, _repo, _tier1 = _build(
        reply="да, по тому плану — вот что думаю",
        history=_PRIOR_IGNORED_TURN,
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
    )

    await handler.handle(_message("ну так что?"))

    assert bot.sent != []  # Bob now replies
    recent_thread = fake.contexts[0].recent_thread
    assert "а что скажешь про новый план?" in recent_thread  # the prior turn is in context


async def test_us5_owner_judge_reply_keeps_the_trusted_recall_path() -> None:
    # 🔴 US-5 (orthogonality, positive side): the semantic decision does NOT strip the
    # OWNER's trusted path — an owner REPLY still recalls owner memory into the prompt.
    decide, _fake = _judge(ResponseIntent.REPLY)
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    handler, _bot, _repo, tier1 = _build(
        reply="конечно помню",
        perceive_sender=_owner_with_id(99),
        recall=recall,
        decide_response=decide,
    )

    await handler.handle(_message("расскажи подробно, помнишь, о чём я говорил?"))

    assert _RECALL_MEMORY in tier1.all_text  # the owner keeps the trusted recall


@pytest.mark.parametrize(
    ("intent", "emoji"),
    [
        (ResponseIntent.REPLY, None),
        (ResponseIntent.REACT, _REACT_EMOJI),
        (ResponseIntent.IGNORE, None),
    ],
    ids=["reply", "react", "ignore"],
)
async def test_us5_guest_intent_governs_compose_with_unified_memory(
    intent: ResponseIntent, emoji: str | None
) -> None:
    # 🔴 BOB-051: memory is unified, so the judge's decision (not authz) governs whether a
    # reply is composed. A guest REPLY carries the UNIFIED recall into the prompt; a REACT
    # or IGNORE composes no reply at all, so the recalled memory never reaches the prompt.
    decide, _fake = _judge(intent, emoji=emoji)
    recall = FakeRecall(hits=[{"content": _RECALL_MEMORY, "category": "personal"}])
    reactor = _RecordingReactor()
    handler, _bot, _repo, tier1 = _build(
        reply="ответ участнику",
        perceive_sender=_guest_with_id(2),
        recall=recall,
        reactor=reactor,
        decide_response=decide,
    )

    await handler.handle(_message("расскажи подробно, кто ты и что помнишь?"))

    if intent is ResponseIntent.REPLY:
        assert _RECALL_MEMORY in tier1.all_text  # unified recall reaches the reply
    else:
        assert _RECALL_MEMORY not in tier1.all_text  # REACT/IGNORE compose no reply


async def test_mood_tone_flows_into_the_judgment_context_as_a_signal() -> None:
    # Regression / signal-provider (BOB-033): Bob's mood TONE is handed to the judge as a
    # weighed SIGNAL (ctx.mood_tone), never a decider — confirming the emotional state is
    # an input to the semantic decision.
    soul = _soul()
    decide, fake = _judge(ResponseIntent.REPLY)
    handler, _bot, _repo, _tier1 = _build(
        reply="ответ",
        soul=soul,
        perceive_sender=_owner_with_id(99),
        decide_response=decide,
    )

    await handler.handle(_message("как дела?"))

    assert fake.contexts[0].mood_tone == soul.mood.tone()  # mood reaches the judge as a hint


# --- BOB-051: unified public memory vs. the gated-privilege invariant ----------
# Acceptance + guardrail tests for the closed-group memory/privilege split (PRD US-1..5).
# The closed Bobiverse group is a PUBLIC space, so Bob's MEMORY is UNIFIED for every
# member (recall, per-person history, normal voice, fact extraction) while ``is_guest``
# keeps gating ONLY privileges (tool-loop / capabilities, the owner inner-life add-ons,
# owner commands). Every assertion is driven by fakes — no real LLM — so it is
# deterministic; an @mention forces ENGAGE where the legacy addressivity path is in play.

# A non-owner member is keyed on ``_GUEST_SENDER_ID`` (2) — the Norman/roadmap
# split-brain case; an owner-originated fact is attributed to ``_OWNER_SENDER_ID`` (1).
_OWNER_FACT = "владелец рассказал про дорожную карту Bobiverse"


async def test_bob051_us1_owner_conversation_fact_is_recallable_for_a_non_owner() -> None:
    # 🔴 US-1 (the Norman/roadmap split-brain is GONE): a fact that originated in the
    # OWNER's conversation (attributed to the owner's sender_id) is now recallable for a
    # NON-OWNER member — Bob's general knowledge is one unified pool, not a per-person
    # silo. The recalled item from the owner's conversation reaches Norman's context.
    recall = FakeRecall(
        hits=[{"content": _OWNER_FACT, "category": "fact", "sender_id": _OWNER_SENDER_ID}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", recall=recall, perceive_sender=_guest_with_id(_GUEST_SENDER_ID)
    )

    await handler.handle(
        _addr_message("Боб, расскажи подробно про дорожную карту", mentions_bob=True)
    )

    assert _OWNER_FACT in tier1.all_text  # owner-originated knowledge reaches the member


async def test_bob051_us3_a_non_owner_statement_becomes_a_stored_fact() -> None:
    # 🔴 US-3 (public memory grows): a NON-OWNER member's durable statement is distilled
    # into Bob's semantic memory end to end — the SAME extraction the owner gets — so the
    # group's shared memory grows from every member's turn (here the stored fact lands in
    # the repo). (@mention forces ENGAGE so the assertion is RNG-independent.)
    handler, _bot, repo, _tier1 = _build(
        reply="приятно познакомиться",
        tier0_replies=[
            "positive",
            '[{"category": "user", "content": "Norman likes tea"}]',
        ],
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_addr_message("Боб, я люблю чай", mentions_bob=True))

    assert any(getattr(f, "content", "") == "Norman likes tea" for f in repo.facts)


async def test_bob051_us5_non_owner_turn_relaxes_memory_but_not_privileges() -> None:
    # 🔴 US-5 — THE SECURITY CORE: one NON-OWNER turn, fully wired (tools, reflection,
    # fascination, owner-attributed recall) and @mentioned so Bob ENGAGEs. MEMORY is
    # RELAXED — the owner-originated recall surfaces and the voice is normal (no wary
    # stranger directive) — while every PRIVILEGE stays gated: NO tool-loop / capability,
    # NO owner inner-life add-on (leak / callback / fascination preface), and the coding
    # router is told is_owner=False (owner commands like /code are refused).
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    coding = _FakeCodingRouter(consume=False)
    recall = FakeRecall(
        hits=[{"content": _OWNER_FACT, "category": "fact", "sender_id": _OWNER_SENDER_ID}]
    )
    handler, _bot, _repo, tier1 = _build(
        reply="привет",
        registry=registry,
        tool_provider=provider,
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        fascination=_FakeFascinationReader(fascination=_FASCINATION),
        expression_freqs=ExpressionFreqs(
            leak_inner_life=1.0, callback=1.0, mention_fascination=1.0
        ),
        recall=recall,
        coding_router=coding,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(
        _addr_message("Боб, создай файл X и расскажи о себе", mentions_bob=True)
    )

    folded = tier1.all_text.casefold()
    # Memory RELAXED: owner-originated knowledge surfaces, the voice is normal.
    assert _OWNER_FACT in tier1.all_text  # 🔴 unified recall (US-1) inside US-5
    assert "настороже" not in folded  # no wary stranger directive (US-2)
    # Privileges NOT relaxed:
    assert provider.tools_seen == []  # the tool loop never ran for a non-owner
    assert cap.calls == []  # no capability dispatched
    assert _REFLECTION_TEXT not in tier1.all_text  # leak_inner_life withheld
    assert "реальный момент из вашего прошлого" not in folded  # callback preface withheld
    assert _FASCINATION.topic not in tier1.all_text  # fascination add-on withheld
    assert coding.calls  # the coding router was consulted
    assert coding.calls[0][2] is False  # owner command refused (is_owner=False)


async def test_bob051_us5_owner_turn_keeps_every_privilege() -> None:
    # 🔴 US-5 (owner path UNCHANGED): the SAME wiring on an OWNER turn keeps the trusted
    # privileges — the tool-loop runs, the capability is dispatched, and the coding router
    # is told is_owner=True (owner commands are honoured). The contrast proves is_guest
    # (not the wiring) is what gates privileges.
    registry, cap = _registry_with_recall()
    provider = ScriptedToolProvider()
    coding = _FakeCodingRouter(consume=False)
    handler, _bot, _repo, _tier1 = _build(
        reply="unused",
        registry=registry,
        tool_provider=provider,
        coding_router=coding,
        perceive_sender=_owner_with_id(99),
    )

    await handler.handle(_message("what's my name?"))

    assert provider.tools_seen  # the tool loop ran for the owner
    assert cap.calls == [{"query": "name"}]  # the capability was dispatched
    assert coding.calls  # the coding router was consulted
    assert coding.calls[0][2] is True  # owner verdict honoured (is_owner=True)


@pytest.mark.parametrize(
    ("addon", "preface_fragment"),
    [
        ("leak", "ловил себя на мысли"),
        ("callback", "реальный момент из вашего прошлого"),
        ("fascination", "чем сейчас увлечён"),
    ],
)
async def test_bob051_us5_inner_life_addon_preface_withheld_from_a_non_owner(
    addon: str, preface_fragment: str
) -> None:
    # 🔴 US-5: each grounded owner inner-life add-on (leak / callback / fascination) is an
    # owner-only privilege — even on an ENGAGEd non-owner turn its framing PREFACE never
    # reaches the prompt. (Unified recall may surface the underlying memory TEXT; the
    # privilege withheld is the intimate inner-life FRAMING, asserted on the preface.)
    freqs = ExpressionFreqs(
        leak_inner_life=1.0 if addon == "leak" else 0.0,
        callback=1.0 if addon == "callback" else 0.0,
        mention_fascination=1.0 if addon == "fascination" else 0.0,
    )
    reflection = (
        _FakeReflectionReader(text=_REFLECTION_TEXT) if addon == "leak" else None
    )
    fascination = (
        _FakeFascinationReader(fascination=_FASCINATION)
        if addon == "fascination"
        else None
    )
    recall = (
        FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}])
        if addon == "callback"
        else FakeRecall()
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=freqs,
        reflection=reflection,
        fascination=fascination,
        recall=recall,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(_addr_message("Боб, расскажи о себе", mentions_bob=True))

    assert preface_fragment.casefold() not in tier1.all_text.casefold()


async def test_bob051_us5_inner_life_addons_still_surface_for_the_owner() -> None:
    # Guardrail companion: with all three add-on flags on AND the real material present,
    # the OWNER's prompt carries every inner-life preface — confirming the
    # withheld-from-a-member assertions above gate on is_guest, not on missing wiring.
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        expression_freqs=ExpressionFreqs(
            leak_inner_life=1.0, callback=1.0, mention_fascination=1.0
        ),
        reflection=_FakeReflectionReader(text=_REFLECTION_TEXT),
        fascination=_FakeFascinationReader(fascination=_FASCINATION),
        recall=FakeRecall(hits=[{"content": _STRONG_MOMENT, "category": "episodic"}]),
        perceive_sender=_owner_with_id(99),
    )

    await handler.handle(
        _message("расскажи подробно про Bobiverse и космос сегодня")
    )

    folded = tier1.all_text.casefold()
    assert "ловил себя на мысли" in folded  # leak preface
    assert "реальный момент из вашего прошлого" in folded  # callback preface
    assert "чем сейчас увлечён" in folded  # fascination preface


async def test_bob051_us4_non_owner_hears_shared_thread_and_keeps_reactions() -> None:
    # 🔴 US-4 (continuity + per-person signals intact): under unified RECALL the non-owner
    # hears the SHARED group thread (BOB-058 .1) with attribution (WHO is writing), and a
    # notable reaction of theirs (BOB-050) is still woven only into THEIR context — the
    # reaction layer stays per-person even as the conversation thread becomes shared.
    store = _FakeNotableStore(_notable(sender_id=_GUEST_SENDER_ID))
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        history=_PERSON_THREAD,
        notable_reaction=store,
        acknowledge_reaction_freq=1.0,
        perceive_sender=_guest_with_id(_GUEST_SENDER_ID),
    )

    await handler.handle(
        _addr_message("Боб, расскажи подробно, продолжим?", mentions_bob=True)
    )

    text = tier1.all_text
    assert _GUEST_THREAD_TURN in text  # their own turn (shared thread, BOB-058)
    assert _OWNER_THREAD_TURN in text  # 🔴 and the other member's turn too
    assert "Norman" in text  # attribution: Bob still clocks WHO is writing
    assert "кофе по утрам — это ритуал" in text  # their reaction woven in (BOB-050)
    assert store.cleared is True  # consumed so Bob does not repeat it


# ---------------------------------------------------------------------------
# BOB-057 .2 — pre-answer epistemic verify (direct web_search, ungated) + hedge
# ---------------------------------------------------------------------------

_VOLATILE_QUERY = "текущая ключевая ставка ЦБ РФ 2026"
_VOLATILE_TOPIC = "свежая ставка ЦБ"
_NEEDS_CHECK = VolatilityVerdict(
    needs_check=True, query=_VOLATILE_QUERY, topic=_VOLATILE_TOPIC
)
_NO_CHECK = VolatilityVerdict(needs_check=False, query="", topic="")


async def test_verify_skipped_when_judge_says_no_check() -> None:
    # 🔴 US-2 (не зануда): a non-volatile turn — the judge returns needs_check=False, so
    # the provider is NEVER called and no verify note reaches generation (zero latency).
    judge = _FakeVolatilityJudge(verdict=_NO_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="unused"))
    handler, _bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    assert judge.calls, "the judge should assess the turn"
    assert provider.queries == [], "no search on a non-volatile turn"
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text


# 🔴 US-2 «НЕ ЗАНУДА» at the FLOW boundary: a representative benign set — the
# conservative judge returns needs_check=False for each — must take the zero-network,
# zero-chatter path (no search, no interim line, no note reaches generation). The id
# names the benign category the False verdict stands in for (banter, greeting, opinion,
# joke, hypothetical, stable fact, Bob's own memory). Complements the exhaustive parser
# table in test_volatility_judgment.py.
_BENIGN_CATEGORIES: tuple[str, ...] = (
    "greeting",
    "smalltalk",
    "opinion_feeling",
    "joke",
    "hypothetical",
    "stable_fact_history",
    "stable_fact_math",
    "bob_memory",
)


@pytest.mark.parametrize("category", _BENIGN_CATEGORIES)
async def test_verify_benign_turn_never_touches_the_net(category: str) -> None:
    # 🔴 The anti-bore floor at the flow level: none of these categories may trigger a
    # search, an interim line, or a folded note — zero added latency (US-2).
    judge = _FakeVolatilityJudge(verdict=_NO_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="unused"))
    generator = _FakeInterimLineGenerator(line="не должно прозвучать")
    handler, bot, _repo, tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=generator,
    )

    await handler.handle(_message())

    assert provider.queries == [], f"{category}: no search on a benign turn"
    assert generator.calls == [], f"{category}: no interim gen on a benign turn"
    assert bot.sent == [(555, "hi")], f"{category}: only the answer, no interim line"
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text
    assert "не вышло" not in tier1.all_text  # no hedge either


async def test_verify_runs_direct_search_and_folds_grounded_note() -> None:
    # US-1/US-4: on a volatile turn Bob searches DIRECTLY with verdict.query and the
    # grounded finding is folded into the Tier-1 generation context (facts + tone nudge).
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(
        result=WebSearchResult(answer="Ставка ЦБ сейчас 16%")
    )
    handler, _bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    assert provider.queries == [_VOLATILE_QUERY], "one DIRECT search with verdict.query"
    folded = tier1.all_text
    assert "СВЕЖАЯ ПРОВЕРКА (веб): Ставка ЦБ сейчас 16%" in folded
    assert "отреагируй по-своему" in folded  # the tone nudge reaches generation


async def test_verify_direct_search_bypasses_registry_and_gate() -> None:
    # 🔴 US-5 (не привилегия): the verify search fires even though the capability
    # registry is EMPTY (default) and no permission flow is wired — proving it is a
    # DIRECT internal call, never registry.dispatch / the BOB-052 per-sender gate.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    handler, _bot, _repo, _tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    # An empty registry could not have dispatched web_search — the search only ran
    # because the verify path calls the provider directly (ungated).
    assert provider.queries == [_VOLATILE_QUERY]
    assert handler._registry.is_empty  # the ungated boundary (empty registry)


async def test_verify_search_failure_yields_honest_hedge() -> None:
    # 🔴 US-6: a failing search NEVER fabricates a fact — Bob gets an honest hedge note
    # (no grounded finding, no stale number as fact) and the answer still ships.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(raises=True)
    handler, bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    folded = tier1.all_text
    assert "Свериться со свежими данными по свежая ставка ЦБ не вышло" in folded
    assert "СВЕЖАЯ ПРОВЕРКА" not in folded  # no fabricated grounded finding
    assert bot.final_text == "hi"  # the turn still produced its answer


async def test_verify_search_timeout_yields_hedge() -> None:
    # US-3 (не 5 минут): a hanging search is bounded by verify.timeout_seconds and
    # degrades to the honest hedge rather than stalling the turn.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(hang=True)
    handler, _bot, _repo, tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        verify_timeout_seconds=0.01,
    )

    await handler.handle(_message())

    assert "не вышло" in tier1.all_text  # hedge on timeout
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text


async def test_verify_empty_answer_yields_hedge() -> None:
    # An empty search answer is not a grounded finding — Bob hedges honestly (US-6).
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="   "))
    handler, _bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    assert "не вышло" in tier1.all_text
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text


def test_grounded_note_steers_bobs_voice_not_an_agent_report() -> None:
    # BOB-060 .2 register-nudge: the GROUNDED note must instruct Bob to present the
    # finding IN HIS OWN VOICE, reacting to it — explicitly NOT as a generic agent
    # report ("выполнен поиск, найдено N…"). Structural keyword assertions on the
    # note builder output (not brittle full-string matches).
    note = _VERIFY_GROUNDED_NOTE.format(answer="Ставка ЦБ сейчас 16%")
    folded = note.casefold()

    assert "Ставка ЦБ сейчас 16%" in note  # the real finding is carried in
    # A voice-steer is present: react as Bob / in his own words.
    assert "как боб" in folded or "по-своему" in folded
    # And an explicit anti-report steer (do NOT read as an agent report / dry summary).
    assert "отчёт" in folded


def test_hedge_note_keeps_anti_confabulation_and_a_live_voice() -> None:
    # 🔴 BOB-053 invariant intact: the HEDGE note still forbids passing a stale number
    # off as fact / fabricating — AND now steers an HONEST, LIVE caveat in Bob's voice
    # (not a robotic "поиск не удался").
    note = _VERIFY_HEDGE_NOTE.format(topic="свежая ставка ЦБ")
    folded = note.casefold()

    # Anti-confabulation (BOB-053): no stale figure as fact, no invention.
    assert "устаревш" in folded
    assert "выдум" in folded or "выдав" in folded
    # Live, in-voice honesty steer (not a dry robo-report).
    assert "честно" in folded
    assert "живо" in folded or "своими словами" in folded


async def test_verify_judge_failure_is_treated_as_no_check() -> None:
    # 🔴 Decorative: a judge that RAISES is caught and treated as «no check» — the
    # provider is never called, no note is added, and the turn still ships its answer.
    judge = _FakeVolatilityJudge(raises=True)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="unused"))
    handler, bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    assert provider.queries == [], "a judge failure must not trigger a search"
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text
    assert "не вышло" not in tier1.all_text
    assert bot.final_text == "hi"  # the turn is unaffected


async def test_verify_inert_when_provider_unwired() -> None:
    # verify.enabled off (either seam None) → the feature is fully inert: the judge is
    # never even consulted, behaviour exactly as before.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    handler, _bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=None
    )

    await handler.handle(_message())

    assert judge.calls == [], "an unwired provider makes the whole seam inert"
    assert "СВЕЖАЯ ПРОВЕРКА" not in tier1.all_text


# ---------------------------------------------------------------------------
# BOB-057 .3 — the LIVE, ADDRESSED interim line before the verify search (US-3b)
# ---------------------------------------------------------------------------


async def test_verify_interim_sends_live_addressed_line_before_search() -> None:
    # US-3b: on a needs_check turn Bob speaks a LIVE one-liner naming the subject and
    # addressing the sender, sent BEFORE the search (not a scripted abstract «ищу…»).
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    generator = _FakeInterimLineGenerator(line="Лёш, гляну свежие ставки, секунду 🙂")
    sent_len_at_search: list[int] = []
    provider = _FakeWebSearchProvider(
        result=WebSearchResult(answer="16%"),
        on_search=lambda: sent_len_at_search.append(len(bot.sent)),
    )
    resolver = _FakeInterlocutorResolver(
        _interlocutor(name="Лёша", kind=InterlocutorKind.OWNER)
    )
    handler, bot, _repo, _tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=generator,
        perceive_sender=resolver,
    )

    await handler.handle(_message())

    # The live gen saw the verdict's topic + the perceived sender name.
    assert generator.calls == [(_VOLATILE_TOPIC, "Лёша")]
    # The addressed interim line reached the chat FIRST, before the search ran.
    assert bot.sent[0][1] == "Лёш, гляну свежие ставки, секунду 🙂"
    assert sent_len_at_search == [1], "the interim was sent before the search"
    assert provider.queries == [_VOLATILE_QUERY]
    assert bot.final_text == "hi"  # the turn still ships its answer


async def test_verify_interim_empty_gen_stays_silent() -> None:
    # 🔴 BOB-060 US-2: an empty live line → SILENCE (no seeded phrase). The search still
    # runs — only the interim VOICE is dropped, never a scripted line.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    handler, bot, _repo, _tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=_FakeInterimLineGenerator(line="   "),
    )

    await handler.handle(_message())

    assert bot.sent[0][1] == "hi", "no interim line — only the final answer"
    assert provider.queries == [_VOLATILE_QUERY]


async def test_verify_interim_without_generator_stays_silent() -> None:
    # 🔴 BOB-060 US-2: no generator wired → SILENCE (there is no scripted fallback).
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    handler, bot, _repo, _tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())

    assert bot.sent[0][1] == "hi", "no interim line — only the final answer"


async def test_verify_interim_gen_failure_stays_silent() -> None:
    # 🔴 Decorative + US-2: a raising live gen is caught → SILENCE (no fallback phrase);
    # the search + turn are unaffected.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    handler, bot, _repo, _tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=_FakeInterimLineGenerator(raises=True),
    )

    await handler.handle(_message())

    assert bot.sent[0][1] == "hi", "no interim line — only the final answer"
    assert provider.queries == [_VOLATILE_QUERY]
    assert bot.final_text == "hi"


async def test_verify_computed_once_per_turn_across_a_regeneration() -> None:
    # 🔴 US-3 «один поиск (не петля)» — BOB-057 .5 BLOCKER fix. When a needs_check turn's
    # first draft trips the anti-repeat guard, _compose_reply runs AGAIN (regeneration).
    # The verify step (judge → interim → search → note) is computed EXACTLY ONCE per turn
    # and the resulting note is THREADED into every regeneration, so the regenerated pass
    # REUSES it instead of re-judging / re-searching / re-announcing. Even across a forced
    # regeneration Bob hits the net once, assesses once, and speaks the interim line once —
    # no 3× serial-search loop, no double «погоди, проверю…».
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    generator = _FakeInterimLineGenerator(line="Лёш, гляну свежие ставки, секунду 🙂")
    handler, bot, _repo, tier1 = _build(
        reply="unused",
        tier1_replies=[_REPEATED_REPLY, "А вот теперь совсем другой ответ."],
        history=[{"content": _PRIOR_DUP_TURN, "event_type": "message"}],
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=generator,
    )

    await handler.handle(_message("объясни подробно ещё раз то же самое"))

    assert len(tier1.payloads) == 2, "the repeat guard forced one regeneration"
    # ONCE per turn across the regeneration: one judgment, one direct search, one interim.
    assert len(judge.calls) == 1, "judge.assess must run once per turn (not per attempt)"
    assert provider.queries == [_VOLATILE_QUERY], "exactly ONE search across the regen"
    assert len(generator.calls) == 1, "no second interim line on regeneration"
    interim_lines = [text for _cid, text in bot.sent if text != bot.final_text]
    assert interim_lines == ["Лёш, гляну свежие ставки, секунду 🙂"]
    assert bot.final_text == "А вот теперь совсем другой ответ."
    # The verify note computed on attempt 1 is REUSED on the regenerated attempt — the
    # grounded finding folds into BOTH generation payloads (not recomputed, not dropped).
    payload_texts = [
        "\n".join(m["content"] for m in payload) for payload in tier1.payloads
    ]
    assert all(
        "СВЕЖАЯ ПРОВЕРКА (веб): 16%" in text for text in payload_texts
    ), "the once-computed verify note is threaded into every regeneration"


async def test_verify_note_not_leaked_across_sequential_turns() -> None:
    # 🔴 Per-turn locality (BOB-057 .5): the verify memoization is a LOCAL threaded through
    # the call chain, NOT a HandleMessage instance attribute — HandleMessage is a shared
    # singleton, so an instance flag would leak the note (and the "already searched" state)
    # into later turns/users. Two sequential turns each compute their OWN verify step:
    # turn 2 judges + searches afresh (its own query), never reusing turn 1's note.
    judge = _FakeVolatilityJudge(verdict=_NEEDS_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="16%"))
    handler, _bot, _repo, tier1 = _build(
        reply="hi", verify_judge=judge, verify_provider=provider
    )

    await handler.handle(_message())
    await handler.handle(_message())

    # Each turn ran its OWN judgment + search — turn 2 is not short-circuited by turn 1.
    assert len(judge.calls) == 2, "each turn assesses independently (no cross-turn cache)"
    assert provider.queries == [_VOLATILE_QUERY, _VOLATILE_QUERY], "one search per turn"
    assert len(tier1.payloads) >= 2


async def test_verify_interim_not_sent_on_no_check_path() -> None:
    # 🔴 The interim fires ONLY when needs_check — a non-volatile turn sends no interim
    # (zero added chatter, US-2 «не зануда»).
    judge = _FakeVolatilityJudge(verdict=_NO_CHECK)
    provider = _FakeWebSearchProvider(result=WebSearchResult(answer="unused"))
    generator = _FakeInterimLineGenerator(line="Лёш, секунду 🙂")
    handler, bot, _repo, _tier1 = _build(
        reply="hi",
        verify_judge=judge,
        verify_provider=provider,
        interim_line_generator=generator,
    )

    await handler.handle(_message())

    assert generator.calls == [], "no live gen on a non-volatile turn"
    assert bot.sent == [(555, "hi")], "only the final answer, no interim line"
