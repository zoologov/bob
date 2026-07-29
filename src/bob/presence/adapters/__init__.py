# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=presence
# beadloom:layer=infrastructure

"""Presence adapters — the episodic-backed realisations of the presence ports."""

from __future__ import annotations

from bob.presence.adapters.outgoing_activity_store import EpisodicOutgoingActivityStore
from bob.presence.adapters.staleness_judge import LlmStalenessJudge

__all__ = ["EpisodicOutgoingActivityStore", "LlmStalenessJudge"]
