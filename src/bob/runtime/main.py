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
from logging.handlers import RotatingFileHandler
from pathlib import Path

from bob.runtime.composition import Application, build_application
from bob.runtime.config import _int, _section, _str

logger = logging.getLogger(__name__)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# BOB-103 rotation defaults. The log grew to 2.7 GB unbounded because nothing
# rotated it; the application now owns the file with a size-capped rotating
# handler. 32 MiB × 5 backups ≈ 160 MiB ceiling — enough history to diagnose,
# bounded so it can never eat the disk. Overridable via ``runtime.log_*``.
_DEFAULT_LOG_MAX_BYTES = 32 * 1024 * 1024
_DEFAULT_LOG_BACKUP_COUNT = 5


def _configure_logging(
    level: str,
    *,
    log_file: Path | None = None,
    max_bytes: int = _DEFAULT_LOG_MAX_BYTES,
    backup_count: int = _DEFAULT_LOG_BACKUP_COUNT,
) -> None:
    """Configure root logging; own the log file with a rotating handler (BOB-103).

    With ``log_file`` set, the application TAKES OWNERSHIP of the log via a
    :class:`~logging.handlers.RotatingFileHandler` (``max_bytes`` + ``backup_count``)
    so the file rotates by size and can never grow unbounded — independent of who
    started the process (correct for a future VPS/systemd, where a shell redirect
    would not exist). The root handlers are RESET each call so a repeated
    configuration cannot leave two handlers double-writing the same file (and
    racing the rotation). With ``log_file`` unset the old stderr behaviour stands
    (tests / ad-hoc runs).
    """
    root = logging.getLogger()
    for existing in list(root.handlers):
        existing.close()
        root.removeHandler(existing)
    root.setLevel(level)
    formatter = logging.Formatter(_LOG_FORMAT)
    handler: logging.Handler
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)


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
    # BOB-103: the application owns its log file (rotating), so it no longer relies
    # on a launcher shell-redirect. ``runtime.log_file`` unset → stderr (tests /
    # ad-hoc); set (the ``./bob`` path) → a size-capped rotating handler.
    log_file_value = _str(runtime_cfg, "log_file", "")
    log_file = Path(log_file_value) if log_file_value else None
    _configure_logging(
        _str(runtime_cfg, "log_level", "INFO"),
        log_file=log_file,
        max_bytes=_int(runtime_cfg, "log_max_bytes", _DEFAULT_LOG_MAX_BYTES),
        backup_count=_int(
            runtime_cfg, "log_backup_count", _DEFAULT_LOG_BACKUP_COUNT
        ),
    )
    logger.info("Bob GUPPI starting")
    asyncio.run(_run(app))


if __name__ == "__main__":
    main()
