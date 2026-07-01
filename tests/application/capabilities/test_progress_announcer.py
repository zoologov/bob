# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the progress announcer — the LIVE interim "searching…" reply (BOB-060).

Before a SLOW web_search runs, Bob sends a short, LIVING one-liner in his own voice
so the owner is not left in silence. There are NO hardwired phrases anymore (BOB-060,
US-2): the line is generated on the LIVE Tier-0 :class:`InterimLineGenerator` (BOB-057)
for BOTH the tool-loop (``announce``) and the verify (``announce_verify``) paths. The
announce is DECORATIVE: it decides by capability name whether to speak, generates via
the live port, sends via the same gateway ``reply`` seam HandleMessage uses, and
swallows its OWN errors. On generator failure / empty line / no generator → SILENCE
(never a scripted phrase).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import bob.application.capabilities.progress_announcer as _announcer_mod
from bob.application.capabilities.progress_announcer import GatewayProgressAnnouncer

if TYPE_CHECKING:
    from collections.abc import Mapping


def test_hardwired_phrase_sets_are_gone() -> None:
    # 🔴 US-2: zero scripted phrases anywhere — the removed names must not be importable.
    assert not hasattr(_announcer_mod, "WEB_SEARCH_PROGRESS_PHRASES")
    assert not hasattr(_announcer_mod, "DEFAULT_PROGRESS_PHRASES")


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


class _FakeLineGenerator:
    """A scripted interim-line generator: returns a line, empty, or raises.

    Records the (topic, sender_name) it saw so a test can prove the live gen was
    asked with the turn's subject + interlocutor.
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


def _announcer(
    gateway: FakeGateway,
    *,
    generator: _FakeLineGenerator | None = None,
    chat_id: int = 42,
    sender_name: str = "Лёша",
) -> GatewayProgressAnnouncer:
    return GatewayProgressAnnouncer(
        chat_id=chat_id,
        gateway=gateway,
        line_generator=generator,
        sender_name=sender_name,
    )


# ---------------------------------------------------------------------------
# tool-loop path: announce(capability_name, arguments)
# ---------------------------------------------------------------------------


async def test_web_search_announce_generates_live_line_from_query() -> None:
    # The tool-loop path pulls the query out of the call arguments and feeds it to the
    # live generator as the topic; the generated line reaches the turn's chat.
    gateway = FakeGateway()
    generator = _FakeLineGenerator(line="секунду, гляну свежие ставки 🙂")
    announcer = _announcer(gateway, generator=generator, chat_id=99, sender_name="Лёша")

    await announcer.announce("web_search", {"query": "свежие ставки"})

    assert generator.calls == [("свежие ставки", "Лёша")]  # gen saw query + sender
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["chat_id"] == 99
    assert gateway.calls[0]["markdown"] == "секунду, гляну свежие ставки 🙂"


async def test_web_search_without_query_uses_a_generic_topic() -> None:
    # No query in the arguments → a generic search topic, still LIVE (never a scripted
    # phrase). The generator is still asked so the line stays in Bob's voice.
    gateway = FakeGateway()
    generator = _FakeLineGenerator(line="момент, поищу 🙂")
    announcer = _announcer(gateway, generator=generator)

    await announcer.announce("web_search", {})

    assert len(generator.calls) == 1
    assert generator.calls[0][0]  # a non-empty generic topic was passed
    assert gateway.calls[0]["markdown"] == "момент, поищу 🙂"


async def test_non_web_search_capability_stays_silent() -> None:
    # read_url / recall_memory are fast → no interim line AND the generator is untouched.
    gateway = FakeGateway()
    generator = _FakeLineGenerator(line="should not be used")
    announcer = _announcer(gateway, generator=generator)

    await announcer.announce("read_url", {"url": "https://x"})
    await announcer.announce("recall_memory", {"query": "x"})

    assert gateway.calls == []
    assert generator.calls == []


async def test_web_search_without_generator_stays_silent() -> None:
    # 🔴 US-2: no generator wired → SILENCE (there is no scripted fallback anymore).
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=None)

    await announcer.announce("web_search", {"query": "ставки"})

    assert gateway.calls == []


async def test_web_search_empty_gen_stays_silent() -> None:
    # 🔴 US-2: an empty (whitespace-only) live line → SILENCE, never a scripted phrase.
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=_FakeLineGenerator(line="   "))

    await announcer.announce("web_search", {"query": "ставки"})

    assert gateway.calls == []


async def test_web_search_gen_error_stays_silent() -> None:
    # 🔴 Decorative + US-2: a raising live gen is caught → SILENCE (no fallback phrase,
    # never propagates).
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=_FakeLineGenerator(raises=True))

    await announcer.announce("web_search", {"query": "ставки"})

    assert gateway.calls == []


async def test_web_search_gateway_failure_is_swallowed() -> None:
    # Decorative: the send blowing up is swallowed — the search and the turn are safe.
    gateway = FakeGateway(raises=True)
    announcer = _announcer(gateway, generator=_FakeLineGenerator(line="секунду 🙂"))

    await announcer.announce("web_search", {"query": "ставки"})

    assert len(gateway.calls) == 1  # it tried, then dropped the error


# ---------------------------------------------------------------------------
# verify path: announce_verify(topic) — same live-only engine, sender from ctor
# ---------------------------------------------------------------------------


async def test_announce_verify_sends_the_live_addressed_line() -> None:
    gateway = FakeGateway()
    generator = _FakeLineGenerator(line="Лёш, гляну свежие ставки, секунду 🙂")
    announcer = _announcer(gateway, generator=generator, chat_id=99, sender_name="Лёша")

    await announcer.announce_verify(topic="свежие ставки")

    assert generator.calls == [("свежие ставки", "Лёша")]
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["chat_id"] == 99
    assert gateway.calls[0]["markdown"] == "Лёш, гляну свежие ставки, секунду 🙂"


async def test_announce_verify_empty_gen_stays_silent() -> None:
    # 🔴 US-2: no seeded fallback — an empty live line is SILENCE.
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=_FakeLineGenerator(line="   "))

    await announcer.announce_verify(topic="ставки")

    assert gateway.calls == []


async def test_announce_verify_gen_error_stays_silent() -> None:
    # 🔴 US-2: a raising gen is caught → SILENCE, not a scripted phrase.
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=_FakeLineGenerator(raises=True))

    await announcer.announce_verify(topic="ставки")

    assert gateway.calls == []


async def test_announce_verify_without_generator_stays_silent() -> None:
    gateway = FakeGateway()
    announcer = _announcer(gateway, generator=None)

    await announcer.announce_verify(topic="ставки")

    assert gateway.calls == []


async def test_announce_verify_gateway_failure_is_swallowed() -> None:
    gateway = FakeGateway(raises=True)
    announcer = _announcer(gateway, generator=_FakeLineGenerator(line="Лёш, секунду 🙂"))

    await announcer.announce_verify(topic="ставки")

    assert len(gateway.calls) == 1  # it tried, then dropped the error
