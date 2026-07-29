# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the такт-разглашения + кредит-доверия scenarios (BOB-066 2.6).

Binds ``disclosure_tact.feature`` to the pure social/personality cores of Пласт 4 —
:func:`~bob.social.disclosure.filter_surfaceable` / :func:`~bob.social.disclosure.may_surface`
(the initiative-surfacing filter, orthogonal to the privilege gate),
:func:`~bob.personality.voice.tactful_withhold_directive` vs
:func:`~bob.personality.voice.stranger_directive` (the warm-refusal VOICE), and
``owner_endorsed_sender`` + ``endorsed_seed`` (the credit of trust). The scenarios
drive the deterministic domain cores directly and assert
the OBSERVABLE contract — living documentation of INV-7 (owner recall byte-identical) and
the conservative, dissolvable warm start.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from bob.personality.mood import Mood
from bob.personality.negotiation import Stance
from bob.personality.voice import stranger_directive, tactful_withhold_directive
from bob.social.disclosure import (
    VISIBILITY_OWNER_PRIVATE,
    VISIBILITY_PUBLIC,
    filter_surfaceable,
)
from bob.social.endorsement import owner_endorsed_sender
from bob.social.interlocutor import Trust
from bob.social.relationship import Relationship, apply_interaction, endorsed_seed

scenarios("../features/disclosure_tact.feature")

_SENDER = 555

_PUBLIC_FACT: dict[str, object] = {"content": "любит джаз", "visibility": VISIBILITY_PUBLIC}
_PRIVATE_FACT: dict[str, object] = {
    "content": "адрес владельца",
    "visibility": VISIBILITY_OWNER_PRIVATE,
}
_LEGACY_FACT: dict[str, object] = {"content": "старый факт"}  # no visibility → NULL = public


class _DisclosureContext:
    """Carries the recall pool / refusal voice / relationship across BDD steps."""

    def __init__(self) -> None:
        self.pool: list[dict[str, object]] = []
        self.surfaced: tuple[object, ...] = ()
        self.refusal = ""
        self.relationship: Relationship | None = None
        self.seeded: Relationship | None = None


@pytest.fixture
def disclosure_context() -> _DisclosureContext:
    return _DisclosureContext()


# --- Такт разглашения ---------------------------------------------------------


@given("в памяти есть owner_private факт и public факт")
def _memory_has_private_and_public(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.pool = [_PRIVATE_FACT, _PUBLIC_FACT]


@given("в памяти есть legacy-факт без метки видимости")
def _memory_has_legacy(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.pool = [_LEGACY_FACT]


@when("Боб инициативно всплывает память для ГОСТЯ")
def _surface_for_guest(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.surfaced = filter_surfaceable(disclosure_context.pool, Trust.GUEST)


@when("Боб инициативно всплывает память для ВЛАДЕЛЬЦА")
def _surface_for_owner(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.surfaced = filter_surfaceable(
        disclosure_context.pool, Trust.TRUSTED
    )


@then("гость видит только public факт")
def _guest_sees_only_public(disclosure_context: _DisclosureContext) -> None:
    assert disclosure_context.surfaced == (_PUBLIC_FACT,)


@then("приватный факт владельца остаётся при Бобе")
def _private_withheld(disclosure_context: _DisclosureContext) -> None:
    assert _PRIVATE_FACT not in disclosure_context.surfaced


@then("public факт всплывает гостю")
def _public_surfaces(disclosure_context: _DisclosureContext) -> None:
    assert _PUBLIC_FACT in disclosure_context.surfaced


@then("владельцу всплывают оба факта без потерь")
def _owner_sees_all(disclosure_context: _DisclosureContext) -> None:
    # INV-7: byte-identical — every item, in order.
    assert disclosure_context.surfaced == (_PRIVATE_FACT, _PUBLIC_FACT)


@then("legacy-факт всплывает гостю")
def _legacy_surfaces(disclosure_context: _DisclosureContext) -> None:
    assert _LEGACY_FACT in disclosure_context.surfaced


# --- Тёплый отказ -------------------------------------------------------------


@given("гость просит личные данные владельца")
def _guest_asks_owner_data(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.refusal = ""


@when("Боб формулирует отказ тактично")
def _compose_tactful_refusal(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.refusal = tactful_withhold_directive()


@then("отказ тёплый и указывает спросить у самого владельца")
def _refusal_points_to_owner(disclosure_context: _DisclosureContext) -> None:
    folded = disclosure_context.refusal.casefold()
    assert "владел" in folded
    assert "груб" in folded  # explicitly not rude — warm, not cold


@then("это не сухая стена незнакомцу")
def _not_the_dry_wall(disclosure_context: _DisclosureContext) -> None:
    # The tactful line is a DIFFERENT, warmer voice than the dry stranger-wall.
    assert disclosure_context.refusal != stranger_directive()


# --- Кредит доверия -----------------------------------------------------------


@given("владелец поручился за нового гостя по имени")
def _owner_vouched(disclosure_context: _DisclosureContext) -> None:
    owner_texts = ["познакомься, это Норман, ему можно доверять"]
    assert owner_endorsed_sender(owner_texts, sender_name="Норман") is True
    disclosure_context.relationship = None  # first contact


@when("Боб впервые встречает этого гостя")
def _first_meeting(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.seeded = endorsed_seed(disclosure_context.relationship, _SENDER)


@given("Боб встретил его с тёплым стартом")
def _warm_start_given(disclosure_context: _DisclosureContext) -> None:
    disclosure_context.seeded = endorsed_seed(None, _SENDER)


@then("отношение стартует теплее нейтрали")
def _starts_warm(disclosure_context: _DisclosureContext) -> None:
    assert disclosure_context.seeded is not None
    assert disclosure_context.seeded.warmth > 0.0
    assert disclosure_context.seeded.trust > 0.0


@when("поведение гостя не подтверждает кредит")
def _behaviour_does_not_confirm(disclosure_context: _DisclosureContext) -> None:
    assert disclosure_context.seeded is not None
    disclosure_context.relationship = apply_interaction(
        disclosure_context.seeded,
        stance=Stance.PROPOSE_ALTERNATIVE,
        mood=Mood(),
        sentiment=0.0,
    )


@then("тёплый старт остывает к нейтрали")
def _cools_toward_neutral(disclosure_context: _DisclosureContext) -> None:
    assert disclosure_context.relationship is not None
    assert disclosure_context.seeded is not None
    assert disclosure_context.relationship.warmth < disclosure_context.seeded.warmth
    assert disclosure_context.relationship.warmth >= 0.0
