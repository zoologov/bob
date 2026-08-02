# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты verbose-режима render_stream_event + chunk_for_telegram (BOB-085.1).

Интерактив-DM (BOB-083) требует КУРИРОВАННЫЙ полный rich-рендер: assistant-текст целиком
с markdown-passthrough (не 200-символьный огрызок), компактные rich-строки вызовов
инструментов, щедро капнутый tool-результат в ``` код-блоке ``` + читаемые ошибки. Груп-
нарратив (``verbose=False``, BOB-082) остаётся байт-в-байт (INV-4). Чистый чанк-хелпер
режет длинный rich-текст ≤4096 по границам строк, НЕ разрывая fenced-код-блок
(переоткрывает fence на стыке). Детерминированно, без I/O — mutation-цель BOB-085.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.stream_render import chunk_for_telegram, render_stream_event

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


# --- INV-4: verbose=False байт-в-байт (регресс груп-нарратива) -----------------


def test_group_assistant_text_is_byte_identical() -> None:
    long_text = "слово " * 200
    event = _assistant(_text(long_text))
    assert render_stream_event(event, verbose=False) == render_stream_event(event)


def test_group_long_assistant_text_still_truncated_to_200() -> None:
    event = _assistant(_text("x" * 600))
    line = render_stream_event(event, verbose=False)
    assert line is not None
    assert len(line) <= 220
    assert line.endswith("…")


def test_group_tool_call_is_plain_no_emoji() -> None:
    event = _assistant(_tool_use("Edit", {"file_path": "src/bob/parser.py"}))
    assert render_stream_event(event, verbose=False) == "правлю `parser.py`"


def test_group_bash_is_plain() -> None:
    event = _assistant(_tool_use("Bash", {"command": "ls -la"}))
    assert render_stream_event(event, verbose=False) == "$ ls -la"


def test_group_tool_result_error_is_plain() -> None:
    event = _user_tool_result(content="Traceback: boom", is_error=True)
    assert render_stream_event(event, verbose=False) == "ошибка: Traceback: boom"


def test_group_tool_result_success_is_noise() -> None:
    event = _user_tool_result(content="ok, file written")
    assert render_stream_event(event, verbose=False) is None


# --- INV-1: verbose assistant-текст целиком (не огрызок) ----------------------


def test_verbose_long_assistant_text_is_full() -> None:
    # 600-символьный список багов доходит ЦЕЛИКОМ (не режется до 200).
    bug_list = "\n".join(f"{i}. баг с приоритетом P{i % 3} — описание длинное" for i in range(20))
    assert len(bug_list) > 200
    event = _assistant(_text(bug_list))
    rendered = render_stream_event(event, verbose=True)
    assert rendered is not None
    assert "…" not in rendered
    assert len(rendered) >= len(bug_list) - 5


# --- INV-2: verbose markdown passthrough --------------------------------------


def test_verbose_markdown_structure_preserved() -> None:
    md = "## Заголовок\n\n- пункт один\n- пункт два\n\nтекст с `кодом`."
    event = _assistant(_text(md))
    rendered = render_stream_event(event, verbose=True)
    assert rendered == md


def test_verbose_fenced_code_block_not_collapsed() -> None:
    md = "Вот код:\n\n```python\ndef f():\n    return  1\n```\n\nконец"
    event = _assistant(_text(md))
    rendered = render_stream_event(event, verbose=True)
    assert rendered is not None
    # Внутренние двойные пробелы кода не схлопнуты.
    assert "return  1" in rendered
    assert "```python" in rendered


def test_verbose_collapses_excess_blank_lines_outside_code() -> None:
    md = "первый\n\n\n\n\nвторой"
    event = _assistant(_text(md))
    rendered = render_stream_event(event, verbose=True)
    assert rendered == "первый\n\nвторой"


def test_verbose_empty_text_is_noise() -> None:
    assert render_stream_event(_assistant(_text("   \n  ")), verbose=True) is None


# --- INV-3: verbose вызовы инструментов — компактные rich-строки --------------


def test_verbose_edit_is_rich_line() -> None:
    event = _assistant(_tool_use("Edit", {"file_path": "src/bob/parser.py"}))
    assert render_stream_event(event, verbose=True) == "✏️ правлю `parser.py`"


def test_verbose_read_is_rich_line() -> None:
    event = _assistant(_tool_use("Read", {"file_path": "src/bob/app.py"}))
    assert render_stream_event(event, verbose=True) == "📄 читаю `app.py`"


def test_verbose_bash_command_in_monospace() -> None:
    event = _assistant(_tool_use("Bash", {"command": "ls -la src/"}))
    assert render_stream_event(event, verbose=True) == "$ `ls -la src/`"


def test_verbose_bash_test_command() -> None:
    event = _assistant(_tool_use("Bash", {"command": "pytest -q"}))
    assert render_stream_event(event, verbose=True) == "🧪 гоняю тесты"


def test_verbose_grep_is_rich_line() -> None:
    event = _assistant(_tool_use("Grep", {"pattern": "foo"}))
    assert render_stream_event(event, verbose=True) == "🔍 ищу «foo»"


def test_verbose_glob_is_rich_line() -> None:
    event = _assistant(_tool_use("Glob", {"pattern": "*.py"}))
    assert render_stream_event(event, verbose=True) == "🔍 ищу файлы «*.py»"


def test_verbose_long_bash_command_is_capped() -> None:
    event = _assistant(_tool_use("Bash", {"command": "echo " + "x" * 500}))
    line = render_stream_event(event, verbose=True)
    assert line is not None
    assert len(line) < 200


# --- INV-3: verbose tool-результат щедро капнут в код-блоке --------------------


def test_verbose_tool_result_in_fenced_block() -> None:
    event = _user_tool_result(content="файл записан\nвсё ок")
    rendered = render_stream_event(event, verbose=True)
    assert rendered == "```\nфайл записан\nвсё ок\n```"


def test_verbose_huge_tool_result_is_capped_with_marker() -> None:
    event = _user_tool_result(content="A" * 5000)
    rendered = render_stream_event(event, verbose=True)
    assert rendered is not None
    assert rendered.startswith("```\n")
    assert rendered.endswith("\n```")
    assert "…(обрезано)" in rendered
    # Щедрый, но конечный кэп ~1500 (+ разметка код-блока и маркер).
    assert len(rendered) < 1600


def test_verbose_tool_result_error_is_readable() -> None:
    event = _user_tool_result(content="Traceback (most recent call last):\n  boom", is_error=True)
    rendered = render_stream_event(event, verbose=True)
    assert rendered is not None
    assert rendered.startswith("ошибка:")
    assert "```" in rendered
    assert "boom" in rendered


def test_verbose_empty_tool_result_is_noise() -> None:
    assert render_stream_event(_user_tool_result(content="   "), verbose=True) is None


def test_verbose_top_level_error_is_readable() -> None:
    rendered = render_stream_event({"type": "error", "message": "subprocess died"}, verbose=True)
    assert rendered is not None
    assert rendered.startswith("ошибка:")
    assert "subprocess died" in rendered


# --- chunk_for_telegram: границы, лимит, код-блок ------------------------------


def _fence_count(chunk: str) -> int:
    return sum(1 for line in chunk.split("\n") if line.strip().startswith("```"))


def test_chunk_under_limit_is_single() -> None:
    assert chunk_for_telegram("короткий текст") == ["короткий текст"]


def test_chunk_over_limit_splits_into_pieces_within_limit() -> None:
    text = "\n".join(f"строка номер {i}" for i in range(2000))
    chunks = chunk_for_telegram(text, limit=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunk_prefers_line_boundaries() -> None:
    text = "\n".join("abc" for _ in range(100))
    chunks = chunk_for_telegram(text, limit=20)
    # Ни один кусок не заканчивается посреди строки «ab» без границы.
    for chunk in chunks:
        assert not chunk.endswith("ab")


def test_chunk_closes_and_reopens_fence_across_boundary() -> None:
    body = "\n".join(f"код-строка {i}" for i in range(200))
    text = f"```python\n{body}\n```"
    chunks = chunk_for_telegram(text, limit=200)
    assert len(chunks) > 1
    # Каждый кусок — сбалансированный markdown (чётное число fence-маркеров).
    for chunk in chunks:
        assert _fence_count(chunk) % 2 == 0
        assert len(chunk) <= 200
    # Язык переоткрыт на стыке.
    assert chunks[1].startswith("```python")


def test_chunk_over_limit_single_line_hard_splits() -> None:
    text = "y" * 5000
    chunks = chunk_for_telegram(text, limit=1000)
    assert len(chunks) >= 5
    assert all(len(c) <= 1000 for c in chunks)


def test_chunk_exact_limit_stays_single() -> None:
    text = "z" * 4096
    assert chunk_for_telegram(text) == [text]
