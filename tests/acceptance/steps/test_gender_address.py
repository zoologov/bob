# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the gender-of-address acceptance scenarios (BOB-078 A).

Binds ``gender_address.feature`` to :mod:`tests.acceptance.gender_address_harness`, which
drives the REAL graph and returns the reply-compose prompt the Tier-1 model was handed. The
scenarios witness, at that boundary, that a feminine self-presentation folds «в женском роде»
into the prompt while a name-only turn forces no gender — never the detector's private state.

Synchronous (pytest-bdd), so the async graph runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from tests.acceptance.gender_address_harness import run_gender_address_turn

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/gender_address.feature")


@dataclass(slots=True)
class _GenderContext:
    """The slate the steps share: temp db root + the captured compose prompt."""

    tmp_path: Path
    prompt: str = ""


@pytest.fixture
def gender_context(tmp_path: Path) -> _GenderContext:
    return _GenderContext(tmp_path=tmp_path)


@given("Боб запущен и слушает свой топик")
def bob_listening(gender_context: _GenderContext) -> None:
    assert gender_context.prompt == ""


@when(parsers.parse('участница пишет Бобу "{text}"'))
def lily_writes(gender_context: _GenderContext, text: str) -> None:
    gender_context.prompt = asyncio.run(
        run_gender_address_turn(gender_context.tmp_path, text=text)
    )


# The who-is-writing gender clause is «Обращайся к собеседнику в женском/мужском роде.» —
# the fragment «собеседнику в … роде» is UNIQUE to it, so it never collides with the GUPPI
# canon (which fixes GUPPI's own male gender in different words).
_FEM_MARKER = "собеседнику в женском роде"
_MASC_MARKER = "собеседнику в мужском роде"


@then("в промпт ответа попадает указание обращаться в женском роде")
def prompt_has_feminine(gender_context: _GenderContext) -> None:
    assert _FEM_MARKER in gender_context.prompt.casefold(), (
        "промпт ответа не несёт указания про женский род (само-презентация не учтена)"
    )


@then("в промпт ответа не попадает указание про женский род")
def prompt_lacks_feminine(gender_context: _GenderContext) -> None:
    assert _FEM_MARKER not in gender_context.prompt.casefold(), (
        "род форсирован без грамматического сигнала (угадан по имени?)"
    )


@then("в промпт ответа не попадает указание про мужской род")
def prompt_lacks_masculine(gender_context: _GenderContext) -> None:
    assert _MASC_MARKER not in gender_context.prompt.casefold(), (
        "в промпт просочился мужской род (живой баг с Лилей)"
    )
