# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob

"""Composition-root entrypoint — build the application and run it until stopped.

The process entrypoint (``main`` / ``_run`` / ``_configure_logging`` + ``__main__``): it
asks the composition root to :func:`build_application`, configures logging from
``runtime.log_level``, and drives lifecycle (startup → runtime start → run-until-stopped →
shutdown). It is ``bob.runtime`` (the composition root / entrypoint), NOT
``bob.application.runtime`` (the async ``AgentRuntime`` primitives it *starts*).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from bob.runtime.composition import Application, build_application
from bob.runtime.config import _section, _str

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run(app: Application) -> None:
    await app.startup()
    await app.runtime.start()
    try:
        await app.runtime.run_until_stopped()
    finally:
        await app.shutdown()


def main(*, config_path: Path | None = None) -> None:
    """Process entrypoint: build the application and run until stopped."""
    app = build_application(config_path=config_path)
    runtime_cfg = _section(app.config, "runtime")
    _configure_logging(_str(runtime_cfg, "log_level", "INFO"))
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
