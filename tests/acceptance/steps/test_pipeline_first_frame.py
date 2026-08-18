# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the «постановка эпика первым кадром» scenarios (BOB-088, С-1).

Binds ``pipeline_first_frame.feature`` to the real interactive stack harness. The
scenarios pin the OBSERVABLE, boundary-level behaviour of «сессия начинается с задачи»:

* a FRESH session (either door — ``/code -i`` or ``/workspace``) receives, as its very
  first stdin frame, the owner's task TOGETHER WITH the process instruction (``CLAUDE.md``
  / ``/coordinator`` / субагенты), not a bare task and not an empty window;
* a session raised by ``--resume`` does NOT get that frame again (its context already
  carries the work);
* with the owner flag OFF nothing is fed before the owner speaks (byte-for-byte the
  pre-BOB-088 behaviour).

Every assertion reads a boundary the production code crosses: the stream-json frames
decoded back out of the fake process's stdin, and the spawn argv (whether ``--resume``
rode). The canonical frame text itself is the domain's
(:func:`bob.interactive.pipeline_prompt.pipeline_first_frame`) — the scenario asserts that
THIS frame reached claude, not that «something non-empty» did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from bob.interactive.pipeline_prompt import pipeline_first_frame
from tests.acceptance.pipeline_conveyor_harness import (
    PRIOR_CLAUDE_SESSION_ID,
    WORKSPACE,
    Observations,
    Rig,
    Turn,
    build_rig,
    prior_session,
    run_turns,
)

scenarios("../features/pipeline_first_frame.feature")

_TASK = "веди BOB-095 по конвейеру"
_ENTRY_COMMAND = f"/code -i {_TASK}"
_WORKSPACE_COMMAND = f"/workspace {WORKSPACE} {_TASK}"
_RESUME_COMMAND = f"/resume {WORKSPACE}"


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the scenario's steps share."""

    rig: Rig
    obs: Observations = field(default_factory=Observations)


def _run(ctx: _Ctx, turns: list[Turn]) -> None:
    ctx.obs = run_turns(ctx.rig, turns)


# --- Given ------------------------------------------------------------------


@given("включён стартовый промпт конвейера", target_fixture="ptx")
def prompt_on() -> _Ctx:
    return _Ctx(rig=build_rig(pipeline_prompt=True))


@given("включён стартовый промпт конвейера и собран resume-путь", target_fixture="ptx")
def prompt_on_resume_on() -> _Ctx:
    return _Ctx(rig=build_rig(pipeline_prompt=True, resume=True))


@given(
    "включён стартовый промпт конвейера и приостановленная сессия эпика",
    target_fixture="ptx",
)
def prompt_on_with_prior() -> _Ctx:
    return _Ctx(
        rig=build_rig(pipeline_prompt=True, resume=True, sessions=(prior_session(),))
    )


@given("стартовый промпт конвейера выключен", target_fixture="ptx")
def prompt_off() -> _Ctx:
    return _Ctx(rig=build_rig(pipeline_prompt=False))


# --- When -------------------------------------------------------------------


@when("owner ставит эпик живой речью")
def owner_sets_the_epic(ptx: _Ctx) -> None:
    _run(ptx, [Turn(text=_ENTRY_COMMAND)])


@when("owner заводит эпик в долгоживущем рабочем месте")
def owner_opens_the_workspace(ptx: _Ctx) -> None:
    _run(ptx, [Turn(text=_WORKSPACE_COMMAND)])


@when("owner поднимает эпик и подтверждает")
def owner_resumes_and_confirms(ptx: _Ctx) -> None:
    _run(ptx, [Turn(text=_RESUME_COMMAND), Turn(text="да")])


# --- Then -------------------------------------------------------------------


def _first_frame(ctx: _Ctx) -> str:
    assert ctx.obs.spawned >= 1, "процесс claude не спавнился — кадр ассертить нечего"
    frames = ctx.obs.fed[0]
    assert frames, f"свежая сессия не получила ни одного кадра: {ctx.obs.fed}"
    return frames[0]


@then("claude получил первым кадром именно эту задачу")
def first_frame_is_the_task(ptx: _Ctx) -> None:
    frame = _first_frame(ptx)
    # 🔴 Это ТОТ САМЫЙ канонический кадр домена, а не «что-то непустое».
    assert frame == pipeline_first_frame(_TASK), f"первый кадр не тот: {frame!r}"
    assert _TASK in frame, f"кадр не несёт задачу owner'а: {frame!r}"


@then("тем же кадром ему сказано вести работу по процессу, а не просто «что-то делать»")
def first_frame_carries_the_process(ptx: _Ctx) -> None:
    frame = _first_frame(ptx)
    # Без указания на процесс сессия снова «claude что-то делает» — гард судит СОДЕРЖАНИЕ.
    assert "CLAUDE.md" in frame, f"кадр не указывает на процесс: {frame!r}"
    assert "/coordinator" in frame, f"кадр не зовёт координатора: {frame!r}"
    assert "СУБАГЕНТАМИ" in frame, f"кадр не говорит про субагентов: {frame!r}"


@then("сессия поднята с --resume той самой нити")
def session_resumed_by_id(ptx: _Ctx) -> None:
    assert ptx.obs.spawned == 1, f"ожидался один спавн: {ptx.obs.spawned}"
    argv = ptx.obs.argvs[0]
    assert "--resume" in argv, f"поднятая сессия не несёт --resume: {argv}"
    at = argv.index("--resume")
    assert argv[at + 1] == PRIOR_CLAUDE_SESSION_ID, (
        f"--resume несёт не ту нить: {argv[at : at + 2]}"
    )


@then("в её stdin постановка задачи повторно не уходила")
def resumed_session_gets_no_first_frame(ptx: _Ctx) -> None:
    # 🔴 Именно вторая половина С-1: у поднятой сессии задача уже в контексте, повторная
    # постановка велела бы начать эпик заново поверх накопленной работы.
    assert ptx.obs.fed[0] == [], (
        f"в поднятую по --resume сессию повторно ушёл кадр: {ptx.obs.fed[0]}"
    )


@then("claude не получил ни одного кадра до первой реплики owner'а")
def no_frame_before_the_owner_speaks(ptx: _Ctx) -> None:
    assert ptx.obs.spawned == 1, f"ожидался один спавн: {ptx.obs.spawned}"
    assert ptx.obs.fed[0] == [], (
        f"при выключенном флаге в свежую сессию что-то ушло: {ptx.obs.fed[0]}"
    )
