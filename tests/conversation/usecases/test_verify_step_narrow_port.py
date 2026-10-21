# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""The verify step depends on the NARROW consumer-side port, not on capabilities (BOB-113 E).

``VerifyStep`` reads exactly one field of a search result — ``answer`` — so its contract is
:class:`~bob.conversation.ports.VerifySearch` (``search(query) -> HasAnswer``), declared in
the conversation vertical (ISP). These tests prove both directions of that contract:

* a fake that has ONLY ``search()`` returning an object with ONLY ``answer`` drives the
  grounded note — it is NOT a ``WebSearchResult`` and knows nothing of ``sources``; under
  ``mypy tests/`` this file type-checks only while ``VerifyStep`` asks for the narrow port;
* the capabilities result (``WebSearchResult``, a frozen dataclass) still satisfies the
  narrow view structurally, so the existing adapter wires in unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.capabilities.ports import WebSearchResult
from bob.conversation.usecases.verify_step import (
    _VERIFY_GROUNDED_NOTE,
    VerifyInterimAnnouncer,
    VerifyStep,
)

if TYPE_CHECKING:
    from bob.conversation.ports import HasAnswer, VerifySearch


class _AnswerOnly:
    """A search result that carries ``answer`` and nothing else (no ``sources``)."""

    def __init__(self, answer: str) -> None:
        self.answer = answer


class _AnswerOnlySearch:
    """The minimal verify search: ``search()`` → an object with only ``answer``."""

    def __init__(self, answer: str) -> None:
        self._answer = answer
        self.queries: list[str] = []

    async def search(self, query: str) -> _AnswerOnly:
        self.queries.append(query)
        return _AnswerOnly(self._answer)


class _CapabilitiesShapedSearch:
    """A search shaped like the capabilities port (returns a ``WebSearchResult``)."""

    async def search(self, query: str) -> WebSearchResult:
        return WebSearchResult(answer=f"ставка 21% ({query})")


def _no_announcer(*, chat_id: int, sender_name: str) -> VerifyInterimAnnouncer:
    raise AssertionError("no interim without chat_id")


def _step(provider: VerifySearch) -> VerifyStep:
    return VerifyStep(
        verify_judge=None,
        verify_provider=provider,
        verify_timeout_seconds=1.0,
        announcer_factory=_no_announcer,
    )


@pytest.mark.asyncio
async def test_answer_only_fake_grounds_the_note() -> None:
    provider = _AnswerOnlySearch(answer="  сейчас 21%  ")

    note = await _step(provider).note("какая ставка?", [], forced=True)

    assert note == _VERIFY_GROUNDED_NOTE.format(answer="сейчас 21%")
    assert provider.queries == ["какая ставка?"]


@pytest.mark.asyncio
async def test_capabilities_result_satisfies_the_narrow_view() -> None:
    # A frozen-dataclass result (read-only ``answer``) must fit ``HasAnswer`` — otherwise
    # the real capabilities adapter would no longer wire into the verify step.
    result: HasAnswer = await _CapabilitiesShapedSearch().search("q")

    note = await _step(_CapabilitiesShapedSearch()).note("q", [], forced=True)

    assert result.answer == "ставка 21% (q)"
    assert note == _VERIFY_GROUNDED_NOTE.format(answer="ставка 21% (q)")
