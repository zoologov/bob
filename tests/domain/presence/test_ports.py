# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the presence ports — the OutgoingActivityStore seam (DDD contract).

The rhythm layer talks to durable state only through the structural
:class:`~bob.presence.ports.OutgoingActivityStore` Protocol. These tests pin the
seam itself: a store that offers ``load`` satisfies it, one that does not is
rejected, and the concrete episodic adapter is a structural implementation of the
domain port — so the composition root can bind it without an ABC.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.presence.adapters.outgoing_activity_store import EpisodicOutgoingActivityStore
from bob.presence.ports import OutgoingActivityStore, StalenessJudge

if TYPE_CHECKING:
    from bob.presence.outgoing_activity import OutgoingActivity
    from bob.presence.staleness import StalenessContext, StalenessReading


class _ConformingStore:
    """A store shaped exactly like the port (async ``load(chat_id)``)."""

    async def load(self, chat_id: int) -> OutgoingActivity:
        raise NotImplementedError


class _WrongMethodStore:
    """A store that offers the wrong method name — must NOT satisfy the port."""

    async def fetch(self, chat_id: int) -> None:  # noqa: ARG002
        return None


def test_store_with_load_satisfies_the_port() -> None:
    # Arrange / Act / Assert: a runtime_checkable Protocol admits by structure.
    assert isinstance(_ConformingStore(), OutgoingActivityStore)


def test_store_without_load_does_not_satisfy_the_port() -> None:
    # Arrange / Act / Assert: the seam is named — a differently-named method is not it.
    assert not isinstance(_WrongMethodStore(), OutgoingActivityStore)


def test_episodic_adapter_is_a_structural_implementation_of_the_port() -> None:
    # Arrange / Act / Assert: the concrete infra adapter the composition root binds
    # conforms to the domain port with no explicit inheritance.
    assert issubclass(EpisodicOutgoingActivityStore, OutgoingActivityStore)


class _ConformingJudge:
    """A judge shaped exactly like the port (async ``assess(ctx)``)."""

    async def assess(self, ctx: StalenessContext) -> StalenessReading:
        raise NotImplementedError


class _WrongMethodJudge:
    """A judge that offers the wrong method name — must NOT satisfy the port."""

    async def read(self, ctx: StalenessContext) -> None:  # noqa: ARG002
        return None


def test_judge_with_assess_satisfies_the_port() -> None:
    # Arrange / Act / Assert: the staleness judge seam admits by structure.
    assert isinstance(_ConformingJudge(), StalenessJudge)


def test_judge_without_assess_does_not_satisfy_the_port() -> None:
    # Arrange / Act / Assert: a differently-named method is not the named seam.
    assert not isinstance(_WrongMethodJudge(), StalenessJudge)
