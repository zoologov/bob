# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_disclosure_guard`` — the composition-root switch for такт разглашения.

The tactful-withhold врезка (BOB-066 Срез W.4) ships inert behind ``presence.tact``. This
builder is the ONE place the flag is read: off → ``None`` (a guest turn composes exactly as
before, byte-identical); on → the guard over the safe-default-guarded Tier-0 privilege judge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRouter
from bob.application.usecases.disclosure_guard import DisclosureGuard
from bob.runtime.wiring.disclosure import build_disclosure_guard

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


def test_flag_off_yields_no_guard() -> None:
    assert build_disclosure_guard({}, router=_router()) is None


def test_flag_on_builds_the_guard() -> None:
    config = {"presence": {"tact": {"enabled": True}}}
    guard = build_disclosure_guard(
        config, router=_router(), capability_hints=("web_search",)
    )
    assert isinstance(guard, DisclosureGuard)
