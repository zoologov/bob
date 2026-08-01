# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime-app
# beadloom:layer=application

"""DisclosureConsentGate — the owner-consent decision for a group turn (BOB-082 .4).

The application bridge for «раскрытие по согласию owner'а»: приватность по умолчанию —
не тюрьма. When the OWNER, speaking in a GROUP, explicitly authorises Bob to voice
previously-private content into the room, this gate says so — and the recall filter lets
that one turn's ``owner_private`` memory surface (a per-turn override, never a stored
reclassification).

🔴 CONSERVATIVE by construction:

* only an OWNER turn in a GROUP is ever judged — a guest, a known peer, or ANY DM turn is
  a flat ``False`` with NO LLM call (in a DM everything is already the owner's; a non-owner
  can never authorise disclosure of the owner's private world);
* the semantic verdict comes from the injected Tier-0
  :class:`~bob.social.disclosure_consent.DisclosureConsentJudge` (not keyword matching);
* a detector failure is swallowed → ``False`` (best-effort: a flaky model never discloses).

A missed consent is safe (the owner simply repeats the ask); a false disclosure is the
failure to avoid — so every uncertainty resolves to «не раскрывать».
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bob.social.disclosure_consent import DisclosureConsentContext

if TYPE_CHECKING:
    from bob.social.disclosure_consent import DisclosureConsentJudge

logger = logging.getLogger(__name__)

__all__ = ["DisclosureConsentGate"]


class DisclosureConsentGate:
    """Decide whether the owner consents to disclose private memory this group turn."""

    def __init__(self, *, judge: DisclosureConsentJudge) -> None:
        self._judge = judge

    async def owner_consents(
        self, *, text: str, is_group: bool, is_owner: bool, recent_thread: str = ""
    ) -> bool:
        """Whether the owner authorised disclosing private content into the room this turn.

        Returns ``False`` at once — with no LLM call — unless the turn is the OWNER speaking
        in a GROUP (only then is disclosure to an audience even a question). For such a turn
        the injected judge assesses ``text`` semantically. 🔴 Best-effort safe default: any
        judge / parse failure is swallowed and yields ``False`` (never an accidental
        disclosure, never a broken turn). Deterministic given a deterministic judge.
        """
        if not (is_group and is_owner):
            return False
        try:
            return await self._judge.assess(
                DisclosureConsentContext(request_text=text, recent_thread=recent_thread)
            )
        except Exception:
            logger.exception("disclosure-consent judgment failed (ignored → no consent)")
            return False
