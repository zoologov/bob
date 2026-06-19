# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""In-process asyncio publish/subscribe event bus.

Decouples event producers (e.g. the Telegram gateway) from consumers (use-cases)
so the GUPPI runtime fans events out concurrently. Implements
:class:`bob.domain.ports.EventBus`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bob.domain.ports import DomainEvent, EventHandler

logger = logging.getLogger(__name__)


class AsyncEventBus:
    """Asyncio fan-out bus: deliver each event to every handler of its name.

    Handlers for one event run concurrently; a handler that raises is logged and
    isolated so it cannot starve its siblings or crash the publisher.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """Register ``handler`` for events published under ``event_name``."""
        self._handlers[event_name].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Deliver ``event`` to all subscribers of its name, concurrently."""
        handlers = self._handlers.get(event.name)
        if not handlers:
            return
        results = await asyncio.gather(
            *(handler(event) for handler in handlers),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                logger.exception("event handler failed for %r", event.name, exc_info=result)
