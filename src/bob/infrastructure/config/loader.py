# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""ConfigLoader — layered configuration: defaults -> YAML file -> environment.

Precedence (lowest to highest): built-in :data:`DEFAULT_CONFIG`, an optional YAML
file (``yaml.safe_load``), then environment variables. Env vars use the prefix
``BOB_`` and ``__`` to denote nesting, e.g. ``BOB_LLM__TIER1_MODEL`` maps to
``config["llm"]["tier1_model"]``. Later layers deep-merge over earlier ones.
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

# Built-in defaults — the safe baseline the runtime boots from with no YAML/env.
DEFAULT_CONFIG: Config = {
    "runtime": {
        "log_level": "INFO",
        "heartbeat_seconds": 30,
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
    },
    "telegram": {
        "poll_timeout": 10,
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
            if not key.startswith(_ENV_PREFIX):
                continue
            path = key[len(_ENV_PREFIX) :].lower().split(_ENV_NESTING_SEPARATOR)
            _assign_nested(overrides, path, value)
        return overrides


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
