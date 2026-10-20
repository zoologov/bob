# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root endorsement wiring — «кредит доверия» behind ``presence.endorsement``.

The endorsement-seed consumption seam (BOB-066 Срез W.4): this is the ONE place the
``presence.endorsement`` flag is read and the
:class:`~bob.application.usecases.endorsement_seeder.EndorsementSeeder` is assembled over the
configured ``owner_id`` (the identity whose OWN thread turns can extend the credit of trust).
Off (the default — the whole «человеческое групповое присутствие» epic ships as one piece)
the seeder is ``None`` so ``HandleMessage`` keeps the neutral first-contact path and Bob is
byte-identical.

The flag follows the nested ``<section>.enabled`` convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.usecases.endorsement_seeder import EndorsementSeeder
from bob.runtime.config import _flag, _section

if TYPE_CHECKING:
    from collections.abc import Mapping


def build_endorsement_seeder(
    config: Mapping[str, object], *, owner_id: int | None
) -> EndorsementSeeder | None:
    """Assemble the endorsement seeder, or ``None`` when ``presence.endorsement`` is off.

    Off (the default) → ``None`` so ``HandleMessage`` meets a first-contact guest at the
    neutral base (byte-identical). On → the :class:`EndorsementSeeder` over ``owner_id``, so
    a guest the owner vouched for by name in the shared thread starts warm (a credit the
    ordinary drift-to-neutral dissolves if the guest's own behaviour doesn't confirm it).
    """
    if not _flag(_section(_section(config, "presence"), "endorsement"), "enabled"):
        return None
    return EndorsementSeeder(owner_id=owner_id)
