# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""BOB-011 BEAD-06 integration + e2e: hybrid memory wired into the composition root.

These tests prove that ``bob.app.build_application`` now assembles Bob's memory as a
HYBRID (semantic + keyword) recall — over fakes at the external edges only: a fake
:class:`~bob.domain.ports.Embedder` (no Ollama), an optional fake reranker, fake LLM
providers (no network), a real temp SQLite (real persistence + sqlite-vec). They
assert:

* a semantically-related-but-no-shared-keyword fact is recalled via the vector half
  (pure FTS5 keyword recall would miss it) — US-1;
* the agentic ``search_memory`` tool-loop runs end to end (the model calls it → the
  hybrid recall answers → the result lands in Bob's reply) — US-2;
* with the embedder made unavailable at runtime (Ollama down), recall degrades to
  pure FTS5 keyword and the app still answers — the graceful-fallback contract;
* ``build_application`` does NOT hard-fail when the embedder cannot be built (the app
  must still START with memory degraded to keyword-only).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.app import build_application
from bob.application.runtime.events import MessageReceived
from bob.capabilities.ports import ToolCall, ToolCallResult
from bob.memory.adapters import HybridMemoryRecall
from bob.memory.entities import SemanticFact
from bob.social.adapters.soul_store import SoulStore
from tests.support.judge_stub import JUDGE_REPLY, is_judge_request

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

    from bob.capabilities.ports import ToolDefinition
    from bob.infrastructure.telegram.gateway import UpdateLike
    from bob.kernel.ports import LLMProvider
    from bob.memory.ports import Recalled

_OWNER = 1
_CHAT = 100
_TOPIC = 32
# The sqlite-vec ``memory_vec`` table fixes BGE-M3's 1024-dim vectors in schema.sql,
# so the fake embedder must match — concept buckets live at fixed low indices.
_DIM = 1024

# A fact phrased so it shares NO keyword with the query below — only meaning. Pure
# FTS5 cannot bridge "spacecraft"/"interstellar" to the query word "зонды"; the
# vector half (concept-keyed FakeEmbedder) can.
_SEMANTIC_FACT = "the owner is captivated by interstellar spacecraft"
_SEMANTIC_QUERY = "что я думаю про зонды"
_PLAIN_REPLY = "Hey, good to hear from you!"

# Concept buckets the FakeEmbedder routes text into: any text containing one of a
# bucket's trigger words gets that bucket's one-hot vector, so a fact and a query
# about the SAME concept land on the SAME vector (cosine-near) without sharing words.
_CONCEPTS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (0, ("spacecraft", "interstellar", "probe", "зонд")),
    (1, ("cooking", "recipe", "kitchen")),
)


class FakeEmbedder:
    """Deterministic concept-keyed embedder: same concept -> same one-hot vector.

    A real BGE-M3 maps semantically-near text to near vectors; this fake captures
    just enough of that for the e2e — text mentioning a shared concept (across
    languages / synonyms) gets the same one-hot bucket vector, so vector KNN finds a
    fact by meaning even with zero keyword overlap. Unknown text gets the zero
    vector (no semantic neighbours).
    """

    def __init__(self, *, dim: int = _DIM) -> None:
        self._dim = dim

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        lowered = text.lower()
        for index, triggers in _CONCEPTS:
            if any(trigger in lowered for trigger in triggers):
                vector[index] = 1.0
        return vector


class _BrokenEmbedder:
    """Embedder that always fails — stands in for Ollama being down at runtime."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:  # noqa: ARG002
        raise ConnectionError("ollama unavailable")


class _IdentityReranker:
    """Fake reranker that records its calls and returns candidates unchanged."""

    def __init__(self) -> None:
        self.calls = 0

    async def rerank(
        self, query: str, candidates: Sequence[Recalled]  # noqa: ARG002
    ) -> list[Recalled]:
        self.calls += 1
        return list(candidates)


# --- Fakes at the external edges (no network, no Telegram) --------------------


class _Provider:
    def __init__(self, *, reply: str) -> None:
        self.reply = reply

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        if is_judge_request(messages):  # BOB-049: model the judge choosing REPLY
            return JUDGE_REPLY
        return self.reply


class _SearchMemoryTier1:
    """Tier-1 fake that calls ``search_memory`` once, then quotes its result back."""

    def __init__(self, *, plain_reply: str) -> None:
        self.plain_reply = plain_reply
        self.tool_calls_seen = 0
        self.last_tool_result = ""

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        return self.plain_reply

    async def complete_with_tools(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        if self.tool_calls_seen == 0:
            assert any(_tool_name(tool) == "search_memory" for tool in tools), (
                "search_memory must be advertised in the manifest"
            )
            self.tool_calls_seen += 1
            return ToolCallResult(
                text="",
                tool_calls=(
                    ToolCall(
                        id="s1",
                        name="search_memory",
                        arguments={"query": _SEMANTIC_QUERY},
                    ),
                ),
            )
        self.last_tool_result = str(messages[-1].get("content", ""))
        return ToolCallResult(text=f"From memory: {self.last_tool_result}", tool_calls=())


def _tool_name(tool: ToolDefinition) -> str:
    function = tool.get("function")
    if isinstance(function, Mapping):
        name = function.get("name")
        if isinstance(name, str):
            return name
    return ""


class _FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id
        self.text: str | None = None
        self.message_thread_id: int | None = None


class _FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.rich_sent: list[tuple[int, str]] = []
        self._next_id = 1

    async def get_updates(self, *, offset: int, timeout: int) -> Sequence[UpdateLike]:  # noqa: ARG002
        return []

    async def send_message(
        self, *, chat_id: int, text: str, message_thread_id: int | None = None  # noqa: ARG002
    ) -> _FakeMessage:
        self.sent.append((chat_id, text))
        message_id = self._next_id
        self._next_id += 1
        return _FakeMessage(message_id=message_id)

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
        return True

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,  # noqa: ARG002
    ) -> _FakeMessage:
        self.rich_sent.append((chat_id, _rich_markdown(rich_message)))
        return _FakeMessage(message_id=999)

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

    @property
    def final_text(self) -> str:
        if self.rich_sent:
            return self.rich_sent[-1][1]
        return self.sent[-1][1] if self.sent else ""


def _rich_markdown(rich_message: object) -> str:
    markdown = getattr(rich_message, "markdown", "")
    return markdown if isinstance(markdown, str) else ""


def _config(tmp_path: Path) -> dict[str, object]:
    return {
        "runtime": {"log_level": "INFO", "heartbeat_seconds": 0},
        "llm": {
            "tier0_base_url": "http://localhost:8080/v1",
            "tier0_model": "tier0",
            "tier1_base_url": "https://api.example/v1",
            "tier1_model": "tier1",
            "tier1_api_key": "sk-test",
        },
        # Match the FakeEmbedder's dimension so the vector store schema agrees.
        "embeddings": {"base_url": "http://localhost:11434", "model": "fake", "dim": _DIM},
        "telegram": {
            "poll_timeout": 1,
            "chat_id": _CHAT,
            "owner_id": _OWNER,
            "allowed_chat_ids": [_CHAT],
            "bob": {"token": "bob-tok", "topic_id": _TOPIC},
            "guppi": {"token": "guppi-tok"},
        },
        "persistence": {
            "db_path": str(tmp_path / "bob.db"),
            "soul_dir": str(tmp_path / "soul"),
        },
    }


def _seed_soul(tmp_path: Path) -> None:
    store = SoulStore(tmp_path / "soul")
    store.write_soul("# SOUL\n\nI am the Bob from the book.\n")
    zero = {"valence": 0.0, "arousal": 0.0, "openness": 0.0, "social": 0.0, "stability": 0.0}
    store.write_json("mood", {"baseline": zero, "current": zero})
    store.write_json("taste_profile", {"axes": []})
    store.write_json("phantom_prefs", {"preferences": []})


# --- Tests --------------------------------------------------------------------


async def test_build_application_wires_hybrid_recall(tmp_path: Path) -> None:
    # Arrange / Act: the composition root now builds the hybrid recall.
    app = build_application(
        config=_config(tmp_path),
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
        embedder=FakeEmbedder(),
    )

    # Assert: the live recall is the hybrid, not the keyword-only Fts5MemoryRecall.
    assert isinstance(app.handle_message._recall, HybridMemoryRecall)


async def test_registry_advertises_search_memory(tmp_path: Path) -> None:
    # Arrange / Act
    app = build_application(
        config=_config(tmp_path),
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
        embedder=FakeEmbedder(),
    )

    # Assert: search_memory (the agentic skill) is advertised alongside recall_memory.
    names = [_tool_name(tool) for tool in app.registry.manifest()]
    assert "search_memory" in names
    assert "recall_memory" in names


async def test_semantic_fact_recalled_without_shared_keyword(tmp_path: Path) -> None:
    # Arrange: a fact phrased with NO keyword overlap with the query — only meaning.
    _seed_soul(tmp_path)
    embedder = FakeEmbedder()
    app = build_application(
        config=_config(tmp_path),
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
        embedder=embedder,
    )
    await app.startup()
    try:
        await app.memory_repo.save_fact(
            SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_SEMANTIC_FACT)
        )

        # Act: recall with a query that shares NO word with the fact.
        hits = list(await app.handle_message._recall.recall(_SEMANTIC_QUERY, k=5))
    finally:
        await app.shutdown()

    # Assert: the semantic (vector) half surfaced it — keyword-only FTS5 would miss.
    assert any(_SEMANTIC_FACT in str(hit["content"]) for hit in hits)


async def test_search_memory_tool_loop_end_to_end(tmp_path: Path) -> None:
    # Arrange: the agentic search_memory + a tool-calling tier 1 + a semantic fact.
    _seed_soul(tmp_path)
    tier1 = _SearchMemoryTier1(plain_reply=_PLAIN_REPLY)
    providers: dict[int, LLMProvider] = {0: _Provider(reply="positive"), 1: tier1}
    bot = _FakeBot()
    app = build_application(
        config=_config(tmp_path),
        providers=providers,
        bob_bot=bot,
        guppi_bot=_FakeBot(),
        embedder=FakeEmbedder(),
    )
    await app.startup()
    try:
        await app.memory_repo.save_fact(
            SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_SEMANTIC_FACT)
        )

        # Act: the model decides to search its own memory; GUPPI executes the skill.
        await app.event_bus.publish(_message())
    finally:
        await app.shutdown()

    # Assert: search_memory ran, its hybrid result fed back, and the reply quotes it.
    assert tier1.tool_calls_seen == 1
    assert _SEMANTIC_FACT in tier1.last_tool_result
    assert _SEMANTIC_FACT in bot.final_text


async def test_recall_falls_back_to_keyword_when_embedder_unavailable(
    tmp_path: Path,
) -> None:
    # Arrange: the embedder fails at runtime (Ollama down). The app must still start
    # and recall must degrade to pure FTS5 keyword.
    _seed_soul(tmp_path)
    app = build_application(
        config=_config(tmp_path),
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
        embedder=_BrokenEmbedder(),
    )
    await app.startup()
    try:
        await app.memory_repo.save_fact(
            SemanticFact(ts=datetime.now(tz=UTC), category="personal", content="зонды are great")
        )

        # Act: a keyword query still works (semantic half degraded, FTS5 carries it).
        hits = list(await app.handle_message._recall.recall("зонды", k=5))
    finally:
        await app.shutdown()

    # Assert: keyword recall surfaced the fact despite the broken embedder.
    assert any("зонды" in str(hit["content"]) for hit in hits)


async def test_build_application_starts_without_embedder_config(tmp_path: Path) -> None:
    # Arrange: a config with NO embeddings section — build_application must NOT
    # hard-fail; memory degrades to keyword-only and the app still starts.
    _seed_soul(tmp_path)
    config = _config(tmp_path)
    del config["embeddings"]
    app = build_application(
        config=config,
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
    )
    await app.startup()
    try:
        await app.memory_repo.save_fact(
            SemanticFact(ts=datetime.now(tz=UTC), category="personal", content="зонды rule")
        )

        # Act: keyword recall still works with no embedder at all.
        hits = list(await app.handle_message._recall.recall("зонды", k=5))
    finally:
        await app.shutdown()

    # Assert: the app booted (hybrid recall, embedder None) and keyword recall works.
    assert isinstance(app.handle_message._recall, HybridMemoryRecall)
    assert any("зонды" in str(hit["content"]) for hit in hits)


async def test_reranker_is_wired_when_enabled(tmp_path: Path) -> None:
    # Arrange: an injected reranker is wired into the hybrid recall (additive boost).
    _seed_soul(tmp_path)
    reranker = _IdentityReranker()
    app = build_application(
        config=_config(tmp_path),
        providers={0: _Provider(reply="positive"), 1: _Provider(reply=_PLAIN_REPLY)},
        bob_bot=_FakeBot(),
        guppi_bot=_FakeBot(),
        embedder=FakeEmbedder(),
        reranker=reranker,
    )
    await app.startup()
    try:
        await app.memory_repo.save_fact(
            SemanticFact(ts=datetime.now(tz=UTC), category="personal", content=_SEMANTIC_FACT)
        )

        # Act: a recall runs the (additive) reranker over the fused pool.
        await app.handle_message._recall.recall(_SEMANTIC_QUERY, k=5)
    finally:
        await app.shutdown()

    # Assert: the wired reranker was invoked.
    assert reranker.calls >= 1


def _message() -> MessageReceived:
    return MessageReceived(
        update_id=1,
        chat_id=_CHAT,
        message_id=7,
        text="расскажи подробно про зонды, Bob",
        sender_id=_OWNER,
        sender_name="Ada",
    )
