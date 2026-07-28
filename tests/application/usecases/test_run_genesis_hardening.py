# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Hardening tests for RunGenesis personality parsing.

The Tier 1 model can return garbage; the use-case must reject malformed output
loudly (GenesisError) rather than persist a half-formed soul. These cover the
three failure modes of ``_parse_personality``: non-JSON, non-object JSON, and a
JSON object missing required keys.
"""

from __future__ import annotations

import pytest

from bob.social.usecases.run_genesis import GenesisError, _parse_personality


def test_parse_personality_rejects_non_json() -> None:
    with pytest.raises(GenesisError, match="not valid JSON"):
        _parse_personality("this is not json {")


def test_parse_personality_rejects_non_object_json() -> None:
    # A JSON array is valid JSON but not the expected object.
    with pytest.raises(GenesisError, match="must be a JSON object"):
        _parse_personality('["identity", "traits"]')


def test_parse_personality_rejects_missing_required_keys() -> None:
    # Valid JSON object but missing every required key.
    with pytest.raises(GenesisError, match="missing keys"):
        _parse_personality('{"identity": "Bob"}')
