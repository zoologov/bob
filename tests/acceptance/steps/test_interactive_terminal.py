# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the interactive-terminal scenarios (BOB-083 S0–S5).

Binds ``interactive_terminal.feature`` to the real interactive stack harness. The
scenarios pin the OBSERVABLE, boundary-level behaviour of the live DM terminal:

* S0 — an owner DM reaches Bob's pipeline as a private turn and his reply targets the DM;
  a stranger DM is dropped (never published, Bob silent);
* S1 — an owner entry command opens an isolated worktree + spawns the live runner and
  streams claude's output to the DM (turn consumed);
* S2 — an owner plain reply is forwarded to claude's stdin (steer) and the turn is
  consumed without a normal Bob reply;
* S4 — ``stop`` directly kills the process + tears the worktree down, and the NEXT plain
  reply flows to the normal Bob path (the mode does not stick);
* S5 — a guest / a group message never opens or feeds; the flag OFF makes the mode
  entirely unavailable; 🔴 the live session NEVER commits/pushes/opens a PR (INV-2).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.interactive_terminal_harness import (
    DmRouteObservations,
    InteractiveObservations,
    Turn,
    guest_tries_to_open,
    interactive_router_when_flag_off,
    owner_opens_feeds_stops,
    owner_opens_interactive,
    owner_opens_then_steers,
    owner_opens_then_stops_then_talks,
    owner_tries_to_open_in_group,
    run_interactive,
    run_owner_dm,
    run_stranger_dm,
)

scenarios("../features/interactive_terminal.feature")

_OWNER_DM_CHAT_ID = 27468732


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the interactive scenario's steps share."""

    turns: list[Turn] = field(default_factory=list)
    obs: InteractiveObservations = field(default_factory=InteractiveObservations)
    dm: DmRouteObservations = field(default_factory=DmRouteObservations)
    flag_router: object | None = None


# --- S0: owner-DM foundation -----------------------------------------------------


@given("owner пишет Бобу в личку", target_fixture="itx")
def owner_dm() -> _Ctx:
    return _Ctx()


@given("посторонний пишет Бобу в личку из чужого чата", target_fixture="itx")
def stranger_dm() -> _Ctx:
    ctx = _Ctx()
    ctx.turns = [Turn(text="__stranger__")]  # marker: the When picks the stranger driver
    return ctx


@when("сообщение проходит через мультибот-роутер")
def route_through_multibot(itx: _Ctx) -> None:
    if itx.turns and itx.turns[0].text == "__stranger__":
        itx.dm = asyncio.run(run_stranger_dm())
    else:
        itx.dm = asyncio.run(run_owner_dm())


@then("сообщение доходит до пайплайна Боба как личное (не групповое)")
def dm_reaches_pipeline_as_private(itx: _Ctx) -> None:
    assert itx.dm.published is True
    assert itx.dm.received_texts, "owner-DM не дошёл до пайплайна Боба (INV-0)"
    assert itx.dm.received_is_group == [False], "личный DM помечен как групповой"


@then("ответ Боба уходит в личку owner'а без привязки к групповому топику")
def reply_targets_dm(itx: _Ctx) -> None:
    assert itx.dm.reply_chat_ids == [_OWNER_DM_CHAT_ID]
    assert itx.dm.reply_threads == [None], "ответ в личку не должен быть привязан к топику"


@then("сообщение не доходит до пайплайна Боба")
def dm_not_published(itx: _Ctx) -> None:
    assert itx.dm.published is False
    assert itx.dm.received_texts == []


@then("Боб ничего не отвечает")
def bob_silent(itx: _Ctx) -> None:
    assert itx.dm.reply_chat_ids == []


# --- S1 / S2 / S4 / S5 interactive turns -----------------------------------------


@given("owner в личке шлёт команду входа в интерактив", target_fixture="itx")
def owner_entry() -> _Ctx:
    return _Ctx(turns=owner_opens_interactive())


@given("открытый интерактив-сеанс owner'а", target_fixture="itx")
def open_session_ctx() -> _Ctx:
    # The concrete turn shape is chosen by the When step (steer vs stop), so the Given
    # only marks that a session will be opened first.
    return _Ctx()


@given("гость в личке шлёт команду входа в интерактив", target_fixture="itx")
def guest_entry() -> _Ctx:
    return _Ctx(turns=guest_tries_to_open())


@given("owner шлёт команду входа в интерактив в группе", target_fixture="itx")
def group_entry() -> _Ctx:
    return _Ctx(turns=owner_tries_to_open_in_group())


@given("флаг coder.interactive выключен", target_fixture="itx")
def flag_off_ctx() -> _Ctx:
    return _Ctx()


@given("owner открывает интерактив, направляет его и завершает", target_fixture="itx")
def full_lifecycle_ctx() -> _Ctx:
    return _Ctx(turns=owner_opens_feeds_stops())


@when("Боб обрабатывает ход интерактив-режима")
def drive_interactive(itx: _Ctx) -> None:
    itx.obs = asyncio.run(run_interactive(itx.turns))


@when("owner шлёт обычную реплику в личку")
def drive_steer(itx: _Ctx) -> None:
    itx.obs = asyncio.run(run_interactive(owner_opens_then_steers()))


@when("owner шлёт команду выхода, а затем обычное сообщение")
def drive_stop_then_talk(itx: _Ctx) -> None:
    itx.obs = asyncio.run(run_interactive(owner_opens_then_stops_then_talks()))


@when("собирается интейк-режим интерактива")
def build_flag_off(itx: _Ctx) -> None:
    itx.flag_router = interactive_router_when_flag_off()


@when("сеанс полностью отработал")
def drive_full_lifecycle(itx: _Ctx) -> None:
    itx.obs = asyncio.run(run_interactive(itx.turns))


# --- S1 Then ---------------------------------------------------------------------


@then("открывается изолированный worktree и спавнится живой раннер")
def worktree_and_runner(itx: _Ctx) -> None:
    assert itx.obs.worktree_created == ["bob/fix-the-bug"], (
        f"ожидался изолированный worktree bob/<slug>; создано: {itx.obs.worktree_created}"
    )
    assert itx.obs.spawned == 1, "живой раннер не заспавнен"


@then("живой поток claude идёт в личку owner'а")
def output_streams_to_dm(itx: _Ctx) -> None:
    assert itx.obs.dm_output_lines, "поток claude не дошёл до лички owner'а"


@then("ход поглощён интерактив-режимом")
def turn_consumed(itx: _Ctx) -> None:
    assert itx.obs.consumed[0] is True, "команда входа не поглощена интерактивом"


# --- S2 Then ---------------------------------------------------------------------


@then("реплика уходит в stdin живого claude")
def reply_fed_to_stdin(itx: _Ctx) -> None:
    assert itx.obs.fed_texts == ["теперь добавь тест"], (
        f"реплика не ушла в stdin claude; в stdin: {itx.obs.fed_texts}"
    )


@then("ход поглощён интерактив-режимом без обычного ответа Боба")
def steer_consumed_silently(itx: _Ctx) -> None:
    # The entry consumed + the steer consumed; steer emits no explicit mode line (silent) —
    # only the open produced one line, the steer itself is silent (output streams elsewhere).
    assert itx.obs.consumed == [True, True]
    assert len(itx.obs.mode_lines) == 1, (
        f"steer не должен слать строку режима — только вход; строки: {itx.obs.mode_lines}"
    )
    assert itx.obs.mode_lines[0], "строка режима входа не должна быть пустой"


# --- S4 Then ---------------------------------------------------------------------


@then("процесс claude напрямую убит и worktree убран")
def process_killed_and_worktree_removed(itx: _Ctx) -> None:
    assert itx.obs.terminated >= 1, "процесс claude не был напрямую завершён (INV-4)"
    assert itx.obs.worktree_removed == ["/wt/fix-the-bug"], "worktree не убран после stop"


@then("следующая обычная реплика идёт обычным путём Боба, а не в интерактив")
def mode_does_not_stick(itx: _Ctx) -> None:
    # open consumed, stop consumed, the trailing plain reply is NOT consumed → normal Bob.
    assert itx.obs.consumed == [True, True, False], (
        f"режим залип после stop; consumed: {itx.obs.consumed}"
    )
    assert itx.obs.fed_texts == [], "после stop ничего не должно уходить в stdin"


# --- S5 Then ---------------------------------------------------------------------


@then("сессия не открывается и ход не поглощается")
def session_not_opened_turn_not_consumed(itx: _Ctx) -> None:
    assert itx.obs.consumed == [False], "ход не должен поглощаться (owner-only/DM-only)"


@then("ни worktree, ни живой раннер не создаются")
def no_worktree_no_runner(itx: _Ctx) -> None:
    assert itx.obs.worktree_created == [], "гость/группа не должны создавать worktree"
    assert itx.obs.spawned == 0, "гость/группа не должны спавнить раннер"


@then("интейк-роутер не собран и режим целиком недоступен")
def flag_off_router_is_none(itx: _Ctx) -> None:
    assert itx.flag_router is None, "при выключенном флаге интейк-роутер должен быть None"


@then("claude-правки остались в worktree, а PR/пуш/мерж в main не вызывались ни разу")
def never_pr_or_push(itx: _Ctx) -> None:
    # 🔴 INV-2: the whole lifecycle ran (open → feed → stop) yet no commit/push/PR fired.
    assert itx.obs.pushes == [], "живой сеанс НЕ должен пушить/мержить/открывать PR"
    # And the worktree that held the edits was created then cleaned up.
    assert itx.obs.worktree_created == ["bob/fix-the-bug"]
    assert itx.obs.worktree_removed == ["/wt/fix-the-bug"]
