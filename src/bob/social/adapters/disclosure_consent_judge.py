# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""LlmDisclosureConsentJudge — Tier-0 реализация consent-раскрытия шва (BOB-082 .4).

Implements the :class:`~bob.social.disclosure_consent.DisclosureConsentJudge` port with
one cheap local Tier-0 call: the pure prompt builder folds the
:class:`~bob.social.disclosure_consent.DisclosureConsentContext` into the request, the
router runs it on the local model (privacy — consent stays local), and the pure parser
maps the reply to a ``bool``.

A thin shell on purpose — all decision shaping is pure domain. The parser is conservative
(bias to NO), so an unparseable reply yields ``False`` rather than raising: a garbled model
never discloses. A model/router ERROR still propagates, so the use-case caller
(:class:`~bob.application.usecases.disclosure_consent_gate.DisclosureConsentGate`) swallows
it as no-consent — best-effort, never an accidental disclosure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.application.router.llm_router import LLMRequest, TaskType
from bob.social.disclosure_consent import (
    DISCLOSURE_CONSENT_SYSTEM_PROMPT,
    build_disclosure_consent_user_prompt,
    parse_disclosure_consent,
)

if TYPE_CHECKING:
    from bob.application.router.llm_router import LLMRouter
    from bob.social.disclosure_consent import DisclosureConsentContext

__all__ = ["LlmDisclosureConsentJudge"]


class LlmDisclosureConsentJudge:
    """Decide whether the owner consents to disclose via one Tier-0 call (bias to NO)."""

    def __init__(self, *, router: LLMRouter) -> None:
        self._router = router

    async def assess(self, ctx: DisclosureConsentContext) -> bool:
        """Run the Tier-0 consent judgment for ``ctx`` and parse it into a bool.

        Builds the request from the pure prompt builder, runs it on the local tier, and
        parses the reply (an unparseable reply is conservatively ``False``). Any
        router/model error propagates for the caller's best-effort fault-tolerance.
        """
        raw = await self._router.run(self._request(ctx))
        return parse_disclosure_consent(raw)

    @staticmethod
    def _request(ctx: DisclosureConsentContext) -> LLMRequest:
        """Build the Tier-0 disclosure-consent request for ``ctx``."""
        return LLMRequest(
            task_type=TaskType.DISCLOSURE_CONSENT,
            messages=[
                {"role": "system", "content": DISCLOSURE_CONSENT_SYSTEM_PROMPT},
                {"role": "user", "content": build_disclosure_consent_user_prompt(ctx)},
            ],
        )
