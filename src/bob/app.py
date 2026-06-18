# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition root — wire ports to adapters and run the GUPPI runtime.

This is the ONLY place allowed to depend on every layer at once. BEAD-01 is a
walking skeleton: the LLM / memory ports are filled with inert stubs so the
process can start and stop. Later beads (.2-.4) swap these stubs for the real
infrastructure adapters (SQLite repo, OpenAI-compatible provider, Telegram
gateway) without touching the domain or application layers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bob.application.runtime import AgentRuntime, AsyncEventBus
from bob.infrastructure.config import ConfigLoader

if TYPE_CHECKING:
    from pathlib import Path

    from bob.domain import ports

logger = logging.getLogger(__name__)

_STUB_REPLY = "…"  # placeholder until the real LLM provider lands (BEAD-03)


class SystemClock:
    """Real time source (UTC). Injected so the domain avoids ``datetime.now()``."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class _StubLLMProvider:
    """Inert LLM provider for the walking skeleton (replaced in BEAD-03)."""

    async def complete(
        self,
        messages: Sequence[ports.LLMMessage],
        *,
        stream: bool = False,
    ) -> str:
        logger.debug("stub LLM complete(messages=%d, stream=%s)", len(messages), stream)
        return _STUB_REPLY


class _StubMemoryRepo:
    """Inert in-memory repo for the walking skeleton (replaced in BEAD-02)."""

    def __init__(self) -> None:
        self._episodes: list[Mapping[str, object]] = []

    async def save_episode(self, episode: Mapping[str, object]) -> None:
        self._episodes.append(episode)

    async def load_episodes(self, *, limit: int) -> Sequence[Mapping[str, object]]:
        return list(reversed(self._episodes[-limit:]))


class _StubMemoryRecall:
    """Inert recall for the walking skeleton (replaced by FTS5 in BEAD-02)."""

    async def recall(self, query: str, *, k: int) -> Sequence[ports.Recalled]:
        logger.debug("stub recall(query=%r, k=%d)", query, k)
        return []


@dataclass(frozen=True)
class Application:
    """Assembled GUPPI process: runtime, bus, and the wired ports.

    Holds the composition result so callers (and tests) can start the runtime or
    inspect the bound adapters without re-running the wiring.
    """

    config: Mapping[str, object]
    runtime: AgentRuntime
    event_bus: AsyncEventBus
    clock: ports.Clock
    llm_provider: ports.LLMProvider
    memory_repo: ports.MemoryRepo
    memory_recall: ports.MemoryRecall


def build_application(*, config_path: Path | None = None) -> Application:
    """Wire stub adapters to the domain ports and assemble the runtime."""
    config = ConfigLoader(yaml_path=config_path).load()

    event_bus = AsyncEventBus()
    clock: ports.Clock = SystemClock()
    llm_provider: ports.LLMProvider = _StubLLMProvider()
    memory_repo: ports.MemoryRepo = _StubMemoryRepo()
    memory_recall: ports.MemoryRecall = _StubMemoryRecall()

    runtime = AgentRuntime()

    return Application(
        config=config,
        runtime=runtime,
        event_bus=event_bus,
        clock=clock,
        llm_provider=llm_provider,
        memory_repo=memory_repo,
        memory_recall=memory_recall,
    )


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(app: Application) -> None:
    await app.runtime.start()
    try:
        await app.runtime.run_until_stopped()
    finally:
        await app.runtime.stop()


def main(*, config_path: Path | None = None) -> None:
    """Process entrypoint: build the application and run until stopped."""
    app = build_application(config_path=config_path)
    runtime_cfg = app.config.get("runtime", {})
    level = "INFO"
    if isinstance(runtime_cfg, Mapping):
        level = str(runtime_cfg.get("log_level", "INFO"))
    _configure_logging(level)
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
