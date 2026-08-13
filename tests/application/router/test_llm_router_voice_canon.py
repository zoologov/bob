# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Роутер: канон о голосе доезжает до провайдера, а не только до кода (BOB-096, срез 3).

Тесты на НАСТОЯЩЕМ :class:`~bob.application.router.llm_router.LLMRouter` с записывающим
провайдером: пинается то, что реально уходит модели. Ядро шва проверено отдельно
(``test_voice_canon``), здесь — что роутер спрашивает про дверь, вплетает канон один раз
на построение payload и что рескью-попытка (падение тира) уносит ТОТ ЖЕ payload — иначе
запасной путь снова оказался бы дверью без канона.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bob.application.router.llm_router import LLMRequest, LLMRouter, TaskType

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence

CANON_PROSE = "GUPPI ты не отыгрываешь: ни речи, ни мнения, ни поступков за него."
CANON_MACHINE = "GUPPI — исполнитель без личности: речи и мнений у него нет."


def canon(*, prose_answer: bool) -> str:
    return CANON_PROSE if prose_answer else CANON_MACHINE


class RecordingProvider:
    """Fake LLMProvider recording every payload; optionally an outage."""

    def __init__(self, *, reply: str = "ok", fail: bool = False) -> None:
        self.reply = reply
        self.fail = fail
        self.calls: list[list[dict[str, str]]] = []

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        stream: bool = False,  # noqa: ARG002 — part of the LLMProvider protocol signature
    ) -> str | AsyncIterator[str]:
        self.calls.append([dict(m) for m in messages])
        if self.fail:
            raise ConnectionError("tier unavailable")
        return self.reply


def _payload(provider: RecordingProvider) -> str:
    return "\n".join(m.get("content", "") for call in provider.calls for m in call)


def _router(provider: RecordingProvider, *, wired: bool = True) -> LLMRouter:
    return LLMRouter(
        providers={0: provider, 1: provider},
        voice_canon=canon if wired else None,
    )


def _request(task: TaskType) -> LLMRequest:
    return LLMRequest(
        task_type=task,
        messages=[{"role": "system", "content": "промпт двери"}],
    )


@pytest.mark.asyncio
async def test_the_reflection_door_receives_the_canon() -> None:
    # Рефлексия — главный источник отравления: её текст ложится в episodic_log и
    # возвращается в разговорный ход припоминанием.
    provider = RecordingProvider()

    await _router(provider).run(_request(TaskType.REFLECT))

    assert CANON_PROSE in _payload(provider)


@pytest.mark.asyncio
async def test_a_judge_receives_nothing_extra() -> None:
    provider = RecordingProvider()

    await _router(provider).run(_request(TaskType.RESPONSE_JUDGE))

    assert _payload(provider) == "промпт двери"


@pytest.mark.asyncio
async def test_a_json_door_receives_the_form_without_prose() -> None:
    provider = RecordingProvider()

    await _router(provider).run(_request(TaskType.EXTRACT_FACTS))

    payload = _payload(provider)
    assert CANON_MACHINE in payload
    assert CANON_PROSE not in payload


@pytest.mark.asyncio
async def test_a_door_already_carrying_the_canon_gets_no_second_copy() -> None:
    provider = RecordingProvider()
    request = LLMRequest(
        task_type=TaskType.REPLY_TO_USER,
        messages=[{"role": "system", "content": f"Ты Боб. {CANON_PROSE}"}],
    )

    await _router(provider).run(request)

    assert _payload(provider).count(CANON_PROSE) == 1


@pytest.mark.asyncio
async def test_an_unwired_router_sends_the_payload_byte_for_byte() -> None:
    provider = RecordingProvider()

    await _router(provider, wired=False).run(_request(TaskType.REFLECT))

    assert provider.calls == [[{"role": "system", "content": "промпт двери"}]]


@pytest.mark.asyncio
async def test_the_rescue_attempt_carries_the_canon_too() -> None:
    # Tier 1 падает по транспорту → один прыжок вниз на Tier 0 ТЕМ ЖЕ payload'ом.
    # Дверь запасного пути обязана нести канон, иначе он терялся бы ровно при сбое.
    tier1 = RecordingProvider(fail=True)
    tier0 = RecordingProvider()
    router = LLMRouter(providers={0: tier0, 1: tier1}, voice_canon=canon)

    await router.run(_request(TaskType.REPLY_TO_USER))

    assert CANON_PROSE in _payload(tier0)


@pytest.mark.asyncio
async def test_the_canon_does_not_displace_the_context_or_the_prompt() -> None:
    provider = RecordingProvider()
    request = LLMRequest(
        task_type=TaskType.REFLECT,
        messages=[{"role": "system", "content": "промпт двери"}],
        private_context="старые записи",
    )

    await _router(provider).run(request)

    contents = [m["content"] for m in provider.calls[0]]
    assert contents == [CANON_PROSE, "старые записи", "промпт двери"]
