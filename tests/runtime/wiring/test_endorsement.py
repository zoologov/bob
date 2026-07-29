# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for ``build_endorsement_seeder`` — the composition-root switch for кредит доверия.

The endorsement-seed врезка (BOB-066 Срез W.4) ships inert behind ``presence.endorsement``.
This builder is the ONE place the flag is read: off → ``None`` (Bob meets a first-contact
guest at the neutral base, byte-identical); on → the seeder over the configured ``owner_id``.
"""

from __future__ import annotations

from bob.application.usecases.endorsement_seeder import EndorsementSeeder
from bob.runtime.wiring.endorsement import build_endorsement_seeder


def test_flag_off_yields_no_seeder() -> None:
    assert build_endorsement_seeder({}, owner_id=1) is None


def test_flag_on_builds_the_seeder() -> None:
    config = {"presence": {"endorsement": {"enabled": True}}}
    assert isinstance(
        build_endorsement_seeder(config, owner_id=1), EndorsementSeeder
    )
