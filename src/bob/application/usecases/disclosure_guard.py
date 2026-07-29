# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app
# beadloom:layer=application

"""DisclosureGuard — the warm VOICE of a guest owner_data refusal (BOB-066 Срез W.4).

The application bridge for «такт разглашения» at the VOICE layer (Пласт 4): when a GUEST
asks for the owner's private data, the privilege GATE is unchanged — Bob still won't
disclose it — but the dry stranger-wall is swapped for a warm, human
:func:`~bob.personality.voice.tactful_withhold_directive` ("это лучше у него самого
спросить").

Whether a turn IS an ``owner_data`` request is judged by the SAME injected
:class:`~bob.social.permission.privilege.PrivilegeJudge` port the permission flow uses
(reused, not re-implemented). The final gate is the pure
:func:`~bob.personality.voice.disclosure_refusal_directive`. Consulted ONLY on a guest turn,
and the whole judgment is decorative — any failure (or a non-owner_data need) yields ``""``
so a flaky judge never breaks a live turn and never leaks. Built ONLY when ``presence.tact``
is on — unwired (the default) HandleMessage folds no withhold line, byte-identical.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.personality.voice import disclosure_refusal_directive
from bob.social.permission.privilege import PrivilegeContext

if TYPE_CHECKING:
    from collections.abc import Sequence

    from bob.social.permission.privilege import PrivilegeJudge

logger = logging.getLogger(__name__)

# The privilege kind that names a disclosure of the owner's private data (the ONE kind the
# tactful withhold voice answers; tool / internal needs are the permission flow's concern).
_OWNER_DATA_KIND = "owner_data"


class DisclosureGuard:
    """Decide the warm-refusal voice for a guest owner_data request (BOB-066 W.4)."""

    def __init__(
        self, *, judge: PrivilegeJudge, capability_hints: Sequence[str] = ()
    ) -> None:
        self._judge = judge
        self._capability_hints = tuple(capability_hints)

    async def withhold_directive(
        self, *, text: str, is_guest: bool, recent_thread: str = ""
    ) -> str:
        """Return the tactful withhold voice for a guest owner_data turn, else ``""``.

        Only a GUEST turn is ever judged (an owner / known peer returns ``""`` at once —
        their path is untouched). The injected judge assesses whether ``text`` is a
        privileged request and of what kind; the pure
        :func:`~bob.personality.voice.disclosure_refusal_directive` then folds the warm line
        in ONLY for an ``owner_data`` need. 🔴 Decorative safe-default: any judge / parse
        failure is swallowed and yields ``""`` (compose exactly as before — never a leak,
        never an outage). Deterministic given a deterministic judge.
        """
        if not is_guest:
            return ""
        try:
            need = await self._judge.assess(
                PrivilegeContext(
                    request_text=text,
                    capability_hints=self._capability_hints,
                    recent_thread=recent_thread,
                )
            )
        except Exception:
            logger.exception("disclosure privilege judgment failed (ignored)")
            return ""
        needs_owner_data = need.needs_permission and need.kind == _OWNER_DATA_KIND
        return disclosure_refusal_directive(
            is_guest=is_guest, needs_owner_data=needs_owner_data
        )
