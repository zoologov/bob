# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты дедупа/чистки плана plan-mode (BOB-041 .1).

claude в plan-mode эмитит план ДВАЖДЫ — текстом ``assistant``-события и снова в
финальном ``result``. Чистый хелпер :func:`_clean_plan` сводит собранные части к
финальному тексту плана ОДИН раз (без дубля ``## План``) и срезает служебную
преамбулу (``ExitPlanMode``-чаттер, «Let me write the plan.»). Нормальный
одно-источниковый план остаётся без изменений.
"""

from __future__ import annotations

from bob.application.usecases.coding_assistant import (
    _clean_plan,
    _plan_part,
    _PlanPart,
)


def _parts(*events: dict[str, object]) -> list[_PlanPart]:
    collected: list[_PlanPart] = []
    for event in events:
        part = _plan_part(event)
        if part is not None:
            collected.append(part)
    return collected


def _assistant(text: str) -> dict[str, object]:
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _result(text: str) -> dict[str, object]:
    return {"type": "result", "subtype": "success", "result": text}


def test_plan_in_both_assistant_and_result_is_captured_once() -> None:
    plan = "## План\n\n- Шаг 1: правки\n- Шаг 2: тесты"
    parts = _parts(_assistant(plan), _result(plan))

    cleaned = _clean_plan(parts)

    assert cleaned.count("## План") == 1
    assert "Шаг 1: правки" in cleaned
    assert "Шаг 2: тесты" in cleaned


def test_preamble_noise_is_stripped() -> None:
    raw = (
        "ExitPlanMode isn't enabled here, so I'll just describe the plan.\n"
        "Let me write the plan.\n"
        "\n"
        "## План\n"
        "- Шаг 1"
    )
    parts = _parts(_result(raw))

    cleaned = _clean_plan(parts)

    assert "ExitPlanMode" not in cleaned
    assert "Let me write the plan" not in cleaned
    assert cleaned.startswith("## План")
    assert "- Шаг 1" in cleaned


def test_normal_single_source_plan_is_unchanged() -> None:
    plan = "## План\n\n- Один шаг"
    parts = _parts(_result(plan))

    assert _clean_plan(parts) == plan


def test_result_preferred_over_assistant_for_the_final_plan() -> None:
    # The assistant carries an early draft; the result is the authoritative final plan.
    parts = _parts(_assistant("Черновик плана"), _result("## План\n- Финальный шаг"))

    cleaned = _clean_plan(parts)

    assert cleaned == "## План\n- Финальный шаг"
    assert "Черновик" not in cleaned


def test_no_result_dedupes_identical_assistant_parts() -> None:
    plan = "## План\n- Шаг 1"
    parts = _parts(_assistant(plan), _assistant(plan))

    cleaned = _clean_plan(parts)

    assert cleaned.count("## План") == 1


def test_plan_in_both_assistant_and_result_with_preamble_cleaned_once() -> None:
    # BRIEF acceptance: a plan-mode stream carrying the plan in BOTH the streamed
    # `assistant` text AND the final `result` — with the `result` led by planning
    # preamble — yields the plan ONCE (no duplicated `## План`) and the preamble gone.
    plan_body = "## План\n\n- Шаг 1: правки\n- Шаг 2: тесты"
    result_with_preamble = (
        "Okay, let me write the plan.\n"
        "ExitPlanMode is unavailable, so here is the plan.\n"
        "\n" + plan_body
    )
    parts = _parts(_assistant(plan_body), _result(result_with_preamble))

    cleaned = _clean_plan(parts)

    assert cleaned.count("## План") == 1  # captured once, not assistant + result both
    assert cleaned.startswith("## План")  # preamble stripped — the plan leads
    assert "let me write the plan" not in cleaned.casefold()
    assert "ExitPlanMode" not in cleaned
    assert "Шаг 1: правки" in cleaned
    assert "Шаг 2: тесты" in cleaned


def test_no_result_drops_a_shorter_fragment_superseded_by_a_later_one() -> None:
    # A streamed draft is later re-emitted EXTENDED; the earlier (contained) fragment is
    # dropped so the plan is not duplicated when there is no authoritative `result`.
    short = "## План\n- Шаг 1"
    extended = "## План\n- Шаг 1\n- Шаг 2"
    parts = _parts(_assistant(short), _assistant(extended))

    cleaned = _clean_plan(parts)

    assert cleaned == extended
    assert cleaned.count("## План") == 1


def test_no_result_drops_a_later_fragment_already_covered() -> None:
    # The reverse order: the extended draft arrives first, then a shorter fragment that
    # is already contained in it — the redundant later fragment is dropped (no echo).
    extended = "## План\n- Шаг 1\n- Шаг 2"
    short = "## План\n- Шаг 1"
    parts = _parts(_assistant(extended), _assistant(short))

    cleaned = _clean_plan(parts)

    assert cleaned == extended


def test_no_result_skips_blank_assistant_fragments() -> None:
    # A blank/whitespace fragment in the no-`result` join contributes nothing (it is
    # skipped, not joined as an empty line) — robustness against a degraded stream.
    parts = [_PlanPart("assistant", "   "), _PlanPart("assistant", "## План\n- Шаг 1")]

    cleaned = _clean_plan(parts)

    assert cleaned == "## План\n- Шаг 1"
