# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=conversation
# beadloom:layer=application

"""AntiRepeatGuard — keep Bob from repeating himself, verbatim or by tic (BOB-022/032/043/061).

The turn's «don't say the same thing (or the same ending) twice» concern in one cohesive
collaborator (extracted from ``HandleMessage`` in BOB-062.6b, wave 3, behavior-preserving):

* :meth:`guard` recomposes a fresh reply that (near-)repeats a recent OR recalled Bob reply,
  or that carries a recurring phrase-tic closer — bounded to ``_MAX_REGENERATIONS`` retries,
  each stripping the recalled exemplar(s) the candidate copied (BOB-032 .1 R2), then keeping
  the last draft (never an infinite loop); after the bound a still-recurring closer is
  deterministically stripped (BOB-043) — but never to an EMPTY reply;
* :meth:`closer_anti_tic` detects a cross-session closer-tic BEFORE generation (the persist
  ring UNION the live window) and returns the recalled exemplars (motif stripped) + a soft
  nudge (BOB-061 .2 «провязка»); and
* :meth:`log_closer` appends Bob's reply closer to the cross-session ring after the turn.

🔴 It closes the compose↔guard cycle through an INJECTED ``compose`` CALLBACK (a reference to
:meth:`VoiceComposer.compose` with IDENTICAL arguments — including the turn-LOCAL
``verify_note`` + ``closer_nudge``), wired in ``HandleMessage.__init__`` — NOT an import, so
this conversation vertical never depends on the personality compose use-case (no import cycle).
🔴 ``verify_note`` is a turn-LOCAL argument threaded verbatim into every regeneration, so
judge.assess / provider.search / the interim line each fire at most once per turn even across
the attractor-breaking retries. 🔴 The closer log is fully DECORATIVE + OPTIONAL: unwired, or
on any read/append failure, the anti-tic is inert and the turn is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from bob.conversation.conversation import (
    closer_text,
    is_bob_repeat,
    is_phrase_tic,
    is_recurring_closer_tic,
    recalled_bob_replies,
    recalled_without_copied_exemplars,
    recurring_closer,
    strip_recurring_closer,
)
from bob.conversation.thread import _recent_bob_replies, _strip_recalled_closer
from bob.personality.expression import EngagementLevel, Verbosity

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from bob.application.usecases.handle_message import EpisodeReader
    from bob.conversation.conversation import RepeatThresholds
    from bob.conversation.ports import CloserLog
    from bob.memory.ports import Recalled
    from bob.personality.expression import ExpressionPlan
    from bob.personality.soul import SOUL
    from bob.proactivity.self_improvement import RuleModulators
    from bob.social.interlocutor import Interlocutor
    from bob.social.relationship import Relationship
    from bob.social.sulk import SulkState

logger = logging.getLogger(__name__)

# Max attractor-breaking regenerations the anti-repeat guard may draw before keeping the
# last draft (BOB-032 .1, R2). Each retry strips the recalled exemplar(s) the candidate
# copied; bounded so a stubborn repeat can never spin an infinite loop.
_MAX_REGENERATIONS = 2

# The SOFT anti-tic nudge (BOB-061 .2 — the «провязка»). When Bob's recent closers cluster
# into ONE recurring motif — a genuine closer-tic — this ONE line folds into the generation
# context. 🔴 It is a NUDGE toward variety, never a ban / forbidden-phrase list: Bob is asked
# to END DIFFERENTLY, in his own words, WITHOUT changing the meaning — so liveness (US-4) is
# intact. It fires ONLY on a genuinely detected tic; on no tic the reply context is
# byte-for-byte unchanged.
_CLOSER_TIC_NUDGE = (
    "Эту концовку/оборот ты в последнее время повторяешь часто — заверши ПО-ДРУГОМУ, "
    "своими словами (не меняя смысла)."
)


class _Compose(Protocol):
    """The compose callback (a reference to :meth:`VoiceComposer.compose`, injected).

    Closes the compose↔guard cycle by VALUE, not import: the guard recomposes through this
    callback with IDENTICAL arguments — including the turn-LOCAL ``verify_note`` +
    ``closer_nudge`` — so the personality compose use-case is never imported here.
    """

    async def __call__(
        self,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
        *,
        user_repeated: bool = ...,
        interlocutor: Interlocutor | None = ...,
        is_guest: bool = ...,
        prior_impression: str | None = ...,
        relationship: Relationship | None = ...,
        engagement: EngagementLevel = ...,
        sulk: SulkState | None = ...,
        verbosity: Verbosity = ...,
        modulators: RuleModulators | None = ...,
        chat_id: int | None = ...,
        verify_note: str | None = ...,
        closer_nudge: str = ...,
    ) -> str: ...


class AntiRepeatGuard:
    """Recompose a repeat / phrase-tic reply + manage the cross-session closer ring."""

    def __init__(
        self,
        *,
        repeat_thresholds: RepeatThresholds,
        closer_log: CloserLog | None,
        episodes: EpisodeReader,
        compose: _Compose,
    ) -> None:
        self._repeat_thresholds = repeat_thresholds
        self._closer_log = closer_log
        self._episodes = episodes
        self._compose = compose

    async def guard(
        self,
        reply: str,
        text: str,
        soul: SOUL,
        recalled: Sequence[Recalled],
        history: Sequence[Mapping[str, object]],
        plan: ExpressionPlan,
        user_repeated: bool = False,
        interlocutor: Interlocutor | None = None,
        *,
        is_guest: bool = False,
        prior_impression: str | None = None,
        relationship: Relationship | None = None,
        engagement: EngagementLevel = EngagementLevel.FULL,
        sulk: SulkState | None = None,
        verbosity: Verbosity = Verbosity.NORMAL,
        modulators: RuleModulators | None = None,
        verify_note: str | None = None,
        closer_nudge: str = "",
    ) -> str:
        """Recompose if ``reply`` (near-)repeats a recent OR recalled Bob reply (BOB-032 .1).

        The verbatim-repeat bug was greedy decoding: an identical prompt returned
        byte-identical text. Sampling temperature (the primary fix) makes that stochastic;
        this is defense in depth. BOB-026 .1 widened it from Bob's single most-recent reply
        to a WINDOW of his last N replies and from exact-only to verbatim-OR-near-verbatim.

        BOB-032 .1 closes the deeper hole:

        * **R1 (recall-aware).** The candidate is compared against the UNION of
          recent-history replies AND the ``bob:`` halves recovered from ``recalled`` (the
          model can copy Bob's OWN recalled past reply verbatim).
        * **R2 (attractor-breaking).** On each retry the recalled episode(s) the candidate
          copied are DROPPED from the context (only those — the fact content is preserved),
          up to ``_MAX_REGENERATIONS`` retries; if it is still a repeat after the bound the
          last draft is kept (no infinite loop).

        BOB-036 .1 also guards the PHRASE level: a signature CLOSER recurring across the
        recent window runs the SAME regeneration path. BOB-043 adds the WIDE closer-lookback
        + a deterministic final strip (never to an empty reply).
        """
        threshold = self._repeat_thresholds.similarity_threshold
        tic_min_words = self._repeat_thresholds.tic_min_words
        tic_min_occurrences = self._repeat_thresholds.tic_min_occurrences
        recent = _recent_bob_replies(history, limit=self._repeat_thresholds.window)
        # BOB-043: a WIDE window of Bob's recent closers. The signature tic is SCATTERED
        # (~21% prevalence), so the narrow per-turn view sees it 0-1 times -- below the
        # occurrence bar -- and BOB-036 misses it live. Over the last ``tic_lookback`` (~20)
        # replies it recurs ~4 times -> reliably >=2 -> caught.
        wide_replies = await self._recent_bob_closers()
        current = reply
        current_recalled = recalled
        for _ in range(_MAX_REGENERATIONS):
            prior_replies = (*recent, *recalled_bob_replies(current_recalled))
            full_repeat = is_bob_repeat(current, prior_replies, threshold=threshold)
            # BOB-036 .1: a phrase-tic (a signature CLOSER recurring across the recent
            # window) is invisible to the full-reply bar above — two DIFFERENT replies
            # can share the same tail. Break it via the SAME regeneration path.
            phrase_tic = is_phrase_tic(
                current,
                prior_replies,
                min_words=tic_min_words,
                min_occurrences=tic_min_occurrences,
            )
            # BOB-043: ADD the wide-lookback check — a tic too scattered for the narrow
            # union still recurs across Bob's last ~tic_lookback closers.
            wide_tic = is_phrase_tic(
                current,
                wide_replies,
                min_words=tic_min_words,
                min_occurrences=tic_min_occurrences,
            )
            if not (full_repeat or phrase_tic or wide_tic):
                return current
            # Break the attractor: strip the recalled reply exemplar(s) the candidate
            # copied so the next draft no longer sees the text it was echoing.
            current_recalled = recalled_without_copied_exemplars(
                current, current_recalled, threshold=threshold
            )
            # 🔴 BOB-057 .5 (US-3 «один поиск, не петля»): REUSE the verify note computed
            # once for this turn instead of recomputing it on every regeneration. Threading
            # the same ``verify_note`` (a turn-LOCAL) through the compose callback means
            # judge.assess / provider.search / the live interim line each fire AT MOST ONCE
            # per turn. ``chat_id`` is intentionally omitted on regeneration (as before) —
            # the interim already spoke on the first pass.
            current = await self._compose(
                text,
                soul,
                current_recalled,
                history,
                plan,
                user_repeated=user_repeated,
                interlocutor=interlocutor,
                is_guest=is_guest,
                prior_impression=prior_impression,
                relationship=relationship,
                engagement=engagement,
                sulk=sulk,
                verbosity=verbosity,
                modulators=modulators,
                verify_note=verify_note,
                closer_nudge=closer_nudge,
            )
        # BOB-043: regeneration could not shake the tic. If the final draft STILL ends with a
        # closer that RECURS across the wide window, deterministically STRIP that trailing
        # sentence so the tic NEVER ships. Only a genuinely recurring closer is removed
        # (``recurring_closer`` returns None for a one-off ending) — no false positive.
        closer = recurring_closer(
            current,
            wide_replies,
            min_words=tic_min_words,
            min_occurrences=tic_min_occurrences,
        )
        if closer is not None:
            # Guard the edge case where the ENTIRE reply is the recurring closer (a bare
            # "Мне так спокойнее."): stripping would leave an empty string, so keep the
            # last draft rather than ship nothing (BOB-043 review).
            stripped = strip_recurring_closer(current, closer)
            return stripped if stripped.strip() else current
        return current

    async def _recent_bob_closers(self) -> tuple[str, ...]:
        """Bob's last ``tic_lookback`` reply texts for the wide tic check (BOB-043).

        The single new read behind the anti-repeat guard: a WIDE window of Bob's recent
        replies (whose closers the phrase-tic detector scans) via the existing
        ``recent_episodes`` seam. It scans Bob's OWN closers (not owner-private material),
        so BOB-051 runs it for every member alike — the anti-tic quality is unified.
        """
        lookback = self._repeat_thresholds.tic_lookback
        wide_history = await self._episodes.recent_episodes(lookback)
        return _recent_bob_replies(wide_history, limit=lookback)

    async def log_closer(self, reply: str) -> None:
        """Append Bob's reply CLOSER to the cross-session ring (BOB-061 .2 wiring).

        The persist half of the «провязка»: the reply's final notable closer (normalised,
        via :func:`closer_text`) is logged so a signature ending recurring ONCE PER SESSION
        over days accumulates in the ring and the tic detector can finally see it. An empty
        closer (a short/blank ending, or an unwired log) is skipped. 🔴 Decorative: a store
        failure is swallowed — this local memory NEVER breaks a turn that already replied.
        """
        if self._closer_log is None:
            return
        closer = closer_text(reply, min_words=self._repeat_thresholds.tic_min_words)
        if not closer:
            return
        try:
            await self._closer_log.append(closer)
        except Exception:
            # Decorative persist: log + drop, never break a turn that already replied.
            logger.warning("appending Bob's closer to the ring failed (ignored)")

    async def closer_anti_tic(
        self, recalled: Sequence[Recalled], history: Sequence[Mapping[str, object]]
    ) -> tuple[Sequence[Recalled], str]:
        """Detect a cross-session closer-tic and return (recalled, soft-nudge) (BOB-061 .2).

        The detect half of the «провязка», computed ONCE per turn BEFORE generation. Reads
        Bob's persisted closers (the ring) UNION the live-window closers and asks
        :func:`is_recurring_closer_tic` — at the CONSERVATIVE ``motif_similarity_threshold``
        — whether his freshest ending clusters into a recurring motif. When it fires:

        * (a) the motif closer is STRIPPED off the recalled Bob-reply exemplars so the tic is
          not fed back as few-shot, and
        * (b) the soft :data:`_CLOSER_TIC_NUDGE` line is returned to fold into the context.

        🔴 Decorative + conservative (US-4 liveness): an unwired log, a read failure, or NO
        tic all return ``(recalled, "")`` UNCHANGED — zero effect on the reply.
        """
        if self._closer_log is None:
            return recalled, ""
        try:
            motif = await self._detect_closer_tic(history)
        except Exception:
            # Decorative detect: on any failure, no nudge and a normal reply (never break).
            logger.warning("closer-tic detection failed (ignored) — no nudge")
            return recalled, ""
        if motif is None:
            return recalled, ""
        stripped = tuple(_strip_recalled_closer(item, motif) for item in recalled)
        return stripped, _CLOSER_TIC_NUDGE

    async def _detect_closer_tic(
        self, history: Sequence[Mapping[str, object]]
    ) -> str | None:
        """Return the recurring closer MOTIF for this turn, or ``None`` (BOB-061 .2).

        Assembles Bob's recent closers — the persist ring (``recent(tic_lookback)``) UNION
        the live-window closers extracted from ``history`` — and probes the FRESHEST closer
        against the rest via :func:`is_recurring_closer_tic`. Fires only when that ending
        near-verbatim RECURS at least ``tic_min_occurrences`` times at the conservative
        ``motif_similarity_threshold``. The matched closer is returned so the caller can
        strip it off the recalled exemplars.
        """
        assert self._closer_log is not None  # guarded by the caller
        persisted = await self._closer_log.recent(self._repeat_thresholds.tic_lookback)
        min_words = self._repeat_thresholds.tic_min_words
        window_replies = _recent_bob_replies(
            history, limit=self._repeat_thresholds.window
        )
        window_closers = tuple(
            c for r in window_replies if (c := closer_text(r, min_words=min_words))
        )
        closers = (*persisted, *window_closers)
        if not closers:
            return None
        current, prior = closers[0], closers[1:]
        if is_recurring_closer_tic(
            current,
            prior,
            similarity_threshold=self._repeat_thresholds.motif_similarity_threshold,
            min_occurrences=self._repeat_thresholds.tic_min_occurrences,
        ):
            return current
        return None
