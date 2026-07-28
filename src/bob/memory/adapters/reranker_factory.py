# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=memory
# beadloom:layer=infrastructure

"""Factory building the optional :class:`bob.memory.ports.Reranker` from config.

Reads the ``reranker`` section of the merged config (defaults -> YAML -> env, see
:mod:`bob.infrastructure.config.loader`) and constructs an
:class:`bob.memory.adapters.ollama_reranker.OllamaReranker` — *unless* the
reranker is disabled (``reranker.enabled`` false) or the section is absent, in
which case it returns ``None`` so the recall pipeline simply skips reranking.

The reranker is an ADDITIVE quality boost, never a hard dependency: returning
``None`` here is the supported "off" state (the hybrid order ships unchanged), so
the factory never raises just because reranking is turned off.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.memory.adapters.ollama_reranker import OllamaReranker


def build_reranker(config: Mapping[str, object]) -> OllamaReranker | None:
    """Build an :class:`OllamaReranker` from ``config['reranker']``, or ``None``.

    Returns ``None`` when the ``reranker`` section is absent or ``enabled`` is
    false — the additive "no reranking" state, not an error.
    """
    section = config.get("reranker")
    if not isinstance(section, Mapping):
        return None
    if not _enabled(section):
        return None
    return OllamaReranker(
        base_url=_require_str(section, "base_url"),
        model=_require_str(section, "model"),
        top_n=_require_int(section, "top_n"),
    )


def _enabled(section: Mapping[str, object]) -> bool:
    """Whether reranking is turned on (tolerating env-string ``"true"``/``"false"``)."""
    value = section.get("enabled", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _require_str(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise KeyError(f"reranker.{key} is required and must be a non-empty string")
    return value


def _require_int(section: Mapping[str, object], key: str) -> int:
    """Read an integer setting, tolerating env-string values (e.g. ``"8"``)."""
    value = section.get(key)
    if isinstance(value, bool):
        raise KeyError(f"reranker.{key} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise KeyError(f"reranker.{key} must be an integer") from exc
    raise KeyError(f"reranker.{key} is required and must be an integer")
