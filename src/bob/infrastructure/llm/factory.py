# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Factory building the Tier 0 / Tier 1 LLM providers from configuration.

Reads the ``llm`` section of the merged config (defaults -> YAML -> env, see
:mod:`bob.infrastructure.config.loader`) and constructs one
:class:`OpenAICompatProvider` per tier:

* Tier 0 — the local mlx-lm server (keyless by default; an optional
  ``llm.tier0_api_key`` lets Tier 0 point at a keyed/remote endpoint);
* Tier 1 — the Qwen API (bearer key from ``llm.tier1_api_key``, sourced from
  config/env; never inlined).

The result maps tier index -> provider, ready for the
:class:`bob.application.router.LLMRouter`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

if TYPE_CHECKING:
    from bob.domain.ports import LLMProvider

_TIER_LOCAL = 0
_TIER_API = 1


def build_tier_providers(config: Mapping[str, object]) -> dict[int, LLMProvider]:
    """Build ``{0: tier0_provider, 1: tier1_provider}`` from ``config['llm']``."""
    llm = config.get("llm")
    if not isinstance(llm, Mapping):
        raise KeyError("config is missing the 'llm' section")

    tier0 = OpenAICompatProvider(
        base_url=_require_str(llm, "tier0_base_url"),
        model=_require_str(llm, "tier0_model"),
        api_key=_optional_str(llm, "tier0_api_key"),
    )
    tier1 = OpenAICompatProvider(
        base_url=_require_str(llm, "tier1_base_url"),
        model=_require_str(llm, "tier1_model"),
        api_key=_optional_str(llm, "tier1_api_key"),
    )
    return {_TIER_LOCAL: tier0, _TIER_API: tier1}


def _require_str(section: Mapping[str, object], key: str) -> str:
    value = section.get(key)
    if not isinstance(value, str) or not value:
        raise KeyError(f"llm.{key} is required and must be a non-empty string")
    return value


def _optional_str(section: Mapping[str, object], key: str) -> str | None:
    value = section.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise KeyError(f"llm.{key} must be a string when set")
    return value or None
