# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``coder.resume`` wiring (BOB-087.D3).

Resuming a stopped session in a LONG-LIVED workspace is the most powerful move of the
interactive seam (a live claude landing in an accumulated tree), so it ships behind its
own flag, default OFF. This builder pair is the ONE place the flag is read:

* 🔴 OFF (the default) → the manager gets NO resume seams (lookup / persistent workspace)
  and the intake router gets NO resume support, so ``/resume …`` is not a command at all:
  the turn is NOT consumed, nothing is looked up and nothing is spawned — byte-identical
  to BOB-083;
* ON → both are wired, so the owner's explicit command reaches the two-step
  confirmation flow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from bob.coding.usecases.coding_assistant import CodingOutcome
from bob.runtime.wiring.coding import (
    _build_interactive_intake,
)
from bob.runtime.wiring.coding import (
    _build_interactive_session as _wire_build_interactive_session,
)
from tests.support.wiring_clone_root import with_a_throwaway_clone_root

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.interactive.usecases.session import InteractiveSessionManager
    from bob.kernel.ports import Clock
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732


class _StubBot:
    """A bot placeholder that swallows the mode line the router emits at the boundary."""

    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send_rich_message(
        self,
        *,
        chat_id: int,
        rich_message: object,
        message_thread_id: int | None = None,
    ) -> None:
        self.sent.append((chat_id, rich_message, message_thread_id))


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


class _RecordingManager:
    """Records what the intake router drives — the resume seam is structural here."""

    def __init__(self) -> None:
        self.proposed: list[tuple[str, int | None]] = []
        self.resolved: list[tuple[str, int | None]] = []
        self.opened: list[tuple[str, int | None]] = []
        self.workspaces: list[tuple[str, str, int | None]] = []
        self.fed: list[str] = []

    async def open_workspace(
        self, name: str, task: str, sender: int | None
    ) -> CodingOutcome:
        self.workspaces.append((name, task, sender))
        return CodingOutcome(ok=True, message="открыл", session=None)

    def active(self) -> bool:
        return False

    async def open(self, task: str, sender: int | None) -> CodingOutcome:
        self.opened.append((task, sender))
        return CodingOutcome(ok=True, message="", session=None)

    async def feed(self, text: str) -> None:
        self.fed.append(text)

    async def resolve_pending_permission(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None:
        # Срез 3: у этого дублёра вопросов о разрешении не бывает — ход идёт дальше.
        return None

    async def stop(self, sender: int | None) -> CodingOutcome:
        return CodingOutcome(ok=True, message="", session=None)

    async def propose_resume(self, name: str, sender: int | None) -> CodingOutcome:
        self.proposed.append((name, sender))
        return CodingOutcome(ok=True, message="поднимаю?", session=None)

    async def resolve_pending_resume(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None:
        self.resolved.append((text, sender))
        return None


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _session_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": _bot(),
        "stream_bot": _bot(),
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def _manager(config: dict[str, object]) -> InteractiveSessionManager:
    manager = _build_interactive_session(config, **_session_deps())
    assert manager is not None
    return manager


def _intake(config: dict[str, object], manager: _RecordingManager) -> object:
    router = _build_interactive_intake(
        config,
        manager=cast("InteractiveSessionManager", manager),
        bot=_bot(),
        owner_id=_OWNER_ID,
    )
    assert router is not None
    return router


# 🔴 Файлы окружения спавна — в ОДНОРАЗОВЫЙ каталог, а не в рабочее дерево (bob-c3r.1).
# С безопасной дорогой по умолчанию сборка материализует их на КАЖДОМ вызове, а предмет
# этого файла — другой; поэтому строители здесь затенены обёрткой, подставляющей
# ``coder.clone_root``. Значение, заданное самим тестом, уважается как есть.


def _build_interactive_session(
    config: Mapping[str, object], **deps: object
) -> InteractiveSessionManager | None:
    """Как продакшн-строитель, но с одноразовым ``clone_root`` (см. комментарий выше)."""
    return _wire_build_interactive_session(
        with_a_throwaway_clone_root(config),
        **deps,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# OFF path (default) — byte-identical to BOB-083
# --------------------------------------------------------------------------- #


async def test_default_wiring_does_not_consume_the_resume_command() -> None:
    # 🔴 The proof of the inert OFF path, at the boundary: `/resume …` behaves like any
    # other plain DM — it is not consumed, so the normal Bob chat path answers it.
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True}}, manager)

    consumed = await router.route(  # type: ignore[attr-defined]
        text="/resume epic-bob-087", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.proposed == []
    assert manager.resolved == []  # the resume seam is not even consulted
    assert manager.opened == []
    assert manager.fed == []


async def test_default_wiring_leaves_the_manager_resume_path_inert() -> None:
    # No lookup / persistent workspace injected → resume answers inertly and (crucially)
    # never touches the database: the stub connection would explode if it did.
    manager = _manager({"coder": {"interactive": True}})

    outcome = await manager.propose_resume("epic-bob-087", _OWNER_ID)

    assert outcome.ok is False
    assert outcome.message == ""
    assert await manager.resolve_pending_resume("да", _OWNER_ID) is None


async def test_explicit_false_stays_inert() -> None:
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True, "resume": False}}, manager)

    consumed = await router.route(  # type: ignore[attr-defined]
        text="/resume epic-bob-087", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.proposed == []


# --------------------------------------------------------------------------- #
# ON path — the owner opted in, explicitly
# --------------------------------------------------------------------------- #


async def test_resume_flag_wires_the_command_into_the_confirmation_flow() -> None:
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True, "resume": True}}, manager)

    consumed = await router.route(  # type: ignore[attr-defined]
        text="/resume epic-bob-087", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.proposed == [("epic-bob-087", _OWNER_ID)]
    assert manager.opened == []  # 🔴 the command asks; it never spawns


async def test_resume_flag_wires_the_pending_answer_path() -> None:
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True, "resume": True}}, manager)

    await router.route(  # type: ignore[attr-defined]
        text="да", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert manager.resolved == [("да", _OWNER_ID)]


async def test_default_wiring_does_not_consume_the_workspace_command() -> None:
    # 🔴 BOB-087.D5b (M3): открытие ДОЛГОЖИВУЩЕГО рабочего места живёт под тем же флагом —
    # OFF → команда не распознаётся, дерево не заводится, ход идёт обычным путём.
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True}}, manager)

    consumed = await router.route(  # type: ignore[attr-defined]
        text="/workspace BOB-087 срез D", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.workspaces == []


async def test_resume_flag_wires_the_workspace_open_command() -> None:
    manager = _RecordingManager()
    router = _intake({"coder": {"interactive": True, "resume": True}}, manager)

    consumed = await router.route(  # type: ignore[attr-defined]
        text="/workspace BOB-087 срез D", sender=_OWNER_ID, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.workspaces == [("BOB-087", "срез D", _OWNER_ID)]
    assert manager.opened == []  # 🔴 не эфемерный путь


def test_resume_flag_injects_the_lookup_and_persistent_workspace() -> None:
    manager = _manager({"coder": {"interactive": True, "resume": True}})

    assert manager._lookup is not None
    assert manager._workspace is not None


def test_default_manager_has_no_resume_seams() -> None:
    manager = _manager({"coder": {"interactive": True}})

    assert manager._lookup is None
    assert manager._workspace is None
