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

from bob.capabilities.adapters.web_search_qwen import QwenWebSearchProvider
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

if TYPE_CHECKING:
    from bob.capabilities.ports import WebSearchProvider
    from bob.kernel.ports import LLMProvider

_TIER_LOCAL = 0
_TIER_API = 1

# Generous default so a slow Tier 1 reasoning model (1000+ reasoning tokens per
# reply) does not time out and spuriously fall back to Tier 0.
_DEFAULT_TIMEOUT_SECONDS = 180.0

# Default Qwen-native search model (verify .1: Responses API returns sources on it).
_DEFAULT_SEARCH_MODEL = "qwen3.7-plus"


def build_tier_providers(config: Mapping[str, object]) -> dict[int, LLMProvider]:
    """Build ``{0: tier0_provider, 1: tier1_provider}`` from ``config['llm']``."""
    llm = config.get("llm")
    if not isinstance(llm, Mapping):
        raise KeyError("config is missing the 'llm' section")

    timeout_seconds = _optional_float(llm, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    disable_thinking = _optional_bool(llm, "disable_thinking", default=False)

    tier0 = OpenAICompatProvider(
        base_url=_require_str(llm, "tier0_base_url"),
        model=_require_str(llm, "tier0_model"),
        api_key=_optional_str(llm, "tier0_api_key"),
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
        temperature=_optional_float_or_none(llm, "tier0_temperature"),
    )
    tier1 = OpenAICompatProvider(
        base_url=_require_str(llm, "tier1_base_url"),
        model=_require_str(llm, "tier1_model"),
        api_key=_optional_str(llm, "tier1_api_key"),
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
        temperature=_optional_float_or_none(llm, "tier1_temperature"),
    )
    return {_TIER_LOCAL: tier0, _TIER_API: tier1}


def build_web_search_provider(config: Mapping[str, object]) -> WebSearchProvider:
    """Build the Qwen-native web-search provider from ``config['search']`` (BOB-053).

    ``search.base_url`` / ``search.api_key`` default to the Tier-1 Qwen MaaS values
    (``llm.tier1_*``) — the same workspace host + ``sk`` key verify .1 proved returns
    sources via the Responses API — so the search section need only flip ``enabled``.
    """
    search = config.get("search")
    if not isinstance(search, Mapping):
        raise KeyError("config is missing the 'search' section")
    llm = config.get("llm")
    llm = llm if isinstance(llm, Mapping) else {}

    base_url = _optional_str(search, "base_url") or _require_str(llm, "tier1_base_url")
    api_key = _optional_str(search, "api_key") or _optional_str(llm, "tier1_api_key")
    model = _optional_str(search, "model") or _DEFAULT_SEARCH_MODEL
    timeout_seconds = _optional_float(search, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)

    return QwenWebSearchProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )


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


def _optional_float(section: Mapping[str, object], key: str, default: float) -> float:
    """Read a numeric setting, tolerating env-string values; fall back to ``default``."""
    value = section.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        raise KeyError(f"llm.{key} must be a number")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise KeyError(f"llm.{key} must be a number") from exc
    raise KeyError(f"llm.{key} must be a number")


def _optional_float_or_none(section: Mapping[str, object], key: str) -> float | None:
    """Read an optional numeric setting (env-string tolerated); ``None`` when absent.

    Used for the per-tier sampling temperature (BOB-022): absent means the provider
    forces nothing and the endpoint keeps its own default.
    """
    if section.get(key) is None:
        return None
    return _optional_float(section, key, default=0.0)


def _optional_bool(section: Mapping[str, object], key: str, *, default: bool) -> bool:
    """Read a boolean setting, tolerating env-string values; fall back to ``default``."""
    value = section.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    raise KeyError(f"llm.{key} must be a boolean")
