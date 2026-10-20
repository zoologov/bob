# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=runtime
# beadloom:layer=runtime

"""Composition-root parameter wiring — resolve config-tuned scalars, flags and dataclasses.

The family of small ``_build_*`` readers that turn config sections into the concrete tuned
parameters HandleMessage / the ticks / the engines consume (thresholds, frequencies,
feature flags, the proactivity RNG seed). Pure config → value; no adapters are built here.
Part of the ``bob.runtime`` composition root (BOB-062.7a).
"""

from __future__ import annotations

import os
import random
from typing import TYPE_CHECKING

from bob.conversation.addressivity import AddressivityThresholds
from bob.conversation.brevity import BrevityThresholds
from bob.conversation.conversation import RepeatThresholds
from bob.conversation.conversation_floor import FloorConfig
from bob.conversation.engagement import EngagementThresholds, FatigueRates
from bob.personality.expression import ExpressionFreqs
from bob.personality.voice import OffDayThresholds
from bob.runtime.config import (
    _ACKNOWLEDGE_REACTION_FREQ,
    _DEFAULT_ABSENCE_HINT_HOURS,
    _DEFAULT_DIAGRAM_SEND_AS,
    _DEFAULT_ENGAGEMENT_MOOD_LIFT,
    _DEFAULT_FASCINATION_INTENSITY,
    _DEFAULT_LENGTH_GUARD_MAX_CHARS,
    _DEFAULT_PURSUIT_TICK_SECONDS,
    _DEFAULT_RECENT_TURNS,
    _PHANTOM_CHANGE_RATE,
    _PHANTOM_MAX_COUNT,
    _SURFACE_OLD_FREQ,
    _flag,
    _float_or,
    _int,
    _section,
    _str,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bob.capabilities.usecases.diagram_sender import DiagramSendMode


def _resolve_seed(config: Mapping[str, object], seed: int | None) -> int:
    """Resolve the proactivity RNG seed: arg → config → env → fresh per-process."""
    if seed is not None:
        return seed
    configured = _int(_section(config, "runtime"), "proactivity_seed", -1)
    if configured >= 0:
        return configured
    env = os.environ.get("BOB_PROACTIVITY_SEED")
    if env is not None and env.isdigit():
        return int(env)
    return random.SystemRandom().randrange(2**32)


def _fascination_initial_intensity(config: Mapping[str, object]) -> float:
    """Read the BOB-020 fresh-fascination intensity from ``emotion.fascination.*``.

    How vivid a freshly-grounded fascination starts (it then decays with age). Falls
    back to the :class:`EvolveFascination` default when absent; out-of-range values
    are clamped to ``[0, 1]`` by the use-case itself.
    """
    fascination = _section(_section(config, "emotion"), "fascination")
    return _float_or(fascination, "initial_intensity", _DEFAULT_FASCINATION_INTENSITY)


def _phantom_evolution_params(config: Mapping[str, object]) -> tuple[int, float]:
    """Read the BOB-020 phantom-evolution bound + cadence from ``emotion.phantom.*``.

    ``max_count`` caps how many phantom preferences Bob carries at once; ``change_rate``
    is the small per-step probability a grounded candidate actually emerges (keeping the
    drift slow). Both fall back to the kernel's conservative defaults when absent; an
    out-of-range ``change_rate`` is clamped to ``[0, 1]`` and a non-positive ``max_count``
    to at least 1, so misconfiguration cannot break the bound.
    """
    phantom = _section(_section(config, "emotion"), "phantom")
    max_count = max(1, _int(phantom, "max_count", _PHANTOM_MAX_COUNT))
    change_rate = min(1.0, max(0.0, _float_or(phantom, "change_rate", _PHANTOM_CHANGE_RATE)))
    return max_count, change_rate


def _build_offday_thresholds(config: Mapping[str, object]) -> OffDayThresholds:
    """Build the BOB-020 off-day tone thresholds from config (low/negative defaults).

    Reads ``emotion.offday.{valence,arousal}`` — the mood floor below which Bob's
    tone shifts to the quieter, vulnerable, honest off-day band instead of forced
    warmth. Falls back to the dataclass defaults (which sit in the low/negative band,
    so a normal or good mood always keeps the warm tone) when a value is absent.
    """
    offday = _section(_section(config, "emotion"), "offday")
    defaults = OffDayThresholds()
    return OffDayThresholds(
        valence=_float_or(offday, "valence", defaults.valence),
        arousal=_float_or(offday, "arousal", defaults.arousal),
    )


def _build_expression_freqs(config: Mapping[str, object]) -> ExpressionFreqs:
    """Build the BOB-018 expression add-on frequencies from config (small defaults).

    Reads ``expression.freqs.{leak_inner_life,callback}`` — the small fractions of
    turns the rare add-on flags fire on (anti-tic). Falls back to the dataclass
    defaults when a value is absent. Out-of-range values are rejected by
    :class:`ExpressionFreqs` itself ([0, 1] probabilities).
    """
    freqs = _section(_section(config, "expression"), "freqs")
    defaults = ExpressionFreqs()
    # The fascination-surfacing frequency (BOB-020) can be set under either
    # ``expression.freqs.mention_fascination`` (alongside the other add-ons) or the
    # emotion-scoped ``emotion.fascination.mention_freq`` knob; the emotion knob wins
    # when present so all fascination tuning lives in one place.
    fascination = _section(_section(config, "emotion"), "fascination")
    mention = _float_or(
        freqs,
        "mention_fascination",
        _float_or(fascination, "mention_freq", defaults.mention_fascination),
    )
    return ExpressionFreqs(
        leak_inner_life=_float_or(freqs, "leak_inner_life", defaults.leak_inner_life),
        callback=_float_or(freqs, "callback", defaults.callback),
        mention_fascination=mention,
    )


def _build_engagement_thresholds(config: Mapping[str, object]) -> EngagementThresholds:
    """Build the BOB-014 .2a appetite thresholds from ``engagement.thresholds.*``.

    Tunes the appetite boundaries: ``interesting`` (the interest bar a topic clears even
    on a low mood), ``high_fatigue`` (the "наскучило" point), ``low_mood`` / ``bright_mood``
    (the mood bands raising the bar / unlocking banter), and ``playful_chance`` (how
    often a bright-mood engaged turn tips into playful banter). Each falls back to the
    dataclass default — which keeps a normal mood fully engaging on any non-trivial topic.
    """
    section = _section(_section(config, "engagement"), "thresholds")
    defaults = EngagementThresholds()
    return EngagementThresholds(
        interesting=_float_or(section, "interesting", defaults.interesting),
        high_fatigue=_float_or(section, "high_fatigue", defaults.high_fatigue),
        low_mood=_float_or(section, "low_mood", defaults.low_mood),
        bright_mood=_float_or(section, "bright_mood", defaults.bright_mood),
        playful_chance=_float_or(section, "playful_chance", defaults.playful_chance),
    )


def _build_addressivity_thresholds(
    config: Mapping[str, object],
) -> AddressivityThresholds:
    """Build the BOB-023 addressivity policy thresholds from ``addressivity.*``.

    Tunes how readily Bob takes a turn by who it is for: ``barge_in_interest`` (the
    HIGH interest bar to rarely cut into someone ELSE's exchange) and ``barge_in_freq``
    (the small seeded frequency of doing so); ``ambient_interest`` (the lower bar to
    join a general ambient turn when others are around) and ``ambient_barge_in_freq``
    (its — easier — frequency); ``react_chance`` (how often an ambient-with-others turn
    becomes a quiet like-reaction instead of full silence). Each falls back to the
    conservative dataclass default — so Bob almost never intrudes into a private 1:1.
    """
    section = _section(config, "addressivity")
    defaults = AddressivityThresholds()
    return AddressivityThresholds(
        barge_in_interest=_float_or(
            section, "barge_in_interest", defaults.barge_in_interest
        ),
        ambient_interest=_float_or(
            section, "ambient_interest", defaults.ambient_interest
        ),
        barge_in_freq=_float_or(section, "barge_in_freq", defaults.barge_in_freq),
        ambient_barge_in_freq=_float_or(
            section, "ambient_barge_in_freq", defaults.ambient_barge_in_freq
        ),
        react_chance=_float_or(section, "react_chance", defaults.react_chance),
    )


def _build_brevity_thresholds(config: Mapping[str, object]) -> BrevityThresholds:
    """Build the BOB-024 brevity verbosity thresholds from ``brevity.thresholds.*``.

    Tunes the verbosity decision: ``interest_upgrade`` (the high interest bar that can
    rarely upgrade a turn's length) at ``upgrade_freq`` (the small seeded chance);
    ``bad_mood`` / ``low_engagement`` (the mood/appetite points that pull length a step
    down); ``tilt_mood`` (the soft-mood point where a terse form_hint adds a downshift).
    Each falls back to the conservative dataclass default — so Bob rarely unfurls "from
    interest" and trims only on a clearly bad mood / thin appetite.
    """
    section = _section(_section(config, "brevity"), "thresholds")
    defaults = BrevityThresholds()
    return BrevityThresholds(
        interest_upgrade=_float_or(
            section, "interest_upgrade", defaults.interest_upgrade
        ),
        upgrade_freq=_float_or(section, "upgrade_freq", defaults.upgrade_freq),
        bad_mood=_float_or(section, "bad_mood", defaults.bad_mood),
        low_engagement=_float_or(section, "low_engagement", defaults.low_engagement),
        tilt_mood=_float_or(section, "tilt_mood", defaults.tilt_mood),
    )


def _build_recent_turns(config: Mapping[str, object]) -> int:
    """Build the BOB-044 recent-history replay window from ``dialogue.recent_turns``.

    How many recent conversation turns HandleMessage replays into the reply context so
    Bob holds the dialogue thread. Falls back to the widened default (14) when the key
    is absent or an invalid type. A non-positive value is rejected here rather than
    silently wiring a window that replays nothing — coherence depends on a real window.
    This is the conversation-replay window only, independent of the anti-repeat
    ``repeat.*`` windows (BOB-026/036) and the wide tic-guard ``repeat.tic_lookback``.
    """
    section = _section(config, "dialogue")
    recent_turns = _int(section, "recent_turns", _DEFAULT_RECENT_TURNS)
    if recent_turns <= 0:
        msg = f"dialogue.recent_turns must be positive, got {recent_turns}"
        raise ValueError(msg)
    return recent_turns


def _build_absence_hint_hours(config: Mapping[str, object]) -> float:
    """Build the BOB-045 .3 long-gap absence threshold from ``dialogue.absence_hint_hours``.

    The pause (in hours) a per-person thread must EXCEED before Bob's compose context
    gains a light "haven't seen you in a while" hint so he notices the gap humanly
    (applies to owner and guest alike). Falls back to the conservative default (~8h)
    when the key is absent or an invalid type. ``0`` is valid and DISABLES the hint;
    a negative value is rejected (a misconfiguration, not a silent disable).
    """
    section = _section(config, "dialogue")
    hours = _float_or(section, "absence_hint_hours", _DEFAULT_ABSENCE_HINT_HOURS)
    if hours < 0:
        msg = f"dialogue.absence_hint_hours must be non-negative, got {hours}"
        raise ValueError(msg)
    return hours


def _build_acknowledge_reaction_freq(config: Mapping[str, object]) -> float:
    """Resolve the BOB-050 .3 being-received acknowledgment frequency from config.

    Reads ``dialogue.acknowledge_reaction_freq`` — how often Bob OCCASIONALLY mentions a
    notable recent reaction to one of his messages (only to the person who reacted). Falls
    back to the small not-needy default when absent. HandleMessage validates the value is a
    [0, 1] probability; ``0`` disables the acknowledgment.
    """
    section = _section(config, "dialogue")
    return _float_or(section, "acknowledge_reaction_freq", _ACKNOWLEDGE_REACTION_FREQ)


def _build_repeat_thresholds(config: Mapping[str, object]) -> RepeatThresholds:
    """Build the BOB-026 .1 anti-repeat window thresholds from ``repeat.*``.

    Tunes the own-reply guard: ``window`` (how many of Bob's recent replies the fresh
    reply is compared against — not just the last, so a repeat "через ход" is caught)
    and ``similarity_threshold`` (the conservative near-verbatim bar, so a merely
    topically-similar but substantively different reply never false-fires a needless
    regeneration). BOB-036 .1 adds the phrase-tic knobs ``tic_min_words`` (the minimum
    notable-phrase length, so short closers never trip) and ``tic_min_occurrences`` (how
    many recent replies a phrase must recur in to be a tic). BOB-043 adds ``tic_lookback``
    (the WIDE window of Bob's recent closers the phrase-tic detector scans, so a SCATTERED
    tic the narrow per-turn view misses is still caught). BOB-061 .1 adds
    ``motif_similarity_threshold`` (the CONSERVATIVE near-verbatim bar for clustering
    closer MOTIF variants, so «мне/ему так спокойнее» count as one motif without sticking
    distinct closers together). BOB-078 C adds ``dup_min_words`` (the minimum reply length
    for the WIDE own-reply self-dup guard, so a legit SHORT repeat «да»/«ок» is never
    suppressed while a content-ful copied reply is). Each falls back to the conservative
    dataclass default.
    """
    section = _section(config, "repeat")
    defaults = RepeatThresholds()
    return RepeatThresholds(
        window=_int(section, "window", defaults.window),
        similarity_threshold=_float_or(
            section, "similarity_threshold", defaults.similarity_threshold
        ),
        tic_min_words=_int(section, "tic_min_words", defaults.tic_min_words),
        tic_min_occurrences=_int(
            section, "tic_min_occurrences", defaults.tic_min_occurrences
        ),
        tic_lookback=_int(section, "tic_lookback", defaults.tic_lookback),
        motif_similarity_threshold=_float_or(
            section, "motif_similarity_threshold", defaults.motif_similarity_threshold
        ),
        dup_min_words=_int(section, "dup_min_words", defaults.dup_min_words),
    )


def _build_floor_enabled(config: Mapping[str, object]) -> bool:
    """Whether the BOB-025 conversation floor is on (``addressivity.floor.enabled``).

    On by default (the floor is the BOB-025 mechanism); when off, no floor store is
    wired and the effective addressivity is the per-message classification, so
    behaviour is exactly BOB-023. Tolerates an env-string ``"true"``/``"false"``.
    """
    section = _section(_section(config, "addressivity"), "floor")
    value = section.get("enabled", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _build_floor_config(config: Mapping[str, object]) -> FloorConfig:
    """Build the BOB-025 conversation-floor config from ``addressivity.floor.*``.

    Tunes the floor's life and decay: ``timeout_seconds`` (how long Bob's floor lives
    without re-confirmation — ~5 min) and ``reset_after_silent`` (how many silent
    ambient turns collapse Bob's floor to idle). Each falls back to the conservative
    dataclass default; the domain validates both are positive.
    """
    section = _section(_section(config, "addressivity"), "floor")
    defaults = FloorConfig()
    return FloorConfig(
        timeout_seconds=_int(section, "timeout_seconds", defaults.timeout_seconds),
        reset_after_silent=_int(
            section, "reset_after_silent", defaults.reset_after_silent
        ),
    )


def _build_require_plan_approval(config: Mapping[str, object]) -> bool:
    """Whether the Goal Engine DOUBLE gate is on (``goals.require_plan_approval``).

    Default ``True`` (conservative at the start of autonomy): after the owner
    approves a goal, the decomposed plan must ALSO be approved before the goal goes
    ACTIVE. Only an explicit falsy value (``false``/``0``/``no``/``off``) drops to
    the single-gate flow. Tolerates an env-string boolean.
    """
    section = _section(config, "goals")
    value = section.get("require_plan_approval", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return True


def _build_length_guard_enabled(config: Mapping[str, object]) -> bool:
    """Whether the BOB-024 brevity length guard is on (``brevity.length_guard.enabled``).

    Off by default (the bayes — directive + few-shot — is the mechanism); when on, an
    over-long reply to a LOW-demand message is lightly clamped to its first finished
    thought (no regeneration). Tolerates an env-string ``"true"``/``"false"``.
    """
    section = _section(_section(config, "brevity"), "length_guard")
    return _flag(section, "enabled")


def _build_origin_provenance(config: Mapping[str, object]) -> bool:
    """Whether Bob SEES where recalled material was said (``memory.origin_provenance``).

    OFF by default (BOB-090.C1): the composed system prompt stays byte-identical, and Bob
    keeps guessing the place as before. ON → the «где это было» line is folded in, built
    from the ``visibility`` the write side already stamps from the channel, so he can say
    «это мы обсуждали в личке» instead of inventing a room. A missing/empty section and an
    explicit falsy value are all OFF; tolerates an env-string boolean.
    """
    return _flag(_section(config, "memory"), "origin_provenance")


def _build_length_guard_max_chars(config: Mapping[str, object]) -> int:
    """The BOB-024 length-guard char ceiling (``brevity.length_guard.max_chars``).

    The threshold above which a LOW-demand reply is clamped to its first finished
    thought when the guard is enabled. Falls back to the conservative default;
    HandleMessage validates it is positive.
    """
    section = _section(_section(config, "brevity"), "length_guard")
    return _int(section, "max_chars", _DEFAULT_LENGTH_GUARD_MAX_CHARS)


def _build_fatigue_rates(config: Mapping[str, object]) -> FatigueRates:
    """Build the BOB-014 .2a conversational-fatigue dynamics from ``engagement.fatigue.*``.

    Tunes the bounded reservoir: ``decay_per_second`` (the recovery guarantee — fatigue
    always unwinds with time, so the owner is never permanently locked out),
    ``aimless_rise`` (how much one aimless turn tires Bob) and ``interest_ease`` (how much
    an interesting turn restores). Each falls back to the dataclass default.
    """
    section = _section(_section(config, "engagement"), "fatigue")
    defaults = FatigueRates()
    return FatigueRates(
        decay_per_second=_float_or(section, "decay_per_second", defaults.decay_per_second),
        aimless_rise=_float_or(section, "aimless_rise", defaults.aimless_rise),
        interest_ease=_float_or(section, "interest_ease", defaults.interest_ease),
    )


def _build_engagement_mood_lift(config: Mapping[str, object]) -> float:
    """Resolve the BOB-014 .2a good-exchange mood lift from ``engagement.mood_lift``.

    The small mood-valence bump a good, interesting exchange earns (scenario 4's
    feedback). Falls back to the small default; HandleMessage validates it is a [0, 1]
    amount.
    """
    section = _section(config, "engagement")
    return _float_or(section, "mood_lift", _DEFAULT_ENGAGEMENT_MOOD_LIFT)


def _build_surface_old_freq(config: Mapping[str, object]) -> float:
    """Resolve the BOB-021 surface-old frequency from config (small default).

    Reads ``memory.surface_old.freq`` — how often a (rare) callback turn reaches for
    an OLD-but-relevant memory via recall's additive opt-in ("что-то напомнило").
    Falls back to the small anti-tic default when absent; the default recall path is
    unchanged regardless (surface_old only ever rides the callback). HandleMessage
    validates the value is a [0, 1] probability.
    """
    section = _section(_section(config, "memory"), "surface_old")
    return _float_or(section, "freq", _SURFACE_OLD_FREQ)


def _build_pursuit_enabled(config: Mapping[str, object]) -> bool:
    """Whether the self-directed goal-pursuit tick is wired (``goals.pursuit_enabled``).

    Off by default — the conservative start of autonomy-execution: the tick is the
    most safety-critical path, so it is scheduled ONLY when the owner explicitly
    switches it on. Tolerates an env-string boolean.
    """
    return _flag(_section(config, "goals"), "pursuit_enabled")


def _build_safe_capabilities(config: Mapping[str, object]) -> tuple[str, ...]:
    """The autonomous safe-allowlist (``goals.safe_capabilities``) as capability names.

    Only these capability names are runnable on the self-directed path; anything
    else (external-agency / arbitrary) is unreachable. An absent or empty list means
    the tick runs no capability at all (the conservative default).
    """
    section = _section(config, "goals")
    raw = section.get("safe_capabilities", [])
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(name) for name in raw if isinstance(name, str) and name)


def _build_max_tasks_per_window(config: Mapping[str, object]) -> int:
    """The per-window autonomous-advance ceiling (``goals.max_tasks_per_window``).

    A rate-limit ON TOP of the governance per-window ceiling — at most this many
    goal advances per window. Falls back to a conservative ``1`` when unset.
    """
    return _int(_section(config, "goals"), "max_tasks_per_window", 1)


def _build_pursuit_tick_seconds(config: Mapping[str, object]) -> float:
    """The self-directed pursuit cadence (``goals.tick_seconds``), in seconds.

    A rare cadence (the default is 900s ≈ 15 min) under the governance ceiling.
    Falls back to that conservative default when unset.
    """
    return float(_int(_section(config, "goals"), "tick_seconds", _DEFAULT_PURSUIT_TICK_SECONDS))


def _build_self_improvement_enabled(config: Mapping[str, object]) -> bool:
    """Whether self-improvement is wired (``self_improvement.enabled``, OFF default).

    The master switch: OFF (the conservative start of metacognition) → the whole feature
    is unwired, so behaviour is exactly as before BOB-028. Tolerates an env-string bool.
    """
    return _flag(_section(config, "self_improvement"), "enabled")


def _build_introspection_enabled(config: Mapping[str, object]) -> bool:
    """Whether read-only self-introspection is wired (``introspection.enabled``).

    Default ON (BOB-017 Phase A — read-only, owner-only chat): on → the three
    self-introspection skills are advertised; off → the registry holds only the
    memory capabilities, exactly as before. Tolerates an env-string boolean.
    """
    return _flag(_section(config, "introspection"), "enabled")


def _build_dev_tools_enabled(config: Mapping[str, object]) -> bool:
    """Whether the dev-introspection tools are wired (``introspection.dev_tools``).

    Default OFF (BOB-081 — the git-history + tracker read tools ship as one gated
    piece): off → the four ``recent_commits`` / ``list_tasks`` / ``show_task`` /
    ``task_comments`` skills are NOT registered (Bob never sees them, zero behaviour
    change); on → they are advertised alongside the other introspection skills. It is
    a SUB-flag under the (default-ON) ``introspection.enabled`` master. Tolerates an
    env-string boolean.
    """
    return _flag(_section(config, "introspection"), "dev_tools")


def _build_architecture_tools_enabled(config: Mapping[str, object]) -> bool:
    """Whether the architecture tools are wired (``introspection.architecture_tools``).

    Default OFF (BOB-091 — the diagram + impact reads ship as one gated piece, switched
    on after the live smoke): off → ``draw_architecture`` / ``architecture_impact`` are
    NOT registered (Bob never sees them, zero behaviour change); on → they are advertised
    alongside the other introspection skills. A SUB-flag under the (default-ON)
    ``introspection.enabled`` master, independent of ``dev_tools``. Tolerates an
    env-string boolean.
    """
    return _flag(_section(config, "introspection"), "architecture_tools")


def _diagram_send_as(config: Mapping[str, object]) -> DiagramSendMode:
    """Resolve the diagram send mode from ``diagrams.send_as`` (BOB-037 C).

    ``document`` (the default) sends the PNG UNCOMPRESSED at full resolution; ``photo``
    sends the recompressed inline-preview photo. Any other value falls back to the
    ``document`` default, so a typo can never crash the boot.
    """
    raw = _str(_section(config, "diagrams"), "send_as", _DEFAULT_DIAGRAM_SEND_AS)
    return "photo" if raw == "photo" else "document"
