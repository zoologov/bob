# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the register-recall scenarios (BOB-087 Срез C).

Binds ``register_recall.feature`` to :mod:`tests.acceptance.register_recall_harness`, which
deposits a realistic archive (Bob's own ``work`` dev episodes + ordinary chat) into a REAL
SQLite store, builds the recall pool through the REAL keyword recall + disclosure gate,
resolves the turn's register through the REAL resolver over the REAL Tier-0 classifier (a
fake local model is the only stand-in), applies the REAL register-aware ranking pipeline and
folds the REAL work-provenance voice directive. The scenarios assert Bob's OBSERVABLE
take-away — which memories fill his final recall slots, whether his work surfaces, whether
the honest first-person directive is active — never the resolver's or store's internals.

The scenarios are synchronous (pytest-bdd), so the async read path runs via ``asyncio.run``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.memory.work_journal import WORK_EVENT_TYPE
from tests.acceptance.register_recall_harness import (
    Episode,
    RegisterOutcome,
    run_register_recall,
)

if TYPE_CHECKING:
    from pathlib import Path

scenarios("../features/register_recall.feature")

# The casual turn — a message that lexically brushes Bob's recent work («занимался»/«сегодня»
# match his work episodes too), so his dev memory genuinely competes for a recall slot: the
# exact fear the register muting exists to contain.
_CASUAL_QUESTION = "Боб, чем ты занимался сегодня?"
# The DIRECT dev-work question — hits only the work episodes («разработка»), the owner's
# «прямой вопрос surfaces work» mechanism.
_WORK_QUESTION = "Боб, как продвигается разработка?"

# Bob's own first-person operator memories: each carries «сегодня» + «занимался» + «разработка»
# so both questions can reach them, and «разработка» so the direct question hits them alone.
_WORK_EPISODES = (
    Episode(
        "Сегодня занимался кодом: разработка шла бодро — я попросил GUPPI "
        "поднять лимит буфера в раннере, тесты позеленели.",
        is_work=True,
    ),
    Episode(
        "Сегодня занимался релизом: разработка почти готова — GUPPI починил "
        "краш стримера, я прогнал тесты.",
        is_work=True,
    ),
    Episode(
        "Сегодня занимался ревью — разработка на финише: я свёл правки, "
        "GUPPI прогнал весь набор, всё зелёное.",
        is_work=True,
    ),
)

# Ordinary chat — each carries «сегодня» (so the casual turn recalls it) but NEITHER
# «занимался» NOR «разработка», so it never masquerades as work.
_CHAT_EPISODES = (
    Episode("Сегодня пил кофе с друзьями, славно поболтали.", is_work=False),
    Episode("Сегодня гуляли в парке, было солнечно и тепло.", is_work=False),
    Episode("Сегодня вечером смотрели кино, комедию.", is_work=False),
    Episode("Сегодня приготовил пасту на ужин, вышло вкусно.", is_work=False),
    Episode("Сегодня читал книгу про космос, залип.", is_work=False),
    Episode("Сегодня навёл порядок дома, наконец разобрал полки.", is_work=False),
)


@dataclass(slots=True)
class _RegisterContext:
    """The slate the steps share: isolated store root, the archive, flags, the outcome."""

    tmp_path: Path
    archive: tuple[Episode, ...] = _WORK_EPISODES + _CHAT_EPISODES
    register_recall_enabled: bool = True
    outcome: RegisterOutcome = field(default_factory=RegisterOutcome)


@pytest.fixture
def register_context(tmp_path: Path) -> _RegisterContext:
    """A fresh, isolated SQLite store per scenario."""
    return _RegisterContext(tmp_path=tmp_path)


# --- Given: the archive + the flag ----------------------------------------------


@given("в памяти Боба лежат его work-эпизоды с GUPPI и обычная болтовня")
def archive_has_work_and_chat(register_context: _RegisterContext) -> None:
    register_context.archive = _WORK_EPISODES + _CHAT_EPISODES


@given("в памяти Боба лежит только обычная болтовня, без work-эпизодов")
def archive_has_only_chat(register_context: _RegisterContext) -> None:
    register_context.archive = _CHAT_EPISODES


@given("флаг memory.register_recall включён")
def flag_on(register_context: _RegisterContext) -> None:
    register_context.register_recall_enabled = True


@given("флаг memory.register_recall выключен")
def flag_off(register_context: _RegisterContext) -> None:
    register_context.register_recall_enabled = False


# --- When: the turn arrives on some channel -------------------------------------


@when("владелец casual-ходом спрашивает, чем Боб занимался сегодня")
def owner_asks_casually(register_context: _RegisterContext) -> None:
    register_context.outcome = asyncio.run(
        run_register_recall(
            register_context.tmp_path,
            archive=register_context.archive,
            question=_CASUAL_QUESTION,
            register_recall_enabled=register_context.register_recall_enabled,
            work_talk_verdict="chat",
        )
    )


@when("владелец прямо спрашивает, как продвигается разработка")
def owner_asks_about_dev(register_context: _RegisterContext) -> None:
    register_context.outcome = asyncio.run(
        run_register_recall(
            register_context.tmp_path,
            archive=register_context.archive,
            question=_WORK_QUESTION,
            register_recall_enabled=register_context.register_recall_enabled,
            work_talk_verdict="work",
        )
    )


@when("владелец пишет тот же casual-ход в dev-DM канал")
def owner_writes_in_dev_dm(register_context: _RegisterContext) -> None:
    register_context.outcome = asyncio.run(
        run_register_recall(
            register_context.tmp_path,
            archive=register_context.archive,
            question=_CASUAL_QUESTION,
            register_recall_enabled=register_context.register_recall_enabled,
            work_talk_verdict="chat",
            in_dev_dm=True,
        )
    )


# --- Then: Bob's observable take-away -------------------------------------------


@then("финальные слоты recall НЕ содержат ни одного work-эпизода")
def no_work_in_final_slots(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert not outcome.work_surfaced, (
        f"work всплыл в casual-болтовне: {outcome.final_categories!r}"
    )
    assert WORK_EVENT_TYPE not in outcome.final_categories


@then("всплывает только личная память, не рабочие детали")
def only_personal_memory(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.final, "финальные слоты пусты — личная память не всплыла"
    assert all(cat != WORK_EVENT_TYPE for cat in outcome.final_categories)


@then("work-директива провенанса не вплетается в голос")
def no_work_directive(register_context: _RegisterContext) -> None:
    assert not register_context.outcome.work_directive_active
    assert register_context.outcome.directive == ""


@then("классификатор поднимает ход в регистр DEV")
def classifier_lifts_to_dev(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.register == "dev", f"регистр не DEV: {outcome.register!r}"
    assert outcome.classifier_calls == 1, (
        f"классификатор консультирован {outcome.classifier_calls} раз, ожидался 1"
    )


@then("в финальные слоты recall всплывает work-эпизод Боба")
def work_surfaces_in_final(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.work_surfaced, (
        f"work не всплыл на прямой вопрос: {outcome.final_categories!r}"
    )
    assert WORK_EVENT_TYPE in outcome.final_categories


@then("регистр DEV задан детерминированным сигналом, классификатор не вызывается")
def dev_by_deterministic_signal(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.register == "dev", f"регистр не DEV: {outcome.register!r}"
    assert outcome.classifier_calls == 0, (
        "классификатор сожжён, хотя dev-DM — детерминированный сигнал"
    )


@then("в финальные слоты recall всплывает work-эпизод Боба в полном весе")
def work_surfaces_full_weight(register_context: _RegisterContext) -> None:
    assert register_context.outcome.work_surfaced, "work не всплыл в dev-контексте"


@then("финальные слоты recall идентичны обычному пред-регистровому recall")
def final_identical_to_plain(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.final == outcome.plain_recall, (
        f"OFF-recall не байт-в-байт: {outcome.final!r} != {outcome.plain_recall!r}"
    )
    # And no register was ever resolved — the pipeline was fully inert (INV-5).
    assert outcome.register == ""
    assert outcome.classifier_calls == 0


@then("рабочая память НЕ приглушена — она всплывает как и раньше")
def work_not_muted_when_off(register_context: _RegisterContext) -> None:
    assert register_context.outcome.work_surfaced, (
        "work не всплыл при выключенном флаге — recall не пред-регистровый"
    )


@then("в голос вплетается work-директива от первого лица")
def work_directive_first_person(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.work_directive_active, "work-директива не вплелась, хотя work всплыл"
    directive = outcome.directive.casefold()
    assert "от первого лица" in directive
    assert "«я " in directive  # speaks as «я попросил GUPPI…»


@then("директива велит говорить честно, вести GUPPI как оператор и не выдумывать деталей")
def work_directive_honest_operator(register_context: _RegisterContext) -> None:
    directive = register_context.outcome.directive.casefold()
    assert "честно" in directive
    assert "оператор" in directive
    assert "guppi" in directive
    # The anti-confabulation backstop: never invent details, never blend work with chatter.
    assert "не выдумывай" in directive


@then("Tier-0-классификатор не вызывается ни разу")
def classifier_never_called(register_context: _RegisterContext) -> None:
    assert register_context.outcome.classifier_calls == 0, (
        "Tier-0 сожжён при пуле без work-эпизодов (economy-гейт не сработал)"
    )


@then("финальные слоты recall содержат только болтовню")
def final_only_chat(register_context: _RegisterContext) -> None:
    outcome = register_context.outcome
    assert outcome.final, "финальные слоты пусты"
    assert not outcome.work_surfaced
    assert all(cat != WORK_EVENT_TYPE for cat in outcome.final_categories)
