# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the progress announcer — the interim "searching…" reply (BOB-055 .2).

Before a SLOW capability (web_search, ~1-2 min) runs, Bob sends a short, VARIED
live line in his own voice so the owner is not left in silence. The announce is
DECORATIVE: it decides by capability name whether to say anything, sends via the
same gateway ``reply`` seam HandleMessage uses, and swallows its OWN errors — a
failure must never break or block the turn.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING

from bob.application.capabilities.progress_announcer import (
    DEFAULT_PROGRESS_PHRASES,
    WEB_SEARCH_PROGRESS_PHRASES,
    GatewayProgressAnnouncer,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeGateway:
    """Records ``reply`` calls; optionally raises to prove the decorative drop."""

    def __init__(self, *, raises: bool = False) -> None:
        self.calls: list[Mapping[str, object]] = []
        self._raises = raises

    async def reply(
        self, *, chat_id: int, markdown: str, thinking: str | None = None
    ) -> int | None:
        self.calls.append({"chat_id": chat_id, "markdown": markdown, "thinking": thinking})
        if self._raises:
            raise RuntimeError("gateway down")
        return 1


def _announcer(
    gateway: FakeGateway,
    *,
    chat_id: int = 42,
    seed: int = 0,
    phrases: Mapping[str, Sequence[str]] | None = None,
) -> GatewayProgressAnnouncer:
    return GatewayProgressAnnouncer(
        chat_id=chat_id,
        gateway=gateway,
        rng=Random(seed),  # noqa: S311 — deterministic test seed, not cryptographic
        phrases=DEFAULT_PROGRESS_PHRASES if phrases is None else phrases,
    )


async def test_web_search_sends_a_phrase_from_the_set_to_the_chat() -> None:
    # Arrange
    gateway = FakeGateway()
    announcer = _announcer(gateway, chat_id=99)

    # Act
    await announcer.announce("web_search")

    # Assert: exactly one interim line, to the turn's chat, drawn from the voiced set.
    assert len(gateway.calls) == 1
    call = gateway.calls[0]
    assert call["chat_id"] == 99
    assert call["markdown"] in WEB_SEARCH_PROGRESS_PHRASES


async def test_unmapped_capability_says_nothing() -> None:
    # Arrange: read_url / recall_memory are fast → no interim line.
    gateway = FakeGateway()
    announcer = _announcer(gateway)

    # Act
    await announcer.announce("read_url")
    await announcer.announce("recall_memory")

    # Assert
    assert gateway.calls == []


async def test_seeded_rng_makes_the_phrase_choice_deterministic() -> None:
    # Arrange: same seed twice → same phrase.
    g1, g2 = FakeGateway(), FakeGateway()

    # Act
    await _announcer(g1, seed=7).announce("web_search")
    await _announcer(g2, seed=7).announce("web_search")

    # Assert
    assert g1.calls[0]["markdown"] == g2.calls[0]["markdown"]


async def test_different_seeds_can_pick_different_phrases() -> None:
    # Arrange / Act: sweep seeds → the varied set is actually exercised (not one robo-line).
    chosen: set[str] = set()
    for seed in range(30):
        gateway = FakeGateway()
        await _announcer(gateway, seed=seed).announce("web_search")
        chosen.add(str(gateway.calls[0]["markdown"]))

    # Assert
    assert len(chosen) > 1


async def test_capability_mapped_to_empty_phrase_set_stays_silent() -> None:
    # Arrange: a name present in the map but with an EMPTY voiced set — the announcer
    # must treat "no options" the same as an unmapped name (silence), never crash on
    # an empty-sequence RNG choice. Distinct branch from the missing-key case.
    gateway = FakeGateway()
    announcer = _announcer(gateway, phrases={"web_search": ()})

    # Act
    await announcer.announce("web_search")

    # Assert
    assert gateway.calls == []


async def test_successive_announces_each_send_a_line() -> None:
    # Arrange: reusing one announcer across two slow calls in a turn must speak both
    # times (the RNG is stateful per-instance; no accidental one-shot latch).
    gateway = FakeGateway()
    announcer = _announcer(gateway)

    # Act
    await announcer.announce("web_search")
    await announcer.announce("web_search")

    # Assert: both interim lines sent, each from the voiced set.
    assert len(gateway.calls) == 2
    assert all(call["markdown"] in WEB_SEARCH_PROGRESS_PHRASES for call in gateway.calls)


async def test_gateway_failure_is_swallowed_not_propagated() -> None:
    # Arrange: the send blows up mid-turn.
    gateway = FakeGateway(raises=True)
    announcer = _announcer(gateway)

    # Act / Assert: announce must NOT raise (decorative — the turn is unaffected).
    await announcer.announce("web_search")
    assert len(gateway.calls) == 1  # it tried, then dropped the error
