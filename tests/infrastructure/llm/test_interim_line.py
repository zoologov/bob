# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmInterimLineGenerator — the Tier-0 live interim line (BOB-057 .3).

The generator builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it
on the local provider, and cleans the reply into a single addressed one-liner. It
does NOT swallow router errors — the caller (the announcer) catches them and falls
back to a seeded BOB-055 phrase, keeping the whole interim decorative.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.infrastructure.llm.interim_line import LlmInterimLineGenerator

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """Tier-0 provider returning a fixed reply and recording the messages."""

    def __init__(self, reply: str, *, raises: bool = False) -> None:
        self._reply = reply
        self._raises = raises
        self.messages: Sequence[Mapping[str, str]] | None = None

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.messages = messages
        if self._raises:
            raise RuntimeError("local model down")
        return self._reply


def _gen(
    reply: str, *, raises: bool = False
) -> tuple[LlmInterimLineGenerator, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmInterimLineGenerator(router=router), provider


async def test_builds_tier0_request_and_cleans_the_line() -> None:
    gen, provider = _gen("Лёш, гляну свежие ставки, секунду 🙂")

    line = await gen.generate(topic="свежие ставки", sender_name="Лёша")

    assert line == "Лёш, гляну свежие ставки, секунду 🙂"
    assert provider.messages is not None
    contents = " ".join(m["content"] for m in provider.messages)
    assert "свежие ставки" in contents  # the topic reached the prompt
    assert "Лёша" in contents  # the addressed name reached the prompt


async def test_request_uses_the_local_interim_line_task() -> None:
    # INTERIM_LINE is pinned Tier-0: a Tier-0-only router proves it never needs Tier 1.
    gen, _ = _gen("момент, проверю")
    line = await gen.generate(topic="курс биткоина", sender_name="Ада")
    assert line == "момент, проверю"
    assert TaskType.INTERIM_LINE.value == "interim_line"


async def test_multiline_reply_is_reduced_to_one_line() -> None:
    gen, _ = _gen("Лёш, секунду 🙂\nсейчас всё проверю подробно")
    assert await gen.generate(topic="ставки", sender_name="Лёша") == "Лёш, секунду 🙂"


async def test_raises_on_model_error() -> None:
    # No silent default here — the announcer catches and seeds the fallback.
    gen, _ = _gen("unused", raises=True)
    with pytest.raises(RuntimeError):
        await gen.generate(topic="ставки", sender_name="Лёша")
