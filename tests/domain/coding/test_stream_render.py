# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты render_stream_event — чистый ПОЛНЫЙ рендер stream-json событий в DM (BOB-082.3).

В отличие от lossy :func:`~bob.coding.narrate.narrate` (глотает большинство), рендерер
лайв-стрима отдаёт строку на КАЖДЫЙ значимый вид события — вызов инструмента (имя + файл),
правка/чтение/тест, текст/прогресс ассистента, результат, ошибка. ``None`` только для
чистого шума (system-init/heartbeat/пустое/неизвестное). Детерминированно, без I/O.
Поддержаны вложенная (tool_use в assistant.content) и уплощённая (type=tool_use) формы.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.stream_render import render_stream_event

if TYPE_CHECKING:
    from collections.abc import Mapping


def _assistant(*blocks: Mapping[str, object]) -> dict[str, object]:
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool_use(name: str, tool_input: Mapping[str, object]) -> dict[str, object]:
    return {"type": "tool_use", "name": name, "input": dict(tool_input)}


def _text(text: str) -> dict[str, object]:
    return {"type": "text", "text": text}


def _user_tool_result(*, content: object, is_error: bool = False) -> dict[str, object]:
    return {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "content": content, "is_error": is_error}]
        },
    }


# --- Правки / чтение файлов ----------------------------------------------------


def test_edit_renders_file() -> None:
    event = _assistant(_tool_use("Edit", {"file_path": "src/bob/parser.py"}))
    assert render_stream_event(event) == "правлю `parser.py`"


def test_write_renders_file() -> None:
    event = _assistant(_tool_use("Write", {"file_path": "/repo/a/b/new.py"}))
    assert render_stream_event(event) == "правлю `new.py`"


def test_multiedit_renders_file() -> None:
    event = _assistant(_tool_use("MultiEdit", {"file_path": "x/y.py"}))
    assert render_stream_event(event) == "правлю `y.py`"


def test_read_renders_reading() -> None:
    event = _assistant(_tool_use("Read", {"file_path": "src/bob/app.py"}))
    assert render_stream_event(event) == "читаю `app.py`"


def test_flattened_tool_use_is_supported() -> None:
    event = _tool_use("Edit", {"file_path": "x/y.py"})
    assert render_stream_event(event) == "правлю `y.py`"


# --- Тесты / команды ----------------------------------------------------------


def test_bash_pytest_renders_running_tests() -> None:
    event = _assistant(_tool_use("Bash", {"command": "pytest -q tests/"}))
    assert render_stream_event(event) == "гоняю тесты"


def test_bash_generic_command_is_shown() -> None:
    # Unlike narrate (which drops non-test Bash as noise), the DM live stream SHOWS the
    # command — the owner is watching a terminal.
    event = _assistant(_tool_use("Bash", {"command": "ls -la src/"}))
    assert render_stream_event(event) == "$ ls -la src/"


def test_bash_empty_command_is_noise() -> None:
    event = _assistant(_tool_use("Bash", {"command": ""}))
    assert render_stream_event(event) is None


def test_long_bash_command_is_truncated() -> None:
    event = _assistant(_tool_use("Bash", {"command": "echo " + "x" * 500}))
    line = render_stream_event(event)
    assert line is not None
    assert len(line) < 140


# --- Навигационные инструменты (в DM показываем, не глотаем) -------------------


def test_grep_is_shown() -> None:
    event = _assistant(_tool_use("Grep", {"pattern": "foo"}))
    assert render_stream_event(event) == "ищу «foo»"


def test_glob_is_shown() -> None:
    event = _assistant(_tool_use("Glob", {"pattern": "*.py"}))
    assert render_stream_event(event) == "ищу файлы «*.py»"


def test_other_named_tool_shows_its_name() -> None:
    event = _assistant(_tool_use("TodoWrite", {}))
    assert render_stream_event(event) == "TodoWrite"


def test_unnamed_tool_is_noise() -> None:
    event = _assistant(_tool_use("", {}))
    assert render_stream_event(event) is None


# --- Текст / прогресс ассистента (в DM показываем) ----------------------------


def test_assistant_text_is_shown() -> None:
    event = _assistant(_text("Сейчас поправлю парсер."))
    assert render_stream_event(event) == "Сейчас поправлю парсер."


def test_long_assistant_text_is_truncated() -> None:
    event = _assistant(_text("слово " * 200))
    line = render_stream_event(event)
    assert line is not None
    assert len(line) <= 220


def test_assistant_text_and_tool_use_both_rendered() -> None:
    event = _assistant(
        _text("Правлю файл."), _tool_use("Edit", {"file_path": "a/b.py"})
    )
    assert render_stream_event(event) == "Правлю файл.\nправлю `b.py`"


def test_empty_assistant_is_noise() -> None:
    assert render_stream_event(_assistant()) is None


def test_assistant_with_non_list_content_is_noise() -> None:
    assert render_stream_event({"type": "assistant", "message": {"content": "x"}}) is None


# --- Результаты инструментов --------------------------------------------------


def test_tool_result_tests_passed() -> None:
    event = _user_tool_result(content="5 passed in 0.10s")
    assert render_stream_event(event) == "тесты прошли"


def test_tool_result_error_is_shown() -> None:
    # Unlike narrate (which suppresses per-tool errors), the private DM live stream SHOWS
    # trial-and-error detail — the owner is watching the raw terminal.
    event = _user_tool_result(content="Traceback: boom", is_error=True)
    line = render_stream_event(event)
    assert line is not None
    assert line.startswith("ошибка:")
    assert "boom" in line


def test_tool_result_success_noise_is_none() -> None:
    event = _user_tool_result(content="ok, file written")
    assert render_stream_event(event) is None


def test_tool_result_content_as_block_list() -> None:
    event = _user_tool_result(content=[{"type": "text", "text": "10 passed"}])
    assert render_stream_event(event) == "тесты прошли"


# --- Финальный результат / ошибки ---------------------------------------------


def test_result_success_renders_done() -> None:
    event = {"type": "result", "subtype": "success", "is_error": False, "result": "ok"}
    assert render_stream_event(event) == "готово"


def test_result_error_renders_error() -> None:
    event = {
        "type": "result",
        "subtype": "error_max_turns",
        "is_error": True,
        "result": "too many turns",
    }
    line = render_stream_event(event)
    assert line is not None
    assert line.startswith("ошибка:")
    # The ``result`` detail (preferred over ``subtype``) reaches the owner verbatim.
    assert "too many turns" in line


def test_result_bare_success_is_done() -> None:
    # No is_error and no subtype → the success default → «готово» (not an error).
    assert render_stream_event({"type": "result"}) == "готово"


def test_result_error_subtype_without_is_error_flag_is_error() -> None:
    # A non-"success" subtype alone (is_error absent) still routes to the error line, and
    # the subtype is the fallback detail when no ``result`` text is present.
    line = render_stream_event({"type": "result", "subtype": "error_max_turns"})
    assert line == "ошибка: error_max_turns"


def test_result_error_without_detail_is_bare_error() -> None:
    assert render_stream_event({"type": "result", "is_error": True}) == "ошибка"


def test_long_result_error_is_truncated() -> None:
    event = {"type": "result", "is_error": True, "result": "x" * 500}
    line = render_stream_event(event)
    assert line is not None
    assert len(line) < 120


def test_top_level_error_event_is_shown() -> None:
    line = render_stream_event({"type": "error", "message": "subprocess died"})
    assert line is not None
    assert line.startswith("ошибка:")


# --- Шум ----------------------------------------------------------------------


def test_system_event_is_noise() -> None:
    assert render_stream_event({"type": "system", "subtype": "init"}) is None


def test_unknown_event_is_noise() -> None:
    assert render_stream_event({"type": "whatever"}) is None
    assert render_stream_event({}) is None


# --- Missing-key / boundary edges (mutation gap-fill, BOB-082.5) ---------------
# Each pins a default/fallback/boundary the happy-path tests left latent, so a mutant
# that swaps the default value or the boundary operator is caught.


def test_flattened_tool_result_event_is_supported() -> None:
    # The uplifted ``type=tool_result`` form (not nested in a user event) renders too.
    assert render_stream_event({"type": "tool_result", "content": "7 passed"}) == "тесты прошли"


def test_flattened_tool_use_without_name_is_noise() -> None:
    # A flattened tool_use lacking a name is noise (not the literal "None").
    assert render_stream_event({"type": "tool_use", "input": {}}) is None


def test_nested_tool_use_block_without_name_is_noise() -> None:
    assert render_stream_event(_assistant({"type": "tool_use", "input": {}})) is None


def test_nested_text_block_without_text_is_noise() -> None:
    assert render_stream_event(_assistant({"type": "text"})) is None


def test_multiple_tool_results_in_one_user_event_are_newline_joined() -> None:
    event = _user_tool_result(content="boom", is_error=True)
    event["message"] = {
        "content": [
            {"type": "tool_result", "content": "boom", "is_error": True},
            {"type": "tool_result", "content": "3 passed", "is_error": False},
        ]
    }
    line = render_stream_event(event)
    assert line is not None
    assert line == "ошибка: boom\nтесты прошли"


def test_bash_without_command_is_noise() -> None:
    assert render_stream_event(_assistant(_tool_use("Bash", {}))) is None


def test_grep_without_pattern_renders_empty_query() -> None:
    assert render_stream_event(_assistant(_tool_use("Grep", {}))) == "ищу «»"


def test_glob_without_pattern_renders_empty_query() -> None:
    assert render_stream_event(_assistant(_tool_use("Glob", {}))) == "ищу файлы «»"


def test_edit_without_file_path_falls_back_to_placeholder() -> None:
    # Empty path → the «файл» placeholder (not the raw default sentinel).
    assert render_stream_event(_assistant(_tool_use("Edit", {}))) == "правлю `файл`"


def test_edit_windows_path_is_normalised_to_basename() -> None:
    # Backslashes are normalised to slashes before taking the basename.
    event = _assistant(_tool_use("Edit", {"file_path": "dir\\sub\\file.py"}))
    assert render_stream_event(event) == "правлю `file.py`"


def test_edit_bare_filename_without_directory_is_the_basename() -> None:
    assert render_stream_event(_assistant(_tool_use("Edit", {"file_path": "solo.py"}))) == (
        "правлю `solo.py`"
    )


def test_top_level_error_reads_the_error_key_when_no_message() -> None:
    line = render_stream_event({"type": "error", "error": "kaboom"})
    assert line == "ошибка: kaboom"


def test_error_detail_whitespace_is_collapsed_to_single_spaces() -> None:
    line = render_stream_event({"type": "error", "message": "line one\n\n line two"})
    assert line == "ошибка: line one line two"


def test_assistant_text_at_exact_limit_is_not_truncated() -> None:
    # Boundary: length == limit keeps the text verbatim (no ellipsis) — pins the ``<=``.
    text = "x" * 200
    rendered = render_stream_event(_assistant(_text(text)))
    assert rendered == text
    assert "…" not in (rendered or "")


def test_error_tool_result_without_text_has_no_detail() -> None:
    # A block-list content with no text → an empty detail → bare «ошибка» (not "None").
    event = _user_tool_result(content=[{"type": "text"}], is_error=True)
    assert render_stream_event(event) == "ошибка"


def test_error_tool_result_joins_multiple_text_blocks_with_a_space() -> None:
    event = _user_tool_result(content=[{"text": "foo"}, {"text": "bar"}], is_error=True)
    assert render_stream_event(event) == "ошибка: foo bar"


def test_error_tool_result_non_text_content_has_no_detail() -> None:
    event = _user_tool_result(content=123, is_error=True)
    assert render_stream_event(event) == "ошибка"
