# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Тесты чистого протокола PrivilegeJudge — промпт + парсер (BOB-052 .1).

Модель-обращённая половина шва, чистая (без I/O): ``build_privilege_user_prompt``
сворачивает ``PrivilegeContext`` (текст запроса + подсказки доступных capability +
лёгкий контекст) в Tier-0 user-prompt; ``parse_privilege_need`` мапит ответ модели в
``PrivilegeNeed``. Консервативно: обычная болтовня / общее знание → ``needs_permission
=False``; невалидный ответ → RAISE (а не тихий дефолт).
"""

from __future__ import annotations

import pytest

from bob.domain.permission.privilege import (
    PRIVILEGE_JUDGE_SYSTEM_PROMPT,
    PrivilegeContext,
    PrivilegeJudgeParseError,
    PrivilegeNeed,
    build_privilege_user_prompt,
    parse_privilege_need,
)


def _context() -> PrivilegeContext:
    return PrivilegeContext(
        request_text="покажи задачи проекта",
        capability_hints=("show_tasks", "run_coding_session"),
        recent_thread="Норман: привет\nbob: привет",
    )


def test_prompt_includes_request_text_and_capability_hints() -> None:
    prompt = build_privilege_user_prompt(_context())

    assert "покажи задачи проекта" in prompt
    assert "show_tasks" in prompt
    assert "run_coding_session" in prompt


def test_prompt_includes_recent_thread_when_present() -> None:
    prompt = build_privilege_user_prompt(_context())
    assert "Норман: привет" in prompt


def test_prompt_tolerates_no_capabilities_and_no_thread() -> None:
    ctx = PrivilegeContext(
        request_text="как дела?", capability_hints=(), recent_thread=""
    )
    prompt = build_privilege_user_prompt(ctx)
    assert "как дела?" in prompt


def test_parses_a_privileged_need() -> None:
    raw = "needs_permission: yes\nkind: owner_data\nwhat: показать задачи проекта"

    need = parse_privilege_need(raw)

    assert need.needs_permission is True
    assert need.kind == "owner_data"
    assert need.what == "показать задачи проекта"


def test_parses_a_tool_need() -> None:
    raw = "needs_permission: yes\nkind: tool\nwhat: запустить кодинг-сессию"
    need = parse_privilege_need(raw)
    assert need.needs_permission is True
    assert need.kind == "tool"


def test_plain_message_is_not_privileged_conservative_default() -> None:
    raw = "needs_permission: no\nkind: \nwhat: "

    need = parse_privilege_need(raw)

    assert need.needs_permission is False


def test_parses_internal_kind() -> None:
    raw = "needs_permission: yes\nkind: internal\nwhat: раскрыть внутреннюю заметку"
    need = parse_privilege_need(raw)
    assert need.kind == "internal"


def test_unknown_kind_on_a_privileged_need_raises() -> None:
    raw = "needs_permission: yes\nkind: nonsense\nwhat: что-то"
    with pytest.raises(PrivilegeJudgeParseError):
        parse_privilege_need(raw)


def test_garbage_reply_raises() -> None:
    with pytest.raises(PrivilegeJudgeParseError):
        parse_privilege_need("я не знаю что сказать")


def test_unrecognisable_needs_value_raises() -> None:
    # A labelled needs_permission with a non-yes/no value is not a safe parse.
    raw = "needs_permission: maybe\nkind: tool\nwhat: что-то"
    with pytest.raises(PrivilegeJudgeParseError):
        parse_privilege_need(raw)


def test_privileged_need_without_kind_raises() -> None:
    # needs_permission=yes with no usable kind is not a safe parse.
    raw = "needs_permission: yes\nwhat: что-то"
    with pytest.raises(PrivilegeJudgeParseError):
        parse_privilege_need(raw)


def test_system_prompt_states_the_conservative_contract() -> None:
    # The system prompt names the three privileged kinds and the conservative
    # "ordinary conversation -> no" rule (BOB-051 public).
    lowered = PRIVILEGE_JUDGE_SYSTEM_PROMPT.lower()
    assert "tool" in lowered
    assert "internal" in lowered
    assert "owner_data" in lowered


def test_need_is_frozen() -> None:
    need = PrivilegeNeed(needs_permission=False, kind="", what="")
    with pytest.raises((AttributeError, TypeError)):
        need.needs_permission = True  # type: ignore[misc]
