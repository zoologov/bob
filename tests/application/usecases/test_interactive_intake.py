# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for InteractiveIntakeRouter — DM intake into the live session (BOB-083 .4).

The router is the consume-gate + entry/exit command path for the interactive terminal.
🔴 Security invariants asserted here (owner-only + DM-only + mode-must-not-stick):

* an OWNER DM entry command (`/code -i <task>`) opens the session + emits the explicit
  "opened" mode line;
* the SAME command in a GROUP is refused (DM-only) — never opens;
* a NON-owner is refused (owner-only) — never opens / feeds;
* while the session is ACTIVE, an owner DM plain reply is fed to stdin and the turn is
  consumed (no normal Bob reply);
* an owner DM exit (`stop`) stops the session + emits the "closed" mode line;
* with NO active session a plain owner DM is NOT consumed (the gate is inert → normal
  Bob path) — the mode does not stick;
* a GROUP message never feeds an active session (DM-only).
"""

from __future__ import annotations

from bob.coding.usecases.coding_assistant import CodingOutcome
from bob.coding.usecases.interactive_intake import InteractiveIntakeRouter

_OWNER = 99
_GUEST = 7


class _FakeManager:
    """Fake interactive-session manager: records open/feed/stop, drives ``active``."""

    def __init__(self, *, active: bool = False) -> None:
        self._active = active
        self.opened: list[tuple[str, int | None]] = []
        self.fed: list[str] = []
        self.stopped: list[int | None] = []

    def active(self) -> bool:
        return self._active

    async def open(self, task: str, sender: int | None) -> CodingOutcome:
        self.opened.append((task, sender))
        self._active = True
        return CodingOutcome(ok=True, message="интерактив открыт", session=None)

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def stop(self, sender: int | None) -> CodingOutcome:
        self.stopped.append(sender)
        self._active = False
        return CodingOutcome(ok=True, message="интерактив закрыт", session=None)


class _FakeNotifier:
    """Records the mode lines the router emits to the owner's DM."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)


def _router(manager: _FakeManager) -> tuple[InteractiveIntakeRouter, _FakeNotifier]:
    notifier = _FakeNotifier()
    return InteractiveIntakeRouter(manager=manager, notifier=notifier), notifier


# --- entry command ---------------------------------------------------------------


async def test_owner_dm_entry_opens_session_and_emits_mode_line() -> None:
    manager = _FakeManager(active=False)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="/code -i почини баг", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.opened == [("почини баг", _OWNER)]
    assert notifier.sent == ["интерактив открыт"]


async def test_entry_in_group_is_refused_dm_only() -> None:
    manager = _FakeManager(active=False)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="/code -i почини баг", sender=_OWNER, is_owner=True, is_group=True
    )

    assert consumed is False
    assert manager.opened == []
    assert notifier.sent == []


async def test_entry_from_non_owner_is_refused() -> None:
    manager = _FakeManager(active=False)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="/code -i почини баг", sender=_GUEST, is_owner=False, is_group=False
    )

    assert consumed is False
    assert manager.opened == []
    assert notifier.sent == []


# --- steer consume-gate ----------------------------------------------------------


async def test_active_session_feeds_owner_dm_plain_text_and_consumes() -> None:
    manager = _FakeManager(active=True)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="теперь добавь тест", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.fed == ["теперь добавь тест"]
    assert notifier.sent == []  # steer is silent (claude output streams elsewhere)


async def test_active_session_exit_stops_and_emits_mode_line() -> None:
    manager = _FakeManager(active=True)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="stop", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.stopped == [_OWNER]
    assert manager.fed == []  # exit is checked BEFORE feed
    assert notifier.sent == ["интерактив закрыт"]


async def test_no_active_session_plain_dm_is_not_consumed() -> None:
    # 🔴 Mode must not stick: with no live session the gate is inert → normal Bob path.
    manager = _FakeManager(active=False)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="привет, как дела", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.fed == []


async def test_group_message_never_feeds_active_session() -> None:
    # DM-only: even with a live session an owner GROUP message is never fed to stdin.
    manager = _FakeManager(active=True)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="теперь добавь тест", sender=_OWNER, is_owner=True, is_group=True
    )

    assert consumed is False
    assert manager.fed == []


async def test_non_owner_never_feeds_active_session() -> None:
    # Owner-only: a guest DM never steers a live session the owner opened.
    manager = _FakeManager(active=True)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="rm -rf /", sender=_GUEST, is_owner=False, is_group=False
    )

    assert consumed is False
    assert manager.fed == []
