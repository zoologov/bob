# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ClassifyCodingIntent — the cheap Tier-0 coding/chat classifier (BOB-041 .2).

The classifier asks the router (one-word ``coding``/``chat``) on the local Tier-0 path
and is CONSERVATIVE: only an exact ``coding`` answer counts as a dev-work request; any
other word, garbage, or a flaky model defaults to chat (``False``), so a misread never
spuriously opens a coding session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.application.usecases.classify_coding_intent import ClassifyCodingIntent

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _FakeProvider:
    """Tier-0 provider returning a fixed label and recording the task metadata."""

    def __init__(self, label: str, *, raises: bool = False) -> None:
        self._label = label
        self._raises = raises
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:
        self.calls += 1
        if self._raises:
            raise RuntimeError("local model down")
        return self._label


def _classifier(label: str, *, raises: bool = False) -> ClassifyCodingIntent:
    provider = _FakeProvider(label, raises=raises)
    router = LLMRouter(providers={0: provider})
    return ClassifyCodingIntent(router=router)


async def test_exact_coding_label_is_a_coding_request() -> None:
    classifier = _classifier("coding")
    assert await classifier.is_coding_request("создай файл X") is True


async def test_coding_label_with_punctuation_and_case() -> None:
    classifier = _classifier("Coding.")
    assert await classifier.is_coding_request("напиши тесты для Y") is True


@pytest.mark.parametrize("label", ["chat", "conversation", "", "  ", "maybe coding?"])
async def test_non_coding_labels_default_to_chat(label: str) -> None:
    classifier = _classifier(label)
    assert await classifier.is_coding_request("как дела?") is False


async def test_flaky_model_defaults_to_chat() -> None:
    classifier = _classifier("coding", raises=True)
    assert await classifier.is_coding_request("сделай рефакторинг") is False


async def test_uses_the_local_tier0_coding_intent_task() -> None:
    # The classifier must route on the CODING_INTENT task, which is pinned Tier-0
    # (cheap + keeps dev-intent local). A Tier-0-only router proves it never needs
    # Tier 1: the call succeeds with no Tier 1 provider wired.
    provider = _FakeProvider("coding")
    router = LLMRouter(providers={0: provider})
    classifier = ClassifyCodingIntent(router=router)

    assert await classifier.is_coding_request("поправь баг") is True
    assert provider.calls == 1
    assert TaskType.CODING_INTENT.value == "coding_intent"
