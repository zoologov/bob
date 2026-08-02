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

import pytest

from bob.coding.stream_render import (
    _MAX_RESULT,
    chunk_for_telegram,
    render_stream_event,
)

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


# --- INV-4: verbose=False == default across EVERY event kind (no regression) --


@pytest.mark.parametrize(
    "event",
    [
        _assistant(_text("слово " * 200)),  # long assistant text (concise truncation)
        _assistant(_tool_use("Edit", {"file_path": "src/bob/parser.py"})),  # edit
        _assistant(_tool_use("Read", {"file_path": "src/bob/app.py"})),  # read
        _assistant(_tool_use("Bash", {"command": "ls -la"})),  # bash command
        _assistant(_tool_use("Bash", {"command": "pytest -q"})),  # test command
        _assistant(_tool_use("Grep", {"pattern": "foo"})),  # grep
        _assistant(_tool_use("Glob", {"pattern": "*.py"})),  # glob
        _assistant(_tool_use("WeirdTool", {})),  # unknown tool → bare name
        _user_tool_result(content="12 passed in 0.3s"),  # tests-passed success
        _user_tool_result(content="Traceback: boom", is_error=True),  # error result
        _user_tool_result(content="ok, wrote file"),  # noise success
        {"type": "tool_use", "name": "Edit", "input": {"file_path": "x/y.py"}},  # flat
        {"type": "tool_result", "content": "boom", "is_error": True},  # flat result
        {"type": "result", "subtype": "success"},  # final ok
        {"type": "result", "is_error": True, "result": "died"},  # final error
        {"type": "error", "message": "subprocess died"},  # top-level error
        {"type": "system", "subtype": "init"},  # pure noise
    ],
)
def test_group_mode_is_byte_identical_to_default_for_every_event(
    event: Mapping[str, object],
) -> None:
    # INV-4: the one-way group path (verbose=False, the default) must stay byte-for-byte
    # what it was before BOB-085 — verbose is a strictly additive interactive-DM branch.
    assert render_stream_event(event, verbose=False) == render_stream_event(event)


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


# --- chunk_for_telegram: EXACT boundary output (mutation gap-fill) -------------
# These pin the precise chunk list at small limits so off-by-one accounting
# mutations (separator/reserve/current_len, and/or, >/>=) produce an observably
# different split and die. Inputs carry spaces so a wrong `split()` (whitespace)
# instead of `split("\n")` also diverges.


def test_chunk_groups_lines_to_exact_boundary() -> None:
    # Two 3-char lines fill limit=7 ("aXa"+"\n"+"bXb" == 7), the third overflows.
    assert chunk_for_telegram("a a\nb b\nc c\nd d", limit=7) == ["a a\nb b", "c c\nd d"]


def test_chunk_separator_is_counted_when_joining_lines() -> None:
    # 4+1(sep)+4 == 9 > 8 → the second line must start a new chunk (kills a dropped
    # or negated separator term).
    assert chunk_for_telegram("aaaa\nbbbb", limit=8) == ["aaaa", "bbbb"]


def test_chunk_keeps_lines_that_exactly_fill_the_limit_together() -> None:
    # 4+1+3 == 8 == limit → stays together (`>` not `>=`); the 8-char line overflows.
    assert chunk_for_telegram("aaaa\nbbb\nzzzzzzzz", limit=8) == ["aaaa\nbbb", "zzzzzzzz"]


def test_chunk_over_limit_single_line_hard_split_is_exact() -> None:
    # A lone 10-char line at limit=4 is hard-split into contiguous, non-overlapping,
    # order-preserving 4-char pieces (kills range start/step/stop mutants).
    assert chunk_for_telegram("0123456789", limit=4) == ["0123", "4567", "89"]


def test_chunk_fenced_block_split_reopens_language_tag_exactly() -> None:
    # A fenced ```py block that overflows closes ``` at each cut and REOPENS with the
    # language tag, every chunk balanced markdown — pinned exactly so fence-reserve /
    # reopen-opener mutants diverge.
    text = "```py\nAAAA\nBBBB\n```"
    assert chunk_for_telegram(text, limit=12) == [
        "```py\n```",
        "```py\nAAAA\n```",
        "```py\nBBBB\n```",
        "```py\n```",
    ]


def test_chunk_fence_reserve_accounts_for_the_closing_fence_exactly() -> None:
    # Inside a fence the split must reserve exactly the closing "```" (len+1 for its own
    # line), no more: an over-reservation would cut a line that in fact still fits.
    assert chunk_for_telegram("```\nx\nx\n```", limit=9) == [
        "```\nx\n```",
        "```\nx\n```",
        "```\n```",
    ]


def test_chunk_reopened_fence_line_uses_exactly_one_separator() -> None:
    # After a fence cut the reopened opener + next line are joined by exactly one "\n";
    # a miscounted separator would flush a line early.
    assert chunk_for_telegram("```\nxxxx\nx\n```", limit=13) == [
        "```\nxxxx\n```",
        "```\nx\n```",
    ]


# --- verbose: EXACT tool-result cap boundary + flattened events ---------------


def test_verbose_tool_result_at_exact_cap_has_no_truncation_marker() -> None:
    # Content exactly _MAX_RESULT long is emitted whole (``<=`` boundary, no marker).
    event = _user_tool_result(content="A" * _MAX_RESULT)
    rendered = render_stream_event(event, verbose=True)
    assert rendered == f"```\n{'A' * _MAX_RESULT}\n```"
    assert "…(обрезано)" not in rendered


def test_verbose_tool_result_one_over_cap_gets_marker() -> None:
    event = _user_tool_result(content="A" * (_MAX_RESULT + 1))
    rendered = render_stream_event(event, verbose=True)
    assert rendered is not None
    assert "…(обрезано)" in rendered


def test_verbose_flattened_tool_use_is_rich() -> None:
    # The flattened (type=tool_use) form must carry verbose through, not silently
    # fall back to the concise group prefix.
    event = {"type": "tool_use", "name": "Read", "input": {"file_path": "a/b.py"}}
    assert render_stream_event(event, verbose=True) == "📄 читаю `b.py`"


def test_verbose_flattened_tool_result_is_fenced() -> None:
    event = {"type": "tool_result", "content": "файл ок"}
    assert render_stream_event(event, verbose=True) == "```\nфайл ок\n```"


def test_verbose_result_error_is_fenced_exactly() -> None:
    event = {"type": "result", "is_error": True, "result": "boom"}
    assert render_stream_event(event, verbose=True) == "ошибка:\n```\nboom\n```"


def test_verbose_top_level_error_is_fenced_exactly() -> None:
    event = {"type": "error", "message": "subprocess died"}
    assert render_stream_event(event, verbose=True) == "ошибка:\n```\nsubprocess died\n```"


def test_verbose_error_with_no_detail_is_bare_word() -> None:
    # An error event with no message/result → the bare "ошибка" fallback (no fence, no
    # detail) — pins the empty-detail branch label exactly.
    assert render_stream_event({"type": "error"}, verbose=True) == "ошибка"
    assert render_stream_event({"type": "result", "is_error": True}, verbose=True) == "ошибка"


# --- verbose: collapse-prose keeps code verbatim, folds prose blanks (exact) ---


def test_verbose_collapse_folds_prose_blanks_but_keeps_every_code_block() -> None:
    # Two fenced blocks with prose around them: prose runs of 3+ blank lines fold to
    # one, code (incl. trailing spaces "d  ") stays verbatim — pins the even/odd
    # segment classification so index-parity mutants misclassify and die.
    text = "A\n```\nc1\n```\nB\n```\nd  \n```\nC\n\n\n\nD"
    event = _assistant(_text(text))
    assert render_stream_event(event, verbose=True) == "A\n```\nc1\n```\nB\n```\nd  \n```\nC\n\nD"
