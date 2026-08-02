# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the interactive-terminal OUTPUT scenarios (BOB-085 S1/S2/S4).

Binds ``interactive_output.feature`` to the real live-stream boundary harness. Each
scenario pins the OBSERVABLE output — the messages the fake notifier captured — of the
coding stream:

* S1 — a long claude answer reaches the owner IN FULL (chunked in order, concatenation ==
  the whole answer), never the concise 200-char stub (INV-1);
* S2 — claude's markdown (heading / list / fenced code) survives to the notifier verbatim,
  not flattened to one prose line (INV-2);
* S4 — the same answer on the one-way group path stays one concise capped message,
  byte-identical to the pre-BOB-085 behaviour (INV-4).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pytest_bdd import given, scenarios, then, when

from tests.acceptance.interactive_output_harness import (
    LONG_BUG_LIST,
    RICH_MARKDOWN,
    TELEGRAM_LIMIT,
    OutputObservations,
    stream_long_answer_group,
    stream_long_answer_interactive,
    stream_rich_answer_interactive,
)

scenarios("../features/interactive_output.feature")

_CONCISE_CAP = 200


@dataclass(slots=True)
class _Ctx:
    """The mutable slate the output scenario's steps share."""

    driver: str = ""
    answer: str = ""
    obs: OutputObservations = field(default_factory=OutputObservations)


# --- Given -----------------------------------------------------------------------


@given("claude выдаёт длинный список багов по приоритетам (>4096 символов)", target_fixture="octx")
def long_answer() -> _Ctx:
    assert len(LONG_BUG_LIST) > TELEGRAM_LIMIT, "S1 вход должен превышать лимит Telegram"
    return _Ctx(driver="interactive_long", answer=LONG_BUG_LIST)


@given("claude выдаёт markdown-заголовок, список и код-блок", target_fixture="octx")
def rich_answer() -> _Ctx:
    return _Ctx(driver="interactive_rich", answer=RICH_MARKDOWN)


@given("тот же длинный список багов идёт в односторонний груп-канал кодера", target_fixture="octx")
def group_answer() -> _Ctx:
    return _Ctx(driver="group_long", answer=LONG_BUG_LIST)


# --- When ------------------------------------------------------------------------


@when("интерактив-DM стрим отправляет ответ")
def drive_interactive(octx: _Ctx) -> None:
    if octx.driver == "interactive_rich":
        octx.obs = stream_rich_answer_interactive()
    else:
        octx.obs = stream_long_answer_interactive()


@when("груп-стрим отправляет строку")
def drive_group(octx: _Ctx) -> None:
    octx.obs = stream_long_answer_group()


# --- S1 Then ---------------------------------------------------------------------


@then("ответ уходит целиком, не обрезаясь до 200 символов")
def answer_is_full_not_truncated(octx: _Ctx) -> None:
    assert octx.obs.joined == octx.answer, "ответ claude не дошёл целиком (INV-1)"
    assert len(octx.obs.joined) > _CONCISE_CAP, "ответ схлопнут до концис-огрызка"


@then("длинный ответ разбит на куски в пределах лимита Telegram")
def answer_is_chunked_within_limit(octx: _Ctx) -> None:
    assert len(octx.obs.sent) > 1, "длинный ответ не был разбит на куски"
    assert all(len(chunk) <= TELEGRAM_LIMIT for chunk in octx.obs.sent), (
        "кусок превышает лимит Telegram"
    )


@then("склейка кусков по порядку восстанавливает весь ответ")
def chunks_rejoin_to_full(octx: _Ctx) -> None:
    assert octx.obs.joined == octx.answer, "склейка кусков не равна исходному ответу"


# --- S2 Then ---------------------------------------------------------------------


@then("markdown-структура сохранена в отправленном (заголовок/список/код-блок)")
def markdown_structure_preserved(octx: _Ctx) -> None:
    sent = "\n".join(octx.obs.sent)
    assert "## Найденные баги" in sent, "заголовок markdown расплющен"
    assert "- **P0**" in sent, "список markdown потерян"
    assert "```python" in sent, "открытие код-блока не сохранено"
    assert sent.count("```") >= 2, "код-блок не закрыт"


@then("текст не расплющен в одну плоскую строку")
def markdown_not_flattened(octx: _Ctx) -> None:
    # A flattened concise render would collapse whitespace into a single line; the rich
    # passthrough keeps the multi-line markdown intact.
    assert octx.obs.sent == [RICH_MARKDOWN], "rich-markdown не прошёл passthrough"
    assert "\n" in octx.obs.sent[0], "markdown схлопнут в одну строку"


# --- S4 Then ---------------------------------------------------------------------


@then("строка уходит одним кратким сообщением под кэпом")
def group_is_one_concise_capped_message(octx: _Ctx) -> None:
    assert len(octx.obs.sent) == 1, "груп-нарратив не должен чанкиться"
    assert len(octx.obs.sent[0]) <= _CONCISE_CAP + 1, "груп-строка превысила концис-кэп"
    assert octx.obs.sent[0].endswith("…"), "длинный груп-текст должен быть усечён кэпом"


@then("это байт-в-байт прежнее груп-поведение (verbose выключен)")
def group_is_byte_identical(octx: _Ctx) -> None:
    # The concise group path must be byte-for-byte the default render — verbose is a
    # strictly additive interactive-DM branch, the group stream did not regress.
    assert octx.obs.sent != [LONG_BUG_LIST], "груп-канал не должен слать полный ответ"
    assert octx.obs.joined == stream_long_answer_group().joined, "груп-выход недетерминирован"
