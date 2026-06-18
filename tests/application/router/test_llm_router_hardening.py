# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening tests for LLMRouter defensive contracts.

Covers the two guard branches the happy-path suite does not exercise: a router
built without a Tier 0 provider must refuse construction, and a provider that
returns a non-string (streaming object in a non-stream call) must be rejected.
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


class _NonStrProvider:
    """A provider that (incorrectly) yields a non-str on a non-stream call."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        async def _gen() -> AsyncIterator[str]:
            yield "x"

        return _gen()


def test_router_requires_a_tier0_provider() -> None:
    # Arrange: only a Tier 1 provider supplied.
    only_tier1 = {1: _NonStrProvider()}

    # Act / Assert
    with pytest.raises(ValueError, match="Tier 0"):
        LLMRouter(providers=only_tier1)


async def test_non_string_completion_is_rejected() -> None:
    # Arrange: a Tier 0 provider that returns the wrong type for a non-stream call.
    router = LLMRouter(providers={0: _NonStrProvider()})
    request = LLMRequest(task_type=TaskType.SENTIMENT, messages=[])

    # Act / Assert: the router enforces its str contract.
    with pytest.raises(TypeError, match="must return str"):
        await router.run(request)
