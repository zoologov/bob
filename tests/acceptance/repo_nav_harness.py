# Copyright (c) 2026 Vladimir Zoologov
# SPDX-License-Identifier: BUSL-1.1
# See the LICENSE file in the project root for full license information.

"""Repo-navigation acceptance harness (BOB-067).

Wires the REAL repo-navigation capabilities (``list_dir`` / ``find_file`` /
``read_code``) to a REAL
:class:`~bob.capabilities.adapters.introspection.subprocess_introspector.SubprocessRepoIntrospector`
over a REAL on-disk tree in a temp directory, guarded by the pure
:class:`~bob.capabilities.introspection.privacy_guard.PrivacyGuard`. The scenarios
then witness Bob's OBSERVABLE tool output — the exact text that reaches the model —
never the guard's private state. No network / subprocess is touched: list/find/read
hit the disk directly through the guard, so the injected runner is never invoked.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bob.capabilities.adapters.introspection.subprocess_introspector import (
    SubprocessRepoIntrospector,
)
from bob.capabilities.introspection.privacy_guard import PrivacyGuard
from bob.capabilities.usecases.find_file import make_find_file_capability
from bob.capabilities.usecases.list_dir import make_list_dir_capability
from bob.capabilities.usecases.read_code import make_read_code_capability

if TYPE_CHECKING:
    from pathlib import Path

    from bob.capabilities.ports import Capability

# The literal secret planted in a config file — it must NEVER survive to the output.
PLANTED_LEAK = "super-secret-telegram-token-1234567890"
# A file whose real path is unmistakable so a scenario can assert the REAL path.
GUARD_REL_PATH = "src/bob/capabilities/introspection/privacy_guard.py"


class _InertRunner:
    """A runner that must never be called by list/find/read (disk-only paths)."""

    async def __call__(self, argv: list[str], *, timeout: float) -> str:  # noqa: ARG002
        raise AssertionError("the CLI runner must not be invoked by repo navigation")


def build_repo(tmp_path: Path) -> None:
    """Materialise a small, known repo tree under ``tmp_path`` for the scenarios."""
    graph = tmp_path / ".beadloom" / "_graph"
    graph.mkdir(parents=True)
    (graph / "nodes.yml").write_text("nodes: []\n", encoding="utf-8")

    guard_file = tmp_path / GUARD_REL_PATH
    guard_file.parent.mkdir(parents=True)
    guard_file.write_text("class PrivacyGuard: ...\n", encoding="utf-8")

    config = tmp_path / "config"
    config.mkdir()
    (config / "bob.yaml").write_text(
        f"TELEGRAM_TOKEN={PLANTED_LEAK}\ntimeout: 30\n", encoding="utf-8"
    )


def build_navigator(tmp_path: Path) -> dict[str, Capability]:
    """Return the real repo-navigation capabilities wired over ``tmp_path``."""
    introspector = SubprocessRepoIntrospector(
        PrivacyGuard(tmp_path), runner=_InertRunner()
    )
    return {
        "list_dir": make_list_dir_capability(introspector),
        "find_file": make_find_file_capability(introspector),
        "read_code": make_read_code_capability(introspector),
    }
