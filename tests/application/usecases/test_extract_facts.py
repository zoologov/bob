# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ExtractFacts — Tier 0 durable-fact extraction into semantic memory.

Everything external is faked: a scripted LLM provider (no network) returns the
structured fact payload, and an in-memory writer captures the persisted
:class:`SemanticFact` entities. The tests assert the contract: durable,
user-specific facts are extracted from a turn, persisted as semantic facts, and
obvious repeats are de-duplicated — while malformed/empty model output and a
provider error never raise (best-effort).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.infrastructure.persistence.sqlite_repo import SqliteMemoryRepo
from bob.memory.adapters.fts_recall import Fts5MemoryRecall
from bob.memory.usecases.extract_facts import ExtractFacts

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from pathlib import Path

    from bob.memory.entities import SemanticFact


class FixedClock:
    """Clock returning a fixed timezone-aware instant (deterministic tests)."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class ScriptedProvider:
    """Fake LLMProvider returning a canned completion and recording requests.

    ``raises`` makes :meth:`complete` raise, to exercise the best-effort path.
    """

    def __init__(self, *, reply: str = "", raises: bool = False) -> None:
        self.reply = reply
        self.raises = raises
        self.payloads: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol
    ) -> str | AsyncIterator[str]:
        self.payloads.append([dict(m) for m in messages])
        if self.raises:
            raise RuntimeError("tier 0 provider exploded")
        return self.reply


class FakeFactWriter:
    """In-memory FactWriter capturing every persisted SemanticFact."""

    def __init__(self) -> None:
        self.facts: list[SemanticFact] = []

    async def save_fact(self, fact: SemanticFact) -> None:
        self.facts.append(fact)


def _moment() -> datetime:
    return datetime(2026, 6, 18, 14, 0, 0, tzinfo=UTC)


def _build(
    *, reply: str = "", raises: bool = False
) -> tuple[ExtractFacts, FakeFactWriter, ScriptedProvider]:
    tier0 = ScriptedProvider(reply=reply, raises=raises)
    tier1 = ScriptedProvider(reply="unused")
    router = LLMRouter(providers={0: tier0, 1: tier1})
    writer = FakeFactWriter()
    extractor = ExtractFacts(router=router, repo=writer, clock=FixedClock(_moment()))
    return extractor, writer, tier0


async def test_extracts_and_persists_a_durable_fact() -> None:
    # Arrange: the model returns one durable, user-specific fact.
    extractor, writer, _tier0 = _build(
        reply='[{"category": "user", "content": "name is Vova"}]'
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="nice to meet you")

    # Assert: it landed in semantic memory as a SemanticFact.
    assert len(writer.facts) == 1
    assert writer.facts[0].category == "user"
    assert writer.facts[0].content == "name is Vova"
    assert writer.facts[0].ts == _moment()


async def test_extraction_runs_on_tier0() -> None:
    # Arrange
    extractor, _writer, tier0 = _build(reply="[]")

    # Act
    await extractor.run(user_message="hi", reply="hello")

    # Assert: the extraction prompt went to the Tier 0 (local) provider.
    assert len(tier0.payloads) == 1


async def test_persists_multiple_facts() -> None:
    # Arrange
    extractor, writer, _tier0 = _build(
        reply=(
            '[{"category": "user", "content": "name is Vova"},'
            ' {"category": "preference", "content": "likes pour-over coffee"}]'
        )
    )

    # Act
    await extractor.run(user_message="I'm Vova and I like pour-over", reply="ok")

    # Assert
    assert {f.content for f in writer.facts} == {
        "name is Vova",
        "likes pour-over coffee",
    }


async def test_dedups_obvious_repeats() -> None:
    # Arrange: the model emits the same fact twice (whitespace/case differing).
    extractor, writer, _tier0 = _build(
        reply=(
            '[{"category": "user", "content": "name is Vova"},'
            ' {"category": "user", "content": "  Name is Vova "}]'
        )
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="ok")

    # Assert: only one fact is persisted.
    assert len(writer.facts) == 1


async def test_empty_extraction_persists_nothing() -> None:
    # Arrange
    extractor, writer, _tier0 = _build(reply="[]")

    # Act
    await extractor.run(user_message="nice weather", reply="indeed")

    # Assert
    assert writer.facts == []


async def test_malformed_output_does_not_raise() -> None:
    # Arrange: the model returns prose, not JSON.
    extractor, writer, _tier0 = _build(reply="I could not find any facts, sorry.")

    # Act / Assert: best-effort — no exception, nothing persisted.
    await extractor.run(user_message="hello", reply="hi")
    assert writer.facts == []


async def test_parses_fenced_json_block() -> None:
    # Arrange: a reasoning model wraps the array in a ```json code fence.
    extractor, writer, _tier0 = _build(
        reply='```json\n[{"category": "user", "content": "name is Vova"}]\n```'
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="hi")

    # Assert: the wrapped fact is extracted despite the fence.
    assert [f.content for f in writer.facts] == ["name is Vova"]


async def test_parses_bare_fence_without_language_tag() -> None:
    # Arrange: a fence with no language tag (just ```).
    extractor, writer, _tier0 = _build(
        reply='```\n[{"category": "user", "content": "name is Vova"}]\n```'
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="hi")

    # Assert
    assert [f.content for f in writer.facts] == ["name is Vova"]


async def test_parses_prose_preamble_before_array() -> None:
    # Arrange: the model prefixes a prose sentence before the array.
    extractor, writer, _tier0 = _build(
        reply='Here are the facts:\n[{"category": "user", "content": "name is Vova"}]'
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="hi")

    # Assert: the stated name survives the prose preamble.
    assert [f.content for f in writer.facts] == ["name is Vova"]


async def test_parses_leading_reasoning_text_then_array() -> None:
    # Arrange: a reasoning model emits chain-of-thought, then the JSON array.
    extractor, writer, _tier0 = _build(
        reply=(
            "Let me think. The user told me their name, which is a durable "
            'user fact, so I will record it.\n'
            '[{"category": "user", "content": "name is Vova"}]'
        )
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="hi")

    # Assert
    assert [f.content for f in writer.facts] == ["name is Vova"]


async def test_parses_array_with_trailing_prose() -> None:
    # Arrange: the array is followed by extra trailing commentary.
    extractor, writer, _tier0 = _build(
        reply=(
            '[{"category": "user", "content": "name is Vova"}]\n'
            "That is the only durable fact I found."
        )
    )

    # Act
    await extractor.run(user_message="my name is Vova", reply="hi")

    # Assert
    assert [f.content for f in writer.facts] == ["name is Vova"]


async def test_parses_fenced_block_wrapped_in_reasoning_and_prose() -> None:
    # Arrange: the full reasoning-model envelope — preamble + fenced json + trailer.
    extractor, writer, _tier0 = _build(
        reply=(
            "Sure, here is what I extracted from the exchange:\n\n"
            "```json\n"
            '[{"category": "user", "content": "name is Vova"},'
            ' {"category": "preference", "content": "likes pour-over coffee"}]\n'
            "```\n\n"
            "Let me know if you need anything else."
        )
    )

    # Act
    await extractor.run(user_message="I'm Vova and I like pour-over", reply="ok")

    # Assert: both facts extracted, including the stated name.
    assert {f.content for f in writer.facts} == {
        "name is Vova",
        "likes pour-over coffee",
    }


async def test_genuine_garbage_persists_nothing() -> None:
    # Arrange: no JSON array anywhere — genuine non-JSON output.
    extractor, writer, _tier0 = _build(
        reply="I'm sorry, I couldn't determine any durable facts from that."
    )

    # Act / Assert: best-effort — nothing persisted, no raise.
    await extractor.run(user_message="hello", reply="hi")
    assert writer.facts == []


async def test_provider_error_does_not_raise() -> None:
    # Arrange: the Tier 0 provider raises.
    extractor, writer, _tier0 = _build(raises=True)

    # Act / Assert: extraction is best-effort and swallows the error.
    await extractor.run(user_message="my name is Vova", reply="ok")
    assert writer.facts == []


async def test_skips_facts_with_blank_content() -> None:
    # Arrange: a fact with empty content must be dropped, a valid one kept.
    extractor, writer, _tier0 = _build(
        reply=(
            '[{"category": "user", "content": ""},'
            ' {"category": "user", "content": "lives in Berlin"}]'
        )
    )

    # Act
    await extractor.run(user_message="I live in Berlin", reply="ok")

    # Assert
    assert [f.content for f in writer.facts] == ["lives in Berlin"]


async def test_extracted_fact_is_later_surfaced_by_recall(tmp_path: Path) -> None:
    # PRD US-3 (the bead's goal): a fact extracted on one turn must be recallable
    # on a later turn — through the REAL SQLite semantic_memory + FTS5 index, not
    # a fake. This is the bridge ExtractFacts -> semantic_memory -> MemoryRecall.
    repo = SqliteMemoryRepo(tmp_path / "bob.db")
    await repo.initialize()
    tier0 = ScriptedProvider(reply='[{"category": "user", "content": "name is Vova"}]')
    router = LLMRouter(providers={0: tier0, 1: ScriptedProvider(reply="unused")})
    extractor = ExtractFacts(router=router, repo=repo, clock=FixedClock(_moment()))

    # Act: extract a durable fact, then recall over it as a later turn would.
    await extractor.run(user_message="my name is Vova", reply="nice to meet you")
    results = await Fts5MemoryRecall(repo).recall("name", k=5)

    # Assert: the durable fact is surfaced for the reply context.
    assert any("Vova" in str(r["content"]) for r in results)
    await repo.close()
