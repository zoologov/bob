# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the «упёрся в запрет → спрашиваю owner'а» scenarios (BOB-088, С-3/С-4).

Binds ``pipeline_permission.feature`` to the real interactive stack harness. The scenarios
pin the OBSERVABLE, boundary-level behaviour of «конвейер едет, неожиданное спрашивает»:

* a scripted ``permission_denied`` event (the exact NDJSON shape from a real claude 2.1.233
  run, bead ``bob-c3r.3``) makes the manager ASK the owner in BOB'S OWN VOICE, in his DM —
  naming the command, without the CLI's service string, without buttons or slashes;
* С-4 — that question travels the manager's own owner-notifier (Bob), while the mechanics
  (the tool-use firehose) travel a SEPARATE streamer (GUPPI canon, BOB-090.D); ``main`` is
  never touched (no push / merge over the whole session);
* an explicit «да» routed the ordinary DM way re-enters the SAME claude thread (``--resume``)
  with EXACTLY ONE command allowed and everything else still banned;
* an empty / off-topic answer does NOT lift the ban (no re-entry, no ``--allowedTools``);
* «нет» declines cleanly and lifts nothing.

Every assertion reads a boundary the production code crosses: what Bob said in his DM
channel vs the firehose, and the spawn argv of the re-entry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.pipeline_conveyor_harness import (
    LIVE_CLAUDE_SESSION_ID,
    Observations,
    Rig,
    Turn,
    build_rig,
    denial_stream,
    run_turns,
)

scenarios("../features/pipeline_permission.feature")

_ENTRY_COMMAND = "/code -i доведи BOB-088 до PR"


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the scenario's steps share (the banned command + observations)."""

    command: str
    rig: Rig
    obs: Observations = field(default_factory=Observations)


def _run(ctx: _Ctx, turns: list[Turn]) -> None:
    ctx.obs = run_turns(ctx.rig, turns)


# --- Given ------------------------------------------------------------------


@given(
    parsers.parse("конвейер упёрся в запрет на команду «{command}»"),
    target_fixture="qtx",
)
def pipeline_hits_a_ban(command: str) -> _Ctx:
    # One live session whose stream carries the denial (script 0); a spare quiet script
    # (1) covers a possible re-entry.
    rig = build_rig(scripts=[denial_stream(command), []])
    return _Ctx(command=command, rig=rig)


# --- When -------------------------------------------------------------------


@when("owner ведёт живой сеанс, в котором эта команда отклонена")
def owner_runs_the_denied_session(qtx: _Ctx) -> None:
    _run(qtx, [Turn(text=_ENTRY_COMMAND)])


@when("owner в живом сеансе с этим запретом отвечает «да»")
def owner_answers_yes(qtx: _Ctx) -> None:
    _run(qtx, [Turn(text=_ENTRY_COMMAND), Turn(text="да")])


@when("owner в живом сеансе с этим запретом отвечает пустой строкой")
def owner_answers_empty(qtx: _Ctx) -> None:
    _run(qtx, [Turn(text=_ENTRY_COMMAND), Turn(text="   ")])


@when("owner в живом сеансе с этим запретом отвечает не по теме")
def owner_answers_off_topic(qtx: _Ctx) -> None:
    _run(qtx, [Turn(text=_ENTRY_COMMAND), Turn(text="а что там по погоде")])


@when("owner в живом сеансе с этим запретом отвечает «нет»")
def owner_answers_no(qtx: _Ctx) -> None:
    _run(qtx, [Turn(text=_ENTRY_COMMAND), Turn(text="нет")])


# --- Then -------------------------------------------------------------------


def _question(ctx: _Ctx) -> str:
    assert ctx.obs.bob_lines, "Боб промолчал вместо вопроса про разрешение"
    return ctx.obs.bob_lines[-1]


@then("Боб спросил owner'а в личку своим голосом, назвав именно эту команду")
def bob_asked_in_his_voice(qtx: _Ctx) -> None:
    question = _question(qtx)
    assert qtx.command in question, f"вопрос не называет команду: {question!r}"
    assert question.rstrip().endswith("?"), f"это не вопрос: {question!r}"


@then("в вопросе нет ни служебной строки CLI, ни кнопок, ни слешей")
def question_has_no_cli_string_or_buttons(qtx: _Ctx) -> None:
    question = _question(qtx)
    # 🔴 Английская служебная строка CLI внутрь русской речи Боба не попадает (BOB-096).
    assert "approval" not in question, f"в реплику протекла строка CLI: {question!r}"
    assert "This command" not in question, f"в реплику протекла строка CLI: {question!r}"
    # Ни кнопок, ни слеш-команды в ответ (решение owner'а от 2026-08-15).
    assert "/" not in question.replace(qtx.command, ""), (
        f"в вопросе есть слеш-команда: {question!r}"
    )


@then("вопрос про разрешение пришёл голосом Боба, а не в поток механики")
def question_is_bobs_not_the_firehose(qtx: _Ctx) -> None:
    # 🔴 С-4 (канон BOB-090.D): вопрос — социальный акт, идёт нотификатором Боба; механика
    # (вывод claude, firehose) — отдельным стримером GUPPI.
    assert any(qtx.command in line for line in qtx.obs.bob_lines), (
        f"вопрос не пришёл голосом Боба: {qtx.obs.bob_lines}"
    )
    assert not any(line.rstrip().endswith("?") for line in qtx.obs.firehose_lines), (
        f"вопрос про разрешение утёк в поток механики: {qtx.obs.firehose_lines}"
    )


@then("main не тронут: ни пуша, ни мёржа за весь сеанс")
def main_untouched(qtx: _Ctx) -> None:
    assert qtx.obs.pushes == [], f"сеанс тронул main: {qtx.obs.pushes}"


def _values_after(argv: list[str], flag: str) -> list[str]:
    """Значения ``flag`` — от него ДО следующего флага (не «все не-флаги в argv»)."""
    if flag not in argv:
        return []
    values: list[str] = []
    for item in argv[argv.index(flag) + 1 :]:
        if item.startswith("--"):
            break
        values.append(item)
    return values


def _allowed(argv: list[str]) -> list[str]:
    """Точечные разрешения этого спавна (``--allowedTools`` … до следующего флага)."""
    return _values_after(argv, "--allowedTools")


def _denied(argv: list[str]) -> list[str]:
    assert "--disallowedTools" in argv, argv
    return _values_after(argv, "--disallowedTools")


@then(
    "сессия поднята заново в той же нити с точечным разрешением ровно этой команды"
)
def re_entry_allows_exactly_the_command(qtx: _Ctx) -> None:
    assert qtx.obs.spawned == 2, f"повторного захода не случилось: {qtx.obs.spawned}"
    second = qtx.obs.argvs[1]
    assert "--resume" in second, f"повторный заход не в ту же нить: {second}"
    at = second.index("--resume")
    assert second[at + 1] == LIVE_CLAUDE_SESSION_ID, (
        f"--resume несёт не ту нить: {second[at : at + 2]}"
    )
    assert _allowed(second) == [f"Bash({qtx.command})"], (
        f"разрешена не ровно эта команда: {_allowed(second)}"
    )


@then("всё остальное необратимое в том же заходе по-прежнему запрещено")
def re_entry_keeps_the_rest_banned(qtx: _Ctx) -> None:
    second = qtx.obs.argvs[1]
    denied = _denied(second)
    # Накрывающий команду шаблон снят, а прочее необратимое — на месте.
    assert "Bash(git push:*)" not in denied, f"накрывающий запрет не снят: {denied}"
    assert "Bash(rm:*)" in denied, f"снос файлов вдруг разрешён: {denied}"


@then("повторного захода не случилось и точечного разрешения никто не выдал")
def no_re_entry_and_no_grant(qtx: _Ctx) -> None:
    # 🔴 Пустой / посторонний / «нет» ответ запрет НЕ снимает: ни второго спавна, ни
    # единого --allowedTools ни в одном argv.
    assert qtx.obs.spawned == 1, f"случился повторный заход: {qtx.obs.spawned}"
    assert not any("--allowedTools" in argv for argv in qtx.obs.argvs), (
        f"кто-то выдал точечное разрешение: {qtx.obs.argvs}"
    )


@then("Боб коротко ответил, что идёт дальше без этого шага")
def bob_declined_cleanly(qtx: _Ctx) -> None:
    # Ответ на «нет» уходит короткой строкой режима (CodingOutcome.message) через роутер.
    assert any("без этого" in line for line in qtx.obs.mode_lines), (
        f"Боб не сказал, что идёт дальше без шага: {qtx.obs.mode_lines}"
    )
