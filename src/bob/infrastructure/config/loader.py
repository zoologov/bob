# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ConfigLoader — layered configuration: defaults -> YAML file -> environment.

Precedence (lowest to highest): built-in :data:`DEFAULT_CONFIG`, an optional YAML
file (``yaml.safe_load``), then environment variables. Env vars use the prefix
``BOB_`` and ``__`` to denote nesting, e.g. ``BOB_LLM__TIER1_MODEL`` maps to
``config["llm"]["tier1_model"]``. Later layers deep-merge over earlier ones.

Two-bot tokens are special-cased because they don't follow the nesting rule
one-to-one: the bot tokens live under ``telegram.bob.token`` /
``telegram.guppi.token`` but are fed by the flat env vars ``BOB_TELEGRAM__TOKEN``
(the historical name) and ``GUPPI_TELEGRAM__TOKEN`` (a non-standard prefix the
generic ``BOB_`` mechanism cannot pick up). :data:`_TOKEN_ENV_MAPPING` maps each
env var to its explicit nested path; these are applied last so env still wins.
"""

from __future__ import annotations

import copy
import logging
import os
from collections.abc import Mapping, MutableMapping
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# A nested configuration tree (string keys; values are scalars or sub-mappings).
type Config = dict[str, Any]

_ENV_PREFIX = "BOB_"
_ENV_NESTING_SEPARATOR = "__"

# Explicit env-var -> nested config path mapping for the two bot tokens. The
# generic BOB_ nesting cannot express either: BOB_TELEGRAM__TOKEN would land at
# telegram.token (not telegram.bob.token), and GUPPI_TELEGRAM__TOKEN does not
# carry the BOB_ prefix at all. Applied after the generic env layer so env wins.
_TOKEN_ENV_MAPPING: dict[str, tuple[str, ...]] = {
    "BOB_TELEGRAM__TOKEN": ("telegram", "bob", "token"),
    "GUPPI_TELEGRAM__TOKEN": ("telegram", "guppi", "token"),
}

# Built-in defaults — the safe baseline the runtime boots from with no YAML/env.
DEFAULT_CONFIG: Config = {
    "runtime": {
        "log_level": "INFO",
        "heartbeat_seconds": 30,
        # The persona's language for self-generated text (proactive compose, the
        # Tier-0 gate, the inner-monologue / reflection ticks) — these have no user
        # message to mirror, so without this constraint the model drifts to English
        # (BOB-012). Default Russian; a Bobiverse replica can override by config.
        "language": "ru",
    },
    "llm": {
        "tier0_model": "qwen2.5:0.5b",
        "tier1_model": "qwen2.5:7b",
        # Generous timeout for slow Tier 1 reasoning replies (seconds).
        "timeout_seconds": 180,
        # Replies don't need chain-of-thought: disabling it cuts cost/latency and
        # avoids the empty-content case where a reasoning model spends its whole
        # budget on reasoning_content.
        "disable_thinking": True,
        # Sampling temperature per tier (BOB-022): without it Qwen MaaS decodes
        # greedily, so an identical prompt returns byte-identical text (the
        # verbatim-repeat bug). Tier 0 (classification/sentiment/summary) runs
        # steadier; Tier 1 (user-facing replies/monologue) runs more varied for
        # natural variation. The factory threads these into each provider.
        "tier0_temperature": 0.5,
        "tier1_temperature": 0.8,
    },
    # Local semantic-memory embeddings (BOB-011). Provider-agnostic: a LOCAL
    # Ollama server (privacy — memory content never leaves the machine), default
    # model BGE-M3 (dense, 1024-dim, multilingual/Russian). Swap ``model``/``dim``
    # (e.g. Qwen3-Embedding) without touching consumers.
    "embeddings": {
        "base_url": "http://localhost:11434",
        "model": "bge-m3",
        "dim": 1024,
    },
    # Local reranker (BOB-011 BEAD-04) — an ADDITIVE quality boost on top of the
    # hybrid recall: re-scores the top-K pool and trims to top_n. Off by default
    # (``enabled`` false): wiring it in is BEAD-06's job. Ollama exposes no native
    # rerank endpoint (Q1), so the adapter scores via a LOCAL model over the
    # OpenAI-compatible chat API — memory content never leaves the machine. Swap
    # ``model`` (e.g. a Qwen3-Reranker / bge-reranker-v2-m3 GGUF) via config.
    "reranker": {
        "enabled": False,
        "base_url": "http://localhost:11434",
        "model": "bge-reranker-v2-m3",
        # top-K candidates from RRF in, top-N reranked out (Q4: ~20-50 -> ~5-8).
        "top_n": 8,
    },
    # Spontaneous expression (BOB-018): per turn a pure ExpressionPlan picks how
    # Bob expresses himself (full reply vs. a terse react-only ack + rare add-on
    # flags + a soft form hint), deterministically from mood + a seeded RNG. The
    # add-on flags fire on a small, configurable fraction of turns (anti-tic):
    # ``leak_inner_life`` surfaces a real recent reflection, ``callback`` a real
    # past moment. Defaults are deliberately small; tune per persona. The seed
    # reuses the proactivity seed (``runtime.proactivity_seed``) so one knob makes
    # all of Bob's stochastic behaviour reproducible in tests.
    "expression": {
        "freqs": {
            "leak_inner_life": 0.12,
            "callback": 0.1,
            # How often Bob surfaces his CURRENT fascination à propos (BOB-020). Small
            # (anti-tic); no fascination → the compose no-ops regardless.
            "mention_fascination": 0.1,
        },
    },
    # Emotional depth (BOB-020). ``offday`` is the mood floor below which Bob's tone
    # goes quieter/vulnerable/honest. ``fascination`` tunes his evolving current
    # passion: ``initial_intensity`` is how vivid a freshly-picked fascination starts
    # (it then decays with age); ``mention_freq`` mirrors the expression flag above so
    # surfacing stays a single configurable knob.
    "emotion": {
        "fascination": {
            "initial_intensity": 0.85,
            "mention_freq": 0.1,
        },
    },
    # Conversational appetite (BOB-014 .2a): Bob's appetite to converse is a LEVEL
    # (full / playful / terse / decline) decided per turn from mood x topic interest x
    # conversational fatigue x relationship. ``thresholds`` tune the appetite boundaries
    # (``interesting`` interest bar, ``high_fatigue`` "наскучило" point, ``low_mood`` /
    # ``bright_mood`` mood bands, ``playful_chance`` banter probability); ``fatigue`` tunes
    # the bounded reservoir's dynamics (``decay_per_second`` — the recovery guarantee,
    # ``aimless_rise``, ``interest_ease``); ``mood_lift`` is the small valence bump a good,
    # interesting exchange earns. Defaults keep a normal mood fully engaging on any
    # non-trivial topic and guarantee fatigue always recovers (no permanent lock-out).
    "engagement": {
        "thresholds": {
            "interesting": 0.5,
            "high_fatigue": 0.7,
            "low_mood": -0.3,
            "bright_mood": 0.3,
            "playful_chance": 0.6,
        },
        "fatigue": {
            "decay_per_second": 1.0 / 3600.0,
            "aimless_rise": 0.15,
            "interest_ease": 0.25,
        },
        "mood_lift": 0.1,
    },
    # Addressivity policy (BOB-023): Bob perceives WHO a message is for — him, another
    # participant, or no one — and decides engage / quietly like-react / stay SILENT, so
    # he no longer barges into every group exchange. Conservative defaults: he almost
    # never cuts into someone else's exchange. ``barge_in_interest`` is the HIGH interest
    # bar to RARELY join a message aimed at another (at ``barge_in_freq`` frequency);
    # ``ambient_interest`` is the lower bar to join a general ambient turn with others
    # around (at ``ambient_barge_in_freq``, easier); ``react_chance`` is how often an
    # ambient-with-others turn becomes a quiet like-reaction instead of full silence.
    "addressivity": {
        "barge_in_interest": 0.8,
        "ambient_interest": 0.6,
        "barge_in_freq": 0.05,
        "ambient_barge_in_freq": 0.15,
        "react_chance": 0.3,
    },
    # Memory consolidation (BOB-021): a rare, non-destructive reflect-tick step that
    # folds OLD un-consolidated episodes into a Tier-0 digest (embedded, recalled like
    # any episode) and flags the sources. Conservative defaults: only episodes at least
    # two weeks old are eligible, a modest batch per tick. ``enabled`` false keeps the
    # step inert until deliberately switched on per persona.
    "memory": {
        "consolidation": {
            "enabled": False,
            "max_age_days": 14.0,
            "batch_size": 50,
        },
        # Fact dedup (BOB-021): a rare, conservative, non-destructive reflect-tick step
        # that merges near-duplicate semantic facts (cosine of embeddings above a high
        # threshold) into a canonical one, flagging the rest superseded (excluded from
        # recall, never deleted). ``threshold`` is deliberately high so dissimilar facts
        # are never merged; ``enabled`` false keeps the step inert until switched on. It
        # needs an embedder — with keyword-only memory the step is a no-op.
        "dedup": {
            "enabled": False,
            "threshold": 0.92,
            "batch_size": 200,
        },
        # Surface-old (BOB-021 mechanism 1, "что-то напомнило"): on a (rare) BOB-018
        # callback turn, Bob occasionally reaches for an OLD-but-relevant memory via
        # recall's additive ``surface_old`` opt-in, so a deep cut can come back à propos.
        # ``freq`` is how often a callback asks for the old blend — small (anti-tic), and
        # it rides ONLY the callback path. The default recall is unchanged (drop-in); a
        # callback with no old-but-relevant hit is a clean no-op (Bob never confabulates).
        "surface_old": {
            "freq": 0.15,
        },
    },
    # Two bots in one process (BOB-003): Bob lives in his topic, GUPPI is the
    # gatekeeper in General. Each bot's token comes from env only (never YAML);
    # the shared ids (chat/owner/allowlist) and Bob's topic are non-secret.
    "telegram": {
        "poll_timeout": 10,
        "chat_id": 0,
        "owner_id": 0,
        "allowed_chat_ids": [],
        "bob": {
            "token": "",
            "topic_id": 0,
        },
        "guppi": {
            "token": "",
        },
    },
}


class ConfigLoader:
    """Build the effective configuration from defaults, an optional YAML, env."""

    def __init__(
        self,
        *,
        yaml_path: Path | None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._yaml_path = yaml_path
        self._env = dict(env) if env is not None else dict(os.environ)

    def load(self) -> Config:
        """Return the merged configuration (defaults <- YAML <- env)."""
        config: Config = copy.deepcopy(DEFAULT_CONFIG)
        _deep_merge(config, self._load_yaml())
        _deep_merge(config, self._load_env())
        self._apply_token_mapping(config)
        return config

    def _load_yaml(self) -> Config:
        if self._yaml_path is None or not self._yaml_path.is_file():
            return {}
        raw = yaml.safe_load(self._yaml_path.read_text(encoding="utf-8"))
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise ValueError(f"config YAML root must be a mapping, got {type(raw).__name__}")
        return dict(raw)

    def _load_env(self) -> Config:
        overrides: Config = {}
        for key, value in self._env.items():
            # The explicitly mapped bot tokens are applied separately (with their
            # own nested path); skip them so the generic rule doesn't misplace one.
            if key in _TOKEN_ENV_MAPPING or not key.startswith(_ENV_PREFIX):
                continue
            path = key[len(_ENV_PREFIX) :].lower().split(_ENV_NESTING_SEPARATOR)
            _assign_nested(overrides, path, value)
        return overrides

    def _apply_token_mapping(self, config: Config) -> None:
        """Overlay the two bot tokens from their explicit env vars (env wins)."""
        for env_var, path in _TOKEN_ENV_MAPPING.items():
            value = self._env.get(env_var)
            if value is not None:
                _assign_nested(config, list(path), value)


def _deep_merge(base: MutableMapping[str, Any], overlay: Mapping[str, Any]) -> None:
    """Recursively merge ``overlay`` into ``base`` in place."""
    for key, value in overlay.items():
        existing = base.get(key)
        if isinstance(existing, MutableMapping) and isinstance(value, Mapping):
            _deep_merge(existing, value)
        else:
            base[key] = value


def _assign_nested(target: Config, path: list[str], value: str) -> None:
    """Assign ``value`` into ``target`` at the nested ``path`` of keys."""
    cursor: MutableMapping[str, Any] = target
    for segment in path[:-1]:
        nxt = cursor.get(segment)
        if not isinstance(nxt, MutableMapping):
            nxt = {}
            cursor[segment] = nxt
        cursor = nxt
    cursor[path[-1]] = value
