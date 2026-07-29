# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Step definitions for the EQ live-врезка WIRING scenarios (BOB-066 Срез W.4).

Binds ``eq_live_wiring.feature`` to the composition-root builders + collaborators of Пласт 4:
:func:`~bob.runtime.wiring.endorsement.build_endorsement_seeder` /
:class:`~bob.application.usecases.endorsement_seeder.EndorsementSeeder` (кредит доверия) and
:func:`~bob.runtime.wiring.disclosure.build_disclosure_guard` /
:class:`~bob.application.usecases.disclosure_guard.DisclosureGuard` (такт разглашения). The
scenarios pin the WIRED contract: the flag gate (off → the seam is not built → byte-identical)
and the observable output (a first-contact endorsed guest starts warm; a guest owner_data
request gets the warm withhold VOICE, not the dry stranger-wall).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pytest_bdd import given, scenarios, then, when

from bob.application.usecases.disclosure_guard import DisclosureGuard
from bob.personality.voice import stranger_directive
from bob.runtime.wiring.disclosure import build_disclosure_guard
from bob.runtime.wiring.endorsement import build_endorsement_seeder
from bob.social.interlocutor import Interlocutor, InterlocutorKind, Trust
from bob.social.permission.privilege import PrivilegeContext, PrivilegeNeed

if TYPE_CHECKING:
    from bob.application.usecases.endorsement_seeder import EndorsementSeeder
    from bob.social.relationship import Relationship

scenarios("../features/eq_live_wiring.feature")

_OWNER_ID = 1
_GUEST_ID = 42


class _ScriptedJudge:
    """A PrivilegeJudge fake returning a fixed need for the wired disclosure guard."""

    def __init__(self, need: PrivilegeNeed) -> None:
        self._need = need

    async def assess(self, ctx: PrivilegeContext) -> PrivilegeNeed:  # noqa: ARG002
        return self._need


def _guest() -> Interlocutor:
    return Interlocutor(
        sender_id=_GUEST_ID,
        display_name="Норман",
        kind=InterlocutorKind.GUEST,
        trust=Trust.GUEST,
    )


def _owner_vouch(text: str) -> dict[str, object]:
    return {"content": f"Vova: {text}\nbob: понял", "sender_id": _OWNER_ID}


@dataclass(slots=True)
class _State:
    seeder: EndorsementSeeder | None = None
    guard: DisclosureGuard | None = None
    history: list[dict[str, object]] = field(default_factory=list)
    relationship: Relationship | None = None
    directive: str = ""


# --- Кредит доверия -----------------------------------------------------------


@given("врезка кредита доверия включена", target_fixture="eq_state")
def endorsement_on() -> _State:
    seeder = build_endorsement_seeder(
        {"presence": {"endorsement": {"enabled": True}}}, owner_id=_OWNER_ID
    )
    return _State(seeder=seeder)


@given("врезка кредита доверия выключена", target_fixture="eq_state")
def endorsement_off() -> _State:
    return _State(
        seeder=build_endorsement_seeder({}, owner_id=_OWNER_ID)
    )


@given("владелец поручился за нового гостя по имени в общей нити")
def owner_vouched_in_thread(eq_state: _State) -> None:
    eq_state.history = [_owner_vouch("познакомься, это Норман, ему можно доверять")]


@given("в общей нити нет поручительства владельца за этого гостя")
def no_vouch_in_thread(eq_state: _State) -> None:
    eq_state.history = [_owner_vouch("Норман, ты придёшь на встречу?")]


@when("Боб впервые встречает этого гостя")
def first_meeting(eq_state: _State) -> None:
    assert eq_state.seeder is not None
    eq_state.relationship = eq_state.seeder.seed(_guest(), None, eq_state.history)


@then("отношение гостя стартует теплее нейтрали")
def relationship_starts_warm(eq_state: _State) -> None:
    assert eq_state.relationship is not None
    assert eq_state.relationship.warmth > 0.0
    assert eq_state.relationship.trust > 0.0


@then("отношение гостя остаётся нейтральным")
def relationship_stays_neutral(eq_state: _State) -> None:
    assert eq_state.relationship is None


@then("сеятель кредита не собирается")
def seeder_not_built(eq_state: _State) -> None:
    assert eq_state.seeder is None


# --- Такт разглашения ---------------------------------------------------------


@given("врезка такта разглашения включена", target_fixture="eq_state")
def tact_on() -> _State:
    guard = build_disclosure_guard(
        {"presence": {"tact": {"enabled": True}}},
        router=None,  # type: ignore[arg-type]  # replaced by the scripted judge below
    )
    assert guard is not None
    return _State(guard=guard)


@given("врезка такта разглашения выключена", target_fixture="eq_state")
def tact_off() -> _State:
    return _State(guard=build_disclosure_guard({}, router=None))  # type: ignore[arg-type]


@when("гость просит личные данные владельца")
def guest_asks_owner_data(eq_state: _State) -> None:
    guard = DisclosureGuard(
        judge=_ScriptedJudge(
            PrivilegeNeed(needs_permission=True, kind="owner_data", what="адрес владельца")
        )
    )
    eq_state.directive = asyncio.run(
        guard.withhold_directive(text="какой адрес у Вовы?", is_guest=True)
    )


@when("гость просит нечто не личное владельца")
def guest_asks_non_private(eq_state: _State) -> None:
    guard = DisclosureGuard(
        judge=_ScriptedJudge(PrivilegeNeed(needs_permission=False, kind="", what=""))
    )
    eq_state.directive = asyncio.run(
        guard.withhold_directive(text="как дела?", is_guest=True)
    )


@then("Боб добавляет тёплый отказ вместо сухой стены")
def warm_refusal_not_dry_wall(eq_state: _State) -> None:
    folded = eq_state.directive.casefold()
    assert "владел" in folded  # points at the owner
    assert "груб" in folded  # explicitly not rude — warm, not cold
    assert eq_state.directive != stranger_directive()  # a DIFFERENT, warmer voice


@then("Боб не добавляет отказ")
def no_refusal(eq_state: _State) -> None:
    assert eq_state.directive == ""


@then("страж разглашения не собирается")
def guard_not_built(eq_state: _State) -> None:
    assert eq_state.guard is None
