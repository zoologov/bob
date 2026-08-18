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
from bob.interactive.usecases.intake import InteractiveIntakeRouter

_OWNER = 99
_GUEST = 7


class _FakeManager:
    """Fake interactive-session manager: records open/feed/stop, drives ``active``."""

    def __init__(
        self, *, active: bool = False, permission: CodingOutcome | None = None
    ) -> None:
        self._active = active
        self.opened: list[tuple[str, int | None]] = []
        self.fed: list[str] = []
        self.stopped: list[int | None] = []
        self.asked_permission: list[tuple[str, int | None]] = []
        self._permission = permission

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

    async def resolve_pending_permission(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None:
        self.asked_permission.append((text, sender))
        return self._permission


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


# --- resume path (BOB-087.D3): OFF by default, two-step when wired ---------------


class _FakeResume:
    """Fake resume seam: records the proposal / the pending resolution the router drives."""

    def __init__(self, *, settle: CodingOutcome | None = None) -> None:
        self.proposed: list[tuple[str, int | None]] = []
        self.resolved: list[tuple[str, int | None]] = []
        self.workspaces: list[tuple[str, str, int | None]] = []
        self._settle = settle

    async def open_workspace(
        self, name: str, task: str, sender: int | None
    ) -> CodingOutcome:
        self.workspaces.append((name, task, sender))
        return CodingOutcome(ok=True, message="открыл рабочее место", session=None)

    async def propose_resume(self, name: str, sender: int | None) -> CodingOutcome:
        self.proposed.append((name, sender))
        return CodingOutcome(ok=True, message="поднимаю?", session=None)

    async def resolve_pending_resume(
        self, text: str, sender: int | None
    ) -> CodingOutcome | None:
        self.resolved.append((text, sender))
        return self._settle


def _resume_router(
    manager: _FakeManager, resume: _FakeResume
) -> tuple[InteractiveIntakeRouter, _FakeNotifier]:
    notifier = _FakeNotifier()
    router = InteractiveIntakeRouter(
        manager=manager, notifier=notifier, resume=resume
    )
    return router, notifier


async def test_resume_command_is_inert_when_the_flag_is_off() -> None:
    # 🔴 OFF path (default): the router holds NO resume seam, so `/resume …` is not a
    # command at all — the turn is not consumed and nothing is raised (byte-identical
    # to BOB-083: with no live session a plain message goes to the normal Bob path).
    manager = _FakeManager(active=False)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="/resume epic-bob-087", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.opened == []
    assert manager.fed == []
    assert notifier.sent == []


async def test_resume_command_with_a_live_session_is_only_steered_when_off() -> None:
    # OFF + a live session: the text is just another steer reply (unchanged BOB-083).
    manager = _FakeManager(active=True)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="/resume epic-bob-087", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.fed == ["/resume epic-bob-087"]


async def test_owner_dm_resume_command_asks_for_confirmation() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume()
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="/resume epic-bob-087", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert resume.proposed == [("epic-bob-087", _OWNER)]
    assert notifier.sent == ["поднимаю?"]
    assert manager.opened == []  # 🔴 nothing is opened by the command itself


async def test_resume_command_in_a_group_is_refused_dm_only() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume()
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="/resume epic-bob-087", sender=_OWNER, is_owner=True, is_group=True
    )

    assert consumed is False
    assert resume.proposed == []
    assert resume.resolved == []
    assert notifier.sent == []


async def test_resume_command_from_a_non_owner_is_refused() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume()
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="/resume epic-bob-087", sender=_GUEST, is_owner=False, is_group=False
    )

    assert consumed is False
    assert resume.proposed == []
    assert resume.resolved == []
    assert notifier.sent == []


async def test_workspace_command_is_inert_when_the_flag_is_off() -> None:
    # 🔴 Тот же флаг ``coder.resume``: OFF → seam'а нет, `/workspace …` не команда.
    manager = _FakeManager(active=False)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="/workspace BOB-087 срез D", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is False
    assert manager.opened == []
    assert notifier.sent == []


async def test_owner_dm_workspace_command_opens_the_persistent_workspace() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume()
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="/workspace BOB-087 срез D", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert resume.workspaces == [("BOB-087", "срез D", _OWNER)]
    assert notifier.sent == ["открыл рабочее место"]
    # 🔴 It went down the PERSISTENT path, not the ephemeral ``open``.
    assert manager.opened == []


async def test_workspace_command_in_a_group_or_from_a_guest_is_refused() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume()
    router, notifier = _resume_router(manager, resume)

    in_group = await router.route(
        text="/workspace BOB-087", sender=_OWNER, is_owner=True, is_group=True
    )
    from_guest = await router.route(
        text="/workspace BOB-087", sender=_GUEST, is_owner=False, is_group=False
    )

    assert (in_group, from_guest) == (False, False)
    assert resume.workspaces == []
    assert notifier.sent == []


async def test_a_settled_confirmation_is_emitted_and_consumes_the_turn() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume(
        settle=CodingOutcome(ok=True, message="поднял", session=None)
    )
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="да", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert resume.resolved == [("да", _OWNER)]
    assert notifier.sent == ["поднял"]


async def test_an_unsettled_turn_falls_through_to_the_normal_path() -> None:
    # 🔴 The pending question must not swallow unrelated turns: when the resume seam
    # does not settle the message, the router carries on exactly as before.
    manager = _FakeManager(active=False)
    resume = _FakeResume(settle=None)
    router, notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="привет, как дела", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is False
    assert resume.resolved == [("привет, как дела", _OWNER)]
    assert notifier.sent == []


async def test_an_unsettled_entry_command_still_opens_a_session() -> None:
    manager = _FakeManager(active=False)
    resume = _FakeResume(settle=None)
    router, _notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="/code -i почини баг", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.opened == [("почини баг", _OWNER)]


async def test_a_live_session_steer_still_reaches_stdin_with_resume_wired() -> None:
    manager = _FakeManager(active=True)
    resume = _FakeResume(settle=None)
    router, _notifier = _resume_router(manager, resume)

    consumed = await router.route(
        text="теперь добавь тест", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.fed == ["теперь добавь тест"]


# --- ответ на вопрос о разрешении (BOB-088, срез 3) ------------------------------
#
# 🔴 ВТОРОЙ ВХОД этого среза, и без него вся работа была бы вакуумной: при ЖИВОМ сеансе
# роутер отдаёт ЛЮБОЙ плоский текст владельца в stdin claude. Значит его «да», сказанное
# в ответ на «упёрся в запрет, разрешаешь?», по умолчанию прочитал бы claude, а не Боб —
# вопрос завис бы навсегда, а менеджер, у которого тесты зелёные, так и не узнал бы, что
# ему ответили. Ответ обязан перехватываться ДО feed.


async def test_the_owners_yes_answers_bob_and_does_not_reach_claude_stdin() -> None:
    manager = _FakeManager(
        active=True,
        permission=CodingOutcome(ok=True, message="Понял, делаю", session=None),
    )
    router, notifier = _router(manager)

    consumed = await router.route(
        text="да", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.asked_permission == [("да", _OWNER)]
    assert manager.fed == []  # 🔴 в stdin сессии не ушло НИЧЕГО
    assert notifier.sent == ["Понял, делаю"]


async def test_a_turn_that_is_not_an_answer_still_steers_the_session() -> None:
    manager = _FakeManager(active=True, permission=None)
    router, notifier = _router(manager)

    consumed = await router.route(
        text="покажи дифф", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.asked_permission == [("покажи дифф", _OWNER)]
    assert manager.fed == ["покажи дифф"]
    assert notifier.sent == []


async def test_a_guest_never_answers_the_owners_permission_question() -> None:
    manager = _FakeManager(active=True, permission=None)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="да", sender=_GUEST, is_owner=False, is_group=False
    )

    assert consumed is False
    assert manager.asked_permission == []
    assert manager.fed == []


async def test_an_exit_command_is_still_an_exit_command() -> None:
    # Порядок разбора: ответ о разрешении не смеет проглотить «стоп».
    manager = _FakeManager(active=True, permission=None)
    router, _notifier = _router(manager)

    consumed = await router.route(
        text="/code stop", sender=_OWNER, is_owner=True, is_group=False
    )

    assert consumed is True
    assert manager.stopped == [_OWNER]
    assert manager.fed == []
