# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_interactive_session`` — the interactive-terminal wiring switch (BOB-083 .3).

The live, bidirectional ``claude`` terminal ships inert behind the ``coder.interactive``
flag (default off, mirroring ``coder.dev_dm`` / ``coder.nl_autostart``). This builder is
the ONE place the flag is read: off → ``None`` (the ``.4`` intake mode stays inert); on →
an :class:`InteractiveSessionManager` that reuses the isolated worktree + DM live-stream
and has NO PR-opener (it physically cannot merge / push main, INV-2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.usecases.interactive_session import InteractiveSessionManager
from bob.runtime.wiring.coding import _build_interactive_session

if TYPE_CHECKING:
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder — the manager is assembled, never sent through, during wiring."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 1, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": _bot(),
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def test_flag_off_yields_no_manager() -> None:
    assert _build_interactive_session({}, **_deps()) is None  # type: ignore[arg-type]


def test_flag_off_explicit_false_yields_no_manager() -> None:
    config = {"coder": {"interactive": False}}
    assert _build_interactive_session(config, **_deps()) is None  # type: ignore[arg-type]


def test_flag_on_builds_the_manager() -> None:
    config = {"coder": {"interactive": True}}
    manager = _build_interactive_session(config, **_deps())  # type: ignore[arg-type]
    assert isinstance(manager, InteractiveSessionManager)
    # Built idle: no live session until an owner opens one (the ``.4`` intake mode drives it).
    assert manager.active() is False
