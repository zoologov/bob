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
from bob.infrastructure.llm.fallback_provider import (
    FallbackLLMProvider,
    ToolCallingFallbackLLMProvider,
    build_fallback_provider,
)
from bob.kernel.ports import (
    LLMProvider,
    ToolCallingProvider,
    ToolCallResult,
    UnderstudyBackedProvider,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from bob.kernel.ports import LLMMessage, ToolDefinition, ToolLoopMessage

_MESSAGES: list[LLMMessage] = [{"role": "user", "content": "привет"}]
_TOOL_MESSAGES: list[ToolLoopMessage] = [{"role": "user", "content": "почитай код"}]
_TOOLS: list[ToolDefinition] = [{"type": "function", "function": {"name": "read_code"}}]


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


class _RecordingToolProvider(_RecordingProvider):
    """A provider that, like OpenAICompatProvider, can also drive the tool loop."""

    def __init__(
        self,
        *,
        reply: str = "ok",
        error: BaseException | None = None,
        tool_reply: str = "final",
        tool_error: BaseException | None = None,
    ) -> None:
        super().__init__(reply=reply, error=error)
        self._tool_reply = tool_reply
        self._tool_error = tool_error
        self.tool_calls: list[tuple[tuple[ToolLoopMessage, ...], tuple[ToolDefinition, ...]]] = []

    async def complete_with_tools(
        self,
        messages: Sequence[ToolLoopMessage],
        *,
        tools: Sequence[ToolDefinition],
    ) -> ToolCallResult:
        self.tool_calls.append((tuple(messages), tuple(tools)))
        if self._tool_error is not None:
            raise self._tool_error
        return ToolCallResult(text=self._tool_reply)


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


# --- tool-calling: the composite must MIRROR the primary's capability (BOB-087.E1b) ---
#
# Lineage: wave E2 left a tripwire here recording that the composite dropped
# ``complete_with_tools`` while the wrapped OpenAICompatProvider realises it. The loss
# would have been SILENT — the tool seam (``bob.runtime.wiring.access._as_tool_provider``)
# probes with ``hasattr``, so a stripped capability makes the tool loop go dormant, never
# error. E1b fixes it, and the tripwire's intent survives as a two-sided contract: the
# composite advertises tool-calling EXACTLY when its primary does — never less (the E2
# bug), never more (a false claim that would hand the seam a provider that cannot serve).


def test_composite_over_a_tool_calling_primary_advertises_tool_calling() -> None:
    # Arrange / Act: this is the shape the factory builds — OpenAICompatProvider primary.
    composite = build_fallback_provider(
        primary=_RecordingToolProvider(),
        fallback=_RecordingToolProvider(),
    )

    # Assert: capability preserved through the wrapper, and it is still an LLMProvider.
    assert isinstance(composite, ToolCallingProvider)
    assert isinstance(composite, LLMProvider)
    assert hasattr(composite, "complete_with_tools")  # the seam's own probe


def test_composite_over_a_tool_less_primary_does_not_advertise_tool_calling() -> None:
    # The other half of the contract: wrapping a tool-less endpoint must not INVENT
    # tool support — the seam would then pick a provider that cannot serve the loop.
    composite = build_fallback_provider(
        primary=_RecordingProvider(),
        fallback=_RecordingToolProvider(),
    )

    assert not isinstance(composite, ToolCallingProvider)
    assert isinstance(composite, LLMProvider)


def test_the_composite_advertises_that_it_is_understudy_backed() -> None:
    # 🔴 BOB-087.E-M1: the composite's degradation is invisible by design, which is right
    # for a служебный ход and wrong for a turn published AS BOB. Declaring the capability
    # is what lets the router ask for the primary alone instead.
    composite = build_fallback_provider(
        primary=_RecordingProvider(), fallback=_RecordingProvider()
    )

    assert isinstance(composite, UnderstudyBackedProvider)


def test_without_understudy_returns_the_bare_primary() -> None:
    # The stripped provider IS the primary object — same endpoint, no stand-in behind it.
    primary = _RecordingProvider(reply="tier0")
    composite = build_fallback_provider(primary=primary, fallback=_RecordingProvider())

    assert composite.without_understudy() is primary


async def test_the_bare_primary_fails_instead_of_degrading() -> None:
    # The whole purpose: an outage on the stripped provider SURFACES (so the router can
    # escalate it upward) rather than being answered by the local stand-in.
    understudy = _RecordingProvider(reply="0.5b")
    composite = build_fallback_provider(
        primary=_RecordingProvider(error=ConnectionError("cloud down")),
        fallback=understudy,
    )

    with pytest.raises(ConnectionError):
        await composite.without_understudy().complete(_MESSAGES)

    assert understudy.calls == []


def test_the_tool_calling_composite_is_understudy_backed_too() -> None:
    # The capability must not be lost in the tool-calling variant (it inherits it).
    primary = _RecordingToolProvider()
    composite = build_fallback_provider(primary=primary, fallback=_RecordingToolProvider())

    assert isinstance(composite, UnderstudyBackedProvider)
    assert composite.without_understudy() is primary


def test_tool_calling_composite_refuses_a_primary_that_cannot_call_tools() -> None:
    # Direct construction bypasses the builder — the invariant must still bite, loudly,
    # rather than produce an object that advertises what it cannot do.
    with pytest.raises(TypeError, match="tool-calling primary"):
        ToolCallingFallbackLLMProvider(
            primary=_RecordingProvider(),
            fallback=_RecordingToolProvider(),
        )


def test_healthy_primary_serves_the_tool_turn_and_local_is_never_asked() -> None:
    # Arrange
    primary = _RecordingToolProvider(tool_reply="из облака")
    fallback = _RecordingToolProvider(tool_reply="локально")
    composite = _tool_composite(primary, fallback)

    # Act
    result = asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))

    # Assert
    assert result == ToolCallResult(text="из облака")
    assert primary.tool_calls == [(tuple(_TOOL_MESSAGES), tuple(_TOOLS))]
    assert fallback.tool_calls == []


def test_tool_turn_transport_failure_switches_to_the_local_model() -> None:
    # Arrange: the BOB-084 outage shape, this time on the tool path.
    primary = _RecordingToolProvider(tool_error=TimeoutError("no answer"))
    fallback = _RecordingToolProvider(tool_reply="локально")
    composite = _tool_composite(primary, fallback)

    # Act
    result = asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))

    # Assert: the same messages AND the same tool manifest reached the local model.
    assert result == ToolCallResult(text="локально")
    assert len(primary.tool_calls) == 1
    assert fallback.tool_calls == [(tuple(_TOOL_MESSAGES), tuple(_TOOLS))]


def test_tool_turn_contract_failure_propagates_without_touching_the_local_model() -> None:
    # Arrange: a broken response shape is OUR defect — masking it is forbidden.
    primary = _RecordingToolProvider(tool_error=ValueError("completion response has no choices"))
    fallback = _RecordingToolProvider()
    composite = _tool_composite(primary, fallback)

    # Act / Assert
    with pytest.raises(ValueError, match="no choices"):
        asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))
    assert fallback.tool_calls == []


def test_tool_turn_cancellation_propagates_without_touching_the_local_model() -> None:
    # Arrange: a shutdown must never be "retried" locally.
    primary = _RecordingToolProvider(tool_error=asyncio.CancelledError())
    fallback = _RecordingToolProvider()
    composite = _tool_composite(primary, fallback)

    # Act / Assert
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))
    assert fallback.tool_calls == []


def test_tool_turn_local_failure_re_raises_the_primary_error() -> None:
    # Arrange: both down — the cloud error is the informative one for the operator.
    primary_error = TimeoutError("cloud timed out")
    primary = _RecordingToolProvider(tool_error=primary_error)
    fallback = _RecordingToolProvider(tool_error=OSError("ollama is not running"))
    composite = _tool_composite(primary, fallback)

    # Act / Assert
    with pytest.raises(TimeoutError, match="cloud timed out") as raised:
        asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))
    assert raised.value is primary_error
    assert isinstance(raised.value.__cause__, OSError)
    assert len(primary.tool_calls) == 1
    assert len(fallback.tool_calls) == 1


def test_tool_turn_switch_is_logged_as_a_warning_naming_the_tool_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: degrading a TOOL turn to a small local model is a bigger quality drop
    # than degrading plain chat — the operator must be told which path degraded.
    primary = _RecordingToolProvider(tool_error=TimeoutError("no answer"))
    fallback = _RecordingToolProvider(tool_reply="локально")
    composite = _tool_composite(primary, fallback)

    # Act
    with caplog.at_level(logging.WARNING, logger="bob.infrastructure.llm.fallback_provider"):
        asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))

    # Assert
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert "TimeoutError" in message
    assert "no answer" in message
    assert "tool" in message.lower()


def test_tool_turn_raises_the_primary_error_when_the_local_model_has_no_tool_support(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Arrange: the honest limit. A local understudy that cannot do tool calls is NOT a
    # substitute — the outage surfaces instead of a silently tool-less answer.
    primary_error = TimeoutError("cloud timed out")
    primary = _RecordingToolProvider(tool_error=primary_error)
    fallback = _RecordingProvider(reply="локально")  # plain chat only
    composite = _tool_composite(primary, fallback)

    # Act / Assert
    with (
        caplog.at_level(logging.WARNING, logger="bob.infrastructure.llm.fallback_provider"),
        pytest.raises(TimeoutError, match="cloud timed out"),
    ):
        asyncio.run(composite.complete_with_tools(_TOOL_MESSAGES, tools=_TOOLS))
    assert fallback.calls == []  # the plain path is NOT a stand-in for a tool turn
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "tool" in warnings[0].getMessage().lower()


def test_plain_completion_still_works_through_the_tool_calling_composite() -> None:
    # The tool-calling composite is the SAME fallback behaviour plus one method: the
    # plain path must not regress when the factory picks the tool-capable variant.
    primary = _RecordingToolProvider(error=TimeoutError("no answer"))
    fallback = _RecordingToolProvider(reply="локально")
    composite = _tool_composite(primary, fallback)

    assert asyncio.run(composite.complete(_MESSAGES)) == "локально"


def _tool_composite(
    primary: _RecordingProvider,
    fallback: _RecordingProvider,
) -> ToolCallingFallbackLLMProvider:
    """Build the composite and assert the factory picked the tool-capable variant."""
    composite = build_fallback_provider(primary=primary, fallback=fallback)
    assert isinstance(composite, ToolCallingFallbackLLMProvider)
    return composite


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
