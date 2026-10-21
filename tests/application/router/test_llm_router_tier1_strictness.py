# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Верхний фолбэк Tier1 → Tier0 больше не прячет наши дефекты (bob-41o).

Срез E дал НИЖНЕМУ фолбэку (облачный Tier-0 → локальный дублёр) консервативную политику:
уходим на дублёра только на ТРАНСПОРТНОМ отказе, а 4xx, битая форма ответа и программные
ошибки идут наружу — иначе фолбэк маскирует наш собственный дефект тихо деградировавшим
ответом. ВЕРХНИЙ фолбэк роутера ловил любое исключение Tier-1 и потому масккировал ровно то
же самое этажом выше: несуществующая модель или кривой base_url в конфиге Tier-1 жили бы
незамеченными неделями, пока Боб тихо отвечает слабым тиром.

🔴 BOB-116: 401/403 (протухший ключ, исчерпанный аккаунт) переехали из «дефекта» в отказ
облака ``auth`` — облако отказывает НАМ, как на 429, и для маршрутизации это недоступность.
Боб десять дней молчал на 403, пока политика звала это «нашим дефектом». Что ключ протух,
владелец узнаёт из сигнала здоровья провайдера (BOB-116), а не из хода, который падает нарочно.

Здесь пришпилена новая строгость. Вердикт — то же самое чистое ядро
:func:`bob.application.router.fallback_policy.should_fall_back`, что судит нижний фолбэк
(одна политика на оба этажа, не две), поэтому проверяем не таксономию исключений (она
своя, в ``tests/application/router/test_fallback_policy.py``), а СТЫК: кого роутер дёрнул и что
увидел вызывающий.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import pytest
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType
from bob.infrastructure.llm.fallback_provider import build_fallback_provider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence


def _response_error(status: int) -> aiohttp.ClientResponseError:
    """То, что реально бросает aiohttp на HTTP-статусе.

    Метаданные запроса заполнены НЕ для галочки: роутер, поднимая контрактный отказ,
    пишет оператору строку сбоя, а ``ClientResponseError.__str__`` читает ``request_info``.
    Двойник без него разошёлся бы с настоящим исключением ровно на том пути, который
    этот файл и проверяет (урок BOB-084: поддельная форма не моделирует настоящую).
    """
    url = URL("http://tier1.example/v1/chat/completions")
    headers: CIMultiDictProxy[str] = CIMultiDictProxy(CIMultiDict())
    request_info = aiohttp.RequestInfo(url, "POST", headers, url)
    return aiohttp.ClientResponseError(request_info, (), status=status, message="boom")


class ScriptedProvider:
    """Фейковый LLMProvider: считает вызовы и падает заданным исключением."""

    def __init__(self, *, reply: str = "ok", error: BaseException | None = None) -> None:
        self.reply = reply
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — часть протокола LLMProvider
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self.error is not None:
            raise self.error
        return self.reply


def _reply_to_user() -> LLMRequest:
    """Ход, чей штатный тир — Tier-1 (именно у него есть верхний фолбэк вниз)."""
    return LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "user", "content": "привет"}],
    )


# --- дефект Tier-1: наружу ошибка, дублирующий тир даже не зовут -------------------


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(_response_error(400), id="400 — кривой запрос"),
        pytest.param(_response_error(404), id="404 — несуществующая модель"),
        pytest.param(ValueError("completion response has no choices"), id="битая форма"),
        pytest.param(aiohttp.InvalidURL("http://[bad"), id="кривой base_url в конфиге"),
        pytest.param(TypeError("non-stream completion must return str"), id="наш баг"),
    ],
)
async def test_a_tier1_defect_surfaces_and_tier0_is_never_asked(error: BaseException) -> None:
    # Arrange: Tier-1 сломан не связью, а контрактом; Tier-0 полностью здоров и готов
    # ответить — то есть у роутера ЕСТЬ чем замаскировать дефект, и он не должен.
    tier0 = ScriptedProvider(reply="слабый тир")
    tier1 = ScriptedProvider(error=error)
    router = LLMRouter(providers={0: tier0, 1: tier1})

    # Act / Assert: наружу ушла ровно исходная ошибка.
    with pytest.raises(type(error)):
        await router.run(_reply_to_user())

    assert len(tier1.calls) == 1
    assert tier0.calls == [], "дефект Tier-1 нельзя прятать за ответом Tier-0"


async def test_the_surfaced_tier1_failure_keeps_its_own_diagnosis() -> None:
    # Наружу должна дойти ПРИЧИНА, по которой конфигурация сломана, а не безликий сбой:
    # оператор чинит 404 (имя модели в конфиге), только если видит 404.
    tier0 = ScriptedProvider(reply="слабый тир")
    tier1 = ScriptedProvider(error=_response_error(404))
    router = LLMRouter(providers={0: tier0, 1: tier1})

    with pytest.raises(aiohttp.ClientResponseError) as surfaced:
        await router.run(_reply_to_user())

    assert surfaced.value.status == 404


# --- авария связи Tier-1: фолбэк вниз работает ровно как работал --------------------


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(TimeoutError(), id="таймаут"),
        pytest.param(ConnectionError("refused"), id="соединение отвергнуто"),
        pytest.param(aiohttp.ServerDisconnectedError(), id="обрыв на полуслове"),
        pytest.param(aiohttp.ClientPayloadError("truncated"), id="тело оборвалось"),
        pytest.param(_response_error(503), id="503 — упал апстрим"),
        pytest.param(_response_error(408), id="408 — эндпоинт устал ждать"),
        pytest.param(_response_error(429), id="429 — нас не обслуживают сейчас"),
        pytest.param(_response_error(401), id="401 — протухший ключ (BOB-116)"),
        pytest.param(_response_error(403), id="403 — аккаунт исчерпан или закрыт (BOB-116)"),
    ],
)
async def test_a_tier1_outage_still_falls_back_to_tier0(error: BaseException) -> None:
    # Регрессия: страховка от отвала облака — ровно то, ради чего верхний фолбэк есть.
    tier0 = ScriptedProvider(reply="ответ Tier-0")
    tier1 = ScriptedProvider(error=error)
    router = LLMRouter(providers={0: tier0, 1: tier1})

    result = await router.run(_reply_to_user())

    assert result == "ответ Tier-0"
    assert len(tier1.calls) == 1
    assert len(tier0.calls) == 1


async def test_the_fallback_payload_is_still_the_redacted_one() -> None:
    # Строгость не трогает редакцию: то, что уходит на Tier-0 после аварии Tier-1, —
    # тот же однажды собранный payload без приватного контекста.
    private = "ВНУТРЕННЕЕ: черновик монолога."
    shareable = "Из разговора: собеседника зовут Алиса."
    tier0 = ScriptedProvider(reply="ответ Tier-0")
    tier1 = ScriptedProvider(error=TimeoutError())
    router = LLMRouter(providers={0: tier0, 1: tier1})

    await router.run(
        LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[{"role": "user", "content": "привет"}],
            shareable_context=shareable,
            private_context=private,
        )
    )

    payload = " ".join(m.get("content", "") for call in tier0.calls for m in call)
    assert shareable in payload
    assert private not in payload


# --- ни одной петли: спасательная попытка ровно одна --------------------------------


async def test_a_failed_rescue_does_not_bounce_back_up() -> None:
    # 🔴 Инвариант «нет петли Tier1 → Tier0 → Tier1»: спасательный ход делается ОДИН раз
    # и вне try, поэтому его собственный отвал уходит наружу, а не запускает круг.
    tier0 = ScriptedProvider(error=ConnectionError("и локальный лёг"))
    tier1 = ScriptedProvider(error=TimeoutError())
    router = LLMRouter(providers={0: tier0, 1: tier1})

    with pytest.raises(ConnectionError):
        await router.run(_reply_to_user())

    assert len(tier1.calls) == 1, "второго захода на Tier-1 быть не может"
    assert len(tier0.calls) == 1


async def test_the_upward_escalation_of_bobs_own_voice_is_untouched() -> None:
    # 🔴 Осознанная асимметрия (см. матрицу в докстринге LLMRouter.run): строгость введена
    # для фолбэка ВНИЗ, потому что вниз — это тихая деградация. Эскалация ВВЕРХ (E-M1) —
    # обычный ход на КАЧЕСТВЕННЫЙ тир, деградации в ней нет, поэтому она остаётся
    # безусловной: дефект Tier-0 не отнимает у собеседника настоящий ответ Боба.
    tier0_primary = ScriptedProvider(error=_response_error(400))
    understudy = ScriptedProvider(reply="0.5b мямлит")
    tier1 = ScriptedProvider(reply="настоящий голос Боба")
    composite = build_fallback_provider(primary=tier0_primary, fallback=understudy)
    router = LLMRouter(providers={0: composite, 1: tier1})

    result = await router.run(
        LLMRequest(
            task_type=TaskType.REPLY_TO_USER,
            messages=[{"role": "user", "content": "как дела"}],
            tier_override=0,
        )
    )

    assert result == "настоящий голос Боба"
    assert understudy.calls == [], "дублёр не говорит за Боба ни при каком отказе"
    assert len(tier1.calls) == 1
