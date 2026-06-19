# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for LLMRouter: tier selection, selective redaction, and fallback.

Uses a captured fake provider (no real network) so the privacy boundary is
directly testable. The invariant (Variant 2, selective redaction): genuinely
internal ``private_context`` MUST NOT reach a Tier 1 payload, while
``shareable_context`` (conversation/memory/mood/identity/taste — material that
shapes Bob's reply and returns to that same user) IS allowed to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import (
    LLMRequest,
    LLMRouter,
    TaskType,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

# Genuinely-internal context that must never reach Tier 1.
PRIVATE_CONTEXT = "INTERNAL: raw inner-monologue scratchpad, never for the user."
# Reply-shaping context (conversation/memory) that MAY reach Tier 1.
SHAREABLE_CONTEXT = "Recent conversation: the user said their name is Alice."


class CapturingProvider:
    """Fake LLMProvider that records every messages payload it is asked to complete."""

    def __init__(self, *, reply: str = "ok", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self.fail:
            raise ConnectionError("tier unavailable")
        return self.reply


def _router(tier0: CapturingProvider, tier1: CapturingProvider) -> LLMRouter:
    return LLMRouter(providers={0: tier0, 1: tier1})


async def test_reply_to_user_routes_to_tier1() -> None:
    # Arrange
    tier0, tier1 = CapturingProvider(reply="t0"), CapturingProvider(reply="t1")
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "hello"}],
    )

    # Act
    result = await router.run(request)

    # Assert: Tier 1 served it; Tier 0 untouched.
    assert result == "t1"
    assert len(tier1.calls) == 1
    assert tier0.calls == []


async def test_sentiment_routes_to_tier0() -> None:
    # Arrange
    tier0, tier1 = CapturingProvider(reply="t0"), CapturingProvider(reply="t1")
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.SENTIMENT,
        messages=[{"role": "user", "content": "feeling"}],
    )

    # Act
    result = await router.run(request)

    # Assert
    assert result == "t0"
    assert len(tier0.calls) == 1
    assert tier1.calls == []


async def test_tier1_call_never_receives_private_context() -> None:
    # Arrange: a reply carrying BOTH shareable and genuinely-private context.
    tier0, tier1 = CapturingProvider(reply="t0"), CapturingProvider(reply="t1")
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "what's up"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    # Act
    await router.run(request)

    # Assert: private context appears in NO Tier 1 message payload.
    assert tier1.calls, "Tier 1 should have been called"
    for call in tier1.calls:
        for message in call:
            assert PRIVATE_CONTEXT not in message.get("content", "")


async def test_tier1_reply_receives_shareable_context() -> None:
    # Arrange: the reply tier SHOULD see conversation/memory context (Variant 2).
    tier0, tier1 = CapturingProvider(reply="t0"), CapturingProvider(reply="t1")
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "what's up"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    # Act
    await router.run(request)

    # Assert: the shareable conversation/memory context DID reach Tier 1.
    joined = " ".join(m.get("content", "") for call in tier1.calls for m in call)
    assert SHAREABLE_CONTEXT in joined


async def test_tier0_receives_both_shareable_and_private_context() -> None:
    # Arrange: a Tier 0 task stays local, so it gets the full context.
    tier0, tier1 = CapturingProvider(reply="t0"), CapturingProvider(reply="t1")
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.INNER_MONOLOGUE,
        messages=[{"role": "user", "content": "reflect"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    # Act
    await router.run(request)

    # Assert: Tier 0 (local) sees both the shareable and the private context.
    joined = " ".join(m.get("content", "") for call in tier0.calls for m in call)
    assert PRIVATE_CONTEXT in joined
    assert SHAREABLE_CONTEXT in joined
    assert tier1.calls == []


async def test_tier1_failure_falls_back_to_tier0() -> None:
    # Arrange: Tier 1 unavailable.
    tier0 = CapturingProvider(reply="fallback")
    tier1 = CapturingProvider(fail=True)
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "hi"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    # Act
    result = await router.run(request)

    # Assert: fell back to Tier 0; Tier 1 was attempted first.
    assert result == "fallback"
    assert len(tier1.calls) == 1
    assert len(tier0.calls) == 1


async def test_fallback_to_tier0_keeps_private_context_redacted() -> None:
    # Arrange: redaction is a property of the request, not the chosen tier — the
    # Tier 1 -> Tier 0 fallback sends the same (shareable-only) payload.
    tier0 = CapturingProvider(reply="fallback")
    tier1 = CapturingProvider(fail=True)
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "hi"}],
        shareable_context=SHAREABLE_CONTEXT,
        private_context=PRIVATE_CONTEXT,
    )

    # Act
    await router.run(request)

    # Assert: the fallback payload carries the shareable context but NOT the private one.
    joined = " ".join(m.get("content", "") for call in tier0.calls for m in call)
    assert SHAREABLE_CONTEXT in joined
    assert PRIVATE_CONTEXT not in joined


async def test_tier0_failure_with_no_fallback_raises() -> None:
    # Arrange: a Tier 0 task whose only provider fails has nowhere to fall back.
    tier0 = CapturingProvider(fail=True)
    tier1 = CapturingProvider()
    router = _router(tier0, tier1)
    request = LLMRequest(
        task_type=TaskType.SENTIMENT,
        messages=[{"role": "user", "content": "x"}],
    )

    # Act / Assert
    with pytest.raises(ConnectionError):
        await router.run(request)
