# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for the pure session key-fact accumulator (no I/O) — BOB-087.B1.

``WorkFactsAccumulator`` is a mutation core: it folds the raw claude stream-json
events a coding session already produces into a small BOUNDED :class:`SessionKeyFacts`
snapshot — the touched files (dedup, capped), whether tests passed/failed, and short
"what broke" error snippets (dedup, capped). It is the DISTILLED substance of a session,
NOT the raw firehose: system-init / plain assistant prose / unknown events are ignored.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.coding.work_facts import (
    _MAX_ERRORS,
    _MAX_FILES,
    SessionKeyFacts,
    WorkFactsAccumulator,
    WorkOutcome,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _edit(path: str, tool: str = "Edit") -> Mapping[str, object]:
    return {"type": "tool_use", "name": tool, "input": {"file_path": path}}


def _read(path: str) -> Mapping[str, object]:
    return {"type": "tool_use", "name": "Read", "input": {"file_path": path}}


def _tool_result(text: str, *, is_error: bool = False) -> Mapping[str, object]:
    return {"type": "tool_result", "content": text, "is_error": is_error}


def _fold(events: list[Mapping[str, object]]) -> SessionKeyFacts:
    acc = WorkFactsAccumulator()
    for event in events:
        acc.observe(event)
    return acc.snapshot()


def test_empty_accumulator_is_empty() -> None:
    facts = WorkFactsAccumulator().snapshot()
    assert facts == SessionKeyFacts()
    assert facts.is_empty() is True


def test_captures_touched_file_basenames() -> None:
    facts = _fold([_edit("src/bob/coding/interactive_runner.py"), _read("tests/x.py")])
    assert facts.files == ("interactive_runner.py", "x.py")
    assert facts.is_empty() is False


def test_dedups_repeated_files_preserving_first_order() -> None:
    facts = _fold([_edit("a/foo.py"), _read("b/foo.py"), _edit("bar.py"), _edit("foo.py")])
    assert facts.files == ("foo.py", "bar.py")


def test_files_are_capped() -> None:
    facts = _fold([_edit(f"f{i}.py") for i in range(_MAX_FILES + 10)])
    assert len(facts.files) == _MAX_FILES


def test_all_edit_tools_count_as_touched() -> None:
    for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        facts = _fold([_edit("mod.py", tool=tool)])
        assert facts.files == ("mod.py",)


def test_tests_passed_from_tool_result() -> None:
    facts = _fold([_tool_result("=== 12 passed in 0.4s ===")])
    assert facts.tests_passed is True
    assert facts.tests_failed is False


def test_tests_failed_from_tool_result() -> None:
    facts = _fold([_tool_result("=== 2 failed, 10 passed ===", is_error=True)])
    assert facts.tests_failed is True
    assert facts.tests_passed is True


def test_error_result_captures_what_broke() -> None:
    facts = _fold([_tool_result("Traceback: ValueError: buffer over 64KB", is_error=True)])
    assert facts.tests_failed is False
    assert any("ValueError" in err for err in facts.errors)


def test_errors_dedup_and_cap() -> None:
    same = [_tool_result("boom", is_error=True) for _ in range(5)]
    distinct = [_tool_result(f"err {i}", is_error=True) for i in range(_MAX_ERRORS + 5)]
    facts = _fold(same + distinct)
    assert facts.errors.count("boom") == 1
    assert len(facts.errors) == _MAX_ERRORS


def test_ignores_firehose_noise() -> None:
    noise: list[Mapping[str, object]] = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "думаю…"}]}},
        {"type": "unknown_event"},
        {},
    ]
    assert _fold(noise) == SessionKeyFacts()


def test_nested_assistant_tool_use_is_captured() -> None:
    event = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "правлю файл"},
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "deep/mod.py"}},
            ]
        },
    }
    assert _fold([event]).files == ("mod.py",)


def test_nested_user_tool_result_is_captured() -> None:
    event = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "3 passed"}]},
    }
    assert _fold([event]).tests_passed is True


def test_final_error_result_event_captured() -> None:
    facts = _fold([{"type": "result", "subtype": "error", "result": "process crashed"}])
    assert any("crashed" in err for err in facts.errors)


def test_top_level_error_event_captured() -> None:
    facts = _fold([{"type": "error", "message": "stream broke"}])
    assert any("stream broke" in err for err in facts.errors)


def test_work_outcome_values() -> None:
    assert {o.value for o in WorkOutcome} == {"finished", "failed", "aborted"}
