# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Factory building the :class:`bob.domain.ports.Embedder` from configuration.

Reads the ``embeddings`` section of the merged config (defaults -> YAML -> env,
see :mod:`bob.infrastructure.config.loader`) and constructs an
:class:`bob.infrastructure.llm.ollama_embedder.OllamaEmbedder`. The section is
provider-agnostic (``base_url`` / ``model`` / ``dim``), so pointing the embedder
at a different local model is a config change, not a rewrite.
"""

from __future__ import annotations

from collections.abc import Mapping

from bob.infrastructure.llm.ollama_embedder import OllamaEmbedder


def build_embedder(config: Mapping[str, object]) -> OllamaEmbedder:
    """Build an :class:`OllamaEmbedder` from ``config['embeddings']``."""
    embeddings = config.get("embeddings")
    if not isinstance(embeddings, Mapping):
        raise KeyError("config is missing the 'embeddings' section")
    return OllamaEmbedder(
        base_url=_require_str(embeddings, "base_url"),
        model=_require_str(embeddings, "model"),
        dim=_require_int(embeddings, "dim"),
    )


def _require_str(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise KeyError(f"embeddings.{key} is required and must be a non-empty string")
    return value


def _require_int(section: Mapping[str, object], key: str) -> int:
    """Read an integer setting, tolerating env-string values (e.g. ``"1024"``)."""
    value = section.get(key)
    if isinstance(value, bool):
        raise KeyError(f"embeddings.{key} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise KeyError(f"embeddings.{key} must be an integer") from exc
    raise KeyError(f"embeddings.{key} is required and must be an integer")
