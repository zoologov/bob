# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты narrate — чистый мэппер stream-json событий Claude Code (BOB-039 .1).

Событие (assistant с tool_use, user с tool_result, result, error, system) → короткая
русская строка нарратива; шумные/внутренние события → None. Поддержаны и вложенные
формы (tool_use в assistant.content, tool_result в user.content), и уплощённые
(type=tool_use/tool_result). Детерминированно, без I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.domain.coding.narrate import narrate

if TYPE_CHECKING:
    from collections.abc import Mapping


def _assistant_tool(name: str, tool_input: Mapping[str, object]) -> dict[str, object]:
    return {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": name, "input": dict(tool_input)}]
        },
    }


def _user_tool_result(
    *, content: object, is_error: bool = False
) -> dict[str, object]:
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "content": content, "is_error": is_error}
            ]
        },
    }


# --- Правки файлов ------------------------------------------------------------


def test_edit_narrates_file() -> None:
    event = _assistant_tool("Edit", {"file_path": "src/bob/parser.py"})
    assert narrate(event) == "правлю `parser.py`"


def test_write_narrates_file() -> None:
    event = _assistant_tool("Write", {"file_path": "/repo/a/b/new.py"})
    assert narrate(event) == "правлю `new.py`"


def test_flattened_tool_use_is_supported() -> None:
    event = {
        "type": "tool_use",
        "name": "Edit",
        "input": {"file_path": "x/y.py"},
    }
    assert narrate(event) == "правлю `y.py`"


def test_read_narrates_reading() -> None:
    event = _assistant_tool("Read", {"file_path": "src/bob/app.py"})
    assert narrate(event) == "читаю `app.py`"


# --- Тесты / команды ----------------------------------------------------------


def test_bash_pytest_narrates_running_tests() -> None:
    event = _assistant_tool("Bash", {"command": "pytest -q tests/"})
    assert narrate(event) == "запускаю тесты"


def test_bash_generic_command_is_noise() -> None:
    event = _assistant_tool("Bash", {"command": "ls -la"})
    assert narrate(event) is None


def test_navigation_tools_are_noise() -> None:
    assert narrate(_assistant_tool("Grep", {"pattern": "foo"})) is None
    assert narrate(_assistant_tool("Glob", {"pattern": "*.py"})) is None


# --- Результаты инструментов --------------------------------------------------


def test_tool_result_tests_passed() -> None:
    event = _user_tool_result(content="5 passed in 0.10s")
    assert narrate(event) == "тесты прошли"


def test_tool_result_error_narrates_error() -> None:
    event = _user_tool_result(content="Traceback: boom", is_error=True)
    line = narrate(event)
    assert line is not None
    assert line.startswith("ошибка:")


def test_tool_result_success_noise_is_none() -> None:
    event = _user_tool_result(content="ok, file written")
    assert narrate(event) is None


def test_tool_result_content_as_block_list() -> None:
    event = _user_tool_result(content=[{"type": "text", "text": "10 passed"}])
    assert narrate(event) == "тесты прошли"


# --- Финальный результат / ошибки ---------------------------------------------


def test_result_success_narrates_done() -> None:
    event = {"type": "result", "subtype": "success", "is_error": False, "result": "ok"}
    assert narrate(event) == "готово"


def test_result_error_narrates_error() -> None:
    event = {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
        "result": "too many turns",
    }
    line = narrate(event)
    assert line is not None
    assert line.startswith("ошибка:")


def test_error_event_narrates_error() -> None:
    event = {"type": "error", "message": "subprocess died"}
    line = narrate(event)
    assert line is not None
    assert line.startswith("ошибка:")


# --- Шум ----------------------------------------------------------------------


def test_system_event_is_noise() -> None:
    assert narrate({"type": "system", "subtype": "init"}) is None


def test_assistant_text_only_is_noise() -> None:
    event = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "сейчас посмотрю"}]},
    }
    assert narrate(event) is None


def test_unknown_event_is_noise() -> None:
    assert narrate({"type": "whatever"}) is None
    assert narrate({}) is None


def test_long_error_message_is_truncated() -> None:
    event = {"type": "error", "message": "x" * 500}
    line = narrate(event)
    assert line is not None
    assert len(line) < 120


# --- Устойчивость к битым событиям --------------------------------------------


def test_assistant_with_non_list_content_is_noise() -> None:
    event = {"type": "assistant", "message": {"content": "просто строка"}}
    assert narrate(event) is None


def test_tool_result_with_scalar_content_is_noise() -> None:
    event = _user_tool_result(content=42)
    assert narrate(event) is None


def test_result_error_without_detail_is_bare_error() -> None:
    event = {"type": "result", "is_error": True}
    assert narrate(event) == "ошибка"
