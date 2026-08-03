# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Tests for FallbackLLMProvider — cloud primary with a local emergency understudy.

Observed through the port: what the caller gets back, which provider was actually
asked, how many times, and what the operator sees in the log. BOB-087.E1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import pytest

from bob.application.router import LLMRequest, LLMRouter, TaskType
from bob.infrastructure.llm.fallback_provider import FallbackLLMProvider
from bob.kernel.ports import LLMProvider

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage

_MESSAGES: list[LLMMessage] = [{"role": "user", "content": "привет"}]


class _RecordingProvider:
    """A provider that records its calls and answers (or raises) as configured."""

    def __init__(self, *, reply: str = "ok", error: BaseException | None = None) -> None:
        self._reply = reply
        self._error = error
        self.calls: list[tuple[tuple[LLMMessage, ...], bool]] = []

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        stream: bool = False,
    ) -> str | AsyncIterator[str]:
        self.calls.append((tuple(messages), stream))
        if self._error is not None:
            raise self._error
        if stream:
            return _tokens(self._reply)
        return self._reply


async def _tokens(reply: str) -> AsyncIterator[str]:
    yield reply


def test_realises_the_llm_provider_port() -> None:
    provider = FallbackLLMProvider(
        primary=_RecordingProvider(),
        fallback=_RecordingProvider(),
    )

    assert isinstance(provider, LLMProvider)


def test_healthy_primary_answers_and_local_is_never_asked() -> None:
    # Arrange
    primary = _RecordingProvider(reply="из облака")
    fallback = _RecordingProvider(reply="локально")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    result = asyncio.run(provider.complete(_MESSAGES))

    # Assert
    assert result == "из облака"
    assert len(primary.calls) == 1
    assert fallback.calls == []


def test_transport_failure_switches_to_the_local_model() -> None:
    # Arrange: the BOB-084 outage shape — the cloud call never came back.
    primary = _RecordingProvider(error=TimeoutError("no answer"))
    fallback = _RecordingProvider(reply="локально")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    result = asyncio.run(provider.complete(_MESSAGES))

    # Assert: the same payload reached the local model, exactly once each.
    assert result == "локально"
    assert len(primary.calls) == 1
    assert fallback.calls == [(tuple(_MESSAGES), False)]


def test_contract_failure_propagates_without_touching_the_local_model() -> None:
    # Arrange: a broken response shape is OUR defect — masking it is forbidden.
    primary = _RecordingProvider(error=ValueError("completion response has no choices"))
    fallback = _RecordingProvider()
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act / Assert
    with pytest.raises(ValueError, match="no choices"):
        asyncio.run(provider.complete(_MESSAGES))
    assert fallback.calls == []


def test_cancellation_propagates_without_touching_the_local_model() -> None:
    # Arrange: a shutdown must never be "retried" locally.
    primary = _RecordingProvider(error=asyncio.CancelledError())
    fallback = _RecordingProvider()
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act / Assert
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.complete(_MESSAGES))
    assert fallback.calls == []


def test_local_failure_re_raises_the_primary_error() -> None:
    # Arrange: both down — the cloud error is the informative one for the operator.
    primary_error = TimeoutError("cloud timed out")
    primary = _RecordingProvider(error=primary_error)
    fallback = _RecordingProvider(error=OSError("ollama is not running"))
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act / Assert: the primary failure surfaces, with the local one as its cause.
    with pytest.raises(TimeoutError, match="cloud timed out") as raised:
        asyncio.run(provider.complete(_MESSAGES))
    assert raised.value is primary_error
    assert isinstance(raised.value.__cause__, OSError)


def test_no_cascade_one_attempt_each() -> None:
    # Arrange: both fail -> exactly one call to each, никаких ретраев.
    primary = _RecordingProvider(error=TimeoutError("cloud timed out"))
    fallback = _RecordingProvider(error=OSError("ollama is not running"))
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    with pytest.raises(TimeoutError):
        asyncio.run(provider.complete(_MESSAGES))

    # Assert
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


def test_switch_is_logged_as_a_warning_with_the_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: silent degradation is unacceptable — the owner must learn that Bob
    # is living on the emergency model.
    primary = _RecordingProvider(error=TimeoutError("no answer"))
    fallback = _RecordingProvider(reply="локально")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    with caplog.at_level(logging.WARNING, logger="bob.infrastructure.llm.fallback_provider"):
        asyncio.run(provider.complete(_MESSAGES))

    # Assert: one warning naming the failure kind + its message.
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "TimeoutError" in message
    assert "no answer" in message


def test_local_failure_is_logged_too(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange: both down — the operator sees the switch AND that it did not help.
    primary = _RecordingProvider(error=TimeoutError("cloud timed out"))
    fallback = _RecordingProvider(error=OSError("ollama is not running"))
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    with (
        caplog.at_level(logging.WARNING, logger="bob.infrastructure.llm.fallback_provider"),
        pytest.raises(TimeoutError),
    ):
        asyncio.run(provider.complete(_MESSAGES))

    # Assert
    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 2
    assert "ollama is not running" in messages[1]


def test_healthy_primary_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    # Arrange
    provider = FallbackLLMProvider(
        primary=_RecordingProvider(reply="из облака"),
        fallback=_RecordingProvider(),
    )

    # Act
    with caplog.at_level(logging.DEBUG, logger="bob.infrastructure.llm.fallback_provider"):
        asyncio.run(provider.complete(_MESSAGES))

    # Assert: the normal path is silent.
    assert caplog.records == []


def test_streaming_is_delegated_to_the_primary() -> None:
    # Arrange: streaming failures surface mid-iteration (tokens may already be out),
    # so a re-run on the local model would duplicate output — the stream path stays
    # a plain delegation to the primary.
    primary = _RecordingProvider(reply="поток")
    fallback = _RecordingProvider(reply="локально")
    provider = FallbackLLMProvider(primary=primary, fallback=fallback)

    # Act
    tokens = asyncio.run(_drain(provider))

    # Assert
    assert tokens == ["поток"]
    assert primary.calls == [(tuple(_MESSAGES), True)]
    assert fallback.calls == []


async def _drain(provider: FallbackLLMProvider) -> list[str]:
    stream = await provider.complete(_MESSAGES, stream=True)
    assert not isinstance(stream, str)
    return [token async for token in stream]


def test_router_keeps_working_when_the_cloud_tier0_is_down() -> None:
    # The acceptance shape (BOB-Issues #34): a Tier-0 task — the register/intent
    # classifiers, the inner monologue — still gets an answer while the cloud Tier-0
    # endpoint is unreachable. The router itself is UNCHANGED: it just holds the
    # composite as its Tier-0 provider.
    primary = _RecordingProvider(error=TimeoutError("aliyun unreachable"))
    local = _RecordingProvider(reply="work")
    router = LLMRouter(
        providers={
            0: FallbackLLMProvider(primary=primary, fallback=local),
            1: _RecordingProvider(reply="из облака"),
        }
    )

    # Act: WORK_TALK is a Tier-0 classifier (BOB-087.C2).
    verdict = asyncio.run(router.run(LLMRequest(task_type=TaskType.WORK_TALK, messages=_MESSAGES)))

    # Assert
    assert verdict == "work"
    assert len(local.calls) == 1
