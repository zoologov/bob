# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root configuration — tuned defaults, repo/data paths, and config readers.

The leaf of the ``bob.runtime`` composition root (BOB-062.7a): the ``_DEFAULT_*`` tunables,
the process constants, the repo/data path resolvers and the small, permissive value-coercion
readers (``_section`` / ``_str`` / ``_str_list`` / ``_int`` / ``_int_list`` / ``_float`` /
``_float_or`` / ``_flag``) that turn the layered YAML/env config into concrete values. It is
``bob.runtime`` (the composition root / entrypoint) — NOT ``bob.application.runtime`` (the
async AgentRuntime/EventBus primitives, which live on unchanged).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from bob.application.runtime import RetryPolicy
from bob.personality.phantom_evolution import CHANGE_RATE as _PHANTOM_RATE
from bob.personality.phantom_evolution import MAX_PHANTOMS as _PHANTOM_MAX
from bob.personality.taste_evolution import ALPHA as _EVOLUTION_ALPHA
from bob.personality.taste_evolution import BETA as _EVOLUTION_BETA

# Default heartbeat cadence and gateway streaming knobs.
_DEFAULT_HEARTBEAT_SECONDS = 30
_DEFAULT_POLL_TIMEOUT = 10
_BATCH_TOKENS = 4
_THROTTLE_INTERVAL = 0.5
_MOOD_DRIFT_SECONDS = 60.0

# Production tick resilience: retry a tick's *transient* LLM/network blips with
# bounded exponential backoff (BEAD-04) before isolating whatever it ultimately
# raises, so a momentary hiccup never silently skips an idle tick.
_TICK_RETRY_POLICY = RetryPolicy()

# The reply tier (Tier 1) is the one whose provider drives the capability tool-loop.
_REPLY_TIER = 1

# Per-persona id for Bob's proactivity state (Bobiverse replicas each get their own).
_BOB_PERSONA = "bob"

# Self-improvement defaults (BOB-028 .3): the soft-tilt ceiling each APPROVED rule's
# magnitude is clamped to, and the cap on how many LIVE rules may accrue. Mirror the
# ``self_improvement.*`` config defaults; only matter when the master switch is on.
_DEFAULT_SI_MAX_MAGNITUDE = 0.3
_DEFAULT_SI_MAX_ACTIVE_RULES = 5

# The tier the pattern detector reasons on (``self_improvement.detector_tier``). 1 =
# the reasoning tier, which is ALSO the ``DETECT_PATTERNS`` task default — so the
# shipped config pins exactly what the router would pick anyway (BOB-096: the key was
# dead until then, and honouring it must not silently move the detector elsewhere).
_DEFAULT_SI_DETECTOR_TIER = 1

# Default vividness of a freshly-grounded fascination (BOB-020); it then decays with
# age. Overridable via ``emotion.fascination.initial_intensity``.
_DEFAULT_FASCINATION_INTENSITY = 0.85

# Default phantom-evolution bound + cadence (BOB-020 wave 3); overridable via
# ``emotion.phantom.{max_count,change_rate}``. Sourced from the pure kernel's constants
# so the domain and composition agree on the conservative defaults.
_PHANTOM_MAX_COUNT = _PHANTOM_MAX
_PHANTOM_CHANGE_RATE = _PHANTOM_RATE

# Default memory-consolidation guardrails (BOB-021); overridable via
# ``memory.consolidation.{max_age_days,batch_size}``. Conservative: only fold
# episodes at least two weeks old, a modest batch per rare reflect tick.
_CONSOLIDATION_MAX_AGE_DAYS = 14.0
_CONSOLIDATION_BATCH_SIZE = 50

# Default fact-dedup guardrails (BOB-021); overridable via
# ``memory.dedup.{threshold,batch_size}``. Conservative: a high cosine threshold so
# only true near-duplicates merge, a bounded batch per rare reflect tick.
_DEDUP_THRESHOLD = 0.92
_DEDUP_BATCH_SIZE = 200

# Default surface-old frequency (BOB-021 mechanism 1); overridable via
# ``memory.surface_old.freq``. Small (anti-tic): a callback turn only occasionally
# reaches for an OLD-but-relevant deep cut; the default recall stays unchanged.
_SURFACE_OLD_FREQ = 0.15

# Default being-received acknowledgment frequency (BOB-050 .3); overridable via
# ``dialogue.acknowledge_reaction_freq``. Small (not needy): Bob only OCCASIONALLY mentions
# that someone warmly reacted to one of his messages, and only to the person who reacted.
_ACKNOWLEDGE_REACTION_FREQ = 0.15

# Default good-exchange mood lift (BOB-014 .2a); overridable via ``engagement.mood_lift``.
# Small: a genuinely interesting, well-engaged exchange brightens Bob a touch — it
# accrues over a real exchange rather than jolting his mood.
_DEFAULT_ENGAGEMENT_MOOD_LIFT = 0.1

# Default char ceiling for the BOB-024 brevity length guard (mirrors HandleMessage's
# default). The guard is off by default; when on, an over-long reply to a LOW-demand
# message is lightly clamped to its first finished thought at this ceiling.
_DEFAULT_LENGTH_GUARD_MAX_CHARS = 280

# Default recent-history replay window (BOB-044; mirrors HandleMessage's default and the
# loader's dialogue.recent_turns default). How many recent conversation turns are
# replayed into the reply context so Bob holds the dialogue thread.
_DEFAULT_RECENT_TURNS = 14

# Default long-gap absence-hint threshold in hours (BOB-045 .3; mirrors the loader's
# dialogue.absence_hint_hours default). When Bob resumes with a person after a pause
# longer than this, a light "haven't seen you in a while" hint enters the compose
# context. ``0`` disables it.
_DEFAULT_ABSENCE_HINT_HOURS = 8.0

# The proactivity engine ticks on the heartbeat cadence: cheap by construction
# (the urge/governance decision is pure, defaulting to silence), so most ticks
# make ZERO LLM calls.
_PROACTIVE_TICK_MULTIPLIER = 1

# Default cadence of the self-directed goal-pursuit tick (BOB-015 .3) when wired:
# rare (≈15 min) and under the governance ceiling; overridable via goals.tick_seconds.
_DEFAULT_PURSUIT_TICK_SECONDS = 900

# Default self-evolution learning rates (BOB-013 Фаза 2); overridable via
# personality.evolution.{alpha,beta}. Sourced from the pure kernel's constants.
EVOLUTION_ALPHA = _EVOLUTION_ALPHA
EVOLUTION_BETA = _EVOLUTION_BETA

# The repo root: ``.../src/bob/runtime/config.py`` -> three parents up
# ([0]=runtime, [1]=bob, [2]=src, [3]=repo root). The read-only tree Bob's
# self-introspection (BOB-017 Phase A) is rooted at, so the PrivacyGuard resolves
# ``src``/``tests``/``docs`` against it and DENIES everything else.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Where the bob-soul personality templates live (repo root / bob-soul).
_DEFAULT_TEMPLATES_DIR = _REPO_ROOT / "bob-soul"

# Default self-introspection resource bounds (BOB-017 Phase A); mirror the
# ``introspection.*`` config defaults. Only consulted when introspection is enabled.
_DEFAULT_INTROSPECTION_MAX_OUTPUT_CHARS = 20_000
_DEFAULT_INTROSPECTION_READ_MAX_LINES = 200

# Default per-render diagram timeout (BOB-035); mirrors the ``diagrams.timeout``
# config default. Only consulted when the render_diagram skill is enabled.
_DEFAULT_DIAGRAM_TIMEOUT_S = 30

# Default diagram render-quality + send-mode (BOB-037); mirror the
# ``diagrams.{scale, background, send_as}`` config defaults. ``scale`` is mmdc's
# deviceScaleFactor (3x → crisp), ``background`` keeps a diagram readable on a dark
# theme, and ``send_as`` defaults to ``document`` (uncompressed, full-resolution).
_DEFAULT_DIAGRAM_SCALE = 3
_DEFAULT_DIAGRAM_BACKGROUND = "white"
_DEFAULT_DIAGRAM_SEND_AS = "document"

# Telegram clears a "typing" action after ~5s, so the coding indicator refreshes a little
# under that so it never lapses during a minute-long claude wait (BOB-046 .2).
_CODING_TYPING_INTERVAL = 4.0


# --- Path readers -------------------------------------------------------------


def _db_path(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "db_path", "data/bob.db"))


def _soul_dir(config: Mapping[str, object]) -> Path:
    return Path(_str(_section(config, "persistence"), "soul_dir", "data/soul"))


def _backfill_name_map(config: Mapping[str, object]) -> dict[str, int]:
    """Owner display name -> owner_id, for the BOB-045 episodic backfill (best-effort).

    Empty when no ``telegram.owner_name`` is configured (or no owner_id) — the
    backfill is then a graceful no-op and legacy NULL-sender rows simply stay
    unattributed.
    """
    telegram = _section(config, "telegram")
    owner_name = _str(telegram, "owner_name", "")
    owner_id = _int(telegram, "owner_id", 0)
    return {owner_name: owner_id} if owner_name and owner_id else {}


def _templates_dir(config: Mapping[str, object]) -> Path:
    genesis = _section(config, "genesis")
    configured = genesis.get("templates_dir")
    if isinstance(configured, str) and configured:
        return Path(configured)
    return _DEFAULT_TEMPLATES_DIR


# --- Config readers -----------------------------------------------------------


def _section(config: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = config.get(key)
    return value if isinstance(value, Mapping) else {}


def _str(section: Mapping[str, object], key: str, default: str) -> str:
    value = section.get(key)
    return value if isinstance(value, str) and value else default


def _int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _int_list(section: Mapping[str, object], key: str) -> tuple[int, ...]:
    """Read a list of ints from config (YAML list or a CSV env string)."""
    value = section.get(key)
    if isinstance(value, str):
        return tuple(int(part) for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(int(item) for item in value if isinstance(item, int))
    return ()


def _str_list(section: Mapping[str, object], key: str) -> tuple[str, ...]:
    """Read a list of strings from config (YAML list or a CSV env string).

    The string twin of :func:`_int_list`: blank and non-string entries are dropped (a
    malformed config degrades to a shorter list instead of crashing the composition
    root), and each kept item is stripped of surrounding whitespace.
    """
    value = section.get(key)
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return ()


def _float(section: Mapping[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _float_or(section: Mapping[str, object], key: str, default: float) -> float:
    """Read a float from config, falling back to ``default`` when absent/invalid."""
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _flag(section: Mapping[str, object], key: str) -> bool:
    """Read a boolean config flag, tolerating env-string ``"true"``/``"false"``."""
    value = section.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False
