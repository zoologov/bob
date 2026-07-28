# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance tests for US-3 (memory between sessions) — fakes only, no network.

These exercise the WHOLE wired GUPPI graph (``build_application``) over real
persistence — a temp on-disk SQLite db with the live FTS5 index and the real
:class:`Fts5MemoryRecall` — driving turns through the real ``AsyncEventBus``.
Only the genuinely-external edges are faked: the LLM tiers (a captured provider,
no HTTP) and Telegram (a fake bot, no network).

They assert the product-level US-3 criteria rather than any single unit:

* **In-session memory** — a durable fact stated in one turn is surfaced (via the
  real recall path) into the *shareable* context a LATER turn hands to the Tier 1
  reply provider; Bob remembers within a session.
* **Across restart** — a persisted fact / episode survives a *process restart*,
  modelled by closing the app and building a FRESH application graph on the SAME
  SQLite file; ``recall`` and ``recent_episodes`` still surface it.
* **Fact recall** — an extracted fact in ``semantic_memory`` is found by FTS5
  recall and reaches the reply context.
* **Privacy (reframed invariant)** — ``private_context`` NEVER reaches a Tier 1
  payload, while ``shareable_context`` (conversation/memory) DOES.
* **Robustness** — a Tier 0 fact-extraction failure does not break the turn: the
  reply is still streamed and the episode persisted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.app import Application, build_application
from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.application.runtime.events import MessageReceived
from bob.memory.adapters import Fts5MemoryRecall
from bob.memory.entities import SemanticFact
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike

_TIER1_REPLY = "Got it, I'll remember that."
# A durable fact Tier 0 will "extract" from turn one; later recalled by keyword.
_EXTRACTED_FACT = "the user's name is Vova"
# What Tier 0 returns for the EXTRACT_FACTS call (JSON array of fact objects).
_FACT_JSON = f'[{{"category": "user", "content": "{_EXTRACTED_FACT}"}}]'
# A fact never offered as shareable/recallable — used to prove the privacy seam.
_SECRET = "user secret pin 4321"  # noqa: S105 — test fixture, not a real credential


class SequencedProvider:
    """Fake :class:`LLMProvider` recording payloads, replying in sequence.

    A single Tier 0 provider serves several calls per turn (sentiment, then fact
    extraction); ``replies`` lets each successive call answer differently, and the
    last reply repeats once the script is exhausted. ``payloads`` captures every
    message sent so a test can assert what a tier actually saw.
    """

    def __init__(self, *, reply: str, replies: Sequence[str] | None = None) -> None:
        self._reply = reply
        self._replies = list(replies) if replies is not None else None
        self._call = 0
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        self.payloads.append([dict(m) for m in messages])
        if self._replies is None:
            return self._reply
        index = min(self._call, len(self._replies) - 1)
        self._call += 1
        return self._replies[index]

    @property
    def all_text(self) -> str:
        """Every message content this provider ever received, concatenated."""
        return "\n".join(m["content"] for payload in self.payloads for m in payload)


class FakeMessage:
    """A minimal Telegram message carrying the placeholder's id."""

    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


class FakeBot:
    """Fake Telegram bot capturing the streamed reply (no network)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.typings: int = 0

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None,  # noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=999)

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
        message_thread_id: int | None = None,# noqa: ARG002
        reply_parameters: object = None,  # noqa: ARG002
    ) -> FakeMessage:
        # BOB-008 (Variant A): the committed reply lands via the rich channel.
        self.sent.append((chat_id, getattr(rich_message, "markdown", "")))
        return FakeMessage(message_id=999)

    async def send_photo(
        self,
        *,
        chat_id: int,
        photo: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> FakeMessage:
        # BOB-035: BotLike parity; this fake's tests never post a photo.
        raise NotImplementedError  # pragma: no cover

    async def send_document(
        self,
        *,
        chat_id: int,
        document: object,
        caption: str | None = None,
        message_thread_id: int | None = None,
    ) -> FakeMessage:
        # BOB-037: BotLike parity; this fake's tests never post a document.
        raise NotImplementedError  # pragma: no cover

    @property
    def final_text(self) -> str:
        """The committed reply text (full streamed reply sent via send_message)."""
        return self.sent[-1][1] if self.sent else ""


def _config(tmp_path: Path) -> dict[str, object]:
    """Config pointing persistence at the temp dir; heartbeat off (no ticks)."""
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        "telegram": {
            "poll_timeout": 1,
            # The stable sender (id 7, chat 42) is the trusted OWNER so the wired
            # SenderPerception (BOB-019) classifies him TRUSTED — recall + fact
            # extraction run as usual (a guest would have them redacted away).
            "owner_id": 7,
            "allowed_chat_ids": [42],
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    """Pre-write a SOUL so Genesis is a no-op (acceptance focus is memory, not awakening)."""
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


def _build_app(
    tmp_path: Path,
    *,
    bot: FakeBot,
    tier0: SequencedProvider,
    tier1: SequencedProvider,
) -> Application:
    """Wire the whole graph on the temp db with the given fakes."""
    return build_application(
        config=_config(tmp_path),
        providers={0: tier0, 1: tier1},
        bob_bot=bot,
        guppi_bot=bot,
    )


def _message(text: str, *, update_id: int = 1, message_id: int = 1) -> MessageReceived:
    """A received Telegram message from a stable sender."""
    return MessageReceived(
        update_id=update_id,
        chat_id=42,
        message_id=message_id,
        text=text,
        sender_id=7,
        sender_name="Vova",
    )


# --- In-session memory --------------------------------------------------------


async def test_fact_stated_in_one_turn_reaches_a_later_turns_reply_context(
    tmp_path: Path,
) -> None:
    # Arrange: full graph on a temp db. Tier 0 answers sentiment then, on the
    # extraction call, returns one durable fact (the user's name).
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive", replies=["positive", _FACT_JSON])
    tier1 = SequencedProvider(reply=_TIER1_REPLY)
    bot = FakeBot()
    app = _build_app(tmp_path, bot=bot, tier0=tier0, tier1=tier1)
    await app.startup()

    # Act 1: the user states their name — Tier 0 extracts it into semantic memory.
    await app.event_bus.publish(_message("my name is Vova", update_id=1, message_id=1))
    # Act 2: a LATER turn asks about it; recall (real FTS5) must surface the fact.
    tier1_before = len(tier1.payloads)
    # A complex (depth-keyword) probe so the hybrid selector escalates to Tier 1.
    await app.event_bus.publish(
        _message("объясни подробно, как меня зовут?", update_id=2, message_id=2)
    )

    # Assert: the stated fact reached the SECOND turn's Tier 1 reply context, so
    # within the session Bob remembers a fact from an earlier turn.
    second_turn_text = "\n".join(
        m["content"] for payload in tier1.payloads[tier1_before:] for m in payload
    )
    assert _EXTRACTED_FACT in second_turn_text

    await app.shutdown()


# --- Across restart -----------------------------------------------------------


async def test_fact_survives_a_process_restart_and_is_recalled(tmp_path: Path) -> None:
    # Arrange: first "process" persists a durable fact, then shuts down.
    _seed_soul(tmp_path)
    first = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive"),
        tier1=SequencedProvider(reply=_TIER1_REPLY),
    )
    await first.startup()
    await first.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="user", content=_EXTRACTED_FACT)
    )
    await first.shutdown()

    # Act: a FRESH application graph on the SAME SQLite file (process restart).
    second = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive"),
        tier1=SequencedProvider(reply=_TIER1_REPLY),
    )
    await second.startup()
    recalled = await _recall(second, "Vova")

    # Assert: the fact persisted by the previous process is recalled by the new one.
    assert any(_EXTRACTED_FACT in str(item.get("content", "")) for item in recalled)

    await second.shutdown()


async def test_episode_survives_a_process_restart(tmp_path: Path) -> None:
    # Arrange: first process handles a full turn (persists an episode), then exits.
    _seed_soul(tmp_path)
    first = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive"),
        tier1=SequencedProvider(reply=_TIER1_REPLY),
    )
    await first.startup()
    await first.event_bus.publish(_message("hello Bob, remember this chat"))
    await first.shutdown()

    # Act: a fresh graph on the same db reads recent conversation history.
    second = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive"),
        tier1=SequencedProvider(reply=_TIER1_REPLY),
    )
    await second.startup()
    history = await second.memory_repo.recent_episodes(5)

    # Assert: the earlier turn's episode survived the restart and is replayable.
    assert any("remember this chat" in str(e.get("content", "")) for e in history)

    await second.shutdown()


# --- Fact recall through the reply path ---------------------------------------


async def test_extracted_fact_in_semantic_memory_reaches_the_reply_context(
    tmp_path: Path,
) -> None:
    # Arrange: a pre-existing semantic fact (as the extractor would have written).
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive")
    tier1 = SequencedProvider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()
    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="user", content=_EXTRACTED_FACT)
    )

    # Act: a complex turn whose keywords match the stored fact (real FTS5 recall);
    # the depth keyword escalates the reply to Tier 1.
    await app.event_bus.publish(_message("расскажи подробно про Vova"))

    # Assert: the recalled fact reached the Tier 1 reply context.
    assert _EXTRACTED_FACT in tier1.all_text

    await app.shutdown()


# --- Privacy (reframed invariant) ---------------------------------------------


async def test_shareable_memory_reaches_tier1_but_private_context_never_does(
    tmp_path: Path,
) -> None:
    # Arrange: a recallable (shareable) fact is stored; a separate private secret
    # is pushed only through the router's private_context channel.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive")
    tier1 = SequencedProvider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()
    await app.memory_repo.save_fact(
        SemanticFact(ts=datetime.now(tz=UTC), category="user", content=_EXTRACTED_FACT)
    )

    # Act: a complex reply turn (matches the shareable fact by keyword) — the
    # depth keyword escalates the reply to Tier 1 ...
    await app.event_bus.publish(_message("расскажи подробно про Vova"))
    # ... and a crafted reply request carrying a private_context secret.
    private_tier1 = SequencedProvider(reply=_TIER1_REPLY)
    router = LLMRouter(providers={0: SequencedProvider(reply="x"), 1: private_tier1})
    await router.run(
        LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[{"role": "user", "content": "what is my pin?"}],
            shareable_context="ok to share",
            private_context=_SECRET,
        )
    )

    # Assert: shareable memory DID reach Tier 1; the private secret NEVER did.
    assert _EXTRACTED_FACT in tier1.all_text
    assert _SECRET not in private_tier1.all_text
    assert "ok to share" in private_tier1.all_text

    await app.shutdown()


# --- Robustness ---------------------------------------------------------------


async def test_fact_extraction_failure_does_not_break_the_turn(tmp_path: Path) -> None:
    # Arrange: Tier 0 returns prose (not a JSON array) on the extraction call, so
    # extraction yields no fact — but the turn has already replied.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(
        reply="positive", replies=["positive", "sorry, I can't do JSON today"]
    )
    tier1 = SequencedProvider(reply=_TIER1_REPLY)
    bot = FakeBot()
    app = _build_app(tmp_path, bot=bot, tier0=tier0, tier1=tier1)
    await app.startup()

    # Act: a complex message escalates the reply to Tier 1.
    await app.event_bus.publish(_message("объясни подробно правила игры"))

    # Assert: the reply still streamed out and the episode persisted; no fact stored.
    assert bot.final_text == _TIER1_REPLY
    episodes = await app.memory_repo.load_episodes(limit=10)
    assert any("объясни подробно правила игры" in str(e["content"]) for e in episodes)
    assert await app.memory_repo.load_facts(limit=10) == []

    await app.shutdown()


async def _recall(app: Application, query: str) -> Sequence[Mapping[str, object]]:
    """Recall through the app's real FTS5 recall adapter (rebuilt per build)."""
    recall = Fts5MemoryRecall(app.memory_repo)
    return await recall.recall(query, k=5)
