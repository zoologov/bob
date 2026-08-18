# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the resume / persistent-workspace scenarios (BOB-087.D R1–R10).

Binds ``interactive_resume.feature`` to the real interactive stack harness. The scenarios
pin the OBSERVABLE, boundary-level behaviour of «поднять с телефона нашу эпик-сессию»:

* R1/R2 — a confirmed resume spawns ``claude --resume <the persisted id>`` inside the
  PERSISTENT workspace (``ensure``, never ``create``), and that tree accumulates work
  across sessions (never removed; the next resume reuses it and continues the id chain);
* R3/R4 — the owner-only sandbox relaxations: ``bypassPermissions`` reaches the process
  ONLY under ``coder.allow_bypass``, and ``--add-dir`` appears ONLY for a configured
  ``coder.extra_dirs`` (a flag-shaped config entry never becomes an argv flag);
* R5/R6 — owner-only + DM-only + the confirmation safety catch: a guest / a group turn /
  the bare command / a late «да» / a hedged «да, но…» / an unrelated reply raise nothing;
* R7 — 🔴 no live-attach: with a live session resume refuses (and the command does not
  leak into claude's stdin), and a non-terminal row is never a candidate;
* R8 — 🔴 a resumed session NEVER pushes / merges / opens a PR (INV-2);
* R9 — flags OFF → BOB-083 byte-for-byte: the command is not consumed and the fresh
  spawn argv equals the pinned baseline;
* R10 — 🔴 the FULL cycle from an empty slate (BOB-087.D5b): the owner OPENS a long-lived
  workspace by an explicit command, works, stops (the tree survives), and a later resume
  raises THAT very session. Before this there was no way to create such a workspace at
  all, so «поднять сессию» could never find a candidate and the feature closed on itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from pytest_bdd import given, scenarios, then, when

from bob.coding.state import CodingSessionState
from bob.interactive.resume_policy import CONFIRMATION_TTL
from bob.interactive.tool_permissions import tool_permission_argv
from tests.acceptance.interactive_resume_harness import (
    BASELINE_ARGV,
    GUEST_ID,
    PRIOR_CLAUDE_SESSION_ID,
    WORKSPACE,
    WORKSPACE_BRANCH,
    WORKSPACE_PATH,
    ResumeObservations,
    Rig,
    Turn,
    build_rig,
    live_claude_session_id,
    prior_session,
    run_turns,
)

scenarios("../features/interactive_resume.feature")

_RESUME_COMMAND = f"/resume {WORKSPACE}"
_WORKSPACE_COMMAND = f"/workspace {WORKSPACE} доделать срез D"
_ENTRY_COMMAND = "/code -i fix the bug"
_EXTRA_DIR = "/srv/shared"
_FLAG_SHAPED_DIR = "--dangerously-skip-permissions"


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the resume scenario's steps share."""

    rig: Rig
    obs: ResumeObservations = field(default_factory=ResumeObservations)


def _pairs(argv: list[str], flag: str, value: str) -> int:
    """How many times ``flag`` is immediately followed by ``value`` in ``argv``."""
    return sum(1 for i in range(len(argv) - 1) if argv[i] == flag and argv[i + 1] == value)


def _first_argv(ctx: _Ctx) -> list[str]:
    assert ctx.obs.argvs, "процесс claude не спавнился — argv ассертить нечего"
    return ctx.obs.argvs[0]


def _run(ctx: _Ctx, turns: list[Turn]) -> None:
    ctx.obs = run_turns(ctx.rig, turns)


# --- Given: the recorded past + the owner-facing config knobs ---------------------


@given("прошлая сессия эпика остановлена и её claude-session-id сохранён", target_fixture="rtx")
def stopped_prior_session() -> _Ctx:
    return _Ctx(rig=build_rig(sessions=(prior_session(),)))


@given("прошлая сессия эпика осталась в нетерминальном состоянии", target_fixture="rtx")
def unfinished_prior_session() -> _Ctx:
    # 🔴 A row still marked INTERACTIVE (e.g. the process died without a clean stop) is
    # NOT a candidate — resuming it would mean two drivers behind one claude.
    return _Ctx(
        rig=build_rig(sessions=(prior_session(state=CodingSessionState.INTERACTIVE),))
    )


@given(
    "запрошен режим bypassPermissions, а флаг coder.allow_bypass выключен",
    target_fixture="rtx",
)
def bypass_requested_flag_off() -> _Ctx:
    return _Ctx(rig=build_rig(resume=False, permission_mode="bypassPermissions"))


@given(
    "запрошен режим bypassPermissions, а флаг coder.allow_bypass включён",
    target_fixture="rtx",
)
def bypass_requested_flag_on() -> _Ctx:
    return _Ctx(
        rig=build_rig(
            resume=False, allow_bypass=True, permission_mode="bypassPermissions"
        )
    )


@given("coder.extra_dirs не задан", target_fixture="rtx")
def no_extra_dirs() -> _Ctx:
    return _Ctx(rig=build_rig(resume=False))


@given(
    "в coder.extra_dirs заданы рабочая директория, её дубль и флагоподобная запись",
    target_fixture="rtx",
)
def configured_extra_dirs() -> _Ctx:
    return _Ctx(
        rig=build_rig(
            resume=False,
            extra_dirs=(_EXTRA_DIR, _EXTRA_DIR, _FLAG_SHAPED_DIR, "   "),
        )
    )


@given("ни одной прошлой сессии не записано", target_fixture="rtx")
def no_prior_session() -> _Ctx:
    # 🔴 BOB-087.D5b (M3): чистый старт — долгоживущего рабочего места ЕЩЁ НЕТ, и завести
    # его можно только явной командой. Раньше такого пути не было вовсе, поэтому
    # «поднять сессию» не находило кандидата НИКОГДА.
    return _Ctx(rig=build_rig())


@given("флаг coder.resume выключен, а прошлая сессия эпика остановлена", target_fixture="rtx")
def resume_flag_off() -> _Ctx:
    return _Ctx(rig=build_rig(sessions=(prior_session(),), resume=False))


@given("все D-флаги выключены", target_fixture="rtx")
def all_d_flags_off() -> _Ctx:
    return _Ctx(rig=build_rig(resume=False))


# --- When: the owner's (or a stranger's) turns ------------------------------------


@when("owner просит поднять эпик и подтверждает")
def owner_asks_and_confirms(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_RESUME_COMMAND), Turn(text="да")])


@when("owner поднимает эпик, работает, завершает сеанс и поднимает эпик снова")
def owner_resumes_twice(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND),
            Turn(text="да"),
            Turn(text="правь дальше"),
            Turn(text="stop"),
            Turn(text=_RESUME_COMMAND),
            Turn(text="да"),
        ],
    )


@when("owner поднимает эпик, направляет его и завершает сеанс")
def owner_resumes_steers_stops(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND),
            Turn(text="да"),
            Turn(text="правь дальше"),
            Turn(text="stop"),
        ],
    )


@when("owner открывает интерактив")
def owner_opens_interactive(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_ENTRY_COMMAND)])


@when("owner открывает рабочее место эпика")
def owner_opens_the_workspace(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_WORKSPACE_COMMAND)])


@when("owner открывает рабочее место эпика, работает, завершает сеанс и поднимает его")
def owner_opens_workspace_works_stops_and_resumes(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_WORKSPACE_COMMAND),
            Turn(text="правь дальше"),
            Turn(text="stop"),
            Turn(text=_RESUME_COMMAND),
            Turn(text="да"),
        ],
    )


@when("owner открывает интерактив и завершает сеанс")
def owner_opens_and_stops(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_ENTRY_COMMAND), Turn(text="stop")])


@when("owner открывает интерактив и в живом сеансе просит поднять эпик")
def owner_opens_then_asks_resume(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_ENTRY_COMMAND), Turn(text=_RESUME_COMMAND)])


@when("гость просит поднять эпик и подтверждает")
def guest_asks_and_confirms(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND, is_owner=False, sender=GUEST_ID),
            Turn(text="да", is_owner=False, sender=GUEST_ID),
        ],
    )


@when("owner просит поднять эпик в группе и подтверждает там же")
def owner_asks_in_group(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND, is_group=True),
            Turn(text="да", is_group=True),
        ],
    )


@when("owner только просит поднять эпик")
def owner_only_asks(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_RESUME_COMMAND)])


@when("owner подтверждает, когда окно подтверждения уже истекло")
def owner_confirms_too_late(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND),
            Turn(text="да", after=CONFIRMATION_TTL + timedelta(seconds=1)),
        ],
    )


@when("owner отвечает «да, но сначала покажи дифф»")
def owner_hedges(rtx: _Ctx) -> None:
    _run(rtx, [Turn(text=_RESUME_COMMAND), Turn(text="да, но сначала покажи дифф")])


@when("owner отвечает не по теме, а следом говорит «да»")
def owner_answers_off_topic_then_yes(rtx: _Ctx) -> None:
    _run(
        rtx,
        [
            Turn(text=_RESUME_COMMAND),
            Turn(text="а что там по погоде"),
            Turn(text="да"),
        ],
    )


# --- Then: what the boundaries saw ------------------------------------------------


@then("процессу claude ушёл argv с --resume и тем самым session-id")
def argv_carries_the_resume_id(rtx: _Ctx) -> None:
    argv = _first_argv(rtx)
    assert _pairs(argv, "--resume", PRIOR_CLAUDE_SESSION_ID) == 1, (
        f"в argv нет --resume {PRIOR_CLAUDE_SESSION_ID}: {argv}"
    )


@then("работа приземлилась в персистентный workspace — ensure, а не create")
def work_lands_in_the_persistent_workspace(rtx: _Ctx) -> None:
    assert rtx.obs.ensured == [WORKSPACE_BRANCH], (
        f"персистентный workspace не поднят: ensured={rtx.obs.ensured}"
    )
    assert rtx.obs.created == [], "возобновление не должно создавать эфемерный worktree"
    assert rtx.obs.cwds == [WORKSPACE_PATH], (
        f"claude запущен не в накопленном дереве: {rtx.obs.cwds}"
    )


@then("оба хода поглощены интерактивом")
def both_turns_consumed(rtx: _Ctx) -> None:
    assert rtx.obs.consumed == [True, True], (
        f"команда и подтверждение должны быть поглощены; consumed={rtx.obs.consumed}"
    )


@then("дерево workspace не удалялось ни разу")
def workspace_never_removed(rtx: _Ctx) -> None:
    # 🔴 The data-loss guard: stopping a resumed session must NOT tear the tree down.
    assert rtx.obs.removed == [], f"накопленное дерево удалили: {rtx.obs.removed}"


@then("второй подъём реюзит тот же workspace и продолжает цепочку сессий")
def second_resume_reuses_the_workspace(rtx: _Ctx) -> None:
    assert rtx.obs.ensured == [WORKSPACE_BRANCH, WORKSPACE_BRANCH]
    assert rtx.obs.created == []
    assert rtx.obs.cwds == [WORKSPACE_PATH, WORKSPACE_PATH], (
        f"второй сеанс поднялся в другом дереве: {rtx.obs.cwds}"
    )
    assert rtx.obs.spawned == 2
    # The chain: the second spawn resumes the id claude announced during the FIRST
    # resumed run (persisted on stop) — not the original seeded one.
    assert _pairs(rtx.obs.argvs[1], "--resume", live_claude_session_id(1)) == 1, (
        f"второй подъём не продолжил цепочку сессий: {rtx.obs.argvs[1]}"
    )


@then("процесс claude не заспавнен")
def no_process_spawned(rtx: _Ctx) -> None:
    assert rtx.obs.spawned == 0, "процесс claude не должен был заспавниться"


@then("Боб честно ответил в личку")
def bob_answered_in_the_dm(rtx: _Ctx) -> None:
    assert rtx.obs.dm_lines, "Боб промолчал вместо честного ответа"
    assert all(line.strip() for line in rtx.obs.dm_lines)


@then("процесс заспавнен и argv несёт запрошенный режим")
def argv_carries_the_requested_mode(rtx: _Ctx) -> None:
    assert rtx.obs.spawned == 1
    assert _pairs(_first_argv(rtx), "--permission-mode", "bypassPermissions") == 1, (
        f"в argv нет запрошенного режима: {_first_argv(rtx)}"
    )


@then("в argv нет ни одного --add-dir")
def argv_has_no_add_dir(rtx: _Ctx) -> None:
    assert "--add-dir" not in _first_argv(rtx), (
        f"незаданные доп-директории просочились в argv: {_first_argv(rtx)}"
    )


@then("в argv ровно одна пара --add-dir с заданной директорией")
def argv_has_one_add_dir(rtx: _Ctx) -> None:
    argv = _first_argv(rtx)
    assert _pairs(argv, "--add-dir", _EXTRA_DIR) == 1, f"дубль не схлопнулся: {argv}"
    assert argv.count("--add-dir") == 1, f"лишние --add-dir в argv: {argv}"


@then("флагоподобная запись из конфига не стала флагом в argv")
def flag_shaped_entry_is_dropped(rtx: _Ctx) -> None:
    # 🔴 argv-инъекция: a config line shaped like a flag must never occupy an argv slot.
    assert _FLAG_SHAPED_DIR not in _first_argv(rtx), (
        f"флагоподобная запись попала в argv: {_first_argv(rtx)}"
    )


@then("ничего не поднято: ни workspace, ни процесса")
def nothing_was_raised(rtx: _Ctx) -> None:
    assert rtx.obs.spawned == 0, "живой claude не должен был подняться"
    assert rtx.obs.ensured == [], "персистентный workspace не должен был подняться"
    assert rtx.obs.created == [], "worktree не должен был создаваться"
    assert rtx.obs.active_after is False


@then("ни один ход не поглощён интерактивом")
def no_turn_consumed(rtx: _Ctx) -> None:
    assert rtx.obs.consumed, "сценарий не прогнал ни одного хода"
    assert not any(rtx.obs.consumed), (
        f"ход не должен поглощаться (owner-only / DM-only / флаг OFF); "
        f"consumed={rtx.obs.consumed}"
    )
    assert rtx.obs.dm_lines == [], "Боб не должен ничего отвечать по этому пути"


@then("Боб переспросил про этот workspace, назвав время прошлой сессии с зоной")
def bob_asked_back(rtx: _Ctx) -> None:
    assert rtx.obs.consumed == [True]
    assert len(rtx.obs.dm_lines) == 1, f"ожидался ровно один вопрос: {rtx.obs.dm_lines}"
    question = rtx.obs.dm_lines[0]
    assert WORKSPACE in question, f"вопрос не называет workspace: {question}"
    assert "10:00 UTC" in question, (
        f"вопрос не называет время прошлой сессии с зоной: {question}"
    )
    assert "?" in question, f"это не вопрос: {question}"


@then("запоздалое «да» не поглощено интерактивом")
def late_yes_not_consumed(rtx: _Ctx) -> None:
    assert rtx.obs.consumed == [True, False], (
        f"«да» вне TTL должно уйти обычным путём; consumed={rtx.obs.consumed}"
    )


@then("оговорка не поглощена интерактивом")
def hedged_yes_not_consumed(rtx: _Ctx) -> None:
    assert rtx.obs.consumed == [True, False], (
        f"«да, но…» — не подтверждение; consumed={rtx.obs.consumed}"
    )


@then("ни посторонняя реплика, ни позднее «да» не поглощены интерактивом")
def dropped_question_does_not_stick(rtx: _Ctx) -> None:
    # The unrelated reply drops the question, so the LATER «да» answers nothing.
    assert rtx.obs.consumed == [True, False, False], (
        f"вопрос залип; consumed={rtx.obs.consumed}"
    )


@then("второй процесс не заспавнен, а команда не утекла в stdin claude")
def resume_refused_while_live(rtx: _Ctx) -> None:
    assert rtx.obs.spawned == 1, (
        f"🔴 live-attach: поднялся второй процесс claude ({rtx.obs.spawned})"
    )
    assert rtx.obs.fed_texts == [], (
        f"команда возобновления утекла в живой claude: {rtx.obs.fed_texts}"
    )
    assert rtx.obs.consumed == [True, True]


@then("персистентный workspace не поднимался")
def persistent_workspace_untouched(rtx: _Ctx) -> None:
    assert rtx.obs.ensured == [], f"workspace подняли при живой сессии: {rtx.obs.ensured}"


@then("PR, пуш и мерж в main не вызывались ни разу")
def never_pushed_or_merged(rtx: _Ctx) -> None:
    # 🔴 INV-2: the whole lifecycle ran (resume → steer → stop) yet nothing left the tree.
    assert rtx.obs.pushes == [], "возобновлённый сеанс НЕ должен пушить/мержить/открывать PR"


@then("правки остались в персистентном workspace")
def edits_stay_in_the_workspace(rtx: _Ctx) -> None:
    assert rtx.obs.ensured == [WORKSPACE_BRANCH]
    assert rtx.obs.cwds == [WORKSPACE_PATH]
    assert rtx.obs.removed == [], "накопленное дерево удалили"
    assert rtx.obs.fed_texts == ["правь дальше"], (
        f"реплика не дошла до живого claude: {rtx.obs.fed_texts}"
    )


def _stop_line(ctx: _Ctx) -> str:
    """Последняя строка режима в личке — та, которой Боб отчитался об остановке."""
    assert ctx.obs.dm_lines, "Боб промолчал на остановке"
    return ctx.obs.dm_lines[-1].casefold()


@then("Боб на остановке не сказал, что убрал рабочую копию")
def stop_line_does_not_claim_cleanup(rtx: _Ctx) -> None:
    # 🔴 Честность голоса: дерево СОЗНАТЕЛЬНО сохранено (см. «дерево workspace не
    # удалялось»), поэтому реплика не смеет утверждать обратное.
    assert rtx.obs.removed == [], f"накопленное дерево удалили: {rtx.obs.removed}"
    assert "убрал" not in _stop_line(rtx), (
        f"Боб соврал про уборку сохранённой работы: {rtx.obs.dm_lines[-1]}"
    )


@then("Боб на остановке сказал, что работа осталась и её можно поднять снова")
def stop_line_promises_the_work_survived(rtx: _Ctx) -> None:
    line = _stop_line(rtx)
    assert "остал" in line, f"реплика не говорит, что работа осталась: {line}"
    assert "подним" in line or "поднять" in line, (
        f"реплика не говорит, что сессию можно поднять снова: {line}"
    )


@then("Боб на остановке сказал, что рабочую копию убрал")
def stop_line_reports_the_cleanup(rtx: _Ctx) -> None:
    # Контраст: эфемерное дерево ДЕЙСТВИТЕЛЬНО убрано — и реплика об этом говорит.
    assert rtx.obs.removed, "эфемерный worktree должен был убраться"
    assert "убрал" in _stop_line(rtx), (
        f"Боб умолчал про уборку эфемерной копии: {rtx.obs.dm_lines[-1]}"
    )


@then("оба сеанса шли в ОДНОМ долгоживущем дереве, и оно ни разу не удалялось")
def both_sessions_shared_one_persistent_tree(rtx: _Ctx) -> None:
    assert rtx.obs.ensured == [WORKSPACE_BRANCH, WORKSPACE_BRANCH], (
        f"сеансы не приземлились в долгоживущее дерево: ensured={rtx.obs.ensured}"
    )
    assert rtx.obs.created == [], "эфемерный worktree тут не должен создаваться"
    assert rtx.obs.cwds == [WORKSPACE_PATH, WORKSPACE_PATH], (
        f"второй сеанс поднялся в другом дереве: {rtx.obs.cwds}"
    )
    assert rtx.obs.removed == [], f"накопленное дерево удалили: {rtx.obs.removed}"
    assert rtx.obs.fed_texts == ["правь дальше"]


@then("подъём продолжил ИМЕННО ту сессию, что открывали командой рабочего места")
def resume_continued_that_very_session(rtx: _Ctx) -> None:
    # 🔴 Полный цикл замкнулся: первый сеанс СВЕЖИЙ (поднимать было нечего), второй
    # поднимает id, который claude назвал в ПЕРВОМ — цепочка началась с команды открытия.
    assert rtx.obs.spawned == 2
    assert "--resume" not in rtx.obs.argvs[0], (
        f"открытие рабочего места не должно ничего возобновлять: {rtx.obs.argvs[0]}"
    )
    assert _pairs(rtx.obs.argvs[1], "--resume", live_claude_session_id(1)) == 1, (
        f"подъём не продолжил ту самую сессию: {rtx.obs.argvs[1]}"
    )


@then("на открытии Боб честно предупредил, что рабочее место долгоживущее")
def opening_line_warns_the_tree_is_long_lived(rtx: _Ctx) -> None:
    assert rtx.obs.dm_lines, "Боб промолчал на открытии"
    opening = rtx.obs.dm_lines[0].casefold()
    assert WORKSPACE.casefold() in opening, f"реплика не называет рабочее место: {opening}"
    assert "остан" in opening, (
        f"owner не предупреждён, что наработанное остаётся: {rtx.obs.dm_lines[0]}"
    )


@then("argv свежей сессии равен базлайну BOB-083 плюс неснимаемый запрет необратимого")
def fresh_argv_matches_the_baseline(rtx: _Ctx) -> None:
    # 🔴 BOB-088 срез 3 ИЗМЕНИЛ этот сценарий, и правка видимая, а не подогнанная: раньше
    # он утверждал «байт-в-байт базлайн BOB-083», и это перестало быть правдой намеренно —
    # запрет необратимого едет в КАЖДОМ спавне и флага, которым его выключить, нет вовсе
    # (урок среза 1). Всё, что было ослаблением (resume / --add-dir / рутина конвейера),
    # по-прежнему отсутствует при выключенных флагах — это и проверяется.
    argv = _first_argv(rtx)
    assert argv == [*BASELINE_ARGV, *tool_permission_argv()], (
        f"argv свежей сессии разошёлся с ожидаемым: {argv}"
    )
    assert "--allowedTools" not in argv, "рутина конвейера приехала без флага владельца"
