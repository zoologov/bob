# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Acceptance: realistic memory + reasoning-model output over the wired graph.

These exercise the WHOLE wired GUPPI graph (``build_application``) on a real
temp SQLite db with the live FTS5 indexes, the real :class:`Fts5MemoryRecall`,
the real :class:`LLMRouter`, and the real ``AsyncEventBus``. Only the genuinely
external edges are faked — the LLM tiers and the Telegram bot — and crucially the
fakes mimic the *real output shapes* of a reasoning model (markdown-fenced /
prose-wrapped JSON; slow, large, content-bearing replies; null-content), the gap
that previously bit production.

Coverage of the landed fixes, at the product level:

* **BEAD-18 (whole-archive recall + backfill).** A fact stated MANY turns before
  the query is surfaced by ``recall`` *from the episodic archive* (not from the
  short recency window) and reaches the Tier 1 reply context; and a db whose
  episodes predate the episodic FTS index becomes searchable after
  ``initialize()`` runs the backfill.
* **BEAD-19 (robust fact parsing).** A Tier 0 fake returning a markdown-fenced or
  prose-wrapped JSON array still lands facts in ``semantic_memory``, later
  surfaced by recall.
* **BEAD-20 (Tier 1 reasoning acceptance).** A fake provider mimicking a
  reasoning model (slow, large, content present) drives the reply via Tier 1 with
  no spurious fallback; null content degrades gracefully; the disable-thinking
  directive is in the outgoing payload.
* **Cross-restart.** An extracted fact survives a fresh application graph built on
  the same db (a process restart).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from bob.app import Application, build_application
from bob.application.runtime.events import MessageReceived
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider
from bob.infrastructure.persistence import Fts5MemoryRecall, SoulStore, SqliteMemoryRepo

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.infrastructure.telegram.gateway import UpdateLike

# --- The fact a reasoning model "extracts", later recalled by keyword ----------
_OLD_FACT_NAME = "Vova"
_OLD_FACT_TEXT = f"my name is {_OLD_FACT_NAME} and I love deep-space probes"
_TIER1_REPLY = "Got it — I'll keep that in mind."

# How a real reasoning model wraps a JSON array of facts: a chain-of-thought
# preamble, then a fenced ```json block. Parsing must recover the array.
_FACT_CONTENT = f"the user's name is {_OLD_FACT_NAME}"
_FENCED_FACT_JSON = (
    "Let me think about what is durable here. The user told me their name, "
    "which is a stable user fact worth keeping. Other content is small talk.\n\n"
    "```json\n"
    f'[{{"category": "user", "content": "{_FACT_CONTENT}"}}]\n'
    "```\n"
)
_PROSE_FACT_JSON = (
    "Reasoning: the only durable, user-specific fact is the user's name. "
    f'Here is the result: [{{"category": "user", "content": "{_FACT_CONTENT}"}}] '
    "— and that's all I found."
)


class SequencedProvider:
    """Fake :class:`LLMProvider` recording payloads, replying in sequence.

    A single Tier 0 provider serves several calls per turn (sentiment, then fact
    extraction); ``replies`` lets each successive call answer differently and the
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


class ReasoningTier1Provider:
    """Fake Tier 1 that mimics a real reasoning model: slow, large, content-bearing.

    Records every payload, simulates per-call latency (so a too-tight timeout
    would have surfaced as a failure) and returns a long, content-present reply —
    the shape that must NOT trigger the Tier 1 -> Tier 0 fallback.
    """

    def __init__(self, *, reply: str, latency: float = 0.0) -> None:
        self._reply = reply
        self._latency = latency
        self.payloads: list[list[dict[str, str]]] = []
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        self.payloads.append([dict(m) for m in messages])
        if self._latency:
            await asyncio.sleep(self._latency)
        return self._reply

    @property
    def all_text(self) -> str:
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
        self.drafts: list[tuple[int, int, str]] = []

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> FakeMessage:
        self.sent.append((chat_id, text))
        return FakeMessage(message_id=999)

    async def send_message_draft(
        self,
        *,
        chat_id: int,
        draft_id: int,
        text: str,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        self.drafts.append((chat_id, draft_id, text))
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        rich_message: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> FakeMessage:
        return FakeMessage(message_id=999)

    async def send_rich_message_draft(
        self,
        *,
        chat_id: int,  # noqa: ARG002
        draft_id: int,  # noqa: ARG002
        rich_message: object,  # noqa: ARG002
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> bool:
        return True

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
            "bob": {"token": "bob-tok", "topic_id": 0},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    """Pre-write a SOUL so Genesis is a no-op (focus is memory, not awakening)."""
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
    tier1: SequencedProvider | ReasoningTier1Provider,
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


# --- BEAD-18: old-fact recall via whole-archive episodic search ---------------


async def test_old_fact_from_many_turns_ago_is_recalled_and_reaches_tier1(
    tmp_path: Path,
) -> None:
    # Arrange: an OLD turn stated the user's name, then MANY later turns buried it
    # far outside the short recency window the reply replays. Only a search over
    # the whole episodic archive (Fix A) can surface it.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive")
    tier1 = ReasoningTier1Provider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()

    base = datetime(2026, 1, 1, tzinfo=UTC)
    # The fact-bearing episode, long ago.
    await app.memory_repo.save_episode(
        {
            "ts": base.isoformat(),
            "event_type": "message",
            "content": f"Vova: {_OLD_FACT_TEXT}\nbob: noted",
            "mood_snapshot": "calm",
            "tags": "telegram",
        }
    )
    # 20 filler turns AFTER it (more recent), none mentioning the name, so the
    # fact falls outside the 6-turn recency replay window.
    for i in range(1, 21):
        await app.memory_repo.save_episode(
            {
                "ts": (base + timedelta(minutes=i)).isoformat(),
                "event_type": "message",
                "content": f"Vova: filler chatter {i}\nbob: ok {i}",
                "mood_snapshot": "calm",
                "tags": "telegram",
            }
        )

    # Act: a query keyed by the old name; FTS5 must dig it out of the archive.
    recalled = await _recall(app, _OLD_FACT_NAME)
    # And drive a full turn so the recalled OLD episode reaches the reply context.
    tier1_before = len(tier1.payloads)
    await app.event_bus.publish(_message("remind me, what is my name?", update_id=99))

    # Assert: recall surfaced the OLD episodic turn (proving whole-archive search),
    # and it reached the Tier 1 reply context — Bob remembers across the whole convo.
    assert any(_OLD_FACT_NAME in str(item.get("content", "")) for item in recalled), (
        "old episode not surfaced by whole-archive recall"
    )
    assert any(item.get("source") == "episodic" for item in recalled)
    turn_text = "\n".join(
        m["content"] for payload in tier1.payloads[tier1_before:] for m in payload
    )
    assert _OLD_FACT_NAME in turn_text

    await app.shutdown()


async def test_pre_fts_episodes_become_searchable_after_initialize_backfill(
    tmp_path: Path,
) -> None:
    # Arrange: simulate a db written BEFORE the episodic FTS index existed — insert
    # an episode straight into episodic_log with the FTS sync trigger removed, so
    # the row is invisible to recall until the boot-time backfill reindexes it.
    _seed_soul(tmp_path)
    db_path = tmp_path / "bob.db"
    legacy = SqliteMemoryRepo(db_path)
    await legacy.initialize()
    conn = legacy.connection
    await conn.execute("DROP TRIGGER IF EXISTS episodic_fts_ai")
    await conn.execute(
        "INSERT INTO episodic_log (ts, event_type, content, mood_snapshot, tags) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            datetime(2025, 12, 1, tzinfo=UTC).isoformat(),
            "message",
            f"Vova: legacy turn, {_OLD_FACT_TEXT}\nbob: noted",
            None,
            "telegram",
        ),
    )
    await conn.commit()
    # Pre-condition: the legacy row is NOT yet findable (no FTS entry for it).
    stale = await Fts5MemoryRecall(legacy).recall(_OLD_FACT_NAME, k=5)
    assert not any(_OLD_FACT_NAME in str(i.get("content", "")) for i in stale)
    await legacy.close()

    # Act: a FRESH app boots on the SAME db; startup()'s initialize() backfills the
    # episodic FTS index from the base table.
    tier0 = SequencedProvider(reply="positive")
    tier1 = ReasoningTier1Provider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()

    # Assert: the pre-FTS episode is now searchable.
    recalled = await _recall(app, _OLD_FACT_NAME)
    assert any(_OLD_FACT_NAME in str(i.get("content", "")) for i in recalled)

    await app.shutdown()


# --- BEAD-19: extraction robust to reasoning-model output shapes ---------------


async def test_fenced_json_extraction_lands_fact_and_is_recalled(tmp_path: Path) -> None:
    # Arrange: Tier 0's extraction call returns a chain-of-thought preamble + a
    # ```json fenced array — the real reasoning-model shape robust parsing handles.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive", replies=["positive", _FENCED_FACT_JSON])
    tier1 = ReasoningTier1Provider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()

    # Act: a turn that triggers extraction, then a later turn whose keywords
    # ("name") match the stored fact content so semantic recall fires.
    await app.event_bus.publish(_message(_OLD_FACT_TEXT, update_id=1, message_id=1))
    tier1_before = len(tier1.payloads)
    await app.event_bus.publish(_message("remind me of my name please", update_id=2, message_id=2))

    # Assert: the fenced fact was parsed into semantic memory and recalled into reply.
    facts = await app.memory_repo.load_facts(limit=10)
    assert any(_FACT_CONTENT in str(f["content"]) for f in facts)
    assert any(f["category"] == "user" for f in facts)
    recalled = await _recall(app, "name")
    assert any(
        item.get("source") == "semantic" and _FACT_CONTENT in str(item.get("content", ""))
        for item in recalled
    )
    second_turn = "\n".join(
        m["content"] for payload in tier1.payloads[tier1_before:] for m in payload
    )
    assert _FACT_CONTENT in second_turn

    await app.shutdown()


async def test_prose_wrapped_json_extraction_lands_fact(tmp_path: Path) -> None:
    # Arrange: Tier 0 returns a JSON array embedded in surrounding prose (preamble
    # AND trailing text) — robust parsing must dig out the balanced array.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive", replies=["positive", _PROSE_FACT_JSON])
    tier1 = ReasoningTier1Provider(reply=_TIER1_REPLY)
    app = _build_app(tmp_path, bot=FakeBot(), tier0=tier0, tier1=tier1)
    await app.startup()

    # Act
    await app.event_bus.publish(_message(_OLD_FACT_TEXT))

    # Assert: the embedded fact was extracted despite the prose wrapping.
    facts = await app.memory_repo.load_facts(limit=10)
    assert any(_FACT_CONTENT in str(f["content"]) for f in facts)

    await app.shutdown()


# --- BEAD-20: Tier 1 reasoning-model acceptance --------------------------------


async def test_reasoning_tier1_reply_is_used_with_no_spurious_fallback(
    tmp_path: Path,
) -> None:
    # Arrange: a Tier 1 that behaves like a slow, large reasoning model with
    # content present; Tier 0's reply differs so a fallback would be detectable.
    _seed_soul(tmp_path)
    long_reply = "Ah, " + "deep-space probes are wonderful companions, " * 20 + "truly."
    tier0 = SequencedProvider(reply="TIER0_FALLBACK_MARKER")
    tier1 = ReasoningTier1Provider(reply=long_reply, latency=0.01)
    bot = FakeBot()
    app = _build_app(tmp_path, bot=bot, tier0=tier0, tier1=tier1)
    await app.startup()

    # Act
    await app.event_bus.publish(_message("tell me about probes"))

    # Assert: the streamed reply is the Tier 1 reasoning output, not the Tier 0
    # fallback marker — Tier 1 was used and did NOT spuriously fall back.
    assert bot.final_text == long_reply
    assert tier1.calls == 1
    assert "TIER0_FALLBACK_MARKER" not in bot.final_text

    await app.shutdown()


async def test_reasoning_tier1_null_content_degrades_gracefully(tmp_path: Path) -> None:
    # Arrange: a reasoning model that spent its budget on reasoning_content and
    # returned empty user-visible content. The provider's tolerant content handling
    # degrades to "" (no error) so the turn completes and persists.
    _seed_soul(tmp_path)
    tier0 = SequencedProvider(reply="positive")
    tier1 = ReasoningTier1Provider(reply="")  # empty content, structurally valid
    bot = FakeBot()
    app = _build_app(tmp_path, bot=bot, tier0=tier0, tier1=tier1)
    await app.startup()

    # Act
    await app.event_bus.publish(_message("anything new?"))

    # Assert: no crash; the turn still persisted an episode and snapshotted mood.
    episodes = await app.memory_repo.load_episodes(limit=10)
    assert any("anything new?" in str(e["content"]) for e in episodes)
    assert await app.memory_repo.get_mood() is not None

    await app.shutdown()


async def test_disable_thinking_directive_in_real_provider_payload() -> None:
    # Arrange: the REAL OpenAI-compatible provider with disable-thinking on (the
    # boot config sets it for reasoning models). Capture the outgoing JSON payload
    # at the aiohttp boundary without any network.
    captured: dict[str, object] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        async def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "ok"}}]}

        async def __aenter__(self) -> _Resp:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class _Session:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def post(self, _url: str, *, json: dict[str, object], headers: dict[str, str]) -> _Resp:
            captured.update(json)
            captured["__headers__"] = headers
            return _Resp()

        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    provider = OpenAICompatProvider(
        base_url="https://api.example/v1",
        model="qwen-reasoner",
        api_key="sk-test",
        disable_thinking=True,
    )

    # Act: complete once with the aiohttp session monkeypatched to capture payload.
    import aiohttp  # noqa: PLC0415 — local import to monkeypatch the session class

    original = aiohttp.ClientSession
    aiohttp.ClientSession = _Session  # type: ignore[misc,assignment]
    try:
        result = await provider.complete([{"role": "user", "content": "hi"}], stream=False)
    finally:
        aiohttp.ClientSession = original  # type: ignore[misc]

    # Assert: the no-thinking directive rode along in BOTH passthrough shapes.
    assert result == "ok"
    assert captured.get("extra_body") == {"enable_thinking": False}
    assert captured.get("chat_template_kwargs") == {"enable_thinking": False}


# --- Cross-restart -------------------------------------------------------------


async def test_extracted_fact_survives_restart_and_is_recalled(tmp_path: Path) -> None:
    # Arrange: first "process" extracts a fact from a fenced reasoning reply, then
    # shuts down.
    _seed_soul(tmp_path)
    first = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive", replies=["positive", _FENCED_FACT_JSON]),
        tier1=ReasoningTier1Provider(reply=_TIER1_REPLY),
    )
    await first.startup()
    await first.event_bus.publish(_message(_OLD_FACT_TEXT))
    assert any(
        _FACT_CONTENT in str(f["content"]) for f in await first.memory_repo.load_facts(limit=10)
    )
    await first.shutdown()

    # Act: a FRESH application graph on the SAME db (process restart).
    second = _build_app(
        tmp_path,
        bot=FakeBot(),
        tier0=SequencedProvider(reply="positive"),
        tier1=ReasoningTier1Provider(reply=_TIER1_REPLY),
    )
    await second.startup()
    recalled = await _recall(second, _OLD_FACT_NAME)

    # Assert: the previously-extracted fact is recalled by the new process.
    assert any(_FACT_CONTENT in str(i.get("content", "")) for i in recalled)

    await second.shutdown()


async def _recall(app: Application, query: str) -> Sequence[Mapping[str, object]]:
    """Recall through the app's real FTS5 recall adapter (rebuilt per build)."""
    recall = Fts5MemoryRecall(app.memory_repo)
    return await recall.recall(query, k=5)
