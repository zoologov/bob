# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root clock — the real UTC time source + async sleep/monotonic seams.

The injectable time seams the composition root wires into the domain so it never calls
``datetime.now()`` directly (BOB-062.7a). ``SystemClock`` is production's UTC ``now()``;
tests inject a fixed clock. This is ``bob.runtime`` (the composition root), NOT
``bob.application.runtime`` (the async AgentRuntime primitives).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime


class SystemClock:
    """Real time source (UTC). Injected so the domain avoids ``datetime.now()``."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def _monotonic() -> float:
    return asyncio.get_event_loop().time()
