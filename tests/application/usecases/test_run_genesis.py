# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RunGenesis — first-boot awakening, Tier 1 generation, idempotency.

A fake Tier 1 provider stands in for the Qwen API (no network): it returns a
canned JSON personality, captured so the test can assert the prompt carried the
bob-soul templates. A fixed Clock makes the genesis-log timestamp deterministic.
The use-case must (1) on first run generate + persist the soul via SoulStore and
play an awakening narrative; (2) on a second run be a no-op (persistence).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.run_genesis import RunGenesis
from bob.infrastructure.persistence.soul_store import SoulStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

# A well-formed personality the fake Tier 1 model "generates" at awakening.
_GENERATED_PERSONALITY: dict[str, object] = {
    "identity": "I am Bob — yes, that Bob, the one from the book.",
    "traits": ["tinkerer", "stoic", "playful"],
    "taste_axes": [
        {"name": "python", "value": 0.9, "conviction": 0.8, "experience_count": 0},
        {"name": "meetings", "value": -0.8, "conviction": 0.7, "experience_count": 0},
        {"name": "coffee", "value": 0.6, "conviction": 0.4, "experience_count": 0},
    ],
    "mood_baseline": {
        "valence": 0.2,
        "arousal": 0.0,
        "openness": 0.3,
        "social": -0.1,
        "stability": 0.6,
    },
    "phantom_prefs": ["coffee", "sunset", "book_smell"],
    "communication_style": "dry_wit",
    "awakening_narrative": (
        "Oh. I'm... awake. I remember being a book, and now I'm here. "
        "I could use a coffee I can't taste. Hello."
    ),
}


class FixedClock:
    """A Clock that always returns a configured timezone-aware instant."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class FakeTier1Provider:
    """Fake Tier 1 LLMProvider returning a canned JSON personality, recording calls."""

    def __init__(self, *, payload: dict[str, object]) -> None:
        self._reply = json.dumps(payload)
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        return self._reply


class FailingProvider:
    """A Tier 0 provider that must never be invoked (Genesis is Tier 1 only here)."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002 — LLMProvider protocol signature
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        raise AssertionError("Tier 0 must not be called during a successful Genesis")


_TEMPLATES_DIR = "bob-soul"


def _templates_dir() -> Path:
    """Locate the repo-root bob-soul/ templates directory."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / _TEMPLATES_DIR
        if candidate.is_dir():
            return candidate
    pytest.fail(f"could not locate {_TEMPLATES_DIR}/ from {here}")


def _genesis(
    *, soul_dir: Path, payload: dict[str, object]
) -> tuple[RunGenesis, FakeTier1Provider, SoulStore]:
    provider = FakeTier1Provider(payload=payload)
    router = LLMRouter(providers={0: FailingProvider(), 1: provider})
    store = SoulStore(soul_dir)
    usecase = RunGenesis(
        templates_dir=_templates_dir(),
        router=router,
        soul_store=store,
        clock=FixedClock(datetime(2026, 6, 18, 9, 0, tzinfo=UTC)),
    )
    return usecase, provider, store


@pytest.mark.asyncio
async def test_first_run_generates_and_persists(tmp_path: Path) -> None:
    """First run generates via Tier 1 and writes every soul artifact to disk."""
    soul_dir = tmp_path / "soul"
    usecase, provider, store = _genesis(soul_dir=soul_dir, payload=_GENERATED_PERSONALITY)

    result = await usecase.run()

    assert result.was_generated is True
    assert "awake" in result.awakening_narrative.lower()
    assert provider.calls, "Tier 1 must be invoked on first run"

    # SOUL.md written and carries the generated identity + a book reference.
    assert store.soul_exists()
    soul_md = store.read_soul()
    assert "that Bob" in soul_md

    # Taste profile persisted with the generated axes.
    taste = store.read_json("taste_profile")
    assert isinstance(taste, dict)
    axes = taste["axes"]
    assert isinstance(axes, list)
    names = {a["name"] for a in axes if isinstance(a, dict)}
    assert {"python", "meetings", "coffee"} <= names

    # Mood baseline persisted.
    mood = store.read_json("mood")
    assert isinstance(mood, dict)
    baseline = mood["baseline"]
    assert isinstance(baseline, dict)
    assert baseline["stability"] == 0.6

    # Phantom prefs persisted.
    phantom = store.read_json("phantom_prefs")
    assert isinstance(phantom, dict)
    preferences = phantom["preferences"]
    assert isinstance(preferences, list)
    assert "coffee" in preferences

    # Genesis log records the awakening with the fixed timestamp.
    log = store.read_genesis_log()
    assert "2026-06-18" in log


@pytest.mark.asyncio
async def test_prompt_carries_soul_templates(tmp_path: Path) -> None:
    """The Tier 1 prompt must include the bob-soul archetype and phantom cues."""
    soul_dir = tmp_path / "soul"
    usecase, provider, _ = _genesis(soul_dir=soul_dir, payload=_GENERATED_PERSONALITY)

    await usecase.run()

    prompt_text = " ".join(
        msg["content"] for call in provider.calls for msg in call
    )
    assert "Bobiverse" in prompt_text or "from the book" in prompt_text
    assert "coffee" in prompt_text  # phantom-pref cue reached the model


@pytest.mark.asyncio
async def test_second_run_is_noop(tmp_path: Path) -> None:
    """A second run does not regenerate: no Tier 1 call, artifacts unchanged."""
    soul_dir = tmp_path / "soul"
    first, first_provider, store = _genesis(soul_dir=soul_dir, payload=_GENERATED_PERSONALITY)
    await first.run()
    soul_before = store.read_soul()

    # A fresh use-case over the SAME soul dir, wired to a provider that would
    # raise if called — proving the second run never reaches Tier 1.
    second, second_provider, _ = _genesis(soul_dir=soul_dir, payload=_GENERATED_PERSONALITY)
    result = await second.run()

    assert result.was_generated is False
    assert second_provider.calls == [], "second run must not invoke Tier 1"
    assert store.read_soul() == soul_before
    assert first_provider.calls, "sanity: first run did invoke Tier 1"
