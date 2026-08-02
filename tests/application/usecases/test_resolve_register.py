# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for RegisterResolver — per-turn DEV/CASUAL resolution (BOB-087.C2).

Mirrors ``HandleMessage._surface_audience``: a small collaborator that resolves the
conversational register of a turn. DEV if EITHER a deterministic signal (the turn is in the
dev-DM chat) OR the Tier-0 «is this about dev work?» classifier says so; otherwise CASUAL.
🔴 Optimisation: the classifier fires ONLY when the recall pool actually holds work episodes
(``pool_has_work``) — no work to mute, no Tier-0 burned; the register is CASUAL (or DEV by
the deterministic signal), and the register filter is a no-op.
"""

from __future__ import annotations

from bob.application.runtime.events import MessageReceived
from bob.memory.register import Register
from bob.memory.usecases.resolve_register import RegisterResolver


class _FakeWorkTalk:
    """A ClassifyWorkTalk double returning a scripted verdict and counting calls."""

    def __init__(self, verdict: bool) -> None:
        self._verdict = verdict
        self.calls = 0

    async def is_work_talk(self, text: str) -> bool:  # noqa: ARG002
        self.calls += 1
        return self._verdict


def _event(*, chat_id: int) -> MessageReceived:
    return MessageReceived(
        update_id=1, chat_id=chat_id, message_id=1, text="как там разработка?",
        sender_id=1, sender_name="Влад", is_group=False,
    )


def _resolver(verdict: bool, *, dev_dm_chat_id: int | None) -> tuple[
    RegisterResolver, _FakeWorkTalk
]:
    classifier = _FakeWorkTalk(verdict)
    resolver = RegisterResolver(
        classify_work_talk=classifier, dev_dm_chat_id=dev_dm_chat_id
    )
    return resolver, classifier


async def test_dev_dm_chat_is_dev_without_calling_classifier() -> None:
    # Deterministic signal wins: a turn in the dev-DM chat is DEV, classifier untouched.
    resolver, classifier = _resolver(False, dev_dm_chat_id=42)
    register = await resolver.resolve(_event(chat_id=42), pool_has_work=True)
    assert register is Register.DEV
    assert classifier.calls == 0


async def test_classifier_lifts_to_dev_when_pool_has_work() -> None:
    resolver, classifier = _resolver(True, dev_dm_chat_id=42)
    register = await resolver.resolve(_event(chat_id=7), pool_has_work=True)
    assert register is Register.DEV
    assert classifier.calls == 1


async def test_classifier_says_chat_stays_casual() -> None:
    resolver, classifier = _resolver(False, dev_dm_chat_id=42)
    register = await resolver.resolve(_event(chat_id=7), pool_has_work=True)
    assert register is Register.CASUAL
    assert classifier.calls == 1


async def test_no_work_in_pool_skips_the_classifier() -> None:
    # 🔴 The optimisation: no work episodes → don't burn Tier-0; register is CASUAL.
    resolver, classifier = _resolver(True, dev_dm_chat_id=42)
    register = await resolver.resolve(_event(chat_id=7), pool_has_work=False)
    assert register is Register.CASUAL
    assert classifier.calls == 0


async def test_dev_dm_wins_even_with_no_work_in_pool() -> None:
    # The deterministic signal does not depend on pool contents.
    resolver, classifier = _resolver(False, dev_dm_chat_id=42)
    register = await resolver.resolve(_event(chat_id=42), pool_has_work=False)
    assert register is Register.DEV
    assert classifier.calls == 0


async def test_no_dev_dm_configured_relies_on_classifier() -> None:
    resolver, classifier = _resolver(True, dev_dm_chat_id=None)
    register = await resolver.resolve(_event(chat_id=7), pool_has_work=True)
    assert register is Register.DEV
    assert classifier.calls == 1
