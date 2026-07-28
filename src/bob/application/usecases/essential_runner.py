# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""EssentialRunner — «полный Боб или честный GUPPI-нотис» (BOB-049 .3).

The turn's reliability primitive in one cohesive collaborator (extracted from
``HandleMessage`` in BOB-062.6b, wave 1, behavior-preserving). An ESSENTIAL LLM step —
the semantic judgment, the reply generation — whose persistent failure must NOT yield a
degraded reply is run through :meth:`run`, which retries it a bounded number of times
with a short injected backoff and, on exhaustion, raises :class:`_EssentialStepError` so
the turn falls back to the honest GUPPI outage notice. :meth:`handle_failure` ends such a
turn: it persists the user's turn (so the message is not lost) via the injected persist
callback and posts GUPPI's honest outage notice. 🔴 OPTIONAL add-ons (verify / grounded /
diagram / closer) are NEVER routed through here — they drop silently at their own call
sites, so a flaky decorative step can never trip the outage notice.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.application.reliability import call_with_retry

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from bob.application.reliability import Sleep
    from bob.application.runtime.events import MessageReceived
    from bob.personality.soul import SOUL

logger = logging.getLogger(__name__)

# Bob's persisted half when an ESSENTIAL step failed after retries (BOB-049 .3): the
# user's turn is saved (so the message is not lost) with this marker — no degraded reply
# was produced; GUPPI reported the outage separately. Russian persona voice.
_OUTAGE_MARKER = "(нет ответа: проблемы со связью)"  # noqa: RUF001


class OutageNotifier(Protocol):
    """GUPPI's honest-outage seam (BOB-049 .3 — «полный Боб или GUPPI-нотис»).

    When an ESSENTIAL turn step (the semantic judgment or the reply generation) keeps
    failing after the bounded retries, Bob — the mind — is unavailable. Rather than ship a
    degraded half-answer («уверенный бред», the antipattern), GUPPI (the infrastructure
    subsystem) honestly reports the outage into Bob's topic via this seam. Optional: with
    no notifier wired the turn still ends cleanly — the user's turn is persisted and NO
    degraded reply is produced — just without a visible notice. The concrete adapter sends
    a fixed system line through Bob's bot into his topic; the third-person text reads as
    GUPPI reporting, not Bob being rude.
    """

    async def notify_outage(self) -> None:
        """Post GUPPI's honest "Bob temporarily unavailable" connectivity notice."""
        ...


class _EssentialStepError(Exception):
    """An ESSENTIAL turn step failed after the bounded retries (BOB-049 .3).

    Raised by the retry-wrapped essential calls (the semantic judgment, the reply
    generation) so the turn falls back to the honest GUPPI outage notice instead of a
    degraded reply. Carries the step label for the log only — never shown to the user.
    """

    def __init__(self, step: str) -> None:
        super().__init__(step)
        self.step = step


# The persist half of an outage turn: save the user's turn under a marker (behaviour
# mirrors HandleMessage's own persist; injected so the runner stays a pure reliability
# primitive with no persistence knowledge of its own).
type _PersistTurn = Callable[[MessageReceived, str, SOUL], Awaitable[None]]


class EssentialRunner:
    """Retry an ESSENTIAL LLM step, then fall back to the honest GUPPI notice (BOB-049 .3)."""

    def __init__(
        self,
        *,
        attempts: int,
        backoff_seconds: float,
        retry_sleep: Sleep,
        outage_notifier: OutageNotifier | None,
        persist: _PersistTurn,
    ) -> None:
        self._attempts = attempts
        self._backoff_seconds = backoff_seconds
        self._retry_sleep = retry_sleep
        self._outage_notifier = outage_notifier
        self._persist = persist

    async def run[T](
        self, operation: Callable[[], Awaitable[T]], *, step: str
    ) -> T:
        """Run an ESSENTIAL LLM step with bounded retry (BOB-049 .3).

        The semantic judgment and the reply generation are the steps whose persistent
        failure must NOT yield a degraded reply. Each is retried up to ``attempts``
        times with the injected backoff sleep; if every attempt raises, the last error
        is wrapped in :class:`_EssentialStepError` so the turn falls back to the honest
        GUPPI outage notice. OPTIONAL add-ons are never routed through here — they drop
        silently at their own call sites.
        """
        try:
            return await call_with_retry(
                operation,
                attempts=self._attempts,
                backoff_seconds=self._backoff_seconds,
                sleep=self._retry_sleep,
            )
        except Exception as exc:
            raise _EssentialStepError(step) from exc

    async def notify_outage(self) -> None:
        """Emit GUPPI's honest outage notice into Bob's topic, best-effort (BOB-049 .3).

        Unwired notifier → a clean no-op (the turn already ended with no degraded reply).
        A flaky send is logged and swallowed so the failure handling itself can never
        raise on top of the original essential failure.
        """
        if self._outage_notifier is None:
            return
        try:
            await self._outage_notifier.notify_outage()
        except Exception:
            logger.exception("sending the GUPPI outage notice failed (ignored)")

    async def handle_failure(
        self, event: MessageReceived, soul: SOUL, exc: _EssentialStepError
    ) -> None:
        """End a turn whose ESSENTIAL step failed: persist + GUPPI notice (BOB-049 .3).

        🔴 «Полный Боб или честный GUPPI-нотис»: NO degraded reply is produced. The user's
        turn is persisted (so the message is not lost — consistent with .2) and GUPPI
        honestly reports the outage into Bob's topic. The same path runs for a guest turn
        (only the episodic record is written — no owner facts, no reply — so nothing leaks).
        """
        logger.warning(
            "essential turn step (%s) failed after %d attempts; "
            "emitting GUPPI outage notice (no degraded reply)",
            exc.step,
            self._attempts,
        )
        await self._persist(event, _OUTAGE_MARKER, soul)
        await self.notify_outage()
