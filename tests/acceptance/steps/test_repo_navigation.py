# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the repo-navigation acceptance scenarios (BOB-067).

Binds ``repo_navigation.feature`` to the real-capability harness
(:mod:`tests.acceptance.repo_nav_harness`): each scenario drives a tool the model
would call (``list_dir`` / ``find_file`` / ``read_code``) over a REAL on-disk tree
and asserts Bob's OBSERVABLE tool output — the text that reaches the model — never the
guard's private state. An escape past the repo is witnessed as an observable refusal
(the tool raises instead of listing).

The scenarios are synchronous (pytest-bdd), so each async tool call runs via
``asyncio.run`` inside its When step — no event loop is active around it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    DeniedPathError,
)
from tests.acceptance.repo_nav_harness import (
    GUARD_REL_PATH,
    PLANTED_LEAK,
    build_navigator,
    build_repo,
)

if TYPE_CHECKING:
    from pathlib import Path

    from bob.capabilities.ports import Capability

scenarios("../features/repo_navigation.feature")


@dataclass(slots=True)
class _NavContext:
    """Mutable slate the repo-navigation steps share: the wired tools + last output."""

    navigator: dict[str, Capability] = field(default_factory=dict)
    output: str = ""
    refused: bool = False


@pytest.fixture
def nav_context(tmp_path: Path) -> _NavContext:
    """A fresh repo tree + real capabilities per scenario."""
    return _NavContext()


def _run_tool(cap: Capability, args: dict[str, object]) -> str:
    """Drive one tool call synchronously and return its observable text field."""
    result = asyncio.run(cap.execute(args))
    assert isinstance(result, dict)
    # list_dir → 'entries'; find_file / read_code → 'matches'. One text field either way.
    (value,) = result.values()
    return str(value)


@given("у Боба есть репозиторий с деревом файлов и подключёнными инструментами")
def repo_with_tools(nav_context: _NavContext, tmp_path: Path) -> None:
    build_repo(tmp_path)
    nav_context.navigator = build_navigator(tmp_path)


@when(parsers.parse('владелец просит перечислить директорию "{path}"'))
def owner_lists_dir(nav_context: _NavContext, path: str) -> None:
    cap = nav_context.navigator["list_dir"]
    try:
        nav_context.output = _run_tool(cap, {"path": path})
    except DeniedPathError:
        nav_context.refused = True


@when(parsers.parse('владелец просит найти файл "{pattern}"'))
def owner_finds_file(nav_context: _NavContext, pattern: str) -> None:
    cap = nav_context.navigator["find_file"]
    nav_context.output = _run_tool(cap, {"pattern": pattern})


@when(parsers.parse('владелец просит прочитать файл с секретом "{path}"'))
def owner_reads_secret_file(nav_context: _NavContext, path: str) -> None:
    cap = nav_context.navigator["read_code"]
    nav_context.output = _run_tool(cap, {"query": path})


@then("в выводе видны реальные имена файлов этой директории")
def output_shows_real_entries(nav_context: _NavContext) -> None:
    # Non-recursive listing of .beadloom shows its real immediate child (the _graph
    # sub-folder), rendered as a real entry — not a confabulated name.
    assert "_graph" in nav_context.output


@then("в выводе виден реальный путь к найденному файлу")
def output_shows_real_path(nav_context: _NavContext) -> None:
    assert GUARD_REL_PATH in nav_context.output


@then("Боб честно сообщает, что ничего не найдено, и не выдумывает путь")
def output_is_honest_not_found(nav_context: _NavContext) -> None:
    # Honest emptiness (INV-N5): a "no files matching" report, and — critically — NO
    # fabricated real path invented to satisfy the request.
    assert "no files matching" in nav_context.output.lower()
    assert GUARD_REL_PATH not in nav_context.output


@then("инструмент отклоняет выход за границу репозитория без листинга")
def escape_is_refused(nav_context: _NavContext) -> None:
    assert nav_context.refused is True
    assert nav_context.output == ""


@then(
    "секрет-значение отсутствует в выводе, а на его месте стоит метка [REDACTED]"
)
def secret_is_redacted(nav_context: _NavContext) -> None:
    assert PLANTED_LEAK not in nav_context.output
    assert "REDACTED" in nav_context.output
