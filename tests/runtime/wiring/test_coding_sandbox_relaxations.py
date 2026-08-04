# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the ``coder.allow_bypass`` / ``coder.extra_dirs`` wiring (BOB-087.D2).

Two owner-only knobs that SPEED UP interactive work inside the isolated worktree at the
price of a weaker sandbox: ``allow_bypass`` admits ``--permission-mode bypassPermissions``
into the runner's allowlist, ``extra_dirs`` adds ``--add-dir`` paths OUTSIDE the worktree.
Both ship inert (OFF / empty), and this builder pair is the ONE place they are read: the
default wiring must reject a bypass mode and pass no ``--add-dir`` at all — byte-identical
to the shipped runners.

🔴 What the knobs really cost, stated honestly (BOB-087.D5b M4 / D5c N4 — this docstring
kept claiming the opposite): Bob's OWN code adds no push / merge / PR path in the
interactive seam, and that stays true. But ``bypassPermissions`` hands claude an
unsupervised shell inside a LINKED worktree, and a linked worktree shares the main repo's
``.git`` — the same refs, remotes and credentials — so ``git push --force origin
HEAD:main``, ``git branch -f main …`` and ``gh pr merge`` are all expressible from there.
With ``allow_bypass: true`` «main is untouchable» stops being a STRUCTURAL guarantee and
becomes the owner's judgement; with it OFF — the default asserted here — every write claude
makes still passes a per-action gate. Same wording as the ``coder`` section of
``infrastructure/config/loader.py`` and ``docs/domains/coding/README.md``; do not soften it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from bob.coding.adapters.claude_runner import (
    ClaudeRunError,
    SubprocessClaudeRunner,
    _ExecStreamRunner,
)
from bob.coding.push_guard import PUSH_GUARD_STUB_URL
from bob.interactive.adapters.runner import (
    InteractiveClaudeRunner,
    _ExecInteractiveSpawner,
)
from bob.runtime.wiring.coding import _build_coding_assistant, _build_interactive_session

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping

    from bob.coding.usecases.coding_assistant import WorkJournalRecorder
    from bob.infrastructure.persistence import SqliteConnection
    from bob.infrastructure.telegram.gateway import BotLike
    from bob.kernel.ports import Clock
    from bob.memory.ports import SelfActionRecorder
    from bob.memory.self_action import SelfAction
    from bob.social.usecases import Authorizer

_OWNER_ID = 27468732
_CHAT_ID = -100123


class _StubBot:
    """A bot placeholder — assembled into notifiers, never sent through, at wiring."""


class _StubAuthorizer:
    def is_owner(self, user_id: int | None) -> bool:
        return user_id == _OWNER_ID


class _StubClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 2, tzinfo=UTC)


class _StubConnection:
    """A connection placeholder — the store retains it but touches nothing at wiring."""


class _StubRecorder:
    async def record(
        self,
        action: SelfAction,
        *,
        sender_id: int | None = None,
        visibility: str | None = None,
    ) -> None:
        return None


class _StubWorkJournal:
    async def record_session(
        self,
        task: str,
        facts: object,
        outcome: object,
        *,
        sender_id: int | None = None,
    ) -> None:
        return None


def _bot() -> BotLike:
    return cast("BotLike", _StubBot())


def _assistant_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "notifier_bot": _bot(),
        "stream_bot": _bot(),
        "chat_id": _CHAT_ID,
        "topic_id": None,
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
        "recorder": cast("SelfActionRecorder", _StubRecorder()),
        "work_journal": cast("WorkJournalRecorder", _StubWorkJournal()),
    }


def _session_deps() -> dict[str, object]:
    return {
        "repo": cast("SqliteConnection", _StubConnection()),
        "authorizer": cast("Authorizer", _StubAuthorizer()),
        "bot": _bot(),
        "stream_bot": _bot(),
        "owner_id": _OWNER_ID,
        "clock": cast("Clock", _StubClock()),
    }


def _one_shot_runner(config: Mapping[str, object]) -> SubprocessClaudeRunner:
    assistant = _build_coding_assistant(config, **_assistant_deps())  # type: ignore[arg-type]
    assert assistant is not None
    runner = assistant._runner
    assert isinstance(runner, SubprocessClaudeRunner)
    return runner


def _interactive_runner(config: Mapping[str, object]) -> InteractiveClaudeRunner:
    manager = _build_interactive_session(config, **_session_deps())  # type: ignore[arg-type]
    assert manager is not None
    runner = manager._runner_factory()
    assert isinstance(runner, InteractiveClaudeRunner)
    return runner


async def _drain(events: AsyncIterator[Mapping[str, object]]) -> None:
    async for _ in events:  # pragma: no cover - a refused run yields nothing
        pass


# --------------------------------------------------------------------------- #
# OFF path (default) — the shipped guarantee is intact
# --------------------------------------------------------------------------- #


async def test_default_wiring_refuses_a_bypass_mode() -> None:
    # Observable through the boundary: the wired runner refuses the mode BEFORE any
    # process is spawned — «no bypassPermissions ever» unless the owner opts in.
    runner = _one_shot_runner({"coder": {"enabled": True}})

    with pytest.raises(ClaudeRunError):
        await _drain(runner.run("/w", "task", mode="bypassPermissions"))


def test_default_wiring_passes_no_extra_dirs() -> None:
    runner = _one_shot_runner({"coder": {"enabled": True}})

    # Nothing appended → the argv is byte-identical to the shipped BOB-039 form.
    assert runner._extra_dir_argv == []


def test_default_interactive_wiring_is_inert() -> None:
    runner = _interactive_runner({"coder": {"interactive": True}})

    assert runner._allow_bypass is False
    assert runner._extra_dirs == ()


def test_explicit_false_and_empty_list_stay_inert() -> None:
    config = {
        "coder": {"enabled": True, "allow_bypass": False, "extra_dirs": []},
    }
    runner = _one_shot_runner(config)

    assert runner._allow_bypass is False
    assert runner._extra_dir_argv == []


# --------------------------------------------------------------------------- #
# ON path — the owner opted in, explicitly
# --------------------------------------------------------------------------- #


def test_allow_bypass_flag_reaches_the_one_shot_runner() -> None:
    config = {"coder": {"enabled": True, "allow_bypass": True}}

    assert _one_shot_runner(config)._allow_bypass is True


def test_extra_dirs_reach_the_one_shot_runner_as_add_dir_pairs() -> None:
    config = {"coder": {"enabled": True, "extra_dirs": ["/srv/docs", "/srv/spec"]}}

    assert _one_shot_runner(config)._extra_dir_argv == [
        "--add-dir",
        "/srv/docs",
        "--add-dir",
        "/srv/spec",
    ]


def test_a_flag_shaped_extra_dir_is_dropped_at_the_wiring_boundary() -> None:
    # 🔴 argv injection: a "--…" config entry must never become a claude flag.
    config = {
        "coder": {
            "enabled": True,
            "extra_dirs": ["--dangerously-skip-permissions", "/srv/docs"],
        }
    }

    assert _one_shot_runner(config)._extra_dir_argv == ["--add-dir", "/srv/docs"]


def test_both_knobs_reach_the_interactive_runner_factory() -> None:
    config = {
        "coder": {
            "interactive": True,
            "allow_bypass": True,
            "extra_dirs": ["/srv/docs"],
        }
    }
    runner = _interactive_runner(config)

    assert runner._allow_bypass is True
    assert runner._extra_dirs == ("/srv/docs",)


def test_extra_dirs_accept_the_csv_env_form() -> None:
    # Env config arrives flat: ``BOB_CODER__EXTRA_DIRS="/srv/docs,/srv/spec"``.
    config = {"coder": {"enabled": True, "extra_dirs": "/srv/docs,/srv/spec"}}

    assert _one_shot_runner(config)._extra_dir_argv == [
        "--add-dir",
        "/srv/docs",
        "--add-dir",
        "/srv/spec",
    ]


# --------------------------------------------------------------------------- #
# 🔴 Push guard (BOB-087.E, bob-5ao) — доезжает ли owner-флаг до границы процесса
# --------------------------------------------------------------------------- #


def _spawn_envs(config: Mapping[str, object]) -> list[dict[str, str] | None]:
    """The env both wired runners would hand their spawned ``claude`` process."""
    one_shot = _one_shot_runner(config)._runner
    interactive = _interactive_runner(config)._spawner
    assert isinstance(one_shot, _ExecStreamRunner)
    assert isinstance(interactive, _ExecInteractiveSpawner)
    return [one_shot._env, interactive._env]


def test_default_wiring_spawns_claude_without_any_env_override() -> None:
    # OFF-путь: барьера нет вовсе → спавн без ``env=``, байт-в-байт как до BOB-087.E.
    assert _spawn_envs({"coder": {"enabled": True, "interactive": True}}) == [None, None]


def test_allow_bypass_puts_the_push_guard_into_both_spawns() -> None:
    # ON-путь: то же самое ослабление, что впускает bypassPermissions, ставит и барьер.
    config = {"coder": {"enabled": True, "interactive": True, "allow_bypass": True}}

    for env in _spawn_envs(config):
        assert env is not None
        assert int(env["GIT_CONFIG_COUNT"]) >= 1
        assert PUSH_GUARD_STUB_URL in env["GIT_CONFIG_KEY_0"]
