# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Проверка дублёра Tier-0 при старте: включён ли, отвечает ли, есть ли модель (BOB-116).

ОДНА ответственность: спросить настроенный локальный эндпоинт (форма Ollama
``GET {base_url}/models``), есть ли на нём модель дублёра, и вернуть ответ фактом с
человеческой причиной. Ничего не шлёт и не решает: сигнал владельцу «дублёр включён, но
модели нет» (через ``OwnerAlertSink``) и строку лога при старте собирает композиция.

Зачем отдельно от обёртки: обёртка узнаёт, что дублёра нет, только когда облако уже упало и
дублёр оказался пуст, — в худший момент. Проверка при старте говорит об этом сразу, пока
облако живо и есть время сделать ``ollama pull``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from bob.infrastructure.llm.factory import UnderstudyEndpoint

__all__ = ["UnderstudyCheck", "probe_understudy"]

_DEFAULT_TIMEOUT_SECONDS = 5.0
_LATEST_TAG = ":latest"


@dataclass(frozen=True, slots=True)
class UnderstudyCheck:
    """Ответ проверки. ``reason`` — человеческая причина, когда дублёр включён и не готов.

    ``reason`` встаёт в фразу «в конфигурации он включён, но <reason>».
    """

    configured: bool
    ready: bool
    reason: str | None = None
    model: str | None = None

    @property
    def summary(self) -> str:
        """Одна строка для лога старта: выключен / включён и готов / включён и не готов."""
        if not self.configured:
            return "tier0 understudy: off"
        if self.ready:
            return f"tier0 understudy: on, model {self.model} ready"
        return f"tier0 understudy: on, NOT ready — {self.reason}"


async def probe_understudy(
    endpoint: UnderstudyEndpoint | None,
    *,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> UnderstudyCheck:
    """Спросить эндпоинт дублёра о его моделях; ``None`` (дублёр выключен) — без сети."""
    if endpoint is None:
        return UnderstudyCheck(configured=False, ready=False)
    url = endpoint.base_url
    try:
        listed = await _listed_models(url, timeout_seconds=timeout_seconds)
    except aiohttp.ClientResponseError as error:
        return _not_ready(endpoint, f"{url} ответил {error.status}")
    except (aiohttp.ClientError, OSError, TimeoutError) as error:
        return _not_ready(endpoint, f"{url} не отвечает ({type(error).__name__})")
    except ValueError:
        return _not_ready(endpoint, f"{url} ответил непонятно — это точно Ollama?")
    if not _has_model(listed, endpoint.model):
        model = endpoint.model
        return _not_ready(endpoint, f"модели {model} нет на {url} (нужен ollama pull {model})")
    return UnderstudyCheck(configured=True, ready=True, model=endpoint.model)


def _not_ready(endpoint: UnderstudyEndpoint, reason: str) -> UnderstudyCheck:
    return UnderstudyCheck(configured=True, ready=False, reason=reason, model=endpoint.model)


async def _listed_models(base_url: str, *, timeout_seconds: float) -> set[str]:
    """Id моделей из ``{base_url}/models``; битое тело — ``ValueError``."""
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with (
        aiohttp.ClientSession(timeout=timeout) as session,
        session.get(f"{base_url.rstrip('/')}/models") as response,
    ):
        response.raise_for_status()
        try:
            body = await response.json(content_type=None)
        except json.JSONDecodeError as error:
            raise ValueError("models listing is not JSON") from error
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        raise ValueError("models listing has no 'data' array")
    return {str(item["id"]) for item in data if isinstance(item, dict) and "id" in item}


def _has_model(listed: set[str], model: str) -> bool:
    """Есть ли модель; имя без тега Ollama читает как ``:latest``."""
    return model in listed or f"{model}{_LATEST_TAG}" in listed
