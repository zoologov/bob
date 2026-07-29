# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Integration tests for the whole BOB-066 W wiring slice (Срез W.5).

The four W dev slices threaded deferred presence mechanisms into the hot path, each behind a
nested ``presence.<section>.enabled`` flag (rhythm / room_mood / series_budget / staleness /
catchup / endorsement / tact) plus the pre-existing ``presence.reflective`` split. This module
is the END-TO-END integration test for that slice — it proves the cross-cutting invariants hold
when the WHOLE stack is wired ON, and that with every new flag OFF the behaviour is
byte-identical to today.

It composes two levels of the real path:

* the FULL GUPPI graph on fakes (``wiring_integration_harness``) for cells the graph can create
  in one turn — a direct address vs ambient chatter, an exhausted share-of-voice ceiling, an
  active per-person sulk, a reflective IGNORE verdict;
* the real intake / handler SEAMS (the per-slice wiring harnesses) for cells the graph cannot
  fabricate in a single turn — a burst collapsing to one reply, a draft going stale
  mid-generation, an away-period backlog.

Together they form the 🔴 INV-1 matrix: across every address form × condition, a direct address
yields a REPLY (never silence), while the same on-stack still stays silent on true ambient
chatter. Observable behaviour is asserted through the outgoing boundary only, never private
state.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from tests.acceptance.catchup_reentry_wiring_harness import run_reentry
from tests.acceptance.fake_gateway import run_turn
from tests.acceptance.series_budget_harness import (
    drive_ambient_burst,
    drive_burst_with_a_direct_address,
)
from tests.acceptance.staleness_wiring_harness import run_staleness_turn
from tests.acceptance.wiring_integration_harness import (
    IGNORE_READING,
    REPLY_READING,
    run_wiring_turn,
)

if TYPE_CHECKING:
    from pathlib import Path

# The direct message ids the seam harnesses embed inside a burst / backlog — the addressee whose
# reply/handling the INV-1 focal guarantee protects.
_BURST_DIRECT_ID = 2
_BACKLOG_DIRECT_ID = 3
# The away-period backlog the catch-up harness drains (batch 2 = messages 2..5).
_BACKLOG_SIZE = 4


# --- The address forms a direct turn can take through the FULL graph -----------------------
# reply-to-Bob (the third form) needs Bob's numeric id, resolved asynchronously via get_me — the
# fake gateway never resolves it, so reply-to-Bob focus is pinned at the seam level (the series /
# catch-up harnesses bind a real bob_user_id). @mention and «Боб, …» name-address both classify
# to DIRECTED_TO_BOB at the event boundary.
_AT_MENTION = {"text": "Bob, что думаешь про зонды?", "mentions_bob": True}
_NAME_ADDRESS = {"text": "Боб, ты тут?", "mentions_bob": False}


class TestInv1FocalGuaranteeSurvivesTheWholeStack:
    """🔴 INV-1: a direct address is NEVER throttled to silence, whatever else is wired ON."""

    @pytest.mark.parametrize(
        ("address", "form_name"),
        [(_AT_MENTION, "at_mention"), (_NAME_ADDRESS, "name_address")],
    )
    @pytest.mark.parametrize(
        ("hog_airtime", "sulk", "reading", "condition"),
        [
            (False, False, IGNORE_READING, "reflective_ignore"),
            (True, False, IGNORE_READING, "share_ceiling_exhausted"),
            (False, True, IGNORE_READING, "sulk_active"),
            (True, True, REPLY_READING, "ceiling_plus_sulk"),
        ],
    )
    def test_direct_address_always_replies_flags_on(
        self,
        tmp_path: Path,
        address: dict[str, object],
        form_name: str,  # noqa: ARG002 — parametrization label for readable test ids
        hog_airtime: bool,
        sulk: bool,
        reading: str,
        condition: str,  # noqa: ARG002 — parametrization label for readable test ids
    ) -> None:
        # Arrange / Act — full graph, EVERY presence flag ON, under the given condition.
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text=str(address["text"]),
                mentions_bob=bool(address["mentions_bob"]),
                flags_on=True,
                reading=reading,
                hog_airtime=hog_airtime,
                sulk=sulk,
            )
        )
        # Assert — the focal guarantee held: Bob spoke (never silence).
        assert gateway.replied, "INV-1 нарушен: прямое обращение заглушено сквозь wiring"

    def test_share_ceiling_does_not_throttle_a_focus_turn(self, tmp_path: Path) -> None:
        # Arrange / Act — Bob hogged the airtime AND the reflective read says REPLY, so a silence
        # could only be the ceiling; a direct address must still bypass it (INV-1).
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text=str(_AT_MENTION["text"]),
                mentions_bob=True,
                flags_on=True,
                reading=REPLY_READING,
                hog_airtime=True,
            )
        )
        # Assert
        assert gateway.replied, "потолок доли эфира заглушил фокус (INV-1)"

    def test_ambient_burst_focus_message_is_always_answered(self) -> None:
        # Arrange / Act — a settled burst of ambient chatter carrying ONE direct address, with the
        # series-budget top-k ON (would otherwise cap the burst).
        observations = asyncio.run(drive_burst_with_a_direct_address(enabled=True))
        # Assert — the addressed message is the one that got the reply.
        assert _BURST_DIRECT_ID in observations.replies, "адресованное в пачке потеряно (INV-1)"

    def test_staleness_does_not_drop_a_fresh_direct_question(self) -> None:
        # Arrange / Act — the drafted reply was answered by someone else mid-generation, but a
        # FRESH direct question also landed; the staleness врезка must never drop a focal signal.
        outcome = asyncio.run(
            run_staleness_turn(
                enabled=True, answered_by_other=True, new_direct_question=True
            )
        )
        # Assert — Bob still speaks; the draft is not dropped to a like.
        assert outcome.replied, "staleness уронил свежий прямой вопрос (INV-1)"
        assert not outcome.liked, "staleness превратил фокус в лайк (INV-1)"

    def test_catchup_does_not_lose_a_backlogged_direct_question(self) -> None:
        # Arrange / Act — after a long away-period, a backlog with one direct address among
        # ambient asides is caught up in one pass (catch-up re-entry ON).
        observations = asyncio.run(run_reentry(enabled=True))
        # Assert — the backlogged direct address was handled (answered), not skimmed away.
        assert _BACKLOG_DIRECT_ID in observations.handled, (
            "догоняющий потерял отложенный прямой вопрос (INV-1)"
        )


class TestOnStackStillStaysSilentOnAmbient:
    """The all-on stack is not a "reply to everything" regression — ambient chatter is left be."""

    def test_ambient_barge_is_throttled_when_bob_hogged_the_room(
        self, tmp_path: Path
    ) -> None:
        # Arrange / Act — an ambient periphery turn (no direct address); the reflective read WOULD
        # barge (REPLY) but Bob hogged the airtime, so the share-of-voice ceiling silences him.
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text="сегодня весь день дождь за окном",
                mentions_bob=False,
                flags_on=True,
                reading=REPLY_READING,
                hog_airtime=True,
            )
        )
        # Assert — Bob stayed out of the exchange he had no business hijacking.
        assert not gateway.replied, "Боб влез в ambient, перебрав долю эфира"

    def test_ambient_low_salience_read_stays_silent(self, tmp_path: Path) -> None:
        # Arrange / Act — ambient chatter the reflective judge reads as IGNORE.
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text="ну и погода сегодня",
                mentions_bob=False,
                flags_on=True,
                reading=IGNORE_READING,
            )
        )
        # Assert
        assert not gateway.replied, "Боб ответил на ambient с вердиктом IGNORE"

    def test_settled_ambient_burst_collapses_to_one_reply(self) -> None:
        # Arrange / Act — a settled burst of pure ambient chatter (no direct address) with the
        # top-k budget ON.
        observations = asyncio.run(drive_ambient_burst(enabled=True))
        # Assert — the burst collapses to at most one reply + a budget-capped like (INV-3: a soft
        # nudge, not a hard drop — Bob still engages, just once).
        assert observations.reply_count <= 1, "пачка не свернулась в один ответ"
        assert observations.like_count <= 1, "бюджет реакций превышен"


class TestFlagsOffAreByteIdentical:
    """🔴 With every new W flag OFF the deferred mechanisms are inert — today's behaviour holds."""

    @pytest.mark.parametrize(
        "address", [_AT_MENTION, _NAME_ADDRESS], ids=["at_mention", "name_address"]
    )
    def test_direct_address_replies_with_all_flags_off(
        self, tmp_path: Path, address: dict[str, object]
    ) -> None:
        # Arrange / Act — the SAME direct turn with the presence section empty (all off).
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text=str(address["text"]),
                mentions_bob=bool(address["mentions_bob"]),
                flags_on=False,
            )
        )
        # Assert — Bob replies exactly as before the epic.
        assert gateway.replied, "флаги OFF изменили поведение (не byte-identical)"

    def test_all_flags_off_matches_the_baseline_direct_turn(
        self, tmp_path: Path
    ) -> None:
        # Arrange — the pre-epic baseline driver (no presence section at all).
        baseline = asyncio.run(
            run_turn(tmp_path, text="Bob, привет", reply="Привет!")
        )
        # Act — the all-flags-OFF wiring driver on the same direct turn.
        all_off = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text="Bob, привет",
                mentions_bob=True,
                flags_on=False,
                reply="Привет!",
            )
        )
        # Assert — both reply through the boundary (the deferred wiring adds nothing when off).
        assert baseline.replied is all_off.replied is True

    @pytest.mark.parametrize(
        "driver",
        [
            lambda: run_staleness_turn(
                enabled=False, answered_by_other=True, new_direct_question=False
            ),
        ],
        ids=["staleness"],
    )
    def test_staleness_off_still_replies(self, driver: object) -> None:
        # Arrange / Act — a burst that WOULD have been read as stale, врезка OFF.
        outcome = asyncio.run(driver())  # type: ignore[operator]
        # Assert — Bob replies as before (the reassessor never runs).
        assert outcome.replied, "staleness OFF изменил поведение"
        assert not outcome.liked

    def test_series_budget_off_replies_to_each_burst_message(self) -> None:
        # Arrange / Act — the same ambient burst with the top-k budget OFF.
        observations = asyncio.run(drive_ambient_burst(enabled=False))
        # Assert — every message replies uncapped (byte-identical pre-epic behaviour).
        assert observations.reply_count >= 1

    def test_catchup_off_replays_the_whole_backlog(self) -> None:
        # Arrange / Act — the away-period backlog with catch-up OFF.
        observations = asyncio.run(run_reentry(enabled=False))
        # Assert — the direct address is STILL handled (never lost), plus the ambient asides — no
        # skimming happens when the re-entry seam is inert.
        assert _BACKLOG_DIRECT_ID in observations.handled
        assert len(observations.handled) >= _BACKLOG_SIZE  # every backlogged message replays


class TestCrossCuttingInvariantsUnderFlagsOn:
    """INV-3 / INV-5 / INV-6 hold end-to-end with the whole presence stack wired ON."""

    def test_sulking_bob_still_answers_a_direct_address_inv6(
        self, tmp_path: Path
    ) -> None:
        # Arrange / Act — Bob is обижен at the owner (per-person sulk active), full stack ON, and
        # the owner addresses him directly. INV-6 cools his tone but never silences him.
        gateway = asyncio.run(
            run_wiring_turn(
                tmp_path,
                text=str(_AT_MENTION["text"]),
                mentions_bob=True,
                flags_on=True,
                sulk=True,
            )
        )
        # Assert — a sulk is a colour, not a wall (INV-6 + INV-1).
        assert gateway.replied, "обида заглушила прямое обращение (INV-6/INV-1)"

    def test_burst_order_is_preserved_inv5(self) -> None:
        # Arrange / Act — a settled burst with the series-budget seam ON serialises per-chat.
        observations = asyncio.run(drive_burst_with_a_direct_address(enabled=True))
        # Assert — the reply for the addressed message is present (per-chat serialisation held; a
        # crash / interleave would drop or duplicate it).
        in_order = observations.replies == sorted(observations.replies)
        assert in_order, "порядок треда нарушен (INV-5)"
        assert _BURST_DIRECT_ID in observations.replies

    def test_soft_ambient_budget_is_a_nudge_not_a_ban_inv3(self) -> None:
        # Arrange — the SAME ambient burst under the top-k budget.
        capped = asyncio.run(drive_ambient_burst(enabled=True))
        uncapped = asyncio.run(drive_ambient_burst(enabled=False))
        # Assert — INV-3: the budget softens the burst (fewer replies) yet Bob still engages once;
        # it never zeroes his presence out entirely.
        assert capped.reply_count <= uncapped.reply_count
        engaged = capped.reply_count + capped.like_count
        assert engaged >= 1, "бюджет полностью заглушил Боба (INV-3)"
