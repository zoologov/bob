# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

# beadloom:domain=bob
# beadloom:feature=social
# beadloom:layer=infrastructure

"""SoulStore — file-backed reader/writer for the ``data/soul/`` artifacts.

Bob's generated identity lives on disk (not in SQLite): ``SOUL.md`` (the
personality narrative), JSON profiles (``taste_profile``, ``mood``,
``phantom_prefs``), and an append-only ``genesis_log.md``. Genesis writes these
once on first awakening; the runtime reads them on every boot. The directory is
created on demand so a fresh install just works.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from bob.kernel.ports import JsonValue

logger = logging.getLogger(__name__)

__all__ = ["SoulStore"]

_SOUL_FILE = "SOUL.md"
_GENESIS_LOG_FILE = "genesis_log.md"


class SoulStore:
    """Read/write Bob's soul artifacts under a ``data/soul/`` directory."""

    def __init__(self, soul_dir: Path) -> None:
        self._dir = soul_dir

    def soul_exists(self) -> bool:
        """Whether ``SOUL.md`` has been written (Genesis-done signal on disk)."""
        return (self._dir / _SOUL_FILE).is_file()

    def write_soul(self, markdown: str) -> None:
        """Write the SOUL.md narrative, creating the directory if needed."""
        self._ensure_dir()
        (self._dir / _SOUL_FILE).write_text(markdown, encoding="utf-8")
        logger.info("SOUL.md written to %s", self._dir)

    def read_soul(self) -> str:
        """Return the SOUL.md narrative (raises ``FileNotFoundError`` if absent)."""
        return (self._dir / _SOUL_FILE).read_text(encoding="utf-8")

    def write_json(self, name: str, data: JsonValue) -> None:
        """Write a JSON artifact ``<name>.json`` (e.g. ``taste_profile``)."""
        self._ensure_dir()
        path = self._dir / f"{name}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def read_json(self, name: str) -> JsonValue:
        """Return a JSON artifact, or ``None`` if it does not exist."""
        path = self._dir / f"{name}.json"
        if not path.is_file():
            return None
        decoded: JsonValue = json.loads(path.read_text(encoding="utf-8"))
        return decoded

    def append_genesis_log(self, line: str) -> None:
        """Append a line to the append-only genesis log."""
        self._ensure_dir()
        with (self._dir / _GENESIS_LOG_FILE).open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")

    def read_genesis_log(self) -> str:
        """Return the genesis log, or empty string if none has been written."""
        path = self._dir / _GENESIS_LOG_FILE
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
