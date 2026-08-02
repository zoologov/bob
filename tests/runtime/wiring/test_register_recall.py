# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_register_resolver`` — the flag switch for register-aware recall.

The register-recall path (BOB-087.C) ships inert behind the bare ``memory.register_recall``
flag (mirroring ``memory.work_journal``). This builder is the ONE place the flag is read:
OFF (the default) → ``None`` (``HandleMessage`` keeps the byte-identical recall, over-fetch
off, INV-5); ON → a real :class:`RegisterResolver` over the Tier-0
:class:`ClassifyWorkTalk` judge plus the deterministic dev-DM signal.
🔴 Recall stays byte-identical until the owner switches the flag on, so the default stays OFF.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.memory.usecases.classify_work_talk import ClassifyWorkTalk
from bob.memory.usecases.resolve_register import RegisterResolver
from bob.runtime.wiring.register_recall import build_register_resolver

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


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
