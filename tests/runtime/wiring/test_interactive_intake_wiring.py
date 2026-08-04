# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``_build_interactive_intake`` — the interactive-intake wiring (BOB-083 .4).

The intake router is built ONLY when the interactive-session manager is wired
(``coder.interactive`` on): no manager → ``None`` (HandleMessage's intake gate stays inert,
the mode is entirely unavailable); a manager → an :class:`InteractiveIntakeRouter` that
pairs the live session with a DM-targeted owner-notifier for the explicit mode lines.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from bob.interactive.usecases.intake import InteractiveIntakeRouter
from bob.runtime.wiring.coding import _build_interactive_intake

if TYPE_CHECKING:
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.interactive.usecases.session import InteractiveSessionManager

_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder — the notifier is assembled, never sent through, at wiring."""


class _StubManager:
    """A manager placeholder — the router only retains it at wiring, never calls it."""


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def test_no_manager_yields_no_router() -> None:
    router = _build_interactive_intake(
        {"coder": {"interactive": False}},
        manager=None,
        bot=_bot(),
        owner_id=_OWNER_ID,
    )
    assert router is None


def test_manager_present_builds_the_router() -> None:
    router = _build_interactive_intake(
        {"coder": {"interactive": True}},
        manager=cast("InteractiveSessionManager", _StubManager()),
        bot=_bot(),
        owner_id=_OWNER_ID,
    )
    assert isinstance(router, InteractiveIntakeRouter)
