# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LlmDisclosureConsentJudge — the Tier-0 consent seam (BOB-082 .4).

The judge builds a Tier-0 ``LLMRequest`` from the pure prompt builder, runs it on the
local provider, and parses the reply into a bool via
:func:`~bob.social.disclosure_consent.parse_disclosure_consent`. Consent is privacy-
sensitive, so it stays local (Tier 0). The parser is conservative (bias to NO), so an
unparseable reply yields ``False`` rather than raising — a garbled model never discloses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.social.adapters.disclosure_consent_judge import LlmDisclosureConsentJudge
from bob.social.disclosure_consent import DisclosureConsentContext

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


def _ctx() -> DisclosureConsentContext:
    return DisclosureConsentContext(
        request_text="Боб, расскажи ребятам, что мы в личке обсуждали",
        recent_thread="",
    )


def _judge(
    reply: str, *, raises: bool = False
) -> tuple[LlmDisclosureConsentJudge, _FakeProvider]:
    provider = _FakeProvider(reply, raises=raises)
    router = LLMRouter(providers={0: provider})
    return LlmDisclosureConsentJudge(router=router), provider


async def test_builds_tier0_request_and_parses_yes() -> None:
    judge, provider = _judge("consent: yes")

    assert await judge.assess(_ctx()) is True
    assert provider.messages is not None
    user_contents = " ".join(m["content"] for m in provider.messages)
    assert "расскажи ребятам" in user_contents


async def test_parses_no() -> None:
    judge, _ = _judge("consent: no")
    assert await judge.assess(_ctx()) is False


async def test_uses_the_local_disclosure_consent_task() -> None:
    # DISCLOSURE_CONSENT is pinned Tier-0: a Tier-0-only router proves it never needs
    # a Tier 1 provider (privacy — consent stays local).
    judge, _ = _judge("consent: yes")
    assert await judge.assess(_ctx()) is True
    assert TaskType.DISCLOSURE_CONSENT.value == "disclosure_consent"


async def test_unparseable_reply_is_conservatively_no() -> None:
    # Bias to NO: a garbled reply never discloses (no raise, safe default).
    judge, _ = _judge("я не знаю")
    assert await judge.assess(_ctx()) is False


async def test_model_error_propagates_for_the_caller_to_swallow() -> None:
    # The thin adapter does not swallow — the use-case caller catches it and treats a
    # detector failure as no-consent (best-effort, never an accidental disclosure).
    judge, _ = _judge("consent: yes", raises=True)
    with pytest.raises(RuntimeError):
        await judge.assess(_ctx())
