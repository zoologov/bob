# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_catch_up_reentry`` — the composition-root switch for the догоняющий.

The catch-up re-entry tick (BOB-066 Срез W.3) ships inert behind ``presence.catchup``. This
builder is the ONE place the flag is read: off → ``None`` (the worker replays every batch,
byte-identical); on → the collaborator over Bob's clock + user-id source.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bob.application.runtime.catch_up_reentry import CatchUpReentry
from bob.runtime.wiring.catchup import build_catch_up_reentry


class _FixedClock:
    def now(self) -> datetime:  # pragma: no cover - not called during wiring
        return datetime(2026, 7, 29, tzinfo=UTC)


def _bob_id() -> int | None:
    return 500


def test_flag_off_yields_no_collaborator() -> None:
    assert (
        build_catch_up_reentry({}, clock=_FixedClock(), bob_user_id_source=_bob_id)
        is None
    )


def test_flag_on_builds_the_collaborator() -> None:
    config = {"presence": {"catchup": {"enabled": True, "budget": 5, "absence_hours": 3.0}}}
    reentry = build_catch_up_reentry(
        config, clock=_FixedClock(), bob_user_id_source=_bob_id
    )
    assert isinstance(reentry, CatchUpReentry)
