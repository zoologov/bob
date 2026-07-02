# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=personality

"""Repeat detection — owner repeats himself (BOB-022) + Bob repeats himself (BOB-026).

Pure, no-LLM predicates.

* :func:`is_user_repeat` (BOB-022) — when the owner sends (near-)the-same message
  he already sent in the recent window, Bob should NOTICE it (and react in his own
  wry voice via :func:`~bob.domain.personality.voice.user_repeat_directive`) rather
  than silently re-answer. Deliberately CONSERVATIVE: an EXACT match after
  normalisation (strip / casefold / collapse internal whitespace), never fuzzy —
  so Bob never accuses the owner of repeating himself when he did not.

* :func:`is_bob_repeat` (BOB-026 .1) — the own-reply twin: does Bob's fresh
  candidate reply echo one of his OWN recent replies (verbatim OR near-verbatim) so
  the anti-repeat guard regenerates? Checks the whole recent window — not just the
  last reply — so a repeat "через ход" no longer slips through.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from bob.domain.ports import Recalled

# Дефолтный порог сходства для near-repeat ответа Боба (BOB-026 .1). Консервативно
# высокий: ловит дословные и near-дословные повторы (мелкие правки одной фразы), но
# НЕ срабатывает на просто похожие по теме, но разные по сути ответы. Перекрывается
# из конфига (``repeat.similarity_threshold``) через app-композицию.
_DEFAULT_BOB_REPEAT_THRESHOLD = 0.9

# Дефолтный размер окна последних ответов Боба, с которыми сравнивается кандидат
# (BOB-026 .1). Достаточно широкое, чтобы поймать повтор «через ход», но не больше
# обычной истории. Перекрывается из конфига (``repeat.window``).
_DEFAULT_BOB_REPEAT_WINDOW = 5

_MIN_REPEAT_WINDOW = 1
_MIN_REPEAT_THRESHOLD = 0.0
_MAX_REPEAT_THRESHOLD = 1.0

# Дефолты фраза-тик детектора (BOB-036 .1). ``tic_min_words`` ≈ 3: «Мне так
# спокойнее» (3 слова) ловится, а короткая закрывашка «Работаем»/«Ок» — нет.
# ``tic_min_occurrences`` = 2: фраза, повторившаяся в ≥2 недавних репликах, —
# это тик, а одноразовое переиспользование длинной фразы — нет.
_DEFAULT_TIC_MIN_WORDS = 3
_DEFAULT_TIC_MIN_OCCURRENCES = 2

_MIN_TIC_MIN_WORDS = 1
_MIN_TIC_MIN_OCCURRENCES = 1

# Default WIDE closer-lookback window (BOB-043). The signature closer is SCATTERED
# (~21% prevalence): in the narrow per-turn view (≈6 history + ≈5 recall replies) it
# shows up 0-1 times -- below ``tic_min_occurrences`` -- so BOB-036 misses it live. Over
# the last ~20 of Bob's replies a 21%-prevalence tic recurs ~4 times -> reliably >=2.
# Overridable from config (``repeat.tic_lookback``).
_DEFAULT_TIC_LOOKBACK = 20

_MIN_TIC_LOOKBACK = 1

# Conservative near-verbatim threshold for CLOSER-MOTIF clustering (BOB-061 .1). The
# closer-motif twin of ``similarity_threshold``: it reuses the SAME SequenceMatcher
# ratio, but calibrated for SHORT closer phrases. A closer is a few words, so a
# single-word variant («мне»->«ему», «остаётся»->«останется») costs far more ratio than
# the same edit inside a whole reply — the whole-reply 0.9 bar would miss those genuine
# motif variants (~0.88-0.94). 0.82 clusters them while staying FAR above distinct
# closers (~0.2-0.25), so it never strangles a legitimately different ending (US-4).
# Overridable from config (``repeat.motif_similarity_threshold``).
_DEFAULT_MOTIF_SIMILARITY_THRESHOLD = 0.82


@dataclass(frozen=True, slots=True)
class RepeatThresholds:
    """Пороги анти-повтора ответа Боба (инъекция из ``repeat.*`` конфига, BOB-026 .1).

    * ``window`` — сколько последних ответов Боба сравнивать с кандидатом (окно, не
      только последний ответ): ловит повтор «через ход».
    * ``similarity_threshold`` — порог сходства ``[0, 1]`` для near-verbatim
      детекции; консервативно высокий, чтобы не было ложных регенераций на просто
      похожих по теме, но разных по сути ответах.
    * ``tic_min_words`` — минимальная длина «заметной» фразы в словах для
      фраза-тик детектора (BOB-036 .1): закрывашка короче этого порога
      («Работаем»/«Ок») никогда не считается тиком.
    * ``tic_min_occurrences`` — в скольких недавних репликах фраза должна
      повториться, чтобы считаться тиком (а не одноразовым переиспользованием).
    * ``tic_lookback`` — ШИРОКОЕ окно последних реплик Боба, по closer-фразам
      которого гоняется фраза-тик детектор (BOB-043). Узкий по-ходовой обзор
      (~6 истории + ~5 recall) видит рассеянный тик 0-1 раз — ниже порога; на ~20
      репликах тик с распространённостью ~21% повторяется ~4 раза и ловится.
    * ``motif_similarity_threshold`` — консервативный near-verbatim порог для
      кластеризации closer-МОТИВА (BOB-061 .1): closer-twin ``similarity_threshold``,
      калиброванный под КОРОТКИЕ closer-фразы. Реюзит тот же SequenceMatcher-ratio, но
      ловит лексические варианты одного мотива («мне/ему так спокойнее»), не сцепляя
      разные по сути концовки (US-4).

    Дефолты консервативны.
    """

    window: int = _DEFAULT_BOB_REPEAT_WINDOW
    similarity_threshold: float = _DEFAULT_BOB_REPEAT_THRESHOLD
    tic_min_words: int = _DEFAULT_TIC_MIN_WORDS
    tic_min_occurrences: int = _DEFAULT_TIC_MIN_OCCURRENCES
    tic_lookback: int = _DEFAULT_TIC_LOOKBACK
    motif_similarity_threshold: float = _DEFAULT_MOTIF_SIMILARITY_THRESHOLD

    def __post_init__(self) -> None:
        if self.window < _MIN_REPEAT_WINDOW:
            raise ValueError(
                f"repeat threshold 'window' must be >= {_MIN_REPEAT_WINDOW}, "
                f"got {self.window}"
            )
        if not _MIN_REPEAT_THRESHOLD <= self.similarity_threshold <= _MAX_REPEAT_THRESHOLD:
            raise ValueError(
                f"repeat threshold 'similarity_threshold' must be within "
                f"[{_MIN_REPEAT_THRESHOLD}, {_MAX_REPEAT_THRESHOLD}], "
                f"got {self.similarity_threshold}"
            )
        if self.tic_min_words < _MIN_TIC_MIN_WORDS:
            raise ValueError(
                f"repeat threshold 'tic_min_words' must be >= {_MIN_TIC_MIN_WORDS}, "
                f"got {self.tic_min_words}"
            )
        if self.tic_min_occurrences < _MIN_TIC_MIN_OCCURRENCES:
            raise ValueError(
                f"repeat threshold 'tic_min_occurrences' must be >= "
                f"{_MIN_TIC_MIN_OCCURRENCES}, got {self.tic_min_occurrences}"
            )
        if self.tic_lookback < _MIN_TIC_LOOKBACK:
            raise ValueError(
                f"repeat threshold 'tic_lookback' must be >= {_MIN_TIC_LOOKBACK}, "
                f"got {self.tic_lookback}"
            )
        if not (
            _MIN_REPEAT_THRESHOLD
            <= self.motif_similarity_threshold
            <= _MAX_REPEAT_THRESHOLD
        ):
            raise ValueError(
                f"repeat threshold 'motif_similarity_threshold' must be within "
                f"[{_MIN_REPEAT_THRESHOLD}, {_MAX_REPEAT_THRESHOLD}], "
                f"got {self.motif_similarity_threshold}"
            )


def _normalise(text: str) -> str:
    """Strip, casefold, and collapse internal whitespace for an exact compare.

    Two messages that differ only in case or whitespace are the same message for
    repeat-detection purposes; everything else is left intact so the match stays
    exact (never fuzzy).
    """
    return " ".join(text.split()).casefold()


def is_user_repeat(current: str, prior_user_texts: Iterable[str]) -> bool:
    """Return ``True`` iff ``current`` exactly repeats a recent prior user turn.

    Both sides are normalised (strip / casefold / collapse whitespace) and matched
    exactly — conservative by design so it never false-fires. An empty/blank
    ``current`` is never a repeat (nothing meaningful to repeat).
    """
    normalised_current = _normalise(current)
    if not normalised_current:
        return False
    return any(normalised_current == _normalise(prior) for prior in prior_user_texts)


def is_bob_repeat(
    candidate: str,
    recent_bob_replies: Iterable[str],
    *,
    threshold: float = _DEFAULT_BOB_REPEAT_THRESHOLD,
) -> bool:
    """Return ``True`` iff ``candidate`` (near-)repeats ANY recent Bob reply (BOB-026 .1).

    The own-reply twin of :func:`is_user_repeat`: does Bob's fresh candidate reply
    echo one of his OWN recent replies — verbatim (after the same strip / casefold /
    whitespace normalisation) OR near-verbatim (a similarity ratio at or above
    ``threshold``)? Unlike the previous guard, which only looked at Bob's most-recent
    reply, this checks the whole window, so a repeat "через ход" — отказ → another
    turn → the SAME отказ — no longer slips through.

    Near-verbatim uses :class:`difflib.SequenceMatcher` (stdlib, no new deps) on the
    normalised texts. ``threshold`` is deliberately conservative (high) so a merely
    topically-similar but substantively different reply never false-fires a needless
    regeneration. An empty/blank ``candidate`` is never a repeat; blank recent replies
    are skipped.
    """
    normalised_candidate = _normalise(candidate)
    if not normalised_candidate:
        return False
    for prior in recent_bob_replies:
        normalised_prior = _normalise(prior)
        if not normalised_prior:
            continue
        if normalised_candidate == normalised_prior:
            return True
        ratio = SequenceMatcher(None, normalised_candidate, normalised_prior).ratio()
        if ratio >= threshold:
            return True
    return False


# Sentence/clause boundaries used to split a reply into candidate "notable" phrases
# for the tic detector (BOB-036 .1). A tic is usually a CLOSER, so each sentence —
# including the final clause — becomes a candidate phrase.
_PHRASE_BOUNDARIES = ".!?\n"


def _notable_phrases(text: str, *, min_words: int) -> frozenset[str]:
    """Return the reply's normalised phrases of length >= ``min_words`` words (BOB-036 .1).

    Splits ``text`` on sentence/clause boundaries (``.``/``!``/``?``/newline), then
    normalises each fragment (strip / casefold / collapse whitespace, via
    :func:`_normalise`). A tic is usually a CLOSER, so the FINAL clause is captured
    like any other sentence — every fragment of at least ``min_words`` words is a
    candidate "notable" phrase. Short fragments (a one-word closer like "Работаем")
    are dropped so common short closers never trip the detector. The result is a SET,
    so a phrase repeated WITHIN one reply still counts once for that reply.
    """
    phrases: set[str] = set()
    for content, _boundary in _split_sentences(text):
        _add_phrase(phrases, content, min_words=min_words)
    return frozenset(phrases)


def _add_phrase(phrases: set[str], fragment: str, *, min_words: int) -> None:
    """Add ``fragment`` to ``phrases`` iff, once normalised, it has >= ``min_words`` words."""
    normalised = _normalise(fragment)
    if normalised and len(normalised.split()) >= min_words:
        phrases.add(normalised)


def is_phrase_tic(
    candidate: str,
    recent_replies: Iterable[str],
    *,
    min_words: int,
    min_occurrences: int,
) -> bool:
    """Return ``True`` iff ``candidate`` shares a RECURRING notable phrase (BOB-036 .1).

    The phrase-level twin of :func:`is_bob_repeat`. BOB-032's full-reply guard compares
    whole replies (a high similarity bar), so two substantively DIFFERENT messages that
    merely end with the SAME signature closer ("Мне так спокойнее.") slip through. This
    catches the closer-tic structurally — never via a scripted "do not say X".

    A "notable phrase" is a sentence/clause of at least ``min_words`` words (see
    :func:`_notable_phrases`); the FINAL clause is included, since a tic is usually a
    closer. ``candidate`` is a tic iff one of ITS notable phrases also appears as a
    notable phrase in at least ``min_occurrences`` of the ``recent_replies`` (each recent
    reply counts at most once — a phrase repeated within one reply is still that one
    reply). So a phrase recurring ACROSS the recent window is a tic, while a one-off
    reuse (shared with a single prior reply) or a short closer (below ``min_words``) is
    not. Pure, deterministic, no I/O. A blank ``candidate`` is never a tic.
    """
    candidate_phrases = _notable_phrases(candidate, min_words=min_words)
    if not candidate_phrases:
        return False
    occurrences = 0
    for reply in recent_replies:
        if candidate_phrases & _notable_phrases(reply, min_words=min_words):
            occurrences += 1
            if occurrences >= min_occurrences:
                return True
    return False


def _split_sentences(text: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(content, boundary)`` pairs preserving order/punctuation.

    Each pair is a fragment and the boundary char that terminated it (one of
    :data:`_PHRASE_BOUNDARIES`), or ``""`` for a trailing fragment with no closing
    boundary. Rejoining ``content + boundary`` for every pair reconstructs ``text``
    exactly, so the strip helper can drop one sentence and rebuild the rest losslessly.
    """
    sentences: list[tuple[str, str]] = []
    fragment_chars: list[str] = []
    for char in text:
        if char in _PHRASE_BOUNDARIES:
            sentences.append(("".join(fragment_chars), char))
            fragment_chars = []
        else:
            fragment_chars.append(char)
    if fragment_chars:
        sentences.append(("".join(fragment_chars), ""))
    return sentences


def _final_notable_phrase(text: str, *, min_words: int) -> str | None:
    """Return ``text``'s LAST notable phrase (normalised), or ``None`` (BOB-043).

    The closer is the final sentence/clause of at least ``min_words`` words (a tic is a
    CLOSER). Scans sentences back to front and returns the first that clears the
    notability bar — so a trailing short/blank fragment (whitespace, a one-word
    "Работаем") is skipped and the substantive closing sentence is found. ``None`` when
    no sentence is notable.
    """
    for content, _boundary in reversed(_split_sentences(text)):
        normalised = _normalise(content)
        if normalised and len(normalised.split()) >= min_words:
            return normalised
    return None


def recurring_closer(
    candidate: str,
    recent_replies: Iterable[str],
    *,
    min_words: int,
    min_occurrences: int,
) -> str | None:
    """Return ``candidate``'s FINAL phrase iff it RECURS across ``recent_replies`` (BOB-043).

    Targets exactly the deterministic-strip case: ``candidate``'s closing notable phrase
    (its tic, see :func:`_final_notable_phrase`) recurring as a notable phrase in at least
    ``min_occurrences`` of ``recent_replies`` (each reply counts at most once). Returns the
    recurring closer (normalised) so the caller can strip it; ``None`` when the final phrase
    is a one-off ending (below ``min_occurrences``) or below ``min_words`` — so the strip
    only ever fires on a closer that genuinely recurs, never on a distinct one-off tail.
    Pure, deterministic, no I/O.
    """
    closer = _final_notable_phrase(candidate, min_words=min_words)
    if closer is None:
        return None
    occurrences = 0
    for reply in recent_replies:
        if closer in _notable_phrases(reply, min_words=min_words):
            occurrences += 1
            if occurrences >= min_occurrences:
                return closer
    return None


def strip_recurring_closer(text: str, closer: str) -> str:
    """Remove the trailing ``closer`` sentence from ``text``, tidied (BOB-043).

    The deterministic last-resort: when regeneration cannot shake a recurring closer-tic,
    its final sentence is excised so the tic never ships. ``closer`` is the recurring
    phrase (normalised, as returned by :func:`recurring_closer`); this drops the LAST
    sentence of ``text`` whose normalised content equals it (and any trailing fragment
    after it), then strips trailing whitespace — leaving the substantive reply intact. A
    blank ``closer``, or a ``text`` whose trailing sentence is not ``closer``, is returned
    unchanged (a no-op — never strips a sentence the closer does not match). Pure, no I/O.
    """
    normalised_closer = _normalise(closer)
    if not normalised_closer:
        return text
    sentences = _split_sentences(text)
    target: int | None = None
    for index, (content, _boundary) in enumerate(sentences):
        if _normalise(content) == normalised_closer:
            target = index
    if target is None:
        return text
    kept = sentences[:target]
    rebuilt = "".join(content + boundary for content, boundary in kept)
    return rebuilt.rstrip()


def closer_text(reply: str, *, min_words: int) -> str | None:
    """Return ``reply``'s final notable closer phrase (normalised), or ``None`` (BOB-061 .1).

    The public extraction the cross-session closer machinery is built on: the closer is
    the LAST sentence/clause of at least ``min_words`` words (see
    :func:`_final_notable_phrase`) — a trailing short/blank fragment is skipped — returned
    normalised (strip / casefold / collapse whitespace) so the logged closer is directly
    comparable as a motif. ``None`` when the reply has no notable closer. This is what the
    wiring (.2) calls to (a) APPEND Bob's normalised closer to the persist ring after each
    reply and (b) extract the current reply's closer to feed the motif detector. Pure, no I/O.
    """
    return _final_notable_phrase(reply, min_words=min_words)


def is_same_closer_motif(first: str, second: str, *, similarity_threshold: float) -> bool:
    """Return ``True`` iff two closers are the SAME recurring motif (BOB-061 .1, gap 2).

    The near-verbatim clustering that closes gap 2: an exact-match-after-``_normalise``
    tic detector UNDER-counts a motif that recurs in lexical VARIANTS («пусть остаётся/
    останется как есть», «мне/ему так спокойнее»). Two closers cluster as one motif when
    they are identical after normalisation OR near-verbatim — a
    :class:`difflib.SequenceMatcher` ratio at or above ``similarity_threshold`` (the SAME
    ratio machinery as :func:`is_bob_repeat`, reused). ``similarity_threshold`` is
    deliberately CONSERVATIVE (see :data:`_DEFAULT_MOTIF_SIMILARITY_THRESHOLD`): genuine
    variants sit ~0.88-0.94 while substantively distinct closers sit ~0.2-0.25, so a merely
    different ending never clusters (US-4 — no over-suppression). A blank side never
    clusters. Pure, deterministic, no I/O.
    """
    normalised_first = _normalise(first)
    normalised_second = _normalise(second)
    if not normalised_first or not normalised_second:
        return False
    if normalised_first == normalised_second:
        return True
    ratio = SequenceMatcher(None, normalised_first, normalised_second).ratio()
    return ratio >= similarity_threshold


def is_recurring_closer_tic(
    current_closer: str,
    prior_closers: Iterable[str],
    *,
    similarity_threshold: float,
    min_occurrences: int,
) -> bool:
    """Return ``True`` iff ``current_closer`` near-verbatim-RECURS across ``prior_closers``.

    The detector .2 calls (BOB-061 .1, gaps 1+2 together): given ``current_closer`` (the
    current reply's closer) and ``prior_closers`` — Bob's recent closers drawn from the
    cross-session persist ring UNION the live window — decide whether the current closer is
    a recurring tic. It counts how many ``prior_closers`` are the SAME motif as
    ``current_closer`` (via :func:`is_same_closer_motif` at ``similarity_threshold``, so
    lexical variants cluster) and fires when that count reaches ``min_occurrences``. This is
    what finally catches the once-per-session tic: a motif logged ~4×/week across the
    persisted ring accumulates enough occurrences even though the LIVE window alone never
    would. A blank ``current_closer`` (or empty history) is never a tic. Pure,
    deterministic, no I/O — thresholds injected.
    """
    if not _normalise(current_closer):
        return False
    occurrences = 0
    for prior in prior_closers:
        if is_same_closer_motif(
            current_closer, prior, similarity_threshold=similarity_threshold
        ):
            occurrences += 1
            if occurrences >= min_occurrences:
                return True
    return False


# Marker prefixing Bob's turn inside a persisted/recalled episode's ``content``: an
# episode is stored as ``"<sender>: <text>\nbob: <reply>"`` (see
# :meth:`~bob.application.usecases.handle_message.HandleMessage._persist`). The shared
# recall-aware anti-repeat (reactive + proactive, BOB-032) recovers Bob's ``bob:`` half
# from each recalled episode through this marker.
_BOB_TURN_MARKER = "\nbob: "


def recalled_bob_reply(item: Recalled) -> str:
    """Return the ``bob:`` half of a recalled episode's content, or ``""`` (BOB-032).

    Recalled semantic memories are stored as whole turns
    ``"<sender>: <text>\\nbob: <old reply>"`` (the same shape as history). This recovers
    Bob's OWN past reply from a recalled episode via :data:`_BOB_TURN_MARKER` so the
    recall-aware anti-repeat guard (reactive AND proactive) can see — and break — Bob
    copying a recalled reply verbatim. A non-string content or a fact-only memory with no
    ``bob:`` half (e.g. "user prefers tea") yields ``""``, so only Bob's copyable reply
    exemplars feed the guard.
    """
    content = item.get("content")
    if not isinstance(content, str):
        return ""
    marker = content.rfind(_BOB_TURN_MARKER)
    if marker == -1:
        return ""
    return content[marker + len(_BOB_TURN_MARKER) :]


def recalled_bob_replies(recalled: Sequence[Recalled]) -> tuple[str, ...]:
    """Return every non-blank Bob reply embedded in the recalled memories (BOB-032).

    R1 (recall-aware anti-repeat): the compose context folds in ``recalled`` semantic
    memories as whole turns, so the model can copy Bob's OWN recalled past reply verbatim
    — a repeat the history-only window is blind to. This recovers the ``bob:`` half of each
    recalled episode (via :func:`recalled_bob_reply`) so a fresh candidate can be compared
    against recalled Bob-replies. Fact-only memories (no ``bob:`` half) and blanks
    contribute nothing. Shared by the reactive turn and the proactive engine.
    """
    return tuple(reply for item in recalled if (reply := recalled_bob_reply(item)))


def recalled_without_copied_exemplars(
    candidate: str, recalled: Sequence[Recalled], *, threshold: float
) -> tuple[Recalled, ...]:
    """Drop the recalled memories whose Bob-reply ``candidate`` copied (BOB-032, R2).

    Attractor-breaking regeneration: when the guard catches ``candidate`` (near-)repeating
    a recalled Bob reply, the retry must no longer SEE the text it was copying. This returns
    ``recalled`` with exactly the episodes whose ``bob:`` half ``candidate`` matched (via
    :func:`is_bob_repeat` at ``threshold``) removed — and ONLY those. Fact-only memories and
    unmatched episodes are preserved untouched, so recall-grounding of FACTS is never
    weakened; only the copied REPLY exemplar is withheld from the next draft. Shared by the
    reactive turn and the proactive engine.
    """
    kept: list[Recalled] = []
    for item in recalled:
        exemplar = recalled_bob_reply(item)
        if exemplar and is_bob_repeat(candidate, [exemplar], threshold=threshold):
            continue
        kept.append(item)
    return tuple(kept)


# The episodic ``event_type`` values that mark a private inner-life reflection (the
# heartbeat writes these via BOB-012). Mirrors
# :data:`bob.infrastructure.persistence.proactivity_sources._INNER_LIFE_KINDS` — the
# single source of "what is a reflection" the reply-recall containment reads.
_REFLECTION_KINDS = frozenset({"reflection", "inner_monologue"})


def recalled_excluding_reflections(recalled: Sequence[Recalled]) -> tuple[Recalled, ...]:
    """Drop private REFLECTION episodes from the reply-recall pool (BOB-033 .3).

    Containment of reflection mimicry: Bob's inner monologue must shape his replies
    through MOOD, not by the model parroting reflection TEXT as a copyable exemplar.
    This returns ``recalled`` with every episode whose ``category`` (the episodic
    ``event_type``) is a reflection kind removed — and ONLY those, so distilled facts
    and past message turns still ground the reply. A memory with no/other category is
    kept (defensive default: only a known reflection kind is excluded). The deliberate
    ``leak_inner_life`` path (BOB-018) is untouched — it reaches a reflection through a
    separate reader, never this pool.
    """
    return tuple(item for item in recalled if not _is_reflection(item))


def _is_reflection(item: Recalled) -> bool:
    """True when a recalled memory is a private inner-life reflection episode."""
    category = item.get("category")
    return isinstance(category, str) and category.casefold() in _REFLECTION_KINDS
