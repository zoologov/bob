# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the register-recall wiring — the flag switch for register-aware recall.

The register-recall path (BOB-087.C) ships inert behind the bare ``memory.register_recall``
flag (mirroring ``memory.work_journal``). This module is the ONE place the flag is read:

* ``build_register_resolver`` — OFF (the default) → ``None`` (``HandleMessage`` keeps the
  byte-identical recall, over-fetch off, INV-5); ON → a real :class:`RegisterResolver` over
  the Tier-0 :class:`ClassifyWorkTalk` judge plus the deterministic dev-DM signal.
* ``build_secondary_recall`` (BOB-087.C8) — OFF → the SAME recall object (identity, so every
  secondary door behaves byte-identically); ON → a :class:`CasualFloorRecall` holding those
  doors at the conservative CASUAL floor.

🔴 Recall stays byte-identical until the owner switches the flag on, so the default stays OFF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.memory.adapters.casual_floor_recall import CasualFloorRecall
from bob.memory.usecases.classify_work_talk import ClassifyWorkTalk
from bob.memory.usecases.resolve_register import RegisterResolver
from bob.runtime.wiring.register_recall import (
    build_register_resolver,
    build_secondary_recall,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

    from bob.kernel.episode_types import Recalled


class _StubProvider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:  # pragma: no cover - never called in wiring
        raise AssertionError("the classifier is not consulted during wiring")


def _router() -> LLMRouter:
    return LLMRouter(providers={0: _StubProvider()})


def _build(config: Mapping[str, object], *, owner_id: int = 42) -> RegisterResolver | None:
    return build_register_resolver(config, router=_router(), owner_id=owner_id)


def test_flag_off_yields_none() -> None:
    assert _build({}) is None


def test_flag_off_explicit_false_yields_none() -> None:
    assert _build({"memory": {"register_recall": False}}) is None


def test_flag_on_builds_resolver_over_work_talk_classifier() -> None:
    resolver = _build({"memory": {"register_recall": True}})
    assert isinstance(resolver, RegisterResolver)
    assert isinstance(resolver._classify, ClassifyWorkTalk)


def test_flag_on_without_dev_channel_leans_on_classifier_only() -> None:
    # No dev-DM channel active (coder.dev_dm / interactive off) → the deterministic dev
    # signal is not cleanly available, so the resolver has no dev-DM chat id and relies on
    # the Tier-0 classifier alone.
    resolver = _build({"memory": {"register_recall": True}})
    assert isinstance(resolver, RegisterResolver)
    assert resolver._dev_dm_chat_id is None


def test_flag_on_with_dev_dm_uses_configured_chat_id() -> None:
    resolver = _build(
        {
            "memory": {"register_recall": True},
            "coder": {"dev_dm": True, "dev_dm_chat_id": 777},
        }
    )
    assert isinstance(resolver, RegisterResolver)
    assert resolver._dev_dm_chat_id == 777


def test_flag_on_with_dev_dm_defaults_chat_id_to_owner() -> None:
    resolver = _build(
        {"memory": {"register_recall": True}, "coder": {"dev_dm": True}}, owner_id=99
    )
    assert isinstance(resolver, RegisterResolver)
    assert resolver._dev_dm_chat_id == 99


class _StubRecall:
    async def recall(
        self,
        query: str,  # noqa: ARG002
        *,
        k: int,  # noqa: ARG002
        surface_old: bool = False,  # noqa: ARG002
    ) -> Sequence[Recalled]:  # pragma: no cover - never called in wiring
        raise AssertionError("recall is not consulted during wiring")


def test_secondary_recall_flag_off_is_the_same_recall_object() -> None:
    # INV-5 for every secondary door: OFF hands back the very same port, so the
    # grounded-addon callback / memory tools / proactive seed are byte-identical.
    recall = _StubRecall()
    assert build_secondary_recall({}, recall=recall) is recall


def test_secondary_recall_flag_off_explicit_false_is_the_same_recall_object() -> None:
    recall = _StubRecall()
    config = {"memory": {"register_recall": False}}
    assert build_secondary_recall(config, recall=recall) is recall


def test_secondary_recall_flag_on_wraps_in_the_casual_floor() -> None:
    recall = _StubRecall()
    floored = build_secondary_recall({"memory": {"register_recall": True}}, recall=recall)
    assert isinstance(floored, CasualFloorRecall)
    assert floored._inner is recall


def test_flag_on_with_interactive_channel_uses_dev_dm_chat_id() -> None:
    # The interactive DM session (coder.interactive) is a dev channel too → its chat id is
    # the deterministic dev signal even without coder.dev_dm.
    resolver = _build(
        {
            "memory": {"register_recall": True},
            "coder": {"interactive": True, "dev_dm_chat_id": 555},
        }
    )
    assert isinstance(resolver, RegisterResolver)
    assert resolver._dev_dm_chat_id == 555
