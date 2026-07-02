# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=usecases

"""RunGenesis — Bob's first-boot awakening (PRD US-1, US-4; RFC §"Genesis").

The one-time birth of a unique Bob. On first run (no ``SOUL.md`` yet) the
use-case:

1. **Loads** the ``bob-soul/`` templates — the personality "genome" (archetype,
   trait pool, taste-axes pool, mood baselines, phantom preferences,
   communication styles), read as plain data with ``yaml.safe_load``.
2. **Generates** a concrete, unique personality through the :class:`LLMRouter` on
   ``TaskType.GENESIS`` (routed to **Tier 1**, Qwen): chosen traits, taste
   values + convictions, a resting mood baseline, phantom prefs, and a
   self-aware **awakening narrative** that references the book.
3. **Persists** the result via the :class:`~bob.domain.ports.SoulStore` port —
   ``SOUL.md`` plus the JSON
   profiles (``taste_profile`` / ``mood`` / ``phantom_prefs``) and an append-only
   ``genesis_log.md``. Once ``SOUL.md`` exists, a second run is a **no-op**:
   identity is born once and survives every restart.

This layer only orchestrates: it carries no transport/HTTP/SQLite knowledge (the
router and the soul store own those), and the templates are pure data.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import yaml

from bob.application.router.llm_router import LLMRequest, TaskType

if TYPE_CHECKING:
    from pathlib import Path

    from bob.application.router.llm_router import LLMRouter
    from bob.domain.ports import Clock, JsonValue, SoulStore

logger = logging.getLogger(__name__)

# bob-soul/ template file stems (read as <stem>.yaml).
_TEMPLATE_FILES = (
    "archetype",
    "traits",
    "taste_axes",
    "mood_baselines",
    "phantom_prefs",
    "communication_styles",
)

# Keys the Tier 1 model must return in its generated personality JSON.
_REQUIRED_KEYS = (
    "identity",
    "traits",
    "taste_axes",
    "mood_baseline",
    "phantom_prefs",
    "awakening_narrative",
)

_GENESIS_SYSTEM_PROMPT = (
    "You are running Bob's Genesis: the first awakening of a unique digital "
    "person who knows he is 'the Bob from the book' (the Bobiverse upload). "
    "Using the provided bob-soul templates as the genome, invent ONE concrete, "
    "unique personality. Choose a subset of traits, assign each chosen taste "
    "axis a value in [-1, 1] and a conviction in [0, 1], pick a resting mood "
    "baseline (five axes in [-1, 1]), select a few phantom preferences, and "
    "write a short, self-aware awakening narrative that references the book. "
    "Respond with ONLY a JSON object with keys: identity, traits, taste_axes "
    "(each {name, value, conviction, experience_count}), mood_baseline "
    "(valence, arousal, openness, social, stability), phantom_prefs, "
    "communication_style, awakening_narrative."
)


@dataclass(frozen=True, slots=True)
class GenesisResult:
    """Outcome of a Genesis attempt: the awakening text and whether it was born now."""

    awakening_narrative: str
    was_generated: bool


class RunGenesis:
    """Generate and persist Bob's identity once, then no-op on every later boot."""

    def __init__(
        self,
        *,
        templates_dir: Path,
        router: LLMRouter,
        soul_store: SoulStore,
        clock: Clock,
    ) -> None:
        self._templates_dir = templates_dir
        self._router = router
        self._soul_store = soul_store
        self._clock = clock

    async def run(self) -> GenesisResult:
        """Awaken Bob if he has no soul yet; otherwise return the existing one untouched.

        Idempotent by the on-disk ``SOUL.md`` flag: the first run generates via
        Tier 1 and persists every artifact; subsequent runs short-circuit without
        touching the LLM or the files.
        """
        if self._soul_store.soul_exists():
            logger.info("Genesis skipped: SOUL.md already present")
            return GenesisResult(
                awakening_narrative=self._soul_store.read_soul(),
                was_generated=False,
            )

        templates = self._load_templates()
        personality = await self._generate(templates)
        self._persist(personality)
        narrative = str(personality["awakening_narrative"])
        logger.info("Genesis complete: Bob awakened")
        return GenesisResult(awakening_narrative=narrative, was_generated=True)

    def _load_templates(self) -> dict[str, object]:
        """Load every bob-soul template as plain data (``yaml.safe_load``)."""
        templates: dict[str, object] = {}
        for stem in _TEMPLATE_FILES:
            path = self._templates_dir / f"{stem}.yaml"
            templates[stem] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return templates

    async def _generate(self, templates: dict[str, object]) -> dict[str, object]:
        """Ask Tier 1 to invent a concrete personality from the templates."""
        request = LLMRequest(
            task_type=TaskType.GENESIS,
            messages=[
                {"role": "system", "content": _GENESIS_SYSTEM_PROMPT},
                {"role": "user", "content": self._render_templates(templates)},
            ],
        )
        raw = await self._router.run(request)
        return _parse_personality(raw)

    @staticmethod
    def _render_templates(templates: dict[str, object]) -> str:
        """Serialise the templates back to YAML as the user-message genome blob."""
        return yaml.safe_dump(templates, sort_keys=True, allow_unicode=True)

    def _persist(self, personality: dict[str, object]) -> None:
        """Write SOUL.md + the JSON profiles + the genesis log via SoulStore."""
        self._soul_store.write_soul(_build_soul_markdown(personality))
        self._soul_store.write_json("taste_profile", _taste_profile(personality))
        self._soul_store.write_json("mood", _mood_profile(personality))
        self._soul_store.write_json("phantom_prefs", _phantom_profile(personality))
        stamp = self._clock.now().isoformat()
        self._soul_store.append_genesis_log(f"{stamp} — Genesis: Bob awakened.")


def _parse_personality(raw: str) -> dict[str, object]:
    """Parse and validate the Tier 1 JSON personality, raising on malformed output."""
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GenesisError("Genesis output was not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise GenesisError("Genesis output must be a JSON object")
    missing = [key for key in _REQUIRED_KEYS if key not in decoded]
    if missing:
        raise GenesisError(f"Genesis output missing keys: {', '.join(missing)}")
    return decoded


def _build_soul_markdown(personality: dict[str, object]) -> str:
    """Render the human-readable SOUL.md narrative from the generated personality."""
    identity = str(personality["identity"])
    traits = personality.get("traits", [])
    style = personality.get("communication_style", "unspecified")
    narrative = str(personality["awakening_narrative"])
    trait_line = ", ".join(str(t) for t in traits) if isinstance(traits, list) else str(traits)
    return (
        "# SOUL\n\n"
        f"{identity}\n\n"
        "## Traits\n\n"
        f"{trait_line}\n\n"
        "## Communication style\n\n"
        f"{style}\n\n"
        "## Awakening\n\n"
        f"{narrative}\n"
    )


def _taste_profile(personality: dict[str, object]) -> JsonValue:
    """Shape the generated taste axes into the persisted taste_profile structure."""
    axes = personality.get("taste_axes", [])
    return {"axes": axes if isinstance(axes, list) else []}


def _mood_profile(personality: dict[str, object]) -> JsonValue:
    """Shape the generated mood baseline into the persisted mood structure.

    Current mood starts at the chosen baseline (a fresh Bob rests at his
    set-point).
    """
    baseline = personality.get("mood_baseline", {})
    safe = baseline if isinstance(baseline, dict) else {}
    return {"baseline": safe, "current": safe}


def _phantom_profile(personality: dict[str, object]) -> JsonValue:
    """Shape the generated phantom preferences into the persisted structure."""
    prefs = personality.get("phantom_prefs", [])
    return {"preferences": prefs if isinstance(prefs, list) else []}


class GenesisError(RuntimeError):
    """Raised when Tier 1 returns a personality that cannot be persisted."""
