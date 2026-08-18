# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Разбор отказа в разрешении — чистое ядро (BOB-088, срез 3).

Предмет: :class:`bob.interactive.permission_denial.DenialWatch` — то, что читает поток
живой сессии и называет отказ так, как о нём можно СПРОСИТЬ ВЛАДЕЛЬЦА: чего именно Боб
хотел, и по какому ``tool_use`` ему отказали.

🔴 Главный факт, ради которого ядро вообще существует, — из живого прогона (протокол в
комментарии беады ``bob-c3r.3``): поле ``message`` события отказа НЕ ВСЕГДА несёт
команду. На ``sh -c "…"`` и на всех отказах встроенного гейта там английское «This
command requires approval», а у ``WebFetch`` — «Claude requested permissions to use
WebFetch, but you haven't granted it yet». Поэтому «что я хотел сделать» берётся ТОЛЬКО
из связанного по ``tool_use_id`` вызова, а служебная строка CLI не произносится вовсе —
иначе повторился бы дефект ``rule_voice`` (BOB-096): чужой английский текст внутри
русской реплики Боба.
"""

from __future__ import annotations

from typing import Any

from bob.interactive.permission_denial import DenialWatch, PermissionDenial


def _tool_use(tool_use_id: str, *, name: str = "Bash", **inputs: Any) -> dict[str, Any]:
    """Кадр ассистента с вызовом инструмента — ровно в форме живого потока."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "I'll run that one command."},
                {"type": "tool_use", "id": tool_use_id, "name": name, "input": inputs},
            ],
        },
    }


def _denied(
    tool_use_id: str,
    *,
    tool_name: str = "Bash",
    message: str = "This command requires approval",
    **extra: Any,
) -> dict[str, Any]:
    """Событие отказа — дословно в форме, снятой с живого прогона."""
    return {
        "type": "system",
        "subtype": "permission_denied",
        "tool_name": tool_name,
        "tool_use_id": tool_use_id,
        "message": message,
        "session_id": "sess-1",
        **extra,
    }


# --------------------------------------------------------------------------- #
# Что Боб узнаёт из отказа
# --------------------------------------------------------------------------- #


def test_a_denial_is_named_by_the_command_it_belongs_to() -> None:
    watch = DenialWatch()

    assert watch.see(_tool_use("toolu_1", command="git push origin master")) is None
    denial = watch.see(_denied("toolu_1"))

    assert denial == PermissionDenial(
        tool_name="Bash", tool_use_id="toolu_1", command="git push origin master"
    )


def test_the_english_line_of_the_cli_is_never_what_bob_wanted() -> None:
    # 🔴 Второй вход этого ядра: на встроенном отказе message выглядит осмысленно
    # («This command requires approval»), и соблазн подставить его в реплику велик.
    watch = DenialWatch()
    watch.see(_tool_use("toolu_1", command="python3 -c \"print(2+2)\""))
    denial = watch.see(_denied("toolu_1"))

    assert denial is not None
    assert denial.command == 'python3 -c "print(2+2)"'
    assert "approval" not in denial.command


def test_a_denial_of_a_tool_without_a_command_still_names_the_tool() -> None:
    # WebFetch отказывают целиком: команды нет, но сказать владельцу всё равно есть что.
    watch = DenialWatch()
    watch.see(_tool_use("toolu_2", name="WebFetch", url="https://example.com"))
    denial = watch.see(
        _denied(
            "toolu_2",
            tool_name="WebFetch",
            message="Claude requested permissions to use WebFetch",
        )
    )

    assert denial == PermissionDenial(
        tool_name="WebFetch", tool_use_id="toolu_2", command=""
    )


def test_a_denial_without_a_remembered_call_does_not_invent_a_command() -> None:
    # Кадр вызова мог не дойти (обрыв, перезапуск перекачки) — Боб не выдумывает.
    watch = DenialWatch()

    denial = watch.see(_denied("toolu_unknown"))

    assert denial == PermissionDenial(
        tool_name="Bash", tool_use_id="toolu_unknown", command=""
    )


def test_the_right_call_is_picked_out_of_several() -> None:
    watch = DenialWatch()
    watch.see(_tool_use("toolu_1", command="uv run pytest"))
    watch.see(_tool_use("toolu_2", command="rm -rf .git"))
    watch.see(_tool_use("toolu_3", command="git status"))

    denial = watch.see(_denied("toolu_2"))

    assert denial is not None
    assert denial.command == "rm -rf .git"


def test_a_flattened_tool_use_event_is_remembered_too() -> None:
    # Поток знает обе формы (как и рендер): вложенную и уплощённую.
    watch = DenialWatch()
    watch.see(
        {"type": "tool_use", "id": "toolu_9", "name": "Bash", "input": {"command": "rm -rf x"}}
    )

    denial = watch.see(_denied("toolu_9"))

    assert denial is not None
    assert denial.command == "rm -rf x"


# --------------------------------------------------------------------------- #
# Что отказом НЕ является
# --------------------------------------------------------------------------- #


def test_an_ordinary_event_is_not_a_denial() -> None:
    watch = DenialWatch()

    assert watch.see({"type": "system", "subtype": "init", "session_id": "s"}) is None
    assert watch.see({"type": "result", "subtype": "success"}) is None
    assert watch.see(_tool_use("toolu_1", command="git status")) is None
    assert watch.see({}) is None


def test_a_denial_shaped_event_of_another_type_is_ignored() -> None:
    # 🔴 subtype один, а тип другой: чужое событие не смеет поднять владельца ночью.
    watch = DenialWatch()

    assert watch.see({"type": "assistant", "subtype": "permission_denied"}) is None


def test_a_repeat_inside_a_tool_result_is_not_a_second_denial() -> None:
    # 🔴 Проверено записями живого прогона: повтор приходит событием ``user`` с блоком
    # ``tool_result``, а НЕ вторым system/permission_denied. Дедупликации в ядре нет
    # (её убрали как неизмеренную), и вот почему её отсутствие безопасно.
    watch = DenialWatch()
    watch.see(_tool_use("toolu_1", command="rm -rf .git"))
    watch.see(_denied("toolu_1"))

    echo = watch.see(
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "is_error": True,
                        "content": "This command requires approval",
                    }
                ],
            },
        }
    )

    assert echo is None


def test_two_calls_in_one_frame_are_both_remembered() -> None:
    # Модель зовёт инструменты пачкой в ОДНОМ кадре; отказ может прийти на любой из них.
    watch = DenialWatch()
    watch.see(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "Bash",
                        "input": {"command": "uv run pytest"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_2",
                        "name": "Bash",
                        "input": {"command": "rm -rf build"},
                    },
                ],
            },
        }
    )

    first = watch.see(_denied("toolu_1"))
    second = watch.see(_denied("toolu_2"))

    assert first is not None
    assert first.command == "uv run pytest"
    assert second is not None
    assert second.command == "rm -rf build"


def test_a_call_whose_input_is_not_a_mapping_names_no_command() -> None:
    watch = DenialWatch()
    watch.see({"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": "не словарь"})

    denial = watch.see(_denied("toolu_1"))

    assert denial is not None
    assert denial.command == ""


def test_a_command_that_is_not_a_string_is_not_spoken() -> None:
    watch = DenialWatch()
    watch.see(_tool_use("toolu_1", command={"weird": True}))

    denial = watch.see(_denied("toolu_1"))

    assert denial is not None
    assert denial.command == ""


def test_the_watch_does_not_grow_without_bound() -> None:
    # Живая сессия делает тысячи вызовов; помнить их все — течь памятью в фоне.
    watch = DenialWatch(remember=4)
    for index in range(50):
        watch.see(_tool_use(f"toolu_{index}", command=f"echo {index}"))

    fresh = watch.see(_denied("toolu_49"))
    stale = watch.see(_denied("toolu_0"))

    assert fresh is not None
    assert fresh.command == "echo 49"
    assert stale is not None
    assert stale.command == ""


def test_the_watch_remembers_exactly_as_many_calls_as_it_promised() -> None:
    # 🔴 Граница ровно на обещанном числе: «на один меньше» — это забытый вызов, то есть
    # вопрос владельцу без команды там, где команда была.
    watch = DenialWatch(remember=2)
    for index in range(3):
        watch.see(_tool_use(f"toolu_{index}", command=f"echo {index}"))

    kept = watch.see(_denied("toolu_1"))
    evicted = watch.see(_denied("toolu_0"))

    assert kept is not None
    assert kept.command == "echo 1"
    assert evicted is not None
    assert evicted.command == ""
