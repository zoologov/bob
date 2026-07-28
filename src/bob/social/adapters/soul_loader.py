# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""Soul loader — rebuild the in-memory :class:`SOUL` from the persisted soul artifacts.

Reads the JSON profiles the :class:`~bob.social.adapters.soul_store.SoulStore` writes
(mood / taste / phantom prefs / disposition) into the live :class:`SOUL`, falling back to
a neutral canon default per missing field so a fresh install (before Genesis has fully
written them) and an install predating a later profile Just Work. Extracted verbatim from
the composition root (BOB-062.7a); the tiny JSON value-coercion helpers are private here so
this social adapter never depends on the composition-root ``config`` readers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from bob.personality.disposition import DEFAULT_DISPOSITION, Disposition
from bob.personality.mood import Mood
from bob.personality.soul import SOUL
from bob.personality.taste import TasteAxis, TasteEngine

if TYPE_CHECKING:
    from bob.social.adapters.soul_store import SoulStore


def _load_soul(soul_store: SoulStore) -> SOUL:
    """Build the in-memory :class:`SOUL` from the persisted soul artifacts.

    Falls back to a neutral default if the JSON profiles are absent (a fresh
    install before Genesis has fully written them).
    """
    if not soul_store.soul_exists():
        return _default_soul()
    identity = soul_store.read_soul()
    mood_doc = soul_store.read_json("mood")
    baseline = _mood_from(mood_doc, "baseline")
    current = _mood_from(mood_doc, "current")
    taste = _taste_from(soul_store.read_json("taste_profile"))
    phantoms = _phantoms_from(soul_store.read_json("phantom_prefs"))
    disposition = _disposition_from(soul_store.read_json("disposition"))
    return SOUL(
        identity=identity,
        mood=current,
        mood_baseline=baseline,
        taste=taste,
        phantom_prefs=phantoms,
        disposition=disposition,
    )


def _default_soul() -> SOUL:
    """A neutral starting soul used before Genesis has run."""
    neutral = Mood()
    return SOUL(
        identity="I am Bob, awaiting Genesis.",
        mood=neutral,
        mood_baseline=neutral,
        taste=TasteEngine(),
    )


def _mood_from(doc: object, key: str) -> Mood:
    if not isinstance(doc, Mapping):
        return Mood()
    section = doc.get(key)
    if not isinstance(section, Mapping):
        return Mood()
    return Mood(
        valence=_float(section, "valence"),
        arousal=_float(section, "arousal"),
        openness=_float(section, "openness"),
        social=_float(section, "social"),
        stability=_float(section, "stability"),
    )


def _taste_from(doc: object) -> TasteEngine:
    if not isinstance(doc, Mapping):
        return TasteEngine()
    axes_doc = doc.get("axes")
    if not isinstance(axes_doc, list):
        return TasteEngine()
    axes: list[TasteAxis] = []
    for raw in axes_doc:
        if not isinstance(raw, Mapping):
            continue
        name = raw.get("name")
        if not isinstance(name, str):
            continue
        axes.append(
            TasteAxis(
                name=name,
                value=_float(raw, "value"),
                conviction=_float(raw, "conviction"),
                experience_count=_int(raw, "experience_count", 0),
            )
        )
    return TasteEngine(axes=tuple(axes))


def _phantoms_from(doc: object) -> tuple[str, ...]:
    if not isinstance(doc, Mapping):
        return ()
    prefs = doc.get("preferences")
    if not isinstance(prefs, list):
        return ()
    return tuple(str(p) for p in prefs)


def _disposition_from(doc: object) -> Disposition:
    """Build Bob's :class:`Disposition`, falling back to canon per missing field.

    An absent or malformed ``disposition.json`` (an existing install predating
    BOB-033) yields the canon-optimist default, so every install Just Works.
    """
    if not isinstance(doc, Mapping):
        return DEFAULT_DISPOSITION
    return Disposition(
        optimism=_float_or(doc, "optimism", DEFAULT_DISPOSITION.optimism),
        resilience=_float_or(doc, "resilience", DEFAULT_DISPOSITION.resilience),
    )


# --- Private JSON value coercion (kept local — no dependency on the config readers) ---


def _int(section: Mapping[str, object], key: str, default: int) -> int:
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _float(section: Mapping[str, object], key: str) -> float:
    value = section.get(key)
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _float_or(section: Mapping[str, object], key: str, default: float) -> float:
    """Read a float from the soul JSON, falling back to ``default`` when absent/invalid."""
    value = section.get(key)
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default
