# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_staleness_reassessor`` — the composition-root switch for the врезка.

The staleness врезка (BOB-066 Срез W.3) ships inert behind ``presence.staleness``. This builder
is the ONE place the flag is read: off → ``None`` (Bob sends every draft as before,
byte-identical); on → the reassessor over the Tier-0 judge + the pure gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.application.runtime.staleness_reassessor import StalenessReassessor
from bob.runtime.wiring.staleness import build_staleness_reassessor, staleness_enabled

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


class _StubProvider:
    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],  # noqa: ARG002
        *,
        stream: bool = False,  # noqa: ARG002
    ) -> str | AsyncIterator[str]:  # pragma: no cover - never called in wiring
        raise AssertionError("the judge is not consulted during wiring")


def _router() -> LLMRouter:
    return LLMRouter(providers={0: _StubProvider()})


def test_flag_off_yields_no_reassessor() -> None:
    assert build_staleness_reassessor({}, router=_router()) is None
    assert staleness_enabled({}) is False


def test_flag_on_builds_the_reassessor() -> None:
    config = {"presence": {"staleness": {"enabled": True}}}
    reassessor = build_staleness_reassessor(config, router=_router())
    assert isinstance(reassessor, StalenessReassessor)
    assert staleness_enabled(config) is True
