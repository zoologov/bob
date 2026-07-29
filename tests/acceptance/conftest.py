# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Shared fixtures for the BDD acceptance layer (BOB-066 Срез 0).

Exposes the fake-gateway harness as a per-scenario fixture so every ``.feature`` asserts
Bob's OBSERVABLE behaviour through the outgoing boundary — a reply / reaction / silence /
honest outage notice — never his private state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from tests.acceptance.fake_gateway import FakeGateway

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class ScenarioContext:
    """The mutable slate a scenario's Given/When/Then steps share.

    ``tmp_path`` — the isolated on-disk SQLite/soul root for this scenario;
    ``gateway`` — the fake outgoing boundary, populated once the turn is driven;
    ``rhythm_enabled`` — whether the presence rhythm layer is wired for this scenario
    (BOB-066 Срез W), so a shared When step can drive the wired vs inert path;
    ``room_mood_enabled`` / ``tone_line_folded`` — whether the room-mood seam is wired
    (BOB-066 Срез W.2) and whether the heavy-room tone line was folded into Bob's voice.
    """

    tmp_path: Path
    gateway: FakeGateway = field(default_factory=FakeGateway)
    rhythm_enabled: bool = True
    room_mood_enabled: bool = True
    tone_line_folded: bool = False


@pytest.fixture
def scenario_context(tmp_path: Path) -> ScenarioContext:
    """A fresh, isolated context (temp db + soul) per acceptance scenario."""
    return ScenarioContext(tmp_path=tmp_path)
