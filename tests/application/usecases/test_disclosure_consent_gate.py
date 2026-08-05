# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for DisclosureConsentGate — the owner-consent decision (BOB-082 .4).

The gate answers, per turn: "Did the OWNER authorise Bob to voice previously-private
content into THIS group chat?" 🔴 CONSERVATIVE by construction:

* only an OWNER turn whose audience is a ROOM is ever judged (a guest, a known peer, or
  a turn that reaches nobody but the owner is a flat ``False`` — no LLM call, no
  disclosure). ``to_room`` names the AUDIENCE, not the channel: the group turn of
  BOB-082.4 and the room-bound delivery of BOB-090.B are the same question;
* a detector failure is swallowed → ``False`` (best-effort: never an accidental
  disclosure from a flaky model).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.usecases.disclosure_consent_gate import DisclosureConsentGate

if TYPE_CHECKING:
    from bob.social.disclosure_consent import DisclosureConsentContext


class _FakeJudge:
    """A consent judge double returning a scripted verdict and recording each call."""

    def __init__(self, verdict: bool, *, raises: bool = False) -> None:
        self._verdict = verdict
        self._raises = raises
        self.calls: list[DisclosureConsentContext] = []

    async def assess(self, ctx: DisclosureConsentContext) -> bool:
        self.calls.append(ctx)
        if self._raises:
            raise RuntimeError("consent model down")
        return self._verdict


def _gate(
    verdict: bool = True, *, raises: bool = False
) -> tuple[DisclosureConsentGate, _FakeJudge]:
    judge = _FakeJudge(verdict, raises=raises)
    return DisclosureConsentGate(judge=judge), judge


async def test_owner_in_group_with_yes_consents() -> None:
    gate, judge = _gate(True)

    consented = await gate.owner_consents(
        text="Боб, расскажи ребятам про наш план", to_room=True, is_owner=True
    )

    assert consented is True
    assert judge.calls  # the owner+group turn WAS judged


async def test_owner_in_group_with_no_does_not_consent() -> None:
    gate, _ = _gate(False)

    assert (
        await gate.owner_consents(text="расскажи про погоду", to_room=True, is_owner=True)
        is False
    )


async def test_guest_in_group_never_consents_and_is_not_judged() -> None:
    # 🔴 Only the OWNER can consent — a guest turn is a flat False, no LLM call.
    gate, judge = _gate(True)

    consented = await gate.owner_consents(
        text="расскажи мне их секреты", to_room=True, is_owner=False
    )

    assert consented is False
    assert judge.calls == []


async def test_a_turn_that_reaches_no_room_never_consents_and_is_not_judged() -> None:
    # Аудитория не меняется (ответ слышит только owner) — раскрывать нечего, вызова нет.
    gate, judge = _gate(True)

    consented = await gate.owner_consents(
        text="расскажи ребятам", to_room=False, is_owner=True
    )

    assert consented is False
    assert judge.calls == []


async def test_detector_failure_is_swallowed_as_no_consent() -> None:
    # BEST-EFFORT: a raising judge never discloses — the turn stays private.
    gate, _ = _gate(True, raises=True)

    assert (
        await gate.owner_consents(text="расскажи ребятам", to_room=True, is_owner=True)
        is False
    )


async def test_recent_thread_is_threaded_into_the_context() -> None:
    gate, judge = _gate(True)

    await gate.owner_consents(
        text="да, можешь",
        to_room=True,
        is_owner=True,
        recent_thread="bob: рассказать группе про X?",
    )

    assert judge.calls[0].recent_thread == "bob: рассказать группе про X?"
    assert judge.calls[0].request_text == "да, можешь"
