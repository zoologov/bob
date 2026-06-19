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
