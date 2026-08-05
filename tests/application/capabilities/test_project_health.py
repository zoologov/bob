# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``project_health`` — «как дела у проекта» (BOB-091.2).

ONE tool over the six read-only beadloom reports, not six near-identical tools: the
manifest is already large, and six siblings that differ by one word would make the
model's choice worse, not better. What matters here: the closed list is what the model
sees, the chosen report reaches the port together with the ``diff`` ref, the answer says
WHICH report it is, and a value outside the list comes back as a readable error naming
the legal ones rather than a crashed turn.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.capabilities.introspection.health_form import HEALTH_CHECKS
from bob.capabilities.usecases.project_health import make_project_health_capability

from .fakes import FakeRepoIntrospector

_REPORT = "Пар док↔код: 585 — все свежие."


def test_capability_advertises_the_closed_list_of_reports() -> None:
    cap = make_project_health_capability(FakeRepoIntrospector())

    assert cap.name == "project_health"
    assert cap.permission == "safe"
    schema = cap.input_schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    check = properties["check"]
    assert isinstance(check, dict)
    # 🔴 The enum IS the closed list: the model never names a beadloom subcommand itself.
    assert check["enum"] == list(HEALTH_CHECKS)
    assert properties["since"] == {"type": "string"}
    assert schema["required"] == ["check"]


def test_the_description_names_every_report_so_the_model_can_choose() -> None:
    cap = make_project_health_capability(FakeRepoIntrospector())

    for check in HEALTH_CHECKS:
        assert check in cap.description


async def test_execute_delegates_the_check_and_returns_the_report() -> None:
    introspector = FakeRepoIntrospector(health_report=_REPORT)
    cap = make_project_health_capability(introspector)

    result = await cap.execute({"check": "sync-check"})

    assert introspector.health_calls == [("sync-check", None)]
    assert isinstance(result, Mapping)
    assert result["report"] == _REPORT
    # The answer says which report it is, so Bob cannot present one verdict as another's.
    assert result["check"] == "sync-check"


async def test_execute_passes_the_diff_ref_through() -> None:
    introspector = FakeRepoIntrospector(health_report="No graph changes since main.")
    cap = make_project_health_capability(introspector)

    await cap.execute({"check": "diff", "since": "main"})

    assert introspector.health_calls == [("diff", "main")]


async def test_a_blank_since_is_not_forwarded_as_a_ref() -> None:
    # An empty string from a model means "not asked"; forwarding it would look like a ref.
    introspector = FakeRepoIntrospector(health_report="ok")
    cap = make_project_health_capability(introspector)

    await cap.execute({"check": "diff", "since": "   "})

    assert introspector.health_calls == [("diff", None)]


async def test_a_non_string_since_is_refused_without_touching_the_port() -> None:
    introspector = FakeRepoIntrospector(health_report="ok")
    cap = make_project_health_capability(introspector)

    result = await cap.execute({"check": "diff", "since": 42})

    assert isinstance(result, Mapping)
    assert "error" in result
    assert introspector.health_calls == []


async def test_a_missing_check_is_refused_without_touching_the_port() -> None:
    introspector = FakeRepoIntrospector(health_report=_REPORT)
    cap = make_project_health_capability(introspector)

    result = await cap.execute({})

    assert isinstance(result, Mapping)
    assert "error" in result
    assert introspector.health_calls == []


async def test_a_refused_check_error_names_the_legal_reports() -> None:
    # 🔴 The refusal has to TEACH, or the model retries the same wrong value: the write
    # subcommands of the same CLI (``reindex`` / ``docs``) arrive here.
    introspector = FakeRepoIntrospector(raise_on_health=True)
    cap = make_project_health_capability(introspector)

    result = await cap.execute({"check": "reindex"})

    assert isinstance(result, Mapping)
    message = str(result["error"])
    for check in HEALTH_CHECKS:
        assert check in message


async def test_an_empty_report_is_honest_not_a_fabrication() -> None:
    introspector = FakeRepoIntrospector(health_report="")
    cap = make_project_health_capability(introspector)

    result = await cap.execute({"check": "doctor"})

    assert isinstance(result, Mapping)
    assert "не смог" in str(result["error"]).lower()


async def test_a_hostile_diff_ref_becomes_a_readable_error_about_the_ref() -> None:
    # 🔴 The two refusals must not be confused: telling the model "выбери другой отчёт"
    # when the REF was wrong sends it fixing the wrong argument.
    introspector = FakeRepoIntrospector(
        raise_on_health=True, health_error="not a valid git ref: 'main; rm -rf /'"
    )
    cap = make_project_health_capability(introspector)

    result = await cap.execute({"check": "diff", "since": "main; rm -rf /"})

    assert isinstance(result, Mapping)
    message = str(result["error"])
    assert "git-ref" in message
    assert "sync-check" not in message
