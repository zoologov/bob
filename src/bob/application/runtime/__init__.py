# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""GUPPI runtime — asyncio event loop, lifecycle, and the in-process event bus."""

from bob.application.runtime.agent import AgentRuntime, RuntimeState
from bob.application.runtime.event_bus import AsyncEventBus
from bob.application.runtime.heartbeat import RetryPolicy, periodic
from bob.application.runtime.retry import is_transient, retry_with_backoff
from bob.application.runtime.serial_queue import SerialQueue

__all__ = [
    "AgentRuntime",
    "AsyncEventBus",
    "RetryPolicy",
    "RuntimeState",
    "SerialQueue",
    "is_transient",
    "periodic",
    "retry_with_backoff",
]
