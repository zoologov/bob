# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition root — wire every layer into the running GUPPI process.

This is the ONLY module allowed to depend on all layers at once. It loads the
layered config, builds the real infrastructure adapters (SQLite repo + FTS5
recall, OpenAI-compatible Tier 0/1 providers, the **two-bot** Telegram gateway,
the soul store), composes the application policy (the :class:`LLMRouter`, the
personality state, the message handler, and the heartbeat ticks), subscribes
:class:`HandleMessage` to the EventBus, registers the ticks + Telegram polling as
runtime background tasks, runs :class:`RunGenesis` once on first boot, and starts
the :class:`AgentRuntime`.

Two admin bots live in one process (BOB-003): Bob is scoped to his forum topic
and GUPPI is the gatekeeper/admin in General, both registered behind one
:class:`~bob.infrastructure.telegram.multibot.MultiBotGateway` whose single poll
drives both. Bob's pipeline (``HandleMessage``) streams replies through the
gateway's Bob reply-seam so they pin to his topic thread; GUPPI's reject + owner
commands run off the shared :class:`Authorizer`.

Secrets (``telegram.bob.token``, ``telegram.guppi.token``, ``llm.tier1_api_key``)
come from config/env only — never inlined here. The providers and both bots are
injectable seams so the whole graph can be exercised end-to-end on fakes (no
network).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from bob.application.authz import Authorizer
from bob.application.capabilities import (
    CapabilityRegistry,
    make_recall_memory_capability,
)
from bob.application.router import LLMRouter
from bob.application.runtime import (
    MESSAGE_RECEIVED,
    AgentRuntime,
    AsyncEventBus,
    MessageReceived,
    RetryPolicy,
    periodic,
)
from bob.application.usecases.extract_facts import ExtractFacts
from bob.application.usecases.handle_message import HandleMessage, PersonalityState
from bob.application.usecases.heartbeat import (
    InnerMonologueTick,
    MoodDriftTick,
    ReflectTick,
)
from bob.application.usecases.run_genesis import RunGenesis
from bob.application.usecases.update_mood_from_text import UpdateMoodFromText
from bob.domain.personality.mood import Mood
from bob.domain.personality.soul import SOUL
from bob.domain.personality.taste import TasteAxis, TasteEngine
from bob.infrastructure.config import ConfigLoader
from bob.infrastructure.llm import build_tier_providers
from bob.infrastructure.persistence import (
    Fts5MemoryRecall,
    KvAllowlistStore,
    SoulStore,
    SqliteMemoryRepo,
)
from bob.infrastructure.telegram.multibot import (
    BotIdentity,
    BotRegistry,
    BotScope,
    MultiBotGateway,
)

if TYPE_CHECKING:
    from aiogram.types import InputRichMessage

    from bob.application.runtime.agent import BackgroundTask
    from bob.application.usecases.run_genesis import GenesisResult
    from bob.domain.ports import (
        DomainEvent,
        EventHandler,
        LLMProvider,
        ToolCallingProvider,
    )
    from bob.infrastructure.telegram.gateway import (
        BotLike,
        MessageLike,
        UpdateLike,
    )

logger = logging.getLogger(__name__)

# Default heartbeat cadence and gateway streaming knobs.
_DEFAULT_HEARTBEAT_SECONDS = 30
_DEFAULT_POLL_TIMEOUT = 10
_BATCH_TOKENS = 4
_THROTTLE_INTERVAL = 0.5
_MOOD_DRIFT_SECONDS = 60.0

# Production tick resilience: retry a tick's *transient* LLM/network blips with
# bounded exponential backoff (BEAD-04) before isolating whatever it ultimately
# raises, so a momentary hiccup never silently skips an idle tick.
_TICK_RETRY_POLICY = RetryPolicy()

# The reply tier (Tier 1) is the one whose provider drives the capability tool-loop.
_REPLY_TIER = 1

# Where the bob-soul personality templates live (repo root / bob-soul).
_DEFAULT_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "bob-soul"


class SystemClock:
    """Real time source (UTC). Injected so the domain avoids ``datetime.now()``."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


@dataclass
class Application:
    """The assembled, runnable GUPPI process and its wired collaborators.

    Holds the composition result so the entrypoint (and tests) can run lifecycle
    (:meth:`startup` / :meth:`shutdown`) and inspect the bound adapters without
    re-running the wiring.
    """

    config: Mapping[str, object]
    runtime: AgentRuntime
    event_bus: AsyncEventBus
    memory_repo: SqliteMemoryRepo
    soul_store: SoulStore
    genesis: RunGenesis
    personality: PersonalityState
    handle_message: HandleMessage
    multibot: MultiBotGateway
    authorizer: Authorizer
    registry: CapabilityRegistry
    inner_monologue_tick: InnerMonologueTick
    mood_drift_tick: MoodDriftTick
    reflect_tick: ReflectTick

    async def startup(self) -> GenesisResult:
        """Initialise persistence, awaken Bob on first boot, load his soul.

        Idempotent Genesis: the first boot generates the soul (Tier 1) and writes
        ``data/soul/``; every later boot loads the existing soul untouched. The
        loaded soul becomes the live :class:`PersonalityState`.
        """
        await self.memory_repo.initialize()
        result = await self.genesis.run()
        self.personality.soul = _load_soul(self.soul_store)
        return result

    async def shutdown(self) -> None:
        """Stop the runtime and close persistence (idempotent)."""
        await self.runtime.stop()
        await self.memory_repo.close()


def build_application(
    *,
    config_path: Path | None = None,
    config: Mapping[str, object] | None = None,
    providers: Mapping[int, LLMProvider] | None = None,
    bob_bot: BotLike | None = None,
    guppi_bot: BotLike | None = None,
) -> Application:
    """Wire the full two-bot GUPPI graph from configuration into an application.

    ``config`` / ``providers`` / ``bob_bot`` / ``guppi_bot`` are injectable seams:
    when omitted the real adapters are built from config (each bot's token from
    env via ``telegram.bob.token`` / ``telegram.guppi.token``); tests pass fake
    aiogram bots to exercise the whole graph without a network or a Telegram
    account. Bob and GUPPI are registered behind one
    :class:`~bob.infrastructure.telegram.multibot.MultiBotGateway` — Bob scoped to
    his topic thread, GUPPI to General — and one Dispatcher polls both.
    """
    merged = dict(config) if config is not None else ConfigLoader(yaml_path=config_path).load()

    clock = SystemClock()
    event_bus = AsyncEventBus()
    tier_providers = providers if providers is not None else build_tier_providers(merged)
    router = LLMRouter(providers=tier_providers)

    memory_repo = SqliteMemoryRepo(_db_path(merged))
    recall = Fts5MemoryRecall(memory_repo)
    soul_store = SoulStore(_soul_dir(merged))

    # Capability seam (BEAD-05/06): advertise recall_memory to the model so the
    # production tool-loop is active — the model may call it, GUPPI executes it,
    # the result loops back into the reply. The tier-1 reply provider is the
    # tool-calling provider; when it cannot do tools the loop stays dormant and
    # HandleMessage keeps the plain reply path.
    registry = _build_registry(recall)
    tool_provider = _as_tool_provider(tier_providers)

    genesis = RunGenesis(
        templates_dir=_templates_dir(merged),
        router=router,
        soul_store=soul_store,
        clock=clock,
    )

    personality = PersonalityState(soul=_default_soul())
    update_mood = UpdateMoodFromText(router=router, clock=clock)
    extract_facts = ExtractFacts(router=router, repo=memory_repo, clock=clock)
    authorizer = _build_authorizer(merged, repo=memory_repo)
    multibot = _build_multibot(
        merged,
        bus=event_bus,
        bob_bot=bob_bot,
        guppi_bot=guppi_bot,
        authorizer=authorizer,
    )

    handle_message = HandleMessage(
        router=router,
        gateway=multibot.reply_streamer(BotIdentity.BOB),
        recall=recall,
        repo=memory_repo,
        episodes=memory_repo,
        update_mood=update_mood,
        extract_facts=extract_facts,
        clock=clock,
        state=personality,
        registry=registry,
        tool_provider=tool_provider,
    )
    event_bus.subscribe(MESSAGE_RECEIVED, _as_handler(handle_message))

    inner_monologue_tick = InnerMonologueTick(router=router, state=personality)
    mood_drift_tick = MoodDriftTick(state=personality)
    reflect_tick = ReflectTick(
        router=router, repo=memory_repo, state=personality, clock=clock
    )

    runtime = AgentRuntime(
        background_tasks=_background_tasks(
            merged,
            multibot=multibot,
            inner_monologue_tick=inner_monologue_tick,
            mood_drift_tick=mood_drift_tick,
            reflect_tick=reflect_tick,
        )
    )

    return Application(
        config=merged,
        runtime=runtime,
        event_bus=event_bus,
        memory_repo=memory_repo,
        soul_store=soul_store,
        genesis=genesis,
        personality=personality,
        handle_message=handle_message,
        multibot=multibot,
        authorizer=authorizer,
        registry=registry,
        inner_monologue_tick=inner_monologue_tick,
        mood_drift_tick=mood_drift_tick,
        reflect_tick=reflect_tick,
    )


# --- Wiring helpers -----------------------------------------------------------


def _as_handler(handle_message: HandleMessage) -> EventHandler:
    """Adapt :meth:`HandleMessage.handle` to the EventBus handler signature."""

    async def handler(event: DomainEvent) -> None:
        if isinstance(event, MessageReceived):
            await handle_message.handle(event)

    return handler


def _build_multibot(
    config: Mapping[str, object],
    *,
    bus: AsyncEventBus,
    bob_bot: BotLike | None,
    guppi_bot: BotLike | None,
    authorizer: Authorizer,
) -> MultiBotGateway:
    """Build the two-bot gateway: Bob (his topic) + GUPPI (General), one poller.

    Each bot is injected (a fake in tests) or built from its env token
    (``telegram.bob.token`` / ``telegram.guppi.token``). Bob is scoped to the
    group's Bob topic so his replies pin to that thread; GUPPI owns the General /
    un-threaded scope. The shared :class:`Authorizer` drives GUPPI's reject + the
    owner commands — no duplicated authz.
    """
    telegram = _section(config, "telegram")
    chat_id = _int(telegram, "chat_id", 0)
    bob_section = _section(telegram, "bob")
    registry = BotRegistry()
    registry.register(
        identity=BotIdentity.BOB,
        bot=bob_bot if bob_bot is not None else _build_real_bot(bob_section, "bob"),
        scope=BotScope(chat_id=chat_id, topic_id=_int(bob_section, "topic_id", 0)),
    )
    registry.register(
        identity=BotIdentity.GUPPI,
        bot=(
            guppi_bot
            if guppi_bot is not None
            else _build_real_bot(_section(telegram, "guppi"), "guppi")
        ),
        scope=BotScope(chat_id=chat_id, topic_id=None),
    )
    return MultiBotGateway(
        registry=registry,
        bus=bus,
        poll_timeout=_int(telegram, "poll_timeout", _DEFAULT_POLL_TIMEOUT),
        authorizer=authorizer,
    )


def _build_authorizer(
    config: Mapping[str, object], *, repo: SqliteMemoryRepo
) -> Authorizer:
    """Build the access-policy Authorizer from config over the SQLite allowlist.

    ``owner_id`` and ``allowed_chat_ids`` come from the ``telegram`` config; the
    dynamic allowlist is persisted in the kv store so ``/authorize`` survives a
    restart.
    """
    telegram = _section(config, "telegram")
    return Authorizer(
        owner_id=_int(telegram, "owner_id", 0),
        allowed_chat_ids=_int_list(telegram, "allowed_chat_ids"),
        store=KvAllowlistStore(repo),
    )


def _build_registry(recall: Fts5MemoryRecall) -> CapabilityRegistry:
    """Build the capability registry GUPPI advertises and dispatches.

    Registers the first real capability — ``recall_memory`` (BEAD-06), a thin
    wrapper over the live :class:`MemoryRecall` — so the tool-loop has something
    to call end to end. New skills register here without touching consumers.
    """
    registry = CapabilityRegistry()
    registry.register(make_recall_memory_capability(recall))
    return registry


def _as_tool_provider(
    providers: Mapping[int, LLMProvider],
) -> ToolCallingProvider | None:
    """Pick the reply-tier provider as the tool-calling provider, if it supports it.

    The Tier 1 reply provider (:class:`OpenAICompatProvider`) realises
    :class:`ToolCallingProvider`; a fake or a tool-less endpoint may not, in which
    case the tool-loop stays dormant and HandleMessage keeps the plain path.
    """
    provider = providers.get(_REPLY_TIER)
    if provider is not None and hasattr(provider, "complete_with_tools"):
        # The reply tier advertises complete_with_tools → it can drive the loop.
        return cast("ToolCallingProvider", provider)
    return None


def _build_real_bot(bot_section: Mapping[str, object], identity: str) -> BotLike:
    """Construct a real aiogram ``Bot`` from a bot's configured (env) token.

    ``identity`` (``"bob"`` / ``"guppi"``) only names the missing token in the
    error — the token itself comes from env (``BOB_TELEGRAM__TOKEN`` /
    ``GUPPI_TELEGRAM__TOKEN``), never inlined.
    """
    from aiogram import Bot  # noqa: PLC0415 — lazy: only the real-bot path needs aiogram

    token = bot_section.get("token")
    if not isinstance(token, str) or not token:
        raise KeyError(
            f"telegram.{identity}.token is required to build the real {identity} bot"
        )
    return _AiogramBotAdapter(Bot(token=token))


def _background_tasks(
    config: Mapping[str, object],
    *,
    multibot: MultiBotGateway,
    inner_monologue_tick: InnerMonologueTick,
    mood_drift_tick: MoodDriftTick,
    reflect_tick: ReflectTick,
) -> list[BackgroundTask]:
    """Build the supervised background tasks: polling + the three heartbeat ticks.

    One poll task drives BOTH bots (Bob + GUPPI) through the multi-bot gateway.
    """
    runtime = _section(config, "runtime")
    heartbeat = float(_int(runtime, "heartbeat_seconds", _DEFAULT_HEARTBEAT_SECONDS))

    async def poll() -> None:
        await multibot.poll_once()

    return [
        periodic(poll, interval_seconds=0.0),
        periodic(
            inner_monologue_tick.run,
            interval_seconds=heartbeat,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            mood_drift_tick.run,
            interval_seconds=_MOOD_DRIFT_SECONDS,
            retry=_TICK_RETRY_POLICY,
        ),
        periodic(
            reflect_tick.run,
            interval_seconds=heartbeat * 10,
            retry=_TICK_RETRY_POLICY,
        ),
    ]


def _monotonic() -> float:
    return asyncio.get_event_loop().time()


# --- Soul loading -------------------------------------------------------------


def _load_soul(soul_store: SoulStore) -> SOUL:
    """Build the in-memory :class:`SOUL` from the persisted soul artifacts.

    Falls back to a neutral default if the JSON profiles are absent (a fresh
    install before Genesis has fully written them).
    """
    if not soul_store.soul_exists():
        return _default_soul()
    identity = soul_store.read_soul()
    mood_doc = soul_store.read_json("mood")
    baseline = _mood_from(mood_doc, "baseline")
    current = _mood_from(mood_doc, "current")
    taste = _taste_from(soul_store.read_json("taste_profile"))
    phantoms = _phantoms_from(soul_store.read_json("phantom_prefs"))
    return SOUL(
        identity=identity,
        mood=current,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=phantoms,
    )


def _default_soul() -> SOUL:
    """A neutral starting soul used before Genesis has run."""
    neutral = Mood()
    return SOUL(
        identity="I am Bob, awaiting Genesis.",
        mood=neutral,
        mood_baseline=neutral,
        taste=TasteEngine(),
    )


def _mood_from(doc: object, key: str) -> Mood:
    if not isinstance(doc, Mapping):
        return Mood()
    section = doc.get(key)
    if not isinstance(section, Mapping):
        return Mood()
    return Mood(
        valence=_float(section, "valence"),
        arousal=_float(section, "arousal"),
        openness=_float(section, "openness"),
        social=_float(section, "social"),
        stability=_float(section, "stability"),
    )


def _taste_from(doc: object) -> TasteEngine:
    if not isinstance(doc, Mapping):
        return TasteEngine()
    axes_doc = doc.get("axes")
    if not isinstance(axes_doc, list):
        return TasteEngine()
    axes: list[TasteAxis] = []
    for raw in axes_doc:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str):
            continue
        axes.append(
            TasteAxis(
                name=name,
                value=_float(raw, "value"),
                conviction=_float(raw, "conviction"),
                experience_count=_int(raw, "experience_count", 0),
            )
        )
    return TasteEngine(axes=tuple(axes))


def _phantoms_from(doc: object) -> tuple[str, ...]:
    if not isinstance(doc, Mapping):
        return ()
    prefs = doc.get("preferences")
    if not isinstance(prefs, list):
        return ()
    return tuple(str(p) for p in prefs)


# --- Config readers -----------------------------------------------------------


def _db_path(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "db_path", "data/bob.db"))


def _soul_dir(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "soul_dir", "data/soul"))


def _templates_dir(config: Mapping[str, object]) -> Path:
    genesis = _section(config, "genesis")
    configured = genesis.get("templates_dir")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return _DEFAULT_TEMPLATES_DIR


def _section(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(section: Mapping[str, object], key: str, default: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) and value else default


def _int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _int_list(section: Mapping[str, object], key: str) -> tuple[int, ...]:
    """Read a list of ints from config (YAML list or a CSV env string)."""
    value = section.get(key)
    if isinstance(value, str):
        return tuple(int(part) for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(int(item) for item in value if isinstance(item, int))
    return ()


def _float(section: Mapping[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


# --- aiogram bot adapter ------------------------------------------------------


@dataclass(frozen=True)
class _ChatView:
    """An :class:`UpdateLike` chat view over an aiogram ``Update``."""

    id: int


@dataclass(frozen=True)
class _UserView:
    """An :class:`UpdateLike` user view over an aiogram ``Update``."""

    id: int
    full_name: str


@dataclass(frozen=True)
class _UpdateView:
    """Adapt an aiogram ``Update`` to the gateway's :class:`UpdateLike`.

    aiogram nests chat/sender under ``message``; the gateway reads them as the
    flat ``effective_chat`` / ``effective_user`` accessors, so this view lifts them
    up while leaving the underlying aiogram message as the message.
    """

    update_id: int
    message: MessageLike | None
    effective_chat: _ChatView | None
    effective_user: _UserView | None


class _AiogramBotAdapter:
    """Adapt aiogram's async ``Bot`` to the gateway's :class:`BotLike`.

    Intake calls ``get_updates`` and normalises each aiogram ``Update`` into an
    :class:`UpdateLike`; the streaming reply uses the native ``send_message_draft``
    channel for DM partials, or ``edit_message_text`` (live edit-streaming) plus
    ``delete_message`` for a forum topic, committing the finished reply with
    ``send_message`` / ``send_rich_message``.
    """

    def __init__(self, bot: object) -> None:
        self._bot = bot

    async def get_updates(
        self, *, offset: int, timeout: int
    ) -> Sequence[UpdateLike]:
        updates = await self._bot.get_updates(offset=offset, timeout=timeout)  # type: ignore[attr-defined]
        return [_to_update_view(update) for update in updates]

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None
    ) -> MessageLike:
        return await self._bot.send_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, text=text, message_thread_id=message_thread_id
        )

    async def edit_message_text(
        self, *, chat_id: int, message_id: int, text: str
    ) -> MessageLike | bool:
        return await self._bot.edit_message_text(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, message_id=message_id, text=text
        )

    async def delete_message(self, *, chat_id: int, message_id: int) -> bool:
        return await self._bot.delete_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id, message_id=message_id
        )

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,
    ) -> bool:
        return await self._bot.send_message_draft(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            draft_id=draft_id,
            text=text,
            message_thread_id=message_thread_id,
        )

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> MessageLike:
        return await self._bot.send_rich_message(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            rich_message=rich_message,
            message_thread_id=message_thread_id,
        )

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        rich_message: InputRichMessage,
        message_thread_id: int | None = None,
    ) -> bool:
        return await self._bot.send_rich_message_draft(  # type: ignore[attr-defined,no-any-return]
            chat_id=chat_id,
            draft_id=draft_id,
            rich_message=rich_message,
            message_thread_id=message_thread_id,
        )


def _to_update_view(update: object) -> _UpdateView:
    """Lift an aiogram ``Update``'s nested chat/sender into an :class:`UpdateLike`."""
    message: MessageLike | None = getattr(update, "message", None)
    chat = getattr(message, "chat", None)
    user = getattr(message, "from_user", None)
    return _UpdateView(
        update_id=update.update_id,  # type: ignore[attr-defined]
        message=message,
        effective_chat=_ChatView(id=chat.id) if chat is not None else None,
        effective_user=(
            _UserView(id=user.id, full_name=user.full_name) if user is not None else None
        ),
    )


# --- Entrypoint ---------------------------------------------------------------


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(app: Application) -> None:
    await app.startup()
    await app.runtime.start()
    try:
        await app.runtime.run_until_stopped()
    finally:
        await app.shutdown()


def main(*, config_path: Path | None = None) -> None:
    """Process entrypoint: build the application and run until stopped."""
    app = build_application(config_path=config_path)
    runtime_cfg = _section(app.config, "runtime")
    _configure_logging(_str(runtime_cfg, "log_level", "INFO"))
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
