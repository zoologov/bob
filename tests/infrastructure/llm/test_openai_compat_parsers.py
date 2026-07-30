# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening tests for the OpenAI-compatible response parsers.

The provider's wire parsers must reject malformed completion bodies loudly and
ignore non-token SSE lines gracefully, so a flaky upstream cannot smuggle
garbage into the application. These cover the defensive branches of
``_extract_message_content`` and ``_parse_sse_token`` directly.
"""

from __future__ import annotations

import pytest

from bob.infrastructure.llm.openai_compat import (
    _extract_message_content,
    _extract_tool_call_result,
    _parse_sse_token,
)

# --- _extract_message_content (non-stream body) -------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},  # no choices
        {"choices": []},  # empty choices
        {"choices": ["not-an-object"]},  # choice not a mapping
        {"choices": [{}]},  # choice has no message
    ],
)
def test_extract_message_content_rejects_structurally_malformed_bodies(
    body: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="completion"):
        _extract_message_content(body)


@pytest.mark.parametrize(
    "body",
    [
        {"choices": [{"message": {}}]},  # message has no content
        {"choices": [{"message": {"content": None}}]},  # content is null
        {"choices": [{"message": {"content": 5}}]},  # content not a string
        {"choices": [{"message": {"content": ""}}]},  # content empty
    ],
)
def test_extract_message_content_tolerates_missing_content(
    body: dict[str, object],
) -> None:
    # A reasoning model may emit a successful response with null/empty content
    # (budget spent on reasoning_content); degrade to "" rather than erroring.
    assert _extract_message_content(body) == ""


def test_extract_message_content_returns_well_formed_content() -> None:
    body = {"choices": [{"message": {"content": "hello"}}]}
    assert _extract_message_content(body) == "hello"


# --- _parse_sse_token (streaming lines) ---------------------------------------


def test_parse_sse_token_extracts_delta_content() -> None:
    line = b'data: {"choices": [{"delta": {"content": "Hi"}}]}'
    assert _parse_sse_token(line) == "Hi"


@pytest.mark.parametrize(
    "line",
    [
        b"",  # blank line
        b": keep-alive comment",  # not a data line
        b"data: [DONE]",  # terminal sentinel
        b'data: {"choices": []}',  # no choices
        b'data: {"choices": [{"delta": "not-a-mapping"}]}',  # delta not a mapping
        b'data: {"choices": [{"delta": {}}]}',  # delta has no content
        b'data: {"choices": [{"delta": {"content": 7}}]}',  # content not a string
    ],
)
def test_parse_sse_token_ignores_non_token_lines(line: bytes) -> None:
    assert _parse_sse_token(line) is None


# --- _extract_tool_call_result (tool-calling body) ----------------------------


def test_extract_tool_call_result_reads_native_tool_calls() -> None:
    # Arrange: an OpenAI-native tool_calls response (the MaaS-supports-tools path).
    body = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "recall_memory",
                                "arguments": '{"query": "coffee"}',
                            },
                        }
                    ],
                }
            }
        ]
    }

    # Act
    result = _extract_tool_call_result(body)

    # Assert: the native call is decoded into a ToolCall (arguments JSON parsed).
    assert result.text == ""
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.id == "call_1"
    assert call.name == "recall_memory"
    assert call.arguments == {"query": "coffee"}


def test_extract_tool_call_result_final_answer_has_no_tool_calls() -> None:
    # Arrange: a plain final answer (no tools requested).
    body = {"choices": [{"message": {"content": "Coffee is great."}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert
    assert result.text == "Coffee is great."
    assert result.tool_calls == ()


def test_extract_tool_call_result_parses_prompt_protocol_fallback() -> None:
    # Arrange: NO native tool_calls — the model emitted a JSON tool-call as TEXT,
    # wrapped in reasoning prose + a code fence (the prompt-protocol fallback for
    # a MaaS endpoint that does not support native OpenAI tools).
    content = (
        "Let me think... I should look that up.\n"
        '```json\n{"tool_call": {"name": "recall_memory", '
        '"arguments": {"query": "coffee"}}}\n```\n'
        "Calling it now."
    )
    body = {"choices": [{"message": {"content": content}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert: the fenced JSON tool-call is recovered tolerantly.
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "recall_memory"
    assert call.arguments == {"query": "coffee"}


def test_extract_tool_call_result_ignores_plain_prose_without_tool_call() -> None:
    # Arrange: prose that merely mentions JSON braces but is no tool-call.
    body = {"choices": [{"message": {"content": "I think {coffee} is nice."}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert: treated as a final answer, no spurious tool call.
    assert result.tool_calls == ()
    assert result.text == "I think {coffee} is nice."


# --- defence-in-depth: textual tool-call forms + no-leak invariant (BOB-069 B) --
# 🔴 Живой баг: Qwen эхом отдавал сырой «[tool_calls] read_code({...})» текстом.
# Страховка распознаёт текстовую/hermes-форму как tool_calls, а хвост-инвариант
# гарантирует, что reply, начинающийся с «[tool_calls] », НИКОГДА не течёт наружу.


def test_extract_tool_call_result_recovers_echoed_tool_calls_string() -> None:
    # Arrange: модель ЭХОМ вернула сырой ход текстом (нет native tool_calls).
    content = '[tool_calls] read_code({"query": "tests/acceptance/features/x.feature"})'
    body = {"choices": [{"message": {"content": content}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert: распознано как вызов, а НЕ отдано текстом.
    assert result.text == ""
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "read_code"
    assert call.arguments == {"query": "tests/acceptance/features/x.feature"}


def test_extract_tool_call_result_recovers_hermes_wrapped_tool_call() -> None:
    # Arrange: hermes-обёртка, которую Qwen может отдать при thinking-off.
    content = (
        "<tool_call>\n"
        '{"name": "read_code", "arguments": {"query": "a.feature"}}\n'
        "</tool_call>"
    )
    body = {"choices": [{"message": {"content": content}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert
    assert result.text == ""
    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert call.name == "read_code"
    assert call.arguments == {"query": "a.feature"}


def test_extract_tool_call_result_never_leaks_unparseable_tool_calls_string() -> None:
    # 🔴 Жёсткий инвариант: даже неразборный «[tool_calls] …» НЕ уходит текстом.
    content = "[tool_calls] "  # обрублено, вызов не восстановить
    body = {"choices": [{"message": {"content": content}}]}

    # Act
    result = _extract_tool_call_result(body)

    # Assert: санитизировано в пустой текст, не утечка.
    assert result.tool_calls == ()
    assert not result.text.startswith("[tool_calls]")


def test_extract_tool_call_result_tolerates_malformed_native_arguments() -> None:
    # Arrange: native tool_call whose arguments are not valid JSON.
    body = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "c9",
                            "function": {"name": "recall_memory", "arguments": "not json"},
                        }
                    ]
                }
            }
        ]
    }

    # Act
    result = _extract_tool_call_result(body)

    # Assert: the call survives with empty arguments rather than erroring.
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].arguments == {}
