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

When ``llm.tier0_fallback`` names a local backend (BOB-087.E1), Tier 0 is handed over
wrapped by :func:`~bob.infrastructure.llm.fallback_provider.build_fallback_provider` so
a network outage of a *cloud* Tier 0 degrades to a local Ollama model instead of taking
the classifiers/monologue/gates down. The builder — not this factory — decides which
composite mirrors the wrapped tier's tool-calling capability (BOB-087.E1b). Empty (the
default) → Tier 0 is the plain provider, exactly as before.

The result maps tier index -> provider, ready for the
:class:`bob.application.router.LLMRouter`.

Provider health (BOB-116): an optional :class:`~bob.kernel.ports.HealthObserver` is
threaded into the understudy wrapper, which reports the cloud and the stand-in separately.
:func:`understudy_endpoint` is the one reading of «is a stand-in configured, and where» —
the composition root learns ``has_understudy`` from it for the monitor and hands it to
:func:`bob.infrastructure.llm.understudy_probe.probe_understudy` at startup.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bob.capabilities.adapters.web_search_qwen import QwenWebSearchProvider
from bob.infrastructure.llm.fallback_provider import build_fallback_provider
from bob.infrastructure.llm.openai_compat import OpenAICompatProvider

if TYPE_CHECKING:
    from bob.capabilities.ports import WebSearchProvider
    from bob.kernel.ports import HealthObserver, LLMProvider

_TIER_LOCAL = 0
_TIER_API = 1

# Generous default so a slow Tier 1 reasoning model (1000+ reasoning tokens per
# reply) does not time out and spuriously fall back to Tier 0.
_DEFAULT_TIMEOUT_SECONDS = 180.0

# Default Qwen-native search model (verify .1: Responses API returns sources on it).
_DEFAULT_SEARCH_MODEL = "qwen3.7-plus"

# Local backends accepted by ``llm.tier0_fallback`` (BOB-087.E1). Ollama speaks the
# OpenAI-compatible chat API, so the emergency provider is the same adapter pointed at
# ``localhost``; an unrecognised value is a typo and must fail loudly rather than leave
# Tier 0 quietly unprotected.
_FALLBACK_BACKENDS = frozenset({"ollama"})


@dataclass(frozen=True, slots=True)
class UnderstudyEndpoint:
    """Where the local Tier-0 stand-in lives: its OpenAI-compatible base URL and model."""

    base_url: str
    model: str


def understudy_endpoint(config: Mapping[str, object]) -> UnderstudyEndpoint | None:
    """The configured Tier-0 stand-in, or ``None`` when ``llm.tier0_fallback`` is off.

    An unrecognised backend is a typo and fails loudly (``KeyError``), exactly as when the
    providers are built — one reading of the flag for the factory and for its callers.
    """
    llm = config.get("llm")
    if not isinstance(llm, Mapping):
        raise KeyError("config is missing the 'llm' section")
    backend = (_optional_str(llm, "tier0_fallback") or "").strip().lower()
    if not backend:
        return None
    if backend not in _FALLBACK_BACKENDS:
        raise KeyError(
            f"llm.tier0_fallback must be one of {sorted(_FALLBACK_BACKENDS)} (got {backend!r})"
        )
    return UnderstudyEndpoint(
        base_url=_require_str(llm, "tier0_fallback_base_url"),
        model=_require_str(llm, "tier0_fallback_model"),
    )


def build_tier_providers(
    config: Mapping[str, object],
    *,
    health: HealthObserver | None = None,
) -> dict[int, LLMProvider]:
    """Build ``{0: tier0_provider, 1: tier1_provider}`` from ``config['llm']``.

    ``health`` reaches the understudy wrapper only: the router reports Tier 1 and a plain
    Tier 0 itself, so threading it into the bare providers would count each call twice.
    """
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
    local_fallback = _build_tier0_fallback(
        understudy_endpoint(config),
        llm,
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
    )
    if local_fallback is None:
        return {_TIER_LOCAL: tier0, _TIER_API: tier1}
    return {
        _TIER_LOCAL: build_fallback_provider(
            primary=tier0, fallback=local_fallback, health=health
        ),
        _TIER_API: tier1,
    }


def _build_tier0_fallback(
    endpoint: UnderstudyEndpoint | None,
    llm: Mapping[str, object],
    *,
    timeout_seconds: float,
    disable_thinking: bool,
) -> OpenAICompatProvider | None:
    """Build the local emergency Tier-0 provider, or ``None`` when it is off.

    Off (``llm.tier0_fallback`` empty/absent — the default) is the supported normal
    state, not an error: Tier 0 is then the plain cloud/local provider it has always
    been. When on, the understudy inherits Tier 0's call knobs (timeout, thinking
    policy, sampling temperature) so the degraded mode answers like Tier 0 rather
    than like a third, differently-tuned tier, and stays keyless — it is local.
    """
    if endpoint is None:
        return None
    return OpenAICompatProvider(
        base_url=endpoint.base_url,
        model=endpoint.model,
        api_key=None,
        timeout_seconds=timeout_seconds,
        disable_thinking=disable_thinking,
        temperature=_optional_float_or_none(llm, "tier0_temperature"),
    )


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
