# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ClassifyWorkTalk — the cheap Tier-0 «this turn is about dev work?» classifier.

The register-recall counterpart of the coding-intent classifier (BOB-087.C2): it asks the
router (one-word ``work``/``chat``) on the local Tier-0 path so the owner's DIRECT question
(«как продвигается разработка?») is recognised in ANY chat and lifts the turn into the DEV
register. Conservative like its sibling: only an exact ``work`` answer counts; any other
word, garbage, or a flaky model defaults to chat (``False``), so a misread never spuriously
mutes casual recall the wrong way.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRouter, TaskType
from bob.memory.usecases.classify_work_talk import (
    ClassifyWorkTalk,
    parse_work_talk_verdict,
)

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


def _classifier(label: str, *, raises: bool = False) -> ClassifyWorkTalk:
    provider = _FakeProvider(label, raises=raises)
    router = LLMRouter(providers={0: provider})
    return ClassifyWorkTalk(router=router)


# --- parse_work_talk_verdict: the pure verdict parser (mutation target) -------


def test_parse_exact_work_label_is_true() -> None:
    assert parse_work_talk_verdict("work") is True


@pytest.mark.parametrize("label", ["Work.", " WORK\n", "work!"])
def test_parse_work_label_with_case_and_punctuation(label: str) -> None:
    assert parse_work_talk_verdict(label) is True


@pytest.mark.parametrize(
    "label", ["chat", "conversation", "", "  ", "work stuff", "not work"]
)
def test_parse_non_work_labels_are_false(label: str) -> None:
    assert parse_work_talk_verdict(label) is False


# --- ClassifyWorkTalk: the Tier-0 classifier ---------------------------------


async def test_exact_work_label_is_work_talk() -> None:
    classifier = _classifier("work")
    assert await classifier.is_work_talk("как продвигается разработка?") is True


async def test_non_work_labels_default_to_chat() -> None:
    classifier = _classifier("chat")
    assert await classifier.is_work_talk("как погода?") is False


async def test_flaky_model_defaults_to_chat() -> None:
    classifier = _classifier("work", raises=True)
    assert await classifier.is_work_talk("что там по коду?") is False


async def test_uses_the_local_tier0_work_talk_task() -> None:
    provider = _FakeProvider("work")
    router = LLMRouter(providers={0: provider})
    classifier = ClassifyWorkTalk(router=router)

    assert await classifier.is_work_talk("что нового построил?") is True
    assert provider.calls == 1
    assert TaskType.WORK_TALK.value == "work_talk"
